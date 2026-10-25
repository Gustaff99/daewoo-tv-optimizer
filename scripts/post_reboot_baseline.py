"""Baseline post-reinicio: captura las metricas 'before' validas.

FASE 7: las metricas previas (docs/validation/FASE7-before-2026-10-25.txt)
se tomaron con el TV degradado (load 72, /data al 99 %, 'hung system
process') y NO sirven de baseline. Tras el reinicio del TV por el
operador, este script captura un baseline nuevo comparable con las mismas
metricas que la captura original.

Seguridad: solo se ejecuta una lista FIJA de comandos adb shell de solo
lectura. Ninguna entrada del usuario entra en la linea de comandos.

Uso:
    python3 scripts/post_reboot_baseline.py --device 192.168.1.130:5555
"""
from __future__ import annotations

import argparse
import datetime as _dt
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detect.adb_probe import resolve_adb_bin  # noqa: E402

# Lista fija de comandos de solo lectura (misma forma que la captura
# original de FASE 7). No admite comandos arbitrarios.
METRIC_COMMANDS: List[str] = [
    "getprop ro.build.fingerprint",
    "getprop ro.build.display.id",
    "uptime",
    "cat /proc/loadavg",
    "top -n 1 -b",
    "df -h",
    "dumpsys meminfo",
]

Runner = Callable[[str, str, str], str]


def default_runner(adb_bin: str, device: str, cmd: str, timeout: int = 30) -> str:
    """Ejecuta `adb -s <device> shell <cmd>` y devuelve la salida.

    Un fallo individual (p. ej. 'dumpsys meminfo' degradado) no rompe la
    captura: devuelve un marcador de error en su seccion.
    """
    try:
        r = subprocess.run(
            [adb_bin, "-s", device, "shell", cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = r.stdout or ""
        if r.stderr:
            out += "\n[stderr] " + r.stderr.strip()
        if r.returncode != 0:
            out += f"\n[exit={r.returncode}]"
        return out.strip() or "(sin salida)"
    except (subprocess.SubprocessError, OSError) as exc:
        return f"(error: {exc})"


def capture_baseline(
    adb_bin: str, device: str, runner: Optional[Runner] = None
) -> str:
    """Ejecuta todas las metricas y devuelve el texto del baseline."""
    run: Runner = runner or (lambda adb, dev, cmd: default_runner(adb, dev, cmd))
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=== FASE 7 — METRICAS ANTES POST-REINICIO (baseline valido) ===",
        f"capturado: {now}",
        f"dispositivo: {device}",
        "",
    ]
    for cmd in METRIC_COMMANDS:
        lines.append(f"--- {cmd} ---")
        lines.append(run(adb_bin, device, cmd).strip())
        lines.append("")
    return "\n".join(lines)


def write_baseline(text: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def default_out_path() -> Path:
    today = _dt.date.today().isoformat()
    return (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "validation"
        / f"FASE7-before-postreboot-{today}.txt"
    )


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Captura el baseline 'before' valido tras el reinicio del TV."
    )
    ap.add_argument(
        "--device", required=True, help="ip:puerto ADB (ej. 192.168.1.130:5555)"
    )
    ap.add_argument("--out", type=Path, default=None, help="ruta de salida")
    args = ap.parse_args(argv)

    adb_bin = resolve_adb_bin()
    text = capture_baseline(adb_bin, args.device)
    out = args.out or default_out_path()
    write_baseline(text, out)
    print(f"baseline escrito en: {out}")
    print(text)
    print("Siguiente paso: python3 cli.py plan --device " + args.device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
