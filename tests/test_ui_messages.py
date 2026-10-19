"""Contracts for the shared presentation-text catalog and translation boundary."""

import ast
import os
import warnings
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
from PyQt5.QtCore import QTranslator
from PyQt5.QtGui import QFont, QFontDatabase, QFontMetrics
from PyQt5.QtWidgets import QApplication

from sciview.interfaces.export_translations import export_ts
from sciview.interfaces.theme.app_style import AppStyle
from sciview.interfaces.text import SOURCE_LOCALE, source_messages, tr

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def use_source_locale_by_default(monkeypatch):
    monkeypatch.delenv("SCIVIEW_DEV_LOCALE", raising=False)


def test_source_catalog_has_context_and_valid_formatting():
    locale_catalogs = files("sciview.interfaces").joinpath("locales", SOURCE_LOCALE)
    assert locale_catalogs.is_dir()
    messages = source_messages()
    assert messages
    for message_id, message in messages.items():
        assert message.context.strip(), message_id
        assert all(description.strip() for description in message.placeholders.values())
        # A number supports all existing numeric format specifications, while
        # nonnumeric placeholders can also display it without type restrictions.
        result = tr(message_id, **{field: 2 for field in message.placeholders})
        assert isinstance(result, str)


def test_lookup_rejects_unknown_ids_and_incorrect_placeholders():
    with pytest.raises(KeyError):
        tr("viewer.missing_message")
    with pytest.raises(ValueError, match="placeholders"):
        tr("viewer.pan.label", unexpected="value")


def test_developer_locale_override_uses_zh_cn_catalog(monkeypatch):
    monkeypatch.setenv("SCIVIEW_DEV_LOCALE", "zh-CN")

    assert tr("viewer.pan.label") == "平移"
    assert (
        tr("base_image.could_not_initialize_the_calibration_error", error="details")
        == "无法初始化校准：details"
    )


def test_developer_locale_override_rejects_unavailable_catalog(monkeypatch):
    monkeypatch.setenv("SCIVIEW_DEV_LOCALE", "es")

    with pytest.raises(ValueError, match="No message catalog"):
        tr("viewer.pan.label")


def test_bundled_fonts_render_chinese_and_scientific_labels(qapp, caplog, monkeypatch):
    from matplotlib import font_manager, rcParams
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    original_font = qapp.font()
    original_family = list(rcParams["font.family"])
    original_sans_serif = list(rcParams["font.sans-serif"])
    try:
        monkeypatch.setattr(font_manager.fontManager, "ttflist", [])
        font_manager.fontManager._findfont_cached.cache_clear()
        AppStyle.apply_bundled_fonts(qapp)
        installed = {family.casefold() for family in QFontDatabase().families()}
        assert {"source sans 3", "noto sans cjk sc"} <= installed
        assert AppStyle.effective_font_family(qapp) == "Source Sans 3"
        assert qapp.font().families() == ["Source Sans 3", "Noto Sans CJK SC"]
        assert qapp.font().styleHint() == QFont.SansSerif
        metrics = QFontMetrics(qapp.font())
        assert all(metrics.inFontUcs4(ord(char)) for char in "Q (Å⁻¹) 水平垂直 αβγ ± × −")
        assert rcParams["font.family"] == ["Source Sans 3", "Noto Sans CJK SC"]
        font_root = Path(str(files("sciview.interfaces").joinpath("fonts"))).resolve()
        for family in ("Source Sans 3", "Noto Sans CJK SC"):
            for weight in ("normal", "bold"):
                path = Path(font_manager.findfont(
                    font_manager.FontProperties(family=family, weight=weight),
                    fallback_to_default=False,
                )).resolve()
                assert path.is_relative_to(font_root)
                assert (path.parent / "LICENSE.txt").is_file()
        figure = Figure()
        FigureCanvasAgg(figure)
        axis = figure.subplots()
        axis.set_xlabel("Q (Å⁻¹) 水平垂直 αβγ ± × −")
        axis.set_title("科学图像", fontweight="bold")
        with caplog.at_level("WARNING", logger="matplotlib.font_manager"):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                figure.canvas.draw()
        assert not [
            warning
            for warning in caught
            if "Glyph" in str(warning.message) or "findfont" in str(warning.message)
        ]
        assert not [
            record
            for record in caplog.records
            if record.name == "matplotlib.font_manager"
            and "Font family" in record.message and "not found" in record.message
        ]
        registered = len(font_manager.fontManager.ttflist)
        AppStyle.apply_bundled_fonts(qapp)
        assert len(font_manager.fontManager.ttflist) == registered
    finally:
        qapp.setFont(original_font)
        rcParams["font.family"] = original_family
        rcParams["font.sans-serif"] = original_sans_serif


