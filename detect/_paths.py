"""Base directory for bundled data (profiles, adb).

Works both from source (project root) and from a PyInstaller onefile
bundle, where data files are extracted at startup to ``sys._MEIPASS``.
"""
from __future__ import annotations

import sys
from pathlib import Path


def base_dir() -> Path:
    """Project root in source mode; the PyInstaller extraction dir when frozen."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return Path(__file__).resolve().parent.parent
