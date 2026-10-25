"""Tests for detect.manual_input (6 tests)."""
import unittest

from detect.manual_input import (
    ManualInputError,
    normalize_model,
    normalize_os,
    parse_manual_entry,
)


class TestNormalization(unittest.TestCase):
    def test_normalize_model_uppercase_strip(self):
        self.assertEqual(normalize_model("  55dm75qv "), "55DM75QV")
        self.assertEqual(normalize_model("55 DM75 QV"), "55 DM75 QV")
        self.assertIsNone(normalize_model("   "))
        self.assertIsNone(normalize_model(None))

    def test_normalize_os_spellings(self):
        self.assertEqual(normalize_os("Android TV"), "android-tv")
        self.assertEqual(normalize_os("google tv"), "google-tv")
        self.assertEqual(normalize_os("Vidaa"), "vidaa")
        self.assertIsNone(normalize_os(None))

    def test_normalize_os_unknown_raises(self):
        with self.assertRaises(ManualInputError):
            normalize_os("Tizen")


class TestParseManualEntry(unittest.TestCase):
    def test_valid_entry_is_likely(self):
        idn = parse_manual_entry("55DM75QV", "VIDAA", firmware="V5.0")
        self.assertEqual(idn.model, "55DM75QV")
        self.assertEqual(idn.os_family, "vidaa")
        self.assertEqual(idn.confidence, "likely")
        self.assertEqual(idn.firmware, "V5.0")

    def test_unknown_os_raises(self):
        with self.assertRaises(ManualInputError):
            parse_manual_entry("X", "WebOS")

    def test_firmware_optional(self):
        idn = parse_manual_entry(None, "Android TV")
        self.assertIsNone(idn.firmware)
        self.assertEqual(idn.os_family, "android-tv")

    def test_brand_only_is_failsafe(self):
        idn = parse_manual_entry(None, None)
        self.assertEqual(idn.os_family, "unknown")
        self.assertEqual(idn.confidence, "unknown")
        self.assertFalse(idn.conclusive)


if __name__ == "__main__":
    unittest.main()
