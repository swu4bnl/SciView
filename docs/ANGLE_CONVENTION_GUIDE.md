# Angle Convention Guide for SciView and AI Assistants

## Purpose

This document explains why the reduction tab angle logic became confusing, and how to avoid repeating that failure mode in future SciView work.

## What trapped GitHub Copilot

Copilot was not confused by one bad line of code. It was confused by an architectural ambiguity:

- The GUI text, overlay geometry, fallback reduction math, and SciAnalysis calls did not all use one explicit angle convention.
- Some code paths assumed a natural screen convention: `0 deg = right`, positive angles rotate counterclockwise.
- Some SciAnalysis code paths use a different convention: `0 deg = up`, `+90 deg = right`.
- `CalibrationRQconv` and plain `Calibration` do not expose identical angle behavior, so even "SciAnalysis convention" was not one thing everywhere.
- The conversion boundary was not named. Instead, angle logic was spread across widget code, overlay code, and backend code.
- User-facing labels described one convention while backend calls used another one.

Once those assumptions drifted apart, an AI assistant had no reliable anchor. It started "fixing" local symptoms with local angle tweaks, which made the overall behavior harder to reason about.

## Observable failure pattern

When this happens, you usually see one or more of these symptoms:

- Sector labels stack in one corner because the overlay searches for a `(chi, q)` point using the wrong angle map.
- A line-cut overlay points one direction while the exported 1D profile corresponds to another direction.
- `0 deg` appears vertical in one view and horizontal in another.
- Positive angle rotation appears clockwise in one path and counterclockwise in another.
- Copilot keeps suggesting hard-coded offsets like `+90`, `-90`, or sign flips in multiple files.

## Root cause

The root cause is not "Copilot made a mistake." The root cause is that the code did not present a single source of truth for angle semantics.

In practice, this means:

- no canonical display convention
- no named conversion helpers
- no clear backend boundary for SciAnalysis-specific translation
- no regression tests that lock the convention down

## Project rule

SciView must use one canonical display convention in GUI-facing code:

- display chi: `0 deg = right`
- positive rotation: counterclockwise
- `+90 deg = up`

SciAnalysis-specific conventions must be converted only at the processing boundary.

## Required implementation pattern

When working on angular reduction logic:

1. Define or reuse one shared convention helper module.
2. Keep GUI widgets, overlay drawing, fallback geometry, and status text in the display convention.
3. Convert to SciAnalysis conventions only inside the processing adapter or reduction backend boundary.
4. Record the applied convention in metadata and exported outputs when angle-bearing results are produced.
5. Add regression tests for both plain SciAnalysis `Calibration` behavior and `CalibrationRQconv` behavior when relevant.

## What not to do

Do not:

- hard-code `+90` or `-90` inside widget callbacks
- let overlay code invent its own angle convention
- let fallback NumPy geometry use a different convention than the GUI
- describe one convention in labels while executing another in the backend
- patch symptoms in more than one layer without identifying the real conversion boundary

## Prompt template for future AI work

Use a prompt like this when changing reduction geometry:

```text
Task:
  Fix or extend reduction angle behavior.

Layer:
  processing backend + GUI interface

Angle convention:
  - GUI/display convention is canonical.
  - display chi = 0 deg right, +90 deg up, counterclockwise.
  - Convert to SciAnalysis only at the backend boundary.

Requirements:
  - Reuse shared angle conversion helpers.
  - Keep overlay geometry and backend output consistent.
  - Update user-facing labels if semantics change.
  - Add regression tests for the conversion path.

Do not:
  - Add hard-coded angle offsets in widgets.
  - Duplicate angle conversion logic in multiple files.
  - Change SciAnalysis-facing semantics without documenting them.
```

## Review checklist

Before merging angle-related changes, verify:

- the same `chi0` points to the same direction in the image overlay and the exported 1D profile
- sector labels sit on the intended sector boundary instead of collapsing into one corner
- display text matches actual behavior
- tests cover the convention and the conversion boundary

## Current source of truth

The current shared angle rules live in:

- [src/sciview/processing/angle_conventions.py](../src/sciview/processing/angle_conventions.py)
- [src/sciview/processing/reduction.py](../src/sciview/processing/reduction.py)
- [src/sciview/interfaces/stable_qt/utils/reduction_overlay.py](../src/sciview/interfaces/stable_qt/utils/reduction_overlay.py)
