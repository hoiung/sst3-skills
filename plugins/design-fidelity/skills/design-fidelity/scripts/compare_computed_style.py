#!/usr/bin/env python3
"""compare_computed_style.py — live vs local computed-CSS delta reporter.

Reads the EXACT rendered CSS (getComputedStyle via page.evaluate) for one or more
selectors on a local build and the live reference, at both the desktop (1440) and
mobile (390) viewports, and reports the per-property deltas. This is the precision
half of the visual-design-fidelity loop: pixel-drift.sh tells you THAT something
differs, this tells you exactly WHICH spacing / colour / font property and by how
much.

exit 0  = every selected property is within tolerance on every viewport
exit 1  = drift found (a property differs) OR a selector is missing on a side
exit 2  = usage error (no selectors / no URLs)
exit 3  = playwright not importable (remediation printed)

The numeric report goes to stdout; decision-branch telemetry (key=value) to
stderr (AP #12). Mechanics reference: references/playwright-fallback.md
("Live computed-CSS reads" section).
"""
from __future__ import annotations

import argparse
import json
import sys

# --- Fail Fast import guard (AC 1.8) -----------------------------------------
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.stderr.write(
        "compare_computed_style.py: playwright is not importable in this interpreter.\n"
        "  Remediation (per references/playwright-fallback.md):\n"
        "    .venv/bin/python -m playwright install chromium\n"
        "  (install the lib first if needed: uv pip install playwright)\n"
    )
    sys.exit(3)


DEFAULT_PROPS: list[str] = [
    "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "color", "background-color",
    "font-family", "font-size", "font-weight", "line-height",
]
VIEWPORTS: list[dict] = [
    {"name": "desktop", "width": 1440, "height": 900},
    {"name": "mobile", "width": 390, "height": 844},
]
PX_TOLERANCE = 1.0  # px properties within this delta are treated as a match
NETWORKIDLE_TIMEOUT_MS = 45000
FALLBACK_SETTLE_MS = 2000

# JS read run in page context: returns {selector: {prop: value} | null}. A null
# value (querySelector miss) is handled on the Python side as a structured
# _error — there is no KeyError path because the JS returns null, not throws.
_READ_JS = """
(args) => {
  const out = {};
  for (const sel of args.selectors) {
    const el = document.querySelector(sel);
    if (!el) { out[sel] = null; continue; }
    const cs = getComputedStyle(el);
    const d = {};
    for (const p of args.props) { d[p] = cs.getPropertyValue(p); }
    out[sel] = d;
  }
  return out;
}
"""


def _log(**kv: object) -> None:
    sys.stderr.write("ccs " + " ".join(f"{k}={v}" for k, v in kv.items()) + "\n")


def _px(value: str) -> float | None:
    """Parse a 'NNpx' value to float, else None (non-px property)."""
    v = value.strip()
    if v.endswith("px"):
        try:
            return float(v[:-2])
        except ValueError:
            return None
    return None


def diff_props(
    live: dict | None,
    local: dict | None,
    props: list[str],
    tol_px: float = PX_TOLERANCE,
) -> dict:
    """Compare two computed-style dicts. Returns a structured result:

    - {"_error": ..., "missing_on": [...]} when EITHER side is None (selector
      not found on that side) — explicit, never a KeyError.
    - {} when every property is within tolerance (no drift).
    - {prop: {"live": ..., "local": ...}, ...} for each property that differs.
    """
    if live is None or local is None:
        missing: list[str] = []
        if live is None:
            missing.append("live")
        if local is None:
            missing.append("local")
        return {"_error": "selector not found", "missing_on": missing}
    deltas: dict[str, dict[str, str]] = {}
    for p in props:
        lv = live.get(p, "")
        lo = local.get(p, "")
        lv_px, lo_px = _px(lv), _px(lo)
        if lv_px is not None and lo_px is not None:
            if abs(lv_px - lo_px) > tol_px:
                deltas[p] = {"live": lv, "local": lo}
        elif lv != lo:
            deltas[p] = {"live": lv, "local": lo}
    return deltas


