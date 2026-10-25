"""Tests for detect.adb_probe."""
import os
import unittest
from pathlib import Path
from unittest import mock

from detect.adb_probe import (
    AdbCommandError,
    build_probe_commands,
    detect_os_from_packages,
    list_adb_devices,
    parse_getprop_output,
    parse_package_list,
    resolve_adb_bin,
    validate_command,
)


class TestWhitelist(unittest.TestCase):
    def test_build_probe_commands_all_readonly(self):
        cmds = build_probe_commands()
        self.assertGreaterEqual(len(cmds), 9)
        for cmd in cmds:  # the whole built probe must pass validation
            validate_command(cmd)
        self.assertIn("pm list packages", cmds)

    def test_validate_accepts_whitelisted_getprop(self):
        validate_command("getprop ro.product.model")
        validate_command("getprop ro.build.fingerprint")

    def test_validate_rejects_arbitrary_getprop(self):
        with self.assertRaises(AdbCommandError):
            validate_command("getprop ro.crypto.keystore.enabled")

    def test_validate_rejects_non_whitelisted_command(self):
        with self.assertRaises(AdbCommandError):
            validate_command("pm uninstall com.example.ads")
        with self.assertRaises(AdbCommandError):
            validate_command("reboot")

    def test_validate_rejects_empty(self):
        with self.assertRaises(AdbCommandError):
            validate_command("   ")


class TestParsers(unittest.TestCase):
    def test_parse_getprop_output(self):
        text = "\n".join(
            [
                "[ro.product.model]: [43DE6500]",
                "[ro.product.brand]: [daewoo]",
                "garbage line",
                "[ro.build.version.release]: [13]",
            ]
        )
        out = parse_getprop_output(text)
        self.assertEqual(out["ro.product.model"], "43DE6500")
        self.assertEqual(out["ro.product.brand"], "daewoo")
        self.assertEqual(out["ro.build.version.release"], "13")

    def test_detect_os_android_tv_package(self):
        self.assertEqual(
            detect_os_from_packages(["com.google.android.tv", "com.foo"]),
            "android-tv",
        )

    def test_detect_os_no_platform_package(self):
        self.assertIsNone(detect_os_from_packages(["com.foo", "com.bar"]))
        self.assertIsNone(detect_os_from_packages([]))

    def test_parse_package_list(self):
        text = "package:com.google.android.tv\npackage:com.example\nnoise\n"
        self.assertEqual(
            parse_package_list(text),
            ["com.google.android.tv", "com.example"],
        )


class TestListAdbDevices(unittest.TestCase):
    """list_adb_devices: solo dispositivos en estado 'device'."""

    def _fake_proc(self, stdout, returncode=0):
        return mock.Mock(returncode=returncode, stdout=stdout, stderr="")

    def test_parses_device_state_only(self):
        stdout = (
            "List of devices attached\n"
            "192.168.1.50:5555\tdevice\n"
            "usb-serial-123\tunauthorized\n"
            "10.0.0.9:5555\toffline\n"
        )
        with mock.patch("subprocess.run", return_value=self._fake_proc(stdout)):
            self.assertEqual(list_adb_devices("/fake/adb"), ["192.168.1.50:5555"])

    def test_no_devices(self):
        with mock.patch("subprocess.run", return_value=self._fake_proc("List of devices attached\n")):
            self.assertEqual(list_adb_devices("/fake/adb"), [])

    def test_adb_missing_returns_empty(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(list_adb_devices("/fake/adb"), [])

    def test_adb_failure_returns_empty(self):
        with mock.patch("subprocess.run", return_value=self._fake_proc("", returncode=1)):
            self.assertEqual(list_adb_devices("/fake/adb"), [])

    def test_uses_devices_subcommand_only(self):
        with mock.patch("subprocess.run", return_value=self._fake_proc("")) as m:
            list_adb_devices("/fake/adb")
        m.assert_called_once_with(
            ["/fake/adb", "devices"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=15.0,
        )


# El binario vendor/platform-tools/adb es un artefacto descargable (no se
# distribuye en el repo publico); el test que asume su presencia se salta
# cuando no existe, en lugar de fallar.
VENDORED_ADB = Path(__file__).resolve().parent.parent / "vendor" / "platform-tools" / "adb"


class TestResolveAdbBin(unittest.TestCase):
    def test_env_var_wins(self):
        with mock.patch.dict(os.environ, {"DAEWOO_ADB": "/opt/adb"}):
            self.assertEqual(resolve_adb_bin(), "/opt/adb")

    def test_blank_env_var_ignored(self):
        with mock.patch.dict(os.environ, {"DAEWOO_ADB": "   "}):
            self.assertNotEqual(resolve_adb_bin(), "   ")

    @unittest.skipUnless(
        VENDORED_ADB.is_file(),
        "vendor/platform-tools/adb ausente (binario descargable, no distribuido en el repo)",
    )
    def test_no_env_prefers_vendored(self):
        env = {k: v for k, v in os.environ.items() if k != "DAEWOO_ADB"}
        with mock.patch.dict(os.environ, env, clear=True):
            bin_ = resolve_adb_bin()
            # En este repo el binario vendado existe: debe preferirse
            # al "adb" del PATH (que no esta instalado en el host).
            self.assertTrue(
                bin_.endswith(os.path.join("vendor", "platform-tools", "adb")),
                bin_,
            )

    def test_fallback_to_path_adb_when_no_vendored(self):
        class FakePath:
            def __init__(self, s: str):
                self.s = s

            def resolve(self):
                return self

            @property
            def parent(self):
                return FakePath(self.s)

            def __truediv__(self, other):
                return FakePath(self.s + "/" + str(other))

            def is_file(self):
                return False

        env = {k: v for k, v in os.environ.items() if k != "DAEWOO_ADB"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch(
            "detect.adb_probe.Path", FakePath
        ):
            self.assertEqual(resolve_adb_bin(), "adb")


if __name__ == "__main__":
    unittest.main()
