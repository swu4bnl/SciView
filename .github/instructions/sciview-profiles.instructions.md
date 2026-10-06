---
applyTo: "src/sciview/profiles/**/*.py"
---

# SciView beamline profile instructions

Beamline profiles contain beamline-specific behavior. CMS is the first profile, not the core design.

## Profiles may define

- detector names and aliases
- default calibration files
- default masks
- default recipes
- folder layout conventions
- optional filename patterns
- metadata mapping rules
- output directory preferences

## Requirements

- Keep profile-specific rules outside core modules.
- Any filename pattern or regular expression must live in a profile and must have tests.
- Prefer metadata and explicit configuration over filename matching.
- Keep profiles small and easy for another beamline to copy.
- Document profile assumptions in profile YAML or README files.

## Avoid

- Importing GUI modules.
- Calling SciAnalysis directly.
- Spreading CMS assumptions into generic modules.
