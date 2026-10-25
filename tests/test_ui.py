"""Tests de ui.py (FASE 5.5): el menu sencillo de usuario final.

Cubren el flujo completo SIN tocar la red ni el adb real:
- probe y runner falsos inyectados (mismo contrato que los de producción);
- list_adb_devices y read_log parcheados;
- log de auditoria en un archivo temporal.

Comportamientos clave bajo prueba:
- Menu: opciones validas/invalidas, salida limpia.
- Deteccion de dispositivo ADB: ninguno / uno / varios / manual.
- Detectar: solo lectura, modelo nuevo -> perfil generico de la familia.
- Optimizar: plan dry-run + confirmacion 'SI'; cancelacion con 'NO' no
  ejecuta NADA; al aplicar se usan los mismos comandos reversibles.
- Restaurar: re-habilita solo lo que el log registro como exitoso.
"""
import tempfile
import unittest
from unittest import mock

import ui
from cli import ProbeResult

PROPS = {
    "ro.build.display.id": "PSP8860.9",
    "ro.build.fingerprint": "daewoo/emu64x/arm64:9/PSP8860/123:user/release-keys",
    "ro.build.version.release": "9",
    "ro.build.version.sdk": "28",
    "ro.product.brand": "Daewoo",
    "ro.product.device": "emu64x",
    "ro.product.model": "D98FC7500",
    "ro.product.name": "daewoo_box",
}

# Modelo NUEVO (no esta en la matriz) con bloatware detectable:
# play.games (known_packages del perfil generico) + com.example.demo
# (patron .demo$) + paquetes nucleo que NUNCA deben tocarse.
PACKAGES = [
    "com.android.systemui",
    "com.android.settings",
    "com.google.android.play.games",
    "com.example.demo",
    "com.example.app",
]


class FakeProbe:
    """Sondeo de solo lectura falso (mismo contrato que cli.ReadProbeRunner)."""

    def __init__(self, packages=PACKAGES, props=PROPS):
        self.packages = packages
        self.props = props
        self.calls = []

    def run(self, device, cmd):
        self.calls.append((device, cmd))
        if cmd.startswith("getprop "):
            key = cmd[len("getprop "):].strip()
            return ProbeResult(0, self.props.get(key, ""), "")
        if cmd == "pm list packages":
            return ProbeResult(
                0, "\n".join("package:" + p for p in self.packages), ""
            )
        if cmd == "pm list packages -d":
            return ProbeResult(0, "", "")
        return ProbeResult(1, "", "comando no soportado por el fake")


class FakeRunner:
    """Ejecutor de escritura falso: registra comandos, puede fallar a pedido."""

    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.commands = []

    def run(self, device, cmd):
        self.commands.append((device, cmd))
        pkg = cmd.split()[-1]
        if pkg in self.fail_on:
            return ProbeResult(255, "", "fallo simulado")
        return ProbeResult(0, "", "")


class TuiTestBase(unittest.TestCase):
    # Registro de auditoria de ejemplo: 2 acciones exitosas + 1 con fallo.
    LOG_OK = [
        {
            "op": "action_executed",
            "ts": "2026-10-25T10:00:00Z",
            "payload": {"package": "com.a", "exit_code": 0},
        },
        {
            "op": "action_executed",
            "ts": "2026-10-25T10:00:01Z",
            "payload": {"package": "com.b", "exit_code": 0},
        },
        {
            "op": "action_executed",
            "ts": "2026-10-25T10:00:02Z",
            "payload": {"package": "com.c", "exit_code": 1},  # fallo: no restaurar
        },
    ]

    def run_menu(
        self,
        inputs,
        probe=None,
        runner=None,
        adb_devices=(),
        log_entries=(),
    ):
        probe = probe if probe is not None else FakeProbe()
        runner = runner if runner is not None else FakeRunner()
        lines = []
        it = iter(inputs)

        def input_fn():
            try:
                return next(it)
            except StopIteration:
                raise EOFError

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("ui.list_adb_devices", return_value=list(adb_devices)), \
                 mock.patch("ui.read_log", return_value=list(log_entries)):
                rc = ui.run_menu(
                    input_fn=input_fn,
                    out=lines.append,
                    probe=probe,
                    runner=runner,
                    log=f"{tmp}/audit.jsonl",
                )
        return rc, "\n".join(lines), probe, runner


class TestMenuBasics(TuiTestBase):
    def test_exit_is_clean(self):
        rc, out, _, _ = self.run_menu(["0"])
        self.assertEqual(rc, 0)
        self.assertIn("Adios.", out)

    def test_invalid_option_is_rejected(self):
        rc, out, _, _ = self.run_menu(["9", "0"])
        self.assertEqual(rc, 0)
        self.assertIn("Opcion no valida", out)

    def test_banner_shows_all_actions(self):
        rc, out, _, _ = self.run_menu(["0"])
        for label in ("Detectar la tele", "Optimizar", "Restaurar", "Salir"):
            self.assertIn(label, out)


