"""SciAnalysis backend adapter owned by SciView."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from sciview.data.models import ProcessingRequest, ProcessingResult, ProvenanceRecord
from sciview.processing.interfaces import ProcessingBackendError
from sciview.sources.filesystem_source import resolve_local_path


ProtocolRunner = Callable[[Path, ProcessingRequest], dict[str, Any] | None]


class SciAnalysisBackend:
    """Thin adapter around SciAnalysis-like processing functions."""

    name = "scianalysis"

    def __init__(self, protocol_registry: dict[str, ProtocolRunner] | None = None):
        self._protocol_registry = dict(protocol_registry or {})

    def is_available(self) -> bool:
        if self._protocol_registry:
            return True

        try:
            from SciAnalysis.XSAnalysis import Protocols  # noqa: F401
        except ImportError:
            return False
        return True

    def validate_request(self, request: ProcessingRequest) -> Path:
        if not request.recipe.operation.strip():
            raise ProcessingBackendError("Processing request recipe operation is required")
        try:
            return resolve_local_path(request.image)
        except Exception as exc:  # pragma: no cover - defensive translation
            raise ProcessingBackendError(f"SciAnalysis requires a file-backed image reference: {exc}") from exc

    def _get_runner(self, operation: str) -> ProtocolRunner:
        if operation in self._protocol_registry:
            return self._protocol_registry[operation]
        raise ProcessingBackendError(
            f"No SciAnalysis runner registered for operation '{operation}'"
        )

    def run(self, request: ProcessingRequest) -> ProcessingResult:
        image_path = self.validate_request(request)
        runner = self._get_runner(request.recipe.operation)

        started = perf_counter()
        payload = runner(image_path, request) or {}
        runtime_s = perf_counter() - started

        output_files = [str(item) for item in payload.get("output_files", [])]
        warnings = [str(item) for item in payload.get("warnings", [])]
        errors = [str(item) for item in payload.get("errors", [])]
        success = bool(payload.get("success", not errors))

        provenance = ProvenanceRecord(
            input_refs=[request.image.source_uri],
            recipe_name=request.recipe.name,
            output_files=output_files,
            software_versions={"backend": self.name},
            runtime_s=runtime_s,
            warnings=warnings,
            errors=errors,
        )

        return ProcessingResult(
            success=success,
            output_files=output_files,
            warnings=warnings,
            errors=errors,
            runtime_s=runtime_s,
            provenance=provenance,
            metadata=dict(payload.get("metadata", {})),
        )