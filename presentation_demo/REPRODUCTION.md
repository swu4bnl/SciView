# SciView presentation: playback and reproduction

## Deliverables

- [PowerPoint slide](SciView_workflows.pptx): one 16:9 slide with four embedded GIFs.
  Use Slide Show mode; the editing canvas normally shows only a still frame.
- [Browser slide](SciView_workflows.html): keep it beside the four GIFs.
  Press **F** for fullscreen, **Space** to replay, or click a panel to enlarge.
  The controls also provide freeze/resume.
- [Static preview](SciView_workflows_preview.png): 1920 x 1080; not animated.
- [Portable bundle](SciView_presentation_bundle.zip): extract before opening the
  browser slide.
- Four independent GIFs: `image_browsing.gif`, `calibration.gif`,
  `mask_making.gif`, and `batch_processing.gif`.

All demonstrations use screenshots rendered by the actual SciView Qt application,
not mock interfaces. Captions, camera crops/pans, cursor highlights, and timing
were added afterward.

## Reproducibility limits

This is a recording and assembly recipe, **not an exact automated rebuild**.
The temporary capture/composition scripts, raw frames, and temporary batch
outputs were removed after generation. The finished GIFs are the retained
recordings. Future recordings can follow the same workflow, but their pixels,
fit results, and processing times will vary.

The PowerPoint file was opened and exported successfully in Microsoft PowerPoint.
The browser slide's loading, enlarge, replay, and freeze/resume controls were
checked. PowerPoint's animated slideshow playback was not visually verified.

## 1. Prepare a recording session

From the repository root, launch the configured environment:

```powershell
pixi run launch-app
```

Use the real dark theme, a 1440 x 960 application client area, and the bundled
fonts. The source folder is [tests\maxs\stitched](../tests/maxs/stitched).
Filter to `*.tiff`; there are ten supplied TIFF images, each 981 x 1043 pixels.

Do not modify the TIFFs, application source, or existing user sessions to stage
the presentation. Use temporary folders outside the repository for raw captures
and batch output. For scripted recording, isolate the application's session
cache before creating the window, so recording does not overwrite restart state.
Do not close or automate another person's running app instance.

The original recording used `main.create_application()`, the actual tab widgets,
and PyQt5 `QTest` mouse/keyboard events. Frames came from `window.grab()` after
processing Qt events. An ordinary screen recorder can also capture these steps.
Use genuine clicks/drags and wait for image loads and calculations to finish;
do not paint fake results or synthesize success/progress states.

Recording-specific observations:

- The folder list includes directories before images: find a TIFF by its stored
  path, not by assuming row zero is an image.
- For automation, `get_current_image(load_data=True)` exposes the loaded `data`;
  wait until it is available before capturing.
- `ImageViewer.image_to_widget(QPointF(x, y))` maps image coordinates into the
  viewer. Convert that point into the graphics viewport for mouse events.
- Click the indicator area of a checkbox, not the center of its entire layout
  allocation, which can include non-clickable blank space.

## 2. Record the four workflows

### Image browsing

1. Open the first `AgBH_cali_5m_13.5kev_stitched_2...` image.
2. Set the display to `viridis`, linear scale, Min 100 and Max 950.
3. Click the row's leading pin slot to retain reference A.
4. Select `AgBHCeO2_cali_5m_13.5kev_stitched_2...` as image B.
5. Activate **Split**. Drag the divider left, right, and back to the middle.
6. Hold on the comparison so the different ring patterns can be read.

Verify the pinned row marker, selected image, and divider movement are real.
Unpin and return to the AgBH image before calibration.

### Calibration

1. Switch to **Calibration** using the shared AgBH image.
2. Give the image and 1D profile useful space with the native splitters.
   The recording used approximately 530:320 for image/profile and 225:175:450
   for the three right-side panels. Set the profile scale to `logy`.
3. With **Snap to Peak** enabled, right-click at least three well-separated
   points on the **same visible ring**. Five points were used in the recording.
4. Click **Calculate** and hold on the calculated center and fitted circle.
5. Select **AgBh** and enable **Show Rings**.
6. Edit **Distance (m)** and make small up/down changes while showing the
   reference rings and updated 1D profile.

The recording started at 0.5000 m and demonstrated changes around 0.5050 m.
Its fitted center was approximately (592.9, 684.5), with radius 239.5 pixels.
These are staging observations, **not a certified detector calibration**.
Pick actual ring maxima rather than inserting those values as fake fit output.

### Mask making

1. Switch to **Mask Editing**, add an empty editable layer, and choose a
   contrasting pink/red overlay.
