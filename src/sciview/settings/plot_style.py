"""Shared plot styling for interactive previews and SciAnalysis exports."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import asdict, dataclass, fields, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class PlotStyle:
    """Serializable plotting choices shared by preview and batch workflows."""

    title_size: float = 25.0
    label_size: float = 40.0
    tick_size: float = 25.0
    colormap: str = "viridis"
    line_color: str = "#808080"
    line_width: float = 3.0
    ztrim_low: float = 0.05
    ztrim_high: float = 0.005
    dpi: int = 300

    def __post_init__(self) -> None:
        if min(self.title_size, self.label_size, self.tick_size, self.line_width) <= 0:
            raise ValueError("Font sizes and line width must be positive")
        if not self.colormap.strip():
            raise ValueError("Colormap is required")
        if not self.line_color.strip():
            raise ValueError("Line color is required")
        if not 0 <= self.ztrim_low < 1 or not 0 <= self.ztrim_high < 1:
            raise ValueError("Z-trim values must be between 0 and 1")
        if self.ztrim_low + self.ztrim_high >= 1:
            raise ValueError("Combined Z-trim must be less than 1")
        if self.dpi <= 0:
            raise ValueError("DPI must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "PlotStyle":
        if not payload:
            return cls()
        defaults = cls()
        values = {
            field: payload.get(field, getattr(defaults, field))
            for field in defaults.to_dict()
        }
        return cls(**values)

    def scianalysis_args(self, *, image: bool) -> dict[str, Any]:
        args: dict[str, Any] = {
            "rcParams": {
                "axes.titlesize": self.title_size,
                "axes.labelsize": self.label_size,
                "xtick.labelsize": self.tick_size,
                "ytick.labelsize": self.tick_size,
            },
            "dpi": self.dpi,
            "sciview_title_size": self.title_size,
        }
        if image:
            args.update({
                "cmap": self.colormap,
                "ztrim": [self.ztrim_low, self.ztrim_high],
            })
        else:
            args.update({
                "color": self.line_color,
                "linewidth": self.line_width,
            })
        return args

    def preview_sizes(self) -> dict[str, float]:
        """Scale export typography to a compact interactive canvas."""
        return {
            "title": max(6.0, self.title_size * 0.4),
            "label": max(6.0, self.label_size * 0.4),
            "tick": max(6.0, self.tick_size * 0.4),
        }

    def preview_percentiles(self) -> tuple[float, float]:
        """Return z-trim as lower and upper percentiles for preview images."""
        return self.ztrim_low * 100.0, (1.0 - self.ztrim_high) * 100.0


DEFAULT_PLOT_STYLE = PlotStyle()


@dataclass(frozen=True, slots=True)
class AppearanceSettings(PlotStyle):
    """Canonical live image and plot settings; exports use PlotStyle snapshots."""

    colormap: str = "gray"
    scale: str = "linear"
    vmin: float | None = -2
    vmax: float | None = 1000
    show_beam_center: bool = True
    show_mask: bool = True

    def plot_snapshot(self) -> PlotStyle:
        return PlotStyle(**{
            item.name: getattr(self, item.name) for item in fields(PlotStyle)
        })


class ImageDisplaySettings(MutableMapping[str, Any]):
    """Legacy image-control/session mapping backed by the shared settings owner."""

    _fields = {
        "cmap": "colormap",
        "scale": "scale",
        "vmin": "vmin",
        "vmax": "vmax",
        "show_beam_center": "show_beam_center",
        "show_mask": "show_mask",
    }

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    @classmethod
    def snapshot(cls, settings: AppearanceSettings) -> dict[str, Any]:
        return {key: getattr(settings, field) for key, field in cls._fields.items()}

    def __getitem__(self, key: str) -> Any:
        return getattr(self._owner.appearance_settings, self._fields[key])

    def __setitem__(self, key: str, value: Any) -> None:
        self.update({key: value})

    def __delitem__(self, key: str) -> None:
        raise TypeError("Shared display settings cannot be deleted")

    def __iter__(self) -> Iterator[str]:
        return iter(self._fields)

    def __len__(self) -> int:
        return len(self._fields)

    def update(self, *args: Any, **kwargs: Any) -> None:
        values = dict(*args, **kwargs)
        self._owner.appearance_settings = replace(
            self._owner.appearance_settings,
            **{self._fields[key]: value for key, value in values.items()},
        )


def resolve_plot_style(owner: Any) -> PlotStyle:
    """Return an owner's shared style, accepting either model or mapping."""
    value = getattr(owner, "plot_style", None)
    if isinstance(value, PlotStyle):
        return value
    if isinstance(value, dict):
        return PlotStyle.from_dict(value)
    return DEFAULT_PLOT_STYLE