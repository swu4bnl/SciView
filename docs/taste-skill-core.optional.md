# Optional Reference: Taste-Skill Principles

**Status:** Optional inspiration, not a default instruction or project requirement. Use selectively when a UI task would benefit from a deliberate visual direction or a more systematic design review. The user's request, the product's established design, accessibility needs, scientific correctness, and project conventions take precedence.

This note distills transferable ideas from [Taste-Skill](https://github.com/leonxlnx/taste-skill) in original wording. It does not reproduce its full skill, code patterns, or visual prescriptions.

## What It Contributes

Taste-Skill combines two kinds of guidance:

- **Interaction and implementation discipline:** understand the brief, inspect the existing product before redesigning, preserve established behavior, account for interaction states, and review the finished interface.
- **Visual art direction:** choose and consistently execute a visual language for a particular audience and product, rather than falling into familiar generated-design defaults.

The first group transfers broadly to product interfaces. The second is useful when the task calls for visual exploration, but should be adapted to the product and user context rather than applied as a fixed style.

## Selective Principles

### Read The Product Context

Before changing an interface, identify the product surface, its users, their immediate task, the existing design language, and any constraints such as accessibility, platform, domain, or risk. Infer a coherent direction from those signals. Ask only when an unresolved choice could materially change the result.

### Audit Before Redesign

For an existing product, inspect its current patterns and important workflows first. Separate what is working and should remain stable from what is causing friction. Prefer targeted improvement over a visual reset; preserve established behavior unless the user approves a change.

### Make Style Choices Intentional

Avoid automatically reaching for familiar generated layouts, colors, typography, decorative labels, or animation. Do not ban a style merely because it is common: use it when it fits the product and audience. A visual choice should strengthen hierarchy, recognition, comprehension, or identity, not exist only to make the screen look more elaborate.

### Treat Interaction States As Part Of The Design

Review how the interface behaves beyond its ideal, populated state. Account for relevant loading, empty, success, error, disabled, selected, focus, and recovery states. Make action results visible, preserve keyboard access, and respect reduced-motion preferences when motion is present.

For consequential operations, make effects understandable and proportionate to their risk. Prefer preview, undo, and clear status over adding confirmations to routine reversible actions.

### Use Motion With A Reason

Use animation when it communicates hierarchy, feedback, a state change, or a meaningful sequence. Keep it restrained and non-blocking in operational interfaces. Do not add motion merely because an animation library or visual effect is available.

### Review The Finished Experience

Inspect the rendered UI and its actual visible wording, not only the component code. Check the changed task at practical window sizes and relevant themes. Confirm that labels predict outcomes, units and scientific terminology remain precise, and there are no misleading placeholders, clipped controls, or missing states.

## Applying It To Scientific Desktop Software

Taste-Skill's default examples and rules are primarily oriented toward web marketing pages and portfolios; its README explicitly says the main skill is not intended for dashboards and other dense product surfaces. For scientific desktop applications:

- Prioritize successful scientific work, clarity, trust, and learnability over dramatic composition.
- Keep useful information density when it supports comparison or analysis; do not add whitespace or imagery at the expense of the task.
- Prefer familiar desktop and domain conventions. Adapt patterns from other mature products when they fit the workflow, not just their appearance.
- Preserve scientific terms and units when they carry meaning; explain unfamiliar concepts in context instead of replacing them with vague labels.
- Keep data, calibration, masks, and other consequential state legible. Make previews and cross-view changes consistent with the underlying state.

## Boundaries

This reference does not require:

- Any particular visual aesthetic, palette, typeface, framework, icon library, animation library, or image-generation tool.
- Numerical style dials, a fixed number of layouts, or arbitrary bans on common components.
- A formal research study before each small UI refinement.
- A full redesign when the task is a focused usability fix.

Use the smallest set of principles that helps with the requested task. Do not let this optional reference silently expand scope or override the existing [UI and architecture skill](../.github/skills/ui-ux-architecture/SKILL.md).

## Source And Caveat

Taste-Skill's current default v2 is marked experimental by its maintainers. Its repository contains explicit anti-default rules and many hard-coded prescriptions tailored to particular visual categories. Treat those as the author's design opinions and project-specific heuristics, not universal HCI evidence. Recheck the upstream version before relying on its details.

Sources:

- [Taste-Skill README](https://github.com/leonxlnx/taste-skill)
- [Taste-Skill v2](https://github.com/leonxlnx/taste-skill/blob/main/skills/taste-skill/SKILL.md)
- [Taste-Skill redesign companion](https://github.com/leonxlnx/taste-skill/blob/main/skills/redesign-skill/SKILL.md)
- [Taste-Skill changelog](https://github.com/leonxlnx/taste-skill/blob/main/CHANGELOG.md)
