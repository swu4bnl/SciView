"""Sequential, calibrated reduction of an ordered image collection."""

from __future__ import annotations

from collections.abc import Callable
from copy import copy, deepcopy
from dataclasses import dataclass, field, replace
from io import BytesIO, StringIO
import json
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from sciview.processing.provenance import detector_geometry, processing_provenance
from sciview.processing.reduction import (
    ReductionBackend, ReductionRequest, ReductionResult, _load_scianalysis_classes,
)
from sciview.core.notebook import CurveData, CurveFigure, FigureMetadata, PlotState

logger = logging.getLogger(__name__)


class WaterfallInputError(ValueError):
    """A settings problem with a specific editing destination."""

    def __init__(self, message: str, destination: str = "reduction"):
        super().__init__(message)
        self.destination = destination


@dataclass(slots=True)
class WaterfallRequest:
    paths: tuple[str, ...]
    reduction: ReductionRequest
    shape: tuple[int, int]
    provenance: dict[str, Any]


@dataclass(slots=True)
class WaterfallCurve:
    index: int
    path: str
    result: ReductionResult | None = None
    error: str = ""
    runtime_s: float = 0.0


@dataclass(slots=True)
class WaterfallRun:
    request: WaterfallRequest
    curves: list[WaterfallCurve] = field(default_factory=list)
    cancelled: bool = False
    runtime_s: float = 0.0


def notebook_waterfall(run: WaterfallRun, state: PlotState, title: str) -> CurveFigure:
    """Reference completed 1D arrays without copying or retaining detector frames."""
    curves = [
        CurveData(
            index=curve.index, source=curve.path,
            x=curve.result.x if curve.result is not None else None,
            y=curve.result.y if curve.result is not None else None,
            x_label=curve.result.x_label if curve.result is not None else "",
            y_label=curve.result.y_label if curve.result is not None else "",
            metadata=deepcopy(curve.result.metadata) if curve.result is not None else {},
            error=curve.error, runtime_s=curve.runtime_s,
        ) for curve in run.curves
    ]
    plot = CurveFigure(
        title=title, sources=list(run.request.paths), curves=curves, state=state,
        provenance=deepcopy(run.request.provenance), mask=run.request.reduction.mask,
        cancelled=run.cancelled, runtime_s=run.runtime_s, figure=FigureMetadata.from_curves(curves),
    )
    plot.validate()
    return plot


def refresh_waterfall(plot: CurveFigure, run: WaterfallRun) -> None:
    """Replace a figure's scientific content in place, keeping identity and presentation.

    Marks index samples of the previous arrays, so they are cleared; curve
    appearance and visibility survive for sources that are still present.
    """
    if run.cancelled or any(curve.result is None for curve in run.curves) or len(run.curves) != len(run.request.paths):
        raise ValueError("An incomplete run cannot replace a saved figure.")
    updated = notebook_waterfall(run, replace(plot.state, marks=[], selected_index=None), plot.title)
    sources = set(updated.sources)
    updated.state.hidden_sources = [source for source in plot.state.hidden_sources if source in sources]
    updated.state.curve_styles = {
        index: style for index, style in plot.state.curve_styles.items() if index < len(updated.sources)
    }
    updated.figure = replace(
        plot.figure,
        legend_names={index: name for index, name in plot.figure.legend_names.items() if index < len(updated.sources)},
    )
    updated.validate()
    for name in ("sources", "curves", "provenance", "mask", "cancelled", "runtime_s", "state", "figure"):
        setattr(plot, name, getattr(updated, name))


