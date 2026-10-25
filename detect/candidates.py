"""Generic bloatware candidate discovery for NEW models (no profile).

Problem solved: a TV model that is not in the compatibility matrix and has
no model-specific profile used to produce an EMPTY plan, forcing the user
to know package names by hand. Now the OS-family generic profiles ship a
conservative `candidate_discovery` section and this module proposes
candidates from the REAL inventory.

Sources of candidates (conservative, in strict priority order):

1. The profile's explicit `candidates` list. When a model-specific
   profile curates its own list, that list is the ONLY source (highest
   priority, no patterns). Validated models keep their curated plans.
2. Otherwise, the profile's `candidate_discovery` section (opt-in):
   - `known_packages`: universal bloatware observed across Android TV /
     Google TV / AOSP TV builds (Google Play Games, feedback app, katniss
     bugreporter, CTS test shims), filtered to packages ACTUALLY present
     in the device inventory.
   - `patterns` (optional): extra narrow regexes the profile may add.
     The module's default narrow patterns (CTS test packages, OEM
     `*.demo` demo apps) always apply when the section is present.
3. A profile with NEITHER `candidates` NOR `candidate_discovery` yields
   NO candidates (empty plan). No discovery without an explicit opt-in.

Safety: this module only PROPOSES. Every proposal is still filtered by
the planner's gates: profile `actions_allowed`, conclusive identity,
inventory presence, profile `critical_exclusions` AND the hard
`engine.planner.CORE_EXCLUSIONS` net. A proposal that hits any gate is
skipped and logged, never executed.

Conservadurismo: la lista conocida es corta a propósito. Mejor proponer
poco y seguro que mucho y arriesgado. Los perfiles de modelo validados
(como aosp-tv/daewoo-d43dm55uqpms) siguen teniendo prioridad con su
lista propia.
"""
from __future__ import annotations

import re
from typing import List, Mapping, Sequence, Tuple

# Universal bloatware: present (or common) on Android TV / Google TV /
# AOSP TV builds and unambiguously non-essential. Each entry is a
# (package, reason) pair. The reason is shown to the user in the plan.
KNOWN_BLOATWARE: dict = {
    "com.google.android.play.games": (
        "Google Play Games: bloat en TV, sin dependencias esenciales"
    ),
    "com.google.android.feedback": (
        "App de feedback de Google: no aporta funcion en TV"
    ),
    "com.google.android.katniss": (
        "Reportador de errores de Google: telemetria"
    ),
    "com.android.cts.ctsshim": "Paquetes de prueba CTS: solo test, no esenciales",
    "com.android.cts.priv.ctsshim": "Paquetes de prueba CTS: solo test, no esenciales",
}

# Narrow default patterns matched against the REAL inventory. Only names
# that are unambiguously non-essential may be pattern-matched. A package
# is proposed at most once (first matching reason wins).
BLOATWARE_PATTERNS: Sequence[Tuple["re.Pattern", str]] = (
    (
        re.compile(r"^com\.android\.cts\."),
        "Paquetes de prueba CTS detectados en el inventario",
    ),
    (
        re.compile(r"\.demo$"),
        "App demo del fabricante detectada en el inventario",
    ),
)


def _explicit_candidates(profile: Mapping) -> List[str]:
    """The profile's curated `candidates` list (model-specific profiles)."""
    out: List[str] = []
    raw = profile.get("candidates")
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, Mapping) and isinstance(item.get("package"), str):
            pkg = item["package"].strip()
            if pkg:
                out.append(pkg)
    return out


def _known_from_profile(profile: Mapping) -> List[str]:
    """Read `candidate_discovery.known_packages` from the profile.

    Accepts either a list of package names (strings) or a list of
    {"package": ..., "reason": ...} dicts (same shape as `candidates`).
    Invalid entries are skipped silently (fail-safe: a bad file must
    never enable anything).
    """
    out: List[str] = []
    disc = profile.get("candidate_discovery")
    if not isinstance(disc, Mapping):
        return out
    raw = disc.get("known_packages")
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, Mapping) and isinstance(item.get("package"), str):
            pkg = item["package"].strip()
            if pkg:
                out.append(pkg)
    return out


