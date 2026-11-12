# SciView UI Control Architecture

## Purpose

This guide explains how SciView controls visual behavior, spacing, typography, theme behavior, and widget-level styling.

It is written for three audiences:

- Developers: where to implement UI behavior without breaking consistency.
- Frontend engineers: how global design tokens map to concrete widgets and runtime refresh.
- Designers: which knobs are safe to tune and which changes require a layout rebuild.

The main goal is a single-source, predictable UI system that stays maintainable as the app evolves.

## Product Language And Control Preferences

- Keep controls compact, discoverable, and accessible; omit incidental technical detail.
- Focus guidance on the main workflow and meaningful decisions, not self-explanatory secondary controls.
- Preserve precision where it affects scientific interpretation, reproducibility, or results.

Text scaling and high contrast use `FONTS.scale_pct`, the `AppStyle` palette,
and the shared runtime refresh path. These session-only UI settings do not
change scientific export styles.

## Shared Image Colors

The Image Browser and Transform plot controls share the color map and linear/log
intensity scale through the main application's `AppearanceSettings` model.
It owns image-display and plot-appearance values together. Changes in either
place update the other controls. The existing image-control/session dictionary
interface is a mapping view of that model, not a second settings store.
The application's read-only `plot_style` property derives a `PlotStyle` snapshot
at the preview/export boundary. Loading a saved plot style updates the model.
Batch jobs retain their own snapshots, independent of later interface changes.
Transform intensity limits and automatic range remain independent of the
raw-image limits.

The backend `ImageCollection` model owns ordered image references, the active
reference, the pinned comparison reference, and comparison parameters. The
Image Browser's session manager owns image loading and its bounded cache; it
retains the pinned array so cache eviction cannot invalidate a comparison.
Comparison operations are pure backend functions, and the browser only maps
their results into the existing viewer. This keeps the collection and
comparison state reusable by later playback and cross-tab workflows.

Navigation and comparison have separate rows: the timeline selects frames;
the comparison slider changes their contribution. Play retains the operation
and weight; adjusting the weight pauses playback. Split uses the canvas
divider rather than a weight slider.

With no operation active, a pinned image is the resting view. Holding a file
or Space reveals the selected image; releasing restores the reference.
Playback and seeking instead keep the selected frame visible when paused.
A subsequent file hold restores the pinned resting view.

`ImageCollection.selected_paths` stores paths in displayed sort order without
loading arrays. Two or more selected files constrain playback and seeking;
otherwise navigation uses the folder. Unmodified Up/Down preserves and
navigates within a multi-selection; Ctrl/Shift retains native selection
editing. Folder refresh retains surviving selections in the new order.
The displayed-frame marker follows the rendered image, not the focused row
or selection membership.

Uncached local frames load through `ImageLoadWorker` off the interface thread
into the existing bounded LRU cache. Only one read runs at a time; rapid
scrubbing replaces pending requests with the latest frame. Late results never
replace a newer selection. Playback waits for each frame to load rather than
queueing reads or skipping unloaded frames. Pinned data remains retained
independently of the cache. An incompatible comparison frame pauses playback
with an explicit error rather than silently playing a raw frame. If the
reference itself is included in a calculated sequence, the same formula is
applied to it (for example, A − A is zero at 100% weight).
Closing or replacing a browser cancels pending requests without waiting on
the UI thread. An in-flight read remains owned by the application until it
finishes; window shutdown is deferred while the event loop stays responsive.

Calculated comparison views (A → B, A + B, A − B) keep their own colormap,
scale, and limits in `ImageCollection.comparison_displays`. While one is
active, the toolbox Color/Scale/Min/Max controls and the viewer Auto button
edit that view instead of the shared display settings, so a signed difference
never changes the colors used by other tabs. Auto runs when a calculated view
is entered; for A − B it keeps or selects a diverging colormap and sets
zero-centered limits. Save exports the active calculated view, including
during playback, as a 32-bit float TIFF with negative values preserved.
Suggested names shorten filenames by length, without interpreting their
structure. The TIFF description records the formula and both source paths.

## Waterfall Results

