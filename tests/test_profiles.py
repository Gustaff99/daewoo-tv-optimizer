"""Tests for detect.profiles: on-disk loading, fail-safe validation,
confidence gate (7 tests)."""
import json
import tempfile
import unittest
from pathlib import Path

from detect.identity import (
    identity_from_adb,
    identity_from_manual,
    profile_allows_actions,
    resolve_profile,
)
from detect.profiles import (
    CONFIDENCE_RANK,
    default_profiles_dir,
    load_profiles,
)


class TestLoader(unittest.TestCase):
    def test_package_profiles_load(self):
        profiles, default_profile = load_profiles()
        self.assertIn("android-tv", profiles)
        self.assertIn("vidaa", profiles)
        self.assertIn("tivo", profiles)
        # FASE 7: familia AOSP + perfil de modelo validado en dispositivo real.
        self.assertIn("aosp-uncertified", profiles)
        self.assertIn("D43DM55UQPMS", profiles)
        self.assertFalse(profile_allows_actions(default_profile))
        self.assertEqual(default_profile["profile"], "unsupported/default")
        # The only action-allowing profiles demand conclusive evidence.
        self.assertEqual(profiles["android-tv"]["min_confidence"], "conclusive")
        self.assertEqual(
            profiles["D43DM55UQPMS"]["min_confidence"], "conclusive"
        )
        self.assertTrue(profile_allows_actions(profiles["D43DM55UQPMS"]))
        # FASE 5.5: la familia AOSP genérica SÍ permite acciones, pero con
        # lista conservadora de bloatware universal, evidencia ADB concluyente
        # obligatoria y la red nucleo dura del planner (no saltable por perfil).
        # Antes (FASE 3-7) era identificacion-solo; el cambio de politica esta
        # justificado en profiles/aosp-tv/generic.json (evidence + safety).
        self.assertTrue(profile_allows_actions(profiles["aosp-uncertified"]))
        self.assertEqual(
            profiles["aosp-uncertified"]["min_confidence"], "conclusive"
        )
        self.assertEqual(
            profiles["D43DM55UQPMS"]["adb_match"], {"firmware": "My/EMIR/shandao"}
        )

    def test_google_tv_family_profile_loads(self):
        # FASE 5.5: la familia Google TV tiene su propio perfil generico
        # (antes caia al fail-safe unsupported/default).
        profiles, _ = load_profiles()
        self.assertIn("google-tv", profiles)
        prof = profiles["google-tv"]
        self.assertEqual(prof["profile"], "google-tv/generic")
        self.assertTrue(profile_allows_actions(prof))
        self.assertEqual(prof["min_confidence"], "conclusive")
        self.assertIn("candidate_discovery", prof)
        self.assertIn("critical_exclusions", prof)

    def test_google_tv_identity_resolves_to_family_profile(self):
        # Modelo Google TV nuevo (no en la matriz) -> perfil generico de la
        # familia con acciones permitidas y deteccion de candidatos.
        profiles, _ = load_profiles()
        ident = identity_from_adb(
            ["com.google.tv", "com.google.android.gms"],
            model="DW50S",
            os_version="13",
        )
        self.assertEqual(ident.os_family, "google-tv")
        self.assertTrue(ident.conclusive)
        prof = resolve_profile(
            ident,
            profiles,
            {"profile": "unsupported/default", "actions_allowed": False},
        )
        self.assertEqual(prof["profile"], "google-tv/generic")
        self.assertTrue(profile_allows_actions(prof))

    def test_invalid_files_are_skipped_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad").mkdir()
            (root / "bad" / "broken.json").write_text("{not json", encoding="utf-8")
            (root / "bad" / "no_actions.json").write_text(
                json.dumps({"profile": "x/y"}), encoding="utf-8"
            )
            (root / "ok").mkdir()
            (root / "ok" / "good.json").write_text(
                json.dumps(
                    {
                        "profile": "ok/good",
                        "os_family": "vidaa",
                        "actions_allowed": False,
                    }
                ),
                encoding="utf-8",
            )
            profiles, default_profile = load_profiles(root)
            self.assertIn("vidaa", profiles)
            self.assertFalse(profile_allows_actions(default_profile))

    def test_model_key_registered_and_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m").mkdir()
            (root / "m" / "p.json").write_text(
                json.dumps(
                    {
                        "profile": "m/p",
                        "os_family": "android-tv",
                        "models": ["dw43s"],
                        "actions_allowed": True,
                        "min_confidence": "conclusive",
                    }
                ),
                encoding="utf-8",
            )
            profiles, _ = load_profiles(root)
            self.assertIn("DW43S", profiles)
            ident = identity_from_adb(
                ["com.google.android.tv"], model="dw43s"
            )
            prof = resolve_profile(ident, profiles, {"profile": "unsupported/default", "actions_allowed": False})
            self.assertEqual(prof["profile"], "m/p")


