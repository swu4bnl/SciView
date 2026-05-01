"""Image/data access service for GUI frontends."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from sciview.data.models import Dataset, ImageRef
from sciview.sources.filesystem_source import open_dataset, resolve_local_path, scan_directory


class ImageService:
    """Backend-backed service used by interface layers for image IO."""

    def scan_local_directory(self, directory: str | Path, *, recursive: bool = False) -> list[ImageRef]:
        return scan_directory(directory, recursive=recursive)

    def open_local_dataset(self, directory: str | Path, *, recursive: bool = False) -> Dataset:
        return open_dataset(directory, recursive=recursive)

    def load_array(self, image_ref: ImageRef) -> np.ndarray:
        path = resolve_local_path(image_ref)
        suffix = path.suffix.lower()
        if suffix == ".npy":
            return np.asarray(np.load(path))
        if suffix in {".tif", ".tiff", ".png", ".jpg", ".jpeg"}:
            with Image.open(path) as img:
                return np.asarray(img)

        raise ValueError(f"Unsupported image format for array load: {suffix}")