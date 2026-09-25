# SMI integration: first two milestones

Development branch: `feat/smi-browser-milestones`.

This checkout is the desktop integration workspace. Keep SciView's existing
image viewer, mask tools, layout, and CMS behavior; add SMI through explicit
source/profile and processing adapters.

The architecture plan was developed in the neighboring smi-browser repository
(`docs/sciview_smi_integration_plan.md`). This document describes the implementation
and can be used independently of that checkout.

## Milestone 1 — lazy raw-data exploration

- Register an optional SMI profile without changing CMS defaults.
- Browse bounded, metadata-only Tiled result pages with scoped filters.
- Preserve UID, stream, detector field, and acquisition-frame identity.
- Fetch one frame on demand and display it in the native ImageViewer.
- Navigate by acquisition index and measured/derived scalar axes, including energy.
- Preserve repeated axis values and map selections back to original frame indices.
- Run reads in bounded background jobs; discard stale completions.

Acceptance: opening a long run does not download the entire detector stack;
rapid run/stream/frame changes cannot display obsolete results; CMS still works.

## Milestone 2 — cached scientific exploration

- Open existing SMI reduction products through an adapter, without importing
  `smi_app.py` or starting Panel.
- Display per-frame I(q) and a heatmap with explicit coordinates and units.
- Define peaks and call the existing `smi_tiled.derived.peakfit` implementation.
- Display fit parameters as 1D/2D maps and additive RGB composites.
- Link a selected point/heatmap row to the corresponding raw detector frame.
- Preserve reduction/fit provenance and invalidate stale results appropriately.

Acceptance: scientific arrays agree with the existing backend; mask polarity,
coordinate transforms, reciprocal units, and frame identity are tested explicitly.

Whole-primary-run processing is now connected through the Reduction and Transform
tabs (see below). Editable SMI mask persistence, non-primary reduction,
energy-dependent geometry corrections, and batch/live integration remain later work.

## Pilot implementation

The first two workflows are now available on this branch:

- Choose the SMI catalog in Tiled Browser (CMS remains the default in the base environment).
- Newest scans load automatically on opening the SMI catalog and after successful
  login. No filters are selected by default. Results are paginated in groups of
  25, newest first, using the smi-browser reverse-catalog pagination path.
- Select **Cycle → Proposal → Project** to narrow automatically. Each child
  selection resets when its parent changes; All leaves that scope unrestricted.
  Cycles include **2026-3** and **Commissioning**, with additional choices from
  the facility API. Commissioning uses the facility's SMI proposal IDs rather
  than pretending it is a regular cycle tag.
- Proposal/project labels show scoped scan counts from Tiled. The selected cycle
  shows the exact search total. Broad all-catalog dropdown counts are deferred
  to avoid blocking the newest list; counts are not guessed on lookup failure.
- **Clear filters / newest scans** returns to the unfiltered list. Scan-ID ranges
  and text search are hidden under **Advanced**, and apply only when requested.
  No detector data is read by searches or dropdown population.
- Select a scan, stream, and detector. Only the requested frame is read. Frame
  memory is capped at 64 MiB and stream descriptors at eight entries.
- Choose a numeric primary or `fn:` axis to change navigation order. The frame
  index remains acquisition-based; duplicate values show occurrence counts.
  **Nearest axis value** selects the first closest occurrence. NaNs stay at the
  end of sorted navigation. Use Refresh run to discard cached descriptors/frames.
- **Open cached I(q) / Peaks** opens the selected UID's existing primary-stream
  reduction from `$SMI_BROWSER_CACHE_DIR` (default temp-directory cache). You can
  also open a cache file directly from Peak Analysis.
- Edit peak definitions in the table or drag heatmap bands; Fit calls smi-tiled
  off-thread. Inspect area/amplitude/center/FWHM, 1D/2D point maps, and RGB peak-area
  composites. Edit composite Use/Color/Gain/Log cells (`yes`/`no`, hex color, numeric gain).
- Clicking a map point or double-clicking a heatmap row opens the corresponding
  primary raw frame. Disable the follow checkbox to inspect I(q) in place.
- Fitted curves show the **peak component only**, explicitly excluding baseline;
  the existing backend does not persist baseline coefficients in fit results.
- Export writes a separate HDF5 artifact with definitions, source revision,
  frame axes, fit arrays, and units. Existing reduction caches remain read-only.

The pilot intentionally uses per-frame scatter maps: no reshaping or averaging
of repeated/irregular coordinates. Large-grid image rendering, general provider
registration, proposal title/PI enrichment, primary scalar
filter combinations, and fit-artifact reopening remain follow-ups. SMI Login uses
a native browser/device-code dialog with cached credentials, open/copy actions,
and cancellation; other profiles retain their existing login behavior.