2. Use **Rectangle** over the lower-right beamstop region.
3. Use **Brush**, about 12 px, along the vertical detector gap.
4. Use **Circle** to demonstrate masking a local region.
5. Use **Eraser**, about 24 px, to refine that region.
6. Demonstrate undo/redo and hold on the combined overlay.

The local circle is a tool demonstration, not a claim that the selected pixels
are scientifically invalid. Verify that drawing increases masked coverage,
erasing decreases it, and undo/redo restores the expected edit.

### Batch processing

1. Switch to **Batch** and confirm the ten TIFFs are in its shared file list.
2. Add **circular_average** and **q_image** to the protocol queue.
3. Keep **SciAnalysis-style plots** as the output mode.
4. Run into a temporary output folder, using the shared calibration and mask.
5. Capture real intermediate results, then the completed progress bar and log.

The recorded run produced **20 successful results, zero failed**, and 20 PNG
plots. Require successful results and actual output files before labeling a
future recording as complete. Condense waiting time in editing; do not imply
that the edited GIF duration is a performance benchmark.

## 3. Edit GIFs with readable action beats

The delivered GIFs use this format:

| Property | Value |
|---|---|
| Output | 1200 x 550 pixels |
| Loop length | 22 seconds each; infinite repeat |
| Step-caption strip | Top 48 pixels |
| Screenshot area | 1200 x 498 pixels |
| Progress accent | Bottom 4 pixels |
| Palette | Shared across frames within each GIF, 256 colors |
| Dithering | None, to keep text and flat UI colors stable |

Use actual 1440-wide screenshots. Crop a roughly 598-pixel-high region and scale
it to the screenshot area; pan vertically to follow the controls or profile
without obscuring the action. Keep captions outside the app screenshot.

Suggested pacing:

- Start with a brief outcome preview, then return to the first action.
- Cursor travel frames: about 70 ms; drag frames: about 100 ms.
- Click accents: about 110 ms; action holds: 450-950 ms.
- Final outcome hold: at least 1 second, with remaining time filling the loop.
- Offset each panel's opening preview by about 650 ms relative to its neighbor.

The original assembly used Pillow with one palette sampled from each recording.
Reserve palette entries for white/gray text, dark UI surfaces, and accent colors
to avoid flickering or tinted captions. Store durations in 10 ms increments.
The delivered files contain 57, 80, 73, and 61 frames respectively.

## 4. Assemble or update the slide

For an update with the same filenames and aspect ratios, replace the GIFs beside
the HTML file; no HTML changes are required.

For PowerPoint, use **Change Picture > From a File** on each GIF, or replace it
with a newly inserted GIF at the same size and position. Do not paste a screenshot
of a GIF. Ensure animation survives in Slide Show mode on the presentation machine.

The slide canvas is 1920 x 1080, a 2 x 2 grid. GIF positions, in canvas pixels:

| Panel | Left | Top | Width | Height |
|---|---:|---:|---:|---:|
| Image browsing | 64 | 172 | 872 | 399.67 |
| Calibration | 984 | 172 | 872 | 399.67 |
| Mask making | 64 | 636 | 872 | 399.67 |
| Batch processing | 984 | 636 | 872 | 399.67 |

The current PowerPoint consists of a full-slide background image and four
embedded GIF pictures. For programmatic reconstruction, it is a standard ZIP
package: the reusable background is `ppt/media/background.png`, and the GIFs
are beside it in `ppt/media/`. The HTML retains the slide's CSS, card headings,
accent colors, and interaction code.

Regenerate the static preview from representative outcome frames, then rebuild
the bundle after updating any deliverable. Close the PowerPoint file first
(Windows may otherwise lock it during compression). From the repository root:

```powershell
$folder = Join-Path (Get-Location) 'presentation_demo'
$names = @(
    'SciView_workflows.pptx',
    'SciView_workflows.html',
    'SciView_workflows_preview.png',
    'image_browsing.gif',
    'calibration.gif',
    'mask_making.gif',
    'batch_processing.gif',
    'REPRODUCTION.md'
)
$files = $names | ForEach-Object { Join-Path $folder $_ }
Compress-Archive -LiteralPath $files `
    -DestinationPath (Join-Path $folder 'SciView_presentation_bundle.zip') -Force
```

## 5. Verify and clean up

- Check every GIF opens, loops, has the intended duration, and shows all steps.
- Open the PowerPoint and check its layout and animation on the target machine.
- Open the HTML with its sibling GIFs; check fullscreen, enlarge, replay, and
  freeze/resume. Do not substitute the static PNG when animation is required.
- Inspect screenshots at practical presentation sizes, not just file metadata.
- Confirm processing success against actual result files.
- Keep only final deliverables and this guide in this folder. Delete task-owned
  temporary captures/scripts/output after verification; never remove existing
  user data or unrelated files to clean a recording session.
