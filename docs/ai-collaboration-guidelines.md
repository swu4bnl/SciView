# AI Collaboration Guidelines (Generic)

Reusable working preferences, not automatically loaded instructions. SciView's active rules are in [.github/copilot-instructions.md](../.github/copilot-instructions.md) and its scoped [instruction files](../.github/instructions/).

## Scope and evidence

- Trace the requested behavior to its owner before editing. Distinguish observed facts from assumptions and verify the outcome directly.
- Make the smallest complete change; preserve unrelated work and avoid speculative abstractions or future requirements.
- Resolve routine omissions from existing conventions. Ask when uncertainty would materially change scope, workflow, or compatibility.

## Design

- Give state and behavior clear owners. Reuse existing APIs and libraries; add layers only for meaningful boundaries or real duplication.
- Validate at external boundaries and surface failures explicitly rather than disguising them with fallbacks.
- Keep UI guidance focused on user decisions. Preserve domain precision while omitting incidental technical detail.

## Verification

- Use focused existing tests or local checks. Retain tests for important behavior and component contracts, not every minor standalone feature or internal detail.
- Keep exploratory probes uncommitted and remove their temporary artifacts. Report what actually ran and what remains uncertain.

## Documentation

- Document meaningful workflows, setup, contracts, and non-obvious consequences; omit self-explanatory secondary controls.
- Keep reusable rules concise, abstract, and proportionate. Replace outdated guidance instead of accumulating examples, duplicates, and routine reminders.
- Keep handoffs brief: outcome, validation, and material limitations.
