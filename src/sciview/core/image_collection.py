"""Shared, GUI-independent image collection and comparison state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

import numpy as np


class ComparisonMode(StrEnum):
    """Available ways to compare a pinned image with the active image.

    ``FLICKER`` is the default: the pinned image is shown at rest and the
    active image is revealed only while the user holds it.
    """

    FLICKER = "flicker"
    OPACITY = "opacity"
    ADD = "add"
    SPLIT = "split"
    DIFFERENCE = "difference"


COLOR_MANAGED_COMPARISON_MODES = (
    ComparisonMode.OPACITY,
    ComparisonMode.ADD,
    ComparisonMode.DIFFERENCE,
)


@dataclass
class ComparisonDisplay:
    """Display settings owned by one color-managed comparison view."""

    colormap: str
    scale: str = "linear"
    levels: tuple[float, float] | None = None


@dataclass
class ImageReference:
    """A lightweight reference to an image in an ordered collection."""

    path: str
    filename: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    size: tuple[int, ...] | None = None
    source: str = "unknown"
    lazy: bool = False
    cache_key: str = ""


@dataclass
class ImageCollection:
    """Ordered image references and the active comparison state."""

    references: list[ImageReference] = field(default_factory=list)
    current_index: int = -1
    pinned_path: str | None = None
    comparison_mode: ComparisonMode = ComparisonMode.FLICKER
    opacity: float = 0.5
    add_b_percentage: int = 100
    subtract_b_percentage: int = 100
    split_fraction: float = 0.5
    comparison_displays: dict[ComparisonMode, ComparisonDisplay] = field(
        default_factory=dict
    )

    @property
    def current_reference(self) -> ImageReference | None:
        if 0 <= self.current_index < len(self.references):
            return self.references[self.current_index]
        return None

    @property
    def pinned_reference(self) -> ImageReference | None:
        return next(
            (reference for reference in self.references if reference.path == self.pinned_path),
            None,
        )

    def add(self, reference: ImageReference) -> None:
        self.references.append(reference)
        self.current_index = len(self.references) - 1

    def select(self, index: int) -> bool:
        if not 0 <= index < len(self.references):
            return False
        self.current_index = index
        return True

    def pin_current(self) -> bool:
        reference = self.current_reference
        if reference is None:
            return False
        self.pinned_path = reference.path
        return True

    def unpin(self) -> None:
        self.pinned_path = None

    def remove(self, index: int) -> ImageReference | None:
        if not 0 <= index < len(self.references):
            return None
        removed = self.references.pop(index)
        if removed.path == self.pinned_path:
            self.unpin()
        if self.current_index >= len(self.references):
            self.current_index = len(self.references) - 1
        elif self.current_index > index:
            self.current_index -= 1
        return removed

    def clear(self) -> None:
        self.references.clear()
        self.current_index = -1
        self.unpin()

    def set_opacity(self, value: float) -> None:
        if not np.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("Opacity must be between 0 and 1.")
        self.opacity = float(value)

    def set_add_b_percentage(self, value: int) -> None:
        self.add_b_percentage = _validated_percentage(value)

    def set_subtract_b_percentage(self, value: int) -> None:
        self.subtract_b_percentage = _validated_percentage(value)

    def set_split_fraction(self, value: float) -> None:
        if not np.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("Split fraction must be between 0 and 1.")
        self.split_fraction = float(value)

    def set_comparison_display(
        self,
        mode: ComparisonMode,
        display: ComparisonDisplay,
    ) -> None:
        """Store display settings for a color-managed comparison mode."""
        if mode not in COLOR_MANAGED_COMPARISON_MODES:
            raise ValueError(f"{mode!r} does not own comparison display settings.")
        if display.levels is not None:
            vmin, vmax = display.levels
            if not (np.isfinite(vmin) and np.isfinite(vmax) and vmax > vmin):
                raise ValueError("Display limits must be finite and increasing.")
            display.levels = (float(vmin), float(vmax))
        if mode == ComparisonMode.DIFFERENCE:
            if display.scale != "linear":
                raise ValueError("Signed differences must use a linear scale.")
            if display.levels is not None and display.levels[0] != -display.levels[1]:
                raise ValueError("Difference limits must be centered on zero.")
        self.comparison_displays[mode] = display


def _validated_percentage(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError("B contribution must be an integer percentage from 0 to 100.")
    return value


def compare_image_arrays(
    reference: np.ndarray,
    current: np.ndarray,
    mode: ComparisonMode,
    *,
    opacity: float = 0.5,
    current_weight: float = 1.0,
    split_fraction: float = 0.5,
) -> np.ndarray:
    """Combine compatible numeric 2D arrays for image comparison."""
    reference_array = np.asarray(reference)
    current_array = np.asarray(current)
    if (
        reference_array.ndim != 2
        or current_array.ndim != 2
        or reference_array.shape != current_array.shape
    ):
        raise ValueError("Images must have matching two-dimensional shapes.")
    if (
        not np.issubdtype(reference_array.dtype, np.number)
        or not np.issubdtype(current_array.dtype, np.number)
        or np.issubdtype(reference_array.dtype, np.complexfloating)
        or np.issubdtype(current_array.dtype, np.complexfloating)
    ):
        raise ValueError("Images must contain real numeric data.")

    if mode == ComparisonMode.OPACITY:
        if not np.isfinite(opacity) or not 0.0 <= opacity <= 1.0:
            raise ValueError("Opacity must be between 0 and 1.")
        return (
            np.asarray(reference_array, dtype=np.float64) * (1.0 - opacity)
            + np.asarray(current_array, dtype=np.float64) * opacity
        )
    if mode in (ComparisonMode.ADD, ComparisonMode.DIFFERENCE):
        if not np.isfinite(current_weight) or not 0.0 <= current_weight <= 1.0:
            raise ValueError("B contribution must be between 0 and 1.")
    if mode == ComparisonMode.ADD:
        return (
            np.asarray(reference_array, dtype=np.float64)
            + np.asarray(current_array, dtype=np.float64) * current_weight
        )
    if mode == ComparisonMode.SPLIT:
        if not np.isfinite(split_fraction) or not 0.0 <= split_fraction <= 1.0:
            raise ValueError("Split fraction must be between 0 and 1.")
        boundary = int(round(reference_array.shape[1] * split_fraction))
        combined = np.array(reference_array, copy=True)
        combined[:, boundary:] = current_array[:, boundary:]
        return combined
    if mode == ComparisonMode.DIFFERENCE:
        return (
            np.asarray(reference_array, dtype=np.float64)
            - np.asarray(current_array, dtype=np.float64) * current_weight
        )
    raise ValueError(f"Unsupported numerical comparison mode: {mode!r}")
