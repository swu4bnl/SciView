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

On the first launch, approve the installation of required components if prompted.

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
4. Adjust the display range, scale, or colormap if needed. Choose **Auto** to set the color limits from the image automatically.

The selected image is shared with the analysis tabs when you switch tabs.

### Image Annotations (Experimental)

Use **Mark** beside Pan/Zoom in the Image Browser viewer toolbar:

- New marks default to green with a 5 px stroke, distinct from the red mask
  overlay. Color and width remain adjustable.
- Click **Mark** to expand a horizontal drawing toolbar directly above the
  main viewer toolbar and draw with the last-used tool (initially Brush).
  Choose Brush, Line, Rectangle, Circle, Polygon, or Text directly in this strip.
  It stays open while drawing so switching tools takes one click.
- Drag to draw strokes and shapes. Circles start at their center.
  For polygons, click vertices and press Enter or double-click to finish.
  For text, click the image, type the label in place, and press Enter.
  Escape or clicking elsewhere discards unfinished text.
- Choose Pan or Zoom, press Escape, right-click, or click **Mark**
  again to leave drawing and collapse the strip. Existing marks stay visible.
- The strip groups drawing tools, a color swatch, **Width**, **Opacity**,
  and compact **Undo**, **Redo**, **Show marks**, and **Clear marks** controls.
  Hover over an icon for its purpose or keyboard shortcut. On narrow windows,
  scroll the strip horizontally to reach the remaining controls.
  Ctrl+Z and Ctrl+Y undo/redo annotations while the viewer has focus.
  Clearing is undoable. **Show marks** temporarily hides the layer without closing
  the strip; turn it back on or select a drawing tool to reveal the marks.

One shared layer stays in the same detector pixel coordinates while browsing images,
including during playback. Marks outside a smaller image are hidden, not deleted.
Starting to draw pauses playback. The layer is local to Image Browser and lasts
until the tab is rebuilt or the application closes; annotations are not saved in
session files. Viewer copy/save includes visible marks, but raw image exports,
masks, calibration, reductions, transforms, and batch processing do not use them.

### Tiled Data (In development)

1. Open **Tiled Browser** and choose a catalog.
2. Choose **Login** if required. SciView displays an authorization code and sign-in link in a separate window.
3. Copy the code, choose **Open sign-in page**, and paste the code into the NSLS-II sign-in page.
4. Search by scan ID or by cycle and proposal.
5. Select a result and choose **Load**.
6. For stacked data, select the frame you want to use.

The loaded image or frame is shared with the analysis tabs.

## Calibration

Use **Calibration** to set the beam center, detector distance, pixel size, wavelength, and detector orientation.

1. Load an image and open **Calibration**.
2. Check the beam-center marker and current parameters.
3. If needed, right click to select points on a diffraction ring and calculate a new center, or use middle-click to pick the center manually.
4. Compare the 1D profile with a standard material when available. Adjust the parameters until the profile matches the expected pattern.
5. Export the calibration when the geometry is correct.

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
- **Remove** deletes the selected layer. **Clear Layers** deletes all layers.
- Undo and Redo apply to drawing and layer refinement changes.

Drawing shows a translucent Qt preview without changing mask pixels or processing
state during the gesture. Release the mouse to apply a brush stroke or shape as
one undoable edit. Polygon vertices remain a preview until **Finish Polygon**,
Enter, or a double-click. Escape cancels the pending gesture without changing the
mask. Switching tools, layers, or the displayed image also cancels pending work.
The preview indicates the gesture, not the final OR/AND combination; restore
gestures use a contrasting color, and the combined mask appears after committing.
Smart Fill shows its seed while held and computes the region once on release.

Points beyond the image but inside the plot snap to the nearest image edge or
corner. Moving outside the plot pauses the gesture; releasing there commits at
the last accepted point. Smart Fill requires a seed inside the image.

### Shared Drawing Controls

Annotations and masks use the same gesture/geometry engine and keyboard command
bindings. Their outputs and undo histories remain separate: annotations stay
display-only, and mask pixels change only when a gesture is committed.

- **B**, **L**, **R**, **C**, **P** select Brush, Line, Rectangle, Circle, and Polygon.
  Selecting the current tool again does not turn it off.
- **T** selects annotation Text; **E** and **F** select mask Eraser and Smart Fill.
- **Enter**, including keypad Enter, finishes a polygon; double-clicking adds the
  final vertex and finishes it.
- **Ctrl+Z** undoes; **Ctrl+Y** or **Ctrl+Shift+Z** redoes. Either first discards an
  unfinished gesture before changing the active editor's history.
- **Escape** cancels pending work. In annotations it also exits Mark mode.
- **Alt** temporarily inverts only the focused mask editor's effect.

Shortcuts apply within the annotation viewer or Mask Editing tab, never a hidden
tab. Tool shortcuts in the annotation viewer also open Mark mode. Text fields,
numeric inputs, and inline annotation labels retain their normal editing keys.
Both editors pause drawing outside the plot; masks additionally snap off-image
points to edge pixels, while annotations keep continuous coordinates and clip
to the image boundary.

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
3. Reorder the queue and adjust selected protocol parameters when needed. Use **Remove** to delete one queued protocol, or **Clear Queue** to delete all of them.
4. Choose the plot output style if needed.
5. Select **Run Batch**.

The progress bar, output log, and results table show the status of each operation. Recipes (In development) can be saved and loaded for repeated workflows. Use **Stop** to cancel a running batch.

## Info

Open **Info** to review the image, calibration, mask, and processing state currently shared across SciView.