class TestChooseDevice(TuiTestBase):
    def test_single_device_autoselected(self):
        rc, out, probe, _ = self.run_menu(
            ["1", "", "0"], adb_devices=["192.168.1.50:5555"]
        )
        self.assertEqual(rc, 0)
        self.assertIn("TV encontrada: 192.168.1.50:5555", out)
        self.assertTrue(
            all(dev == "192.168.1.50:5555" for dev, _ in probe.calls),
            probe.calls,
        )

    def test_multiple_devices_user_picks(self):
        rc, out, probe, _ = self.run_menu(
            ["1", "2", "0"], adb_devices=["a:5555", "b:5555"]
        )
        self.assertEqual(rc, 0)
        self.assertIn("[2] b:5555", out)
        self.assertTrue(all(dev == "b:5555" for dev, _ in probe.calls))

    def test_no_device_explains_how_to_connect(self):
        rc, out, probe, _ = self.run_menu(["1", "0", "192.168.1.99:5555", "0"])
        self.assertEqual(rc, 0)
        self.assertIn("adb connect", out)
        self.assertIn("modo desarrollador", out)
        self.assertTrue(all(dev == "192.168.1.99:5555" for dev, _ in probe.calls))


class TestDetect(TuiTestBase):
    def test_detect_new_model_uses_family_generic_profile(self):
        # D98FC7500 no esta en la matriz: debe resolverse a aosp-tv/generic
        # (familia aosp-uncertified) y avisar que usa perfil generico.
        rc, out, _, _ = self.run_menu(["1", "0", "TV:5555", "0"])
        self.assertEqual(rc, 0)
        self.assertIn("D98FC7500", out)
        self.assertIn("aosp-uncertified", out)
        self.assertIn("aosp-tv/generic", out)
        self.assertIn("perfil generico", out)
        self.assertIn("admite optimización", out)

    def test_detect_is_read_only(self):
        rc, out, probe, runner = self.run_menu(["1", "0", "TV:5555", "0"])
        self.assertEqual(rc, 0)
        self.assertEqual(runner.commands, [])  # nada de escritura


class TestOptimize(TuiTestBase):
    def test_optimize_confirm_executes_reversible_actions(self):
        rc, out, _, runner = self.run_menu(["2", "0", "TV:5555", "SI", "0"])
        self.assertEqual(rc, 0)
        cmds = [c for _, c in runner.commands]
        self.assertIn("pm disable-user --user 0 com.google.android.play.games", cmds)
        self.assertIn("pm disable-user --user 0 com.example.demo", cmds)
        # Nucleo NUNCA se toca, ni por deteccion automatica.
        self.assertNotIn(
            "pm disable-user --user 0 com.android.systemui", cmds
        )
        self.assertNotIn(
            "pm disable-user --user 0 com.android.settings", cmds
        )
        self.assertIn("Listo", out)
        # El plan se muestra antes de confirmar (dry-run visible).
        self.assertIn("Motivos de cada paquete", out)

    def test_optimize_cancel_executes_nothing(self):
        rc, out, _, runner = self.run_menu(["2", "0", "TV:5555", "NO", "0"])
        self.assertEqual(rc, 0)
        self.assertEqual(runner.commands, [])
        self.assertIn("Cancelado por el usuario", out)
        self.assertIn("No se ha modificado nada", out)

    def test_optimize_empty_confirmation_does_not_apply(self):
        # Enter vacio (ni 'SI') no aplica: confirmacion explicita.
        rc, out, _, runner = self.run_menu(["2", "0", "TV:5555", "", "0"])
        self.assertEqual(rc, 0)
        self.assertEqual(runner.commands, [])


class TestRestore(TuiTestBase):
    def test_restore_reenables_only_successful_actions(self):
        rc, out, _, runner = self.run_menu(
            ["3", "0", "TV:5555", "SI", "0"], log_entries=self.LOG_OK
        )
        self.assertEqual(rc, 0)
        cmds = [c for _, c in runner.commands]
        self.assertIn("pm enable --user 0 com.a", cmds)
        self.assertIn("pm enable --user 0 com.b", cmds)
        self.assertNotIn("pm enable --user 0 com.c", cmds)
        self.assertIn("Restaurados: 2", out)

    def test_restore_with_empty_log_is_noop(self):
        rc, out, _, runner = self.run_menu(["3", "0", "TV:5555", "0"])
        self.assertEqual(rc, 0)
        self.assertEqual(runner.commands, [])
        self.assertIn("No hay paquetes que restaurar", out)

    def test_restore_cancel_executes_nothing(self):
        rc, out, _, runner = self.run_menu(
            ["3", "0", "TV:5555", "NO", "0"], log_entries=self.LOG_OK
        )
        self.assertEqual(rc, 0)
        self.assertEqual(runner.commands, [])
        self.assertIn("Cancelado por el usuario", out)


class TestStatus(TuiTestBase):
    def test_status_shops_recent_operations(self):
        rc, out, _, _ = self.run_menu(["4", "0"], log_entries=self.LOG_OK)
        self.assertEqual(rc, 0)
        self.assertIn("deshabilitar com.a -> OK", out)
        self.assertIn("deshabilitar com.c -> FALLO", out)

    def test_status_empty_log(self):
        rc, out, _, _ = self.run_menu(["4", "0"])
        self.assertEqual(rc, 0)
        self.assertIn("Sin operaciones registradas", out)


if __name__ == "__main__":
    unittest.main()