def notebook_waterfall_run(plot: CurveFigure) -> WaterfallRun:
    """Restore a display/export value, not an executable calibration or recipe."""
    plot.validate()
    parameters = dict(plot.provenance["parameters"])
    geometry = plot.provenance.get("calibration") or {}
    for axis in ("x", "y"):
        parameters.setdefault(f"center_{axis}", geometry.get(f"beam_{axis}"))
    for name in ("line_start", "line_end"):
        if parameters.get(name) is not None:
            parameters[name] = tuple(parameters[name])
    reduction = ReductionRequest(image=None, **parameters, mask=plot.mask)
    request = WaterfallRequest(
        tuple(plot.sources), reduction, tuple(plot.provenance["shape"]), plot.provenance,
    )
    return WaterfallRun(
        request, [
            WaterfallCurve(
                curve.index, curve.source,
                ReductionResult(
                    reduction.operation, curve.x, curve.y, curve.x_label, curve.y_label, curve.metadata,
                ) if curve.x is not None else None,
                curve.error, curve.runtime_s,
            ) for curve in plot.curves
        ], plot.cancelled, plot.runtime_s,
    )


def _clear_calibration_maps(calibration: Any) -> None:
    calibration.clear_maps()
    # RQconv's inherited clear_maps leaves these large derived arrays attached.
    for name in ("X", "Y", "FPol_map_data", "FSA_map_data"):
        if hasattr(calibration, name):
            setattr(calibration, name, None)


def snapshot_waterfall(paths: tuple[str, ...], template: ReductionRequest) -> WaterfallRequest:
    """Detach scientific settings and geometry caches from editable UI state."""
    paths = tuple(dict.fromkeys(paths))
    if not paths or any("://" in path for path in paths):
        raise WaterfallInputError("Select at least one local image.")
    if template.operation not in {"circular_average", "sector_average"}:
        raise WaterfallInputError("Waterfall currently supports circular and sector averages.")
    if template.calibration is None:
        raise WaterfallInputError("A calibrated q axis requires a calibration.", "calibration")
    if _load_scianalysis_classes() is None:
        raise WaterfallInputError("SciAnalysis is required for calibrated waterfall reduction.")

    try:
        calibration = copy(template.calibration)
        _clear_calibration_maps(calibration)
        calibration = deepcopy(calibration)
        shape, geometry = detector_geometry(calibration)
    except (AttributeError, TypeError, ValueError) as exc:
        destination = "reduction" if template.metadata.get("calibration_source") == "Custom profile" else "calibration"
        raise WaterfallInputError(f"Invalid calibration: {exc}", destination) from exc

    mask = None
    if template.use_mask and template.mask is not None:
        destination = "reduction" if template.metadata.get("mask_source") == "Custom mask" else "mask_editing"
        mask = np.array(template.mask, dtype=bool, copy=True)
        if mask.shape != shape:
            raise WaterfallInputError(
                f"Mask shape {mask.shape} does not match calibrated detector {shape}.", destination,
            )
        if mask.all():
            raise WaterfallInputError("The mask excludes every detector pixel.", destination)
        mask.setflags(write=False)

    reduction = replace(
        template, image=None, calibration=calibration, mask=mask,
        metadata=deepcopy(template.metadata), show_region=False,
    )
    parameters = {
        key: getattr(reduction, key)
        for key in (
            "operation", "bins", "bins_relative", "q_min", "q_max",
            "angle_start_deg", "angle_end_deg", "use_mask",
        )
    }
    if reduction.bins < 1 or (
        reduction.bins_relative is not None
        and (not np.isfinite(reduction.bins_relative) or reduction.bins_relative <= 0)
    ):
        raise WaterfallInputError("Reduction binning must be positive.")
    if any(value is not None and (not np.isfinite(value) or value < 0)
           for value in (reduction.q_min, reduction.q_max)):
        raise WaterfallInputError("The q range must be finite and non-negative.")
    if reduction.q_min is not None and reduction.q_max is not None and reduction.q_max <= reduction.q_min:
        raise WaterfallInputError("The q range must be increasing.")
    if not np.isfinite([reduction.angle_start_deg, reduction.angle_end_deg]).all():
        raise WaterfallInputError("Sector angles must be finite.")
    provenance = processing_provenance(
        backend="SciAnalysis", parameters=parameters, shape=shape, calibration=geometry,
        mask=mask, metadata=template.metadata,
    )
    return WaterfallRequest(paths, reduction, shape, provenance)


