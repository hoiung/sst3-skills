---
name: design-fidelity
description: Picture every page a change touches at each declared viewport (default desktop 1440 + phone 390) and read every picture, after ANY change to a rendered page (the sst3-page-review hook prints the shoot command); also compare a local build against the live site, match the design, and pixel-diff drift. Headless full-page captures, live computed-CSS reads, and ImageMagick pixel-drift scoring, reusable in any repo.
---

# Design-Fidelity — Visual Design-Fidelity Loop

> **Scope contract (Invariant)**: this skill ONLY shoots screenshots, diffs them, reads computed CSS, and SUGGESTS CSS changes for the operator to apply. It NEVER deploys, NEVER edits live-site config or DNS, and NEVER pushes to a live site. It reads; the operator decides and edits. Screenshot output is always written OUTSIDE any git repo so a capture can never be committed.

> **Related**: drawing/annotating a schematic diagram (not matching a live page)? See `docs/guides/diagram-annotation-qa.md` (`../dotfiles/docs/guides/...` from a consumer repo) — it reuses this skill's `shoot.py` for the render-and-inspect step of the Hybrid diagram pipeline.

> **Hard dependency**: the three helpers `scripts/shoot.py`, `scripts/compare_computed_style.py`, and `scripts/pixel-drift.sh`; the two mechanics guides `references/playwright-fallback.md` (capture + computed-CSS + pixel-diff command bodies) and `references/chrome-devtools-mcp.md` (MCP route); the `playwright` Python lib + its bundled `chromium_headless_shell` (per-repo `.venv` OR global python3 — the helpers fail loud with the install command if it is missing); and ImageMagick `compare` (the pixel-diff engine — pixelmatch is NOT installed). The skill is available in every repo where its directory is present on the Claude Code skills path.