def _patterns_for_profile(profile: Mapping) -> List[Tuple["re.Pattern", str]]:
    """Default narrow patterns + any extra regexes the profile adds.

    Extra patterns come from `candidate_discovery.patterns` as
    {"regex": ..., "reason": ...} dicts. A bad regex is ignored
    (fail-safe), never raised.
    """
    patterns: List[Tuple["re.Pattern", str]] = list(BLOATWARE_PATTERNS)
    disc = profile.get("candidate_discovery")
    if not isinstance(disc, Mapping):
        return patterns
    extra = disc.get("patterns")
    if not isinstance(extra, list):
        return patterns
    for item in extra:
        if not (isinstance(item, Mapping) and isinstance(item.get("regex"), str)):
            continue
        try:
            compiled = re.compile(item["regex"])
        except re.error:
            continue  # fail-safe: un regex invalido se ignora
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = "patron del perfil"
        patterns.append((compiled, reason.strip()))
    return patterns


def _pattern_hits(inventory: Mapping[str, str], patterns) -> List[str]:
    """Packages in the inventory that match a (narrow) pattern."""
    hits: List[str] = []
    for pkg in sorted(inventory):
        if not isinstance(pkg, str):
            continue
        for regex, _reason in patterns:
            if regex.search(pkg):
                hits.append(pkg)
                break  # one reason is enough; avoid duplicate proposals
    return hits


def _dedup_present(candidates: Sequence[str], inventory: Mapping) -> List[str]:
    """Only packages actually observed on the device; de-duplicated, sorted."""
    seen = set()
    out: List[str] = []
    for p in candidates:
        if p in inventory and p not in seen:
            seen.add(p)
            out.append(p)
    return sorted(out)


def discover_candidates(inventory: Mapping[str, str], profile: Mapping) -> List[str]:
    """Propose bloatware candidates for a device, from the REAL inventory.

    Returns a de-duplicated, sorted list of package names (empty list when
    the profile neither curates `candidates` nor opts into
    `candidate_discovery`). The caller (CLI/planner) is responsible for
    the safety gates; this function only proposes packages that actually
    exist in the inventory.
    """
    if not isinstance(profile, Mapping) or not isinstance(inventory, Mapping):
        return []

    # 1. Curated model-profile candidates: ONLY source when present.
    explicit = _explicit_candidates(profile)
    if explicit:
        return _dedup_present(explicit, inventory)

    # 2. Discovery: only when the profile opts in via candidate_discovery.
    if not isinstance(profile.get("candidate_discovery"), Mapping):
        return []
    proposed = _known_from_profile(profile)
    proposed.extend(_pattern_hits(inventory, _patterns_for_profile(profile)))
    return _dedup_present(proposed, inventory)


def reason_for(package: str, profile: Mapping) -> str:
    """Human-readable reason for a proposed candidate (for the UI)."""
    raw = profile.get("candidates")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping) and item.get("package") == package:
                reason = item.get("reason")
                if isinstance(reason, str) and reason.strip():
                    return reason.strip()
    disc = profile.get("candidate_discovery")
    if isinstance(disc, Mapping):
        raw = disc.get("known_packages")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, Mapping) and item.get("package") == package:
                    reason = item.get("reason")
                    if isinstance(reason, str) and reason.strip():
                        return reason.strip()
        for regex, reason in _patterns_for_profile(profile):
            if regex.search(package):
                return reason
    if package in KNOWN_BLOATWARE:
        return KNOWN_BLOATWARE[package]
    for _regex, reason in BLOATWARE_PATTERNS:
        if _regex.search(package):
            return reason
    return "candidato del perfil"
