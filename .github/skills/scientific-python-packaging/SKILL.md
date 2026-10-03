---
name: scientific-python-packaging
description: Use only when a task concerns packaging scientific Python code for reuse, distribution, or ongoing maintenance; this skill is optional and is not a SciView project requirement.
---

# Scientific Python Packaging Skill

This is an optional, standalone reference adapted from external scientific-Python packaging guidance. It is not part of SciView's project instructions and does not imply that SciView needs packaging changes. Apply it only when the user's task concerns scientific Python packaging, reuse, or distribution.

Help make scientific Python software reusable, understandable, reproducible, and maintainable without changing scientific behavior merely to modernize its structure. Apply recommendations to the repository in front of you; this is guidance, not a mandatory scaffold.

## Use This Skill When

- Packaging analysis scripts or notebook code for reuse.
- Separating scientific calculations from file, facility, workflow, or interface code.
- Modernizing package metadata, installation, testing, documentation, or contribution workflows.
- Preparing a scientific project for community use or ongoing maintenance.

Do not package a one-off analysis unless the user asks for reuse or distribution.

## Start With The Existing Science

Before restructuring, identify representative inputs, outputs, units, coordinate/axis conventions, masks, calibration and metadata assumptions, and current entry points. Use existing examples or trusted outputs to characterize behavior where practical. Keep structural changes separate from algorithm changes; explain and validate intentional numerical changes.

Do not replace an algorithm for style alone. If behavior is unclear, ask for a representative example or design a small check with the user rather than inventing scientific assumptions.

## Boundaries And Public API

- Keep reusable calculations callable without a specific filesystem layout, notebook, GUI, private service, or live instrument whenever the current requirements allow it.
- Separate concerns where useful: scientific operations, data adapters, workflow orchestration, and presentation. These are conceptual boundaries, not a requirement to create a directory or class for each one.
- Use explicit inputs/outputs and document units, shapes, coordinate conventions, metadata expectations, and meaningful tolerances.
- Put facility-, instrument-, or source-specific assumptions in a clearly owned configuration or adapter, not in generic numerical functions.
- Prefer small composable functions or types with clear contracts. Introduce modules, classes, configuration frameworks, or compatibility layers only when they solve a real maintenance or reuse problem.
- Preserve public names and behavior when downstream users may depend on them. Coordinate breaking changes and migration paths with the user.

## Packaging Choices

- Inspect the current build backend, supported Python versions, dependency manager, and install workflow before recommending changes.
- For new Python packages, use a supported declarative project configuration such as `pyproject.toml`; choose the build backend and environment tool based on project constraints and compiled dependencies.
- Declare runtime and development dependencies in the mechanism the project actually uses. Add dependencies only for a concrete need and explain their role.
- Choose a source layout, command-line entry point, optional dependency groups, and version strategy when they serve the project; none is mandatory for every analysis library.
- Do not copy example version numbers, classifiers, dependency lists, licenses, CI matrices, or directory trees without verifying that they match the project's support policy and actual code.
- Keep private data, credentials, facility identifiers that should not be public, and machine-specific paths out of source control.

## Validation And Tests

- Use a small, representative check for scientific behavior before and after a refactor. Match numerical tolerances to the method and data; do not use exact float equality without a scientific reason.
- Keep contributor-facing tests proportionate: cover major supported functions/workflows and add focused regressions for confirmed defects or new behavior. Avoid sprawling tests of every internal branch or duplicated assertion.
- Prefer tests that run without private data, facility services, or hardware. When that is not possible, separate those integration checks and explain their prerequisites.
- Run the repository's focused checks and packaging/build checks that are relevant. Do not claim success for checks that were not run.
- Keep one-off runtime probes temporary and local unless the user asks to commit them.

## Documentation And Community Use

Document installation, one complete representative workflow, input/output expectations, scientific assumptions, limitations, and contribution steps to the level the project needs. Include citation, license, security, release, API, and governance files when they are appropriate to the project's distribution and community, not as a boilerplate checklist.

Examples should be small, runnable, and free of private infrastructure where possible. Preserve data provenance and cite sources for reference values or scientific standards.

## Staged Work

Prefer reviewable stages that leave the project usable:

1. Map current entry points, behavior, dependencies, and constraints.
2. Agree on scope and characterize important outputs.
3. Make one structural change at a time, preserving behavior.
4. Validate the affected public behavior and installation path.
5. Document new contracts and remove obsolete guidance only when the replacement is clear.

Do not begin a large migration until the user has agreed on its scope and the important behavior is understood.
