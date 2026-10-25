"""Tests for the FASE 4 dry-run planner (engine/planner.py).

Covers the safety gates: default-deny profile, non-conclusive identity,
missing inventory, critical exclusions, unknown candidates, already
disabled packages, reversibility, determinism and dry-run constancy.
"""
import unittest

from detect.identity import DeviceIdentity
from engine.planner import PlanError, build_plan, render_plan

ALLOWING_PROFILE = {
    "profile": "android-tv/generic",
    "os_family": "android-tv",
    "actions_allowed": True,
    "min_confidence": "conclusive",
    "critical_exclusions": {
        "packages": [
            "com.android.settings",
            "com.android.systemui",
            # Exclusion SOLO de perfil (no esta en la red nucleo):
            # permite probar que el motivo 'exclusion critica del perfil'
            # sigue existiendo aparte de la red nucleo dura.
            "com.example.profileonly",
        ],
    },
}

DENY_PROFILE = {"profile": "unsupported/default", "actions_allowed": False}

INVENTORY = {
    "com.example.ads": "enabled",
    "com.example.telemetry": "enabled",
    "com.example.already-off": "disabled",
    "com.android.settings": "enabled",
    "com.example.profileonly": "enabled",
}


def conclusive_identity() -> DeviceIdentity:
    return DeviceIdentity(
        os_family="android-tv",
        confidence="conclusive",
        model="55DM75QV",
        brand="Daewoo",
        sources=("adb",),
    )


def likely_identity() -> DeviceIdentity:
    return DeviceIdentity(
        os_family="android-tv",
        confidence="likely",
        model="55DM75QV",
        sources=("manual",),
    )


class PlanGatesTest(unittest.TestCase):
    def test_deny_profile_never_plans(self):
        with self.assertRaises(PlanError):
            build_plan(conclusive_identity(), DENY_PROFILE, INVENTORY, ["com.example.ads"])

    def test_missing_profile_never_plans(self):
        with self.assertRaises(PlanError):
            build_plan(conclusive_identity(), {}, INVENTORY, ["com.example.ads"])

    def test_likely_identity_never_plans(self):
        with self.assertRaises(PlanError):
            build_plan(likely_identity(), ALLOWING_PROFILE, INVENTORY, ["com.example.ads"])

    def test_unreliable_identity_never_plans(self):
        ident = DeviceIdentity(os_family="android-tv", confidence="unreliable")
        with self.assertRaises(PlanError):
            build_plan(ident, ALLOWING_PROFILE, INVENTORY, ["com.example.ads"])

    def test_missing_inventory_never_plans(self):
        with self.assertRaises(PlanError):
            build_plan(conclusive_identity(), ALLOWING_PROFILE, {}, ["com.example.ads"])

    def test_none_inventory_never_plans(self):
        with self.assertRaises(PlanError):
            build_plan(conclusive_identity(), ALLOWING_PROFILE, None, ["com.example.ads"])  # type: ignore[arg-type]


