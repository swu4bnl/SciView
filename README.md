# SciView

SciView is a PyQt5 application for interactive 2D X-ray scattering data inspection and analysis. It is designed for beamline workflows where users need fast image loading, calibration, mask editing, and data reduction protocol preview (under development) in one desktop interface.

## Core capabilities

- Image browsing from local files and Tiled data services.
- Tiled Browser workflow for proposal/cycle search, detector selection, image preview, metadata display, and series playback.
- Calibration editing for beam center, detector distance, wavelength, and related parameters.
- Layered mask creation and editing with interactive drawing tools.
- Protocol preview workflows for SciAnalysis-driven processing (under development).

## Application structure

- [main.py](main.py): application entry point and tab orchestration.
- [src/sciview/settings/](src/sciview/settings): application runtime settings.
- [src/sciview/interfaces/theme/](src/sciview/interfaces/theme): UI style definitions.
- [src/sciview/interfaces/stable_qt/](src/sciview/interfaces/stable_qt): Qt-specific tools and utility modules used by tabs.
- [tabs/](tabs): main GUI modules (Image Browser, Tiled Browser, Calibration, Mask, Protocol).
- [src/sciview/](src/sciview): backend package modules and launcher interface.
- [src/sciview/calibration/](src/sciview/calibration): calibration I/O and diffraction standards.

## Core dependencies

The application depends on a scientific Python stack and the following key project dependencies:

- SciAnalysis: https://github.com/CFN-softbio/SciAnalysis
- tiled: https://github.com/bluesky/tiled
- PyQt5: https://pypi.org/project/PyQt5/
- NumPy: https://numpy.org/
- SciPy: https://scipy.org/
- Matplotlib: https://matplotlib.org/
- Pillow: https://python-pillow.org/
- PyYAML: https://pyyaml.org/

Dependency definitions are managed in [pixi.toml](pixi.toml) and [pyproject.toml](pyproject.toml).

## Quick start

### Recommended (pixi)

Run once from the repository root:

```bash
./scripts/bootstrap_env.sh
```

Then launch by platform:

- Linux: `./Launch-SciView-linux.sh`
- macOS: `./Launch-SciView-macOS.command`
- Windows: `Launch-SciView-win64.cmd`

The platform launchers configure the environment and start the application using the standard pixi task.

### Alternative (local venv)

If pixi is unavailable, use the fallback bootstrap mode:

```bash
./scripts/bootstrap_env.sh --mode venv
```

Then start manually:

```bash
PYTHONPATH=src ./.venv/bin/python main.py
```

## User workflow overview

### Image Browser

- Load single images and folders.
- Navigate image sessions and sync selected images to other tabs by clicking "Use This Image".

### Tiled Browser

- Log in to a configured Tiled service and choose a catalog profile.
- Search by cycle and proposal ID using profile-configured metadata mappings.
- Apply optional filters such as `measure_type`, `sample_savename`, and experiment alias directory.
- Select a detector, load image plus metadata on demand, and preview stacked image frames with the frame slider.
- Use "Use This Image" to sync the selected Tiled frame to the rest of the application.

### Calibration

- Edit geometry and wavelength parameters.
- Use ring-center tools and profile overlays for validation.

### Mask Editing

- Build masks with multiple layers and drawing tools.
- Import, combine, and export mask artifacts.

### Protocol Preview (under development)

- Configure and run protocol previews using SciAnalysis-compatible data flow.

## Configuration

Beamline-specific behavior is centralized in [src/sciview/profiles/](src/sciview/profiles) and application runtime settings under [src/sciview/settings/](src/sciview/settings). This includes detector defaults, calibration defaults, file pattern handling, Tiled profile integration, metadata field mappings, and Tiled timeout settings.

## Troubleshooting

- If startup fails, run [scripts/bootstrap_env.sh](scripts/bootstrap_env.sh) again to refresh the environment.
- If Tiled access fails, verify connectivity, login state, and profile settings in [src/sciview/profiles/](src/sciview/profiles) and [src/sciview/settings/app_settings.py](src/sciview/settings/app_settings.py).
- If SciAnalysis operations fail, verify package availability in the active environment and confirm SciAnalysis import paths.
- If reduction overlays or angular line cuts do not match what is shown on screen, check [docs/ANGLE_CONVENTION_GUIDE.md](docs/ANGLE_CONVENTION_GUIDE.md) before patching angle offsets.

## Development notes

- Keep UI logic in [tabs/](tabs) and reusable processing logic in [src/sciview/interfaces/stable_qt/](src/sciview/interfaces/stable_qt) or [src/sciview/](src/sciview).
- Keep shared utilities in [src/sciview/interfaces/stable_qt/utils/](src/sciview/interfaces/stable_qt/utils) and [src/sciview/sources/](src/sciview/sources).
- Update beamline defaults and Tiled metadata mappings in profile/settings modules rather than hardcoding values in tabs.
- Use local tests and smoke checks during development, but keep test scripts and private fixtures outside the public release tree.

For additional implementation details, see [docs/](docs).

