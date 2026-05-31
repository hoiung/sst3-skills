#!/usr/bin/env bash
# pixel-drift.sh — measurable per-page visual drift between a local build and the
# live reference, using ImageMagick `compare` (IM 6.9.12; pixelmatch is NOT
# installed — ImageMagick is the engine).
#
# Usage: pixel-drift.sh <local.png> <live.png> [out_dir] [fuzz%]
#   <local.png>  the build under test (defines the canonical WxH)
#   <live.png>   the reference; normalised to <local.png>'s exact WxH before diff
#   [out_dir]    where the diff-highlight PNG is written
#                (default: OUTSIDE any git repo — ~/DevProjects/screenshots/<repo>/diffs)
#   [fuzz%]      per-pixel colour tolerance passed to `compare -fuzz` (default 0%)
#
# Prints (stdout):  AE=<raw pixel delta>   closeness=<RMSE-derived %>   diff=<png path>
# Telemetry (stderr, AP #12): normalisation WxH applied, compare return codes.
#
# The pixel-drift number is a TREND diagnostic — the operator watches it DECREASE
# across iterations; it is NEVER a hard pass-gate (the target is a structural
# match, not pixel-perfection). The `-resize WxH!` normalisation is a deliberate
# distort-to-compare choice (the `!` forces exact dimensions, ignoring aspect
# ratio); IM 6.9.12 silently MISCOUNTS AE when the two inputs differ in size, so
# the normalise step is mandatory. Capture local + live at IDENTICAL viewport
# WIDTHS (full_page heights still differ) to minimise stretch — wildly different
# aspect ratios inflate the drift number, which is why it is read as a trend, not
# an absolute.
#
# NOT wrapped in `set -e`: `compare` returns 1 (not 0) for any non-identical
# image pair, which is the NORMAL case here — `set -e` would abort on the first
# real comparison. Return codes are checked explicitly instead (rc==2 = a genuine
# ImageMagick failure → surface stderr + exit 2; rc 0/1 = images identical/differ
# = normal).
#
# Mechanics reference: references/playwright-fallback.md ("Pixel-diff scoring").

local_png="$1"
live_png="$2"
out_dir="${3:-$HOME/DevProjects/screenshots/$(basename "$PWD")/diffs}"
fuzz="${4:-0%}"

log() { echo "pixel-drift $*" >&2; }

if [[ -z "$local_png" || -z "$live_png" ]]; then
    echo "usage: pixel-drift.sh <local.png> <live.png> [out_dir] [fuzz%]" >&2
    exit 64
fi
for f in "$local_png" "$live_png"; do
    if [[ ! -f "$f" ]]; then
        echo "pixel-drift.sh: input not found: $f" >&2
        exit 64
    fi
done

# --- Startup PROBE guard (AC 1.7) --------------------------------------------
# `command -v compare` is not enough: ImageMagick may be installed but its
# policy.xml can deny the PNG coder. On THIS host /etc/ImageMagick-6/policy.xml
# line 78 blanket-denies all coders (pattern="*") and line 79 RE-ALLOWS
# {GIF,JPEG,PNG,WEBP} — so PNG works here. Other hosts may lack the line-79
# re-allow, in which case every PNG read/write below would fail. Probe by
# generating a 1x1 PNG and running a trivial self-compare; fail loud if either
# step is blocked, naming the policy.xml cause.
probe_dir="$(mktemp -d)"
probe_png="$probe_dir/probe.png"
if ! convert -size 1x1 xc:white "$probe_png" 2>/dev/null; then
    echo "pixel-drift.sh: ImageMagick cannot WRITE a PNG — policy.xml likely blocks the PNG coder." >&2
    echo "  Check /etc/ImageMagick-6/policy.xml for a 'coder rights=\"none\" pattern=\"*\"' line" >&2
    echo "  without a following PNG re-allow (read|write {GIF,JPEG,PNG,WEBP})." >&2
    exit 2
fi
compare -metric AE "$probe_png" "$probe_png" null: >/dev/null 2>&1
probe_rc=$?
if [[ "$probe_rc" -ge 2 ]]; then
    echo "pixel-drift.sh: ImageMagick 'compare' cannot READ a PNG (probe rc=$probe_rc) — policy.xml likely blocks the PNG coder." >&2
    exit 2
fi
log event=probe status=ok rc="$probe_rc"

mkdir -p "$out_dir"

# Canonical dimensions come from the LOCAL build under test.
dims="$(identify -format '%wx%h' "$local_png" 2>/dev/null)"
if [[ -z "$dims" ]]; then
    echo "pixel-drift.sh: could not read dimensions of $local_png" >&2
    exit 2
fi

base="$(basename "${local_png%.*}")"
norm_png="$out_dir/${base}-live-normalised.png"
diff_png="$out_dir/${base}-diff.png"

# Mandatory normalisation: force the live reference to the local build's EXACT
# WxH (the trailing `!` distorts; this is intentional — see header).
if ! convert "$live_png" -resize "${dims}!" "$norm_png" 2>/dev/null; then
    echo "pixel-drift.sh: failed to normalise $live_png to ${dims}" >&2
    exit 2
fi
log event=normalise to="$dims" out="$norm_png"

# AE: raw count of differing pixels + the diff-highlight image.
ae="$(compare -metric AE -fuzz "$fuzz" "$local_png" "$norm_png" "$diff_png" 2>&1)"
ae_rc=$?
log event=compare metric=AE rc="$ae_rc"
if [[ "$ae_rc" -ge 2 ]]; then
    echo "pixel-drift.sh: ImageMagick 'compare' failed (AE rc=$ae_rc): $ae" >&2
    exit 2
fi

# RMSE: normalised closeness. Output form: "<abs> (<normalised 0..1>)".
rmse="$(compare -metric RMSE -fuzz "$fuzz" "$local_png" "$norm_png" null: 2>&1)"
rmse_rc=$?
log event=compare metric=RMSE rc="$rmse_rc"
if [[ "$rmse_rc" -ge 2 ]]; then
    echo "pixel-drift.sh: ImageMagick 'compare' failed (RMSE rc=$rmse_rc): $rmse" >&2
    exit 2
fi
# Extract the parenthesised normalised value (0..1). The regex MUST accept
# scientific notation: IM emits e.g. "0.0741895 (1.13206e-06)" for a small-but-real
# drift over a large image, and a `[0-9.]`-only class would miss the exponent,
# leaving norm_val empty -> a silent closeness=100.00% for an image that DOES differ
# (the small-drift regime this trend diagnostic exists to track). If extraction
# still finds nothing, FAIL LOUD (exit 2) rather than substituting 0 — never report
# a fabricated perfect match. awk parses the exponent form natively.
norm_val="$(printf '%s' "$rmse" | grep -oE '\(([0-9.]+([eE][+-]?[0-9]+)?)\)' | tr -d '()' | head -1)"
if [[ -z "$norm_val" ]]; then
    echo "pixel-drift.sh: could not parse normalised RMSE from compare output: $rmse" >&2
    exit 2
fi
closeness="$(awk -v n="$norm_val" 'BEGIN { printf "%.2f", (1 - n) * 100 }')"

# Strip any IM "(normalised)" suffix from AE so the stdout token is a bare int.
ae_int="$(printf '%s' "$ae" | grep -oE '^[0-9]+' | head -1)"
[[ -z "$ae_int" ]] && ae_int=0

echo "AE=${ae_int} closeness=${closeness}% diff=${diff_png}"
exit 0
