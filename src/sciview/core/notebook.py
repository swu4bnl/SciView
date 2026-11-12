"""GUI-independent scientific notebook values."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4
from hashlib import sha256
import re

import numpy as np

from sciview.settings.viewer_config import (
    ARTIST_IMAGE_COLORMAPS, SUPPORTED_IMAGE_COLORMAPS, SUPPORTED_IMAGE_SCALES,
)


IMAGE_COLORMAPS = (*SUPPORTED_IMAGE_COLORMAPS, *ARTIST_IMAGE_COLORMAPS)
AUTO_INTENSITY_PERCENTILES = (5.0, 99.5)


def plain_value(value):
    """Convert numpy scalars/arrays and paths into YAML- and JSON-safe values."""
    if isinstance(value, dict):
        return {key: plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return value


def _single_line(value: Any, limit: int = 256) -> bool:
    return isinstance(value, str) and len(value) <= limit and "\n" not in value


def _validate_dimensions(width: Any, height: Any) -> None:
    if not isinstance(width, int) or not 50 <= width <= 100 or not 160 <= height <= 1200:
        raise ValueError("Invalid notebook plot dimensions.")


def _validate_view_range(view_range: Any) -> None:
    if view_range is None:
        return
    ranges = np.asarray(view_range, dtype=float)
    if ranges.shape != (2, 2) or not np.isfinite(ranges).all() or not (ranges[:, 1] > ranges[:, 0]).all():
        raise ValueError("Invalid plot viewing range.")


@dataclass(slots=True)
class CurveData:
    index: int
    source: str
    x: np.ndarray | None = None
    y: np.ndarray | None = None
    x_label: str = ""
    y_label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    runtime_s: float = 0.0


@dataclass(slots=True)
class CurveStyle:
    color: str | None = None
    line_style: str | None = None
    line_width: float | None = None
    gain: float = 1.0
    opacity: float = 1.0

    def validate(self) -> None:
        if self.color is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", self.color):
            raise ValueError("Invalid curve color.")
        if self.line_style is not None and self.line_style not in {"solid", "dash", "dot", "dash_dot"}:
            raise ValueError("Invalid curve line style.")
        if self.line_width is not None and (
            not np.isfinite(self.line_width) or not 1 <= self.line_width <= 8
        ):
            raise ValueError("Invalid curve line width.")
        if not np.isfinite(self.gain) or self.gain < 0:
            raise ValueError("Invalid display-only curve gain.")
        if not np.isfinite(self.opacity) or not 0 <= self.opacity <= 1:
            raise ValueError("Invalid curve opacity.")


@dataclass(slots=True)
class PlotState:
    spacing: float = 0.0
    palette: str = "viridis"
    hidden_sources: list[str] = field(default_factory=list)
    view_range: list[list[float]] | None = None
    selected_index: int | None = None
    marks: list[list[int]] = field(default_factory=list)
    curve_styles: dict[int, CurveStyle] = field(default_factory=dict)
    width: int = 100
    height: int = 320
    default_line_style: str = "solid"
    default_line_width: float | None = None

    def __post_init__(self) -> None:
        self.curve_styles = {
            int(index): style if isinstance(style, CurveStyle) else CurveStyle(**style)
            for index, style in self.curve_styles.items()
        }

    def validate(self, curves: list[CurveData]) -> None:
        CurveStyle(line_style=self.default_line_style, line_width=self.default_line_width).validate()
        if self.default_line_style is None:
            raise ValueError("Invalid default line style.")
        if not np.isfinite(self.spacing) or self.spacing < 0:
            raise ValueError("Invalid waterfall spacing.")
        if self.palette not in {"viridis", "plasma", "cividis", "turbo"}:
            raise ValueError("Unknown waterfall palette.")
        _validate_dimensions(self.width, self.height)
        _validate_view_range(self.view_range)
        indexed = {curve.index: curve for curve in curves}
        for index, style in self.curve_styles.items():
            if index not in indexed:
                raise ValueError("Curve appearance refers to an unknown source.")
            style.validate()
        if self.selected_index is not None and self.selected_index not in indexed:
            raise ValueError("Unknown selected curve.")
        for index, point in self.marks:
            curve = indexed.get(index)
            if (
                curve is None or curve.x is None or not 0 <= point < len(curve.x)
                or not np.isfinite([curve.x[point], curve.y[point]]).all()
            ):
                raise ValueError("A mark does not refer to a saved curve sample.")

    def resolved_curve_style(self, index: int, fallback_width: float) -> CurveStyle:
        """Apply figure defaults without turning them into individual overrides."""
        style = self.curve_styles.get(index, CurveStyle())
        return replace(
            style, line_style=style.line_style or self.default_line_style,
            line_width=style.line_width or self.default_line_width or fallback_width,
        )

    @staticmethod
    def palette_position(index: int, count: int) -> float:
        """Place curves within the readable middle of a palette, in input order."""
        return 0.2 + 0.6 * index / max(1, count - 1)


@dataclass(slots=True)
class ImageState:
    colormap: str = "viridis"
    scale: str = "linear"
    vmin: float | None = None
    vmax: float | None = None
    view_range: list[list[float]] | None = None
    width: int = 100
    height: int = 420

    def validate(self) -> None:
        if self.colormap not in IMAGE_COLORMAPS:
            raise ValueError("Unknown image colormap.")
        if self.scale not in SUPPORTED_IMAGE_SCALES:
            raise ValueError("Unknown intensity scale.")
        if (self.vmin is None) != (self.vmax is None):
            raise ValueError("Intensity limits must be set together or left automatic.")
        if self.vmin is not None and (
            not np.isfinite([self.vmin, self.vmax]).all() or self.vmax <= self.vmin
        ):
            raise ValueError("Intensity limits must be finite and increasing.")
        _validate_dimensions(self.width, self.height)
        _validate_view_range(self.view_range)


@dataclass(slots=True)
class FigureMetadata:
    x_label: str = ""
    x_units: str = ""
    y_label: str = ""
    y_units: str = ""
    legend_names: dict[int, str] = field(default_factory=dict)
    show_legend: bool = True

    def __post_init__(self) -> None:
        self.legend_names = {int(index): name for index, name in self.legend_names.items()}
        for field_name in ("x_label", "x_units", "y_label", "y_units"):
            value = getattr(self, field_name)
            if isinstance(value, str):
                setattr(self, field_name, self.plain_label(value))

    @staticmethod
    def plain_label(label: str) -> str:
        """Translate legacy SciView math-text labels without interpreting user text."""
        legacy = {
            "q": "q", "q_x": "q_x", "q_r": "q_r", "q_z": "q_z",
            "I(q)": "I(q)", r"I(\chi)": "I(χ)",
            r"\chi": "χ", r"\phi": "φ",
            r"\mathrm{\AA}^{-1}": "Å⁻¹", r"^\circ": "°",
        }
        return re.sub(r"\$([^$]+)\$", lambda match: legacy.get(match[1], match[0]), label)

    def validate(self, curves: list[CurveData]) -> None:
        labels = [self.x_label, self.x_units, self.y_label, self.y_units, *self.legend_names.values()]
        if any(not _single_line(label) for label in labels):
            raise ValueError("Figure labels must be single-line text up to 256 characters.")
        if not isinstance(self.show_legend, bool):
            raise ValueError("Invalid figure legend visibility.")
        if set(self.legend_names) - {curve.index for curve in curves}:
            raise ValueError("Legend refers to an unknown measurement.")

    @staticmethod
    def split_label(label: str) -> tuple[str, str]:
        label = FigureMetadata.plain_label(label)
        match = re.fullmatch(r"(.*?)\s+\(([^()]*)\)", label.strip())
        return (match[1], match[2]) if match else (label.strip(), "")

    @classmethod
    def from_labels(cls, x_label: str, y_label: str) -> FigureMetadata:
        x_label, x_units = cls.split_label(x_label)
        y_label, y_units = cls.split_label(y_label)
        if x_label == "q" and not x_units:
            x_units = "Å⁻¹"
        return cls(x_label=x_label, x_units=x_units, y_label=y_label, y_units=y_units)

    @classmethod
    def from_curves(cls, curves: list[CurveData]) -> FigureMetadata:
        first = next((curve for curve in curves if curve.x is not None), None)
        return cls.from_labels(first.x_label if first else "", first.y_label if first else "")

    def axis_title(self, axis: str) -> str:
        label = getattr(self, f"{axis}_label")
        units = getattr(self, f"{axis}_units")
        return f"{label} ({units})" if units else label


class ScientificObject(ABC):
    """Shared identity, provenance and persistence contract; payloads stay specialized.

    Concrete types keep their own arrays, state and validation. The notebook,
    persistence and editor bridge only rely on this interface.
    """

    __slots__ = ()
    kind: ClassVar[str]
    id: str
    title: str
    sources: list[str]
    provenance: dict[str, Any]
    preview: bytes
    figure: FigureMetadata
    state: Any

    def validate(self) -> None:
        if len(self.id) != 32 or any(char not in "0123456789abcdef" for char in self.id):
            raise ValueError("Invalid notebook object ID.")
        if not _single_line(self.title) or not self.title.strip():
            raise ValueError("Figure title must be nonempty single-line text up to 256 characters.")
        if not isinstance(self.sources, list) or not all(isinstance(source, str) for source in self.sources):
            raise ValueError("Object sources must be a list of references.")
        if not isinstance(self.provenance, dict):
            raise ValueError("Object provenance must be a mapping.")
        self.validate_payload()

    @abstractmethod
    def validate_payload(self) -> None:
        """Check the scientific arrays and presentation state of this type."""

    @abstractmethod
    def arrays(self) -> dict[str, np.ndarray]:
        """Numeric arrays persisted beside the document."""

    @abstractmethod
    def record(self) -> dict[str, Any]:
        """Plain manifest record without arrays, preview or identity."""

    @classmethod
    @abstractmethod
    def from_record(
        cls, key: str, record: dict[str, Any], arrays: dict[str, np.ndarray], preview: bytes,
    ) -> ScientificObject:
        """Rebuild a saved object from its manifest record and arrays."""

    def _validate_mask(self, mask: np.ndarray | None) -> None:
        if mask is None:
            return
        mask_info = self.provenance.get("mask")
        if (
            mask_info is None
            or mask.dtype != np.dtype(bool)
            or list(mask.shape) != self.provenance["shape"]
            or sha256(mask.tobytes()).hexdigest() != mask_info["sha256"]
        ):
            raise ValueError("Saved mask does not match the processing provenance.")


@dataclass(slots=True)
class CurveFigure(ScientificObject):
    """One or more 1D curves sharing axes, presented as an overlay or waterfall."""

    kind: ClassVar[str] = "curves"

    title: str
    sources: list[str]
    curves: list[CurveData]
    provenance: dict[str, Any]
    state: PlotState
    mask: np.ndarray | None = None
    cancelled: bool = False
    runtime_s: float = 0.0
    id: str = field(default_factory=lambda: uuid4().hex)
    preview: bytes = b""
    figure: FigureMetadata = field(default_factory=FigureMetadata)

    def validate_payload(self) -> None:
        seen = set()
        for curve in self.curves:
            if curve.index in seen or not 0 <= curve.index < len(self.sources):
                raise ValueError("Invalid or duplicate curve index.")
            seen.add(curve.index)
            if curve.source != self.sources[curve.index]:
                raise ValueError("Curve source does not match the ordered collection.")
            if (curve.x is None) != (curve.y is None):
                raise ValueError("A saved curve must contain both coordinates and intensities.")
            if curve.x is not None:
                if (
                    curve.x.ndim != 1 or curve.x.shape != curve.y.shape
                    or curve.x.dtype.kind not in "fiu" or curve.y.dtype.kind not in "fiu"
                ):
                    raise ValueError("Saved curves must have matching numeric one-dimensional arrays.")
        self.state.validate(self.curves)
        self.figure.validate(self.curves)
        self._validate_mask(self.mask)

    def arrays(self) -> dict[str, np.ndarray]:
        arrays = {}
        for curve in self.curves:
            if curve.x is not None:
                arrays[f"x_{curve.index}"] = curve.x
                arrays[f"y_{curve.index}"] = curve.y
        if self.mask is not None:
            arrays["mask"] = self.mask
        return arrays

    def record(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "sources": list(self.sources),
            "curves": [
                {
                    "index": curve.index, "source": curve.source,
                    "x_label": curve.x_label, "y_label": curve.y_label,
                    "metadata": plain_value(curve.metadata), "error": curve.error,
                    "runtime_s": curve.runtime_s, "has_data": curve.x is not None,
                }
                for curve in self.curves
            ],
            "provenance": plain_value(self.provenance),
            "state": asdict(self.state),
            "cancelled": self.cancelled,
            "runtime_s": self.runtime_s,
            "figure": asdict(self.figure),
        }

    @classmethod
    def from_record(cls, key, record, arrays, preview) -> CurveFigure:
        curves = []
        for entry in record["curves"]:
            values = dict(entry)
            has_data = values.pop("has_data")
            index = values["index"]
            curves.append(CurveData(
                **values,
                x=arrays[f"x_{index}"] if has_data else None,
                y=arrays[f"y_{index}"] if has_data else None,
            ))
        return cls(
            id=key, title=record["title"], sources=list(record["sources"]), curves=curves,
            provenance=record["provenance"], state=PlotState(**record["state"]),
            mask=arrays.get("mask"), cancelled=record["cancelled"], runtime_s=record["runtime_s"],
            preview=preview,
            figure=FigureMetadata(**record["figure"]) if "figure" in record else FigureMetadata.from_curves(curves),
        )


@dataclass(slots=True)
class ImageFigure(ScientificObject):
    """A 2D intensity map on calibrated axes, such as a reciprocal-space transform."""

    kind: ClassVar[str] = "image"

    title: str
    sources: list[str]
    image: np.ndarray
    provenance: dict[str, Any]
    state: ImageState
    x_axis: np.ndarray | None = None
    y_axis: np.ndarray | None = None
    mask: np.ndarray | None = None
    runtime_s: float = 0.0
    id: str = field(default_factory=lambda: uuid4().hex)
    preview: bytes = b""
    figure: FigureMetadata = field(default_factory=FigureMetadata)

    def validate_payload(self) -> None:
        if (
            not isinstance(self.image, np.ndarray) or self.image.ndim != 2
            or self.image.dtype.kind not in "fiu" or min(self.image.shape) < 1
            or not np.isfinite(self.image).any()
        ):
            raise ValueError("An image figure needs a two-dimensional numeric map with finite values.")
        for axis, length in ((self.x_axis, self.image.shape[1]), (self.y_axis, self.image.shape[0])):
            if axis is None:
                continue
            if (
                not isinstance(axis, np.ndarray) or axis.ndim != 1 or len(axis) != length
                or axis.dtype.kind not in "fiu" or not np.isfinite(axis).all()
                or (len(axis) > 1 and not (np.diff(axis) > 0).all())
            ):
                raise ValueError("Image axes must be finite, increasing and match the map dimensions.")
        self.state.validate()
        if self.state.scale == "log":
            self.intensity_limits()
        self.figure.validate([])
        self._validate_mask(self.mask)

    def arrays(self) -> dict[str, np.ndarray]:
        arrays = {"image": self.image}
        if self.x_axis is not None:
            arrays["x_axis"] = self.x_axis
        if self.y_axis is not None:
            arrays["y_axis"] = self.y_axis
        if self.mask is not None:
            arrays["mask"] = self.mask
        return arrays

    def record(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "sources": list(self.sources),
            "provenance": plain_value(self.provenance),
            "state": asdict(self.state),
            "runtime_s": self.runtime_s,
            "figure": asdict(self.figure),
        }

    @classmethod
    def from_record(cls, key, record, arrays, preview) -> ImageFigure:
        return cls(
            id=key, title=record["title"], sources=list(record["sources"]), image=arrays["image"],
            provenance=record["provenance"], state=ImageState(**record["state"]),
            x_axis=arrays.get("x_axis"), y_axis=arrays.get("y_axis"), mask=arrays.get("mask"),
            runtime_s=record["runtime_s"], preview=preview, figure=FigureMetadata(**record["figure"]),
        )

    def extent(self) -> list[list[float]]:
        """Outer edges of the map in axis units, extending bin centers by half a step."""
        edges = []
        for axis, length in ((self.x_axis, self.image.shape[1]), (self.y_axis, self.image.shape[0])):
            if axis is None:
                edges.append([0.0, float(length)])
            elif len(axis) == 1:
                edges.append([float(axis[0]) - 0.5, float(axis[0]) + 0.5])
            else:
                step = float(axis[1] - axis[0])
                edges.append([float(axis[0]) - step / 2, float(axis[-1]) + step / 2])
        return edges

    def intensity_limits(self) -> tuple[float, float]:
        """Resolve automatic or requested limits into the values used for display."""
        finite = self.image[np.isfinite(self.image)]
        if self.state.vmin is None:
            low, high = (float(value) for value in np.percentile(finite, AUTO_INTENSITY_PERCENTILES))
        else:
            low, high = float(self.state.vmin), float(self.state.vmax)
        if self.state.scale == "log":
            positive = finite[finite > 0]
            if not positive.size:
                raise ValueError("Log intensity scale requires positive image values.")
            low = max(low, float(positive.min()))
            high = max(high, low * (1 + 1e-6))
        if high <= low:
            high = low + 1.0
        return low, high


OBJECT_TYPES: dict[str, type[ScientificObject]] = {
    cls.kind: cls for cls in (CurveFigure, ImageFigure)
}


def _signature_values(value):
    """Drop transient selection and round floating ranges so edits compare stably."""
    if isinstance(value, dict):
        return {
            key: (
                [[float(f"{item:.10g}") for item in axis] for axis in item_value]
                if key == "view_range" and item_value is not None else _signature_values(item_value)
            )
            for key, item_value in value.items() if key != "selected_index"
        }
    if isinstance(value, list):
        return [_signature_values(item) for item in value]
    return value


def object_signature(scientific_object: ScientificObject) -> str:
    arrays = {
        name: {"dtype": str(array.dtype), "shape": list(array.shape), "sha256": sha256(array.tobytes()).hexdigest()}
        for name, array in scientific_object.arrays().items()
    }
    document = {
        "kind": scientific_object.kind, "record": _signature_values(scientific_object.record()),
        "arrays": arrays,
    }
    return sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(slots=True)
class Notebook:
    markdown: str = ""
    objects: dict[str, ScientificObject] = field(default_factory=dict)
    path: Path | None = None

    def content_signature(self) -> str:
        """Compare document content, not editor selection or regenerated previews."""
        markdown = re.sub(
            r'!\[[^\]\n]*\]\([^)\n]*\s+"sciview:([0-9a-f]{32})"\)',
            lambda match: f'![figure](sciview:{match[1]})', self.markdown,
        ).strip()
        objects = {key: object_signature(item) for key, item in self.objects.items()}
        return sha256(json.dumps(
            {"markdown": markdown, "objects": objects}, sort_keys=True, ensure_ascii=False,
        ).encode()).hexdigest()

    def add_object(self, scientific_object: ScientificObject) -> str:
        scientific_object.validate()
        if scientific_object.id in self.objects:
            raise ValueError("Notebook object already exists.")
        self.objects[scientific_object.id] = scientific_object
        return scientific_object.id
