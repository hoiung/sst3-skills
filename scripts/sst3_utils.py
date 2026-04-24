"""Minimal SST3 utilities stub for vendored voice-tells / secret-detection scripts.

This repo vendors a couple of scripts from the dotfiles canonical. Those scripts
import `sst3_utils` for a Windows console fix. In this public repo we only need
the single symbol, so ship a stub rather than the full 400-line canonical.
"""
from __future__ import annotations

import io
import sys


def fix_windows_console() -> None:
    """Force UTF-8 on Windows consoles so unicode banned-word output renders.

    No-op on Linux / macOS. Idempotent.
    """
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
