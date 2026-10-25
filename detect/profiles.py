"""Profile loading for the optimization layer (FASE 3).

Profiles are JSON files under the project-level `profiles/` directory:

    profiles/<family>/<name>.json

The loader builds the lookup consumed by `identity.resolve_profile`:
- every valid profile is registered under its `os_family` key (if set)
- and under each entry of its `models` list (uppercased)
- the profile whose id is `unsupported/default` (or the only one under
  `unsupported/`) becomes the fail-safe default

Fail-safe rules (a bad file must never enable anything):
- unparseable or schema-invalid profile files are skipped, never raised
- a profile may set `min_confidence`; identities with lower confidence
  fall through to the fail-safe default (checked in `resolve_profile`)
- `actions_allowed` stays the single default-deny gate for the executor
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from .identity import CONFIDENCE_LEVELS
from ._paths import base_dir

DEFAULT_PROFILE_ID = "unsupported/default"

# Higher = stronger evidence.
CONFIDENCE_RANK: Dict[str, int] = {
    "conclusive": 3,
    "likely": 2,
    "unreliable": 1,
    "unknown": 0,
}


def default_profiles_dir() -> Path:
    """Profiles ship next to the package so the tool works from a USB stick
    regardless of the current working directory (source or frozen bundle)."""
    return base_dir() / "profiles"


def _valid_profile(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("profile"), str) or not data["profile"].strip():
        return False
    if not isinstance(data.get("actions_allowed"), bool):
        return False
    min_conf = data.get("min_confidence", "conclusive")
    if min_conf not in CONFIDENCE_LEVELS:
        return False
    return True


def _register(profiles: Dict[str, dict], prof: dict) -> None:
    family = prof.get("os_family")
    if isinstance(family, str) and family and family != "unknown":
        profiles[family] = prof
    models = prof.get("models")
    if isinstance(models, list):
        for m in models:
            if isinstance(m, str) and m.strip():
                profiles[m.strip().upper()] = prof


def load_profiles(root: Optional[Path] = None) -> Tuple[Dict[str, dict], dict]:
    """Load every valid profile under `root` (default: package dir).

    Returns (profiles, default_profile). `profiles` maps uppercase model
    keys and os_family keys to profile dicts. `default_profile` is always
    the fail-safe (actions_allowed=False), either from disk or synthesized.
    """
    root = Path(root) if root is not None else default_profiles_dir()
    profiles: Dict[str, dict] = {}
    default_profile: Optional[dict] = None

    if root.is_dir():
        for path in sorted(root.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # fail-safe: unreadable/invalid file -> ignored
            if not _valid_profile(data):
                continue
            prof = dict(data)
            _register(profiles, prof)
            if prof["profile"] == DEFAULT_PROFILE_ID:
                default_profile = prof

    if default_profile is None:
        default_profile = {
            "profile": DEFAULT_PROFILE_ID,
            "actions_allowed": False,
            "policy": "fail-safe: sin perfil valido, no se modifica nada",
        }
    return profiles, default_profile
