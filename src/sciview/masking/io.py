"""Mask IO helpers decoupled from GUI state."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def load_mask_file(file_path: str | Path) -> np.ndarray:
    """Load a mask from .npy or image files and return a boolean mask array."""

    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".npy":
        data = np.load(path)
    elif suffix == ".xcf":
        raise ValueError("Cannot read XCF directly. Export from GIMP as PNG/TIFF first.")
    else:
        data = np.array(Image.open(path))

    if data.dtype == bool:
        return data
    if data.ndim > 2:
        data = data[:, :, 0]

    return data == 0


def export_mask_file(mask_data: np.ndarray, file_path: str | Path) -> Path:
    """Export mask data to .npy or grayscale image formats."""

    path = Path(file_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()

    if suffix == ".npy":
        np.save(path, mask_data)
        return path

    if suffix not in {".png", ".tif", ".tiff"}:
        raise ValueError(f"Unsupported mask export format: {suffix or '<none>'}")

    img_array = (np.invert(mask_data.astype(bool)).astype(np.uint8) * 255)
    Image.fromarray(img_array, mode="L").save(path)
    return path