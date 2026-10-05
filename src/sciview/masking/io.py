"""Mask IO helpers decoupled from GUI state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def coerce_mask_to_bool(
    mask: Any,
    shape: tuple[int, int] | None = None,
) -> np.ndarray | None:
    """Convert any mask representation to a bool ndarray where True = masked pixel.

    Handles SA Mask objects (mask.data: 1=valid, 0=masked) and numpy arrays.
    Returns None when mask is None or the shape doesn't match.
    """
    if mask is None:
        return None
    if hasattr(mask, "data") and not isinstance(mask, np.ndarray):
        raw = np.asarray(mask.data)
        result = (raw <= 0).astype(bool)  # SA: 0=masked → True=masked
    else:
        raw = np.asarray(mask)
        result = raw.astype(bool)
    if shape is not None and result.shape != shape:
        return None
    return result


def load_mask_file(file_path: str | Path) -> np.ndarray:
    """Load a mask from .npy or image files and return a boolean mask array."""

    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".npy":
        data = np.load(path)
    elif suffix == ".xcf":
        raise ValueError("Cannot read XCF directly. Export from GIMP as PNG/TIFF first.")
    else:
        from PIL import Image
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

    from PIL import Image
    img_array = (np.invert(mask_data.astype(bool)).astype(np.uint8) * 255)
    Image.fromarray(img_array, mode="L").save(path)
    return path