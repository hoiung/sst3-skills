# Playwright Fallback — E2E Browser Automation Without MCP

Cheap script-based E2E browser automation for the case when `chrome-devtools` MCP is disabled or unavailable mid-session.

## When to reach for playwright vs chrome-devtools MCP

| Situation | Use |
|---|---|
| chrome-devtools MCP enabled + tools visible in `ToolSearch` | Chrome DevTools MCP (canonical) |
| chrome-devtools MCP disabled by operator (`/plugin`) | **Playwright Python lib (this guide)** |
| chrome-devtools MCP enabled but tools didn't surface this session | **Playwright Python lib (this guide)** OR ask operator for Claude Code restart |
| Re-runnable regression check (CI-style, exit-coded) | **Playwright Python lib (this guide)** — one Bash invocation, scripted, replayable |
| One-off interactive browser inspection | Chrome DevTools MCP — orchestrate step-by-step via tool calls |

**Token-cost note**: a chrome-devtools MCP flow costs one tool-call per browser action (navigate, fill, click, screenshot) — 10-20 round-trips for a typical E2E. A playwright Python script is one `Bash` call returning all results in a single tool result. For repeatable checks the script is cheaper.

## When NOT to use playwright

- Operator has chrome-devtools MCP enabled AND it's surfaced this session → use the MCP (canonical SST3 path).
- Pure UI-poking with no scripted assertion → MCP is more natural; playwright requires writing a Python script first.

## Install (one-time per repo)

```bash
# In the consumer repo's .venv (any repo that runs a local preview build)
VIRTUAL_ENV=.venv uv pip install playwright    # ~45 MB
.venv/bin/python -m playwright install chromium  # ~115 MB chromium-headless-shell → ~/.cache/ms-playwright/
```

After install: `.venv/bin/python -c "from playwright.sync_api import sync_playwright; print('OK')"` exits 0.

## Idle cost

Zero. The Python lib lives as static files in `.venv/lib/python3.12/site-packages/playwright/`; the chromium binary lives in `~/.cache/ms-playwright/`. Neither spawns a process or holds a pipe open between script invocations. Compare to MCP servers, which boot at session start and stay alive for the session lifetime — that's why playwright is a clean fallback when chrome-devtools is intentionally off.

## Canonical pattern

Save script as `scripts/e2e_<topic>.py`. The script structure:

```python
from pathlib import Path
import json, sys, time
from playwright.sync_api import sync_playwright, Route, Request

REPO_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = REPO_ROOT.parent / "screenshots"   # canonical AC location
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

captured = {}

def intercept(route: Route, request: Request) -> None:
    """Capture POST body + short-circuit so no real backend job fires."""
    if request.method == "POST" and "/api/<target>" in request.url:
        captured["body"] = request.post_data_json or {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"success": True, "stub": True}))
        return
    route.continue_()

def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1920, "height": 1080}).new_page()
        page.route("**/api/<target>**", intercept)

        # Polling-dashboard pattern: avoid `wait_until="networkidle"` — it never settles
        # under continuous status polling. Use `domcontentloaded` + explicit selector +
        # a small fixed wait for React mount.
        page.goto("http://localhost:<port>/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_selector("#root", timeout=10000)
        page.wait_for_timeout(5000)

        page.screenshot(path=str(SCREENSHOTS_DIR / f"issue-<N>-default.png"), full_page=True)
        # ... interact, capture POST body, assert on `captured["body"]` keys ...
        assert "expected_field" in captured["body"], f"missing: {captured}"
        browser.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Run: `.venv/bin/python scripts/e2e_<topic>.py`. Exit 0 = PASS, non-zero = FAIL (assertion + traceback to stderr).

## Canonical example — production reference

A production E2E reference is a repo-local headless-chromium script that navigates the running dashboard, fills a form component, intercepts the outgoing `POST` request, asserts the expected field is present in the payload, and captures full-page screenshots. Exit 0 verifies that the change propagates end-to-end (React → API → subprocess) — the AP #18 Workflow/E2E-tier sample invocation.

## Live computed-CSS reads

When matching a build to a live reference you often need the EXACT rendered value
of a property, not an eyeball. `page.evaluate` runs JS in page context and can read
`getComputedStyle` for any selector, returning a plain property-dict back to Python.
Reuse the same `REPO_ROOT` / `SCREENSHOTS_DIR` / `headless=True` / `full_page=True`
script shape as above — only the read step changes:

```python
from pathlib import Path
import json, sys
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = REPO_ROOT.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

