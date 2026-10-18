"""Context-rich source messages and Qt translation at the presentation boundary."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from string import Formatter
from types import MappingProxyType
from typing import Mapping

import yaml
from PyQt5.QtCore import QCoreApplication

SOURCE_LOCALE = "en-US"
_LOCALE_ROOT = ("locales",)
_DEVELOPER_LOCALE_ENV = "SCIVIEW_DEV_LOCALE"


@dataclass(frozen=True)
class Message:
    """An English source message with translator guidance."""

    text: str
    context: str
    placeholders: Mapping[str, str]


class _CatalogLoader(yaml.SafeLoader):
    """Reject duplicate IDs instead of silently replacing source messages."""


def _unique_mapping(loader: _CatalogLoader, node: yaml.MappingNode) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f"Duplicate message catalog key: {key}")
        result[key] = loader.construct_object(value_node)
    return result


_CatalogLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def _fields(template: str) -> set[str]:
    fields = set()
    for _, field, spec, _ in Formatter().parse(template):
        if field is not None:
            if not field.isidentifier():
                raise ValueError(f"Message placeholders must be named fields: {field!r}")
            fields.add(field)
            fields.update(_fields(spec))
    return fields


@lru_cache(maxsize=None)
def _catalog(domain: str, locale: str = SOURCE_LOCALE) -> Mapping[str, Message]:
    if not domain.isidentifier():
        raise ValueError(f"Invalid message domain: {domain!r}")
    resource = files("sciview.interfaces").joinpath(
        *_LOCALE_ROOT, locale, f"{domain}.yaml"
    )
    raw = yaml.load(resource.read_text(encoding="utf-8"), Loader=_CatalogLoader)
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"Empty or invalid message catalog: {domain}")
    messages = {}
    for message_id, entry in raw.items():
        if not isinstance(message_id, str) or not message_id.startswith(f"{domain}."):
            raise ValueError(f"Invalid message ID in {domain}: {message_id!r}")
        if not isinstance(entry, dict) or set(entry) - {"text", "context", "placeholders"}:
            raise ValueError(f"Invalid message entry: {message_id}")
        text, context = entry.get("text"), entry.get("context")
        placeholders = entry.get("placeholders", {})
        if not isinstance(text, str) or not isinstance(context, str) or not context.strip():
            raise ValueError(f"Message requires source text and translator context: {message_id}")
        if not isinstance(placeholders, dict) or any(
            not isinstance(name, str) or not isinstance(description, str) or not description.strip()
            for name, description in placeholders.items()
        ):
            raise ValueError(f"Invalid placeholder descriptions: {message_id}")
        if _fields(text) != set(placeholders):
            raise ValueError(f"Placeholder descriptions do not match source text: {message_id}")
        messages[message_id] = Message(text, context, MappingProxyType(placeholders))
    if locale != SOURCE_LOCALE:
        source = _catalog(domain)
        if messages.keys() != source.keys():
            raise ValueError(f"Locale catalog IDs do not match en-US: {domain} ({locale})")
        for message_id, message in messages.items():
            source_message = source[message_id]
            if (
                message.context != source_message.context
                or message.placeholders != source_message.placeholders
            ):
                raise ValueError(f"Locale catalog metadata does not match en-US: {message_id} ({locale})")
    return MappingProxyType(messages)


def source_messages() -> Mapping[str, Message]:
    """Return validated en-US source messages for review and translation tooling."""
    messages = {}
    resources = files("sciview.interfaces").joinpath(*_LOCALE_ROOT, SOURCE_LOCALE)
    for resource in sorted(resources.iterdir(), key=lambda item: item.name):
        if resource.name.endswith(".yaml"):
            messages.update(_catalog(resource.name[:-5]))
    return MappingProxyType(messages)


@lru_cache(maxsize=None)
def _validate_locale(locale: str) -> str:
    if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Z]{2})?", locale):
        raise ValueError(f"Invalid value for {_DEVELOPER_LOCALE_ENV}: {locale!r}")
    if not files("sciview.interfaces").joinpath(*_LOCALE_ROOT, locale).is_dir():
        raise ValueError(f"No message catalog is available for locale {locale!r}")
    return locale


def developer_locale() -> str:
    """Return the validated locale selected for developer-only UI checks."""
    return _validate_locale(os.environ.get(_DEVELOPER_LOCALE_ENV, SOURCE_LOCALE))


def tr(message_id: str, **values: object) -> str:
    """Translate a catalog message using installed Qt translators, then format it."""
    domain, separator, _ = message_id.partition(".")
    if not separator:
        raise ValueError(f"Message ID must include a domain: {message_id!r}")
    locale = developer_locale()
    message = _catalog(domain, locale)[message_id]
    if set(values) != set(message.placeholders):
        raise ValueError(f"Incorrect placeholders for {message_id}: {sorted(values)}")
    translated = message.text if locale != SOURCE_LOCALE else QCoreApplication.translate(
        "SciView", message.text, message_id
    )
    if _fields(translated) != set(message.placeholders):
        raise ValueError(f"Translation changed placeholders for {message_id}")
    return translated.format_map(values)