class TestConfidenceGate(unittest.TestCase):
    def setUp(self):
        self.profiles, self.default = load_profiles()

    def test_manual_likely_never_reaches_action_profile(self):
        # User-typed "Android TV" is only 'likely' -> must fall to fail-safe.
        ident = identity_from_manual("D55DM54UAMSX", "android-tv")
        self.assertEqual(ident.confidence, "likely")
        prof = resolve_profile(ident, self.profiles, self.default)
        self.assertFalse(profile_allows_actions(prof))
        self.assertEqual(prof["profile"], "unsupported/default")

    def test_adb_conclusive_reaches_action_profile(self):
        ident = identity_from_adb(["com.google.android.tv"], model="D55DM54UAMSX")
        self.assertEqual(ident.confidence, "conclusive")
        prof = resolve_profile(ident, self.profiles, self.default)
        self.assertTrue(profile_allows_actions(prof))
        self.assertEqual(prof["profile"], "android-tv/generic")
        self.assertTrue(prof["safety"]["dry_run_by_default"])

    def test_adb_aosp_real_fingerprint_resolves_model_profile(self):
        # FASE 7: identidad ADB concluyente del dispositivo real
        # D43DM55UQPMS -> perfil de modelo con acciones permitidas.
        ident = identity_from_adb(
            packages=["com.google.android.tvlauncher", "com.netflix.ninja"],
            model="D43DM55UQPMS",
            os_version="11",
            firmware="My/EMIR/shandao:11/RTM3.211215.317/8963041:user/release-keys",
        )
        self.assertEqual(ident.os_family, "aosp-uncertified")
        prof = resolve_profile(ident, self.profiles, self.default)
        self.assertEqual(prof["profile"], "aosp-tv/daewoo-d43dm55uqpms")
        self.assertTrue(profile_allows_actions(prof))
        self.assertEqual(prof["min_confidence"], "conclusive")

    def test_adb_aosp_without_match_stays_family_only(self):
        # Mismo SO, fingerprint distinto: familia conservadora sin acciones.
        ident = identity_from_adb(
            packages=["com.example.app"],
            model="OTRA-TV",
            os_version="11",
            firmware="OtroOEM/plataforma:11/x:user/release-keys",
        )
        prof = resolve_profile(ident, self.profiles, self.default)
        self.assertEqual(prof["profile"], "aosp-tv/generic")
        # FASE 5.5: el perfil generico de familia permite acciones
        # conservadoras (lista universal filtrada en el inventario real +
        # exclusiones nucleo), SOLO con evidencia ADB concluyente.
        self.assertTrue(profile_allows_actions(prof))

    def test_proprietary_profile_allows_nothing(self):
        ident = identity_from_manual("55DM75QV", "vidaa")
        prof = resolve_profile(ident, self.profiles, self.default)
        self.assertEqual(prof["profile"], "proprietary/vidaa")
        self.assertFalse(profile_allows_actions(prof))

    def test_unknown_identity_failsafe(self):
        ident = identity_from_manual(None, None)
        prof = resolve_profile(ident, self.profiles, self.default)
        self.assertFalse(profile_allows_actions(prof))

    def test_confidence_rank_ordering(self):
        self.assertGreater(
            CONFIDENCE_RANK["conclusive"], CONFIDENCE_RANK["likely"]
        )
        self.assertGreater(CONFIDENCE_RANK["likely"], CONFIDENCE_RANK["unreliable"])
        self.assertGreater(
            CONFIDENCE_RANK["unreliable"], CONFIDENCE_RANK["unknown"]
        )

    def test_default_deny_for_empty_profile(self):
        self.assertFalse(profile_allows_actions({}))
        self.assertFalse(profile_allows_actions({"actions_allowed": None}))


class TestCliWithProfiles(unittest.TestCase):
    def test_cli_vidaa_resolves_to_proprietary_profile(self):
        from detect.cli import main
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--model", "55DM75QV", "--os", "VIDAA"])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["profile"], "proprietary/vidaa")
        self.assertFalse(data["actions_allowed"])


if __name__ == "__main__":
    unittest.main()
