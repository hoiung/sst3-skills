---
description: Run the three-tier Ralph Review sequence (Haiku → Sonnet → Opus) on the current branch. Only a production fault fails a tier; at most 2 fix cycles, then one fix agent.
---

# Ralph Review

Run a sequential three-tier code review on the current feature / solo branch. Each tier dispatches a reviewer subagent that runs its own checklist at increasing depth and reviews the whole diff once.

The bar: simple code that works reliably for the inputs that really arrive. Not coverage of every conceivable case.

## Agent dispatch — namespacing matters

Claude Code registers plugin-bundled agents under the `<plugin-name>:<agent-name>` namespace. Dispatching a bare `haiku-reviewer` will fail with `Agent type 'haiku-reviewer' not found`. Always dispatch with the full plugin prefix:

- `ralph-review-trio:haiku-reviewer`
- `ralph-review-trio:sonnet-reviewer`
- `ralph-review-trio:opus-reviewer`

## Controller logic

1. **Tier 1 — Haiku** (surface). Dispatch the `ralph-review-trio:haiku-reviewer` subagent with the diff scope and pass criteria. Wait for `<promise>HAIKU_PASS</promise>` or a failure report.
2. **Sort every finding** into one of the three kinds below. The reviewer proposes the kind; the main agent decides it and writes one line of reason.
3. **On a PRODUCTION FAULT**: run a fix cycle (below), then resume at the NEXT tier. Do not return to Tier 1.
4. **Tier 2 — Sonnet** (logic). Dispatch `ralph-review-trio:sonnet-reviewer`. Same logic.
5. **Tier 3 — Opus** (deep analysis). Dispatch `ralph-review-trio:opus-reviewer`. Same logic. After an Opus production fault, a passing fix check is the overall pass.
6. On pass: emit `<promise>RALPH_PASS</promise>` and proceed to merge gate.

## The three kinds of finding

| Kind | Test | Outcome |
|------|------|---------|
| PRODUCTION FAULT | Shipped code gives a wrong result for an input a real user or system can send. The finding names the input and the wrong result. | A fix cycle. |
| GAP | Anything that does not change what a real input gets: a missing, weak or vacuous test, doc drift, a record gap, dead or duplicate code, a hardcoded value, a missing log line. | The main agent fixes it in place and runs the tests. The round continues. Nothing is re-reviewed. |
| RARE EDGE CASE | Needs a chain of unlikely events, or an input no shipped path sends. | Recorded for the human reviewer, not fixed. |

- Only a PRODUCTION FAULT starts a fix cycle. A finding with no named input and wrong result is not a PRODUCTION FAULT.
- A RARE EDGE CASE whose consequence is money loss, data loss or a security hole is a PRODUCTION FAULT.
- A repaired or new test that fails on shipped code is a PRODUCTION FAULT.

## Fix cycle

At most 2 fix cycles. The limit counts fix cycles, not faults.

1. Fix every production fault in that tier's report, with one test that fails when the fix is reverted. Findings that share a root cause are fixed at the shared cause, not symptom by symptom. Commit per file.
2. Run the test suite until green.
3. Dispatch `ralph-review-trio:sonnet-reviewer` as a "Fix check" on the fix diff only.
4. Fix check passes: the sequence resumes at the tier after the one that found the fault, and that tier reviews the whole diff.
5. A production fault found by the fix check starts the next fix cycle.

## Escalation: one fix agent

A third production fault is NOT a third fix cycle. Dispatch ONE fix agent with write access on the strongest model available (Fable where offered). Give it the issue, the whole diff, and every earlier finding and fix.

- It finds the root cause, writes the fix and its test, and runs the tests. It is the only subagent here that writes code.
- The main agent does not edit while it runs. Afterwards the main agent reads its diff, runs the test suite and commits.
- Then one fix check of that diff.
- Pass: the remaining tiers run. Any further production fault is a stop.
- Fail, or no fix agent can be dispatched: stop.

A stop is a report to the human, never a silent abandon: every outstanding finding with its kind, what was tried, and the question ship or fix. No second escalation, no further cycle.

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
findings: [{path, line, claim, evidence, kind}]   # kind: PRODUCTION FAULT | GAP | RARE EDGE CASE
scope_gaps: [list or "none"]
```

The main agent parses the RESULT block. Prose body is informational only.

## Bash output discipline

Any command a reviewer runs that produces > 200 lines (pytest, git diff, log tail): capture to a file, report only the path + verdict in the RESULT block. Do not paste full output back to the main agent.

## Output

- On PASS: `<promise>RALPH_PASS</promise>` + summary of all three tiers' RESULT blocks, with every recorded GAP and RARE EDGE CASE.
- On a stop: every outstanding finding with its kind and what was tried. No PASS promise emitted.
