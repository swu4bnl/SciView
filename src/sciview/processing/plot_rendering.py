"""Shared renderers for interactive previews and WYSIWYG batch plots."""

from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.colors import LogNorm

from sciview.settings.plot_style import PlotStyle
from sciview.settings.viewer_config import resolve_matplotlib_colormap
from sciview.processing.scientific_labels import INTENSITY, scientific_plot_title


REDUCTION_FIGURE_SIZE = (6.0, 4.0)
TRANSFORM_FIGURE_SIZE = (6.0, 8.0)


def create_transform_axes(figure):
    """Create a centered image axis with symmetric space around its colorbar."""
    figure.clear()
    figure.set_layout_engine(None)
    axis = figure.add_axes([0.14, 0.10, 0.72, 0.82])
    colorbar_axis = figure.add_axes([0.885, 0.10, 0.025, 0.82])
    return axis, colorbar_axis


def apply_plot_theme(figure, colors: dict[str, str] | None) -> None:
    if not colors:
        return
    text_color = colors.get("text", "#000000")
    base_color = colors.get("base", "#ffffff")
    window_color = colors.get("window", "#ffffff")
    grid_color = colors.get("grid", "#808080")
    figure.patch.set_facecolor(window_color)
    axes = list(figure.axes)
    for parent_axis in figure.axes:
        axes.extend(parent_axis.child_axes)
    for axis in axes:
        axis.set_facecolor(base_color)
        axis.title.set_color(text_color)
        axis.xaxis.label.set_color(text_color)
        axis.yaxis.label.set_color(text_color)
        axis.xaxis.get_offset_text().set_color(text_color)
        axis.yaxis.get_offset_text().set_color(text_color)
        axis.tick_params(colors=text_color, labelcolor=text_color)
        for spine in axis.spines.values():
            spine.set_color(grid_color)
        for line in axis.get_xgridlines() + axis.get_ygridlines():
            line.set_color(grid_color)
            line.set_alpha(0.35)


def render_reduction_plot(
    figure,
    axis,
    result: Any,
    style: PlotStyle,
    *,
    scale: str = "linear",
    x_limits: tuple[float, float] | None = None,
    theme: dict[str, str] | None = None,
) -> None:
    axis.clear()
    sizes = style.preview_sizes()
    axis.plot(result.x, result.y, color=style.line_color, linewidth=style.line_width)
    axis.set_xscale("log" if scale in ("logx", "loglog") else "linear")
    axis.set_yscale("log" if scale in ("logy", "loglog") else "linear")
    axis.set_xlabel(result.x_label, fontsize=sizes["label"])
    axis.set_ylabel(result.y_label, fontsize=sizes["label"])
    axis.set_title(scientific_plot_title(result.operation), fontsize=sizes["title"])
    axis.tick_params(labelsize=sizes["tick"])
    axis.grid(True, alpha=0.2)
    axis.set_axis_on()
    if x_limits is not None and not (scale in ("logx", "loglog") and x_limits[0] <= 0):
        axis.set_xlim(*x_limits)
    apply_plot_theme(figure, theme)


def render_transform_plot(
    figure,
    axis,
    result: Any,
    style: PlotStyle,
    *,
    colorbar_axis=None,
    scale: str = "linear",
    vmin: float | None = None,
    vmax: float | None = None,
    x_limits: tuple[float, float] | None = None,
    y_limits: tuple[float, float] | None = None,
    theme: dict[str, str] | None = None,
):
    axis.clear()
    image = np.asarray(result.image, dtype=float)
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        raise ValueError("No finite transform values")

    extent = None
    if result.x_axis is not None and result.y_axis is not None:
        if result.x_axis.size == image.shape[1] and result.y_axis.size == image.shape[0]:
            extent = [result.x_axis[0], result.x_axis[-1], result.y_axis[0], result.y_axis[-1]]

    if vmin is None or vmax is None or vmax <= vmin:
        low_percentile, high_percentile = style.preview_percentiles()
        vmin, vmax = (float(value) for value in np.percentile(finite, [low_percentile, high_percentile]))
        if vmax <= vmin:
            vmax = vmin + 1.0

    kwargs: dict[str, Any] = {
        "origin": "lower",
        "cmap": resolve_matplotlib_colormap(style.colormap),
        "aspect": "equal" if result.operation in ("q_image", "qr_qz_image") else "auto",
    }
    if extent is not None:
        kwargs["extent"] = extent
    if scale == "log":
        positive = finite[finite > 0]
        if positive.size:
            positive_min = max(vmin, float(np.min(positive)))
            positive_max = max(positive_min * (1.0 + 1e-12), vmax)
            kwargs["norm"] = LogNorm(vmin=positive_min, vmax=positive_max)
    else:
        kwargs.update(vmin=vmin, vmax=vmax)

    image_artist = axis.imshow(image, **kwargs)
    sizes = style.preview_sizes()
    axis.set_xlabel(result.x_label, fontsize=sizes["label"])
    axis.set_ylabel(result.y_label, fontsize=sizes["label"])
    axis.set_title(scientific_plot_title(result.operation), fontsize=sizes["title"])
    axis.tick_params(labelsize=sizes["tick"])
    if x_limits is not None:
        axis.set_xlim(*x_limits)
    if y_limits is not None:
        axis.set_ylim(*y_limits)
    axis.set_axis_on()
    if colorbar_axis is not None:
        axis.apply_aspect()
        image_position = axis.get_position()
        colorbar_axis.set_position([
            image_position.x1 + 0.025,
            image_position.y0,
            0.025,
            image_position.height,
        ])
    colorbar = figure.colorbar(image_artist, cax=colorbar_axis, ax=None if colorbar_axis is not None else axis)
    colorbar.ax.tick_params(labelsize=sizes["tick"])
    colorbar.set_label(INTENSITY, fontsize=sizes["label"])
    apply_plot_theme(figure, theme)
    return colorbar