Calibration, Mask Editing, Reduction and Transform now select native SMI views;
returning to CMS restores the original SciAnalysis views. Calibration and generated
masks currently require primary-stream SAXS/WAXS frames; other streams remain
available for raw browsing.
Live SMI monitoring is not enabled in this pilot. Non-singleton exposure/panel
dimensions beyond a simple frame stack are rejected pending explicit mapping.

## Metadata-relative calibration and layered masks

Calibration keeps SciView's right-click ring picks, local-maximum snapping,
manual center controls, and robust circle-center calculation for SAXS. Geometry
is initialized by smi-tiled's metadata resolvers, including sample/detector motor
corrections and bundled calibration. WAXS uses the folded three-panel model and
the calibrated integration distance (273 mm by default), while the metadata motor
distance is retained as information. SAXS currently uses the backend's run-reference
geometry; selecting a different frame does not imply per-frame SAXS geometry support.

- **Center only:** pick at least five well-spaced points on any one ring. Ring q
  is fitted as a nuisance parameter; energy and distance stay fixed.
- **Known q:** provide q in nm⁻¹ and fit center plus distance, with energy, tilt,
  and panel geometry fixed.
- **AgB order:** q is `order × 2π/5.8380 nm`. Orders 1–100 are selectable.
- **Store picked ring + q:** accumulate separate known-q/AgB rings, clearing picks
  between rings, then **Fit stored rings jointly** for common center/distance tweaks.
- Optional intensity refinement searches near each pick along the local q-gradient
  (including folded WAXS geometry). This is a picked-ring refinement, not automatic
  whole-image ring discovery or the older smi-browser q–χ sinusoidal fitting UI.
- Review the fit RMS and correction values; **Apply fitted / edited center and
  distance** transfers them to the instrument session and subsequent reductions.
  Applying twice does not accumulate the same correction. Reset returns to metadata
  plus bundled defaults. The fitted center is the direct-beam center, not a command
  to reposition a beamstop motor.
- Native diagnostic radial/sector profiles use SMI q coordinates and nm⁻¹ units;
  standards are converted from the native Å⁻¹ database. The native flat-circle
  operation is unavailable for WAXS; the metadata-relative folded-model fit is used.

Mask Editing retains SciView's brush, shape, threshold/morphology, import/export,
and layer tools. **Every editable layer is a user exclusion.** Static detector
masks (blue) and dynamic beamstop/shadow masks (red) are separate generated
overlays, not editable layers. Their visibility switches affect display only.
The explicit SAXS shadow/aperture switches affect processing as well as preview.
Erasing a user layer cannot unmask a detector gap or a generated beamstop region.

User masks are scoped by detector and raw image shape, and persist when switching
frames/scans in the session. OR/AND and native layer inclusion work within the user
mask only; its result is always added to the backend exclusions. Drawings remain
rasters in the UI. For the published smi-tiled API, they are converted to exact
pixel-boundary rectangles and appended to the original static polygon specification.
Tests verify pixel-exact round trips, holes, edge pixels, and WAXS transpose; dynamic
beamstop wrappers/offsets are preserved without normalized JSON round-trip loss.
Highly fragmented/noisy masks can produce many rectangles and cost more to rasterize;
a native raster-exclusion backend API would be a useful future improvement.

**Save/Load SMI session** persists relative corrections, original base-mask specs,
editable layer rasters/names/inclusion, combined user masks, and dynamic options.
Use **Load SMI base-mask JSON** for an alternate scientific specification; ordinary
mask imports are user layers. Reduction shows the active instrument corrections
and user pixel counts. Explicit reduction-panel deltas take precedence over session
calibration tweaks. Jobs snapshot masks into their own directories and validate raw
detector shape before reduction. Fitted transmission WAXS corrections are not
silently applied to GI; that geometry adapter still needs validation.

Scientific verification includes synthetic known/unknown/multiple-ring geometry
recovery, folded WAXS q-map parity, exact mask composition, session round trips,
and a real WAXS Qt load with generated masks plus user exclusions passed through
the backend mask builder. Real AgB calibration against a known reference and real
GI correction validation remain outstanding.

## Whole-run processing

1. Select an SMI scan's **primary** stream in Tiled Browser.
2. Open **Reduction**. Choose transmission SAXS+WAXS or grazing-incidence WAXS,
   output grid, pixel splitting, dezinger settings, and whether to retain frame maps.
3. Leave calibration overrides unchecked to use smi-tiled's metadata and bundled
   defaults. Optional transmission overrides are metadata-relative center/distance
   deltas. For GI, the incident angle can be automatic or explicitly overridden.
4. Optional mask paths accept existing **SMI JSON specifications**, not SciView
   raster masks. Blank paths retain bundled masks and their dynamic behavior.
5. Click **Reduce whole primary run**. This processes all available participating
   detectors and frames, not only the detector/frame currently displayed.
6. Inspect merged/per-frame I(q), SAXS/WAXS components, and q-scaled curves in
   Reduction. Use **Transform** for merged or per-detector frame q–χ maps, or GI
   qxy–qz maps. Map axes and cursor values are physical coordinates; q is nm⁻¹.
