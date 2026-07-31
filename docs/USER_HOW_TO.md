# SciView User How-To Guide

This guide is for general SciView users who want to load scattering images, inspect them, calibrate geometry, build masks, preview reductions, and export results from the desktop app.

The format is intentionally tutorial-like: each page has an objective, a screenshot slot, labeled arrow callouts, and a short path to success. Replace each screenshot placeholder with an annotated capture of the matching page.

## Before You Start

You need:

- SciView installed and launched.
- A local detector image folder, or access to a configured Tiled catalog.
- A calibration file if you already have one. If not, use the Calibration page to create or adjust one.
- A mask file if your workflow needs one. If not, use the Mask Editing page to create one.

Launch SciView with the launcher for your platform:

- Windows: `Launch-SciView-win64.cmd`
- macOS: `Launch-SciView-macOS.command`
- Linux: `Launch-SciView-linux.sh`

## Tutorial Screenshot Style

Use the same annotation style for every screenshot so the guide feels like one guided tour.

- Use red arrows for the next required action.
- Use blue arrows for optional settings.
- Use green outlines for buttons that complete a step.
- Label callouts with short letters: `A`, `B`, `C`.
- Keep text outside the main data image whenever possible.
- Capture the full SciView window for page overview screenshots.
- Capture cropped close-ups only when a control group is too small to read.

Suggested screenshot folder:

```text
docs/images/user-guide/
```

Suggested file names:

```text
01-launch-overview.png
02-image-browser.png
03-tiled-browser.png
04-calibration.png
05-mask-editing.png
06-reduction.png
07-transform.png
08-protocol-preview.png
09-update-buttons.png
```

## Page 1: Main Window Overview

![Main SciView window with annotated tabs](images/user-guide/01-launch-overview.png)

Arrow callouts to add:

- `A` - Main tabs. Move between Image Browser, Tiled Browser, Calibration, Mask Editing, Reduction, Transform, and Protocol Preview.
- `B` - Refresh button. Reloads the current tab and clears relevant cached state.
- `C` - Update SciView button. Pulls the latest SciView source when available.
- `D` - Update SciAnalysis button. Updates the active SciAnalysis source or package.
- `E` - Status bar. Shows loading messages, errors, and resource usage.

Your goal on this page is to understand that SciView works from left to right: load an image, share it with the rest of the app, calibrate, mask, reduce, transform, and export.

## Page 2: Image Browser

![Image Browser page with annotated controls](images/user-guide/02-image-browser.png)

Use this page when your data are on your computer or mounted file storage.

Arrow callouts to add:

- `A` - Open Folder. Choose the folder that contains image files.
- `B` - Filename Filter. Narrow the list with patterns such as `*.tif`, `*.tiff`, or `*.h5`.
- `C` - Image list. Select a file to preview it.
- `D` - Playback controls. Step through a folder or play the image sequence.
- `E` - Raw Image display. Inspect the selected image.
- `F` - Display controls. Adjust `vmin`, `vmax`, color map, and scale.
- `G` - Session Images. Review images already loaded into the current session.

Steps:

1. Click `Open Folder`.
2. Select your image directory.
3. Set `Filename Filter` if the folder contains mixed files.
4. Click an image in the list.
5. Adjust display controls until the image is readable.
6. Switch to Calibration, Mask Editing, Reduction, or Transform. SciView automatically shares the current browser image when you leave this page.

Success check: the selected image appears in the other pages when you switch tabs.

## Page 3: Tiled Browser

![Tiled Browser page with annotated controls](images/user-guide/03-tiled-browser.png)

Use this page when your data come from a configured Tiled catalog.

Arrow callouts to add:

- `A` - Catalog selector. Choose the beamline or data catalog profile.
- `B` - Login. Authenticate before searching protected data.
- `C` - Scan ID search. Load a single scan or a scan range.
- `D` - Cycle and Proposal search. Find scans for an experiment.
- `E` - Filters. Narrow results by available metadata.
- `F` - Results table. Select the scan you want to inspect.
- `G` - Load. Download and display the selected scan image.
- `H` - Series controls. Step, play, stop, loop, or cancel loading/series preview.
- `I` - Frame slider. Select a frame in stacked image data.
- `J` - Metadata panel. Review scan metadata for the selected image.
- `K` - Auto-share behavior. The loaded image or selected frame is shared with the rest of SciView when you switch to another tab.

