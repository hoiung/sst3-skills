---
description: Run the three-tier Ralph Review sequence (Haiku → Sonnet → Opus) on the current branch. Restarts from Tier 1 on any tier failure.
---

# Ralph Review

Run a sequential three-tier code review on the current feature / solo branch. Each tier dispatches a reviewer subagent that runs its own checklist at increasing depth. If any tier fails, fix the findings and restart from Tier 1.

## Agent dispatch — namespacing matters

Claude Code registers plugin-bundled agents under the `<plugin-name>:<agent-name>` namespace. Dispatching a bare `haiku-reviewer` will fail with `Agent type 'haiku-reviewer' not found`. Always dispatch with the full plugin prefix:

- `ralph-review-trio:haiku-reviewer`
- `ralph-review-trio:sonnet-reviewer`
- `ralph-review-trio:opus-reviewer`

## Controller logic

1. **Tier 1 — Haiku** (surface). Dispatch the `ralph-review-trio:haiku-reviewer` subagent with the diff scope and pass criteria. Wait for `<promise>HAIKU_PASS</promise>` or a failure report.
2. **On FAIL**: main agent applies fixes, commits per-file, then restarts from Tier 1. Do NOT proceed to Tier 2 with a flag. The restart loop is bounded at up to 5 restarts. The bound counts RESTARTS, not rounds: a restart is a return to Tier 1 after a FAIL, so round N+1 begins with restart N.
3. **On PASS**: proceed to Tier 2.
4. **Tier 2 — Sonnet** (logic). Dispatch `ralph-review-trio:sonnet-reviewer`. Same pass / fail logic.
5. **Tier 3 — Opus** (deep analysis). Dispatch `ralph-review-trio:opus-reviewer`. Same pass / fail logic.
6. On all three passes: emit `<promise>RALPH_PASS</promise>` and proceed to merge gate.

## Why restart-on-fail (not continue-with-flag)

Bugs caught by a later tier often invalidate earlier-tier findings. The surface-check pass on commit hygiene is meaningless if the deeper review surfaces a removed-and-re-added file. A fail at any tier says "go back and re-verify everything" — not "note the problem and keep going".

## Inputs

- Current git branch + diff against main (or the project's default branch).
- Issue number (if a solo branch named `solo/issue-NNN-...`).
- Expected Behavior / Acceptance Criteria from the issue body (if available).

## RESULT block schema (required from every tier)

```
## RESULT
structural_search_available: yes|no   # first line when discussing structural-search results
verdict: pass|fail|unknown
files_touched: [paths]
findings: [{path, line, claim, evidence}]
scope_gaps: [list or "none"]
```

The main agent parses the RESULT block. Prose body is informational only.

## Bash output discipline

Any command a reviewer runs that produces > 200 lines (pytest, git diff, log tail): capture to a file, report only the path + verdict in the RESULT block. Do not paste full output back to the main agent.

## Output

- On PASS: `<promise>RALPH_PASS</promise>` + summary of all three tiers' RESULT blocks.
- On FAIL (after all retries): the failing tier's RESULT block + main-agent-proposed fix list. No PASS promise emitted.

## Restart bound and escalation

Restart 6 is NOT taken. Escalate instead: run ONE class-sweep pass over the whole defect class, then resume the tier sequence with the restart count reset to zero. Each escalation MUST use a different method from the previous escalation in the same review, and records which method it used and what it cost - two identical sweeps fail identically. The cycle repeats - up to 5 restarts, escalate, up to 5 restarts, escalate. There is no stop-and-ask terminal state: the bound redirects effort, it never ends the review.

Only a finding that changes SHIPPED BEHAVIOUR restarts the sequence. A finding confined to tests, comments, or documentation is recorded and fixed, but does not restart from Tier 1. A finding that invalidates the EVIDENCE for an acceptance criterion counts as shipped behaviour and DOES restart.
