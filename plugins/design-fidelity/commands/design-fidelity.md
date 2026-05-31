---
description: Run the visual design-fidelity loop — capture headless screenshots, compare a local build against a live reference, read computed-CSS deltas, and pixel-diff drift. Read-only: it measures and suggests, never deploys.
---

# Design-Fidelity

Invoke the design-fidelity skill to match a built site against a live reference. The skill bundles three helpers (`shoot.py`, `compare_computed_style.py`, `pixel-drift.sh`) and two mechanics references (`playwright-fallback.md`, `chrome-devtools-mcp.md`). Read the bundled `SKILL.md` first — it is the authoritative workflow; this command is a thin entry point.

## Sub-commands

- **`/design-fidelity shoot`** — capture only. Works standalone with no live reference (greenfield): full-page desktop + mobile screenshots for review.
- **`/design-fidelity compare`** — the full per-page loop against a live reference: `shoot.py` (local + live) → `compare_computed_style.py` → `pixel-drift.sh`. Fires only when a live reference URL is supplied.
- **`/design-fidelity diff`** — re-run `pixel-drift.sh` on an existing local/live PNG pair to re-measure drift after a tweak.

## The per-page 3x iterate loop

Work one page at a time. Each iteration: (1) shoot both the local build and the live reference at both viewports (desktop 1440, mobile 390) for the target path; (2) measure the gap with `compare_computed_style.py` (computed-CSS deltas) and `pixel-drift.sh` (AE + closeness% + a diff-highlight image); (3) apply the smallest CSS change the deltas point to, rebuild, re-shoot, re-measure. Repeat at most 3 times per page, watching the drift number trend down, then move on.

## Scope contract (invariant)

This skill only shoots screenshots, diffs them, reads computed CSS, and suggests CSS changes. It never deploys, never edits live-site config or DNS, and never pushes to a live site. Screenshot output is always written outside any git repo so a capture can never be committed. The pixel-drift number is a trend diagnostic, never a hard pass-gate — the target is a structural match, not pixel-perfection.

## Configuration

An optional per-repo `.design-fidelity.json` carries the page→path map, viewports, and output directory. Treat it as untrusted (it is repo-local): the opt-in build-server launcher spawns nothing unless the explicit `--allow-hugo-launcher` flag is passed, and even then allowlists static dev-servers only. See the bundled `SKILL.md` "Skill Surface Contract" for the full threat model.