def _goto(page, url: str) -> None:
    """networkidle with documented domcontentloaded fallback (lazy-site safe)."""
    try:
        page.goto(url, wait_until="networkidle", timeout=NETWORKIDLE_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        page.goto(url, wait_until="domcontentloaded", timeout=NETWORKIDLE_TIMEOUT_MS)
        page.wait_for_timeout(FALLBACK_SETTLE_MS)


def read_styles(browser, url: str, selectors: list[str], props: list[str], width: int, height: int) -> dict:
    """Return {selector: {prop: value} | None} for a URL at one viewport, reusing the
    caller's already-launched browser (ONE chromium cold-start per run, not one per
    read — run() makes 4 reads). The per-read context is named and closed in a finally
    so a read failure cannot leak it."""
    ctx = browser.new_context(viewport={"width": width, "height": height})
    try:
        page = ctx.new_page()
        _goto(page, url)
        return page.evaluate(_READ_JS, {"selectors": selectors, "props": props})
    finally:
        ctx.close()


def run(live_url: str, local_url: str, selectors: list[str], props: list[str]) -> int:
    drift = False
    report: dict = {}
    # One browser cold-start for the whole run, reused across all 4 reads (2 viewports
    # x live/local) — was 4 separate p.chromium.launch() cold-starts. browser.close()
    # in a finally so it is torn down even if a read raises.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for vp in VIEWPORTS:
                _log(event="read", side="live", viewport=vp["name"], url=live_url)
                live = read_styles(browser, live_url, selectors, props, vp["width"], vp["height"])
                _log(event="read", side="local", viewport=vp["name"], url=local_url)
                local = read_styles(browser, local_url, selectors, props, vp["width"], vp["height"])
                report[vp["name"]] = {}
                for sel in selectors:
                    result = diff_props(live.get(sel), local.get(sel), props)
                    report[vp["name"]][sel] = result
                    if result:  # non-empty = either drift deltas or an _error
                        drift = True
                        _log(event="drift", viewport=vp["name"], selector=sel,
                             kind="missing" if "_error" in result else "delta",
                             fields=",".join(k for k in result if k != "missing_on"))
        finally:
            browser.close()
    print(json.dumps(report, indent=2))
    _log(event="done", drift=drift)
    return 1 if drift else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Live vs local computed-CSS delta reporter (design-fidelity skill).")
    ap.add_argument("--live-url", dest="live_url", help="Live reference URL")
    ap.add_argument("--local-url", dest="local_url", help="Local build URL")
    ap.add_argument("--selector", action="append", default=[], dest="selectors",
                    help="CSS selector to compare (repeatable)")
    ap.add_argument("--props", help="Comma-separated property list (default: spacing+colour+font set)")
    ap.add_argument("--self-test", action="store_true",
                    help="Validate diff/null-selector handling (no browser) and exit 0")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    props = [p.strip() for p in args.props.split(",")] if args.props else DEFAULT_PROPS

    if args.self_test:
        # The null-selector path must return a structured _error, never crash.
        miss_live = diff_props(None, {"color": "rgb(0, 0, 0)"}, ["color"])
        assert miss_live.get("_error") == "selector not found", miss_live
        assert miss_live["missing_on"] == ["live"], miss_live
        miss_local = diff_props({"color": "rgb(0, 0, 0)"}, None, ["color"])
        assert miss_local["missing_on"] == ["local"], miss_local
        miss_both = diff_props(None, None, [])
        assert miss_both["missing_on"] == ["live", "local"], miss_both
        # px-tolerance + exact-match behaviour.
        assert diff_props({"font-size": "16px"}, {"font-size": "16.5px"}, ["font-size"]) == {}
        assert "margin-top" in diff_props({"margin-top": "48px"}, {"margin-top": "32px"}, ["margin-top"])
        assert "color" in diff_props({"color": "red"}, {"color": "blue"}, ["color"])
        _log(event="self-test", status="ok")
        print("compare_computed_style.py self-test OK")
        return 0

    if not args.selectors:
        sys.stderr.write("compare_computed_style.py: at least one --selector is required\n")
        return 2
    if not args.live_url or not args.local_url:
        sys.stderr.write("compare_computed_style.py: both --live-url and --local-url are required\n")
        return 2

    return run(args.live_url, args.local_url, args.selectors, props)


if __name__ == "__main__":
    sys.exit(main())
