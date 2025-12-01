# SciAnalysis GUI — Overview and usage

Purpose
-------
SciAnalysis GUI is a modular PyQt5 application that integrates CFN/SciAnalysis (https://github.com/CFN-softbio/SciAnalysis) X-ray scattering functionality with an interactive graphical frontend. The project provides on-the-fly data inspection and light-weight analysis workflows (calibration, ring-center finding, 1D profiling) while supporting local files and NSLS-II tiled data sources.

Design and architecture
------------------------
- Configuration-driven: beamline-specific settings (detectors, tiled profiles, calibration defaults) are stored in `config/beamline_config.py` so the same codebase can be reused across beamlines by updating configuration only.
- Tab-based UI: features are organized into independent tabs under `tabs/`. Each tab implements UI and interacts with shared tools and managers for heavy processing.
- Tools vs UI separation: numerical routines and algorithms live in `tools/` (for example `ring_center.py`), and are intentionally decoupled from Qt code to remain testable.
- Centralized clients and helpers: `utils/tiled_client.py` centralizes tiled connectivity, caching, and image extraction. `ImageSessionManager` (used by the Image Browser) centralizes session state and metadata.
- Centralized styling: `config/app_style.py` provides `AppStyle` and helper functions so the visual theme and layout ratios are consistent across tabs.

Repository layout (high level)
-----------------------------
```
SciAnaGui/
├── main.py                      # GUI entrypoint
├── config/                      # beamline configuration and app style
├── tabs/                        # UI tabs (calibration, image browser, ...)
├── tools/                       # numeric/analysis algorithms
├── utils/                       # shared clients and helpers (tiled client, image utils)
├── standards/                   # diffraction standards database
├── dev/                         # developer notes (devlog)
└── testdata/                    # sample inputs used for testing
```

Key features (current)
----------------------
- Image Browser
    - File, folder and tiled loading modes.
    - Background loader thread for non-blocking I/O.
    - Session manager that tracks loaded images and metadata.
    - Image-shape normalization utilities for common detector/tiled formats.

- TiledClientManager (`utils/tiled_client.py`)
    - Profile-driven connections with optional authentication.
    - Cached client instances and validation.
    - Image extraction and metadata packaging by scan ID + detector.
    - Graceful fallback if `tiled` is not installed.

- Calibration tab
    - Beam center and detector geometry controls.
    - Multi-point ring-center calculation UI and update action.
    - 1D profile plotting with optional standards overlay from `standards/`.

- AppStyle and UI utilities
    - Central palette, fonts and widget style templates.
    - Splitter layout helpers and convenience functions to keep the UI consistent.

Usage example (quickstart)
--------------------------
1. Prepare an environment with required packages (PyQt5, matplotlib, numpy). Install `tiled` if you want tiled access.

2. Edit `config/beamline_config.py` to match your beamline defaults (detectors, `DEFAULT_CALIBRATION`, `TILED_PROFILES`).

3. Launch the GUI from the repository root:

```bash
python main.py
```

4. In the Image Browser tab:
    - Load a single file or multiple files, or point to a folder with a matching pattern.
    - If tiled is available and configured, select a tiled profile and load a scan by ID.
    - Use the session manager to navigate images and export session lists.

5. Open the Calibration tab to inspect beam center, run ring-center calculations, adjust detector geometry, and view 1D profiles.

Configuration notes
-------------------
- `config/beamline_config.py` controls:
    - Detector configurations (pixel size, masks), default calibration parameters, and tiled profiles.
    - File naming patterns and export preferences.
- Updating this file is the primary step to adapt the GUI to a new beamline.

Testing and reliability notes
----------------------------
- The project intentionally keeps numerical logic in `tools/` to make unit testing straightforward.
- Tiled functionality checks for the `tiled` package at runtime; if missing, tiled operations are disabled with clear messaging.
- Image-shape conversion covers common dimensionalities used by tiled servers and detectors, but rare/custom formats may require additional conversion helpers.

Roadmap / future work
---------------------
- Additional analysis tabs (batch processing, automated reduction, fit-based analysis).
- Persist session state and thumbnails for long-running user sessions.
- Add a thumbnail cache and lazy-loading strategy for very large image sets.
- Improve onboarding: example beamline configs, a guided tiled-profile setup, and a developer setup script (conda/pip environment specification).

Contact and contribution
------------------------
Contributions are welcome. Please open an issue or a PR with a clear description of the change and any test/data needed to validate it.

