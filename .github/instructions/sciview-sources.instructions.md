---
applyTo: "src/sciview/sources/**/*.py"
---

# SciView data-source instructions

Data sources convert external data systems into SciView-neutral objects.

## Supported source types

- Local file system
- Tiled
- Future facility data services

## Requirements

- Return ImageRef, Dataset, or Workspace objects.
- Do not call GUI code.
- Do not call SciAnalysis directly.
- Use a resolver/cache layer when a downstream processing backend requires local files.
- Mock external services in tests.
- Do not require a live Tiled server in unit tests.

## Local file-source rules

- Use pathlib.
- Avoid beamline-specific assumptions.
- Beamline-specific layouts belong in profiles.

## Tiled-source rules

- Keep Tiled metadata mapping explicit.
- Do not assume the same metadata schema for all beamlines.
- Provide graceful error messages when nodes or metadata are missing.
