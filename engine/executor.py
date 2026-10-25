"""Execution layer (FASE 5): the ONLY code path that can modify a device.

Safety model:
- Write commands are matched against a strict whitelist regex:
  `pm disable-user --user 0 <pkg>` and `pm enable --user 0 <pkg>` with a
  validated Android package name. Nothing else is representable.
- No shell: commands run through `subprocess.run` with a fixed argv
  (adb binary, -s device, shell, cmd). Package names are validated
  before they can reach the argument vector.
- `execute_plan` stops at the first failed action (fail-safe: no blind
  partial continuation) and records every attempt in the audit log.
- The runner is injectable: tests and dry simulations pass a fake runner;
  production uses `AdbActionRunner`.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from detect.adb_probe import resolve_adb_bin
from .audit_log import append_entry, log_restoration
from .planner import ExecutionPlan, PlanAction

# Strict whitelist for the ONLY two write operations this tool can perform.
# <pkg> must be a valid Android package name (dotted Java identifiers,
# hyphens allowed for OEM packages that violate the spec in the wild).
_PKG = r"[A-Za-z_][A-Za-z0-9_$\-]*(\.[A-Za-z_][A-Za-z0-9_$\-]*)*"
_WRITE_CMD_RE = re.compile(
    rf"^pm (disable-user|enable) --user 0 ({_PKG})$"
)


class ExecutionError(Exception):
    """Raised when a command cannot be executed safely."""


def validate_write_command(cmd: str) -> str:
    """Return the canonical command if it is on the write whitelist.

    Raises ExecutionError for anything else. The canonical form is
    returned (not the input) so callers always execute the exact
    whitelisted string.
    """
    if not isinstance(cmd, str):
        raise ExecutionError("command no es una cadena")
    m = _WRITE_CMD_RE.match(cmd.strip())
    if not m:
        raise ExecutionError(f"comando no en whitelist de escritura: {cmd!r}")
    verb, pkg = m.group(1), m.group(2)
    if len(pkg) > 256:
        raise ExecutionError(f"nombre de paquete demasiado largo: {len(pkg)} chars")
    return f"pm {verb} --user 0 {pkg}"


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class ActionRunner(Protocol):
    """Executes one device command. Injectable for tests."""

    def run(self, device: str, cmd: str) -> RunResult:
        ...


class AdbActionRunner:
    """Production runner: `adb -s <device> shell <cmd>` via fixed argv.

    `adb_bin` is the path to the adb executable. When omitted it is
    resolved via detect.adb_probe.resolve_adb_bin(): DAEWOO_ADB env var,
    then the vendored vendor/platform-tools/adb, then "adb" on PATH.
    No shell is involved: the command string is a single argv element,
    and it has already been validated against the write whitelist by
    the caller (execute_plan does this before dispatch).
    """

    def __init__(self, adb_bin: Optional[str] = None, timeout: float = 30.0) -> None:
        self.adb_bin = adb_bin or resolve_adb_bin()
        self.timeout = timeout

    def run(self, device: str, cmd: str) -> RunResult:
        validate_write_command(cmd)  # defense in depth
        try:
            proc = subprocess.run(
                [self.adb_bin, "-s", device, "shell", cmd],
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            raise ExecutionError(f"adb no encontrado en {self.adb_bin!r}")
        except subprocess.TimeoutExpired:
            raise ExecutionError(f"timeout ejecutando {cmd!r}")
        return RunResult(proc.returncode, proc.stdout or "", proc.stderr or "")


def _log_action(
    log_path: str,
    action: PlanAction,
    result: RunResult,
) -> None:
    append_entry(
        log_path,
        "action_executed",
        {
            "package": action.package,
            "command": action.command,
            "exit_code": result.exit_code,
            "stderr": result.stderr[:500],
            "reversible_command": action.reversible_command,
        },
    )


def execute_plan(
    plan: ExecutionPlan,
    runner: ActionRunner,
    device: str,
    log_path: str,
) -> Dict[str, object]:
    """Execute a plan's actions in order. Fail-safe: stop at first failure.

    Returns a summary dict:
      {"executed": [...], "failed": Optional[pkg], "remaining": [...]}

    Every action (success or failure) is recorded in the audit log.
    Raises ExecutionError before dispatch if any command is off the
    whitelist (the plan builder already guarantees this, but the
    execution layer re-validates independently).
    """
    if not plan.dry_run:
        # The planner is dry-run by construction; a non-dry-run plan
        # would be a logic bug. Refuse to execute it.
        raise ExecutionError("plan no dry-run: no existe path de ejecución")

    # Pre-validate every command before touching the device.
    for a in plan.actions:
        validate_write_command(a.command)

    executed: List[str] = []
    remaining: List[str] = []
    failed: Optional[str] = None

    for i, action in enumerate(plan.actions):
        result = runner.run(device, action.command)
        _log_action(log_path, action, result)
        if result.ok:
            executed.append(action.package)
        else:
            failed = action.package
            remaining = [a.package for a in plan.actions[i + 1:]]
            break  # fail-safe: stop at first failure

    return {"executed": executed, "failed": failed, "remaining": remaining}


def restore_packages(
    packages: Sequence[str],
    runner: ActionRunner,
    device: str,
    log_path: str,
) -> Dict[str, object]:
    """Re-enable a set of packages (`pm enable --user 0 <pkg>`).

    Used by the `restore` CLI command. Same fail-safe semantics:
    stop at first failure, log everything.
    """
    executed: List[str] = []
    remaining: List[str] = []
    failed: Optional[str] = None

    pkgs = list(packages)
    for i, pkg in enumerate(pkgs):
        cmd = validate_write_command(f"pm enable --user 0 {pkg}")
        result = runner.run(device, cmd)
        append_entry(
            log_path,
            "restoration_action",
            {
                "package": pkg,
                "command": cmd,
                "exit_code": result.exit_code,
                "stderr": result.stderr[:500],
            },
        )
        if result.ok:
            executed.append(pkg)
        else:
            failed = pkg
            remaining = pkgs[i + 1:]
            break

    log_restoration(log_path, executed, success=failed is None)
    return {"executed": executed, "failed": failed, "remaining": remaining}
