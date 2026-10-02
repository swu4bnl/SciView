# SciView User Guide

SciView is a desktop application for viewing and processing 2D X-ray scattering data. A typical workflow is:

1. Load an image or scan.
2. Check or create a calibration.
3. Create a mask if needed.
4. Preview a reduction or transform.
5. Export the result or send the settings to Batch.

## Start SciView

Use the launcher for your platform:

- Windows: double-click `Launch-SciView-win64.cmd`.
- macOS: open `Launch-SciView-macOS.command`.
- Linux: run `./Launch-SciView-linux.sh`.

On the first launch, allow the launcher to install Pixi if prompted. The launcher may also offer a SciView update. It safely skips updates that conflict with local work.

## Main Window

SciView contains these tabs:

- **Image Browser** loads files from local or mounted storage.
- **Tiled Browser** searches and loads data from a configured Tiled catalog.
- **Calibration** adjusts detector geometry and beam center.
- **Mask Editing** creates and combines mask layers.
- **Reduction** previews and exports 1D results.
- **Transform** previews and exports transformed 2D images.
- **Batch** applies one or more operations to a list of files.
- **Info** summarizes the current shared data and settings.

The buttons beside the tabs switch the theme, refresh the current tab, and clear saved session data. The status bar shows progress and errors.

## Load Data

### Local Files

1. Open **Image Browser** and select **Open Folder**.
2. Choose a folder and select an image from the file list.
3. Use the filename filter when the folder contains unrelated files.
4. Adjust the display range, scale, or colormap if needed. The magic wand tool can help automatically select the color range.

The selected image is shared with the analysis tabs when you switch tabs.

### Tiled Data (On development)

1. Open **Tiled Browser** and choose a catalog.
2. Log in if required.
3. Search by scan ID or by cycle and proposal.
4. Select a result and choose **Load**.
5. For stacked data, select the frame you want to use.

The loaded image or frame is shared with the analysis tabs.

## Calibration

Use **Calibration** to set the beam center, detector distance, pixel size, wavelength, and detector orientation.

1. Load an image and open **Calibration**.
2. Check the beam-center marker and current parameters.
3. If needed, right click to select points on a diffraction ring and calculate a new center, or use middle-click to pick the center manually.
4. Compare the 1D profile with a standard material when available.
5. You can use the 1D profile to verify the calibration against a standard material, or adjust the parameters until the profile matches the expected pattern.
6. Export the calibration when the geometry is correct.

## Mask Editing

Masks identify pixels that should be excluded from processing.

1. Load an image and open **Mask Editing**.
2. Create masked regions with a threshold or a drawing tool.
3. Add more layers when separate regions need to be reviewed independently.
4. Export the combined mask when finished.

Useful mask controls:

- **Brush**, shape tools, and **Smart Fill** add masked pixels.
- **Eraser** removes masked pixels. Hold Alt to temporarily invert the active drawing effect.
- **OR** adds a layer to the combined mask; **AND** keeps only its overlap with the preceding result.
- Layers are combined from top to bottom. Hidden layers are not included.
- Undo and Redo apply to drawing and layer refinement changes.

## Reduction

Use **Reduction** to create a 1D result from the current image.

1. Confirm the calibration and mask sources.
2. Choose an operation: Circular Average, Sector Average, Line I(q) at Chi, or Line I(chi) at Q.
3. Adjust only the parameters needed for the selected operation.
4. Choose **Refresh Preview** to review the result.
5. Choose **Export Data** to save it, or **Send to Batch** to reuse the settings on multiple files.

Reduction angles follow the screen convention: `0 deg` points right and `+90 deg` points up.

## Transform

Use **Transform** to create a transformed 2D image.

1. Confirm the calibration and mask sources.
2. Choose **Q Image**, **Q-Phi Image**, or **Qr-Qz Image**.
3. Set the output bins and ranges as needed.
4. Refresh the preview and inspect the result.
5. Choose **Export Data** to save it, or **Send to Batch** to reuse the settings.

## Batch Processing

Batch uses the files loaded in **Image Browser**.

1. Open **Batch** and refresh the file list if needed.
2. Add reduction or transform operations to the protocol queue.
3. Reorder the queue and adjust selected protocol parameters when needed.
4. Choose the plot output style if needed.
5. Select **Run Batch**.

The progress bar, output log, and results table show the status of each operation. Recipes (On development) can be saved and loaded for repeated workflows. Use **Stop** to cancel a running batch.

## Info

Open **Info** to review the image, calibration, mask, and processing state currently shared across SciView.
