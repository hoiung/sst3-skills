---
name: ralph-review-trio
description: Run a sequential three-tier code review on a finished implementation branch — Haiku (surface) → Sonnet (logic) → Opus (deep). Only a production fault fails a tier; fixes are bounded at 2 fix cycles, then one fix agent, ending in a stop-and-report. Use when a solo branch or PR is code-complete and you want structured pre-merge verification before human review.
---

# Ralph Review Trio

This skill triggers `/ralph-review`, which runs three sequential reviewer subagents at increasing depth, each reviewing the whole diff once. A tier fails only on a PRODUCTION FAULT: shipped code gives a wrong result for an input a real user or system can send. The main agent fixes it, runs the tests, has one Sonnet fix check review the fix diff, and the sequence resumes at the next tier: at most 2 fix cycles. The limit counts fix cycles, not faults. A third production fault goes to ONE fix agent with write access on the strongest model available (Fable where offered), followed by one fix check; if that does not pass, the review stops and reports the outstanding findings rather than looping on. Test, doc and record gaps are fixed in place with no re-review; rare edge cases are recorded, not fixed.

## When to trigger

- An implementation is code-complete on a feature / solo branch.
- All acceptance criteria for the underlying issue are believed satisfied.
- Pre-merge verification is needed before human review or merge-to-main.
- You want structured evidence that each tier's checklist was walked.

## When NOT to trigger

- Work-in-progress branches mid-implementation — Ralph assumes the change is complete.
- Documentation-only diffs with no code — Tier 2/3 still run but most checks short-circuit to "doc-only PR" exemption; overkill for a single README edit.
- Hotfix branches where speed dominates verification — use the project's normal PR review.

## How it works

```
/ralph-review
    │
    ▼
  Tier 1  — Haiku  (surface checks)   ─── production fault ──> fix cycle, then Tier 2
    │  pass
    ▼
  Tier 2  — Sonnet (logic checks)     ─── production fault ──> fix cycle, then Tier 3
    │  pass
    ▼
  Tier 3  — Opus   (deep analysis)    ─── production fault ──> fix cycle, then PASS
    │  pass
    ▼
  RALPH_PASS  →  merge OK

  fix cycle  = fix + one test that fails when the fix is reverted → tests green
               → one Sonnet fix check on the fix diff
  limit      = 2 fix cycles → a third production fault goes to ONE fix agent
               → one fix check → PASS, or stop and report
```

A `<promise>HAIKU_PASS</promise>` / `<promise>SONNET_PASS</promise>` / `<promise>OPUS_PASS</promise>` token is emitted by each tier on pass. A tier that found a production fault is cleared by a passing fix check (`<promise>FIX_CHECK_PASS</promise>`).

## Entry point

`/ralph-review` — defined in `../../commands/ralph-review.md`.

## Per-tier checklists

- `../../agents/haiku-reviewer.md` — Tier 1 surface checklist
- `../../agents/sonnet-reviewer.md` — Tier 2 logic checklist
- `../../agents/opus-reviewer.md` — Tier 3 deep-analysis checklist

Extended reference content under `references/` (same dir as this SKILL.md) is loaded on demand by each tier when a specific check requires more context.

## Outputs

Each tier writes a fenced `## RESULT` block with:

```
## RESULT
structural_search_available: yes|no   # first line when discussing structural-search results
verdict: pass|fail|unknown
files_touched: [paths]
findings: [{path, line, claim, evidence, kind}]   # kind: PRODUCTION FAULT | GAP | RARE EDGE CASE
scope_gaps: [list or "none"]
```

The main agent reads the RESULT block and decides next action (next tier, a fix cycle, the fix agent, PASS, or stop-and-report).
