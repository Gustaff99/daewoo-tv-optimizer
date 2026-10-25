"""Tests for detect.identity."""
import unittest

from detect.identity import (
    CONFIDENCE_LEVELS,
    DeviceIdentity,
    IdentityError,
    identity_from_adb,
    identity_from_manual,
    identity_from_official_page,
    profile_allows_actions,
    resolve_profile,
)

DEFAULT = {"profile": "unsupported/default", "actions_allowed": False}


class TestIdentityFailSafe(unittest.TestCase):
    def test_brand_alone_is_unknown(self):
        idn = identity_from_manual(None, None)
        self.assertEqual(idn.os_family, "unknown")
        self.assertEqual(idn.confidence, "unknown")
        self.assertFalse(idn.conclusive)

    def test_model_only_is_unreliable(self):
        idn = identity_from_manual("55DM75QV", None)
        self.assertEqual(idn.confidence, "unreliable")
        self.assertEqual(idn.os_family, "unknown")

    def test_manual_input_never_conclusive(self):
        idn = identity_from_manual("55DM75QV", "vidaa")
        self.assertEqual(idn.confidence, "likely")
        self.assertFalse(idn.conclusive)

    def test_unsupported_profile_forbids_actions(self):
        self.assertFalse(profile_allows_actions(DEFAULT))
        self.assertFalse(profile_allows_actions({}))
        self.assertFalse(profile_allows_actions({"actions_allowed": None}))

    def test_invalid_confidence_rejected(self):
        with self.assertRaises(IdentityError):
            DeviceIdentity(os_family="vidaa", confidence="certain")

    def test_invalid_os_family_rejected(self):
        with self.assertRaises(IdentityError):
            DeviceIdentity(os_family="harmonyos", confidence="likely")


class TestResolution(unittest.TestCase):
    def test_adb_package_resolves_os_first(self):
        idn = identity_from_adb(
            packages=["com.google.android.tv", "com.example.app"],
            model="43DE6500",
            os_version="13",
        )
        self.assertEqual(idn.os_family, "android-tv")
        self.assertEqual(idn.confidence, "conclusive")
        self.assertTrue(idn.conclusive)

    def test_adb_google_tv_package(self):
        idn = identity_from_adb(packages=["com.google.tv"])
        self.assertEqual(idn.os_family, "google-tv")

    def test_adb_no_platform_package_is_unknown(self):
        idn = identity_from_adb(packages=["com.example.app"], model="X")
        self.assertEqual(idn.os_family, "unknown")
        self.assertFalse(idn.conclusive)


class TestAospUncertified(unittest.TestCase):
    def test_android_build_without_tv_platform_is_aosp(self):
        # Evidencia real del dispositivo D43DM55UQPMS (FASE 7):
        # ro.build.version.release=11, fingerprint Vestel EMIR/shandao,
        # sin com.google.android.tv ni com.google.tv.
        idn = identity_from_adb(
            packages=["com.google.android.tvlauncher", "com.example.app"],
            model="D43DM55UQPMS",
            os_version="11",
            firmware="My/EMIR/shandao:11/RTM3.211215.317/8963041:user/release-keys",
        )
        self.assertEqual(idn.os_family, "aosp-uncertified")
        self.assertEqual(idn.confidence, "conclusive")
        self.assertTrue(idn.conclusive)

    def test_no_android_evidence_stays_unknown(self):
        idn = identity_from_adb(packages=["com.example.app"], model="X")
        self.assertEqual(idn.os_family, "unknown")
        self.assertFalse(idn.conclusive)

    def test_certified_platform_still_wins_over_aosp(self):
        idn = identity_from_adb(
            packages=["com.google.android.tv"],
            model="M",
            os_version="13",
            firmware="google/ristretto:13/...:user/release-keys",
        )
        self.assertEqual(idn.os_family, "android-tv")


