"""Interfaz de menu (FASE 5.5): la herramienta "sin friccion".

Pensada para el usuario final que conecta el USB a un PC y no quiere
aprender nombres de paquetes ni flags. El flujo completo es:

    python3 cli.py gui

y el menu (en espanol) ofrece:

    [1] Detectar la tele        (solo lectura: que modelo y SO es)
    [2] Optimizar               (deshabilitar bloatware, con confirmacion)
    [3] Restaurar               (devolver todo a como estaba)
    [4] Ver estado / registro   (que se ha hecho, cuando)
    [0] Salir

Principios de seguridad (iguales que la CLI):
- NO hay un segundo path de modificacion: el menu reutiliza exactamente
  las mismas funciones de cli.py / engine (ReadProbeRunner, _probe_device,
  build_plan, execute_plan, restore_packages). La whitelist de escritura,
  el fail-safe al primer fallo y el log de auditoria son los mismos.
- Autodeteccion del dispositivo ADB (`adb devices`): si hay un solo
  dispositivo conectado, se usa sin pedir nada; si hay varios, el
  usuario elige; si no hay ninguno, se explica como activar ADB.
- Confirmacion EXPLICITA: para optimizar y para restaurar hay que
  teclear "SI" (no basta con pulsar enter).
- Modelos nuevos: sin perfil propio, el perfil generico de la familia SO
  propone una lista conservadora de bloatware filtrada contra el
  inventario real y las exclusiones nucleo (red dura del planner).
  El plan se muestra SIEMPRE antes de confirmar (dry-run).
"""
from __future__ import annotations

from typing import Callable, List, Optional

import cli
from detect.adb_probe import list_adb_devices
from detect.candidates import discover_candidates, reason_for
from detect.identity import resolve_profile
from detect.profiles import load_profiles
from engine.audit_log import read_log
from engine.executor import (
    AdbActionRunner,
    ExecutionError,
    execute_plan,
    restore_packages,
)
from engine.planner import PlanError, build_plan, render_plan

PRINT = Callable[[str], None]
INPUT = Callable[[], str]

BANNER = """
=====================================================
   DAEWOO TV OPTIMIZER  -  menu sencillo
=====================================================
   [1] Detectar la tele      (solo lectura)
   [2] Optimizar             (deshabilitar bloatware)
   [3] Restaurar             (devolver a como estaba)
   [4] Ver estado / registro
   [0] Salir
=====================================================
"""


# ------------------------------------------------------------------ helpers
def _print(msg: str = "", out: PRINT = print) -> None:
    out(msg)


def _input_safe(input_fn: INPUT) -> str:
    try:
        return input_fn()
    except EOFError:
        return ""


def choose_device(
    input_fn: INPUT = input,
    out: PRINT = print,
    adb_bin: Optional[str] = None,
) -> Optional[str]:
    """Auto-detecta el dispositivo ADB.

    - 1 dispositivo -> se usa directamente (sin friccion).
    - Varios -> el usuario elige por numero (o teclea una IP).
    - Ninguno -> se explica como activar el modo desarrollador + ADB.
    """
    devices = list_adb_devices(adb_bin)
    if not devices:
        _print(
            "\nNo se ha encontrado ninguna TV conectada por ADB.\n"
            "Para conectarla:\n"
            "  1. En la TV: Ajustes > Sistema > Informacion > pulsar 7 veces\n"
            "     a 'Numero de version' (activa el modo desarrollador).\n"
            "  2. En la TV: Ajustes > Sistema > Opciones de desarrollador >\n"
            "     'Depuracion ADB' = activado.\n"
            "  3. Conecta la TV al mismo router/WiFi que este PC.\n"
            "  4. En la TV, anota su direccion IP (Ajustes > Red).\n"
            "  5. En este PC, ejecuta:  adb connect IP_DE_LA_TV:5555\n"
            "     (usa el adb incluido: vendor/platform-tools/adb)\n",
            out,
        )
    elif len(devices) == 1:
        _print(f"\nTV encontrada: {devices[0]}", out)
        _print("(escribe 0 para teclear una direccion manualmente)", out)
    else:
        _print("\nSe han encontrado varias TVs conectadas:", out)
        for i, d in enumerate(devices, 1):
            _print(f"  [{i}] {d}", out)
        _print("  [0] teclear una direccion manualmente", out)

    raw = _input_safe(input_fn).strip()
    if raw == "0":
        raw = _input_safe(input_fn).strip()
        return raw or None
    if raw.isdigit() and 1 <= int(raw) <= len(devices):
        return devices[int(raw) - 1]
    if raw:
        # El usuario ha tecleado una direccion (IP:puerto o serial).
        return raw
    if not devices:
        return None
    _print(f"Opcion vacia: se usara el primer dispositivo: {devices[0]}", out)
    return devices[0]


