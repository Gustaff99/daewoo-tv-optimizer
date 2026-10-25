"""Tests for engine/inventory.py (FASE 6).

Covers:
- Parsing of pm list packages output (valid, malformed, empty, None)
- Parsing of pm list packages -d output
- build_inventory: enabled/disabled mapping, overlap resolution
- Package name validation (rejects injection attempts)
- inventory_summary formatting
"""
import unittest

from engine.inventory import (
    build_inventory,
    inventory_summary,
    parse_pm_list_packages,
    parse_pm_list_packages_disabled,
)


class TestParsePmListPackages(unittest.TestCase):
    def test_valid_output(self):
        out = "package:com.android.settings\npackage:com.daewoo.bloat\npackage:com.example.app"
        self.assertEqual(
            parse_pm_list_packages(out),
            ["com.android.settings", "com.daewoo.bloat", "com.example.app"],
        )

    def test_empty_string(self):
        self.assertEqual(parse_pm_list_packages(""), [])

    def test_none(self):
        self.assertEqual(parse_pm_list_packages(None), [])

    def test_malformed_lines_skipped(self):
        out = "garbage\npackage:com.valid.app\n:::bad\npackage:com.also.valid"
        self.assertEqual(
            parse_pm_list_packages(out),
            ["com.valid.app", "com.also.valid"],
        )

    def test_blank_lines_ignored(self):
        out = "\n\npackage:com.x\n\n"
        self.assertEqual(parse_pm_list_packages(out), ["com.x"])

    def test_injection_attempts_rejected(self):
        # Package names with shell metacharacters must be rejected
        out = "package:com.evil;rm -rf /\npackage:com.evil$(cmd)\npackage:com.evil`cmd`\npackage:com.evil|cmd"
        self.assertEqual(parse_pm_list_packages(out), [])

    def test_package_with_dots_and_underscores(self):
        out = "package:com.daewoo.smart_tv.v2"
        self.assertEqual(parse_pm_list_packages(out), ["com.daewoo.smart_tv.v2"])

    def test_package_with_hyphen(self):
        # Some OEM packages use hyphens (technically invalid Java but exist)
        out = "package:com.daewoo-my-app"
        self.assertEqual(parse_pm_list_packages(out), ["com.daewoo-my-app"])

    def test_package_starting_with_digit_rejected(self):
        out = "package:123.com.invalid"
        self.assertEqual(parse_pm_list_packages(out), [])

    def test_oversized_package_name_rejected(self):
        out = f"package:{'a' * 300}"
        self.assertEqual(parse_pm_list_packages(out), [])

    def test_single_segment_package(self):
        out = "package:android"
        self.assertEqual(parse_pm_list_packages(out), ["android"])

    def test_dollar_sign_in_package(self):
        # Inner classes use $ in package names
        out = "package:com.example.app$Inner"
        self.assertEqual(parse_pm_list_packages(out), ["com.example.app$Inner"])


class TestParseDisabled(unittest.TestCase):
    def test_same_as_all(self):
        out = "package:com.disabled.app\npackage:com.other"
        self.assertEqual(
            parse_pm_list_packages_disabled(out),
            ["com.disabled.app", "com.other"],
        )

    def test_none(self):
        self.assertEqual(parse_pm_list_packages_disabled(None), [])


class TestBuildInventory(unittest.TestCase):
    def test_all_enabled(self):
        inv = build_inventory("package:com.a\npackage:com.b")
        self.assertEqual(inv, {"com.a": "enabled", "com.b": "enabled"})

    def test_disabled_overrides_enabled(self):
        all_out = "package:com.a\npackage:com.b\npackage:com.c"
        disabled_out = "package:com.b"
        inv = build_inventory(all_out, disabled_out)
        self.assertEqual(inv["com.a"], "enabled")
        self.assertEqual(inv["com.b"], "disabled")
        self.assertEqual(inv["com.c"], "enabled")

    def test_empty_all(self):
        inv = build_inventory("")
        self.assertEqual(inv, {})

    def test_none_all(self):
        inv = build_inventory(None)
        self.assertEqual(inv, {})

    def test_none_disabled(self):
        inv = build_inventory("package:com.a", None)
        self.assertEqual(inv, {"com.a": "enabled"})

    def test_malformed_all(self):
        inv = build_inventory("garbage\nno packages here")
        self.assertEqual(inv, {})


class TestInventorySummary(unittest.TestCase):
    def test_empty(self):
        self.assertIn("vacío", inventory_summary({}))

    def test_mixed(self):
        inv = {"a": "enabled", "b": "enabled", "c": "disabled"}
        s = inventory_summary(inv)
        self.assertIn("3 paquetes", s)
        self.assertIn("2 enabled", s)
        self.assertIn("1 disabled", s)

    def test_only_disabled(self):
        inv = {"a": "disabled", "b": "disabled"}
        s = inventory_summary(inv)
        self.assertIn("0 enabled", s)
        self.assertIn("2 disabled", s)


if __name__ == "__main__":
    unittest.main()
