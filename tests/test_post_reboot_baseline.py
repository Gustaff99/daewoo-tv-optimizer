"""Tests para scripts/post_reboot_baseline.py (FASE 7, opcion B).

Cubren:
- Todos los comandos de metricas son de solo lectura (seguridad).
- capture_baseline genera secciones por comando con un runner fake.
- write_baseline crea el archivo con el contenido.
- default_out_path apunta a docs/validation con fecha de hoy.
"""
import datetime as _dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detect.adb_probe import ALLOWED_GETPROPS  # noqa: E402
from scripts.post_reboot_baseline import (  # noqa: E402
    METRIC_COMMANDS,
    capture_baseline,
    default_out_path,
    write_baseline,
)

# Comandos shell de solo lectura admitidos (prefixos fijos).
_READONLY_SHELL = (
    "uptime",
    "cat /proc/loadavg",
    "top ",
    "df ",
    "dumpsys meminfo",
)


class TestMetricCommands(unittest.TestCase):
    def _assert_read_only(self, cmd: str) -> None:
        if cmd.startswith("getprop "):
            prop = cmd[len("getprop "):].strip()
            self.assertIn(prop, ALLOWED_GETPROPS, msg=f"getprop no permitido: {prop!r}")
            return
        for prefix in _READONLY_SHELL:
            if cmd.startswith(prefix):
                return
        self.fail(f"comando no de solo lectura: {cmd!r}")

    def test_all_commands_read_only(self):
        for cmd in METRIC_COMMANDS:
            self._assert_read_only(cmd)

    def test_expected_metrics_present(self):
        joined = "\n".join(METRIC_COMMANDS)
        for expected in (
            "ro.build.fingerprint",
            "uptime",
            "/proc/loadavg",
            "top",
            "df",
            "dumpsys meminfo",
        ):
            self.assertIn(expected, joined)


class TestCaptureBaseline(unittest.TestCase):
    def test_sections_per_command(self):
        calls = []

        def fake_runner(adb_bin, device, cmd):
            calls.append((device, cmd))
            return f"FAKE:{cmd}"

        text = capture_baseline("/fake/adb", "192.168.1.130:5555", fake_runner)
        self.assertEqual(len(calls), len(METRIC_COMMANDS))
        for dev, cmd in calls:
            self.assertEqual(dev, "192.168.1.130:5555")
        for cmd in METRIC_COMMANDS:
            self.assertIn(f"--- {cmd} ---", text)
            self.assertIn(f"FAKE:{cmd}", text)
        self.assertIn("baseline valido", text)
        self.assertIn("192.168.1.130:5555", text)


class TestWriteBaseline(unittest.TestCase):
    def test_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sub" / "baseline.txt"
            write_baseline("contenido", out)
            self.assertTrue(out.is_file())
            self.assertEqual(out.read_text(encoding="utf-8"), "contenido")

    def test_default_out_path(self):
        p = default_out_path()
        today = _dt.date.today().isoformat()
        self.assertEqual(p.name, f"FASE7-before-postreboot-{today}.txt")
        self.assertEqual(p.parent.name, "validation")


if __name__ == "__main__":
    unittest.main()