def confirm_si(input_fn: INPUT, out: PRINT) -> bool:
    """Confirmacion explicita: solo 'SI' (mayusculas o minusculas)."""
    raw = _input_safe(input_fn).strip().lower()
    return raw == "si"


def _probe_and_plan(device: str, probe: cli.ReadProbeRunner):
    """Sondea y construye el plan dry-run con candidatos automaticos.

    Devuelve (data_probe, identity, profile, candidates, plan).
    """
    data = cli._probe_device(device, probe)
    identity = data["identity"]
    profiles, default_profile = load_profiles()
    profile = resolve_profile(identity, profiles, default_profile)
    candidates = discover_candidates(data["inventory"], profile)
    plan = build_plan(identity, profile, data["inventory"], candidates)
    return data, identity, profile, candidates, plan


# ------------------------------------------------------------------ acciones
def do_detect(device: str, probe: cli.ReadProbeRunner, out: PRINT = print) -> int:
    """[1] Detectar la tele: solo lectura. Muestra modelo, SO, perfil."""
    _print(f"\n--- Detectando la TV ({device}) ---", out)
    try:
        data = cli._probe_device(device, probe)
    except Exception as exc:  # fail-safe: nunca crash, siempre mensaje
        _print(f"ERROR al leer la TV: {exc}", out)
        _print(
            "Comprueba que la TV esta encendida, con ADB activo y en la misma red.",
            out,
        )
        return 1
    identity = data["identity"]
    profiles, default_profile = load_profiles()
    profile = resolve_profile(identity, profiles, default_profile)

    _print(f"  Modelo:      {identity.model or 'no identificado'}", out)
    _print(f"  Marca:       {identity.brand or '?'}", out)
    _print(
        f"  Sistema:     {identity.os_family} (version {identity.os_version or '?'})",
        out,
    )
    _print(f"  Firmware:    {identity.firmware or '?'}", out)
    _print(
        f"  Evidencia:   ADB en el dispositivo -> concluyente: {identity.conclusive}",
        out,
    )
    _print(f"  Perfil:      {profile.get('profile', 'desconocido')}", out)

    is_family_generic = str(profile.get("profile", "")).endswith("/generic")
    if is_family_generic:
        _print(
            "  NOTA: este modelo no esta en la matriz de compatibilidad;\n"
            "        se usa el perfil generico de su familia SO (lista\n"
            "        conservadora). El plan se mostrara antes de confirmar.",
            out,
        )
    if not profile.get("actions_allowed"):
        _print(
            "\n  Esta TV NO se puede optimizar con esta herramienta\n"
            "  (SO propietario o identificacion no concluyente). Solo se\n"
            "  puede identificar; no se modificara nada.",
            out,
        )
        return 0
    _print("\n  La TV SÍ admite optimización. Opción [2] para ver el plan.", out)
    return 0


def do_optimize(
    device: str,
    probe: cli.ReadProbeRunner,
    runner: AdbActionRunner,
    input_fn: INPUT = input,
    log: str = cli.DEFAULT_LOG,
    out: PRINT = print,
) -> int:
    """[2] Optimizar: plan dry-run -> confirmacion 'SI' -> apply -> resumen."""
    _print(f"\n--- Preparando optimizacion ({device}) ---", out)
    try:
        data, identity, profile, candidates, plan = _probe_and_plan(device, probe)
    except (PlanError, ExecutionError) as exc:
        _print(f"NO se ha podido preparar el plan (fail-safe): {exc}", out)
        return 4

    if not identity.conclusive:
        _print("La identificacion NO es concluyente; no se modificara nada.", out)
        return 4
    if not profile.get("actions_allowed"):
        _print("El perfil de esta TV no permite modificaciones; no se hara nada.", out)
        return 4

    _print(render_plan(plan), out)
    if plan.actions:
        _print("\n  Motivos de cada paquete:", out)
        for a in plan.actions:
            _print(f"   - {a.package}: {reason_for(a.package, profile)}", out)
    if not plan.actions:
        _print("\n  No hay nada que optimizar en esta TV (plan vacio).", out)
        return 0

    _print(
        f"\n  Se van a deshabilitar {len(plan.actions)} paquetes "
        "(reversible: opcion [3]).",
        out,
    )
    if not confirm_si(input_fn, out):
        _print("Cancelado por el usuario. No se ha modificado nada.", out)
        return 0

    try:
        summary = execute_plan(plan, runner, device, log)
    except ExecutionError as exc:
        _print(f"ERROR de ejecucion: {exc}", out)
        return 1

    _print(f"\n  Ejecutados: {len(summary['executed'])} de {len(plan.actions)}", out)
    for p in summary["executed"]:
        _print(f"   - {p}  (deshabilitado)", out)
    if summary["failed"]:
        _print(f"  FALLO en: {summary['failed']}", out)
        _print(f"  Sin ejecutar: {', '.join(summary['remaining']) or 'ninguno'}", out)
        _print("  Puedes restaurar con la opcion [3] y volver a intentarlo.", out)
        return 1
    _print("  Listo. La TV queda optimizada. Para volver atras: opcion [3].", out)
    return 0


