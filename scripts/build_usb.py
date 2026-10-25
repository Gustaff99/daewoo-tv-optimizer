"""Build the USB distribution folder (FASE 8).

Assembles `dist/usb/` with everything a non-technical user needs, plus
a SHA-256 manifest so the user (or a script) can verify integrity.

Safety rules enforced here:
- The USB is NOT firmware update media: the builder refuses to include
  any file that looks like firmware (known extensions) and writes a
  clear disclaimer into LEEME.txt.
- No __pycache__, .pyc, logs, backups or test files are shipped.
- The manifest covers every shipped file; a tampered file breaks it.

Usage:
  python3 scripts/build_usb.py [--out DIR]

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# What the USB ships (relative to the project root).
# vendor/platform-tools/adb: the standalone ADB client so the USB works
# on a PC without adb installed (no system modification needed).
# Only the adb binary ships, not the rest of platform-tools.
SHIPPED_DIRS = ("detect", "engine", "profiles")
SHIPPED_FILES = ("cli.py", "ui.py", "vendor/platform-tools/adb")
# Data files shipped at the USB ROOT (no docs/ tree inside the USB): the
# compatibility matrix lets the user check their exact model and OS.
EXTRA_FILES = {
    "docs/research/compatibility-matrix.json": "compatibility-matrix.json",
}

# Forbidden firmware-like extensions: this USB must never be mistaken
# for (or contain) firmware update media.
FIRMWARE_EXT = {".bin", ".img", ".zip", ".tar", ".gz", ".swu", ".firmware", ".dat"}

# What is never shipped.
FORBIDDEN_PARTS = {"__pycache__", "tests", "docs", "backups", "logs", "restore", "scripts", "dist"}
FORBIDDEN_EXT = {".pyc", ".pyo"}

LEEME = """DAWOO TV OPTIMIZER — LÉEME PRIMERO
====================================

Que es esto
-----------
Una herramienta para identificar tu televisor Daewoo y, SI lo necesitas,
deshabilitar programas que lo ralentizan (bloatware). Todo es reversible
y hay un registro de cada operacion.

El archivo compatibility-matrix.json incluye los 32 modelos Daewoo
comercializados en Europa con su sistema operativo verificado en la tienda
oficial (VIDAA, Android TV, TiVo o no inteligente) y que optimizaciones
aplican a cada uno. Consultalo antes de ejecutar nada.

Que NO es
---------
- NO es una actualizacion de firmware. NO contiene ni imita archivos de
  sistema. No lo conectes como si lo fuera.
- NO modifica el sistema, solo deshabilita programas (pm disable-user),
  y solo si tu modelo esta verificado y tu lo confirmas.
- Si no sabes cual es tu modelo exacto, usa SOLO el comando "identify":
  no modifica nada.

Requisitos
----------
- Un PC con Python 3.10 o superior (gratuito: python.org).
- Para modelos Android TV / Google TV / Android TV AOSP: el televisor en
  modo desarrollador con ADB. El programa "adb" ya viene incluido en esta
  carpeta (vendor/platform-tools/adb), no hay que instalar nada.
  Si tu PC ya tiene adb propio, la herramienta lo detecta en el PATH.
- Para modelos VIDAA / TiVO: solo identificacion (no hay ADB); esta
  herramienta NO modifica esos modelos.

Comando principal (recomendado para la mayoria)
------------------------------------------------
  python3 daewoo-optimizer\\cli.py gui
      -> Menu sencillo en espanol: detectar la tele, optimizar,
         restaurar, ver el registro. No hay que saber nombres de
         paquetes: la herramienta detecta el modelo, el SO y una lista
         conservadora de bloatware por ti, y te muestra el plan ANTES de
         confirmar. Para optimizar o restaurar hay que teclear "SI".

Comandos avanzados (equivalentes al menu, para usuarios tecnicos)
-----------------------------------------------------------------
  python3 daewoo-optimizer\\cli.py identify --model TU_MODELO --os "EL_SO"
      -> Te dice que perfil aplica y si se pueden hacer cambios.

  python3 daewoo-optimizer\\cli.py probe --device IP_DEL_TV:5555
      -> Lee el TV (solo lectura) e identifica SO y modelo con evidencia.

  python3 daewoo-optimizer\\cli.py plan --device IP_DEL_TV:5555
      -> Muestra lo que SE HARIA (dry-run). Sin --candidates la lista se
         detecta sola contra los paquetes reales de tu TV. No toca nada.

  python3 daewoo-optimizer\\cli.py apply --device IP_DEL_TV:5555 --confirm
      -> Ejecuta el plan. SOLO con --confirm y solo si la identificacion
         fue concluyente. --candidates es opcional (deteccion automatica).

  python3 daewoo-optimizer\\cli.py restore --device IP_DEL_TV:5555
      -> Devuelve todo a como estaba.

  python3 daewoo-optimizer\\cli.py report
      -> Muestra el registro de operaciones.