def load_waterfall_image(path: str) -> np.ndarray:
    """Use SciAnalysis detector readers without coercing stacks into single frames."""
    classes = _load_scianalysis_classes()
    if classes is None:
        raise RuntimeError("SciAnalysis is unavailable.")
    data = classes[1](path)
    return np.asarray(data.data)


def run_waterfall(
    request: WaterfallRequest,
    *,
    load_image: Callable[[str], np.ndarray] = load_waterfall_image,
    backend: ReductionBackend | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    on_curve: Callable[[WaterfallCurve], None] | None = None,
) -> WaterfallRun:
    """Retain only 1D results; cancellation takes effect between backend calls."""
    backend = backend if backend is not None else ReductionBackend()
    run = WaterfallRun(request)
    started = perf_counter()
    try:
        for index, path in enumerate(request.paths):
            if cancelled():
                run.cancelled = True
                break
            frame_started = perf_counter()
            try:
                image = np.asarray(load_image(path))
                if cancelled():
                    run.cancelled = True
                    break
                if image.ndim != 2 or image.shape != request.shape:
                    raise ValueError(f"Image shape {image.shape} does not match detector {request.shape}.")
                result = backend.run(replace(
                    request.reduction, image=image,
                    metadata={**request.reduction.metadata, "source_path": path},
                ))
                if result.metadata.get("source") != "scianalysis":
                    raise ValueError("Calibrated reduction is unavailable; pixel-coordinate fallback was rejected.")
                if result.x.shape != result.y.shape or result.x.ndim != 1:
                    raise ValueError("Reduction did not return matching one-dimensional coordinates and intensities.")
                if not np.any(np.isfinite(result.x) & np.isfinite(result.y)):
                    raise ValueError("Reduction returned no finite curve points.")
                curve = WaterfallCurve(index, path, result, runtime_s=perf_counter() - frame_started)
            except Exception as exc:
                logger.exception("Waterfall reduction failed for %s", path)
                curve = WaterfallCurve(index, path, error=str(exc), runtime_s=perf_counter() - frame_started)
            run.curves.append(curve)
            if on_curve is not None:
                on_curve(curve)
        run.cancelled = run.cancelled or cancelled()
    finally:
        run.runtime_s = perf_counter() - started
        _clear_calibration_maps(request.reduction.calibration)
    return run


def _json_metadata(value):
    """Uncertainty arrays can contain nonfinite values; JSON represents them as null."""
    if isinstance(value, dict):
        return {key: _json_metadata(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_metadata(item) for item in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return value.item() if isinstance(value, np.generic) else value


def export_waterfall(run: WaterfallRun, path: str | Path) -> Path:
    """Export unshifted curves and their input/settings manifest in one archive."""
    target = Path(path)
    manifest = {
        **deepcopy(run.request.provenance), "inputs": list(run.request.paths),
        "cancelled": run.cancelled, "runtime_s": run.runtime_s, "curves": [],
    }
    with NamedTemporaryFile(dir=target.parent, suffix=".zip", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as archive:
            if run.request.reduction.mask is not None:
                mask_data = BytesIO()
                np.save(mask_data, run.request.reduction.mask, allow_pickle=False)
                archive.writestr("mask.npy", mask_data.getvalue())
                manifest["mask"]["file"] = "mask.npy"
            for curve in run.curves:
                entry = {
                    "index": curve.index, "source": curve.path, "error": curve.error,
                    "runtime_s": curve.runtime_s,
                }
                if curve.result is not None:
                    name = f"curve_{curve.index + 1:05d}.csv"
                    text = StringIO()
                    np.savetxt(text, np.column_stack((curve.result.x, curve.result.y)), delimiter=",",
                               header=f"{curve.result.x_label}, {curve.result.y_label}")
                    archive.writestr(name, text.getvalue())
                    entry["file"] = name
                    entry["metadata"] = curve.result.metadata
                manifest["curves"].append(entry)
            archive.writestr("manifest.json", json.dumps(_json_metadata(manifest), indent=2, allow_nan=False))
        temporary_path.replace(target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return target
