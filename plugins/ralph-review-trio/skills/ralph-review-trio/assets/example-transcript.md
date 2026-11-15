# Example Ralph Review transcript

A scrubbed example of a Ralph Review pass over a small Python feature — adding a retry wrapper around an HTTP client. Branch: `solo/issue-42-http-retry`. Issue: "Add configurable retries to the OrderClient HTTP calls".

The three tiers ran in sequence with the controller `/ralph-review` command. Output below is condensed — real transcripts are longer.

---

## User invocation

```
> /ralph-review
```

## Controller — Tier 1 dispatch

Main agent dispatches `haiku-reviewer` against the current branch diff.

## Tier 1 — Haiku RESULT

```
## RESULT
structural_search_available: yes
verdict: pass
files_touched:
  - src/clients/order_client.py
  - src/clients/retry.py
  - tests/test_retry.py
findings:
  - path: src/clients/retry.py
    line: 34
    kind: GAP
    claim: debug print statement left in
    evidence: "print(f'retrying {attempt} of {max_retries}')"
  - path: src/clients/order_client.py
    line: 78
    kind: GAP
    claim: magic number in code (max_retries=3)
    evidence: "self._retry_wrapper(max_retries=3) — should be in config"
scope_gaps: none
```

`<promise>HAIKU_PASS</promise>`

Neither finding changes what a real request gets, so both are GAPs. Main agent fixes them in place:
- Remove the `print()` (commit `a3f12e9`)
- Move `max_retries=3` to `config/clients.yaml` under `order_client.max_retries`, read via `config.get('order_client.max_retries')` (commit `b84c5d1`)
- Run tests, all pass.

**The round continues to Tier 2.** Nothing is re-reviewed.

## Tier 2 — Sonnet RESULT

```
## RESULT
structural_search_available: yes
verdict: fail
files_touched:
  - src/clients/order_client.py
  - src/clients/retry.py
  - tests/test_retry.py
  - config/clients.yaml
findings:
  - path: src/clients/retry.py
    line: 22
    kind: PRODUCTION FAULT
    claim: a failed order is reported as placed
    input: the order service answers 503 on every attempt
    wrong_result: "the wrapper returns None with no error, so create_order() carries on as if the order was placed"
    evidence: "except requests.RequestException: pass  # silent fallback — no log, no metric"
  - path: tests/test_retry.py
    line: 51
    kind: GAP
    claim: mock accepts **kwargs — does not prove propagation
    evidence: "mock_call.assert_called()  # should be assert_called_with(max_retries=3)"
scope_gaps: none
```

**Fix cycle 1 of 2.** Main agent:
- Raises `RetriesExhausted` after the last attempt, with a structured log + a `retries_exhausted` counter metric (commit `c19f7a2`)
- Adds `test_raises_after_last_attempt`: green with the fix, red when the fix is reverted (commit `e02a6b4`)
- Fixes the GAP in place: `assert mock_call.call_args.kwargs['max_retries'] == 3` (commit `d55b908`)
- Runs the full test suite: green.

## Fix check — Sonnet RESULT (fix diff only: `c19f7a2`, `e02a6b4`)

```
verdict: pass
findings: []
```

`<promise>FIX_CHECK_PASS</promise>`

**The sequence resumes at Tier 3**, not Tier 1.

## Tier 3 — Opus RESULT

```
## RESULT
structural_search_available: yes
verdict: pass
files_touched:
  - src/clients/order_client.py
  - src/clients/retry.py
  - tests/test_retry.py
  - config/clients.yaml
findings: []
scope_gaps: none
governance_drift: none_detected
  - Tier A box "Add retry wrapper" closed at commit b84c5d1 — interleaves with phase 1 commits
  - Tier A box "Move max_retries to config" closed at commit b84c5d1 — same phase window
  - Tier B box "Fix Everything applied" closed at end — acceptable
spot_check:
  - structural_search_result: call sites of _retry_wrapper -> 1 caller
  - source_read: src/clients/order_client.py:78 — confirmed single call site
factual_claims: none added in this diff
```

`<promise>OPUS_PASS</promise>`

## Controller — final output

```
<promise>RALPH_PASS</promise>

Three tiers ran once each. 1 fix cycle of 2.
Production faults fixed: 1. Gaps fixed in place: 3.
Branch ready for merge.
```

---

## What this transcript demonstrates

- **Only a production fault fails a tier**: Tier 1's two findings were gaps. They were fixed in place and the round carried on.
- **Fix cycle, then the next tier**: Tier 2's fault got a fix, a test that fails when the fix is reverted, and one fix check on the fix diff. The sequence resumed at Tier 3, not Tier 1.
- **Bounded**: this run used 1 fix cycle. The loop allows at most 2 fix cycles; a third production fault goes to ONE fix agent, then one fix check, after which an unresolved review stops and reports its outstanding findings. The limit counts fix cycles, not faults.
- **Cross-boundary contract**: the `**kwargs`-swallowing mock was caught at Tier 2 — surface tier doesn't trace call-args assertions.
- **Governance cadence**: Opus tier classified the three checkbox closures correctly (two Tier A interleaved, one Tier B batched).
- **Graph spot-check**: Opus used graph to list callers, then read the source to confirm — never trusted the graph alone.
- **Silent fallback caught late**: the swallowed exception was invisible at surface; Tier 2 traced the exception path to find it.