Steps for a scan ID:

1. Choose the catalog.
2. Click `Login` if required.
3. Enter a scan ID, or a start and end scan range.
4. Click the search button.
5. Select a result.
6. Click `Load`.
7. If the data are stacked, move the frame slider to the frame you want.
8. Switch to the destination analysis tab. SciView automatically shares the currently loaded frame.

Steps for proposal search:

1. Choose the catalog.
2. Enter `Cycle` and `Proposal`.
3. Open `Filters` only if you need to narrow the table.
4. Click the proposal search button.
5. Select a row, click `Load`, choose the desired frame if needed, then switch to the destination analysis tab.

Success check: the preview panel shows the selected image and metadata before you share it.

## Page 4: Calibration

![Calibration page with annotated controls](images/user-guide/04-calibration.png)

Use this page to set beam center, detector geometry, wavelength, and related calibration values.

Arrow callouts to add:

- `A` - Raw Image. Shows the current shared image.
- `B` - Beam center crosshair. Confirms the current beam center estimate.
- `C` - 1D Profiles. Shows calculated profiles and optional reference lines.
- `D` - Ring Center Calculation. Pick points on one diffraction ring to estimate the center.
- `E` - Point table. Review or edit ring points.
- `F` - Calculate. Compute ring center from selected points.
- `G` - Calibration Parameters. Edit beam center, orientation, tilt, distance, pixel size, wavelength, and energy.
- `H` - Calibrate. Apply the current calibration values.
- `I` - Export. Save the calibration as a reusable file.
- `J` - Standard Materials. Select a material to compare expected diffraction lines.
- `K` - Export 1D. Save the current profile data.

Steps:

1. Load an image from Image Browser or Tiled Browser, then switch to `Calibration`.
2. Switch to `Calibration`.
3. Inspect whether the beam center crosshair looks reasonable.
4. If the center needs adjustment, right-click points around a visible diffraction ring.
5. Click `Calculate`.
6. Review the updated center values in Calibration Parameters.
7. Adjust distance, pixel size, wavelength, or energy if needed.
8. Click `Calibrate`.
9. Use Standard Materials to compare expected lines against the 1D profile.
10. Click `Export` when the calibration is ready.

Success check: the 1D profile and reference material lines align with the expected diffraction features.

## Page 5: Mask Editing

![Mask Editing page with annotated controls](images/user-guide/05-mask-editing.png)

Use this page to hide detector gaps, hot pixels, beamstops, shadows, or other regions that should not be included in analysis.

Arrow callouts to add:

- `A` - Image with Mask Overlay. Shows the active mask on top of the image.
- `B` - Show Mask. Toggle mask visibility.
- `C` - Color and Transparency. Change how the mask overlay appears.
- `D` - Mask Layers. Add, remove, reorder, and select layers.
- `E` - Combine. Choose how visible layers combine into one mask.
- `F` - Threshold. Generate a mask from intensity limits.
- `G` - Filter. Apply Sobel or morphology operations to the active layer.
- `H` - Drawing Tools. Choose brush, line, rectangle, circle, or watershed fill.
- `I` - Mode. Choose whether drawing adds masked pixels or removes them.
- `J` - Size. Change brush or tool size.
- `K` - Open in GIMP. Send the mask to an external editor.
- `L` - Import mask. Bring an externally edited mask back into SciView.
- `M` - Export Selected Layer. Save only the active layer.
- `N` - Export Mask (All Layers). Save the combined mask for reduction or transform.

Steps:

1. Load an image from Image Browser or Tiled Browser, then switch to `Mask Editing`.
2. Switch to `Mask Editing`.
3. Click `Add` to create a new mask layer.
4. Use Threshold or Drawing Tools to mark invalid regions.
5. Use `Show Mask`, color, and transparency to inspect your edits.
6. Add extra layers for different mask types if that helps review.
7. Choose the combine mode.
8. Click `Export Mask (All Layers)`.

Success check: masked regions cover only the pixels you want excluded, and the exported mask can be loaded in Reduction or Transform.

