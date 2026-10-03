---
applyTo: "src/sciview/processing/**/*.py"
---

# SciView processing instructions

Processing modules adapt SciView-neutral requests to processing backends such as SciAnalysis.

## Requirements

- GUI-independent.
- Receive ProcessingRequest or equivalent structured inputs.
- Return ProcessingResult or equivalent structured outputs.
- Capture warnings, errors, output files, runtime, and provenance.
- Validate inputs before running a backend.
- Keep backend-specific code isolated in adapter modules.
- Add tests using mocks when SciAnalysis is unavailable or expensive to run.

## SciAnalysis rules

- SciAnalysis is the first processing backend.
- Call SciAnalysis only through a SciView adapter.
- Start with file-backed processing.
- Add array-native processing only when the file-backed adapter is stable.
- Do not expose SciAnalysis internals to GUI widgets.

## Provenance

Processing runs should write or return:

- input references
- recipe name/version
- calibration reference
- mask reference
- output files
- software versions when available
- runtime
- status
- warnings/errors
