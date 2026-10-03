---
applyTo: "src/sciview/{core,data}/**/*.py"
---

# SciView core/data instructions

This code must be beamline-neutral and GUI-independent.

## Requirements

- No PyQt, PySide, napari, matplotlib widget, or Electron-related imports.
- No SciAnalysis calls in core/data modules.
- No hard-coded CMS paths, detector names, proposal numbers, pass IDs, or filename patterns.
- Use dataclasses or Pydantic models.
- Use type hints for public functions.
- Keep objects serializable when practical.
- Prefer explicit metadata fields over filename parsing.
- Add tests for new behavior.

## Core objects

Prefer these concepts:

- ImageRef
- Dataset
- Workspace
- CalibrationRef
- MaskRef
- ProcessingRequest
- ProcessingResult
- ProvenanceRecord

Core modules define shared language. They should not know how a specific GUI or beamline works.