## Page 6: Reduction

![Reduction page with annotated controls](images/user-guide/06-reduction.png)

Use this page to preview and export 1D reductions from the current image.

Arrow callouts to add:

- `A` - Image display. Shows the current image and reduction overlay.
- `B` - Reduction Preview. Shows the calculated 1D result.
- `C` - Plot Scale. Switch between linear, logx, logy, and loglog.
- `D` - Sources. Choose calibration and mask sources.
- `E` - Operation. Choose Circular Average, Sector Average, Line I(q) at Chi, or Line I(chi) at Q.
- `F` - Auto preview. Recalculate when settings change.
- `G` - Bins. Set output resolution.
- `H` - q range. Use automatic q range or set q min and q max manually.
- `I` - Sector controls. Set angle start and angle end for sector averages.
- `J` - Line Profile controls. Set the reference q or chi and the half-width.
- `K` - Preview. Run the preview manually.
- `L` - Export Data. Save the current reduction result.
- `M` - Export Recipe. Save the current reduction settings.

Steps:

1. Load an image from Image Browser or Tiled Browser, then switch to `Reduction`.
2. Create or load calibration.
3. Create or load a mask if needed.
4. Switch to `Reduction`.
5. Confirm the Sources panel uses the intended calibration and mask.
6. Pick an Operation.
7. Leave `Auto q-range` enabled for a first preview.
8. Click `Preview`, or let Auto preview update the plot.
9. Adjust bins, q range, sector angle, or line profile settings.
10. Click `Export Data` when the preview is correct.
11. Click `Export Recipe` if you want to reuse the same settings later.

Success check: the overlay on the image matches the region used to create the 1D plot.

Angle note for users: reduction angles use the screen convention `0 deg = right` and `+90 deg = up`.

## Page 7: Transform

![Transform page with annotated controls](images/user-guide/07-transform.png)

Use this page to preview and export transformed 2D maps such as q images, q-phi images, or qx-qz images.

Arrow callouts to add:

- `A` - Source image. Shows the current shared image.
- `B` - Transform Preview. Shows the transformed output.
- `C` - Sources. Choose calibration and mask sources.
- `D` - Operation. Choose Q Image, Q-Phi Image, or Qx-Qz Image.
- `E` - Auto preview. Recalculate when settings change.
- `F` - Q bins and Phi bins. Set output grid resolution.
- `G` - q range. Use automatic range or set q min and q max.
- `H` - phi range. Set phi min and phi max for Q-Phi output.
- `I` - Preview. Run the transform manually.
- `J` - Export Transform. Save the transformed result.

Steps:

1. Load an image from Image Browser or Tiled Browser, then switch to `Transform`.
2. Confirm calibration and mask sources.
3. Switch to `Transform`.
4. Pick the transform operation.
5. Use Auto preview for quick feedback.
6. Adjust q bins, phi bins, and ranges as needed.
7. Click `Export Transform`.

Success check: the transform preview updates and the exported file matches the selected operation.

## Page 8: Protocol Preview

![Protocol Preview page with annotated controls](images/user-guide/08-protocol-preview.png)

Use this page for workflow preview and export. Some parts are still under development, so use Reduction and Transform for the main interactive processing workflows.

Arrow callouts to add:

- `A` - Calibration & Mask. Load calibration and mask files for the workflow preview.
- `B` - Image Display. Choose color map and color limits.
- `C` - Export Settings. Set figure size, DPI, margins, font, and rendering options.
- `D` - Protocol Stack. Add, remove, reorder, and enable protocol steps.
- `E` - Protocol Parameters. Configure the selected protocol.
- `F` - Plot Settings. Set line width and log scale options.
- `G` - Export Format. Choose Python Script, JSON, or YAML.
- `H` - Preview Export. Inspect what will be exported.
- `I` - Export Workflow. Save the configured workflow.
- `J` - Run Preview. Run the protocol preview.
- `K` - Info tab. Review loaded image, calibration, mask, and protocol status.

Steps:

1. Load a shared image before opening this page.
2. Load calibration and mask files if needed.
3. Add protocols to the stack.
4. Select each protocol and review its parameters.
5. Choose export format.
6. Click `Preview Export`.
7. Click `Export Workflow` when ready.
8. Use `Run Preview` only after the workflow settings look correct.

