---
name: sciview-ui-tweaks
description: Use when making UI/style tweaks in SciView's Qt tabs (tabs/*.py) or theme module (src/sciview/interfaces/theme/app_style.py) — spacing, colors, fonts, button/input sizes, splitter ratios, panel layout. Ensures changes stay configuration-first with no hard-coded values and no unnecessary helper layers.
---

# SciView UI Tweaks

SciView's Qt GUI is styled through one central config class, `AppStyle` in
[src/sciview/interfaces/theme/app_style.py](../../../src/sciview/interfaces/theme/app_style.py).
Tab widgets (`tabs/*.py`) never hard-code pixels, colors, or fonts — they read
tokens from `AppStyle` and call its style-application helpers.

## Where values live

| Kind of value | Dict/location | Takes effect |
|---|---|---|
| QSS-injected values (padding, radius, button height) | `AppStyle.CSS_TOKENS` | Instantly on save (hot-reload) |
| Python construction-time layout (margins, spacing, splitter ratios) | `AppStyle.LAYOUT` | Requires tab rebuild (Ctrl+R) |
| Widget sizing constants (input widths, button widths) | `AppStyle.FORM_UI`, `AppStyle.BUTTON_FORM` | Requires tab rebuild |
| Typography sizes | `AppStyle.FONTS` | Instantly on save |
| Theme colors | `AppStyle.COLORS` (fallback) + `AppStyle.theme_colors()` (active theme) | Instantly on save |
| QSS templates per widget kind | `AppStyle.WIDGET_STYLES` | Instantly on save |

A live dev tool exists for this: `src/sciview/dev/style_inspector.py` (enable with
`DEV_TOOLS=1` or Ctrl+Shift+I). It edits `CSS_TOKENS`/`FONTS`/`LAYOUT` and can
write the values back into `app_style.py`. Prefer pointing the user at this
tool for exploratory tweaking; use direct edits for a specific, known change.

## Rules for any UI change

0. **Match the widget to its semantics, and prefer Qt's built-in state over
   reimplementing it.** Widgets carry interaction meaning to users:
   `QCheckBox`/`QRadioButton` imply the user can click them, so don't use them
   for a read-only status readout. A pure status readout (e.g. an "is this
   picked?" LED) is a plain `QLabel` styled as a small colored dot via QSS
   (`AppStyle.WIDGET_STYLES['status_led']` / `apply_status_led_style()`) —
   there is no native Qt "LED" widget, so a styled `QLabel` is the standard,
   idiomatic way to do this, not a from-scratch custom widget class. A toggle
   the user *can* click is a checkable `QPushButton`/`QToolButton` using the
   `:checked` QSS pseudo-class (already defined for `toolbar_symbol_button` /
   `toolbar_text_button`) rather than manually swapping stylesheets in Python.
0a. **Match the size of the fix to the size of the ask.** Not every tweak
   needs a new `AppStyle` entry. Simple one-off text emphasis (bold/underline
   a label) is just rich text — `QLabel(f"<b>{text}</b>")` — not a new
   `WIDGET_STYLES` template + `FONT_ROLE_MAP` entry + `apply_*_style` function.
   Reach for the `AppStyle` machinery when a value needs to be theme-aware,
   reused across widgets, or hot-reloadable; skip it for a single bold label.
0b. **Don't add formatting flags to builder function signatures** (e.g. an
   `emphasize=True` param on a widget-building helper). That grows into a
   laundry list as more formatting needs appear. Put the formatting in the
   string/data itself instead — e.g. pass `"<u>Beam Center X</u>"` as the
   label text directly, rather than a plain label plus an `emphasize` flag
   the helper has to branch on.
1. **Never inline a literal.** No raw hex colors, pixel widths, or font sizes
   in `tabs/*.py`. If a new value is needed, add a key to the right dict in
   `AppStyle` (see table above) and reference it — don't invent a new pattern.
2. **Reuse existing accessor methods before adding new ones.** Check for an
   existing `AppStyle.<name>()` (e.g. `wide_input_min_width()`,
   `compact_input_min_width()`, `action_button_min_width()`,
   `inline_label_width()`, `unit_label_width()`, `standard_button_min_height()`)
   before writing a new getter. Only add a new accessor if no existing one fits.
3. **Reuse the `apply_*_style` functions** for widget styling instead of
   `setStyleSheet(...)` in tab code: `apply_title_style`, `apply_subtitle_style`,
   `apply_info_style`, `apply_body_style`, `apply_status_style`,
   `apply_primary_button_style`, `apply_secondary_button_style`,
   `apply_emphasis_button_style`, `apply_toolbar_symbol_button_style`,
   `apply_toolbar_text_button_style`, `apply_input_style`, `apply_group_box_style`.
4. **Splitters/panel ratios** go through `setup_splitter_layout(splitter, ratios)`
   with ratios pulled from `AppStyle.LAYOUT` (e.g. `AppStyle.get_layout_ratios()['main_splitter_ratio']`),
   not literal `[2, 1]` lists scattered in tab code (a local override list is fine
   only when it's a one-off ratio not meant to be globally configurable, as with
   `control_ratios = [2, 4, 1]` in `calibration_tab.py`).
5. **Panel margins/spacing** come from `AppStyle.LAYOUT['panel_inner_margin']`,
   `AppStyle.LAYOUT['panel_margin']`, `AppStyle.LAYOUT['section_spacing']`, etc.
   Use `layout.setContentsMargins(*([AppStyle.LAYOUT['panel_inner_margin']] * 4))`
   the way every other tab does it.
6. **Reuse `BaseImageTab` helpers** instead of writing new one-off widgets:
   `make_scrollable_panel(panel)` for scrollable side panels,
   `configure_adaptive_form_layout(form)` for responsive `QFormLayout`s,
   `add_display_hook(fn, 'pre'|'post')` for image-viewer overlay extensions.
7. **No new helper functions or wrapper layers** unless the same snippet is
   needed in 2+ places. A single-use one-off styling tweak belongs inline where
   it's used, using existing `AppStyle` tokens directly.
8. **Don't touch scientific/backend logic for a UI tweak.** Tabs call backend
   functions (`sciview.processing.*`, `sciview.calibration.*`, `sciview.masking.*`)
   — a UI tweak should never change what those calls compute, only how results
   are displayed/laid out.

## Quick checklist before finishing a UI tweak

- [ ] Widget choice matches its interaction semantics: clickable state uses a
      real clickable widget (checkable button/checkbox/radio); a pure status
      readout uses a non-interactive one (styled `QLabel`), not a hijacked
      clickable widget.
- [ ] No literal color/px/font value added to a `tabs/*.py` file.
- [ ] Used an existing `AppStyle` accessor/dict entry, or added one in the
      correct dict (`CSS_TOKENS` vs `LAYOUT` vs `FORM_UI`/`BUTTON_FORM` vs `FONTS`).
- [ ] Used an existing `apply_*_style` helper rather than ad hoc `setStyleSheet`.
- [ ] If the change is construction-time (`LAYOUT`/`FORM_UI`/`BUTTON_FORM`),
      mention that a tab rebuild (Ctrl+R) or app restart is needed to see it.
- [ ] No new helper/abstraction introduced for a single call site.

