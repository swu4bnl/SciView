"""Binary mask-layer model and composition."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal, cast

import numpy as np


LayerCombineMode = Literal["AND", "OR"]

_LAYER_COMBINE_OPERATORS: dict[LayerCombineMode, Callable] = {
    "AND": np.logical_and,
    "OR": np.logical_or,
}


class MaskLayer:
    """A named binary mask and its operator relative to the preceding layer."""

    def __init__(
        self,
        data: np.ndarray,
        name: str = "Layer",
        visible: bool = True,
        *,
        combine_mode: str = "OR",
    ) -> None:
        self.data = np.asarray(data, dtype=bool)
        self.name = name
        self.visible = visible
        self.combine_mode = combine_mode
        self.source = "custom"

    @property
    def combine_mode(self) -> LayerCombineMode:
        return self._combine_mode

    @combine_mode.setter
    def combine_mode(self, value: str) -> None:
        if value not in _LAYER_COMBINE_OPERATORS:
            supported = ", ".join(_LAYER_COMBINE_OPERATORS)
            raise ValueError(f"Unsupported mask layer combine mode: {value!r}; expected {supported}")
        self._combine_mode = cast(LayerCombineMode, value)

    def __repr__(self) -> str:
        return f"MaskLayer({self.name!r}, visible={self.visible}, shape={self.data.shape})"


def compose_mask_layers(
    layers: Sequence[MaskLayer],
    *,
    replacement: tuple[int, np.ndarray] | None = None,
) -> np.ndarray | None:
    """Compose visible layers in order using each layer's incoming operator."""
    result: np.ndarray | None = None
    for index, layer in enumerate(layers):
        if not layer.visible:
            continue
        data = replacement[1] if replacement is not None and index == replacement[0] else layer.data
        data = np.asarray(data, dtype=bool)
        if result is None:
            result = data.copy()
            continue
        result = _LAYER_COMBINE_OPERATORS[layer.combine_mode](result, data)
    return result
