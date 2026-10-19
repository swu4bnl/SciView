---
name: sciview-ui-tweaks
description: Use when changing SciView Qt tabs, shared widgets, or theme styles — spacing, colors, fonts, control sizes, splitter ratios, and panel layout. Prefer native layouts and existing AppStyle tokens and helpers.
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

## Design priorities

1. **Fix the layout contract before tuning dimensions.** Decide what stays
   compact, what grows, and where spare space belongs. Prefer native grids,
   size policies, alignment, and stretch over nested containers or runtime
   geometry synchronization. Do not enlarge controls merely to fill space.
2. **Reuse the visual system before extending it.** Use existing `AppStyle`
   sizes, fonts, styles, and `apply_*_style` helpers. Add a token or derived
   accessor only for a missing design relationship, not every local value.
   Keep visual dimensions and colors out of tab code; structural layout
   indices and stretch weights need not become design tokens.
3. **Preserve interaction meaning and visible state.** Use native checkable
   controls for toggles and non-interactive widgets for status. Keep checked,
   unchecked, hover, focus, and disabled states distinguishable; do not
   replace shared state styling with a parallel local implementation.
4. **Keep the change proportionate.** Reuse `BaseImageTab` and splitter
   helpers; avoid speculative extension layers, single-use wrappers, and
   formatting flags. Leave scientific computation and state ownership alone.

## Verification and handoff

- Review the whole composition, not just isolated dimensions: grouping,
  whitespace, alignment, visual weight, and state visibility.
- Use the application's actual theme initialization and realistic window
  sizes. Behavior tests and geometry assertions do not establish visual
  quality; inspect the rendered result before claiming a visual fix.
- If feedback rejects the direction repeatedly, reconsider the layout
  model rather than stacking more compensating rules onto it.
- Keep minor visual probes uncommitted. Report checks and remaining
  uncertainty; mention Ctrl+R or restart for construction-time changes.
