#!/usr/bin/env bash
# run_unit_tests.sh — Unit Tier (Three-Tier Testing Framework) for the
# design-fidelity skill helpers. Each helper's contract is asserted WITHOUT a browser
# launch or a live site, so this runs anywhere ImageMagick + playwright-lib are
# importable. The browser-driven E2E Tier is the Phase-5 dogfood (a real shoot +
# compare + drift on a live page), not this file.
#
# Reuses the helpers' own contracts (shoot.py / compare_computed_style.py expose
# --self-test; pixel-drift.sh is exercised against its documented output binary)
# rather than re-implementing parallel test logic.
#
# Exit 0 = all unit checks pass; non-zero = a contract regressed.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/scripts"
fail=0

run() {
    local name="$1"; shift
    local out rc
    # Capture combined output so a FAIL names WHICH assert regressed (AP #12) — the
    # old `>/dev/null 2>&1` swallowed the AssertionError, leaving only "(exit N)".
    out="$("$@" 2>&1)"; rc=$?
    if [[ "$rc" -eq 0 ]]; then
        echo "  [PASS] $name"
    else
        echo "  [FAIL] $name (exit $rc)"
        printf '%s\n' "$out" | sed 's/^/        /'
        fail=1
    fi
}

echo "design-fidelity unit tests:"

# 1. shoot.py contract (config-merge + parsers, no browser).
run "shoot.py --self-test" python3 "$SCRIPT_DIR/shoot.py" --self-test

# 2. compare_computed_style.py contract (diff + null-selector _error path).
run "compare_computed_style.py --self-test" python3 "$SCRIPT_DIR/compare_computed_style.py" --self-test

# 3. pixel-drift.sh output-binary contract: AE + closeness tokens, a *diff*.png
#    artefact, and a non-2 exit on a real (non-identical) PNG pair.
td="$(mktemp -d)"
convert -size 120x120 xc:white "$td/a.png" 2>/dev/null
convert -size 120x120 xc:'#fdfdfd' "$td/b.png" 2>/dev/null
out="$(bash "$SCRIPT_DIR/pixel-drift.sh" "$td/a.png" "$td/b.png" "$td/d" 2>/dev/null)"
rc=$?
if echo "$out" | grep -qE 'AE=[0-9]+' \
   && echo "$out" | grep -qE 'closeness=[0-9.]+%' \
   && ls "$td"/d/*diff*.png >/dev/null 2>&1 \
   && [[ "$rc" -ne 2 ]]; then
    echo "  [PASS] pixel-drift.sh output-binary contract"
else
    echo "  [FAIL] pixel-drift.sh output-binary contract (rc=$rc out='$out')"
    fail=1
fi

# 4. pixel-drift.sh scientific-notation RMSE regression (Stage-5 #9 fix). A single
#    18-level pixel on a 1000x1000 image makes IM emit a normalised RMSE in
#    scientific notation, e.g. "4.626 (7.05882e-05)". The pre-fix parser's [0-9.]
#    class dropped the exponent, fell back to 0, and reported closeness=100.00% — a
#    fabricated perfect match for an image that DOES differ (the small-drift regime
#    this trend diagnostic exists to track). Assert the parsed closeness is NOT
#    100.00% and the run did not error, so the parser can never regress to the
#    silent-100% behaviour (a happy-path-only test is what let the bug ship).
td2="$(mktemp -d)"
convert -size 1000x1000 xc:white "$td2/a.png" 2>/dev/null
convert "$td2/a.png" -fill '#ededed' -draw 'point 0,0' "$td2/b.png" 2>/dev/null
out2="$(bash "$SCRIPT_DIR/pixel-drift.sh" "$td2/a.png" "$td2/b.png" "$td2/d" 2>/dev/null)"
rc2=$?
close2="$(printf '%s' "$out2" | grep -oE 'closeness=[0-9.]+%' | grep -oE '[0-9.]+')"
if [[ "$rc2" -ne 2 ]] && [[ -n "$close2" ]] && [[ "$close2" != "100.00" ]]; then
    echo "  [PASS] pixel-drift.sh scientific-notation RMSE (closeness=${close2}%, not silent 100.00%)"
else
    echo "  [FAIL] pixel-drift.sh scientific-notation RMSE (rc=$rc2 closeness='$close2' out='$out2')"
    fail=1
fi

if [[ "$fail" -eq 0 ]]; then
    echo "design-fidelity unit tests: ALL PASS"
else
    echo "design-fidelity unit tests: FAILURES"
fi
exit "$fail"
