"""Device identity resolution: OS first, model second, fail-safe.

Principle (non-negotiable): never modify a TV based on the brand "Daewoo"
alone. If identification is not conclusive, resolution falls back to the
unsupported fail-safe profile, which authorizes zero modifications.

Signal trust order (highest first):
1. ADB read-only probes on the actual device (fingerprint + packages).
2. Official product page stating the OS (source: official-page).
3. Manual user input (max confidence: "likely").
4. Brand only -> confidence "unknown" -> fail-safe.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping, Optional, Sequence

CONFIDENCE_LEVELS = ("conclusive", "likely", "unreliable", "unknown")

# OS families recognized by the resolver.
OS_FAMILIES = (
    "android-tv",
    "google-tv",
    "vidaa",
    "tivo",
    "aosp-uncertified",
    "unknown",
)

# Packages whose presence on a device identifies the TV platform.
ANDROID_TV_PACKAGES = ("com.google.android.tv", "com.android.tv")
GOOGLE_TV_PACKAGES = ("com.google.tv",)


class IdentityError(Exception):
    """Raised when identity inputs are invalid."""


@dataclass(frozen=True)
class DeviceIdentity:
    """Resolved identity of a TV. Immutable; built only by resolvers."""

    os_family: str
    confidence: str
    os_version: Optional[str] = None
    model: Optional[str] = None
    brand: Optional[str] = None
    firmware: Optional[str] = None
    sources: tuple = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.os_family not in OS_FAMILIES:
            raise IdentityError(f"unknown os_family: {self.os_family!r}")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise IdentityError(f"unknown confidence: {self.confidence!r}")

    @property
    def conclusive(self) -> bool:
        return self.confidence == "conclusive"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sources"] = list(self.sources)
        d["conclusive"] = self.conclusive
        return d


def identity_from_adb(
    packages: Sequence[str],
    model: Optional[str] = None,
    brand: Optional[str] = None,
    os_version: Optional[str] = None,
    firmware: Optional[str] = None,
) -> DeviceIdentity:
    """Resolve identity from read-only ADB evidence. OS is resolved first
    from the installed package set; the model only refines the result."""
    pkgs = set(packages)
    # Android build evidence: ro.build.version.release only exists on
    # Android builds; the fingerprint string is a secondary signal.
    android_evidence = bool(os_version and str(os_version).strip())
    if not android_evidence and firmware and "android" in str(firmware).lower():
        android_evidence = True
    if any(p in pkgs for p in ANDROID_TV_PACKAGES):
        os_family = "android-tv"
    elif any(p in pkgs for p in GOOGLE_TV_PACKAGES):
        os_family = "google-tv"
    elif android_evidence:
        # Android build without a certified TV platform package:
        # rebranded AOSP Android (e.g. OEM TV platforms such as
        # Vestel EMIR/shandao on Daewoo D43DM55UQPMS).
        os_family = "aosp-uncertified"
    else:
        os_family = "unknown"
    # ADB on the real device is the strongest evidence we have.
    confidence = "conclusive" if os_family != "unknown" else "unreliable"
    return DeviceIdentity(
        os_family=os_family,
        confidence=confidence,
        os_version=os_version,
        model=model,
        brand=brand,
        firmware=firmware,
        sources=("adb",),
    )


def identity_from_official_page(
    os_family: str,
    model: Optional[str] = None,
    os_version: Optional[str] = None,
    firmware: Optional[str] = None,
) -> DeviceIdentity:
    """Resolve identity from an official product page stating the OS."""
    if os_family not in OS_FAMILIES or os_family == "unknown":
        raise IdentityError(f"official page must state a concrete OS, got {os_family!r}")
    return DeviceIdentity(
        os_family=os_family,
        confidence="conclusive",
        os_version=os_version,
        model=model,
        brand="daewoo",
        firmware=firmware,
        sources=("official-page",),
    )


def identity_from_manual(
    model: Optional[str],
    os_family: Optional[str],
    os_version: Optional[str] = None,
    firmware: Optional[str] = None,
) -> DeviceIdentity:
    """Resolve identity from user-typed data. User input is never
    conclusive on its own: max confidence is 'likely'; brand-only input
    is 'unknown' (fail-safe)."""
    if os_family is None:
        if model is None:
            return DeviceIdentity(
                os_family="unknown",
                confidence="unknown",
                brand="daewoo",
                sources=("manual",),
            )
        return DeviceIdentity(
            os_family="unknown",
            confidence="unreliable",
            model=model,
            brand="daewoo",
            sources=("manual",),
        )
    if os_family not in OS_FAMILIES:
        raise IdentityError(f"unknown os_family: {os_family!r}")
    return DeviceIdentity(
        os_family=os_family,
        confidence="likely",
        os_version=os_version,
        model=model,
        brand="daewoo",
        firmware=firmware,
        sources=("manual",),
    )


def _adb_match(identity: DeviceIdentity, match: Mapping) -> bool:
    """Evidence-based profile binding: every `field: value` pair in
    `match` must hold for the identity. The `firmware` field (build
    fingerprint) matches by prefix; other fields match exactly
    (case-insensitive). An empty or malformed match never binds."""
    if not isinstance(match, Mapping) or not match:
        return False
    for field_name, required in match.items():
        if not isinstance(field_name, str) or not isinstance(required, str) or not required.strip():
            return False
        actual = getattr(identity, field_name, None)
        if actual is None:
            return False
        actual_s = str(actual)
        if field_name == "firmware":
            if not actual_s.lower().startswith(required.strip().lower()):
                return False
        elif actual_s.strip().lower() != required.strip().lower():
            return False
    return True


def resolve_profile(
    identity: DeviceIdentity,
    profiles: Mapping[str, Mapping],
    default_profile: Mapping,
) -> Mapping:
    """Map an identity to a profile. Lookup order:
    1. exact model key (case-insensitive)
    2. `adb_match` evidence binding (profile declares on-device property
       pairs, e.g. fingerprint prefix, that must all match)
    3. OS family key
    4. default (unsupported fail-safe) profile.

    Confidence gate: a candidate profile may declare `min_confidence`
    (default: "conclusive"). If the identity's confidence is lower, the
    candidate is rejected and resolution falls through to the fail-safe
    default. Manual user input ("likely") therefore never reaches a
    profile that authorizes actions.

    The returned profile's 'actions_allowed' flag is the single gate the
    execution layer consults; the fail-safe default is always False.
    """
    from .profiles import CONFIDENCE_RANK

    def acceptable(prof: Mapping) -> bool:
        min_conf = prof.get("min_confidence", "conclusive")
        return CONFIDENCE_RANK.get(identity.confidence, 0) >= CONFIDENCE_RANK.get(min_conf, 3)

    if identity.model:
        key = identity.model.strip().upper()
        for name, prof in profiles.items():
            if name.strip().upper() == key and acceptable(prof):
                return prof
    for name in sorted(profiles):
        prof = profiles[name]
        if _adb_match(identity, prof.get("adb_match")) and acceptable(prof):
            return prof
    prof = profiles.get(identity.os_family)
    if prof is not None and acceptable(prof):
        return prof
    return default_profile


def profile_allows_actions(profile: Mapping) -> bool:
    """The only gate the executor may use. Default-deny: a profile that
    does not explicitly allow actions does not allow them."""
    return bool(profile.get("actions_allowed", False))
