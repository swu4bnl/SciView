---
applyTo: "tests/**/*.py"
---

# SciView testing instructions

SciView tests must be deterministic and independent of live beamline infrastructure.

## Requirements

- Use pytest.
- Use tmp_path for file-system tests.
- Use small NumPy arrays for image and mask tests.
- Mock SciAnalysis when testing adapter behavior.
- Mock Tiled when testing Tiled integration.
- Do not require `/nsls2/data`.
- Do not require network access.
- Do not require a live Tiled server.
- Do not require large detector files.

## Test priorities

Add tests for:

- neutral data models
- workspace save/load
- local file-source behavior
- beamline profile discovery
- recipe validation
- mask I/O
- calibration I/O
- SciAnalysis adapter request/result behavior
- provenance generation
- error handling
