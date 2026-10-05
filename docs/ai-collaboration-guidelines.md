# AI Collaboration Guidelines (Generic)

This is a reusable, project-agnostic companion to [AI_CODING_WORKFLOW.md](AI_CODING_WORKFLOW.md). It is not the file GitHub Copilot or VS Code loads automatically — that file is [.github/copilot-instructions.md](../.github/copilot-instructions.md) at the repository root and takes precedence for SciView-specific rules. Use this doc for general collaboration habits that apply beyond SciView.

These are reusable collaboration and implementation preferences. Follow project-local instructions and established conventions when they add relevant detail; verify that project-specific claims are current before relying on them.

## Working Method

- Start from the named file, behavior, symbol, failure, or nearest test. Read only enough surrounding code to identify the controlling path.
- Before editing, form a falsifiable local hypothesis and identify a cheap check that could disprove it. Keep investigation proportional to the task.
- Distinguish observed facts from hypotheses and unverified claims. Consult authoritative source or documentation when framework behavior is uncertain.
- Fix the cause at the owning boundary. Make the smallest coherent change and validate the touched behavior before broadening the work.
- Preserve user changes in a dirty worktree. Do not discard, overwrite, or reformat unrelated work.
- Avoid speculative future requirements, unrelated cleanup, and unsolicited documentation or abstractions.
- Ask before substantial redesigns, established-workflow changes, or broad cross-module refactors. Small local fixes can proceed directly.
- When design or behavior has multiple reasonable tradeoffs, state the options and recommendation briefly; let the user choose when the choice materially affects their workflow.
- Treat a prompt as intent, not necessarily a complete specification. Resolve routine omissions from nearby code and established conventions; state assumptions that affect behavior, and ask or present options when a gap is consequential.
- Check the user's diagnosis and proposed approach against repository evidence. If they conflict, explain the evidence and recommend a better-supported path; do not silently replace the requested behavior when the alternative would materially change intent.

## Design And Maintainability

- Give each piece of state and each behavior one clear owner. Prefer one canonical representation with a small, one-way adapter at a real system boundary.
- Keep modules cohesive. Add a layer, helper, class, or compatibility path only when it owns meaningful behavior or removes real duplication.
- Prefer direct code that follows existing project patterns over a new abstraction or a generic framework for a one-off need.
- Prefer a maintained library's existing capability over a hand-rolled implementation when it fits the requirements and project constraints. Check existing dependencies first; justify any new dependency. Implement locally when performance, required customization, or a material mismatch makes the library a poor fit.
- Validate external or user-provided data at the boundary. Within a validated contract, avoid repeated defensive checks, broad exception swallowing, silent fallback behavior, and duplicated validation without a concrete failure mode. Handle expected recoverable failures clearly; let violated internal assumptions surface rather than disguising defects.
- Prefer standard library and domain-specific APIs for paths, structured data, and parsing. Do not introduce regular expressions; use explicit path operations, parsers, or straightforward string operations instead.
- Do not assume a directory layout, naming convention, instrument, platform, or service that the user has not provided. Ask for representative examples when an implementation depends on them.
- Use descriptive names and units where relevant. Comments should explain non-obvious decisions, not narrate the code.
- Name functions and methods for their primary responsibility and caller-relevant behavior. Avoid encoding internal mechanics, incidental optimizations, or implementation sequence in a name unless that detail is part of the function's contract or meaningfully distinguishes its behavior. Follow the codebase's naming conventions and prefer clear, concise names over both vague and over-specified ones.
- Keep comments sparse and purposeful. Document public API contracts and non-obvious scientific assumptions, units, or constraints where callers need them; avoid docstrings that merely restate a function's name or body.
- Preserve documented public behavior by default, but simplify or remove obsolete interfaces when the benefit is clear. Call out compatibility effects and migration cost; ask before changes that would materially disrupt downstream users or established workflows.

## User Interfaces

- Start from the user's task and workflow. Diagnose placement, grouping, naming, and duplicate controls before increasing size or visual weight.
- Preserve established interaction patterns unless asked to change them. Prefer familiar platform-native controls and the project's existing design system.
- Keep operational interfaces scannable and useful at practical window sizes. Consider keyboard use, accessible names/tooltips, feedback, disabled/loading states, and non-overlapping layouts where relevant.
- Do not add explanatory UI copy when a clear label or familiar control is enough.
- For a substantial redesign or workflow change, describe the intended behavior and alternatives and wait for approval before implementation.

## Checks And Tests

- Run focused local runtime checks or existing tests when they are available and useful. Report exactly what ran and what remains unverified.
- Keep temporary probes and exploratory checks local and uncommitted unless the user asks to retain them.
- Keep repository tests lean and useful to contributors: cover major supported functions/workflows and add focused regressions for confirmed bugs or new behavior. Do not generate exhaustive tests for every branch or implementation detail.
- Test the supported contract rather than accidental fallback behavior. Do not add a silent fallback or defensive path mainly to make a test pass; test recoverable invalid input only when that recovery is an explicit requirement.
- Follow the repository's existing test conventions. Avoid creating test infrastructure or a large suite solely to satisfy a generic checklist; discuss broader test expansion first.
- Do not claim a check passed unless it actually ran. Separate pre-existing warnings/failures from results caused by the change.

## Documentation And Handoff

- Update user or developer documentation when a change alters supported behavior, setup, or a stable interface. Do not create intermediate status documents or duplicate information.
- Keep the completion note concise: describe the material change, the checks performed, and any important limitation.
