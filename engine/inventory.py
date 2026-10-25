"""Package inventory collection (FASE 6).

Parses ADB read-only output into the inventory mapping consumed by the
FASE 4 planner. The inventory maps package name -> observed state.

ADB commands used (read-only, whitelisted in detect/adb_probe.py):
  pm list packages       -> all installed packages
  pm list packages -d    -> disabled packages

Fail-safe rules:
- Malformed lines are silently skipped (never raise on bad input).
- An empty or None input produces an empty inventory (the planner's
  gate 3 will reject an empty inventory: no plan without evidence).
- Package names are validated: must be a non-empty string of valid
  Java-identifier characters (letters, digits, dots, underscores,
  hyphens) to prevent command injection if the inventory is ever
  interpolated into a shell command.
"""
from __future__ import annotations

import re
from typing import Dict, Mapping, Optional

# Valid Android package name: dotted Java identifiers.
# Each segment: starts with a letter or underscore, then letters/digits/_/$
# (We allow hyphens too for OEM packages that technically violate the
# spec but exist in the wild, e.g. some Daewoo preloads.)
_PACKAGE_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_$\-]*(\.[A-Za-z_][A-Za-z0-9_$\-]*)*$"
)

# pm list packages line format: "package:com.example.app"
_PM_LINE_RE = re.compile(r"^package:(\S+)$")


def _valid_package_name(name: str) -> bool:
    """True if `name` looks like a real Android package name."""
    if not name or len(name) > 256:
        return False
    return bool(_PACKAGE_RE.match(name))


def parse_pm_list_packages(output: Optional[str]) -> list[str]:
    """Parse `pm list packages` output into a list of package names.

    Each line should be `package:<name>`. Malformed lines are skipped.
    Returns an empty list for None/empty input.
    """
    if not output:
        return []
    packages = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _PM_LINE_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        if _valid_package_name(name):
            packages.append(name)
    return packages


def parse_pm_list_packages_disabled(output: Optional[str]) -> list[str]:
    """Parse `pm list packages -d` output into a list of disabled package names.

    Same format as `pm list packages`; the -d flag filters to disabled.
    """
    return parse_pm_list_packages(output)


def build_inventory(
    all_packages_output: Optional[str],
    disabled_packages_output: Optional[str] = None,
) -> Dict[str, str]:
    """Build the inventory mapping: package -> state.

    - All packages from `pm list packages` default to "enabled".
    - Packages listed in `pm list packages -d` are set to "disabled".
    - A package that appears in both lists is "disabled" (the -d list
      wins, as it is the more specific observation).
    - Malformed input produces an empty or partial inventory; the
      planner's gate 3 rejects empty inventories.

    Returns a plain dict suitable for the FASE 4 planner.
    """
    inventory: Dict[str, str] = {}

    for pkg in parse_pm_list_packages(all_packages_output):
        inventory[pkg] = "enabled"

    for pkg in parse_pm_list_packages_disabled(disabled_packages_output):
        inventory[pkg] = "disabled"

    return inventory


def inventory_summary(inventory: Mapping[str, str]) -> str:
    """Human-readable summary of the inventory (for logs/reports)."""
    if not inventory:
        return "inventario vacío (0 paquetes)"
    enabled = sum(1 for v in inventory.values() if v == "enabled")
    disabled = sum(1 for v in inventory.values() if v == "disabled")
    other = len(inventory) - enabled - disabled
    parts = [f"{len(inventory)} paquetes: {enabled} enabled, {disabled} disabled"]
    if other:
        parts.append(f", {other} otro")
    return " ".join(parts)
