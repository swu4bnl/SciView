"""Turn single-image Reduction and Transform results into notebook objects."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np

from sciview.core.notebook import CurveData, CurveFigure, FigureMetadata, ImageFigure, ImageState, PlotState
from sciview.processing.provenance import detector_geometry, processing_provenance
from sciview.processing.reduction import ReductionRequest, ReductionResult
from sciview.processing.transform import TransformRequest, TransformResult

REDUCTION_PARAMETERS = (
    "operation", "center_x", "center_y", "bins", "bins_relative", "q_min", "q_max", "radius_max",
    "angle_start_deg", "angle_end_deg", "line_start", "line_end", "line_chi0_deg", "line_dq",
    "line_mode", "line_value", "use_mask",
)
TRANSFORM_PARAMETERS = (
    "operation", "use_mask", "bins_phi", "bins_relative", "preferred_method",
    "x_min", "x_max", "y_min", "y_max",
)


def source_reference(metadata: dict[str, Any]) -> str:
    """Name the processed image by its file or stream reference, never by its pixels."""
    for key in ("source_path", "source_uri", "name"):
        value = metadata.get(key)
        if value:
            return str(value)
    return "image"


def _applied_mask(request: Any, shape: tuple[int, int]) -> np.ndarray | None:
    if not request.use_mask or request.mask is None:
        return None
    mask = np.array(getattr(request.mask, "data", request.mask), dtype=bool, copy=True)
    if mask.shape != shape:
        raise ValueError(f"Mask shape {mask.shape} does not match image shape {shape}.")
    mask.setflags(write=False)
    return mask


def _geometry(calibration: Any) -> dict[str, float] | None:
    if calibration is None:
        return None
    try:
        return detector_geometry(calibration)[1]
    except ValueError:
        return None


def _parameters(request: Any, names: tuple[str, ...]) -> dict[str, Any]:
    parameters = {}
    for name in names:
        value = getattr(request, name)
        parameters[name] = list(value) if isinstance(value, tuple) else value
    return parameters


def reduction_figure(
    request: ReductionRequest, result: ReductionResult, *, title: str, state: PlotState | None = None,
) -> CurveFigure:
    """Reference the computed curve and the settings that produced it; no reprocessing."""
    shape = tuple(int(value) for value in np.asarray(request.image).shape)
    if len(shape) != 2:
        raise ValueError("Reduction provenance requires a two-dimensional image.")
    mask = _applied_mask(request, shape)
    source = source_reference({**request.metadata, **result.metadata})
    provenance = processing_provenance(
        backend="SciAnalysis" if result.metadata.get("source") == "scianalysis" else "numpy",
        parameters=_parameters(request, REDUCTION_PARAMETERS),
        shape=shape, calibration=_geometry(request.calibration), mask=mask, metadata=request.metadata,
    )
    curve = CurveData(
        index=0, source=source,
        x=np.asarray(result.x, dtype=float), y=np.asarray(result.y, dtype=float),
        x_label=result.x_label, y_label=result.y_label, metadata=deepcopy(result.metadata),
    )
    plot = CurveFigure(
        title=title, sources=[source], curves=[curve], provenance=provenance,
        state=state if state is not None else PlotState(), mask=mask,
        figure=FigureMetadata.from_curves([curve]),
    )
    plot.validate()
    return plot


def transform_figure(
    request: TransformRequest, result: TransformResult, *, title: str, state: ImageState | None = None,
) -> ImageFigure:
    """Reference the remeshed map, its axes and the geometry used to compute it."""
    shape = tuple(int(value) for value in np.asarray(request.image).shape)
    if len(shape) != 2:
        raise ValueError("Transform provenance requires a two-dimensional image.")
    mask = _applied_mask(request, shape)
    source = source_reference({**request.metadata, **result.metadata})
    provenance = processing_provenance(
        backend=str(result.metadata.get("backend") or "SciAnalysis"),
        parameters={**_parameters(request, TRANSFORM_PARAMETERS), "method": result.metadata.get("method")},
        shape=shape, calibration=_geometry(request.calibration), mask=mask, metadata=request.metadata,
    )
    plot = ImageFigure(
        title=title, sources=[source], image=np.asarray(result.image, dtype=float),
        provenance=provenance, state=state if state is not None else ImageState(),
        x_axis=None if result.x_axis is None else np.asarray(result.x_axis, dtype=float),
        y_axis=None if result.y_axis is None else np.asarray(result.y_axis, dtype=float),
        mask=mask, figure=FigureMetadata.from_labels(result.x_label, result.y_label),
    )
    plot.validate()
    return plot


def refresh_image_figure(plot: ImageFigure, request: TransformRequest, result: TransformResult) -> None:
    """Replace a map in place with a new computation, keeping identity, labels and presentation."""
    updated = transform_figure(request, result, title=plot.title, state=plot.state)
    updated.figure = plot.figure
    updated.validate()
    for name in ("sources", "image", "x_axis", "y_axis", "mask", "provenance", "runtime_s"):
        setattr(plot, name, getattr(updated, name))