def do_restore(
    device: str,
    runner: AdbActionRunner,
    input_fn: INPUT = input,
    log: str = cli.DEFAULT_LOG,
    out: PRINT = print,
) -> int:
    """[3] Restaurar: re-habilita todo lo deshabilitado (segun el log)."""
    _print(f"\n--- Restaurando ({device}) ---", out)
    entries = read_log(log)
    executed = [
        e["payload"]["package"]
        for e in entries
        if e.get("op") == "action_executed"
        and e.get("payload", {}).get("exit_code") == 0
    ]
    packages: List[str] = list(dict.fromkeys(executed))
    if not packages:
        _print("  No hay paquetes que restaurar (registro vacio o sin acciones).", out)
        return 0
    _print("  Se van a re-habilitar estos paquetes:", out)
    for p in packages:
        _print(f"   - {p}", out)
    if not confirm_si(input_fn, out):
        _print("Cancelado por el usuario. No se ha modificado nada.", out)
        return 0
    try:
        summary = restore_packages(packages, runner, device, log)
    except ExecutionError as exc:
        _print(f"ERROR de restauracion: {exc}", out)
        return 1
    _print(f"\n  Restaurados: {len(summary['executed'])} de {len(packages)}", out)
    if summary["failed"]:
        _print(f"  FALLO en: {summary['failed']}", out)
        return 1
    _print("  Listo. La TV ha quedado como estaba antes de optimizarla.", out)
    return 0


def do_status(log: str = cli.DEFAULT_LOG, out: PRINT = print) -> int:
    """[4] Ver estado / registro: las ultimas operaciones en lenguaje claro."""
    _print("\n--- Registro de operaciones (ultimas 15) ---", out)
    entries = read_log(log)
    if not entries:
        _print("  Sin operaciones registradas.", out)
        return 0
    for e in entries[-15:]:
        op = e.get("op", "?")
        ts = e.get("ts", "")
        payload = e.get("payload", {})
        pkg = payload.get("package", "")
        if op == "action_executed":
            ok = payload.get("exit_code") == 0
            _print(f"  [{ts}] deshabilitar {pkg} -> {'OK' if ok else 'FALLO'}", out)
        elif op == "restoration_action":
            ok = payload.get("exit_code") == 0
            _print(f"  [{ts}] re-habilitar {pkg} -> {'OK' if ok else 'FALLO'}", out)
        elif op == "restoration_completed":
            ok = payload.get("success") is True
            _print(
                f"  [{ts}] restauracion completada -> {'OK' if ok else 'PARCIAL'}",
                out,
            )
        else:
            _print(f"  [{ts}] {op} {pkg}", out)
    return 0


# ---------------------------------------------------------------------- menu
def run_menu(
    input_fn: INPUT = input,
    out: PRINT = print,
    probe: Optional[cli.ReadProbeRunner] = None,
    runner: Optional[AdbActionRunner] = None,
    log: str = cli.DEFAULT_LOG,
    adb_bin: Optional[str] = None,
) -> int:
    """Bucle principal del menu. Devuelve el exit code final (0 = limpio)."""
    probe = probe if probe is not None else cli.ReadProbeRunner()
    runner = runner if runner is not None else AdbActionRunner()
    rc = 0
    while True:
        _print(BANNER, out)
        choice = _input_safe(input_fn).strip()
        if choice == "0":
            _print("Adios.", out)
            return rc
        if choice in ("1", "2", "3"):
            device = choose_device(input_fn, out, adb_bin)
            if not device:
                _print("Sin dispositivo: operacion cancelada.", out)
                continue
            if choice == "1":
                rc = max(rc, do_detect(device, probe, out))
            elif choice == "2":
                rc = max(rc, do_optimize(device, probe, runner, input_fn, log, out))
            else:
                rc = max(rc, do_restore(device, runner, input_fn, log, out))
        elif choice == "4":
            rc = max(rc, do_status(log, out))
        else:
            _print(f"Opcion no valida: {choice!r}. Elige 0-4.", out)


def main(argv: Optional[List[str]] = None) -> int:
    return run_menu()


if __name__ == "__main__":
    raise SystemExit(main())