The capture, computed-CSS and pixel-diff mechanics live in the two guides; this file points at them (ANTI-PATTERNS.md AP #10, AP #16, AP #18).

## Operator Prerequisites

- **playwright + chromium**: per-repo `.venv/bin/python -m playwright install chromium` (or global). WSL works out of the box with the bundled `chromium_headless_shell` — no Windows Chrome, no extra flags.
- **ImageMagick**: `compare`, `convert`, `identify` on PATH. On a host whose `policy.xml` denies the PNG coder, `pixel-drift.sh`'s probe guard fails loud — re-allow the PNG coder.
- **A reachable base_url**: the operator runs the local build server (e.g. `hugo server`) OR supplies a live URL. The skill does not own the server lifecycle by default (an opt-in `hugo` block exists for convenience).
- **A per-repo `.design-fidelity.json`** (optional): the page map below. The sample values are an EXAMPLE, never a default.

## When to Invoke

- After ANY change a person sees rendered (a page, HTML email, print PDF, social card): `shoot` every touched page at each declared viewport and Read every PNG, every time, never only on request. The `sst3-page-review` hook holds Stop and a push to the default branch until each picture, newer than its page's last change, has been Read, and prints the exact `shoot` command (rule: STANDARDS.md "Three-Tier Testing Framework" Run procedure step 3; dotfiles#583).
- "Screenshot this page / the whole site at desktop and mobile."
- "Compare my local build against the live site and tell me what's off." / "Match the design of <live site>." / "Show me the pixel-diff drift for the home page."
- Greenfield capture-only (no live reference yet): just shoot the build for review.

## Mandatory Reading on Invoke

1. `references/playwright-fallback.md` — the canonical capture + "Live computed-CSS reads" + "Pixel-diff scoring" mechanics (command bodies live HERE, not in this file).
2. `references/chrome-devtools-mcp.md` — the MCP route + the browser-state security note.
3. The per-repo `.design-fidelity.json` if it exists.
4. The screenshots output directory for the active repo under `~/DevProjects/screenshots/<repo>/` (OUTSIDE the repo).

## The page map (`.design-fidelity.json`)

```json
{ "base_url": "http://127.0.0.1:1313", "pages": { "home": "/", "about": "/about" },
  "viewports": [ { "name": "desktop", "width": 1440, "height": 900 }, { "name": "mobile", "width": 390, "height": 844 } ],
  "page_files": { "layouts/**": ["home", "about"], "content/about.md": ["about"] },
  "ignore_files": [ "reports/**" ], "fixed_size_files": [ "templates/letter.html" ] }
```

- `base_url`, `pages` (label to path), `viewports` (default desktop 1440x900 + mobile 390x844), `out_dir`, `scroll`, `hugo`: read by `shoot.py`.
- `page_files`, `ignore_files`, `fixed_size_files`: read by the `sst3-page-review` hook only. `page_files` is a list of globs, or `{glob: [page labels]}` so the hook names those pages and its printed command shoots only them; `ignore_files` drops matches (generated reports); `fixed_size_files` marks a true-size output, satisfied by one fresh picture of any width. Globs match the repo-relative path (`*` also crosses `/`). With no `page_files` the hook counts its default page kinds (`.html`, `.css`, `.j2`, `.tsx`, `.vue` and the like, outside test and build folders); `.js`, `.ts`, `.md` and `.py` page sources need a map.
- The hook also reads `viewports` (a PNG counts for the widest declared viewport no wider than it; a desktop-only repo declares only desktop; a labelled page counts only pictures named `<label>-<viewport>.png`, the names `shoot.py` writes, so a page pictured another way is saved under that name) and `base_url` + `pages` (its printed command). It finds `shoot.py` at `SST3_PAGE_REVIEW_SHOOT_PY`, else this skill's installed copy, else the sst3-skills plugin cache.

## The Per-Page 3x Iterate Loop

Work ONE page at a time. Each iteration runs this concrete dual-URL recipe:

1. **Shoot both sides at both viewports.** Shoot the LOCAL build (`shoot.py` with `base_url` = the local server) for the target page path at desktop (1440) + mobile (390), and shoot/cache the LIVE reference (`shoot.py` with `base_url` = the live base) for the same path at the same viewports. Capture local and live at identical viewport widths so the drift number is not inflated by stretch.
2. **Measure the gap.** Run `compare_computed_style.py --local-url <local> --live-url <live> --selector <target>` on the selector(s) you are matching (exact spacing / colour / font deltas per viewport), AND run `pixel-drift.sh <local.png> <live.png>` on the PNG pair (a measurable AE + closeness% + a diff-highlight image).
3. **Tweak and re-shoot.** Apply the smallest CSS change the deltas point to, rebuild the local site, then re-shoot and re-measure.

Repeat at most 3 times per page, without pausing to ask. Watch the drift number trend DOWN and the computed-CSS deltas shrink toward zero. Then move to the next page.

## Sub-Commands

- **`/design-fidelity shoot`** — capture only (`shoot.py`); works STANDALONE with no live reference. Check its exit code and stderr telemetry (which wait strategy fired, normalisation WxH; AP #16), then Read every PNG and look for cut, overlapping or badly wrapped text, alignment, wrong sums, missing details and anything hard to use. Fix what you find and shoot again.
- **`/design-fidelity compare`** — run the full per-page loop above against a live reference: `shoot.py` (local + live) → `compare_computed_style.py` → `pixel-drift.sh` (check each exit code and the `compare` rc). Fires ONLY when a live reference URL is supplied.
- **`/design-fidelity diff`** — re-run `pixel-drift.sh` on an existing local/live PNG pair to re-measure drift after a tweak.

Tests: `tests/run_unit_tests.sh` (helper contracts, no browser); a real `shoot` against a reachable `base_url` (Workflow); shoot + compare + drift on one live page (E2E sample).

## Security: chrome-devtools browser state

When you drive a LIVE site via the chrome-devtools MCP (the alternative to the headless playwright route), the MCP runs with full browser access — it can read open-tab cookies, auth tokens in request/response headers, pasted secrets in form fields, and cached credentials surfaced by the page (live browser state). Disable chrome-devtools via `/plugin` BEFORE pasting any secret. The DEFAULT route in this skill is headless playwright, which carries no live browser state, so prefer it. Full detail: `references/chrome-devtools-mcp.md` "Security note".

## Anti-Overfit Constraint

The pixel-drift number is a TREND diagnostic — the operator watches it decrease across iterations; it is NEVER a hard pass-gate. The target is a STRUCTURAL match, not pixel-perfection (anti-aliasing, font-hinting, and dynamic content make pixel-perfect impossible and pointless). The page→path map, `base_url`, and viewport list are PER-REPO config — the proto values are an example, NOT a default.

## Skill Surface Contract

- Inputs: a `base_url` (local build or live), a page→path map, viewports, and optional selectors. Via `.design-fidelity.json` and/or CLI overrides.
- Outputs: full-page PNGs + diff-highlight PNGs under `~/DevProjects/screenshots/<repo>/`; computed-CSS deltas + drift numbers on stdout; decision-branch telemetry on stderr.
- Never writes into the consumer repo tree; never deploys; never edits the live site.
- Exit codes are load-bearing (AP #16): the helpers fail loud on a missing dependency, a blocked PNG coder, or a missing selector rather than producing a silent empty result.
- **The `.design-fidelity.json` config is treated as UNTRUSTED** (it is repo-local, so a cloned repo could ship a hostile one). `shoot.py`: the opt-in `hugo.cmd` launcher spawns NOTHING unless the operator passes the explicit `--allow-hugo-launcher` CLI flag (config alone can never start a process); when enabled it allowlists the executable to STATIC dev-servers only (hugo/jekyll/vite/serve/http-server — bare PATH names, no `./hugo` path component — and no interpreters or `npm run`-style wrappers) and rejects inline-code/eval flags; `base_url` is http(s)-only (no `file://`); page labels + viewport names must be `[A-Za-z0-9_-]+`; viewport width/height must be ints in `1..8192`; `scroll.step` must be a positive int (settle clamped); `out_dir` must resolve strictly UNDER `$HOME` or the system temp dir. Each violation is a loud exit 2.
- **Residual trust the threat model deliberately does NOT remove — only pass `--allow-hugo-launcher` on a repo you TRUST**: (1) `vite` and `jekyll` execute the repo's OWN build config (`vite.config.{js,ts}`, Jekyll `_config.yml`/`_plugins`) by design when they start, so launching them runs that repo's build code; `hugo`/`serve`/`http-server` do not. (2) `base_url`/page paths are scheme-restricted to http(s) but NOT host-filtered (the tool MUST reach `http://127.0.0.1:<port>` for local builds), so a hostile config can point captures at internal/loopback/cloud-metadata HTTP endpoints (e.g. `169.254.169.254`) — do not run an untrusted repo's config on a host with sensitive internal HTTP reachability.
