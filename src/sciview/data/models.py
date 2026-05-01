"""Beamline-neutral data models for SciView backend APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _to_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    return value if isinstance(value, Path) else Path(value)


@dataclass(slots=True)
class ImageRef:
    """Reference to an image in a source-agnostic form."""

    source_uri: str
    source_type: str = "unknown"
    local_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_uri": self.source_uri,
            "source_type": self.source_type,
            "local_path": str(self.local_path) if self.local_path else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ImageRef":
        return cls(
            source_uri=str(payload["source_uri"]),
            source_type=str(payload.get("source_type", "unknown")),
            local_path=_to_path(payload.get("local_path")),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class Dataset:
    """A collection of related image references and metadata."""

    name: str
    images: list[ImageRef] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "images": [image.to_dict() for image in self.images],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Dataset":
        return cls(
            name=str(payload["name"]),
            images=[ImageRef.from_dict(item) for item in payload.get("images", [])],
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class Workspace:
    """The active experiment context for data and processing."""

    root: Path
    profile: str
    datasets: dict[str, Dataset] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "profile": self.profile,
            "datasets": {name: ds.to_dict() for name, ds in self.datasets.items()},
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Workspace":
        dataset_map = {
            str(name): Dataset.from_dict(dataset_payload)
            for name, dataset_payload in payload.get("datasets", {}).items()
        }
        return cls(
            root=Path(payload["root"]),
            profile=str(payload["profile"]),
            datasets=dataset_map,
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class CalibrationRef:
    """Calibration values needed for converting detector to scattering coordinates."""

    detector_name: str
    wavelength_a: float
    distance_m: float
    pixel_size_um: float
    beam_center_x: float
    beam_center_y: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_name": self.detector_name,
            "wavelength_a": self.wavelength_a,
            "distance_m": self.distance_m,
            "pixel_size_um": self.pixel_size_um,
            "beam_center_x": self.beam_center_x,
            "beam_center_y": self.beam_center_y,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CalibrationRef":
        return cls(
            detector_name=str(payload["detector_name"]),
            wavelength_a=float(payload["wavelength_a"]),
            distance_m=float(payload["distance_m"]),
            pixel_size_um=float(payload["pixel_size_um"]),
            beam_center_x=float(payload["beam_center_x"]),
            beam_center_y=float(payload["beam_center_y"]),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class MaskRef:
    """Reference to a persisted mask and related metadata."""

    name: str
    source_uri: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_uri": self.source_uri,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MaskRef":
        return cls(
            name=str(payload["name"]),
            source_uri=str(payload["source_uri"]),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class ProcessingRecipe:
    """Validated processing recipe configuration."""

    name: str
    operation: str
    description: str = ""
    version: str = "1.0"
    inputs: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    mask: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "operation": self.operation,
            "description": self.description,
            "version": self.version,
            "inputs": dict(self.inputs),
            "calibration": dict(self.calibration),
            "mask": dict(self.mask),
            "parameters": dict(self.parameters),
            "outputs": dict(self.outputs),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProcessingRecipe":
        return cls(
            name=str(payload["name"]),
            operation=str(payload["operation"]),
            description=str(payload.get("description", "")),
            version=str(payload.get("version", "1.0")),
            inputs=dict(payload.get("inputs", {})),
            calibration=dict(payload.get("calibration", {})),
            mask=dict(payload.get("mask", {})),
            parameters=dict(payload.get("parameters", {})),
            outputs=dict(payload.get("outputs", {})),
        )


@dataclass(slots=True)
class ProcessingRequest:
    """Structured processing request consumed by backend adapters."""

    image: ImageRef
    recipe: ProcessingRecipe
    calibration: CalibrationRef | None = None
    mask: MaskRef | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image": self.image.to_dict(),
            "recipe": self.recipe.to_dict(),
            "calibration": self.calibration.to_dict() if self.calibration else None,
            "mask": self.mask.to_dict() if self.mask else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProcessingRequest":
        return cls(
            image=ImageRef.from_dict(payload["image"]),
            recipe=ProcessingRecipe.from_dict(payload["recipe"]),
            calibration=CalibrationRef.from_dict(payload["calibration"])
            if payload.get("calibration")
            else None,
            mask=MaskRef.from_dict(payload["mask"]) if payload.get("mask") else None,
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class ProvenanceRecord:
    """Provenance metadata captured for processing runs."""

    input_refs: list[str] = field(default_factory=list)
    recipe_name: str = ""
    output_files: list[str] = field(default_factory=list)
    software_versions: dict[str, str] = field(default_factory=dict)
    runtime_s: float | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_refs": list(self.input_refs),
            "recipe_name": self.recipe_name,
            "output_files": list(self.output_files),
            "software_versions": dict(self.software_versions),
            "runtime_s": self.runtime_s,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProvenanceRecord":
        return cls(
            input_refs=[str(v) for v in payload.get("input_refs", [])],
            recipe_name=str(payload.get("recipe_name", "")),
            output_files=[str(v) for v in payload.get("output_files", [])],
            software_versions={
                str(name): str(version)
                for name, version in payload.get("software_versions", {}).items()
            },
            runtime_s=float(payload["runtime_s"]) if payload.get("runtime_s") is not None else None,
            warnings=[str(v) for v in payload.get("warnings", [])],
            errors=[str(v) for v in payload.get("errors", [])],
        )


@dataclass(slots=True)
class ProcessingResult:
    """Structured result returned by processing adapters."""

    success: bool
    output_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    runtime_s: float | None = None
    provenance: ProvenanceRecord | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output_files": list(self.output_files),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "runtime_s": self.runtime_s,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProcessingResult":
        return cls(
            success=bool(payload["success"]),
            output_files=[str(v) for v in payload.get("output_files", [])],
            warnings=[str(v) for v in payload.get("warnings", [])],
            errors=[str(v) for v in payload.get("errors", [])],
            runtime_s=float(payload["runtime_s"]) if payload.get("runtime_s") is not None else None,
            provenance=ProvenanceRecord.from_dict(payload["provenance"])
            if payload.get("provenance")
            else None,
            metadata=dict(payload.get("metadata", {})),
        )
