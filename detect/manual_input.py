"""Validated manual input flow.

The user types what they can read off the TV (model label, OS name from
Settings > About). All input is normalized and validated; unknown values
raise ManualInputError with an actionable message. Manual data never
reaches "conclusive" confidence (see identity.identity_from_manual).
"""
from __future__ import annotations

from typing import Optional

from .identity import DeviceIdentity, identity_from_manual


class ManualInputError(Exception):
    """Raised on invalid or unusable manual input."""


# Accepted OS spellings (lowercase) -> canonical family.
KNOWN_OS_VALUES = {
    "android tv": "android-tv",
    "androidtv": "android-tv",
    "google tv": "google-tv",
    "googletv": "google-tv",
    "vidaa": "vidaa",
    "tivo": "tivo",
    "android": "aosp-uncertified",
}


def normalize_model(raw: Optional[str]) -> Optional[str]:
    """Uppercase, collapse whitespace. Returns None for empty input."""
    if raw is None:
        return None
    cleaned = " ".join(raw.split()).upper()
    return cleaned or None


def normalize_os(raw: Optional[str]) -> Optional[str]:
    """Map a user OS spelling to a canonical family; None if absent."""
    if raw is None:
        return None
    key = " ".join(raw.lower().split())
    if key not in KNOWN_OS_VALUES:
        raise ManualInputError(
            f"unrecognized OS {raw!r}; expected one of: "
            + ", ".join(sorted(KNOWN_OS_VALUES))
        )
    return KNOWN_OS_VALUES[key]


def parse_manual_entry(
    model: Optional[str],
    os_name: Optional[str],
    firmware: Optional[str] = None,
) -> DeviceIdentity:
    """Validate a manual entry and build the identity.

    Rules:
    - No model and no OS -> fail-safe unknown identity (no error: the
      user simply has no data; the resolver must stop, not crash).
    - Model only -> unreliable (model does not imply OS).
    - OS only / model+OS -> likely.
    - Unknown OS spelling -> ManualInputError.
    """
    model_c = normalize_model(model)
    os_c = normalize_os(os_name)
    if model_c is None and os_c is None:
        return identity_from_manual(None, None)
    return identity_from_manual(model_c, os_c, firmware=firmware)
