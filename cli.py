"""daewoo-optimizer — CLI top-level (FASE 5).

La herramienta se distribuye en USB y se ejecuta en un PC:
  python3 cli.py <comando>

Comandos:
  identify  Identidad manual (modelo + SO) -> perfil. Nunca concluyente.
  probe     Sondeo ADB SOLO LECTURA del TV (identidad + inventario).
  plan      Plan dry-run (siempre dry_run=true). Sin --confirm no ejecuta nada.
  apply     Ejecuta el plan en el TV. Requiere --confirm, identidad
            CONCLUYENTE (ADB u oficial) y perfil que permita acciones.
  restore   Re-habilita paquetes deshabilitados (pm enable --user 0).
  report    Muestra el log de auditoría (JSON-lines).

Modelo de seguridad:
- El plan es dry-run por construcción (planner FASE 4).
- apply es el ÚNICO path de modificación; exige --confirm explícito.
- Solo `pm disable-user --user 0 <pkg>` / `pm enable --user 0 <pkg>`;
  whitelist estricto en engine/executor.py. Sin shell.
- Cada operación queda en el log de auditoría (engine/audit_log.py).
- Fail-safe: identidad no concluyente, perfil default-deny o inventario
  vacío -> no se modifica nada.

Sin dependencias externas: solo stdlib de Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from detect.adb_probe import (
    build_probe_commands,
    parse_getprop_output,
    parse_package_list,
    resolve_adb_bin,
)
from detect.candidates import discover_candidates
from detect.identity import (
    DeviceIdentity,
    identity_from_adb,
    identity_from_manual,
    resolve_profile,
)
from detect.manual_input import ManualInputError, parse_manual_entry
from detect.profiles import load_profiles
from engine.audit_log import read_log
from engine.executor import (
    AdbActionRunner,
    ActionRunner,
    ExecutionError,
    execute_plan,
    restore_packages,
)
from engine.inventory import build_inventory, inventory_summary
from engine.planner import PlanError, build_plan

DEFAULT_LOG = "daewoo-optimizer-ops.jsonl"


# ---------------------------------------------------------------- ADB runner
class ReadProbeRunner:
    """Runner de solo lectura para el sondeo: ejecuta el probe ADB.

    Separado del ActionRunner de escritura: no puede recibir comandos
    de escritura aunque se le intenten pasar (valida contra la whitelist
    de solo lectura de detect/adb_probe.py).
    """

    def __init__(self, runner: Optional[ActionRunner] = None) -> None:
        # Para tests se inyecta un runner falso; en producción usamos
        # subprocess directamente sobre comandos de solo lectura.
        self._fake = runner

    def run(self, device: str, cmd: str) -> "ProbeResult":
        from detect.adb_probe import validate_command

        validate_command(cmd)  # solo lectura, siempre
        if self._fake is not None:
            r = self._fake.run(device, cmd)
            return ProbeResult(r.exit_code, r.stdout, r.stderr)
        import subprocess

        try:
            proc = subprocess.run(
                [resolve_adb_bin(), "-s", device, "shell", cmd],
                shell=False,
                capture_output=True,
                text=True,
                timeout=30.0,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return ProbeResult(1, "", str(exc))
        return ProbeResult(proc.returncode, proc.stdout or "", proc.stderr or "")


class ProbeResult:
    def __init__(self, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _probe_device(device: str, probe: ReadProbeRunner) -> dict:
    """Ejecuta el sondeo de solo lectura y devuelve identidad + inventario."""
    props: dict = {}
    packages: List[str] = []
    for cmd in build_probe_commands():
        r = probe.run(device, cmd)
        if not r.ok:
            continue
        if cmd.startswith("getprop "):
            prop = cmd[len("getprop "):].strip()
            val = r.stdout.strip()
            props[prop] = val if val else None
        elif cmd == "pm list packages":
            packages = parse_package_list(r.stdout)

    # pm list packages -d para estados deshabilitados (mejora el inventario)
    try:
        from detect.adb_probe import validate_command

        validate_command("pm list packages -d")
        r = probe.run(device, "pm list packages -d")
        disabled = parse_package_list(r.stdout) if r.ok else []
    except Exception:
        disabled = []

    inventory = build_inventory(
        "\n".join(f"package:{p}" for p in packages),
        "\n".join(f"package:{p}" for p in disabled),
    )
    identity = identity_from_adb(
        packages,
        model=props.get("ro.product.model"),
        brand=props.get("ro.product.brand"),
        os_version=props.get("ro.build.version.release"),
        firmware=props.get("ro.build.fingerprint"),
    )
    return {"identity": identity, "inventory": inventory}


# ------------------------------------------------------------------ comandos
def cmd_identify(args: argparse.Namespace) -> int:
    try:
        identity = parse_manual_entry(args.model, args.os_name, args.firmware)
    except ManualInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    profiles, default_profile = load_profiles()
    profile = resolve_profile(identity, profiles, default_profile)
    result = {
        "identity": identity.to_dict(),
        "profile": profile.get("profile", "unsupported/default"),
        "actions_allowed": bool(profile.get("actions_allowed", False)),
        "conclusive": identity.conclusive,
        "note": "identidad manual: nunca concluyente; no habilita apply",
    }
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    probe = ReadProbeRunner()
    try:
        data = _probe_device(args.device, probe)
    except Exception as exc:
        print(f"error: sondeo falló: {exc}", file=sys.stderr)
        return 1
    identity: DeviceIdentity = data["identity"]
    profiles, default_profile = load_profiles()
    profile = resolve_profile(identity, profiles, default_profile)
    result = {
        "identity": identity.to_dict(),
        "profile": profile.get("profile", "unsupported/default"),
        "actions_allowed": bool(profile.get("actions_allowed", False)),
        "inventory": inventory_summary(data["inventory"]),
        "inventory_count": len(data["inventory"]),
    }
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if identity.conclusive else 3


def _load_profile_by_id(profile_id: Optional[str]) -> tuple:
    profiles, default_profile = load_profiles()
    if profile_id is None:
        return None, profiles, default_profile
    prof = profiles.get(profile_id)
    if prof is None:
        raise PlanError(f"perfil no encontrado: {profile_id!r}")
    return prof, profiles, default_profile


def _candidates_for_cli(
    args: argparse.Namespace, prof: dict, inventory: dict
) -> List[str]:
    """Candidatos para plan/apply (FASE 5.5):

    1. Los explicitos de la CLI (--candidates) tienen prioridad absoluta.
    2. Si no se pasan, se usa la deteccion automatica de bloatware
       (detect/candidates.py): lista conservadora del perfil filtrada
       contra el INVENTARIO REAL del dispositivo + patrones. Esto es lo
       que permite optimizar modelos NUEVOS sin conocer paquetes.
    3. Sin seccion candidate_discovery en el perfil: plan vacio.

    La seguridad no depende de esta lista: el planner sigue aplicando
    exclusiones nucleo (duras), exclusiones de perfil, inventario real
    y confirmacion explicita."""
    explicit = [c.strip() for c in (args.candidates or "").split(",") if c.strip()]
    if explicit:
        return explicit
    return discover_candidates(inventory, prof)


def cmd_plan(args: argparse.Namespace) -> int:
    """Genera un plan dry-run. Nunca ejecuta nada."""
    if not args.device:
        print("error: plan requiere --device (sondeo ADB)", file=sys.stderr)
        return 2
    try:
        prof, profiles, default_profile = _load_profile_by_id(args.profile)
        probe = ReadProbeRunner()
        data = _probe_device(args.device, probe)
        identity: DeviceIdentity = data["identity"]
        if prof is None:
            prof = resolve_profile(identity, profiles, default_profile)
        candidates = _candidates_for_cli(args, prof, data["inventory"])
        plan = build_plan(identity, prof, data["inventory"], candidates)
    except (PlanError, ExecutionError) as exc:
        print(f"fail-safe: {exc}", file=sys.stderr)
        return 4
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """ÚNICO path de modificación. Exige --confirm + identidad concluyente."""
    if not args.confirm:
        print(
            "error: apply requiere --confirm (acción irreversiblemente "
            "visible en el TV; sin confirmación explícita no se ejecuta)",
            file=sys.stderr,
        )
        return 2
    if not args.device:
        print("error: apply requiere --device", file=sys.stderr)
        return 2
    try:
        prof, profiles, default_profile = _load_profile_by_id(args.profile)
        probe = ReadProbeRunner()
        data = _probe_device(args.device, probe)
        identity: DeviceIdentity = data["identity"]
        if prof is None:
            prof = resolve_profile(identity, profiles, default_profile)
        candidates = _candidates_for_cli(args, prof, data["inventory"])
        plan = build_plan(identity, prof, data["inventory"], candidates)
    except (PlanError, ExecutionError) as exc:
        print(f"fail-safe: {exc}", file=sys.stderr)
        return 4

    if not identity.conclusive:
        print(
            f"fail-safe: identidad no concluyente ({identity.confidence!r}); "
            "no se modifica nada",
            file=sys.stderr,
        )
        return 4

    if not plan.actions:
        print("plan vacío: nada que ejecutar")
        return 0

    runner = AdbActionRunner()
    try:
        summary = execute_plan(plan, runner, args.device, args.log)
    except ExecutionError as exc:
        print(f"error de ejecución: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {"summary": summary, "dry_run": False, "profile": plan.profile_id},
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    )
    return 0 if summary["failed"] is None else 1


def cmd_restore(args: argparse.Namespace) -> int:
    """Re-habilita los paquetes indicados (o los del último plan en el log)."""
    if not args.device:
        print("error: restore requiere --device", file=sys.stderr)
        return 2
    packages = [p.strip() for p in (args.packages or "").split(",") if p.strip()]
    if not packages:
        # Sin lista explícita: leer del log las acciones ejecutadas
        entries = read_log(args.log)
        executed = [
            e["payload"]["package"]
            for e in entries
            if e.get("op") == "action_executed"
            and e.get("payload", {}).get("exit_code") == 0
        ]
        packages = list(dict.fromkeys(executed))  # dedup, preserves order
        if not packages:
            print("no hay paquetes que restaurar (log vacío o sin acciones)",
                  file=sys.stderr)
            return 0
    runner = AdbActionRunner()
    try:
        summary = restore_packages(packages, runner, args.device, args.log)
    except ExecutionError as exc:
        print(f"error de restauración: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if summary["failed"] is None else 1


def cmd_report(args: argparse.Namespace) -> int:
    entries = read_log(args.log)
    print(json.dumps(entries, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="daewoo-optimizer",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("identify", help="identidad manual -> perfil")
    sp.add_argument("--model")
    sp.add_argument("--os", dest="os_name")
    sp.add_argument("--firmware")
    sp.set_defaults(func=cmd_identify)

    sp = sub.add_parser("probe", help="sondeo ADB de solo lectura")
    sp.add_argument("--device", required=True, help="host:port del TV")
    sp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("plan", help="plan dry-run (nunca ejecuta)")
    sp.add_argument("--device", required=True)
    sp.add_argument("--profile", help="id de perfil (opcional)")
    sp.add_argument("--candidates", help="paquetes candidatos, separados por coma")
    sp.add_argument("--log", default=DEFAULT_LOG)
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("apply", help="ejecuta el plan (requiere --confirm)")
    sp.add_argument("--device", required=True)
    sp.add_argument("--profile", help="id de perfil (opcional)")
    sp.add_argument("--candidates",
                    help="paquetes candidatos, separados por coma (opcional: "
                         "sin esta flag se usa la deteccion automatica de "
                         "bloatware del perfil contra el inventario real)")
    sp.add_argument("--confirm", action="store_true",
                    help="confirmación explícita del usuario")
    sp.add_argument("--log", default=DEFAULT_LOG)
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("restore", help="re-habilita paquetes")
    sp.add_argument("--device", required=True)
    sp.add_argument("--packages", help="paquetes a restaurar (o leer del log)")
    sp.add_argument("--log", default=DEFAULT_LOG)
    sp.set_defaults(func=cmd_restore)

    sp = sub.add_parser("report", help="muestra el log de auditoría")
    sp.add_argument("--log", default=DEFAULT_LOG)
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser(
        "gui",
        help="menu interactivo en español (el modo sin fricción; FASE 5.5)",
    )
    sp.add_argument("--log", default=DEFAULT_LOG)
    sp.set_defaults(func=cmd_gui)

    return p


def cmd_gui(args: argparse.Namespace) -> int:
    import ui

    return ui.run_menu(log=args.log)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
