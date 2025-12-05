# SciAnaGui — Quick start and user guide

What the app does
-----------------
SciAnaGui is a compact PyQt5 application for viewing and doing light data analysis of 2D X‑ray scattering images. It focuses on practical, repeatable tasks you need at the beamline:

- Browse and display 2D X‑ray scattering images from local files or a tiled data service.
- Adjust calibration (beam center, distance, wavelength) and inspect 1D profiles.
- Create and edit layered masks with an interactive paint tool.
- Run small analysis tasks (under development).

The codebase is structured to keep instrument-specific settings in configuration files so the same software can be reused across beamlines.

Where things are
-----------------------------
- `main.py` — start the GUI
- `config/` — beamline configuration and UI styling
- `tabs/` — UI components (Image Browser, Calibration, Mask Editor, Data Reduction)
- `tools/` — numerical and analysis routines
- `utils/` — shared helpers (image utilities, tiled client, cache manager)
- `standards/` — diffraction standard values used for overlays

Quick setup
--------------------
1. The app expects PyQt5 and common scientific Python packages. If you don’t have that, create a local venv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install PyQt5 numpy matplotlib pillow
```

2. Install SciAnalysis (https://github.com/CFN-softbio/SciAnalysis).

2. (Optional) Install `tiled` if you want to load images from a tiled data service.

3. Run the app from the repository root:

```bash
python main.py
```

Basic user workflows
--------------------

Image Browser
- Load a single file, a folder, or use a tiled profile if configured.
- The session manager tracks loaded images so you can step through and export session lists.
- You can sync the current image to other tabs (Calibration, Mask, Data Reduction) with the "Use This Image" button.

Calibration
- Use the Calibration tab to edit beam center, sample-to-detector distance, and wavelength.
- You can use a simple ring-center finding tool to help locate the beam center.
- 1D profiles and common standard overlays are available for quick checks to inspect data quality.

Mask Editor
- Masks are layer-based: create layers, paint (add/remove), toggle visibility, combine, and export.
- You can also load instrument default masks, generate threshold-based masks, and edit masks in GIMP.

Data Reduction (under development)
- For common batch-like data reduction workflows.

Configuration
-------------
Edit `config/beamline_config.py` to adapt to your instrument. Important keys:
- `DETECTOR_CONFIGS` — known detectors and defaults
- `DEFAULT_CALIBRATION` — starting calibration values
- `FILE_PATTERNS` — file naming patterns to recognize
- `SCIANALYSIS_PATH` — optional path if SciAnalysis is required

Troubleshooting and tips
------------------------
- If the GUI won’t start: ensure PyQt5 is installed or use your facility’s environment loader.
- SciAnalysis features are required. If missing, some calibration and reduction features will be limited; set `SCIANALYSIS_PATH` if needed.
- This app attempts to convert various image input types (NumPy arrays, memoryviews, SciAnalysis objects) for display. If you encounter unsupported formats, consider adding conversion helpers in `utils/image_utils.py`.
- For large image collections prefer tiled profiles or a machine with enough memory; the app includes basic caching helpers but is not an image database.

Contributing and development notes
---------------------------------
- Keep scientific code in `tools/` and UI code in `tabs/`.
- Use `utils/` for shared helpers (image conversion, caching, tiled client).
- Change beamline defaults in `config/beamline_config.py` rather than editing core code.

For developer notes and tests, see `dev/` and `testscript/`.

License and contact
-------------------
This repository is maintained by the project owner. For licensing or deployment questions, open an issue or contact the repository maintainer.

