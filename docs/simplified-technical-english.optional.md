# Optional Reference: Simplified Technical English for SciView

**Status:** Optional language-review guidance, not a default instruction, formal style standard, or ASD-STE100 compliance claim. Use it when precise wording can improve a SciView workflow. Scientific correctness, established UI conventions, accessibility, and project instructions take precedence.

This note adapts transferable ideas from [danyuchn/asd-ste100-skill](https://github.com/danyuchn/asd-ste100-skill) in original wording. That skill applies principles from ASD-STE100 Simplified Technical English to agent-facing text. SciView uses a narrower adaptation for scientific desktop software.

## Where It Helps

Use these principles for text that users or tools must interpret correctly:

- Error and warning messages.
- Status-bar messages and progress text.
- Confirmation dialogs.
- Tooltips and short instructions.
- User documentation and troubleshooting steps.
- Agent instructions, tool descriptions, and structured handoffs.

Apply them lightly to compact labels, button text, table headings, protocol names, and metadata fields. These controls often need established domain terms rather than complete sentences.

Do not apply them mechanically to creative text, citations, quoted external messages, code, configuration keys, file names, or data supplied by a beamline or external service.

## Core Principles

### Preserve Meaning Before Shortening

A rewrite must keep every fact, condition, quantity, unit, exception, and scope limit. Keep words such as `may`, `can`, and `sometimes` when they express real uncertainty. Do not turn a possible cause into a confirmed cause.

Do not add a diagnosis or recovery step that the software cannot support. Clear but incorrect text is still incorrect.

### Use One Term For One Concept

Use the same term for the same object or action within a workflow. Do not rotate between near-synonyms only to vary the prose.

For example, choose the term that matches the actual action:

- **Browse** selects a file or folder through the operating system.
- **Open** displays a selected item in SciView.
- **Load** reads data into SciView.
- **Save** writes the current SciView state or configuration.
- **Export** writes a result for use outside the current workflow.
- **Remove** deletes one selected item from a collection.
- **Clear** removes all items or resets a whole view.
- **Stop** ends active work.
- **Cancel** abandons an operation before it completes.

Treat this list as a consistency guide, not a mandate for a repo-wide rename. Inspect each workflow before changing established labels.

### Keep Scientific Terms And Units

Keep precise domain terms such as calibration, mask, detector, reciprocal space, $q$, $q_x$, $q_z$, $\chi$, wavelength, and incident angle. Do not replace them with vague everyday words.

Use one notation and unit format consistently in a workflow. Define an unfamiliar term near its first use when the intended audience may not know it.

### Prefer Direct Sentences

Use an explicit actor and action when the actor matters:

- Prefer: "SciView could not load the mask."
- Avoid: "The mask could not be loaded."

Passive voice is acceptable when the actor is unknown or irrelevant. Do not add "SciView" to every status message when the interface already makes the actor obvious.

Prefer a direct verb over a noun phrase:

- Prefer: "Analyze the image."
- Avoid: "Perform an analysis of the image."

Prefer a single verb over an informal phrasal verb:

- Prefer: "Start the batch."
- Avoid: "Kick off the batch."

### Separate Actions And Conditions

Use one instruction per sentence. Put a condition before the action when the condition controls the action.

- Prefer: "Select a calibration file. Then refresh the preview."
- Avoid: "Select a calibration file and refresh the preview after it loads."

Use a numbered list for a procedure with three or more steps. Use bullets for independent options or conditions.

Short sentences are usually easier to scan. Treat 20 words for instructions and 25 words for descriptions as review prompts, not hard UI limits. Preserve necessary scientific precision even when a sentence must be longer.

### Remove Ambiguous References

Replace `it`, `this`, `that`, or `they` when more than one noun could be the referent.

- Prefer: "The mask dimensions do not match the image dimensions."
- Avoid: "It does not match the image."

Do not omit the subject, action, or object merely to reduce word count.

### Avoid Decorative Technical Prose

Remove words that claim quality without evidence, such as seamless, robust, powerful, effortless, or cutting-edge. Replace the claim with observable behavior when that behavior matters.

Avoid stacked hedges such as "might possibly be able to." Keep only the uncertainty that the software actually knows.

Avoid long noun clusters. Expand them when a reader could group the words in more than one way.

## Patterns For SciView UI Text

### Buttons And Menu Commands

Use a short action label that predicts the result. Include the object when several nearby actions could be confused.

- `Clear Queue` is clearer than `Clear` in a panel with multiple collections.
- `Export Combined Mask` is clearer than `Export` when individual layers can also be exported.

Do not add explanatory text inside a button. Put necessary detail in a nearby label, tooltip, or confirmation dialog.

### Tooltips

A tooltip must add information that the visible label or familiar icon does not provide. Do not repeat the button text in a full sentence.

Useful tooltip content includes:

- A precondition.
- The affected object.
- A unit or scientific constraint.
- The result of an unfamiliar icon action.

### Status And Progress Messages

State the current action or completed result. Include counts, identifiers, or the affected object when they help the user verify the outcome.

- Prefer: "Batch complete. 12 files succeeded. 1 file failed."
- Avoid: "Batch operation has been completed with mostly successful results."

Do not report success before the operation and its required cleanup are complete.

### Errors

Tell the user what failed. Add the known reason when it is safe and useful. Add a next action only when SciView can support that action.

A useful pattern is:

1. What failed.
2. Why it failed, if known.
3. What the user can do next, if known.

Examples:

- "SciView could not load the mask: unsupported array shape. Select a two-dimensional mask."
- "The preview failed: no calibration is selected. Select a calibration and refresh the preview."

Do not show a traceback, internal class name, or raw exception as the only user-facing explanation. Preserve technical details in logs for diagnosis.

### Warnings And Confirmations

Name the action and its consequence. Avoid a confirmation that says only "Are you sure?"

- Prefer: "Clear all images and references from this session?"
- Avoid: "Are you sure you want to continue?"

Prefer undo over confirmation for a routine reversible action. Use confirmation for actions that are destructive, expensive, or difficult to recover.

### Empty And Disabled States

State the missing requirement in the terminology used by the related control.

- Prefer: "Select a protocol to edit its parameters."
- Prefer: "Load an image before you create a mask layer."
- Avoid: "No data available."

## Review Process

1. Identify the user task and the UI state in which the text appears.
2. Confirm the behavior, cause, and recovery path in code before rewriting the text.
3. Preserve scientific terms, values, units, uncertainty, and scope.
4. Use consistent terms and direct verbs.
5. Split unrelated claims or instructions.
6. Read the text in its interface context. Remove words that only repeat a nearby label, control, or visible state.

If the original text is already clear, leave it unchanged. Do not force a rewrite to satisfy a checklist.

## Adoption Guidance

Apply this guidance incrementally when a workflow changes or when users report ambiguous text. Do not perform a repo-wide string rewrite without reviewing each workflow.

Keep terminology decisions close to the domain owner. A small project glossary can help when the same scientific concept appears in several tabs, but do not create a glossary only to restate obvious labels.

The upstream structural linter can identify some sentence patterns, but SciView does not depend on it. A clean linter result cannot prove that text is scientifically correct, contextually useful, or unambiguous.

## Boundaries

This reference does not require:

- The official ASD-STE100 controlled dictionary.
- Certified ASD-STE100 conformance.
- Fixed sentence lengths for every UI string.
- Removal of necessary scientific vocabulary.
- Active voice when the actor is genuinely irrelevant.
- Tooltips for self-explanatory controls.
- Simplification that changes confidence, causality, or scientific meaning.
- A new runtime dependency or mandatory language linter.

## Source And Caveat

The upstream skill is MIT-licensed and distinguishes structural guidance from dictionary-dependent lexical rules. ASD-STE100 itself has separate reproduction conditions. This document therefore summarizes transferable principles in original wording and does not reproduce the official controlled dictionary or claim compliance.

For certified ASD-STE100 work, obtain the current standard from the official source and follow its authorization terms.

Sources:

- [ASD-STE100 skill](https://github.com/danyuchn/asd-ste100-skill)
- [ASD-STE100 official site](https://www.asd-ste100.org/)
- [ASD Europe: Simplified Technical English](https://www.asd-europe.org/standards-specifications/simplified-technical-english/)