class PlanContentTest(unittest.TestCase):
    def test_valid_candidate_becomes_reversible_action(self):
        plan = build_plan(
            conclusive_identity(), ALLOWING_PROFILE, INVENTORY, ["com.example.ads"]
        )
        self.assertEqual(len(plan.actions), 1)
        action = plan.actions[0]
        self.assertEqual(action.package, "com.example.ads")
        self.assertEqual(action.command, "pm disable-user --user 0 com.example.ads")
        self.assertEqual(action.reversible_command, "pm enable --user 0 com.example.ads")
        self.assertEqual(action.state_before, "enabled")

    def test_dry_run_is_constant_true(self):
        plan = build_plan(conclusive_identity(), ALLOWING_PROFILE, INVENTORY, ["com.example.ads"])
        self.assertTrue(plan.dry_run)
        self.assertTrue(plan.to_dict()["dry_run"])

    def test_core_exclusion_is_skipped_with_reason(self):
        # Red nucleo dura: com.android.settings esta en CORE_EXCLUSIONS
        # (engine/planner.py) -> el motivo es 'exclusion nucleo' aunque el
        # perfil no la listara nunca.
        plan = build_plan(
            conclusive_identity(),
            ALLOWING_PROFILE,
            INVENTORY,
            ["com.android.settings", "com.example.ads"],
        )
        packages = [a.package for a in plan.actions]
        self.assertNotIn("com.android.settings", packages)
        self.assertIn("com.example.ads", packages)
        skipped = dict(plan.skipped)
        self.assertEqual(
            skipped["com.android.settings"],
            "exclusion nucleo (no perfil puede saltarla)",
        )

    def test_profile_critical_exclusion_is_skipped_with_reason(self):
        # Exclusion solo del perfil (no en la red nucleo): el motivo
        # 'exclusion critica del perfil' sigue vigente.
        plan = build_plan(
            conclusive_identity(),
            ALLOWING_PROFILE,
            INVENTORY,
            ["com.example.profileonly", "com.example.ads"],
        )
        packages = [a.package for a in plan.actions]
        self.assertNotIn("com.example.profileonly", packages)
        self.assertIn("com.example.ads", packages)
        skipped = dict(plan.skipped)
        self.assertEqual(
            skipped["com.example.profileonly"], "exclusion critica del perfil"
        )

    def test_core_exclusion_cannot_be_overridden_by_profile(self):
        # Un perfil que NO liste un paquete nucleo sigue sin poder
        # planearlo: la red nucleo es una red de seguridad dura que ningun
        # perfil puede saltarse (FASE 5.5, modelos nuevos).
        bare_profile = {
            "profile": "android-tv/generic",
            "os_family": "android-tv",
            "actions_allowed": True,
            "min_confidence": "conclusive",
            "critical_exclusions": {"packages": []},
        }
        inventory_with_core = dict(INVENTORY, **{"com.android.bluetooth": "enabled"})
        plan = build_plan(
            conclusive_identity(),
            bare_profile,
            inventory_with_core,
            ["com.android.bluetooth"],
        )
        self.assertEqual(plan.actions, ())
        self.assertEqual(
            dict(plan.skipped)["com.android.bluetooth"],
            "exclusion nucleo (no perfil puede saltarla)",
        )

    def test_core_exclusion_prefix_is_skipped(self):
        # Prefijos nucleo (familias enteras): com.android.providers.* y
        # com.android.networkstack.* estan protegidos por prefijo.
        bare_profile = {
            "profile": "android-tv/generic",
            "os_family": "android-tv",
            "actions_allowed": True,
            "min_confidence": "conclusive",
            "critical_exclusions": {"packages": []},
        }
        inventory_with_prefix = dict(INVENTORY, **{"com.android.providers.foo": "enabled"})
        plan = build_plan(
            conclusive_identity(),
            bare_profile,
            inventory_with_prefix,
            ["com.android.providers.foo"],
        )
        self.assertEqual(plan.actions, ())
        self.assertEqual(
            dict(plan.skipped)["com.android.providers.foo"],
            "exclusion nucleo (no perfil puede saltarla)",
        )

    def test_unknown_candidate_is_skipped_not_planned(self):
        plan = build_plan(
            conclusive_identity(),
            ALLOWING_PROFILE,
            INVENTORY,
            ["com.example.not-on-device"],
        )
        self.assertEqual(plan.actions, ())
        skipped = dict(plan.skipped)
        self.assertEqual(
            skipped["com.example.not-on-device"], "no presente en el inventario del dispositivo"
        )

    def test_already_disabled_is_skipped(self):
        plan = build_plan(
            conclusive_identity(), ALLOWING_PROFILE, INVENTORY, ["com.example.already-off"]
        )
        self.assertEqual(plan.actions, ())
        skipped = dict(plan.skipped)
        self.assertEqual(skipped["com.example.already-off"], "ya deshabilitado en el inventario")

    def test_duplicates_and_blank_candidates_are_ignored(self):
        plan = build_plan(
            conclusive_identity(),
            ALLOWING_PROFILE,
            INVENTORY,
            ["com.example.ads", "com.example.ads", "  ", "com.example.telemetry"],
        )
        packages = [a.package for a in plan.actions]
        self.assertEqual(packages, ["com.example.ads", "com.example.telemetry"])

    def test_plan_is_deterministic_sorted(self):
        args = (conclusive_identity(), ALLOWING_PROFILE, INVENTORY,
                ["com.example.telemetry", "com.example.ads"])
        first = build_plan(*args)
        second = build_plan(*args)
        self.assertEqual(first, second)
        self.assertEqual([a.package for a in first.actions],
                         ["com.example.ads", "com.example.telemetry"])

    def test_render_contains_no_execution_and_lists_actions(self):
        plan = build_plan(
            conclusive_identity(),
            ALLOWING_PROFILE,
            INVENTORY,
            ["com.example.ads", "com.android.systemui"],
        )
        text = render_plan(plan)
        self.assertIn("DRY-RUN", text)
        self.assertIn("pm disable-user --user 0 com.example.ads", text)
        self.assertIn("pm enable --user 0 com.example.ads", text)
        self.assertIn("com.android.systemui", text)


if __name__ == "__main__":
    unittest.main()
