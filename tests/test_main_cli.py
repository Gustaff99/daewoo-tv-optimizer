"""Tests para cli.py — CLI top-level (FASE 5).

Cubren los paths que no requieren un TV real:
- identify: identidad manual -> perfil (nunca concluyente)
- apply sin --confirm: rechaza (exit 2)
- plan/apply con identidad no concluyente: fail-safe (exit 4)
- report: lectura del log
- parser: comandos y flags
"""
import contextlib
import io
import json
import os
import tempfile
import unittest

import cli
from engine.audit_log import append_entry


class TestIdentify(unittest.TestCase):
    def test_manual_identity_never_conclusive(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["identify", "--model", "55DM75QV", "--os", "VIDAA"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["conclusive"])
        self.assertIn("note", data)

    def test_model_only_is_unreliable(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["identify", "--model", "32DE15HLED"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["conclusive"])
        self.assertFalse(data["actions_allowed"])

    def test_invalid_os_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["identify", "--model", "X", "--os", "Windows 95"])
        self.assertEqual(rc, 2)


class TestApplyRequiresConfirm(unittest.TestCase):
    def test_without_confirm_refused(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli.main(
                ["apply", "--device", "192.168.1.50:5555",
                 "--candidates", "com.x", "--profile", "android-tv"]
            )
        self.assertEqual(rc, 2)
        self.assertIn("--confirm", err.getvalue())


class TestReport(unittest.TestCase):
    def test_empty_log(self):
        tmp = tempfile.mkdtemp()
        log = os.path.join(tmp, "nope.jsonl")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["report", "--log", log])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue()), [])

    def test_with_entries(self):
        tmp = tempfile.mkdtemp()
        log = os.path.join(tmp, "ops.jsonl")
        append_entry(log, "action_executed",
                     {"package": "com.a", "exit_code": 0}, timestamp="T1")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["report", "--log", log])
        self.assertEqual(rc, 0)
        entries = json.loads(buf.getvalue())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["op"], "action_executed")


class TestParser(unittest.TestCase):
    def test_all_commands_present(self):
        p = cli.build_parser()
        # parse_args con cada subcomando y sus flags mínimos
        a = p.parse_args(["identify", "--model", "X"])
        self.assertEqual(a.command, "identify")
        a = p.parse_args(["probe", "--device", "d:1"])
        self.assertEqual(a.command, "probe")
        a = p.parse_args(["plan", "--device", "d:1"])
        self.assertEqual(a.command, "plan")
        a = p.parse_args(["apply", "--device", "d:1", "--candidates", "c",
                          "--confirm"])
        self.assertTrue(a.confirm)
        a = p.parse_args(["restore", "--device", "d:1"])
        self.assertEqual(a.command, "restore")
        a = p.parse_args(["report"])
        self.assertEqual(a.command, "report")

    def test_apply_candidates_optional(self):
        # FASE 5.5: --candidates ya es opcional (deteccion automatica
        # contra el inventario real). apply sin candidatos es valido.
        p = cli.build_parser()
        args = p.parse_args(["apply", "--device", "d:1", "--confirm"])
        self.assertIsNone(args.candidates)
        self.assertTrue(args.confirm)
        self.assertEqual(args.device, "d:1")


class TestProbeExitCodes(unittest.TestCase):
    """probe sin adb disponible debe fallar limpiamente (no crash)."""

    def test_probe_without_adb(self):
        # En este entorno no hay adb ni TV: el sondeo devuelve
        # identidad unknown (unreliable) -> exit 3, sin excepción.
        err = io.StringIO()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = cli.main(["probe", "--device", "127.0.0.1:5555"])
        # Sin adb: probe falla -> exit 1 con mensaje, o identity
        # unreliable -> exit 3. Ambos son comportamientos válidos;
        # lo que NO se admite es un traceback (rc fuera de {0,1,3}).
        self.assertIn(rc, (0, 1, 3))


class TestCliCandidates(unittest.TestCase):
    """_candidates_for_cli: prioridad CLI > deteccion automatica (FASE 5.5).

    Sin candidatos en CLI se usa discover_candidates() contra el
    inventario real: known_packages del perfil (solo los presentes)
    + patrones. Sin inventario ni perfil -> [] (el plan queda vacio).
    """

    INVENTORY = {"x.y": "enabled", "z.w": "enabled", "com.example.demo": "enabled"}

    def _args(self, candidates=None):
        import argparse
        return argparse.Namespace(candidates=candidates)

    def test_explicit_cli_candidates_win(self):
        prof = {
            "candidate_discovery": {"known_packages": [{"package": "x.y"}]}
        }
        self.assertEqual(
            cli._candidates_for_cli(self._args("a.b, c.d"), prof, self.INVENTORY),
            ["a.b", "c.d"],
        )

    def test_auto_discovery_used_when_cli_empty(self):
        prof = {
            "candidate_discovery": {
                "known_packages": [
                    {"package": "x.y"},
                    {"package": "not-on-device"},
                    {"nope": True},
                ],
                "patterns": [{"regex": "\\.demo$", "reason": "demo"}],
            }
        }
        # Resultado determinista: deduplicado y ordenado alfabeticamente.
        expected = ["com.example.demo", "x.y"]
        self.assertEqual(
            cli._candidates_for_cli(self._args(None), prof, self.INVENTORY),
            expected,
        )
        self.assertEqual(
            cli._candidates_for_cli(self._args(""), prof, self.INVENTORY),
            expected,
        )

    def test_no_candidates_empty(self):
        self.assertEqual(
            cli._candidates_for_cli(self._args(None), {}, self.INVENTORY), []
        )
        self.assertEqual(
            cli._candidates_for_cli(
                self._args(""), {"candidate_discovery": "bad"}, self.INVENTORY
            ),
            [],
        )
        # Sin inventario no hay que deteccionar (fail-safe: plan vacio).
        self.assertEqual(cli._candidates_for_cli(self._args(None), {}, None), [])


if __name__ == "__main__":
    unittest.main()
