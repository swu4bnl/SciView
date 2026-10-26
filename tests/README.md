# SciView Tests

## Run Tests

Run the required test suite:

```bash
pixi run test
```

Run one test file:

```bash
pixi run python -m pytest tests/test_image_viewer.py
```

## Test Scope

Keep a flat, feature-based suite:

| File | Retained coverage |
| --- | --- |
| [test_image_collection.py](test_image_collection.py) | Ordered selection, pin ownership, comparison arithmetic and input validation |
| [test_image_io.py](test_image_io.py) | Local discovery, filtering/sorting, float-TIFF integrity and export rejection |
| [test_image_viewer.py](test_image_viewer.py) | Display/data separation, comparison/export and cross-tab workflows |
| [test_image_playback.py](test_image_playback.py) | Selection/navigation, asynchronous reads, shutdown and annotation isolation |
| [test_mask_drawing.py](test_mask_drawing.py) | Pixel footprints, transactional edits, cancellation and undo/redo |
| [test_tiled_workflow.py](test_tiled_workflow.py) | Mocked remote discovery/loading and local use without Tiled |
| [test_ui_messages.py](test_ui_messages.py) | Catalog integrity, translation boundaries and scientific glyph support |

Organize retained tests around user tasks and main workflows. Assert meaningful
outputs and scientific correctness, not one test per feature or helper.
Examples include:

- Image coordinates and display transformations.
- Source-data preservation.
- Shared image and display state.
- Mask composition and boundary handling.
- Connecting to a data source, finding a scan, and loading detector data.
- Continuing local work when an external data source is unavailable.
- Application installation and startup.

Keep focused scientific regressions when they protect interpretation or source
data; do not combine unrelated cases merely to reduce test counts. Remove
temporary probes after the focused change passes. Do not keep tests that only
assert private fields, exact callback counts, individual appearance controls,
cache mechanics, removed controls, or unfinished external-service behavior.

Mock external services. Do not require network access, authentication, live beamline services, or large detector files.

## Performance Diagnostics

Use `pixi run benchmark-ui` for native startup and appearance timings. This is
an opt-in developer tool, not a timing-gated pytest suite. See the
[benchmark guidance](../docs/UI_CONTROL_ARCHITECTURE.md#measuring-startup-and-appearance-changes)
for scope, isolation, and comparison limits.

## Test Installation

Check the current environment:

```bash
pixi run verify-installation
```

Test installation in a temporary workspace:

```bash
pixi run test-installation
```

The `Installation` workflow tests Windows, macOS, and Red Hat UBI 8.10.
