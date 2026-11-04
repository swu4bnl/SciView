"""Markdown-first notebook persistence with versioned, non-executable assets."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
from tempfile import NamedTemporaryFile
from uuid import uuid4
from urllib.parse import quote

import numpy as np
import yaml

from sciview.core.notebook import OBJECT_TYPES, CurveFigure, Notebook


PLOT_IMAGE = re.compile(r'!\[([^\]\n]*)\]\([^)\n]*\s+"sciview:([0-9a-f]{32})"\)')
DOCUMENT_VERSION = 1
# Version 1 manifests predate typed objects; every object in them is a curve figure.
MANIFEST_VERSIONS = (1, 2)


def _local_asset(directory: Path, relative: str) -> Path:
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Notebook asset escapes its document directory.")
    return path


def save_notebook(notebook: Notebook, path: str | Path) -> Path:
    """Commit a complete asset revision before atomically replacing the document."""
    target = Path(path).resolve()
    revision = target.parent / f"{target.stem}.assets" / uuid4().hex
    revision.mkdir(parents=True)
    temporary_path = None
    committed = False
    try:
        manifest = {"version": MANIFEST_VERSIONS[-1], "objects": {}}
        for key, scientific_object in notebook.objects.items():
            scientific_object.validate()
            if key != scientific_object.id:
                raise ValueError("Notebook object key does not match its ID.")
            if not scientific_object.preview:
                raise ValueError("A notebook object needs a preview before saving.")
            np.savez_compressed(revision / f"{key}.npz", **scientific_object.arrays())
            (revision / f"{key}.png").write_bytes(scientific_object.preview)
            manifest["objects"][key] = {"kind": scientific_object.kind, **scientific_object.record()}
        (revision / "objects.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8",
        )
        asset_directory = revision.relative_to(target.parent).as_posix()

        def image(match):
            key = match[2]
            if key not in notebook.objects:
                raise ValueError(f"Notebook refers to a missing scientific object: {key}")
            return f'![{match[1]}]({quote(asset_directory)}/{key}.png "sciview:{key}")'

        markdown = PLOT_IMAGE.sub(image, notebook.markdown)
        header = yaml.safe_dump({
            "sciview": {"version": DOCUMENT_VERSION, "manifest": f"{asset_directory}/objects.yaml"},
        }, sort_keys=False)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(f"---\n{header}---\n\n{markdown}")
        temporary_path.replace(target)
        committed = True
        notebook.path = target
        return target
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if not committed:
            shutil.rmtree(revision)


def load_notebook(path: str | Path) -> Notebook:
    """Load saved scientific objects without source images, calibration objects or processing."""
    target = Path(path).resolve()
    text = target.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return Notebook(markdown=text, path=target)
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise ValueError("Unterminated notebook metadata.")
    header = yaml.safe_load(parts[1])
    if not isinstance(header, dict) or "sciview" not in header:
        return Notebook(markdown=text, path=target)
    metadata = header["sciview"]
    if metadata["version"] != DOCUMENT_VERSION:
        raise ValueError("Unsupported notebook document version.")
    manifest_path = _local_asset(target.parent, metadata["manifest"])
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if manifest["version"] not in MANIFEST_VERSIONS:
        raise ValueError("Unsupported notebook object version.")
    notebook = Notebook(markdown=parts[2].lstrip("\n"), path=target)
    for key, record in manifest["objects"].items():
        record = dict(record)
        kind = record.pop("kind", CurveFigure.kind)
        object_type = OBJECT_TYPES.get(kind)
        if object_type is None:
            raise ValueError(f"Unsupported notebook object type: {kind}")
        with np.load(_local_asset(manifest_path.parent, f"{key}.npz"), allow_pickle=False) as saved:
            arrays = {name: saved[name] for name in saved.files}
        preview = _local_asset(manifest_path.parent, f"{key}.png").read_bytes()
        notebook.add_object(object_type.from_record(key, record, arrays, preview))
    for match in PLOT_IMAGE.finditer(notebook.markdown):
        if match[2] not in notebook.objects:
            raise ValueError(f"Notebook refers to a missing scientific object: {match[2]}")
    return notebook
