---
name: design-fidelity
description: Screenshot a webpage, compare a local build against the live site, match the design, and pixel-diff drift. Visual-design-fidelity loop — headless full-page captures (desktop+mobile), live computed-CSS reads, and ImageMagick pixel-drift scoring — reusable in any repo.
---

# Design-Fidelity — Visual Design-Fidelity Loop

Orchestrates the loop for matching a built site to a live reference: capture headless screenshots, compare to the live reference, read the exact computed CSS, tweak, re-shoot, and measure drift. The mechanics live in two guides; this skill packages the loop on top of them. Reusable in every repo where the skill directory is on the Claude Code skills path.

> **Scope contract (Invariant)**: this skill ONLY shoots screenshots, diffs them, reads computed CSS, and SUGGESTS CSS changes for the operator to apply. It NEVER deploys, NEVER edits live-site config or DNS, and NEVER pushes to a live site. It reads; the operator decides and edits. Screenshot output is always written OUTSIDE any git repo so a capture can never be committed.

> **Hard dependency**: the three helpers `scripts/shoot.py`, `scripts/compare_computed_style.py`, and `scripts/pixel-drift.sh`; the two mechanics guides `references/playwright-fallback.md` (capture + computed-CSS + pixel-diff command bodies) and `references/chrome-devtools-mcp.md` (MCP route); the `playwright` Python lib + its bundled `chromium_headless_shell` (per-repo `.venv` OR global python3 — the helpers fail loud with the install command if it is missing); and ImageMagick `compare` (the pixel-diff engine — pixelmatch is NOT installed). The skill is available in every repo where its directory is present on the Claude Code skills path.

## SST3 Anti-Patterns Governing This Skill

Before any action, respect these APs (full detail in the SST3 `ANTI-PATTERNS.md` standard):

- **AP #10 Duplicate Rules**: the capture / computed-CSS / pixel-diff MECHANICS live in the two guides. This skill points at them — it does NOT restate the command bodies. Grep the guides before adding any mechanic doc here.
- **AP #16 Monitor, Don't Fire-and-Forget**: after every `shoot.py` / `compare_computed_style.py` / `pixel-drift.sh` run, VERIFY the exit code and read the stderr telemetry (which wait-strategy fired, normalisation WxH, `compare` rc). "Ran the script" is not "got the shot".
- **AP #17 Keep Going Until Done**: a per-page 3x loop runs its iterations without pausing to ask "should I continue?". Stop ONLY at 80% context, a destructive action needing consent, genuinely stuck, or task complete.
- **AP #18 Sample-Invocation**: a real end-to-end shoot + compare + drift on one live page IS the Workflow/E2E-tier verification. Keep the per-repo `.design-fidelity.json` + the produced numbers as the evidence.

## Operator Prerequisites

- **playwright + chromium**: per-repo `.venv/bin/python -m playwright install chromium` (or global). WSL works out of the box with the bundled `chromium_headless_shell` — no Windows Chrome, no extra flags.
- **ImageMagick**: `compare`, `convert`, `identify` on PATH. On a host whose `policy.xml` denies the PNG coder, `pixel-drift.sh`'s probe guard fails loud — re-allow the PNG coder.
- **A reachable base_url**: the operator runs the local build server (e.g. `hugo server`) OR supplies a live URL. The skill does not own the server lifecycle by default (an opt-in `hugo` block exists for convenience).
- **A per-repo `.design-fidelity.json`** (optional): the page→path map, viewports, and out_dir for that repo. The sample values are an EXAMPLE, never a default.

## When to Invoke

- "Screenshot this page / the whole site at desktop and mobile."
- "Compare my local build against the live site and tell me what's off."
- "Match the design of <live site> — measure how close we are and what to change."
- "Show me the pixel-diff drift between local and live for the home page."
- Greenfield capture-only (no live reference yet): just shoot the build for review.

## Mandatory Reading on Invoke

1. `references/playwright-fallback.md` — the canonical capture + "Live computed-CSS reads" + "Pixel-diff scoring" mechanics (command bodies live HERE, not in this file).
2. `references/chrome-devtools-mcp.md` — the MCP route + the browser-state security note.
3. The per-repo `.design-fidelity.json` if it exists (page map / viewports / out_dir).
4. The screenshots output directory for the active repo under `~/DevProjects/screenshots/<repo>/` (where captures and diffs land — OUTSIDE the repo).

## The Per-Page 3x Iterate Loop

The framing, verbatim: "focus on one page at a time screenshot and re-iteration, screenshot, re-iteration, screenshot, re-iteration, up to 3 times until it's closely designed per page".

Work ONE page at a time. Each iteration runs this concrete dual-URL recipe:

1. **Shoot both sides at both viewports.** Shoot the LOCAL build (`shoot.py` with `base_url` = the local server) for the target page path at desktop (1440) + mobile (390), and shoot/cache the LIVE reference (`shoot.py` with `base_url` = the live base) for the same path at the same viewports. Capture local and live at identical viewport widths so the drift number is not inflated by stretch.
2. **Measure the gap.** Run `compare_computed_style.py --local-url <local> --live-url <live> --selector <target>` on the selector(s) you are matching (exact spacing / colour / font deltas per viewport), AND run `pixel-drift.sh <local.png> <live.png>` on the PNG pair (a measurable AE + closeness% + a diff-highlight image).
3. **Tweak and re-shoot.** Apply the smallest CSS change the deltas point to, rebuild the local site, then re-shoot and re-measure.

