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
  python3 scripts/build_exe.py --gui    # build windowed con GUI tkinter
  python3 scripts/build_exe.py --skip-smoke

El build --gui (el que se usa para Windows) no abre consola: el doble
clic muestra la ventana gráfica directamente.

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


def build(adb: Path, gui: bool = False) -> Path:
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
    ]
    if gui:
        # Sin consola: el doble clic abre la ventana tkinter directamente.
        # PyInstaller usa `--hidden-import` (no existe `--hiddenimports`).
        cmd += [
            "--windowed",
            "--hidden-import=tkinter",
            "--hidden-import=tkinter.messagebox",
        ]
    cmd.append(str(ROOT / "cli.py"))
    print("[build_exe] " + " ".join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)
    if not out.is_file():
        raise SystemExit(f"binario no generado: {out}")
    return out


def smoke_test(exe: Path, gui: bool = False) -> None:
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

    # Entrada sin argumentos (doble clic) no debe morir en silencio:
    # - build de consola: menú terminal; con stdin cerrado sale con 0.
    # - build --gui headless: no hay display ni consola; sale con 1 y
    #   escribe el aviso en el log de errores (comportamiento esperado).
    print("[build_exe] smoke test: entrada sin argumentos (doble clic)", file=sys.stderr)
    proc = subprocess.run(
        [str(exe)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180,
    )
    if gui:
        if proc.returncode != 1:
            raise SystemExit(
                f"smoke test: build --gui headless debe salir 1 (sin display), "
                f"salió {proc.returncode}"
            )
    else:
        if proc.returncode != 0:
            raise SystemExit(
                f"smoke test: menú terminal con stdin cerrado debe salir 0, "
                f"salió {proc.returncode}"
            )
        if "DAEWOO TV OPTIMIZER" not in (proc.stdout or "").upper():
            raise SystemExit("smoke test: no se vio el banner del menú")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument(
        "--gui", action="store_true",
        help="build windowed con interfaz gráfica tkinter (para Windows)",
    )
    args = parser.parse_args()
    adb = ensure_adb()
    exe = build(adb, gui=args.gui)
    if not args.skip_smoke:
        smoke_test(exe, gui=args.gui)
    print(f"[build_exe] OK: {exe} ({exe.stat().st_size // 1024} KB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