Modelos nuevos (no incluidos en la matriz de 32 modelos)
---------------------------------------------------------
La herramienta los admite: usa el perfil generico de la familia de su
sistema operativo y propone una lista conservadora de bloatware filtrada
contra los paquetes REALES de tu TV, con una red de seguridad en el
codigo que protege los componentes esenciales (launcher, ajustes, red,
plataforma). El plan siempre se muestra antes de confirmar y todo es
reversible con "restaurar".

Ante cualquier duda: NO ejecutes "apply". La herramienta esta disenada
para no hacer nada si algo no esta verificado.
"""

SEGURIDAD = """SEGURIDAD — modelo de la herramienta
====================================

1. Fail-safe: ante incertidumbre no se modifica nada.
   - Identidad no concluyente (sin ADB ni ficha oficial) -> 0 acciones.
   - Perfil sin acciones permitidas -> 0 acciones.
   - Inventario de paquetes vacio -> 0 acciones.
2. Dry-run por defecto: "plan" solo muestra; "apply" existe y es el unico
   path de modificacion, y exige --confirm explicito.
3. Reversible: solo se deshabilitan paquetes (pm disable-user --user 0),
   nunca se eliminan. "restore" re-habilita todo.
4. Sin root, sin exploits, sin flash de firmware, sin bypass de bootlock.
5. Whitelist de escritura: la unica capa que escribe solo entiende
   "pm disable-user --user 0 <paquete>" y "pm enable --user 0 <paquete>".
   Cualquier otro comando (uninstall, su, shell, otros usuarios) es
   rechazado por el codigo.
6. Sin shell: los comandos se ejecutan con argv fijo; no hay interpolacion
   de cadenas del usuario en shell.
7. Registro: cada operacion (plan, accion, restauracion, error) queda en
   un log JSON append-only ("report" lo muestra).
8. ADB solo lectura en deteccion: getprop de 8 propiedades fijas y
   "pm list packages". Nada mas.
9. El USB no es medio de firmware: el constructor de la USB rechaza
   archivos con extensiones de firmware y este carpeta no contiene
   ningun binario de sistema.
"""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_sources() -> list[Path]:
    """Return the project files that will ship, in deterministic order.

    Raises ValueError if a forbidden file would be included.
    """
    out: list[Path] = []
    for name in SHIPPED_FILES:
        out.append(ROOT / name)
    for d in SHIPPED_DIRS:
        base = ROOT / d
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT).as_posix()
            parts = rel.split("/")
            # Excluir (no saltar) contenido prohibido: pycache, compilados...
            if any(part in FORBIDDEN_PARTS for part in parts):
                continue
            if p.suffix.lower() in FORBIDDEN_EXT:
                continue
            # Un firmware SI salta: la USB nunca puede contenerlo.
            if p.suffix.lower() in FIRMWARE_EXT:
                raise ValueError(f"archivo de firmware prohibido en la USB: {rel}")
            out.append(p)
    return out


def build_usb(out_dir: Path | None = None) -> Path:
    """Assemble the USB folder and write the manifest. Returns the USB dir."""
    usb = (out_dir or ROOT / "dist" / "usb") / "daewoo-tv-optimizer"
    if usb.exists():
        import shutil

        shutil.rmtree(usb)
    usb.mkdir(parents=True)

    sources = collect_sources()
    for src in sources:
        dest = usb / src.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())

    for src_rel, dest_name in EXTRA_FILES.items():
        src = ROOT / src_rel
        if not src.is_file():
            raise ValueError(f"falta el archivo de datos: {src_rel}")
        if src.suffix.lower() in FIRMWARE_EXT:
            raise ValueError(f"archivo de firmware prohibido en la USB: {src_rel}")
        (usb / dest_name).write_bytes(src.read_bytes())

    (usb / "LEEME.txt").write_text(LEEME, encoding="utf-8")
    (usb / "SEGURIDAD.txt").write_text(SEGURIDAD, encoding="utf-8")

    # Manifest: every shipped file, relative path + sha256.
    lines = []
    for p in sorted(usb.rglob("*")):
        if p.is_file():
            rel = p.relative_to(usb).as_posix()
            lines.append(f"{_sha256(p)}  {rel}")
    (usb / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return usb


def verify_manifest(usb_dir: Path) -> bool:
    """Check every file listed in MANIFEST.sha256 matches its hash."""
    manifest = usb_dir / "MANIFEST.sha256"
    if not manifest.is_file():
        return False
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        p = usb_dir / rel
        if not p.is_file():
            return False
        if _sha256(p) != digest.strip():
            return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", help="directorio de salida (default: dist/usb)")
    args = ap.parse_args(argv)
    usb = build_usb(Path(args.out) if args.out else None)
    ok = verify_manifest(usb)
    n = sum(1 for p in usb.rglob("*") if p.is_file())
    print(f"USB construida: {usb} ({n} archivos, manifiesto {'OK' if ok else 'INVÁLIDO'})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
