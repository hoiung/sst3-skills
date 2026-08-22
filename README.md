# SST3 Skills

Claude Code plugin marketplace for the SST3 harness review, workflow, and subagent patterns.

## Install

```
/plugin marketplace add hoiung/sst3-skills
/plugin install ralph-review-trio@sst3-skills
/plugin install design-fidelity@sst3-skills
```

Then run `/ralph-review` on a finished implementation branch, or `/design-fidelity` to match a built site against a live reference.

## Plugins

### `ralph-review-trio`

Sequential three-tier code review. A reviewer at each tier runs a different-depth checklist; if any tier fails, the loop restarts from Tier 1. No next-tier-with-flag shortcut. The loop is bounded at up to 3 restarts; at restart 4 it escalates to a class sweep and then resumes with the count reset to zero for one final loop, after which an unresolved review stops and reports its outstanding findings rather than looping on.

| Tier | Model | Role |
|---|---|---|
| 1 | Haiku | Surface checks — file structure, commits, debug code, common-culprit scan |
| 2 | Sonnet | Logic checks — scope alignment, fail-fast policy, observability, cross-boundary contracts |
| 3 | Opus | Deep analysis — architectural fit, standards compliance, dead code, null propagation, config wiring, factual-claims audit |

Runs as a `/ralph-review` slash command that dispatches the three subagents in order with a restart-on-fail controller.

See `plugins/ralph-review-trio/skills/ralph-review-trio/SKILL.md` for the triggering instruction, and `plugins/ralph-review-trio/skills/ralph-review-trio/references/` for the per-tier checklists.

### `design-fidelity`

Visual design-fidelity loop. Capture headless full-page screenshots (desktop + mobile), compare a local build against a live reference, read the exact computed-CSS deltas, and pixel-diff the drift. Read-only: it measures and suggests CSS changes, never deploys or edits a live site.

| Step | Helper | Output |
|---|---|---|
| Shoot | `shoot.py` | full-page desktop + mobile PNGs, written outside any repo |
| Compare | `compare_computed_style.py` | per-selector computed-CSS deltas (spacing / colour / font) |
| Drift | `pixel-drift.sh` | AE + closeness% + a diff-highlight image |

Runs as a `/design-fidelity` slash command (`shoot` / `compare` / `diff`) over a per-page 3x iterate loop. The pixel-drift number is a trend diagnostic, never a hard pass-gate.

See `plugins/design-fidelity/skills/design-fidelity/SKILL.md` for the workflow, and `plugins/design-fidelity/skills/design-fidelity/references/` for the capture + computed-CSS + pixel-diff mechanics.

## What makes this pack different

- **Sequential restart-on-fail**: fail in any tier restarts from Tier 1, not "continue to next tier with warning". Bounded at up to 3 restarts, counting RESTARTS not rounds, then escalation instead of a fourth, then one final loop, then a terminal stop-and-report.
- **AP #18 Sample Invocation Gate**: for pipeline / CLI-wiring / cross-module function-arg propagation changes, reviewers require a REAL-CLI sample invocation against a real DB. Exit-code-0 alone is insufficient.
- **AP #20 Proof-of-Work governance**: canonical audit signal is the `## Proof of Work` section in the issue body — not timeline events. Tier A phase-deliverable vs Tier B cross-cutting-meta cadence discrimination.
- **AP #19 `structural_search_available` first-line discriminator**: every subagent RESULT block that discusses code-graph queries must declare structural-search availability on the first line, so the controller can distinguish "no structural-search access" from "lazy fallback".

## Provenance

Scrubbed from the private SST3 harness source at `dotfiles@9249dbf`. Business identifiers, private trading internals, and Hoi-specific filesystem paths removed. Review provenance kept intact so the pack retains its teeth.

## Licence

[MIT](LICENSE). Use, fork, publish, adapt.

## Links

- Author: [hoiung](https://github.com/hoiung) · [hoiboy.uk](https://hoiboy.uk)
- Issues / feedback: [GitHub Issues](https://github.com/hoiung/sst3-skills/issues)
- Full SST3 harness reference (public mirror): [SST3-AI-Harness](https://github.com/hoiung/sst3-ai-harness)

## Developer setup

Clone and install the pre-commit hooks before making changes. Pre-commit runs the voice guard + secret scanner locally; CI runs the same checks on every push and pull request.

```bash
git clone https://github.com/hoiung/sst3-skills.git
cd sst3-skills
pip install pre-commit
pre-commit install
```

Verify the hooks work:

```bash
pre-commit run --all-files
```

If this skips because no files are staged, add `--files <path>` or edit a file first.

## Contributing

Open an issue first. Keep PRs single-purpose.
