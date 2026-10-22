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

While an image is pinned and no operation is active, the canvas rests on the
pinned image. Holding the mouse on a file (or Space in the file list) shows
that file; releasing returns to the pinned image while the file stays
selected. Playback shows each file. Split, A → B, A + B, and A − B are
toggles; clicking the active one returns to this hold-to-compare state.

Calculated comparison views (A → B, A + B, A − B) keep their own colormap,
scale, and limits in `ImageCollection.comparison_displays`. While one is
active, the toolbox Color/Scale/Min/Max controls and the viewer Auto button
edit that view instead of the shared display settings, so a signed difference
never changes the colors used by other tabs. Auto runs when a calculated view
is entered; for A − B it keeps or selects a diverging colormap and sets
zero-centered limits. A → B, A + B, and A − B each have one slider for the
selected image's percentage (A → B shows A and B shares that sum to 100%).

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