Select multiple local images in Image Browser and choose **Waterfall** to process
them with the current Reduction settings. Results keeps this ordered input
snapshot; **Update** uses the same inputs with the latest settings, not a later
browser selection. Calibration, Masking, Reduction and Transform remain the
settings owners; the Notebook owns presentation. Editing settings marks the
figures that depend on them stale (shared calibration/mask, or the matching
processing tab) without recomputing anything; each stale figure shows an
**Update · settings changed** action in its own header, which reprocesses that
figure's sources with the current settings and replaces its content in place,
keeping identity, title, labels and appearance (marks reset because sample
indices change). A cancelled or partly failed recomputation leaves the figure
unchanged. The corner Recalculate action remains only for the explorer's
unlinked latest result and for retrying after a settings problem.

The GUI-independent waterfall adapter processes one image at a time through the
existing Reduction backend. Each run captures calibration and mask snapshots;
incompatible image shapes and failed reductions are reported per source, never
replaced with pixel-coordinate results. This first version supports circular
and sector averages with one calibration across the selected series.

Spacing adds a display-only intensity offset; zero overlays the curves.
Visibility and colors do not change numerical data. **Show source** reveals the
raw image while retaining browser selection and its pinned reference.
**Export curves** writes original, unshifted CSV values, the applied mask, and a
JSON settings/source manifest, including failures and cancellation status.
Cancellation takes effect between image reads and reduction calls.

Results uses a pyqtgraph canvas with Pan, box Zoom, and Home. Image and curve
viewers share toolbar builders, icons, plot theming, colormaps, and PNG export.
Hovering a plotted curve or source row transiently highlights both; clicking a
curve selects its source row and reveals its appearance controls. The canvas
footer groups navigation with scientific coordinates and intensity readouts.
Waterfall separation and palette stay visible in the source panel, separate
from navigation. Recalculate appears only when processing settings are stale;
export remains a secondary action. The source list expands above content-sized
settings groups, and the panel scrolls when the available height is insufficient.
Separation reports a compact intensity-unit value; automatic framing applies to a
new run, while plot adjustments preserve a manually selected view range.
Mark labels a sampled curve point with its original q and intensity, follows
spacing and visibility, and never modifies numerical exports. Marks are
reset on Update; Escape leaves marking and Ctrl+Z undoes a mark when the canvas
has focus. Save writes the visible plot, including marks.

### Scientific notebook

Results opens into an offline Milkdown document with a document bar, centered
writing canvas, and collapsed outline rail. The document bar owns New, Open,
Save, Save As, and insertion of the latest completed waterfall. The outline's
own rail controls its expansion; heading and figure navigation scrolls without
changing the writing caret or figure selection. Milkdown's native sticky
formatting bar exposes headings, marks, lists, links, and content insertion;
Markdown shortcuts, slash commands, and block handles remain available.

