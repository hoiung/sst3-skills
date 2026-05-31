#!/usr/bin/env python3
"""shoot.py — config-driven full-page screenshot capture for the design-fidelity skill.

Generalised from the id8u throwaway protos (~/DevProjects/screenshots/id8u-compare/
_shoot_*.py) into a repo-generic, config-file-driven capture tool. Captures
full-page screenshots of any site (local build OR live reference) at one or more
viewports, with the WSL lazy-load / networkidle-hang gotcha handled by default.

Capture mode is full_page ONLY by design — the visual-design-fidelity loop never
needs region or element shots, so the protos' clip/element modes are deliberately
NOT carried (YAGNI). There is exactly ONE navigation path (the _goto helper) so a
bare networkidle goto cannot exist anywhere else.

Config FILE (default <consumer-repo>/.design-fidelity.json), schema (every key is read
by code — Config Traceability):
    {
      "base_url":  "http://127.0.0.1:1313",        # str (required unless --base-url)
      "pages":     {"home": "/", "about": "/about"},# label -> path
      "viewports": [{"name":"desktop","width":1440,"height":900},
                    {"name":"mobile","width":390,"height":844}],
      "out_dir":   "~/DevProjects/screenshots/myrepo/local",  # optional; default is
                                                              # outside any git repo
      "scroll":    {"enabled": true, "step": 600, "settle_ms": 250},  # or a bare bool
      "hugo":      {"cmd": "hugo server -p 1313", "ready_wait_sec": 3} # OPT-IN, requires --allow-hugo-launcher
    }

CLI overrides may replace any of base_url / pages / viewports / out_dir / scroll
without touching the config file. Output (the screenshot paths) is printed to
stdout; all decision-branch telemetry (key=value) goes to stderr (AP #12).

Mechanics reference (do not duplicate here): docs/guides/playwright-fallback.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

# --- Fail Fast import guard (AC 1.8) -------------------------------------------
# Playwright lives in a per-repo .venv in some consumers and in the global
# interpreter in others; either way, a missing import must surface a clear
# remediation, never a bare traceback.
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.stderr.write(
        "shoot.py: playwright is not importable in this interpreter.\n"
        "  Remediation (per docs/guides/playwright-fallback.md):\n"
        "    .venv/bin/python -m playwright install chromium\n"
        "  (install the lib first if needed: uv pip install playwright)\n"
    )
    sys.exit(3)


DEFAULT_VIEWPORTS = [
    {"name": "desktop", "width": 1440, "height": 900},
    {"name": "mobile", "width": 390, "height": 844},
]
MAX_VIEWPORT_DIM = 8192  # ceiling on a config-supplied viewport dim (guards a billions-px OOM)
DEFAULT_SCROLL = {"enabled": True, "step": 600, "settle_ms": 250}
NETWORKIDLE_TIMEOUT_MS = 45000
FALLBACK_SETTLE_MS = 2500
TOP_SETTLE_MS = 400  # final settle after scrolling back to the top (was a bare literal)
MAX_SETTLE_MS = 60000  # ceiling on any per-step settle so an untrusted config cannot hang the run
MAX_SCROLL_ITERS = 10000  # hard cap so a hostile page that grows scrollHeight forever cannot loop infinitely

# --- Untrusted-config hardening --------------------------------------------------
# The config file (default <consumer-repo>/.design-fidelity.json) is REPO-LOCAL and
# therefore UNTRUSTED: a cloned/hostile repo must not be able to (a) run an
# arbitrary executable via the opt-in hugo launcher, (b) capture a local file via a
# file:// base_url, or (c) write a PNG to an arbitrary path via out_dir / label.
# The opt-in hugo launcher is restricted to known dev-server binaries (basename of
# the first token, which must also be a bare PATH-resolved name — no `./hugo` /
# `/repo/hugo` path component, so a repo-shipped binary cannot masquerade as an
# allowlisted name), base_url is restricted to http(s), screenshot filenames are
# built only from a [A-Za-z0-9_-] charset, and out_dir must resolve strictly UNDER
# $HOME or the system temp dir. CLI overrides are validated the same way (defence
# in depth).
# Static dev-server binaries ONLY — every one of these starts a server from its
# argv and does NOT accept an inline-code/eval/run flag in argv[1] (unlike
# python -c / node -e / ruby -e / php -r / npm run / npx / bundle exec, which an
# untrusted config could coerce into arbitrary code execution). Interpreters and
# package-manager run-wrappers are deliberately EXCLUDED.
#
# RESIDUAL TRUST (not a defect — the threat model's deliberate boundary):
#  - `vite` and `jekyll` execute the repo's OWN build config (vite.config.{js,ts},
#    Jekyll _config.yml / _plugins/*.rb) BY DESIGN when they start. The
#    --allow-hugo-launcher opt-in therefore means "I trust THIS repo's build to run
#    its own build code" — only pass it on a repo you trust. `hugo`/`serve`/
#    `http-server` do not execute repo code; vite/jekyll do.
#  - base_url/pages are scheme-restricted to http(s) but NOT host-filtered (the tool
#    MUST reach http://127.0.0.1:<port> for local builds), so a hostile config can
#    point captures at internal/loopback/cloud-metadata http endpoints (e.g.
#    169.254.169.254). Do not run an untrusted repo's config on a host with
#    sensitive internal HTTP reachability. (See SKILL.md "Security".)
HUGO_CMD_ALLOWLIST = {"hugo", "jekyll", "vite", "serve", "http-server"}
# Belt-and-braces: reject any inline-code/eval flag anywhere in argv even for an
# allowlisted binary (defence in depth against a future allowlist addition).
DANGEROUS_HUGO_FLAGS = {"-c", "-e", "-r", "-E", "--eval", "--exec", "--"}
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
ALLOWED_URL_SCHEMES = {"http", "https"}
SAFE_OUT_ROOTS = [Path.home().resolve(), Path(tempfile.gettempdir()).resolve()]


def _name_is_safe(name: str) -> bool:
    """Filename-component safety: label / viewport name must be a bare identifier
    (no `/`, `..`, NUL, whitespace) so `out_dir / f"{label}-{name}.png"` cannot escape."""
    return bool(SAFE_NAME_RE.match(name or ""))


def _scheme_is_allowed(url: str) -> bool:
    """Only http(s) — blocks file:// / chrome:// / javascript: local-resource capture.
    Leading/trailing whitespace is stripped first so ` http://x` cannot slip a scheme
    past urlparse and then fail opaquely at page.goto."""
    return urlparse((url or "").strip()).scheme.lower() in ALLOWED_URL_SCHEMES


def _hugo_exe(cmd: str) -> str | None:
    """Basename of the first token of a hugo.cmd string (shlex-aware), or None."""
    argv = shlex.split(cmd or "")
    return os.path.basename(argv[0]) if argv else None


def _hugo_argv_safe(argv: list[str]) -> bool:
    """True iff the launcher argv is allowlisted AND carries no inline-code/eval flag.
    Three conditions must hold: (1) argv[0] is a BARE name (no path separator) so an
    untrusted config cannot point it at a repo-shipped `./hugo` / `/repo/hugo` binary
    whose basename merely matches the allowlist — only a PATH-resolved system binary
    may run; (2) that name is in HUGO_CMD_ALLOWLIST; (3) no argv token is in
    DANGEROUS_HUGO_FLAGS (nor a `--eval=`/`--exec=` form)."""
    if not argv:
        return False
    exe = argv[0]
    if os.path.basename(exe) != exe:  # reject any path component: ./hugo, /repo/hugo, a/b
        return False
    if exe not in HUGO_CMD_ALLOWLIST:
        return False
    for tok in argv[1:]:
        if tok in DANGEROUS_HUGO_FLAGS or tok.startswith("--eval=") or tok.startswith("--exec="):
            return False
    return True


def _out_dir_under_safe_root(out_dir: Path) -> bool:
    """out_dir (already resolved) must be strictly UNDER $HOME or the system temp dir.
    A bare root (out_dir == $HOME) is rejected so a config `out_dir: "~"` cannot dump
    PNGs into the home-directory root — at least one path component below a safe root
    is required."""
    return any(root in out_dir.parents for root in SAFE_OUT_ROOTS)


def _log(**kv: object) -> None:
    """Emit one structured key=value telemetry line to stderr (AP #12).

    Kept DISTINCT from the CLI result (screenshot paths on stdout) so a caller
    can parse stdout for paths without the decision-branch noise.
    """
    sys.stderr.write("shoot " + " ".join(f"{k}={v}" for k, v in kv.items()) + "\n")


def _goto(page, url: str, settle_ms: int = FALLBACK_SETTLE_MS) -> str:
    """The ONE navigation path. Try networkidle; on timeout fall back to
    domcontentloaded + a fixed settle. Returns the strategy that fired so the
    caller (and the telemetry) knows which path was taken. No other goto exists
    in this file, so a bare-networkidle navigation cannot leak in elsewhere.
    """
    try:
        page.goto(url, wait_until="networkidle", timeout=NETWORKIDLE_TIMEOUT_MS)
        _log(event="goto", url=url, wait_strategy="networkidle")
        return "networkidle"
    except Exception as exc:  # noqa: BLE001 — any nav failure → documented fallback
        page.goto(url, wait_until="domcontentloaded", timeout=NETWORKIDLE_TIMEOUT_MS)
        page.wait_for_timeout(settle_ms)
        _log(event="goto", url=url, wait_strategy="domcontentloaded-fallback",
             reason=str(exc).splitlines()[0][:80], settle_ms=settle_ms)
        return "domcontentloaded-fallback"


def scroll_through(page, step: int = 600, settle_ms: int = 250) -> None:
    """Lazy-load settle generalised from the protos: re-read scrollHeight every
    iteration (the page grows as images lazy-load), step down `step` px, then
    return to the top and settle so the full_page shot captures a fully-loaded
    document. Parametrised step / settle; gated by the `scroll` flag at the call
    site (AC 1.3).
    """
    height = page.evaluate("document.body.scrollHeight")
    y = 0
    iters = 0
    # step is guaranteed >= 1 by _normalise_scroll, so y always advances; the iter
    # cap is a second backstop against a hostile served page that grows scrollHeight
    # every pass (which could otherwise outrun the cursor indefinitely).
    while y < height and iters < MAX_SCROLL_ITERS:
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(settle_ms)
        y += step
        height = page.evaluate("document.body.scrollHeight")
        iters += 1
    if iters >= MAX_SCROLL_ITERS:
        _log(event="scroll_through", warning="hit MAX_SCROLL_ITERS — page scrollHeight may be growing unbounded")
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(TOP_SETTLE_MS)
    _log(event="scroll_through", final_scrollHeight=height, step=step, settle_ms=settle_ms, iters=iters)


def _default_out_dir() -> str:
    """Default output dir OUTSIDE any git repo (AC 4.6): never writes screenshots
    into the working repository tree. `<repo>` is the basename of the CWD.
    """
    repo = Path.cwd().name or "repo"
    return str(Path.home() / "DevProjects" / "screenshots" / repo)


def _scroll_int(raw: dict, key: str) -> int:
    """Coerce an untrusted-config scroll int with the file's named Fail-Fast contract
    (exit 2, name the offender) instead of a bare ValueError traceback."""
    try:
        return int(raw.get(key, DEFAULT_SCROLL[key]))
    except (ValueError, TypeError):
        sys.stderr.write(f"shoot.py: scroll.{key} must be an integer (got {raw.get(key)!r})\n")
        sys.exit(2)


def _normalise_scroll(raw: object) -> dict:
    """Accept either a bare bool or the {enabled,step,settle_ms} object form.

    `step` and `settle_ms` come from the REPO-LOCAL (untrusted) config: a non-numeric
    value Fail-Fasts (exit 2, named); `step` is forced >= 1 so the scroll loop always
    makes forward progress (step <= 0 would hang forever — a DoS from config); and
    `settle_ms` is clamped to [0, MAX_SETTLE_MS] so a huge value cannot hang each step.
    """
    if isinstance(raw, bool):
        return {"enabled": raw, "step": DEFAULT_SCROLL["step"], "settle_ms": DEFAULT_SCROLL["settle_ms"]}
    if isinstance(raw, dict):
        step = _scroll_int(raw, "step")
        settle_ms = _scroll_int(raw, "settle_ms")
        if step <= 0:
            sys.stderr.write(f"shoot.py: scroll.step must be a positive integer (got {step})\n")
            sys.exit(2)
        if settle_ms < 0:
            sys.stderr.write(f"shoot.py: scroll.settle_ms must be >= 0 (got {settle_ms})\n")
            sys.exit(2)
        return {
            "enabled": bool(raw.get("enabled", True)),
            "step": step,
            "settle_ms": min(settle_ms, MAX_SETTLE_MS),
        }
    return dict(DEFAULT_SCROLL)


def load_config(path: Path | None) -> dict:
    """Read the JSON config file. Returns {} when no path is given / file absent
    so CLI-only invocation works (greenfield, capture-only)."""
    if path is None:
        return {}
    if not path.is_file():
        _log(event="config", status="absent", path=str(path))
        return {}
    with path.open(encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as exc:  # Fail Fast: name the file + the parse error, no bare traceback
            sys.stderr.write(f"shoot.py: {path} is not valid JSON: {exc}\n")
            sys.exit(2)
    if not isinstance(cfg, dict):
        sys.stderr.write(f"shoot.py: {path} must contain a JSON object (got {type(cfg).__name__})\n")
        sys.exit(2)
    _log(event="config", status="loaded", path=str(path), keys=",".join(sorted(cfg)))
    return cfg


def _parse_pages(raw: str) -> dict:
    """Parse a CLI --pages override of the form 'label:/path,label2:/path2'."""
    pages: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:  # Fail Fast: a missing colon would silently shoot base_url
            sys.stderr.write(f"shoot.py: --pages entry '{item}' must be 'label:/path' (missing ':')\n")
            sys.exit(2)
        label, _, path = item.partition(":")
        pages[label.strip()] = path.strip()
    return pages


def _parse_viewports(raw: str) -> list[dict]:
    """Parse a CLI --viewports override of the form 'desktop:1440x900,mobile:390x844'."""
    vps: list[dict] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        name, _, dims = item.partition(":")
        w, _, h = dims.partition("x")
        try:  # Fail Fast: a malformed 'name:WxH' must name the offender, not emit a bare traceback
            vps.append({"name": name.strip(), "width": int(w), "height": int(h)})
        except ValueError:
            sys.stderr.write(f"shoot.py: --viewports entry '{item}' must be 'name:WIDTHxHEIGHT' (e.g. desktop:1440x900)\n")
            sys.exit(2)
    return vps


def _maybe_start_hugo(hugo: dict | None, allow_launcher: bool = False):
    """OPT-IN local dev-server lifecycle (AC 1.4). Returns a Popen handle or None.

    Default path (hugo block absent) spawns NO server — capture runs against the
    operator-managed base_url, keeping the skill repo-generic. When present, the
    server is started via subprocess.Popen and the captured handle is terminated
    in the caller's finally block. The process group is NEVER discovered/killed by
    name (a documented operator self-kill footgun) and server-stop is never chained
    behind an && that an upstream non-zero exit could abort.

    SECURITY — the `cmd` comes from the REPO-LOCAL (untrusted) config, so spawning a
    process is gated by THREE controls: (1) the operator must pass the explicit CLI
    flag `--allow-hugo-launcher` (config-file-only invocation can NEVER spawn — the
    config is untrusted, the CLI is operator-driven); (2) the executable basename must
    be a static dev-server in HUGO_CMD_ALLOWLIST (no interpreters / run-wrappers that
    take inline code); (3) no inline-code/eval flag may appear anywhere in argv.
    """
    if not hugo:
        return None
    cmd = hugo.get("cmd")
    if not cmd:
        return None
    if not allow_launcher:  # config alone must never spawn — require explicit operator opt-in
        _log(event="hugo", action="skip", reason="pass --allow-hugo-launcher to enable the opt-in launcher")
        return None
    # Repo-local config is UNTRUSTED: shlex.split for correct quoting, then require an
    # allowlisted static-server basename AND no inline-code/eval flag (Fail Fast otherwise).
    argv = shlex.split(cmd)
    if not _hugo_argv_safe(argv):
        sys.stderr.write(
            f"shoot.py: hugo.cmd is not an allowed dev-server launch: {cmd!r}. "
            f"Allowed executables {sorted(HUGO_CMD_ALLOWLIST)} (bare PATH names only, no path component); "
            f"inline-code/eval flags {sorted(DANGEROUS_HUGO_FLAGS)} are refused — not running an arbitrary command from config.\n"
        )
        sys.exit(2)
    # Validate ready_wait_sec BEFORE spawning: a non-numeric or negative value raised
    # AFTER Popen would orphan the spawned server (the handle is not yet returned, so
    # the caller's finally cannot terminate it). Fail Fast here, before any process.
    try:
        ready_wait = float(hugo.get("ready_wait_sec", 3))
    except (ValueError, TypeError):
        sys.stderr.write(f"shoot.py: hugo.ready_wait_sec must be a number (got {hugo.get('ready_wait_sec')!r})\n")
        sys.exit(2)
    if ready_wait < 0:
        sys.stderr.write(f"shoot.py: hugo.ready_wait_sec must be >= 0 (got {ready_wait})\n")
        sys.exit(2)
    _log(event="hugo", action="start", exe=os.path.basename(argv[0]))
    # shell=False, allowlisted-basename argv list — no shell metachar interpretation.
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(ready_wait)
    return proc


def capture(cfg: dict, allow_hugo_launcher: bool = False) -> list[str]:
    """Run the capture. Returns the list of written screenshot paths."""
    base_url = cfg.get("base_url")
    if isinstance(base_url, str):
        base_url = base_url.strip()
    if not base_url:
        sys.stderr.write("shoot.py: no base_url (set it in the config file or pass --base-url)\n")
        sys.exit(2)
    if not _scheme_is_allowed(base_url):  # block file:// / chrome:// / javascript: capture
        sys.stderr.write(f"shoot.py: base_url scheme not allowed (use http/https): {base_url}\n")
        sys.exit(2)
    pages = cfg.get("pages") or {"home": "/"}
    viewports = cfg.get("viewports") or DEFAULT_VIEWPORTS
    # Screenshot filenames are built from label + viewport name — restrict both to a
    # safe identifier charset so a repo-local config cannot path-traverse out of out_dir.
    for label in pages:
        if not _name_is_safe(label):
            sys.stderr.write(f"shoot.py: page label '{label}' must match [A-Za-z0-9_-]+ (no path separators)\n")
            sys.exit(2)
    # Config viewports are UNTRUSTED: validate name AND dims (the CLI path already
    # int-coerces dims in _parse_viewports; config must Fail-Fast identically rather
    # than pass a missing/huge/non-int dim straight into new_context — KeyError, bare
    # traceback, or a billions-px OOM otherwise).
    for vp in viewports:
        if not _name_is_safe(str(vp.get("name", ""))):
            sys.stderr.write(f"shoot.py: viewport name '{vp.get('name')}' must match [A-Za-z0-9_-]+\n")
            sys.exit(2)
        for dim in ("width", "height"):
            if dim not in vp:
                sys.stderr.write(f"shoot.py: viewport '{vp.get('name')}' is missing '{dim}'\n")
                sys.exit(2)
            try:
                val = int(vp[dim])
            except (ValueError, TypeError):
                sys.stderr.write(f"shoot.py: viewport '{vp.get('name')}' {dim} must be an integer (got {vp[dim]!r})\n")
                sys.exit(2)
            if not (1 <= val <= MAX_VIEWPORT_DIM):
                sys.stderr.write(f"shoot.py: viewport '{vp.get('name')}' {dim}={val} must be in 1..{MAX_VIEWPORT_DIM}\n")
                sys.exit(2)
            vp[dim] = val
    out_dir = Path(os.path.expanduser(cfg.get("out_dir") or _default_out_dir())).resolve()
    if not _out_dir_under_safe_root(out_dir):  # repo config must not write PNGs to arbitrary system paths
        sys.stderr.write(f"shoot.py: out_dir {out_dir} must be under {[str(r) for r in SAFE_OUT_ROOTS]}\n")
        sys.exit(2)
    out_dir.mkdir(parents=True, exist_ok=True)
    scroll = _normalise_scroll(cfg.get("scroll", True))
    hugo = cfg.get("hugo")

    _log(event="capture-start", base_url=base_url, pages=len(pages),
         viewports=len(viewports), out_dir=str(out_dir), scroll=scroll["enabled"])

    written: list[str] = []
    proc = None
    try:
        proc = _maybe_start_hugo(hugo, allow_hugo_launcher)
        with sync_playwright() as p:
            # Bare bundled-headless launch — relies on the chrome-headless-shell
            # build that `playwright install chromium` ships; WSL works as-is.
            browser = p.chromium.launch()
            try:
                for vp in viewports:
                    ctx = browser.new_context(viewport={"width": vp["width"], "height": vp["height"]})
                    for label, path in pages.items():
                        page = ctx.new_page()
                        _goto(page, base_url.rstrip("/") + path)
                        if scroll["enabled"]:
                            scroll_through(page, step=scroll["step"], settle_ms=scroll["settle_ms"])
                        dest = out_dir / f"{label}-{vp['name']}.png"
                        if dest.resolve().parent != out_dir:  # defence in depth (label/name already sanitised)
                            sys.stderr.write(f"shoot.py: refusing to write outside out_dir: {dest}\n")
                            sys.exit(2)
                        page.screenshot(path=str(dest), full_page=True)
                        written.append(str(dest))
                        _log(event="shot", label=label, viewport=vp["name"], path=str(dest))
                        page.close()
                    ctx.close()
            finally:
                # Close on the exception path too — a mid-loop _goto/scroll failure
                # would otherwise skip browser.close() (sync_playwright().__exit__ still
                # tears down the driver, but close explicitly so the intent is local).
                browser.close()
    finally:
        if proc is not None:
            _log(event="hugo", action="terminate")
            proc.terminate()
            # Reap the child and escalate to SIGKILL if it ignores SIGTERM, so a
            # trap-SIGTERM dev-server cannot linger as a zombie for the parent's life.
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _log(event="hugo", action="kill", reason="did not exit on SIGTERM within 5s")
                proc.kill()
                proc.wait()
    return written


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Config-driven full-page screenshot capture (design-fidelity skill).")
    ap.add_argument("--config", type=Path, default=Path(".design-fidelity.json"),
                    help="Path to the design-fidelity config JSON (default: <cwd>/.design-fidelity.json)")
    ap.add_argument("--base-url", dest="base_url", help="Override config base_url")
    ap.add_argument("--pages", help="Override config pages: 'home:/,about:/about'")
    ap.add_argument("--viewports", help="Override config viewports: 'desktop:1440x900,mobile:390x844'")
    ap.add_argument("--out-dir", dest="out_dir", help="Override config out_dir (default is outside any repo)")
    ap.add_argument("--no-scroll", action="store_true", help="Disable the lazy-load scroll pass")
    ap.add_argument("--allow-hugo-launcher", action="store_true",
                    help="Explicitly permit the opt-in hugo-block dev-server launcher (the config "
                         "is untrusted; without this flag a hugo.cmd is ignored and no process spawns)")
    ap.add_argument("--self-test", action="store_true",
                    help="Validate the script wiring (no browser launch) and exit 0")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.self_test:
        # Exercises config-merge + the parsers without launching a browser, and
        # confirms the import guard already passed (we are past the top-level
        # try/except, so playwright imported cleanly).
        cfg = load_config(args.config if args.config.is_file() else None)
        assert _normalise_scroll(True)["enabled"] is True
        assert _parse_pages("home:/,about:/about") == {"home": "/", "about": "/about"}
        assert _parse_viewports("desktop:1440x900")[0]["width"] == 1440
        # Untrusted-config hardening guards.
        assert _name_is_safe("home-desktop") and not _name_is_safe("../etc") and not _name_is_safe("a/b")
        assert _scheme_is_allowed("http://x") and _scheme_is_allowed("https://x")
        assert not _scheme_is_allowed("file:///etc/passwd") and not _scheme_is_allowed("javascript:1")
        assert _hugo_exe("hugo server -p 1313") == "hugo"
        # Launcher argv safety: allowlisted static server with benign flags is OK;
        # interpreters / run-wrappers / inline-code flags are refused.
        assert _hugo_argv_safe(["hugo", "server", "-p", "1313"])
        assert _hugo_argv_safe(["vite", "dev"])
        assert not _hugo_argv_safe(["python", "-c", "import os"])
        assert not _hugo_argv_safe(["node", "-e", "x"])
        assert not _hugo_argv_safe(["npm", "run", "evil"])
        assert not _hugo_argv_safe(["hugo", "--eval", "x"]) and not _hugo_argv_safe(["hugo", "--exec=rm"])
        # A repo-shipped binary whose basename matches the allowlist must NOT pass —
        # only a bare PATH-resolved name is allowed (no path component).
        assert not _hugo_argv_safe(["./hugo", "server"])
        assert not _hugo_argv_safe(["/repo/.bin/hugo", "server"])
        assert not _hugo_argv_safe(["a/b", "server"])
        assert _out_dir_under_safe_root(Path.home() / "DevProjects" / "screenshots")
        assert not _out_dir_under_safe_root(Path("/etc"))
        # The bare home/temp root is rejected (config out_dir:"~" must not dump into $HOME).
        assert not _out_dir_under_safe_root(Path.home().resolve())
        # Scroll validation: valid passes; step<=0 / settle<0 / non-numeric Fail-Fast (exit 2);
        # a huge settle is clamped to MAX_SETTLE_MS (no silent hang).
        assert _normalise_scroll({"step": 600, "settle_ms": 250})["step"] == 600
        assert _normalise_scroll({"settle_ms": 10 ** 9})["settle_ms"] == MAX_SETTLE_MS
        for _bad in ({"step": 0}, {"step": -5}, {"step": "x"}, {"settle_ms": -1}, {"settle_ms": "y"}):
            try:
                _normalise_scroll(_bad)
                raise AssertionError(f"expected SystemExit for scroll {_bad}")
            except SystemExit as _e:
                assert _e.code == 2, _bad
        _log(event="self-test", status="ok", config_keys=",".join(sorted(cfg)))
        print("shoot.py self-test OK")
        return 0

    cfg = load_config(args.config)
    if args.base_url:
        cfg["base_url"] = args.base_url
    if args.pages:
        cfg["pages"] = _parse_pages(args.pages)
    if args.viewports:
        cfg["viewports"] = _parse_viewports(args.viewports)
    if args.out_dir:
        cfg["out_dir"] = args.out_dir
    if args.no_scroll:
        cfg["scroll"] = False

    paths = capture(cfg, allow_hugo_launcher=args.allow_hugo_launcher)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
