# SST3 Skills

Claude Code plugin marketplace for the SST3 harness review, workflow, and subagent patterns.

## Install

```
/plugin marketplace add hoiung/sst3-skills
/plugin install ralph-review-trio@sst3-skills
```

Then run `/ralph-review` on a finished implementation branch.

## Plugins

### `ralph-review-trio`

Sequential three-tier code review. A reviewer at each tier runs a different-depth checklist; if any tier fails, the loop restarts from Tier 1. No next-tier-with-flag shortcut.

| Tier | Model | Role |
|---|---|---|
| 1 | Haiku | Surface checks — file structure, commits, debug code, common-culprit scan |
| 2 | Sonnet | Logic checks — scope alignment, fail-fast policy, observability, cross-boundary contracts |
| 3 | Opus | Deep analysis — architectural fit, standards compliance, dead code, null propagation, config wiring, factual-claims audit |

Runs as a `/ralph-review` slash command that dispatches the three subagents in order with a restart-on-fail controller.

See `plugins/ralph-review-trio/skills/ralph-review-trio/SKILL.md` for the triggering instruction, and `plugins/ralph-review-trio/references/` for the per-tier checklists.

## What makes this pack different

- **Sequential restart-on-fail**: fail in any tier restarts from Tier 1, not "continue to next tier with warning".
- **AP #18 Sample Invocation Gate**: for pipeline / CLI-wiring / cross-module function-arg propagation changes, reviewers require a REAL-CLI sample invocation against a real DB. Exit-code-0 alone is insufficient.
- **AP #20 Proof-of-Work governance**: canonical audit signal is the `## Proof of Work` section in the issue body — not timeline events. Tier A phase-deliverable vs Tier B cross-cutting-meta cadence discrimination.
- **AP #19 `mcp_graph_available` first-line discriminator**: every subagent RESULT block that discusses code-graph queries must declare MCP availability on the first line, so the controller can distinguish "no MCP access" from "lazy fallback".

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
