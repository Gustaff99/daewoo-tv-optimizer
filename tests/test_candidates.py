"""Tests de detect/candidates.py (FASE 5.5): deteccion de candidatos.

Comportamiento esperado (conservador, opt-in):
- Sin `candidates` ni `candidate_discovery` en el perfil -> sin candidatos.
- `candidates` curado (perfil de modelo) -> unica fuente, filtrada por el
  inventario real.
- `candidate_discovery` (opt-in) -> known_packages presentes en el
  inventario + patrones estrechos (CTS, *.demo) + patrones extra del perfil.
- Inputs invalidos -> [] (fail-safe: nunca crash, nunca habilita).
"""
import unittest

from detect.candidates import discover_candidates, reason_for

INVENTORY = {
    "com.google.android.play.games": "enabled",
    "com.google.android.gms": "enabled",
    "com.example.demo": "enabled",
    "com.android.cts.priv.ctsshim": "enabled",
    "com.android.systemui": "enabled",
    "com.example.app": "enabled",
}


class TestDiscoverCandidates(unittest.TestCase):
    def test_empty_profile_no_candidates(self):
        # Sin opt-in explícito no hay deteccion: plan vacio, nunca "a ojo".
        self.assertEqual(discover_candidates(INVENTORY, {}), [])

    def test_non_mapping_inputs_fail_safe(self):
        self.assertEqual(discover_candidates(None, {}), [])
        self.assertEqual(discover_candidates(INVENTORY, None), [])

    def test_explicit_candidates_are_only_source(self):
        # Perfil de modelo curado: su lista es la unica fuente, aunque el
        # inventario tenga otro bloatware detectable por patrones.
        prof = {"candidates": [{"package": "com.example.app", "reason": "r"}]}
        self.assertEqual(discover_candidates(INVENTORY, prof), ["com.example.app"])

    def test_explicit_candidates_filtered_by_inventory(self):
        prof = {"candidates": ["com.not.present", "com.example.demo"]}
        self.assertEqual(discover_candidates(INVENTORY, prof), ["com.example.demo"])

    def test_discovery_known_packages_filtered(self):
        # known_packages se filtra por inventario (com.not.present se descarta);
        # los patrones estrechos por defecto (CTS, .demo) se suman igualmente.
        prof = {
            "candidate_discovery": {
                "known_packages": [
                    {"package": "com.google.android.play.games"},
                    {"package": "com.not.present"},
                    {"nope": True},
                ]
            }
        }
        self.assertEqual(
            discover_candidates(INVENTORY, prof),
            [
                "com.android.cts.priv.ctsshim",
                "com.example.demo",
                "com.google.android.play.games",
            ],
        )

    def test_discovery_known_packages_only_no_patterns(self):
        # Con known_packages pero sin patrones por defecto desactivables:
        # usamos un inventario sin CTS ni .demo para aislar known_packages.
        inv = {"com.google.android.play.games": "enabled", "com.android.systemui": "enabled"}
        prof = {
            "candidate_discovery": {
                "known_packages": ["com.google.android.play.games", "com.not.present"]
            }
        }
        self.assertEqual(discover_candidates(inv, prof), ["com.google.android.play.games"])

    def test_discovery_default_patterns(self):
        # Con opt-in, los patrones estrechos por defecto aplican sobre el
        # inventario real: CTS y app demo.
        prof = {"candidate_discovery": {"known_packages": []}}
        self.assertEqual(
            discover_candidates(INVENTORY, prof),
            ["com.android.cts.priv.ctsshim", "com.example.demo"],
        )

    def test_discovery_extra_patterns_and_bad_regex_ignored(self):
        prof = {
            "candidate_discovery": {
                "known_packages": [],
                "patterns": [
                    {"regex": "^com\\.example\\.app$", "reason": "app de test"},
                    {"regex": "([", "reason": "regex invalido"},
                    {"nope": True},
                ],
            }
        }
        self.assertEqual(
            discover_candidates(INVENTORY, prof),
            ["com.android.cts.priv.ctsshim", "com.example.app", "com.example.demo"],
        )

    def test_no_opt_in_no_patterns(self):
        # actions_allowed sin candidate_discovery no activa patrones.
        self.assertEqual(discover_candidates(INVENTORY, {"actions_allowed": True}), [])


class TestReasonFor(unittest.TestCase):
    def test_explicit_reason_wins(self):
        prof = {
            "candidates": [{"package": "com.example.demo", "reason": "motivo propio"}]
        }
        self.assertEqual(reason_for("com.example.demo", prof), "motivo propio")

    def test_known_bloatware_reason(self):
        prof = {
            "candidate_discovery": {
                "known_packages": [{"package": "com.google.android.play.games"}]
            }
        }
        self.assertIn(
            "Google Play Games", reason_for("com.google.android.play.games", prof)
        )

    def test_profile_discovery_reason(self):
        prof = {
            "candidate_discovery": {
                "known_packages": [
                    {"package": "com.google.android.katniss", "reason": "telemetria propia"}
                ]
            }
        }
        self.assertEqual(reason_for("com.google.android.katniss", prof), "telemetria propia")

    def test_pattern_reason(self):
        prof = {"candidate_discovery": {"known_packages": []}}
        self.assertIn("demo", reason_for("com.example.demo", prof).lower())

    def test_fallback_reason(self):
        self.assertEqual(reason_for("com.example.thing", {}), "candidato del perfil")


if __name__ == "__main__":
    unittest.main()
