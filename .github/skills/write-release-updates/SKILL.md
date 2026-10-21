---
name: write-release-updates
description: "Use when writing or revising SciView release notes, update messages, or user-facing GitHub PR descriptions. Prioritize user-visible changes, separate developer details, and use concise, direct language."
---

# Write release updates

Write for people who already use SciView. Explain what changed, not how to use
familiar features. Treat the user's latest draft and comments as the editorial
baseline; do not restore details they removed.

## 1. Establish scope and coverage

- Read the PR or commit diff and relevant source, not only its title or existing
  description.
- Identify substantive changes across the full revision. Classify them as
  user-facing, developer-facing, or not worth announcing.
- Distinguish new capabilities from existing behavior and fixes. Do not present
  an existing workflow as a new feature.
- Verify claims, limits, and performance comparisons. Do not imply that a
  proposed or merged change is already deployed.

Use this coverage check to avoid omissions, not as an outline to publish.
Complete coverage means covering meaningful changes, not every control or commit.

## 2. Select and order the message

- Lead with required user action or compatibility changes, if any. Otherwise,
  lead with the most important new capability.
- Follow with noticeable improvements, then consequential fixes.
- Use **For users** and **For developers** when both audiences need coverage.
  For a user-only request, omit developer details.
- Describe what users can now accomplish or experience. Group related controls
  around that outcome instead of listing features.
- Give each distinct major benefit its own point. Do not give minor fixes the
  same weight as major capabilities or group unrelated changes under vague
  headings.

In the user section, omit implementation mechanics, self-evident interactions,
obvious defaults, and unchanged behavior. Include a limit, persistence detail,
or exception only when it affects a meaningful decision or prevents a likely
misunderstanding.

Put architecture, dependencies, caching, localization infrastructure, diagnostic
tools, tests, and contributor guidance in the developer section when relevant.
Do not pad that section with routine cleanup.

## 3. Write the update

- Use short, direct sentences, concrete verbs, and consistent terms. Apply
  Simplified Technical English principles without claiming formal compliance.
- Preserve scientific meaning, units, conditions, and uncertainty.
- Avoid promotional claims, repeated benefits, and generic claims of improvement.
  State the observable change.
- Add instructions only for required migration or a non-obvious action. Verify
  exact commands and edits before including them.
- Use a short title and compact Markdown sections or bullets. Add source links
  where they help the reader act or investigate; do not turn the update into a
  source-file inventory.

## 4. Review before delivery

Check the draft against the full change set and the user's edits:

- Are the most important changes first, and are meaningful changes covered?
- Does each user-facing point describe a change without teaching a known workflow?
- Are technical details confined to the appropriate audience?
- Can self-evident detail, repetition, or a low-value item be removed?
- Are necessary actions and consequential limits still clear and accurate?

Return a publishable draft. Do not publish it or change the PR unless requested.
