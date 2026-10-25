"""Pruebas de la entrada interactiva (doble clic) y la GUI (FASE 5.6).

Cubren el incidente real del usuario: el .exe abría y cerraba la consola
sin mostrar nada porque (a) sin argumentos argparse fallaba, (b) no había
interfaz gráfica y (c) los errores no eran visibles.

- main() sin argumentos enruta a la GUI (tk si hay display, si no menú
  terminal; windowed sin display -> fallo elegante con log).
- El menú terminal sale limpiamente con stdin agotado (sin bucle
  infinito).
- El log de auditoría en ejecutable congelado vive en el home (el CWD al
  hacer doble clic en Windows no es fiable).
- stdio None (build windowed) se redirige a un archivo: ningún comando
  crashea por imprimir.
- El puente de confirmación GUI mapea el diálogo SI/NO al input_fn que
  las funciones del motor ya conocían.
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path
from typing import List
from unittest import mock

import cli
import ui
import ui_tk
from detect import _paths


class TestNoArgsRouting(unittest.TestCase):
    """main() sin argumentos (doble clic) debe abrir la GUI, no fallar."""

    def test_no_args_routes_to_terminal_menu_without_display(self) -> None:
        calls: List[str] = []

        def fake_run_menu(*a, **k) -> int:
            calls.append("menu")
            return 7

        with mock.patch.object(ui_tk, "has_display", return_value=False), \
             mock.patch.object(ui, "run_menu", side_effect=fake_run_menu):
            rc = cli.main([])
        self.assertEqual(rc, 7)
        self.assertEqual(calls, ["menu"])

    def test_no_args_routes_to_tk_when_display_available(self) -> None:
        calls: List[str] = []

        def fake_tk_run() -> int:
            calls.append("tk")
            return 3

        with mock.patch.object(ui_tk, "has_display", return_value=True), \
             mock.patch.object(ui_tk, "run", side_effect=fake_tk_run):
            rc = cli.main([])
        self.assertEqual(rc, 3)
        self.assertEqual(calls, ["tk"])

    def test_windowed_without_display_fails_gracefully(self) -> None:
        # .exe windowed sin display: no hay consola ni pantalla -> escribe
        # el aviso y sale 1 (antes: la ventana moría en silencio).
        with mock.patch.object(sys, "frozen", "daewoo", create=True), \
             mock.patch.object(ui_tk, "has_display", return_value=False), \
             mock.patch.object(cli, "_ENTRY_WINDOWED", True):
            rc = cli.main([])
        self.assertEqual(rc, 1)
        p = Path(ui_tk.fallback_log_path())
        try:
            self.assertTrue(p.is_file())
        finally:
            p.unlink(missing_ok=True)

    def test_explicit_command_still_works(self) -> None:
        # El routing no debe romper los comandos explícitos.
        rc = cli.main(["identify", "--model", "X", "--os", "VIDAA"])
        self.assertEqual(rc, 0)


class TestMenuEof(unittest.TestCase):
    """El menú terminal debe salir limpiamente con stdin agotado."""

    def test_run_menu_exits_on_eof(self) -> None:
        def eof_input() -> str:
            raise EOFError

        out: List[str] = []
        rc = ui.run_menu(input_fn=eof_input, out=out.append)
        self.assertEqual(rc, 0)
        self.assertTrue(any("saliendo" in m for m in out))

    def test_run_menu_still_exits_with_0_choice(self) -> None:
        answers = iter(["0"])
        out: List[str] = []
        rc = ui.run_menu(input_fn=lambda: next(answers), out=out.append)
        self.assertEqual(rc, 0)
        self.assertTrue(any("Adios" in m for m in out))


class TestDefaultLogPath(unittest.TestCase):
    """Log de auditoría: en frozen va al home, en fuente es relativo."""

    def test_source_mode_is_relative_name(self) -> None:
        self.assertEqual(_paths.default_log_path(), _paths.LOG_NAME)

    def test_frozen_mode_goes_to_home(self) -> None:
        with mock.patch.object(sys, "frozen", "daewoo", create=True), \
             mock.patch.dict(os.environ, {"HOME": "/tmp/fakehome-daewoo"}):
            p = _paths.default_log_path()
        self.assertTrue(p.startswith("/tmp/fakehome-daewoo/.daewoo-optimizer/"))
        self.assertTrue(p.endswith(_paths.LOG_NAME))


class TestStdioHardening(unittest.TestCase):
    """_reconfigure_stdio: windowed (stdout=None) no puede crashear."""

    def test_none_streams_get_redirected(self) -> None:
        tmp = Path("/tmp/fakehome-stdio-daewoo")
        old_out, old_err = sys.stdout, sys.stderr
        with mock.patch.object(sys, "stdout", None), \
             mock.patch.object(sys, "stderr", None), \
             mock.patch.dict(os.environ, {"HOME": str(tmp)}):
            cli._reconfigure_stdio()
            self.assertIsNotNone(sys.stdout)
            self.assertIsNotNone(sys.stderr)
            sys.stdout.write("hola\n")
            sys.stderr.write("adios\n")
        sys.stdout, sys.stderr = old_out, old_err
        log = tmp / ".daewoo-optimizer" / "console.log"
        self.assertTrue(log.is_file())
        content = log.read_text(encoding="utf-8")
        self.assertIn("hola", content)
        self.assertIn("adios", content)

    def test_normal_streams_get_utf8_replace(self) -> None:
        buf = io.StringIO()
        old_out = sys.stdout
        sys.stdout = buf
        try:
            cli._reconfigure_stdio()
            sys.stdout.write("café ñandú\n")  # no debe lanzar
        finally:
            sys.stdout = old_out
        self.assertIn("café", buf.getvalue())


class TestConfirmBridgeMapping(unittest.TestCase):
    """El diálogo SI/NO de la GUI mapea al input_fn del motor."""

    def test_answer_mapping(self) -> None:
        self.assertEqual(ui_tk._answer_to_input(True), "si")
        self.assertEqual(ui_tk._answer_to_input(False), "")

    def test_ui_confirm_si_accepts_bridge_output(self) -> None:
        out: List[str] = []
        # El motor sigue siendo el mismo: 'si' confirma, '' cancela.
        self.assertTrue(ui.confirm_si(lambda: ui_tk._answer_to_input(True), out.append))
        self.assertFalse(ui.confirm_si(lambda: ui_tk._answer_to_input(False), out.append))


class TestConsoleMain(unittest.TestCase):
    """_console_main captura excepciones (la consola no cierra sin mostrar nada)."""

    def test_exception_is_caught_and_reported(self) -> None:
        err = io.StringIO()
        old_err, old_stdout = sys.stderr, sys.stdout
        sys.stderr, sys.stdout = err, io.StringIO()
        try:
            with mock.patch.object(cli, "main", side_effect=RuntimeError("boom")):
                rc = cli._console_main()
        finally:
            sys.stderr, sys.stdout = old_err, old_stdout
        self.assertEqual(rc, 1)
        self.assertIn("boom", err.getvalue())


if __name__ == "__main__":
    unittest.main()
