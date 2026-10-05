# SciView Docs Index

This folder holds SciView-specific architecture notes, process guides, and a user-facing how-to. Generic, project-agnostic skills live outside this folder, under [.github/skills/](../.github/skills/) (and, for Claude Code, [.claude/skills/](../.claude/skills/)) so they are auto-discoverable by the agent tooling.

Reorganized 2026-10-03 — see git history on this folder for what changed and why.

## SciView-specific (keep these current as the code changes)


| Doc                                                          | Purpose                                                                                                                                        |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| [ARCHITECTURE.md](ARCHITECTURE.md)                           | Layered architecture summary (interfaces -> backend API -> adapters -> external systems).                                                      |
| [ROADMAP.md](ROADMAP.md)                                     | Stage-by-stage backend refactor status. Check against`src/sciview/` before trusting a stage's checkbox.                                        |
| [ANGLE_CONVENTION_GUIDE.md](ANGLE_CONVENTION_GUIDE.md)       | Canonical display angle convention and the SciAnalysis conversion boundary. Required reading before touching reduction/overlay angle code.     |
| [UI_CONTROL_ARCHITECTURE.md](UI_CONTROL_ARCHITECTURE.md)     | How`AppStyle` tokens, templates, and runtime theme refresh fit together. Pair with the `sciview-ui-tweaks` skill for the actionable checklist. |
| [CONTRIBUTING.md](CONTRIBUTING.md)                           | Where a new feature belongs (core, source, profile, processing, interface, tests, docs).                                                       |
| [USER_HOW_TO.md](USER_HOW_TO.md)                             | End-user tutorial for the desktop app, one page per tab. Screenshots are placeholders — see its checklist before publishing.                  |
| [SciView-project-reference.md](SciView-project-reference.md) | Compact orientation snapshot of the repo shape; re-verify details before relying on them.                                                      |

## Generic / reusable (not SciView-specific; apply only when relevant)


| Doc                                                              | Purpose                                                                                                                                                               |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [AI_CODING_WORKFLOW.md](AI_CODING_WORKFLOW.md)                   | SciView-flavored prompt templates for keeping AI coding tasks small and bounded.                                                                                      |
| [ai-collaboration-guidelines.md](ai-collaboration-guidelines.md) | Project-agnostic collaboration/working-method notes. Not the file Copilot auto-loads — that is[.github/copilot-instructions.md](../.github/copilot-instructions.md). |
| [taste-skill-core.optional.md](taste-skill-core.optional.md)     | Optional visual-design-review reference; explicitly not a default instruction.                                                                                        |

## Moved out of this folder

- `scientific_python_packaging.skill.md` -> [.github/skills/scientific-python-packaging/SKILL.md](../.github/skills/scientific-python-packaging/SKILL.md)
- `ui-ux-architecture-lessons.md` -> [.github/skills/ui-ux-architecture/SKILL.md](../.github/skills/ui-ux-architecture/SKILL.md)

Both had skill-style frontmatter (`name`/`description`) and are auto-discoverable as skills once under `.github/skills/<name>/SKILL.md` — leaving them flat in `docs/` meant they weren't picked up by the skill system.

## Removed

- `copilot-instructions.md` (confusing duplicate name of the real `.github/copilot-instructions.md`; content kept, renamed to `ai-collaboration-guidelines.md`).
- `TOMORROW_CHECKLIST.md` (a stale, session-specific scratch note from an early commit-splitting session; fully superseded by actual commits and this roadmap).
