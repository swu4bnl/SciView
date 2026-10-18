"""Export the source catalog, including translator guidance, to a Qt TS file."""

from __future__ import annotations

import argparse
from pathlib import Path
from xml.etree import ElementTree as ET

from sciview.interfaces.text import SOURCE_LOCALE, source_messages


def export_ts(destination: Path, language: str) -> None:
    """Write an untranslated Qt Linguist catalog for a target language."""
    if not language.strip():
        raise ValueError("A target language code is required")
    root = ET.Element(
        "TS",
        version="2.1",
        sourcelanguage=SOURCE_LOCALE.replace("-", "_"),
        language=language,
    )
    context = ET.SubElement(root, "context")
    ET.SubElement(context, "name").text = "SciView"
    for message_id, entry in sorted(source_messages().items()):
        message = ET.SubElement(context, "message")
        ET.SubElement(message, "source").text = entry.text
        ET.SubElement(message, "comment").text = message_id
        notes = [entry.context]
        notes.extend(f"{{{name}}}: {description}" for name, description in entry.placeholders.items())
        ET.SubElement(message, "extracomment").text = "\n".join(notes)
        ET.SubElement(message, "translation", type="unfinished")
    ET.indent(root)
    with destination.open("xb") as handle:
        ET.ElementTree(root).write(handle, encoding="utf-8", xml_declaration=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="Output .ts file")
    parser.add_argument("--language", required=True, help="Qt locale code, such as fr_FR")
    args = parser.parse_args()
    export_ts(args.destination, args.language)


if __name__ == "__main__":
    main()
