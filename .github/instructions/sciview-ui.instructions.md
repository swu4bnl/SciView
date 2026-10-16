---
applyTo: "tabs/**/*.py,src/sciview/interfaces/**/*.py"
description: "Use when changing SciView Qt tabs, shared viewer controls, or other interfaces."
---

# SciView interface instructions

- Call shared backends; keep scientific computation, SciAnalysis calls, and beamline conventions out of widgets.
- Use the existing `AppStyle` tokens and helpers for Qt styling instead of local color, size, or font literals. Follow the `sciview-ui-tweaks` skill for styling changes.
- Keep controls compact and accessible. Expose scientific details when they affect interpretation, not incidental implementation mechanics.
- Preserve shared-state ownership and established interactions; ask before changing workflows.
- Surface backend failures with concise, actionable messages. Keep diagnostic details in logs.