Image Browser's Waterfall action processes the ordered selected measurements
and inserts the completed result directly into the active Notebook, without
opening a separate plot explorer. Progress, cancellation and actionable
failures appear contextually above the document; stale figures carry their own
Update action.
Partial or cancelled results retain their source errors and processing snapshot.
The SciView insertion action also places the latest completed waterfall at the
writing caret, preserving surrounding text and leaving a paragraph after the
figure. Only block drag handles initiate reordering; plot gestures, sliders,
annotations, and editable text cannot drag a figure. Curves render inline from the
saved scientific arrays; hovering reports source coordinates and intensity,
and clicking a curve reveals its measurement-specific controls inside the
selected figure. Editing is owned by the visible element, not an embedded
property panel: title and legend text edit in place, and clicking an axis
opens label/unit editing over that axis title (including the rotated y axis).
Clicking a curve opens a compact floating color/style/thickness strip near it;
opacity and the presentation-only Intensity × multiplier are secondary tools.
Thickness has one slider/value pair, not duplicate controls. Legend swatches select
curves. Empty-canvas clicks and drags are reserved for
selection and plot navigation; they never open figure settings. The explicit
Figure settings action in the figure header opens palette, default line appearance,
separation, measurement visibility and legend
visibility in a dismissible panel attached to that figure block. It groups
global elements under Figure, measurement visibility and collapsible default
appearance under Curves, and separation/palette under Waterfall. Only the
plot-type-specific section needs replacement for another visualization type.
Titles and axis labels edit only at their displayed locations, not through
remote inspector buttons. Titles, axis labels, legend names and future editable
figure text use one shared `figure-editable` mechanism: a dashed outline and
pencil appear only on hover, and focused text shows a solid editing box and caret.
The panel does not repeat the figure title; its attachment conveys ownership. It
stays available during curve editing, and closes when returning to writing.
Selecting an element alone never narrows the scientific plot or adds a settings
column. Explicitly opening advanced settings places them beside the plot within
its document block, scrolling with it rather than docking to the application
window. Narrow figure blocks place the settings below the plot instead of
compressing the scientific content.
Measurement visibility lives only in figure settings, where hidden measurements
remain listed and can always be restored. Individual line overrides take
precedence over figure defaults; opacity and multipliers leave source arrays
unchanged. Curve tools group color, pattern, width and opacity in one Line row, with
presentation-only Scaling on a separate compact slider/value row. Default
pattern and width share a row in the inspector's collapsed appearance group.
The figure has no permanent explanatory footer. Titles edit in place
and update the outline and saved document.
Clicking outside returns to writing and dismisses tools. Escape from a selected
figure places the writing caret after it without replacing the figure block.
Separation, palette, visibility, gain, color, line style and width update the
canonical linked plot object. Sliders are paired
with editable numbers for precise adjustments; slider ranges are convenient
defaults, while typed Separation and Scaling accept any finite nonnegative value. The visible legend identifies
measurements even when a figure is not selected. Figure titles, axis labels and
units, and legend names are directly editable. Presentation metadata is separate
from scientific source labels: editing a unit does not convert the arrays.
Routine scientific titles and axis labels use plain text and Unicode symbols
(such as Å⁻¹, χ, φ, and °), not Markdown or math delimiters. Older notebook
axis metadata uses the same presentation without changing saved source labels.
Only the selected element's tools are exposed; text editing does not open
unrelated appearance controls. Expand enlarges
the same document figure, with the same controls and interaction, rather than
opening another editing workspace. Its corner handle continuously resizes
between half and full document width and adjusts height; arrow keys provide
accessible size adjustments. Axes, ticks, curves and sample annotations redraw
at the actual display dimensions. Pan, box Zoom, Fit, and Mark share one
interaction in both sizes; Ctrl-wheel zooms without intercepting ordinary
document scrolling. Display gains and separation leave original data unchanged.
The curve explorer behind the document is an editing convenience for curve
figures, not a required processing or figure-editing step.

### Scientific objects

Every notebook figure is a `core.notebook.ScientificObject`: a stable ID,
title, ordered source references, processing provenance, a PNG preview, shared
figure metadata (axis labels/units, legend) and a kind-specific payload with
its own presentation state and validation. Two kinds exist:

- `CurveFigure` (`kind: curves`): one or more 1D curves sharing axes, with
  waterfall presentation (`PlotState`). A waterfall and a single Reduction
  preview are the same object type; the single curve simply has one source.
- `ImageFigure` (`kind: image`): a 2D map on calibrated axes (a Transform
  result) with `ImageState` — colormap, linear/log scale, automatic or explicit
  intensity limits, and view range. Pan, box Zoom and Fit, title and axis
  label/unit editing behave as for curves; the figure settings panel replaces
  the Curves/Waterfall sections with an Image section.

Log intensity requires positive image values. A rejected display edit reports
the reason and keeps the previous settings. Recomputing a map refreshes its
pixels even when its dimensions and intensity limits are unchanged.

Reduction and Transform expose **Add to Notebook**. `processing.notebook_results`
turns the previewed request/result pair into a figure using the same
`processing.provenance` snapshot (detector geometry, mask hash, parameters,
software versions) as waterfall processing; nothing is recomputed. The tab's
current plot style is carried over as presentation state (line color/width;
colormap, scale, intensity limits and manual crop) and remains editable in the
document. Selecting an image figure never engages the curve explorer.

