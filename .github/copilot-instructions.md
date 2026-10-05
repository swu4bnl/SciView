# GitHub Copilot Instructions for SciView

SciView is a Python-first, beamline-neutral application for 2D X-ray scattering workflows.

## Project priorities

1. Maintainability
2. Beamline neutrality
3. Local file-system and Tiled data support
4. SciAnalysis integration through a clean adapter
5. AI-friendly testing and debugging
6. Thin replaceable user interfaces

## Required design pattern

Use a backend-first architecture.

GUI widgets must call backend functions. GUI widgets must not contain scientific logic.

The backend must be callable from scripts, notebooks, command-line tools, tests, napari widgets, and future desktop interfaces.

## Core rules

- Do not hard-code CMS behavior in `sciview.core`.
- Do not hard-code `/nsls2/data` in tests.
- Do not parse filenames in core modules.
- Use beamline profiles for beamline-specific behavior.
- Use data-source adapters for file-system and Tiled access.
- Use processing adapters for SciAnalysis.
- Keep SciAnalysis calls out of GUI widgets.
- Use `pathlib.Path` for local paths.
- Use type hints for public APIs.
- Use dataclasses or Pydantic models for structured data.
- Use YAML for recipes and beamline profile configuration.
- Add pytest tests for backend changes.

## Preferred modules

```text
src/sciview/core/         neutral models, workspace, jobs, provenance
src/sciview/data/         ImageRef, Dataset, metadata models
src/sciview/sources/      file-system and Tiled source adapters
src/sciview/profiles/     beamline profiles such as CMS
src/sciview/processing/   SciAnalysis adapter and recipe runner
src/sciview/calibration/  calibration models and I/O
src/sciview/masking/      mask models and I/O
src/sciview/interfaces/   GUI and napari interfaces
tests/                    pytest tests
```

## Avoid

- Electron, React, FastAPI, databases, or cloud services unless explicitly requested.
- Large rewrites.
- Untested backend changes.
- Hidden dependencies on a mounted beamline file system.
- Duplicating scientific logic between GUI and backend.