def test_literal_message_references_resolve_with_declared_placeholders():
    root = Path(__file__).resolve().parents[1]
    paths = [root / "main.py", *root.joinpath("tabs").glob("*.py")]
    paths.extend(root.joinpath("src", "sciview").rglob("*.py"))
    messages = source_messages()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue
            message_id = node.args[0].value
            assert message_id in messages, (path, node.lineno, message_id)
            if all(keyword.arg is not None for keyword in node.keywords):
                assert {keyword.arg for keyword in node.keywords} == set(
                    messages[message_id].placeholders
                ), (path, node.lineno, message_id)


def test_qt_translation_uses_semantic_id_and_formats_after_translation(qapp):
    messages = source_messages()
    message_id = next(key for key, entry in messages.items() if entry.placeholders)
    entry = messages[message_id]

    class TestTranslator(QTranslator):
        def translate(self, context, source, disambiguation=None, n=-1):
            if context == "SciView" and disambiguation == message_id:
                return "translated " + source
            return ""

        def isEmpty(self):
            return False

    translator = TestTranslator()
    qapp.installTranslator(translator)
    try:
        values = {field: 2 for field in entry.placeholders}
        assert tr(message_id, **values) == "translated " + entry.text.format_map(values)
    finally:
        qapp.removeTranslator(translator)


def test_translated_display_scale_keeps_canonical_scientific_setting(qapp):
    from sciview.settings.app_settings import DEFAULT_DISPLAY_SETTINGS
    from tabs.base_image_tab import BaseImageTab

    class ScaleTranslator(QTranslator):
        def translate(self, context, source, disambiguation=None, n=-1):
            if context == "SciView" and disambiguation and disambiguation.startswith("base_image.scale."):
                return "translated " + source
            return ""

        def isEmpty(self):
            return False

    translator = ScaleTranslator()
    qapp.installTranslator(translator)
    tab = BaseImageTab(SimpleNamespace(display_settings=DEFAULT_DISPLAY_SETTINGS.copy()))
    panel = tab._create_image_panel()
    try:
        combo = tab.img_scale_combo
        combo.setCurrentIndex(combo.findData("log"))
        assert combo.currentText() != "log"
        assert tab.display_settings["scale"] == "log"
        tab.sync_display_controls()
        assert combo.currentData() == "log"
    finally:
        panel.close()
        tab.close()
        qapp.removeTranslator(translator)


def test_export_preserves_context_ids_and_placeholder_notes(tmp_path: Path):
    destination = tmp_path / "sciview_fr.ts"
    export_ts(destination, "fr_FR")
    root = ET.parse(destination).getroot()
    assert root.attrib["language"] == "fr_FR"
    assert root.attrib["sourcelanguage"] == SOURCE_LOCALE.replace("-", "_")
    exported = {
        message.findtext("comment"): message
        for message in root.findall("./context/message")
    }
    messages = source_messages()
    assert exported.keys() == messages.keys()
    for message_id, entry in messages.items():
        message = exported[message_id]
        assert message.findtext("source") == entry.text
        assert entry.context in message.findtext("extracomment")
        for field in entry.placeholders:
            assert "{" + field + "}" in message.findtext("extracomment")
    original = destination.read_bytes()
    with pytest.raises(FileExistsError):
        export_ts(destination, "de_DE")
    assert destination.read_bytes() == original