7. **Explore result in Peak Analysis** opens newly produced per-frame transmission
   I(q). GI maps do not claim an I(q)/peak product that the backend did not produce.

Jobs run in separate Python processes. Cancel first requests a stop at a backend
progress checkpoint, then kills the worker after three seconds if needed. Partial
files are never offered as complete products; the per-job directory retains logs
and any temporary output for diagnosis. Selecting another scan does not publish
the old job's result into the new view.

Result location: `$SCIVIEW_SMI_RESULTS_DIR`, default
`$SMI_BROWSER_CACHE_DIR/sciview_results` (under the temp cache when unset). Each
execution has its own directory containing `request.json`, `job.log`, optional
frame stores, and atomically published `result.h5`. **Open saved SciView reduction**
restores a result when its source UID/primary stream is selected. HDF5 includes
requested options, backend arguments (including mask specs), resolved transmission
parameters, backend version, recipe fingerprint, and a unique execution revision.

The pinned GitHub backend predates a local fix for partially populated browser
image caches. New reductions therefore bypass raw-cache reuse and disable cache
population; raw data are read from Tiled. Existing caches remain usable for the
read-only cached-analysis workflow. Backend upgrades can re-enable raw-cache reuse
after the published completeness checks are available and tested.

Validation: a real 80-frame WAXS run completed via the pinned backend with a
256×72 test grid, producing merged/per-frame I(q) and merged/per-frame q–χ maps.
Qt heartbeat events continued during processing. A second Qt check reopened the
artifact in Reduction, Transform, and Peak Analysis. Synthetic GI tests verify
named-axis orientation; real GI reduction validation remains outstanding.

## Readability and per-frame displays

- **View → Appearance…** (`Ctrl+Shift+A`) controls application text size, automatic
  high contrast, and a custom text color. Preferences persist across launches and
  apply to native plot axes/labels as well as widgets. Large-screen installations
  default to 150% text scale; the menu also offers a light/dark theme toggle.
- **Per-frame** I(q) defaults to a **Waterfall** with adjustable spacing. In log
  mode the display is explicitly `log10(I × q^p) + offset`, with spacing in decades;
  in linear mode spacing is a fraction of the robust intensity span. Original data
  and exported results are unchanged. **Single frame** is still available.
- Choose **Frame label** from the stored primary signals, then hover a waterfall
  trace to see the acquisition-frame index and signal value. Large overviews show
  at most 200 evenly sampled traces and 2000 q points, with the count displayed.
- Transform has a bottom frame slider and a readable frame/signal label; its exact
  frame-number input stays synchronized. Merged maps disable frame navigation.
  Existing files expose the labels they already contain; new reductions additionally
  retain string frame labels and GI incident-angle/motor values.

## Local development

From this checkout:

```bash
pixi install --locked
PYTHONNOUSERSITE=1 pixi run launch-app
PYTHONNOUSERSITE=1 PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen pixi run python -m pytest tests/ -q
```

The upstream Unix launcher auto-pulls by default. For branch development use the
Pixi command above or `./Launch-SciView-linux.sh --no-auto-pull`.

Optional SMI environment (smi-tiled installs from a pinned GitHub commit; no
separate checkout or installation required):

```bash
pixi install -e smi --locked
pixi run -e smi launch-smi
PYTHONNOUSERSITE=1 PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen pixi run -e smi python -m pytest tests/ -q
```

The base environment has no SMI scientific dependency. No Panel/Bokeh or
`smi_app.py` imports are used by the pilot. Keep scientific code in smi-tiled,
and use the new `frame_source` and cache adapters from the Qt UI.

For backend development only, replace the `smi-tiled` entry under
`[feature.smi.pypi-dependencies]` locally with:

```toml
smi-tiled = { path = "../smi-tiled", editable = true, extras = ["tiled"] }
```

Then run `pixi install -e smi`. Restore the GitHub dependency and regenerate the
lockfile with `pixi install -e smi` before sharing changes. To upgrade the shared
backend, change `rev` to a tested published commit and regenerate the lockfile;
this keeps installations reproducible rather than following a moving branch.

Initial baseline verified: locked Python 3.12 / Qt5 / PyQtGraph environment,
31 upstream tests passing in offscreen mode. This establishes installation and
test health, not end-to-end performance against real SMI data.

Pilot validation: 44 tests pass in the SMI environment, including upstream CMS
tests, lazy reads/stream identity, bounded requests, cache fitting/export, native
device authentication, and Qt axis/composite views. A real 80-frame WAXS run was
searched and sliced to one `(619, 1475)` int32 frame; its cached `(80, 3000)` I(q)
and six fits loaded successfully. A real offscreen Qt workflow verified that a
cached-analysis selection navigates to the matching acquisition frame in Tiled.
