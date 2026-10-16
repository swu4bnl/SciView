# GitHub Copilot Instructions for SciView

SciView is a Python-first, beamline-neutral application for 2D X-ray scattering workflows.

## Critical boundaries

- Keep scientific logic in GUI-independent backends callable from scripts, notebooks, tests, and replaceable interfaces. Widgets collect input, call backends, and display results.
- Keep `core` and `data` beamline-neutral. Beamline conventions and filename interpretation belong in `profiles`; file-system and Tiled access in `sources`; SciAnalysis calls in `processing` adapters.
- Preserve scientific meaning, units, source data, and provenance. Do not hide failures behind silent defaults or success-shaped results.
- Keep changes bounded to the request. Preserve unrelated work and ask before substantial workflow changes or rewrites.

## Validation and test retention

- Validate the changed behavior with the smallest relevant existing tests or local checks. Backend behavior changes require pytest coverage.
- Retain tests for scientific correctness, major workflows, public contracts, and consequential component interactions. Do not add permanent tests merely because a minor isolated feature changed.
- Keep one-off UI, cosmetic, and implementation probes local and uncommitted; remove temporary artifacts after use. See [test instructions](instructions/sciview-tests.instructions.md).

## UI and documentation

- Keep routine controls compact and self-explanatory. Preserve scientific precision where it affects decisions or results.
- Document workflows and non-obvious consequences, not every feature. Keep reusable guidance concise and abstract rather than accumulating task-specific examples.
- Follow [UI instructions](instructions/sciview-ui.instructions.md) for interface changes.

## Project conventions

- Use `pathlib.Path` for local paths, typed public APIs, dataclasses or Pydantic models for structured data, and YAML for recipes and beamline profiles.
- Tests must run without facility mounts or live services.
- Do not introduce web stacks, databases, or cloud services unless requested.

Module-specific rules live in [instructions/](instructions/). The [project reference](../docs/SciView-project-reference.md) provides broader context; [collaboration guidance](../docs/ai-collaboration-guidelines.md) records reusable working preferences.
