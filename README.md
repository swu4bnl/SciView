# SciView

SciView is a Python-first desktop workbench for 2D X-ray scattering workflows. It combines local file browsing, Tiled data access, calibration inspection, mask editing, reduction previews, and SciAnalysis-backed protocol experiments in one PyQt5 application.

The project is being refactored toward a backend-first architecture: GUI tabs collect user choices and display results, while reusable logic lives under [src/sciview/](src/sciview). CMS is the first supported beamline profile, but core modules should remain beamline-neutral.

## What You Can Do

- Browse detector images from local folders or configured Tiled catalogs.
- Preview images with PyQtGraph axes, locked aspect ratio, histogram color limits, colormap controls, and shared display settings.
- Select a local or Tiled image once and let SciView share it automatically when you switch to analysis tabs.
- Adjust calibration parameters and inspect beam-center overlays and 1D profiles.
- Build layered masks with PyQtGraph drawing tools for brush, line, rectangle, circle, and watershed fill workflows.
- Preview reductions and transforms using shared image, calibration, and mask state.
- Experiment with SciAnalysis protocol previews while the processing adapter continues to mature.

For a step-by-step user workflow, see [docs/USER_HOW_TO.md](docs/USER_HOW_TO.md).

## Quick Start

On Windows, double-click [Launch-SciView-win64.cmd](Launch-SciView-win64.cmd). The first launch uses Pixi to prepare SciView's Python environment automatically, then starts the app. If Windows asks whether to install Pixi, choose `Y`.

On Linux or macOS, run once from the repository root to prepare the environment:

```bash
./scripts/bootstrap_env.sh
```

Then launch SciView with the script for your platform:

- Linux: `./Launch-SciView-linux.sh`
- macOS: `./Launch-SciView-macOS.command`
- Windows: `Launch-SciView-win64.cmd`

The launchers configure the Pixi-managed Python environment and start the application.

### Launcher Behavior

All three platform launchers are setup-first launchers intended for end users.

- They check for source updates at startup with git pull --ff-only when the repository is a git checkout.
- They print terminal progress so users can see update checks and dependency setup.
- They run pixi install automatically before launching the app.

Platform entry points:

- macOS: [Launch-SciView-macOS.command](Launch-SciView-macOS.command) -> [scripts/run_sciview_unix.sh](scripts/run_sciview_unix.sh)
- Linux: [Launch-SciView-linux.sh](Launch-SciView-linux.sh) -> [scripts/run_sciview_unix.sh](scripts/run_sciview_unix.sh)
- Windows: [Launch-SciView-win64.cmd](Launch-SciView-win64.cmd) -> [scripts/run_sciview_windows.ps1](scripts/run_sciview_windows.ps1)

Launcher options:

- Disable source auto-update for one run:
	- macOS/Linux: --no-auto-pull
	- Windows: -NoAutoPull
- Prepare dependencies without launching the GUI:
	- macOS/Linux: --setup-only
	- Windows: -SetupOnly

Environment variables:

- SCIVIEW_AUTO_PULL=0 disables source auto-update.
- SCIVIEW_KEEP_SHELL_OPEN=1 keeps terminal open after app exit (enabled by default in [Launch-SciView-macOS.command](Launch-SciView-macOS.command)).

For advanced/manual setup, use the fallback virtual environment mode:


```bash
./scripts/bootstrap_env.sh --mode venv
```

Then start manually:

```bash
PYTHONPATH=src ./.venv/bin/python main.py
```

## Everyday Workflow

1. Load a local image in Image Browser or load a scan/frame in Tiled Browser.
2. Switch to Calibration, Mask Editing, Reduction, or Transform. The current browser image is shared automatically on tab switch.
3. Adjust shared display settings with the image histogram, `vmin`, `vmax`, colormap, and linear/log scale controls.
4. Calibrate geometry or load an existing calibration.
5. Build or load a mask if the analysis needs one.
6. Preview reductions or transforms, then export data or recipes.

## Repository Map

- [main.py](main.py): application entry point and shared-state tab orchestration.
- [tabs/](tabs): current PyQt5 tab widgets.
- [src/sciview/settings/](src/sciview/settings): application, viewer, and runtime configuration.
- [src/sciview/profiles/](src/sciview/profiles): beamline profiles and detector defaults.
- [src/sciview/sources/](src/sciview/sources): local file and Tiled source adapters.
- [src/sciview/processing/](src/sciview/processing): processing request models and SciAnalysis adapter work.
- [src/sciview/interfaces/stable_qt/](src/sciview/interfaces/stable_qt): reusable Qt viewer, drawing, and utility modules.
- [tests/](tests): pytest coverage using synthetic data and mocked services.

## Dependencies

Dependency definitions are managed in [pixi.toml](pixi.toml) and [pyproject.toml](pyproject.toml). Key runtime dependencies include PyQt5, PyQtGraph, NumPy, SciPy, Matplotlib, Pillow, PyYAML, Tiled, and SciAnalysis.

## Development Checks

When available, run:

```bash
pixi run pytest
pixi run python -m ruff check src tests
```

Focused GUI migration checks often use:

```bash
pixi run pytest tests/test_image_viewer.py
```

## Configuration Notes

- Beamline-specific behavior belongs in [src/sciview/profiles/](src/sciview/profiles).
- Application and viewer defaults belong in [src/sciview/settings/](src/sciview/settings).
- Core modules should not hard-code CMS paths, proposal IDs, filename rules, or mounted beamline storage.
- GUI-facing angle behavior follows the display convention documented in [docs/ANGLE_CONVENTION_GUIDE.md](docs/ANGLE_CONVENTION_GUIDE.md): `0 deg = right`, positive rotation is counterclockwise, and `+90 deg = up`.

## Troubleshooting

- If startup fails, rerun [scripts/bootstrap_env.sh](scripts/bootstrap_env.sh) to refresh the environment.
- If Tiled access fails, verify connectivity, login state, profile settings, and [src/sciview/settings/app_settings.py](src/sciview/settings/app_settings.py).
- If SciAnalysis operations fail, verify package availability and the configured SciAnalysis source.
- If another tab does not show the expected image, return to the browser tab, confirm the desired image/frame is selected or loaded, then switch back to the analysis tab.

