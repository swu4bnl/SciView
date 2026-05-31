"""Mask processing helpers for morphology, edges, and seeded fills."""

from __future__ import annotations

from typing import Tuple

import numpy as np
from scipy import ndimage


def _disk_structure(radius: int) -> np.ndarray:
    """Return a disk-like boolean structuring element for morphology."""
    safe_radius = max(1, int(radius))
    yy, xx = np.ogrid[-safe_radius : safe_radius + 1, -safe_radius : safe_radius + 1]
    return (xx * xx + yy * yy) <= safe_radius * safe_radius


def erode_mask(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    """Shrink masked regions to remove small speckles and jagged artifacts."""
    return ndimage.binary_erosion(mask.astype(bool), structure=_disk_structure(radius))


def dilate_mask(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    """Expand masked regions to bridge small gaps."""
    return ndimage.binary_dilation(mask.astype(bool), structure=_disk_structure(radius))


def close_mask_holes(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    """Close small holes and narrow gaps inside a mask."""
    structure = _disk_structure(radius)
    closed = ndimage.binary_closing(mask.astype(bool), structure=structure)
    return ndimage.binary_fill_holes(closed)


def sobel_edge_mask(image: np.ndarray, percentile: float = 92.0, smooth_sigma: float = 0.0) -> np.ndarray:
    """Detect edges in all directions using Sobel gradients."""
    image_array = np.asarray(image, dtype=float)
    if smooth_sigma > 0:
        image_array = ndimage.gaussian_filter(image_array, sigma=smooth_sigma)

    grad_x = ndimage.sobel(image_array, axis=1, mode="reflect")
    grad_y = ndimage.sobel(image_array, axis=0, mode="reflect")
    magnitude = np.hypot(grad_x, grad_y)

    finite = magnitude[np.isfinite(magnitude)]
    if finite.size == 0:
        return np.zeros_like(image_array, dtype=bool)

    threshold = float(np.percentile(finite, np.clip(percentile, 0.0, 100.0)))
    return magnitude >= threshold


def watershed_fill_mask(
    image: np.ndarray,
    seed_point: Tuple[int, int],
    seed_radius: int = 1,
    edge_strength: float = 92.0,
) -> np.ndarray:
    """Fill a region from a seed point using image-gradient-constrained watershed."""
    image_array = np.asarray(image, dtype=float)
    if image_array.ndim != 2:
        raise ValueError("watershed_fill_mask requires a 2D image")

    row, col = int(seed_point[0]), int(seed_point[1])
    height, width = image_array.shape
    row = max(0, min(height - 1, row))
    col = max(0, min(width - 1, col))

    smoothed = ndimage.gaussian_filter(image_array, sigma=max(0.0, seed_radius / 2.0))
    grad_x = ndimage.sobel(smoothed, axis=1, mode="reflect")
    grad_y = ndimage.sobel(smoothed, axis=0, mode="reflect")
    magnitude = np.hypot(grad_x, grad_y)

    finite = magnitude[np.isfinite(magnitude)]
    if finite.size == 0:
        return np.zeros_like(image_array, dtype=bool)

    cutoff = float(np.percentile(finite, np.clip(edge_strength, 0.0, 100.0)))
    clipped = np.minimum(magnitude, cutoff) if cutoff > 0 else magnitude
    scaled = clipped - float(np.min(clipped))
    peak = float(np.max(scaled))
    if peak > 0:
        scaled = scaled / peak
    gradient_uint8 = np.clip(np.round(scaled * 255.0), 0, 255).astype(np.uint8)

    markers = np.zeros_like(gradient_uint8, dtype=np.int32)
    markers[0, :] = 2
    markers[-1, :] = 2
    markers[:, 0] = 2
    markers[:, -1] = 2

    seed_structure = _disk_structure(seed_radius)
    radius = max(1, int(seed_radius))
    row_min = max(0, row - radius)
    row_max = min(height, row + radius + 1)
    col_min = max(0, col - radius)
    col_max = min(width, col + radius + 1)

    seed_row_min = row_min - (row - radius)
    seed_row_max = seed_row_min + (row_max - row_min)
    seed_col_min = col_min - (col - radius)
    seed_col_max = seed_col_min + (col_max - col_min)
    seed_mask = seed_structure[seed_row_min:seed_row_max, seed_col_min:seed_col_max]
    markers[row_min:row_max, col_min:col_max][seed_mask] = 1

    labels = ndimage.watershed_ift(gradient_uint8, markers)
    return labels == 1