"""Tests para scripts/build_usb.py (FASE 8).

Cubren:
- La USB contiene cli.py + detect/ + engine/ + profiles/ + LEEME + SEGURIDAD
- No incluye tests/docs/backups/logs/__pycache__/.pyc
- Rechaza archivos con extension de firmware
- MANIFEST.sha256 es valido y detecta tamperado
"""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_usb import (  # noqa: E402
    FIRMWARE_EXT,
    build_usb,
    collect_sources,
    verify_manifest,
)


class TestCollectSources(unittest.TestCase):
    def test_includes_core(self):
        srcs = collect_sources()
        names = {p.name for p in srcs}
        self.assertIn("cli.py", names)
        self.assertIn("identity.py", names)
        self.assertIn("planner.py", names)
        self.assertIn("executor.py", names)
        self.assertIn("generic.json", names)
        self.assertIn("vidaa.json", names)

    def test_excludes_forbidden(self):
        srcs = collect_sources()
        for p in srcs:
            rel = p.as_posix()
            self.assertNotIn("__pycache__", rel, rel)
            self.assertNotIn("tests", rel, rel)
            self.assertNotIn(".pyc", rel, rel)
            self.assertNotIn("docs", rel, rel)
            self.assertNotIn("backups", rel, rel)

    def test_firmware_ext_rejected(self):
        # Si apareciera un archivo .bin en una carpeta shippeada, debe saltar
        self.assertIn(".bin", FIRMWARE_EXT)
        self.assertIn(".img", FIRMWARE_EXT)


class TestBuildUsb(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_builds_complete_usb(self):
        usb = build_usb(self.tmp)
        self.assertTrue((usb / "cli.py").is_file())
        self.assertTrue((usb / "detect" / "identity.py").is_file())
        self.assertTrue((usb / "engine" / "planner.py").is_file())
        self.assertTrue((usb / "engine" / "executor.py").is_file())
        self.assertTrue((usb / "profiles" / "unsupported" / "default.json").is_file())
        self.assertTrue((usb / "LEEME.txt").is_file())
        self.assertTrue((usb / "SEGURIDAD.txt").is_file())
        self.assertTrue((usb / "MANIFEST.sha256").is_file())
        # Matriz de compatibilidad en la raiz de la USB (sin arbol docs/)
        self.assertTrue((usb / "compatibility-matrix.json").is_file())
        import json

        m = json.loads((usb / "compatibility-matrix.json").read_text(encoding="utf-8"))
        self.assertEqual(len(m["models"]), 32)
        # No test/docs en la USB
        self.assertFalse((usb / "tests").exists())
        self.assertFalse((usb / "docs").exists())
        self.assertFalse(list(usb.rglob("__pycache__")))

    def test_leeme_disclaimer(self):
        usb = build_usb(self.tmp)
        leeme = (usb / "LEEME.txt").read_text(encoding="utf-8")
        self.assertIn("NO es una actualizacion de firmware", leeme)
        self.assertIn("--confirm", leeme)
        self.assertIn("restore", leeme)

    def test_manifest_valid(self):
        usb = build_usb(self.tmp)
        self.assertTrue(verify_manifest(usb))

    def test_manifest_detects_tamper(self):
        usb = build_usb(self.tmp)
        # Tamper un archivo shippeado
        target = usb / "LEEME.txt"
        target.write_text(target.read_text(encoding="utf-8") + "tamperado\n",
                          encoding="utf-8")
        self.assertFalse(verify_manifest(usb))

    def test_manifest_detects_missing_file(self):
        usb = build_usb(self.tmp)
        (usb / "SEGURIDAD.txt").unlink()
        self.assertFalse(verify_manifest(usb))

    def test_rebuild_is_clean(self):
        usb1 = build_usb(self.tmp)
        (usb1 / "extra.txt").write_text("residuo\n")
        usb2 = build_usb(self.tmp)
        self.assertFalse((usb2 / "extra.txt").exists())
        self.assertTrue(verify_manifest(usb2))

    def test_usb_is_importable(self):
        """La CLI de la USB debe funcionar sin el resto del repo."""
        usb = build_usb(self.tmp)
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(usb / "cli.py"), "identify",
             "--model", "55DM75QV", "--os", "VIDAA"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        import json

        data = json.loads(proc.stdout)
        self.assertEqual(data["profile"], "proprietary/vidaa")
        self.assertFalse(data["conclusive"])


if __name__ == "__main__":
    unittest.main()
