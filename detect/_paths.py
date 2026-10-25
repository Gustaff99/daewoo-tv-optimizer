"""Base directory for bundled data (profiles, adb).

Works both from source (project root) and from a PyInstaller onefile
bundle, where data files are extracted at startup to ``sys._MEIPASS``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: Nombre del log de auditoría (FASE 6: registro completo de operaciones).
LOG_NAME = "daewoo-optimizer-ops.jsonl"


def state_dir() -> Path:
    """Directorio de estado escribible (logs, avisos).

    Siempre en el home del usuario: en ejecutable congelado el CWD no es
    fiable (en Windows al hacer doble clic es C:\\Windows\\System32, no
    escribible). En modo fuente no se usa para nada crítico.
    """
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE") \
        or str(Path.home())
    d = Path(home) / ".daewoo-optimizer"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def default_log_path() -> str:
    """Ruta del log de auditoría.

    - Ejecutable congelado: el CWD no es fiable (en Windows al hacer doble
      clic es System32, no escribible); se usa el home del usuario.
    - Modo fuente: la ruta relativa histórica (junto al directorio de
      trabajo del usuario).
    """
    if getattr(sys, "frozen", False):
        return str(state_dir() / LOG_NAME)
    return LOG_NAME


def base_dir() -> Path:
    """Project root in source mode; the PyInstaller extraction dir when frozen."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return Path(__file__).resolve().parent.parent
