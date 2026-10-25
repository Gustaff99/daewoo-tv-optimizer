"""Dry-run plan builder (FASE 4).

Safety model (mirrors the profile policy, enforced in code):

- No plan without a profile that allows actions (default-deny gate).
- No plan without a CONCLUSIVE identity (ADB on-device or official page).
  Manual input ("likely") can never reach the planner: the identity gate
  rejects it before any package is considered.
- No plan without an initial package inventory (FASE 6 requirement).
- Only reversible `pm disable-user --user 0 <pkg>` actions are generated;
  uninstall, root and firmware modification are not representable here.
- Critical exclusions (profile `critical_exclusions.packages`) are always
  skipped and recorded with a reason.
- Candidates missing from the inventory are skipped and recorded: the
  plan only touches packages that were actually observed on the device.
- The plan is dry-run by construction: `dry_run` is a constant True and
  there is no code path that clears it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence, Tuple

from detect.identity import DeviceIdentity
from detect.profiles import CONFIDENCE_RANK

# Hard safety net (defense in depth): packages that NO profile may ever
# propose for disabling, regardless of its critical_exclusions list. This
# encodes the mission's non-negotiable list (boot, launcher, settings,
# connectivity, remote control, media/DRM, updates, core platform)
# directly in code so a bad or too-permissive profile file can never
# disable an essential component. Checked in addition to the profile's
# own exclusions; a hit is recorded with reason "exclusion nucleo".
CORE_EXCLUSIONS: frozenset = frozenset(
    {
        # Launcher / interfaz principal
        "com.android.systemui",
        "com.android.tv",
        "com.google.android.tv",
        "com.google.tv",
        "com.google.android.tvlauncher",
        "com.android.tv.settings",
        # Ajustes del dispositivo
        "com.android.settings",
        "com.android.settings.intelligence",
        # Arranque y primer arranque
        "com.google.android.setupwizard",
        "com.google.android.onetimeinitializer",
        "com.android.certinstaller",
        # Conectividad: wifi, bluetooth, network stack, vpn, hotspot
        "com.android.bluetooth",
        "com.android.networkstack.inprocess",
        "com.android.networkstack.tethering.inprocess",
        "com.android.vpndialogs",
        "com.android.hotspot2.osulogin",
        "com.android.captiveportallogin",
        "com.android.wifi.resources",
        "com.android.localtransport",
        "com.android.pacprocessor",
        "com.android.proxyhandler",
        # Provedores de datos esenciales
        "com.android.providers.settings",
        "com.android.providers.media",
        "com.android.providers.media.module",
        "com.android.providers.calendar",
        "com.android.providers.contacts",
        "com.android.providers.tv",
        "com.android.providers.downloads",
        "com.android.providers.userdictionary",
        # Plataforma Google esencial
        "com.google.android.gms",
        "com.google.android.gsf",
        "com.google.android.vending",
        "com.google.android.permissioncontroller",
        "com.google.android.packageinstaller",
        "com.google.android.webview",
        "com.google.android.tts",
        "com.google.android.inputmethod.latin",
        # Seguridad y sistema
        "com.android.keychain",
        "com.android.se",
        "com.android.shell",
        "com.android.dynsystem",
        "com.android.inputdevices",
        "android",
    }
)

# Prefixes that are always core (whole families, not single packages).
CORE_EXCLUSION_PREFIXES: tuple = (
    "com.android.providers.",
    "com.android.networkstack.",
)


def is_core_excluded(package: str) -> bool:
    """True if the package is part of the hard core-exclusion net."""
    if not isinstance(package, str):
        return True  # fail-safe: un nombre invalido nunca se toca
    return package in CORE_EXCLUSIONS or any(
        package.startswith(pfx) for pfx in CORE_EXCLUSION_PREFIXES
    )


class PlanError(Exception):
    """Raised whenever a plan cannot be built safely. Fail-safe: stop."""


@dataclass(frozen=True)
class PlanAction:
    """One reversible action in the plan."""

    package: str
    command: str
    reversible_command: str
    state_before: str


@dataclass(frozen=True)
class ExecutionPlan:
    profile_id: str
    model: Optional[str]
    os_family: str
    dry_run: bool
    actions: Tuple[PlanAction, ...] = field(default_factory=tuple)
    skipped: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile_id,
            "model": self.model,
            "os_family": self.os_family,
            "dry_run": self.dry_run,
            "actions": [
                {
                    "package": a.package,
                    "command": a.command,
                    "reversible_command": a.reversible_command,
                    "state_before": a.state_before,
                }
                for a in self.actions
            ],
            "skipped": [{"package": p, "reason": r} for p, r in self.skipped],
        }


def _excluded_packages(profile: Mapping) -> set:
    """The profile's own critical exclusions (see docstring, FASE 4).

    The hard CORE_EXCLUSIONS net is NOT merged here: it is enforced
    separately in build_plan via is_core_excluded(), so prefix-based core
    families (e.g. com.android.providers.*) are also protected. A profile
    cannot re-enable a core package by omitting it from its own list.
    """
    crit = profile.get("critical_exclusions")
    if not isinstance(crit, Mapping):
        return set()
    pkgs = crit.get("packages")
    if not isinstance(pkgs, list):
        return set()
    return {p for p in pkgs if isinstance(p, str) and p.strip()}


def build_plan(
    identity: DeviceIdentity,
    profile: Mapping,
    inventory: Mapping[str, str],
    candidates: Sequence[str],
) -> ExecutionPlan:
    """Build a dry-run plan. Raises PlanError on any safety violation.

    `inventory` maps package -> observed state (e.g. "enabled", "disabled").
    `candidates` are the packages proposed for optimization (from the
    research layer); only those present in the inventory and not excluded
    become actions.
    """
    # Gate 1: profile must allow actions (default-deny otherwise).
    if not isinstance(profile, Mapping) or profile.get("actions_allowed") is not True:
        raise PlanError("perfil no permite acciones (default-deny); no se genera plan")

    # Gate 2: identity must be conclusive.
    if CONFIDENCE_RANK.get(identity.confidence, 0) < CONFIDENCE_RANK["conclusive"]:
        raise PlanError(
            "identidad no concluyente "
            f"({identity.confidence!r}); fail-safe: no se modifica nada"
        )

    # Gate 3: initial inventory is mandatory (FASE 6).
    if not isinstance(inventory, Mapping) or not inventory:
        raise PlanError("falta inventario inicial de paquetes; fail-safe: sin plan")

    # Gate 4: candidates must be a sequence (None is a caller bug, not empty).
    if candidates is None:
        raise PlanError("lista de candidatos nula; fail-safe: sin plan")

    excluded = _excluded_packages(profile)
    actions: list[PlanAction] = []
    skipped: list[tuple[str, str]] = []

    seen = set()
    for raw in candidates:
        pkg = raw.strip()
        if not pkg or pkg in seen:
            continue
        seen.add(pkg)

        if is_core_excluded(pkg):
            # Red nucleo dura: ni un perfil demasiado permisivo puede
            # saltarla (incluye familias enteras por prefijo).
            skipped.append((pkg, "exclusion nucleo (no perfil puede saltarla)"))
            continue
        if pkg in excluded:
            skipped.append((pkg, "exclusion critica del perfil"))
            continue
        if pkg not in inventory:
            skipped.append((pkg, "no presente en el inventario del dispositivo"))
            continue

        state = str(inventory[pkg])
        if state == "disabled":
            skipped.append((pkg, "ya deshabilitado en el inventario"))
            continue

        actions.append(
            PlanAction(
                package=pkg,
                command=f"pm disable-user --user 0 {pkg}",
                reversible_command=f"pm enable --user 0 {pkg}",
                state_before=state,
            )
        )

    actions.sort(key=lambda a: a.package)
    skipped.sort()
    return ExecutionPlan(
        profile_id=str(profile.get("profile", "?")),
        model=identity.model,
        os_family=identity.os_family,
        dry_run=True,
        actions=tuple(actions),
        skipped=tuple(skipped),
    )


def render_plan(plan: ExecutionPlan) -> str:
    """Human-readable dry-run rendering (no execution)."""
    lines = [
        f"PLAN DRY-RUN (no se ejecuta nada) — perfil {plan.profile_id}",
        f"modelo: {plan.model or '?'} | familia SO: {plan.os_family}",
    ]
    if plan.actions:
        lines.append("acciones propuestas (reversibles):")
        for a in plan.actions:
            lines.append(f"  - {a.package}: {a.command}")
            lines.append(f"    estado antes: {a.state_before} | reversión: {a.reversible_command}")
    else:
        lines.append("sin acciones propuestas")
    if plan.skipped:
        lines.append("omitidos:")
        for pkg, reason in plan.skipped:
            lines.append(f"  - {pkg}: {reason}")
    return "\n".join(lines)