class TestAdbMatchResolution(unittest.TestCase):
    """adb_match: vinculacion de perfil por evidencia de dispositivo."""

    def setUp(self):
        self.profiles = {
            "D43DM55UQPMS": {
                "profile": "aosp-tv/daewoo-d43dm55uqpms",
                "actions_allowed": True,
                "min_confidence": "conclusive",
                "models": ["D43DM55UQPMS"],
                "adb_match": {"firmware": "My/EMIR/shandao"},
            },
            "aosp-uncertified": {
                "profile": "aosp-tv/generic",
                "actions_allowed": False,
                "min_confidence": "conclusive",
            },
        }
        self.default = {"profile": "unsupported/default", "actions_allowed": False}

    def test_firmware_prefix_binds_model_profile(self):
        idn = identity_from_adb(
            packages=["com.example.app"],
            model="D43DM55UQPMS",
            os_version="11",
            firmware="My/EMIR/shandao:11/RTM3.211215.317/8963041:user/release-keys",
        )
        prof = resolve_profile(idn, self.profiles, self.default)
        self.assertEqual(prof["profile"], "aosp-tv/daewoo-d43dm55uqpms")
        self.assertTrue(profile_allows_actions(prof))

    def test_wrong_firmware_falls_to_family(self):
        idn = identity_from_adb(
            packages=["com.example.app"],
            model="OTHER-TV",
            os_version="11",
            firmware="OtherOEM/platform:11/x:user/release-keys",
        )
        prof = resolve_profile(idn, self.profiles, self.default)
        self.assertEqual(prof["profile"], "aosp-tv/generic")
        self.assertFalse(profile_allows_actions(prof))

    def test_partial_evidence_never_binds(self):
        # Sin firmware observado no puede haber adb_match: fail-safe a familia.
        idn = identity_from_adb(
            packages=["com.example.app"],
            model="OTHER-TV",
            os_version="11",
        )
        prof = resolve_profile(idn, self.profiles, self.default)
        self.assertEqual(prof["profile"], "aosp-tv/generic")

    def test_low_confidence_never_binds_action_profile(self):
        idn = DeviceIdentity(
            os_family="aosp-uncertified",
            confidence="likely",
            model="OTHER-TV",
            firmware="My/EMIR/shandao:11/x:user/release-keys",
            sources=("manual",),
        )
        prof = resolve_profile(idn, self.profiles, self.default)
        self.assertFalse(profile_allows_actions(prof))

    def test_malformed_adb_match_never_binds(self):
        bad = dict(self.profiles)
        bad["D43DM55UQPMS"] = {
            "profile": "aosp-tv/daewoo-d43dm55uqpms",
            "actions_allowed": True,
            "min_confidence": "conclusive",
            "adb_match": {"firmware": ""},
        }
        idn = identity_from_adb(
            packages=["com.example.app"],
            model="OTHER-TV",
            os_version="11",
            firmware="My/EMIR/shandao:11/x:user/release-keys",
        )
        prof = resolve_profile(idn, bad, self.default)
        self.assertEqual(prof["profile"], "aosp-tv/generic")

    def test_official_page_os_is_conclusive(self):
        idn = identity_from_official_page("vidaa", model="55DM75QV")
        self.assertEqual(idn.os_family, "vidaa")
        self.assertEqual(idn.confidence, "conclusive")
        self.assertEqual(idn.brand, "daewoo")

    def test_official_page_requires_concrete_os(self):
        with self.assertRaises(IdentityError):
            identity_from_official_page("unknown")

    def test_identity_to_dict_roundtrip(self):
        idn = identity_from_official_page("vidaa", model="55DM75QV")
        d = idn.to_dict()
        self.assertEqual(d["os_family"], "vidaa")
        self.assertIn("adb" if False else "official-page", d["sources"])
        self.assertIsInstance(d["sources"], list)
        self.assertTrue(d["conclusive"])
        self.assertEqual(d["confidence"], "conclusive")


class TestProfileResolution(unittest.TestCase):
    def setUp(self):
        self.profiles = {
            "55DM75QV": {"profile": "proprietary/55dm75qv", "actions_allowed": False},
            "android-tv": {"profile": "android-tv/generic", "actions_allowed": True},
        }

    def test_exact_model_match(self):
        idn = identity_from_official_page("vidaa", model="55DM75QV")
        prof = resolve_profile(idn, self.profiles, DEFAULT)
        self.assertEqual(prof["profile"], "proprietary/55dm75qv")

    def test_model_match_case_insensitive(self):
        idn = identity_from_official_page("vidaa", model=" 55dm75qv ")
        prof = resolve_profile(idn, self.profiles, DEFAULT)
        self.assertEqual(prof["profile"], "proprietary/55dm75qv")

    def test_os_family_fallback(self):
        idn = identity_from_adb(packages=["com.google.android.tv"], model="UNKNOWN-X")
        prof = resolve_profile(idn, self.profiles, DEFAULT)
        self.assertEqual(prof["profile"], "android-tv/generic")

    def test_default_fallback(self):
        idn = identity_from_manual("Mystery", "vidaa")
        prof = resolve_profile(idn, self.profiles, DEFAULT)
        self.assertEqual(prof["profile"], "unsupported/default")
        self.assertFalse(profile_allows_actions(prof))


if __name__ == "__main__":
    unittest.main()
