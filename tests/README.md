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

Keep tests for stable product contracts, including:

- Image coordinates and display transformations.
- Source-data preservation.
- Shared image and display state.
- Mask composition and boundary handling.
- Application imports and installation checks.
- User-visible error and disabled states.

Remove temporary probes after the focused change passes. Do not keep tests that only assert private fields, exact callback counts, removed controls, or unfinished external-service behavior.

Mock external services. Do not require network access, authentication, live beamline services, or large detector files.

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