Previews are rendered headlessly by `processing.plot_rendering.figure_preview_png`
from the object itself at the size the card last reported, when a figure is
inserted and again at save for objects whose content or size changed. The
saved PNG is only used when the Markdown is viewed outside SciView.

Save writes a Markdown document and a sibling `.assets` directory. Share both.
The assets hold the original arrays (curves, maps, axes, mask), scientific
provenance, presentation and PNG previews; reopening does not require the
source images or reprocessing, and missing or changed source files never alter
a saved object. The manifest records each object's `kind` (version 2);
version 1 manifests without kinds are read as curve figures. The Python
notebook object remains canonical; the editor receives arrays and presentation
state only to render the interactive document view (map pixels travel as
base64 float32, so large maps make documents heavier to load). Notebook marks
retain original sample indices. Asset revisions are written before the document
is replaced, so a failed save preserves the prior version. Previous successful
asset revisions are retained; they can increase storage over repeated saves.
Dedicated publication export and PDF are not included yet. The application
session cache remembers the last opened or saved notebook path and restores it
on restart; missing or invalid documents report an error. Unsaved-change
prompts compare actual document and scientific-object content against the
saved baseline. Curve selection and regenerated previews are not edits;
undoing a content change back to that baseline restores clean state.

The GUI-independent `core.notebook` values and `data.notebook` save/load APIs
own document persistence. Processing adapters capture/restore figure values
without rebuilding scientific logic. The Qt WebChannel carries Markdown, render
data and presentation updates; the editor does not recalculate scientific
results. The editor blocks network requests and is bundled locally; Node is a
build dependency only.
Import or paste local images: they are embedded as persistent data URLs in
Markdown, not transient browser URLs. Remote image URLs remain blocked; import
the image instead. Open links from the native link preview, or Ctrl-click
(Command-click) a link, to use the system browser without leaving the document.
AI and collaboration services are not enabled. Crepe's built-in labels retain
their upstream language; SciView-owned actions use the application catalogs.

After changing the editor sources, rebuild the checked-in bundle:

```powershell
cd src\sciview\interfaces\stable_qt\notebook
pixi run --manifest-path ..\..\..\..\..\pixi.toml -e notebook-build npm ci
pixi run --manifest-path ..\..\..\..\..\pixi.toml -e notebook-build npm run build
```

The generated distribution includes third-party license notices. Rebuild before
testing or packaging changes to the editor. KaTeX is aligned to the renderer
version used by Crepe, including the transitive Markdown math parser.

## Layer Map

The UI stack is intentionally layered. Think of each layer as owning a different class of decision.

Owned interface wording is maintained separately in the context-rich
[message catalog](LOCALIZATION.md). Widgets resolve message IDs at the
presentation boundary; stable settings and scientific identifiers are not
translated.

1. Product-level defaults and app startup

- Module: main.py
- Responsibility: create application, apply global style system, create top-level window, wire tabs.
- Key point: all tabs and widgets should rely on the same style system initialized at app startup.

1. Runtime settings layer

- Modules: src/sciview/settings/app_settings.py, src/sciview/settings/viewer_config.py
- Responsibility: non-theme defaults such as window sizing, splitter ratios, image display defaults, viewer behavior defaults.
- Key point: this layer provides app defaults, not per-widget styling rules.
- Viewer tool actions and group order are declared by `VIEWER_TOOLBAR_ACTIONS` and `VIEWER_TOOLBAR_GROUPS` in `viewer_config.py`. New tools need an action, icon mapping, group membership, and behavior connection; layout placement is derived from the group configuration.

1. Design-system and style engine layer

- Module: src/sciview/interfaces/theme/app_style.py
- Responsibility: token definitions, style templates, style helper APIs, runtime theme refresh.
- Key point: this is the primary source of truth for styling decisions.
- Viewer toolbar dimensions derive from shared control and typography tokens; native layouts own alignment and overflow.

1. Theme tooling layer (development-time)

- Module: src/sciview/dev/style_inspector.py
- Responsibility: live editing for CSS tokens, typography, and selected layout values.
- Key point: this is an editor for the design system, not a separate style system.
- The corner inspector button and Ctrl+Shift+I are available by default.
  Automatic file hot-reload remains opt-in with `DEV_TOOLS=1`.

