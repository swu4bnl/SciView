"""Beamline-neutral local file-system source adapter."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from sciview.data.models import Dataset, ImageRef


DEFAULT_IMAGE_EXTENSIONS: tuple[str, ...] = (".tif", ".tiff", ".h5", ".hdf5", ".dat")


def _normalize_directory(directory: str | Path) -> Path:
    normalized = directory if isinstance(directory, Path) else Path(directory)
    resolved = normalized.expanduser().resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"Directory does not exist: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {resolved}")

    return resolved


def _normalize_extensions(extensions: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if extensions is None:
        return DEFAULT_IMAGE_EXTENSIONS

    normalized: list[str] = []
    for suffix in extensions:
        suffix_text = suffix.lower()
        normalized.append(suffix_text if suffix_text.startswith(".") else f".{suffix_text}")
    return tuple(normalized)


def _iter_candidate_files(directory: Path, recursive: bool) -> list[Path]:
    iterator = directory.rglob("*") if recursive else directory.iterdir()
    return sorted(path for path in iterator if path.is_file())


def _image_ref_from_path(file_path: Path) -> ImageRef:
    resolved = file_path.resolve()
    stat = resolved.stat()
    return ImageRef(
        source_uri=resolved.as_uri(),
        source_type="file",
        local_path=resolved,
        metadata={
            "filename": resolved.name,
            "suffix": resolved.suffix.lower(),
            "size_bytes": stat.st_size,
        },
    )


def scan_directory(
    directory: str | Path,
    *,
    extensions: tuple[str, ...] | list[str] | None = None,
    recursive: bool = False,
) -> list[ImageRef]:
    """List supported image-like files in a directory as ImageRef objects."""

    resolved_directory = _normalize_directory(directory)
    allowed_suffixes = set(_normalize_extensions(extensions))

    image_refs: list[ImageRef] = []
    for file_path in _iter_candidate_files(resolved_directory, recursive=recursive):
        if file_path.suffix.lower() not in allowed_suffixes:
            continue
        image_refs.append(_image_ref_from_path(file_path))

    return image_refs


def open_dataset(
    directory: str | Path,
    *,
    name: str | None = None,
    extensions: tuple[str, ...] | list[str] | None = None,
    recursive: bool = False,
) -> Dataset:
    """Create a Dataset from a local directory without beamline-specific assumptions."""

    resolved_directory = _normalize_directory(directory)
    images = scan_directory(resolved_directory, extensions=extensions, recursive=recursive)
    dataset_name = name or resolved_directory.name
    return Dataset(
        name=dataset_name,
        images=images,
        metadata={
            "source_type": "filesystem",
            "root": str(resolved_directory),
            "recursive": recursive,
        },
    )


def _path_from_file_uri(source_uri: str) -> Path:
    parsed = urlparse(source_uri)
    if parsed.scheme != "file":
        raise ValueError(f"Unsupported source URI scheme: {parsed.scheme or '<empty>'}")

    if parsed.netloc and parsed.path:
        uri_path = f"//{parsed.netloc}{parsed.path}"
    else:
        uri_path = parsed.netloc or parsed.path

    return Path(url2pathname(unquote(uri_path))).resolve()


def resolve_local_path(image_ref: ImageRef) -> Path:
    """Resolve an ImageRef to a local path for file-backed processing."""

    if image_ref.local_path is not None:
        return image_ref.local_path.resolve()

    if image_ref.source_type != "file":
        raise ValueError(f"ImageRef is not file-backed: {image_ref.source_type}")

    return _path_from_file_uri(image_ref.source_uri)


def read_bytes(image_ref: ImageRef) -> bytes:
    """Read file bytes for a file-backed image reference."""

    return resolve_local_path(image_ref).read_bytes()