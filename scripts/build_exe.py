"""Build a self-contained executable for USB distribution (FASE 5, v2).

Produces `dist/daewoo-tv-optimizer` (Linux) or `dist/daewoo-tv-optimizer.exe`
(Windows): a single file with Python + the tool + the official ADB client
bundled. The end user needs NO Python and NO installation: copy the file to
a USB stick (or run it in place) and double-click.

- ADB is downloaded from Google (platform-tools) at build time if absent in
  `vendor/platform-tools/adb`; third-party binaries are never committed.
- The bundle includes `profiles/` (model matrix data) and the adb binary.
- The built binary is smoke-tested (`identify`) before the script exits.

Usage:
  python3 scripts/build_exe.py          # build + smoke test
  python3 scripts/build_exe.py --skip-smoke

Requires PyInstaller:  pip install pyinstaller
"""
from __future__ import annotations

import argparse
import io
import os
import platform
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PLATFORM_TOOLS = {
    "Linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
    "Windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "Darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
}


def ensure_adb() -> Path:
    """Return the path of a working adb binary, downloading it if needed."""
    adb = ROOT / "vendor" / "platform-tools" / "adb"
    if sys.platform.startswith("win"):
        adb = ROOT / "vendor" / "platform-tools" / "adb.exe"
    if adb.is_file():
        return adb
    url = PLATFORM_TOOLS.get(platform.system())
    if not url:
        raise SystemExit(f"platform-tools no disponible para {platform.system()}")
    print(f"[build_exe] descargando adb oficial: {url}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    adb.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        name = "platform-tools/adb.exe" if sys.platform.startswith("win") else "platform-tools/adb"
        zf.extract(name, ROOT / "vendor")
    if not sys.platform.startswith("win"):
        adb.chmod(0o755)
    if not adb.is_file():
        raise SystemExit("adb no encontrado tras la descarga")
    return adb


def build(adb: Path) -> Path:
    sep = ";" if os.name == "nt" else ":"
    suffix = ".exe" if os.name == "nt" else ""
    out = ROOT / "dist" / f"daewoo-tv-optimizer{suffix}"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconfirm",
        "--clean",
        f"--name=daewoo-tv-optimizer",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build'}",
        f"--specpath={ROOT / 'build'}",
        f"--add-data={str(ROOT / 'profiles')}{sep}.",
        f"--add-data={str(adb.parent)}{sep}vendor/platform-tools",
        "--hidden-import=detect",
        "--hidden-import=engine",
        str(ROOT / "cli.py"),
    ]
    print("[build_exe] " + " ".join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)
    if not out.is_file():
        raise SystemExit(f"binario no generado: {out}")
    return out


def smoke_test(exe: Path) -> None:
    print("[build_exe] smoke test: identify --model 55DM75QV --os VIDAA", file=sys.stderr)
    proc = subprocess.run(
        [str(exe), "identify", "--model", "55DM75QV", "--os", "VIDAA"],
        capture_output=True, text=True, timeout=120,
    )
    print(proc.stdout, file=sys.stderr)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise SystemExit("smoke test fallido")
    # Identidad manual es NUNCA concluyente (fail-safe): el perfil debe
    # caer en el default deny. Si apareciese otro perfil, algo rompió el
    # modelo de seguridad.
    if '"profile": "unsupported/default"' not in proc.stdout:
        raise SystemExit("smoke test: identidad manual no cayó en fail-safe")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args()
    adb = ensure_adb()
    exe = build(adb)
    if not args.skip_smoke:
        smoke_test(exe)
    print(f"[build_exe] OK: {exe} ({exe.stat().st_size // 1024} KB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