1. Widget and tab consumption layer

- Modules: tabs/*.py and src/sciview/interfaces/stable_qt/widgets/image_viewer.py
- Responsibility: build UI, call style helpers, use layout tokens, implement domain-specific interaction.
- Key point: these modules consume style APIs; they should not invent parallel style rules.

## Ownership Matrix: Who Controls What

### A. Global color semantics and theme adaptation

Owner: AppStyle.theme_colors in app_style.py

Controls:

- Derived runtime colors from active Qt or external theme.
- Accent, text, border, control background, hover, muted tone.
- Icon tint behavior through themed SVG rendering.

Should not be overridden ad hoc in tabs unless a visual exception is deliberate and documented.

### B. Core design tokens

Owner: AppStyle constants in app_style.py

Token groups:

- COLORS: semantic fallback palette.
- FONTS: scale and type roles.
- Font roles use native Qt Normal/Bold weights; styles use normal/bold.
  Intermediate numeric weight tuning is not exposed.
- CSS_TOKENS: live stylesheet token values such as paddings, radius, height hints.
- LAYOUT: construction-time spacings, splitter ratios, panel constraints.
- BUTTON_FORM and FORM_UI: reusable control dimensions.

Design interpretation:

- CSS_TOKENS: paint-time controls (safe to tweak live).
- LAYOUT and dimensional constants: construction-time controls (may require rebuild/reopen of affected panels).

### C. Widget stylesheet generation

Owner: AppStyle.format_style and AppStyle.WIDGET_STYLES in app_style.py

Controls:

- Converts semantic tokens into concrete QSS fragments.
- Provides named style targets such as title labels, info labels, input fields, primary and secondary buttons.

This is where visual language is translated into widget styling.

### D. App-level style application

Owner: AppStyle.apply_global_style and AppStyle.tab_widget_stylesheet in app_style.py

Controls:

- Applies shared base styles to the QApplication.
- Applies top-level tab shell style.
- Triggers runtime refresh pass for live widgets.

### E. Per-widget semantic style assignment

Owner: style helper functions in app_style.py

Examples:

- apply_title_style
- apply_info_style
- apply_primary_button_style
- apply_toolbar_symbol_button_style
- apply_input_style

These helpers assign style keys and font roles so global refresh can reapply expected styling later.

### F. Runtime style reapplication

Owner: AppStyle.refresh_runtime_theme and AppStyle.apply_widget_style

Controls:

- Reapplies style keys to existing widgets.
- Reapplies font roles and key sizing constraints.
- Refreshes theme-aware widgets and matplotlib figures.

This prevents style drift after theme changes and live token updates.

## Runtime Performance

- Global appearance refresh updates each viewer; tabs refresh only visuals
  they own. Avoid redundant stylesheet assignments and intermediate themes.
- Themed SVGs use Qt's bounded pixmap cache and a disposable disk cache at
  `<platform generic cache>/sciview/icons-v1`. Invalid entries are logged and
  regenerated; removing this cache does not affect user data.
- Tiled client and streaming dependencies load only when needed, through
  background tasks. Startup availability checks do not verify dependency health.
- Status-bar resource sampling must remain nonblocking.

### Measuring startup and appearance changes

Run `pixi run benchmark-ui --runs 3 --samples 4 --json measurements.json` on a
desktop session to compare startup and appearance changes with cold and warm icon
caches. It uses fresh processes, an empty session, and a disposable cache without
changing saved user state or connecting to Tiled. Results include queued layouts
and paints, not compositor latency, launcher overhead, or session restoration.
Compare runs on the same machine/theme/locale; timings are diagnostic, not test
thresholds.

## Stylesheet vs Token vs Runtime Theme: Practical Difference

1. Stylesheet templates

   - Defined in WIDGET_STYLES.
   - They are patterns for how a widget should look.
   - They are not raw values by themselves.

2. Tokens

   - COLORS, FONTS, CSS_TOKENS, LAYOUT, BUTTON_FORM, FORM_UI.
   - They are reusable decisions and constraints.
   - Templates consume tokens.

3. Runtime theme colors

   - theme_colors computes live colors from the active app theme.
   - This allows one tokenized style system to adapt to light and dark theme families.

4. Rendered widget style

   - apply_widget_style materializes template plus token values into concrete widget stylesheet text.

## Live Controls vs Rebuild Controls

### Live and immediate

- CSS_TOKENS updates.
- Typography token updates.
- Global theme switching.

These changes are intended to apply immediately through refresh_runtime_theme.

### Usually requires tab rebuild or reconstruction

- Many LAYOUT values such as splitter handles, panel spacing relationships, and build-time geometry decisions.

These values affect how widgets are created and laid out, so changing them later may need rebuild actions.

## How Designers Should Think About This System

Use a design-system mindset:

1. Semantic first

   - Tune semantic tokens before touching individual widget code.
   - Example: adjust spacing rhythm in CSS_TOKENS and LAYOUT instead of changing one panel manually.

2. Scale and hierarchy

   - Typography hierarchy is controlled by font roles and FONTS scale.
   - If visual hierarchy feels wrong, adjust role tokens first.

3. Component consistency

   - Button families should map to style helpers.
   - If a button looks unique, verify whether it should be a new semantic style type or a bug.

4. Theme resilience

   - Prefer theme-aware paths so light/dark transitions remain readable.

## How Engineers Should Add UI Without Breaking Global Control

1. Always choose a semantic helper first

   - Use existing apply_* style helpers for labels, buttons, inputs, and group boxes.

2. Reuse AppStyle dimensions

   - Use AppStyle dimension helpers and LAYOUT constants for widths, heights, and spacing.

3. Avoid direct per-widget stylesheet strings

   - Only use direct strings for justified exceptions, with comments.

4. Register style state through helper APIs

   - Ensure widgets can be re-styled on runtime refresh.

5. Keep style logic in AppStyle

   - If a new visual category appears, add a named style key and helper in app_style.py instead of duplicating style snippets in tabs.

## Current Risk Areas to Watch

These are known classes of risk that can slowly fragment the system:

1. Hardcoded spacing in tabs

   - Some tabs still use numeric spacing and margins directly.
   - Over time this can drift from global rhythm.

2. Direct compact-button stylesheet calls

   - Some widgets set compact styles directly instead of using semantic helper ownership.

3. Legacy/deprecated UI sections

   - Deprecated panel builders or placeholder-only paths increase ambiguity around active architecture.

4. Duplicate compatibility shims

   - Compatibility logic copied into multiple modules can create conflicting behavior.

## Recommended Maintenance Contract

Use this contract to keep future AI and human edits consistent.

1. Single source for style behavior

   - AppStyle is the only place for reusable visual rules.

2. Single source for runtime defaults

   - app_settings and viewer_config hold app/view defaults.

3. Tabs are consumers, not style authors

   - Tabs should request style intent, not define the visual system.

4. Token-first changes

   - Start with tokens, then template adjustments, then local exceptions only if necessary.

5. Regression tests for style behavior

   - Keep tests for format_style output, style-key reapply behavior, and layout-reset invariants.

## Quick Decision Guide

When changing UI, decide quickly with this checklist:

- Need color, typography, border, or component visual update?
  Change AppStyle tokens or style templates.

- Need app default window or splitter behavior?
  Change app_settings GUI settings and AppStyle layout handling.

- Need one widget type to look different everywhere?
  Add or update a semantic style helper in AppStyle.

- Need one exceptional visual treatment in one panel?
  Prefer a documented semantic style extension; avoid inline hardcoded styles when possible.

## Suggested Future Improvements

1. Continue migrating hardcoded per-tab spacing to AppStyle.LAYOUT keys.
2. Consolidate any remaining direct compact-button stylesheet calls into helper-based semantic styling.
3. Remove deprecated inactive panel builders and stale placeholders where possible.
4. Add a small architecture diagram to docs showing data flow from token to widget render and runtime refresh.

---

This architecture is strong when every contributor treats AppStyle as a design system engine, not just a utility module.
