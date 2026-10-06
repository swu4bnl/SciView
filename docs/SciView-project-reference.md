# SciView Project Reference

This is a compact project-specific companion to the reusable instructions in [docs/ai-collaboration-guidelines.md](ai-collaboration-guidelines.md) and the generic skills under [.github/skills/](../.github/skills/). It reflects the `swu4bnl/SciView` repository checked on 2026-10-03. Treat it as an orientation, not an authoritative contract: inspect the current checkout, callers, tests, and configuration before relying on any detail.

## Current Project Shape

- SciView is a PyQt5 desktop application for X-ray scattering workflows, using SciAnalysis for processing and supporting local files and configured Tiled sources.
- `main.py` composes the application and shares active workspace state. Feature tabs live under `tabs/`.
- The installable package is under `src/sciview/`. Its current areas include data models, source adapters, calibration, masking, processing, profiles, settings, sessions, and interface services.
- Reusable Qt viewers, tools, and utilities live under `src/sciview/interfaces/stable_qt/`; shared application presentation is in `src/sciview/interfaces/theme/app_style.py`. The image viewer uses PyQtGraph.
- Processing backends and SciAnalysis integration belong under `src/sciview/processing/`, rather than being reimplemented in tab event handlers.
- The CMS profile data is stored in `src/sciview/profiles/data/profile_cms.yaml`; `cms_profile.py` loads/exposes that configuration. Do not move profile values back into a second hard-coded source.
- `pyproject.toml` uses setuptools with a `src` package layout and declares Python `>=3.12`. `pixi.toml` manages the development environment and defines `launch-app` as `python -m sciview.launchers app` with `PYTHONPATH=src`.

## Change Guidance

- Trace the active flow from tab or launcher to the service/backend that computes, mutates, or owns the behavior. Do not assume all tabs should inherit a particular widget base class.
- Keep UI coordination in tabs and reusable/domain behavior with the existing package owner. Reuse a viewer, service, style helper, backend, or adapter only after confirming its current contract and callers.
- Preserve the boundary between canonical UI/workflow data and SciAnalysis-specific inputs where the current processing API defines one. Do not recreate a second mutable copy of the same recipe or state.
- Keep facility-specific behavior in the profile/configuration or source adapter that owns it. Do not speculate about other facilities or folder conventions.
- Preserve platform-specific launcher behavior and non-destructive update semantics. Check both platform implementations when changing shared startup/update behavior.
- Follow the codebase's current native Qt/AppStyle conventions; avoid stale Matplotlib-canvas and `BaseImageTab` instructions from older notes unless the exact code path still uses them.

## Environment And Checks

- Confirm the current environment and task definitions before suggesting commands. Pixi is the documented development workflow; the project also has Python package metadata.
- The checked `pyproject.toml` declares pytest as a development extra and configures `testpaths = ["tests"]`. A `tests/` directory exists locally with pytest coverage for most backend modules (data models, calibration/mask I/O, processing recipes, reduction/transform, batch processing, sources). Note: this checkout's `.gitignore` ignores `tests/`, so a fresh clone or a public mirror may not show it even though pytest runs it locally — verify locally with `pixi run pytest -q` rather than assuming from `git status`/`git ls-files` alone.
- Keep runtime probes focused and local. Add community-facing tests for important supported behavior and specific regressions, not an exhaustive AI-generated suite.
- Choose checks from the touched subsystem and current project configuration. Do not treat historical commands or file paths in collected notes as current without verification.