Success check: the Info tab lists the expected image, calibration, mask, and protocol stack.

## Page 9: Update and Refresh Buttons

![Top-right update buttons with annotations](images/user-guide/09-update-buttons.png)

Use these buttons when you need to reload a tab or update installed code.

Arrow callouts to add:

- `A` - Refresh current tab. Reloads the selected page. On Image Browser, it also clears session cache.
- `B` - Update SciView. Runs a source update for the SciView checkout.
- `C` - Update SciAnalysis. Updates the active SciAnalysis source or package.

Steps:

1. Use Refresh if a page is stale or you want to reload its controls.
2. Use Update SciView only when you intend to update the application code.
3. Use Update SciAnalysis only when you intend to update the processing dependency.
4. Restart SciView after source or package updates complete.

Success check: the status bar reports whether the refresh or update succeeded.

## Common Workflows

### Workflow A: Load a Local Image and Export a Reduction

1. Go to `Image Browser`.
2. Click `Open Folder` and select your data folder.
3. Pick an image, then switch to `Calibration`.
4. Go to `Calibration` and confirm or export calibration.
5. Go to `Mask Editing` if you need a mask, then export the combined mask.
6. Go to `Reduction`.
7. Choose calibration and mask sources.
8. Select `Circular Average` for a first result.
9. Click `Preview`.
10. Click `Export Data`.

### Workflow B: Load a Tiled Image and Inspect Metadata

1. Go to `Tiled Browser`.
2. Choose the catalog and log in.
3. Search by scan ID or by cycle and proposal.
4. Select a row in the Results table.
5. Click `Load`.
6. Review the metadata panel.
7. Select the desired frame if the scan is stacked.
8. Switch to the tab where you want to inspect or process the loaded image.

### Workflow C: Make a Mask for Bad Pixels or Beamstop Shadow

1. Share an image from Image Browser or Tiled Browser.
2. Go to `Mask Editing`.
3. Add a mask layer.
4. Choose a drawing tool.
5. Set Mode to add masked pixels.
6. Draw over detector gaps, beamstop shadows, or bad regions.
7. Toggle `Show Mask` to compare with and without the overlay.
8. Export the combined mask.

## Quick Troubleshooting

| Problem | What to Try |
| --- | --- |
| Other tabs do not show the image | Return to Image Browser or Tiled Browser, confirm the image is selected or loaded, then switch back to the destination tab. |
| Image looks blank | Adjust `vmin`, `vmax`, color map, and scale. Try log scale for scattering data. |
| Tiled search fails | Confirm catalog, login status, cycle, proposal, scan ID, and network access. |
| Calibration result looks wrong | Check beam center, distance, pixel size, wavelength, and selected standard material. |
| Mask hides too much | Lower transparency, inspect layers one at a time, and use remove/unmask drawing mode. |
| Reduction overlay and plot do not match | Confirm the correct calibration and mask source, then rerun Preview. |
| Export buttons are disabled or fail | Make sure an image is loaded and the current preview has run successfully. |

## Screenshot Capture Checklist

Before publishing this guide, capture and annotate these screenshots:

- `01-launch-overview.png` - full app window immediately after launch.
- `02-image-browser.png` - Image Browser with a loaded folder and visible image.
- `03-tiled-browser.png` - Tiled Browser with search results, preview, and metadata.
- `04-calibration.png` - Calibration with a visible ring, profile, and calibration controls.
- `05-mask-editing.png` - Mask Editing with at least one visible mask layer.
- `06-reduction.png` - Reduction with an overlay and 1D preview result.
- `07-transform.png` - Transform with a generated transform preview.
- `08-protocol-preview.png` - Protocol Preview with at least one protocol in the stack.
- `09-update-buttons.png` - crop of the top-right tab corner buttons.

For each screenshot, verify:

- All arrow labels in the image match the callout list in this guide.
- Sensitive proposal names, usernames, paths, tokens, or private sample names are hidden.
- Text is large enough to read in the final document.
- The screenshot shows realistic data or synthetic demo data, not a private user dataset.