"""Read-only ADB probe builder and parser.

Safety model: every command is checked against a strict whitelist before
it may be executed by the (separate) execution layer. Anything not on the
whitelist raises AdbCommandError. This module never executes commands.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .identity import ANDROID_TV_PACKAGES, GOOGLE_TV_PACKAGES


class AdbCommandError(Exception):
    """Raised when a command is not on the read-only whitelist."""


def resolve_adb_bin() -> str:
    """Resuelve el binario adb a usar:
    1. variable de entorno DAEWOO_ADB (explicita, siempre gana);
    2. vendor/platform-tools/adb junto al proyecto (repo o USB);
    3. "adb" del PATH (fallback).
    """
    env = os.environ.get("DAEWOO_ADB", "").strip()
    if env:
        return env
    vendored = (
        Path(__file__).resolve().parent.parent / "vendor" / "platform-tools" / "adb"
    )
    if vendored.is_file():
        return str(vendored)
    return "adb"


# Whitelist of command prefixes. Order matters: most specific first.
_WHITELIST_PREFIXES: Sequence[str] = (
    "getprop ",
    "pm list packages",
    "dumpsys package ",
    "wm size",
    "wm density",
)

# The only properties we ever read.
ALLOWED_GETPROPS = frozenset(
    {
        "ro.product.model",
        "ro.product.brand",
        "ro.product.device",
        "ro.build.fingerprint",
        "ro.build.version.release",
        "ro.build.version.sdk",
        "ro.build.display.id",
        "ro.product.name",
    }
)


def build_probe_commands() -> List[str]:
    """The complete read-only probe: one command per allowed property,
    plus the package list used for OS resolution."""
    cmds = [f"getprop {p}" for p in sorted(ALLOWED_GETPROPS)]
    cmds.append("pm list packages")
    return cmds


def validate_command(cmd: str) -> None:
    """Raise AdbCommandError unless cmd is on the read-only whitelist."""
    if not isinstance(cmd, str) or not cmd.strip():
        raise AdbCommandError("empty command")
    stripped = cmd.strip()
    for prefix in _WHITELIST_PREFIXES:
        if stripped.startswith(prefix):
            if prefix == "getprop ":
                prop = stripped[len("getprop "):].strip().strip('"')
                if prop not in ALLOWED_GETPROPS:
                    raise AdbCommandError(f"property not allowed: {prop!r}")
            return
    raise AdbCommandError(f"command not on read-only whitelist: {stripped!r}")


def parse_getprop_output(text: str) -> Dict[str, str]:
    """Parse `getprop`-style `[key]: [value]` lines into a dict."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("[") or ": [" not in line:
            continue
        key, _, value = line.partition(": [")
        key = key.strip().strip("[]").strip()
        value = value.rsplit("]", 1)[0]
        if key:
            out[key] = value
    return out


def detect_os_from_packages(packages: Sequence[str]) -> Optional[str]:
    """OS family from an installed package list, or None if no platform
    package is present (Android TV and Google TV both ship one)."""
    pkgs = set(packages)
    if any(p in pkgs for p in ANDROID_TV_PACKAGES):
        return "android-tv"
    if any(p in pkgs for p in GOOGLE_TV_PACKAGES):
        return "google-tv"
    return None


def parse_package_list(text: str) -> List[str]:
    """Parse `pm list packages` output (lines like `package:com.foo`)."""
    out: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            out.append(line[len("package:"):].strip())
    return out


def list_adb_devices(adb_bin: Optional[str] = None) -> List[str]:
    """List ADB devices currently in the 'device' state.

    Runs `adb devices` (read-only, local; never touches the TV beyond the
    standard ADB handshake) and returns the serials (host:port or usb id).
    Devices in 'unauthorized', 'offline' or any other state are excluded:
    the UI must not let the user operate on a device that is not ready.
    Returns [] when adb is missing or fails (the UI shows guidance).
    """
    import subprocess

    bin_ = adb_bin or resolve_adb_bin()
    try:
        proc = subprocess.run(
            [bin_, "devices"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=15.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    out: List[str] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            out.append(parts[0])
    return out
