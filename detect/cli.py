"""Command-line front end for identity detection.

Usage:
  python -m detect.cli --model 55DM75QV --os "VIDAA"
  python -m detect.cli --model 43DE6500 --os "Android TV" --json

Output: the resolved identity as JSON (always; --json is accepted for
compatibility). Exit codes: 0 = identity resolved (any confidence),
2 = invalid input. The CLI never executes anything on a device.
"""
from __future__ import annotations

import argparse
import json
import sys

from .identity import resolve_profile
from .manual_input import ManualInputError, parse_manual_entry
from .profiles import load_profiles


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="daewoo-detect", description=__doc__)
    p.add_argument("--model", help="model exactly as printed on the TV")
    p.add_argument("--os", dest="os_name", help="OS as shown in Settings > About")
    p.add_argument("--firmware", help="firmware/build string (optional)")
    p.add_argument("--json", action="store_true", help="(default) JSON output")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        identity = parse_manual_entry(args.model, args.os_name, args.firmware)
    except ManualInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    profiles, default_profile = load_profiles()
    profile = resolve_profile(identity, profiles, default_profile)
    result = {
        "identity": identity.to_dict(),
        "profile": profile.get("profile", "unsupported/default"),
        "actions_allowed": bool(profile.get("actions_allowed", False)),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