READ_JS = """
(args) => {
  const out = {};
  for (const sel of args.selectors) {
    const el = document.querySelector(sel);
    if (!el) { out[sel] = null; continue; }   // null, not throw — caller handles the miss
    const cs = getComputedStyle(el);
    const d = {};
    for (const p of args.props) { d[p] = cs.getPropertyValue(p); }
    out[sel] = d;
  }
  return out;
}
"""

def read_styles(url, selectors, props, width=1440, height=900):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": width, "height": height}).new_page()
        page.goto(url, wait_until="networkidle", timeout=45000)
        result = page.evaluate(READ_JS, {"selectors": selectors, "props": props})
        browser.close()
    return result   # {selector: {prop: value} | None}
```

Read once per viewport (1440 desktop + 390 mobile) to catch responsive deltas. A
missing selector returns `None` for that key (querySelector → null in JS) so the
caller reports which side is missing instead of raising a `KeyError`. The
design-fidelity skill's `compare_computed_style.py` is this pattern wrapped with a
diff + a px-tolerance + exit codes.

## Pixel-diff scoring

To put a NUMBER on how far a build is from its reference, diff the two PNGs with
ImageMagick `compare` (pixelmatch is NOT installed — ImageMagick is the engine).
First normalise the reference to the build's exact `WxH` (mandatory — IM 6.9.12
silently miscounts `AE` when the two inputs differ in size), then read both `AE`
(raw count of differing pixels) and `RMSE` (whose parenthesised normalised value
gives a closeness%):

```bash
dims=$(identify -format '%wx%h' local.png)
convert live.png -resize "${dims}!" live-normalised.png        # ! forces exact size (distort-to-compare)
compare -metric AE  local.png live-normalised.png diff.png      # rc 0=identical 1=differ 2=error; writes diff
compare -metric RMSE local.png live-normalised.png null:        # "<abs> (<normalised 0..1>)"  closeness = (1-norm)*100
```

`compare` returns 1 (not 0) for any non-identical pair — that is the NORMAL case,
so never wrap the diff in `set -e` (it would abort on the first real comparison);
check `rc==2` explicitly for a genuine ImageMagick failure. The number is a TREND
the operator watches decrease across iterations, never a hard pass-gate. The
design-fidelity skill's `pixel-drift.sh` is this one-liner wrapped with a policy.xml
probe guard + the normalisation + AE/closeness output.

## design-fidelity SKILL

The **design-fidelity SKILL** — visual design-fidelity loop that orchestrates these
mechanics (`SKILL.md`) — chains capture + computed-CSS
+ pixel-diff into a per-page 3x iterate loop. This guide is its mechanics
reference; the skill owns the loop orchestration.

## Gotchas

- **`wait_until="networkidle"` hangs forever** on any dashboard with continuous status polling. Use `"domcontentloaded"` + `wait_for_selector("#root")` + a short fixed `wait_for_timeout(5000)` instead.
- **`get_by_role(..., name=lambda ...)` fails** with `AttributeError: 'function' object has no attribute 'replace'`. The `name=` arg accepts only strings or regex objects (`re.compile(...)`), not callables.
- **First `playwright install chromium` is slow** (~115 MB download). Cache at `~/.cache/ms-playwright/` — persists across `.venv` recreations.
- **WSL/headless Linux**: works out of the box with the `chromium-headless-shell` build that `playwright install chromium` ships. No X server needed.
- **Route interception runs in browser context**: `request.post_data_json` requires the body to be JSON; for form-urlencoded payloads use `request.post_data` and parse manually.

## Relationship to AP #18 (sample-invocation discipline)

A playwright E2E script IS an AP #18 Workflow-Tier verification — it exercises the real frontend bundle + real API + intercepts the wire payload. Treat it as a per-Issue permanent artefact like `scripts/sample_invocation_issue<N>.py`: keep it after the Issue closes so any future change to the same plumbing can re-run it for regression. The script is one Bash invocation in the Stage 4 Verification Loop.

## See also

- `chrome-devtools-mcp.md` — canonical MCP browser-automation path
- SST3 `ANTI-PATTERNS.md` AP #18 — sample-invocation Workflow Tier
- SST3 `WORKFLOW.md` "Three-Tier Testing Framework" — where E2E fits in the test taxonomy