Repeat at most 3 times per page. Watch the drift number trend DOWN and the computed-CSS deltas shrink toward zero. Then move to the next page.

## Sub-Commands

- **`/design-fidelity shoot`** — capture only (`shoot.py`). Works STANDALONE with no live reference (greenfield repo): just produces full-page desktop+mobile screenshots for review.
- **`/design-fidelity compare`** — run the full per-page loop above against a live reference: `shoot.py` (local + live) → `compare_computed_style.py` → `pixel-drift.sh`. Fires ONLY when a live reference URL is supplied.
- **`/design-fidelity diff`** — re-run `pixel-drift.sh` on an existing local/live PNG pair to re-measure drift after a tweak.

## Triple-Check Discipline

> Maps to the Three-Tier Testing Framework (SST3 `STANDARDS.md` "Three-Tier Testing Framework").

- **Unit Tier**: `tests/run_unit_tests.sh` asserts each helper's contract (config-merge + parsers, the null-selector `_error` path, and the pixel-drift output binary) with no browser/live-site dependency.
- **Workflow Tier**: a real `shoot.py` capture run against a reachable `base_url`, exit 0, with the expected PNGs written outside the repo.
- **E2E Tier**: a full shoot + compare + drift on one live page end-to-end, producing a real drift number + diff image — the AP #18 sample-invocation.

## Security: chrome-devtools browser state

When you drive a LIVE site via the chrome-devtools MCP (the alternative to the headless playwright route), the MCP runs with full browser access — it can read open-tab cookies, auth tokens in request/response headers, pasted secrets in form fields, and cached credentials surfaced by the page (live browser state). Disable chrome-devtools via `/plugin` BEFORE pasting any secret. The DEFAULT route in this skill is headless playwright, which carries no live browser state, so prefer it. Full detail: `references/chrome-devtools-mcp.md` "Security note".

## Anti-Overfit Constraint

The pixel-drift number is a TREND diagnostic — the operator watches it decrease across iterations; it is NEVER a hard pass-gate. The target is a STRUCTURAL match, not pixel-perfection (anti-aliasing, font-hinting, and dynamic content make pixel-perfect impossible and pointless). The page→path map, `base_url`, and viewport list are PER-REPO config — the proto values are an example, NOT a default. Honestly across all repos: `shoot.py` is usable capture-only / standalone when there is no live reference (greenfield); the compare + pixel-drift loop fires ONLY when a live reference URL is supplied.

## File Locations

| File | Location |
|------|----------|
| Capture helper | `scripts/shoot.py` |
| Computed-CSS delta helper | `scripts/compare_computed_style.py` |
| Pixel-drift helper | `scripts/pixel-drift.sh` |
| Unit tests | `tests/run_unit_tests.sh` |
| Capture / computed-CSS / pixel-diff mechanics | `references/playwright-fallback.md` |
| MCP route + browser-state security | `references/chrome-devtools-mcp.md` |
| Per-repo config | `<consumer-repo>/.design-fidelity.json` |
| Screenshot output (OUTSIDE any repo) | `~/DevProjects/screenshots/<repo>/` |

## Skill Surface Contract

- Inputs: a `base_url` (local build or live), a page→path map, viewports, and optional selectors. Via `.design-fidelity.json` and/or CLI overrides.
- Outputs: full-page PNGs + diff-highlight PNGs under `~/DevProjects/screenshots/<repo>/`; computed-CSS deltas + drift numbers on stdout; decision-branch telemetry on stderr.
- Never writes into the consumer repo tree; never deploys; never edits the live site.
- Exit codes are load-bearing (AP #16): the helpers fail loud on a missing dependency, a blocked PNG coder, or a missing selector rather than producing a silent empty result.
- **The `.design-fidelity.json` config is treated as UNTRUSTED** (it is repo-local, so a cloned repo could ship a hostile one). `shoot.py`: the opt-in `hugo.cmd` launcher spawns NOTHING unless the operator passes the explicit `--allow-hugo-launcher` CLI flag (config alone can never start a process); when enabled it allowlists the executable to STATIC dev-servers only (hugo/jekyll/vite/serve/http-server — bare PATH names, no `./hugo` path component — and no interpreters or `npm run`-style wrappers) and rejects inline-code/eval flags; `base_url` is http(s)-only (no `file://`); page labels + viewport names must be `[A-Za-z0-9_-]+`; viewport width/height must be ints in `1..8192`; `scroll.step` must be a positive int (settle clamped); `out_dir` must resolve strictly UNDER `$HOME` or the system temp dir. Each violation is a loud exit 2.
- **Residual trust the threat model deliberately does NOT remove — only pass `--allow-hugo-launcher` on a repo you TRUST**: (1) `vite` and `jekyll` execute the repo's OWN build config (`vite.config.{js,ts}`, Jekyll `_config.yml`/`_plugins`) by design when they start, so launching them runs that repo's build code; `hugo`/`serve`/`http-server` do not. (2) `base_url`/page paths are scheme-restricted to http(s) but NOT host-filtered (the tool MUST reach `http://127.0.0.1:<port>` for local builds), so a hostile config can point captures at internal/loopback/cloud-metadata HTTP endpoints (e.g. `169.254.169.254`) — do not run an untrusted repo's config on a host with sensitive internal HTTP reachability.
