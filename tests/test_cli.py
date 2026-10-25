"""Tests for detect.cli (4 tests)."""
import contextlib
import io
import json
import unittest

from detect.cli import main


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestCli(unittest.TestCase):
    def test_manual_identity_json(self):
        code, out, _ = run_cli("--model", "55DM75QV", "--os", "VIDAA")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["identity"]["os_family"], "vidaa")
        self.assertEqual(data["identity"]["confidence"], "likely")
        self.assertFalse(data["actions_allowed"])

    def test_no_input_still_resolves_failsafe(self):
        code, out, _ = run_cli()
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["identity"]["os_family"], "unknown")
        self.assertFalse(data["actions_allowed"])

    def test_unknown_os_errors(self):
        code, _, err = run_cli("--model", "X", "--os", "WebOS")
        self.assertEqual(code, 2)
        self.assertIn("unrecognized OS", err)

    def test_output_is_valid_json_always(self):
        for argv in (("--model", "A", "--os", "Tivo"), ("--os", "Android TV")):
            code, out, _ = run_cli(*argv)
            self.assertEqual(code, 0, argv)
            json.loads(out)


if __name__ == "__main__":
    unittest.main()
