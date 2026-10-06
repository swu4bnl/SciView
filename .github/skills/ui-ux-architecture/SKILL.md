---
name: ui-ux-architecture
description: Use when designing or changing an application's interface, interaction flow, shared state, or boundaries between UI and domain/external systems. Focus on user workflows, clear ownership, and proportionate architecture.
---

# UI And Architecture Design Skill

Apply this skill to desktop, web, and other interactive applications. First inspect the concrete workflow and the code that owns it; do not assume that a lesson from another project maps directly to this one.

For SciView-specific UI token/style rules (AppStyle, CSS_TOKENS, LAYOUT), use the `sciview-ui-tweaks` skill instead or alongside this one — this skill covers general product/UX reasoning, not SciView's concrete style system.

## Product Discovery And Iteration

- Start with the person, their context, and the task outcome. Identify what users are trying to accomplish, what currently gets in their way, and what a successful outcome looks like before proposing UI changes.
- Infer one coherent design direction from the audience, task, domain, existing product, and constraints. Prefer the current design system and established conventions; do not impose a fashionable aesthetic or fixed style presets. State a consequential assumption when the brief leaves the direction unclear.
- Use proportionate evidence. Prefer observing realistic tasks and concrete friction; also use user feedback, support requests, domain workflow knowledge, and usage or error data when available. Do not require formal research for every small improvement.
- Treat stated preferences as useful evidence, not a substitute for seeing whether users can complete the task. When direct user access is limited, say what is known, what is inferred, and what remains uncertain.
- Borrow proven interaction conventions from mature products, including outside the application's domain, when they fit users' context and task. Adapt the pattern; do not copy a product's screen or brand without understanding why the pattern works.
- Treat product quality as more than visual polish: aim for a coherent, dependable experience that users can learn, trust, and choose to use. Continue iterating as useful evidence and product needs evolve; avoid changes justified only by novelty or personal taste.
- For substantial redesigns or established workflow changes, present the user problem, intended outcome, and reasonable alternatives before editing. Small, reversible refinements can proceed directly.
- Before redesigning an existing interface, audit its current visual language, information structure, core workflows, and interaction states. Identify what is working and should be preserved, what causes observed friction, and what is safe to change. Do not treat an existing product as a blank canvas.

## Progressive Learning

- Give new users a clear, approachable path through common tasks without making expert workflows needlessly slow.
- Introduce advanced controls near the task where they become relevant. Prefer progressive disclosure and concise, optional in-context guidance over a forced tutorial users must memorize.
- Support learning by doing: make effects visible promptly, provide useful previews, and make experimentation safe with undo or a clear way to cancel where appropriate.
- For settings that affect scientific interpretation and actions that can overwrite or delete work, make the current state and consequence clear. Prefer preview and recovery; reserve confirmation for irreversible or high-cost actions rather than adding it to routine reversible steps.
- Use familiar platform and product conventions to reduce relearning. Use domain-specific interaction when it materially improves the scientific task, and make that rationale clear.

## Product Language And Consistency

- Keep terminology, units, command wording, status messages, and interaction patterns consistent across the product where they refer to the same concept.
- Be consistent, not mechanically uniform: allow a tab or workflow to differ when its task, risk, or user context genuinely differs.
- Use precise scientific terms when they matter for correctness. Clarify unfamiliar terms, units, or consequences briefly and in context rather than replacing precision with vague everyday wording.
- Write labels and actions so users can predict what will happen. Keep status, preview, success, and error feedback specific to the user's task; avoid unexplained internal jargon and generic messages.
- Reuse shared components and design rules where they reduce inconsistency and maintenance, while allowing evidence-based exceptions. Do not impose a design system or component abstraction without a real recurring need.

## Workflow Before Appearance

When something is hard to find, understand, or use, inspect:

1. **Placement:** Is the control near the task or object it affects?
2. **Grouping:** Is it separated from unrelated decisions and grouped with related ones?
3. **Naming:** Could nearby labels be mistaken for duplicate or synonymous settings?
4. **Redundancy:** Is the same value independently editable or represented in multiple places?
5. **Visual weight:** Only after the above, adjust emphasis, size, or color.

Make small local improvements directly. For substantial redesigns or changes to an established workflow, present the behavior change and reasonable options, then wait for approval. Do not silently turn a usability fix into a broad redesign.

## Interaction And Presentation

- Preserve the application's visual language and platform conventions. Use the project's shared style system where one exists.
- Prefer familiar controls for familiar actions. Give unfamiliar icon-only controls an accessible name and a discoverable tooltip or equivalent.
- Keep working interfaces compact and scannable; give the primary work area room to expand.
- Consider realistic window sizes, keyboard interaction, focus, empty/loading/error states, and whether state changes are visible to the user.
- Solve discoverability through task order and grouping before decorative treatment or added instructional text.

## State, Ownership, And Boundaries

- Trace the real data flow and determine which component owns each value before changing it.
- Keep one canonical representation for a value that multiple consumers share. Derive previews and views from that state rather than maintaining parallel copies.
- Translate data only at a genuine boundary between distinct APIs or formats. Prefer a small, explicit, one-way adapter over duplicated state, inheritance between unrelated concepts, or a generalized conversion framework.
- Scope an adapter to the inputs it understands. Preserve other legitimate flows rather than forcing them through a translation they do not need.
- Prefer explicit fields/allowlists for external calls so internal routing or UI metadata cannot leak across the boundary.
- Validate constrained input where it enters the owned model or service. Downstream code may rely on that contract; do not repeat checks at every layer without a concrete reason.
- Do not add compatibility fallbacks, implicit object creation, caches, or wrappers to hide uncertainty. Confirm the actual contract and solve the current failure.

## Investigation And Change Size

- Confirm the behavior in the current code and, when needed, in the framework/library source. Treat a symptom report as a prompt to trace the mechanism, not as proof of its cause.
- Separate observed facts from hypotheses. If a proposed fix only hides a symptom, say so and continue to the underlying owner when feasible.
- Change one coherent slice at a time. Validate it before checking sibling components for the same bounded failure pattern.
- Inspect siblings when a shared defect is plausible, but do not turn that check into an unrequested repository-wide refactor.
- When a tradeoff changes user-visible behavior or scientific meaning, state it plainly and let the user decide if no default is clearly correct.

## Completion

For a UI or architecture change, report the behavior that changed, the owner/boundary involved, checks run, and any remaining uncertainty. Do not imply that a visual or underlying-state problem is solved if only its display was changed.
- Before handoff, review the actual interface and visible copy in the changed flow. Check relevant empty, loading, success, and error states, plus practical window sizes, keyboard/focus access, and theme or reduced-motion behavior where the product supports them.
