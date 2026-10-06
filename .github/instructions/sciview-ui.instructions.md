---
applyTo: "src/sciview/interfaces/**/*.py"
---

# SciView interface instructions

Interfaces include the current Qt GUI, future napari plugin, and any later desktop shell.

## Requirements

- Keep interface code thin.
- Interface code may collect user input, call backend functions, and display results.
- Interface code must not contain core scientific processing logic.
- Do not call SciAnalysis directly from widgets.
- Do not parse CMS folder conventions directly in widgets.
- Convert backend exceptions into concise user-facing messages.
- Avoid duplicating logic across the stable Qt and napari interfaces.

## Stable Qt GUI

The current SciView GUI may remain useful for image viewing, calibration inspection, and mask-making.

During refactor, preserve visible behavior where practical while moving backend logic into `sciview` modules.

## Napari plugin

The napari plugin should use napari layers for images, masks, overlays, and result maps.

Napari widgets should call the same backend APIs as the stable Qt GUI.
