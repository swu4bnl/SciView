---
applyTo: "tests/**/*.py"
description: "Use when deciding which tests to retain or changing SciView pytest coverage."
---

# SciView testing instructions

## What belongs in the suite

- Retain coverage for scientific correctness, major workflows, public contracts, persistence, and consequential interactions between components.
- Add a regression when failure would compromise those contracts, not for every isolated control, helper, or implementation branch.
- Use one-off local checks for minor standalone UI behavior and cosmetics. Do not retain probes that lock down incidental wording, layout, assets, or internal call sequences.
- When revising tests, remove redundant or low-value cases and their unused fixtures/imports without weakening meaningful coverage.

## Execution

- Use pytest with small NumPy arrays and `tmp_path` fixtures; no facility mounts, large detector files, network access, or live services.
- Mock Tiled and expensive or unavailable SciAnalysis execution at the adapter boundary.
- Run the smallest relevant selection; run the retained file after pruning it. Report actual results and unresolved failures.
