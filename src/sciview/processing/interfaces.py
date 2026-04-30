"""Processing backend interfaces for SciView."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sciview.data.models import ProcessingRequest, ProcessingResult


class ProcessingBackendError(RuntimeError):
    """Raised when a processing backend cannot execute a request."""


@runtime_checkable
class ProcessingBackend(Protocol):
    """Contract implemented by processing adapters such as SciAnalysis."""

    name: str

    def run(self, request: ProcessingRequest) -> ProcessingResult:
        """Execute a structured processing request and return a structured result."""
