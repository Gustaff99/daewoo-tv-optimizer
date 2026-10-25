"""Operation audit log (FASE 6: "Registro completo de operaciones").

Append-only JSON-lines log. Every operation (plan generation, action
execution, restoration, error) is recorded as a single JSON line with
a timestamp, operation type, and payload.

Design constraints:
- The log is append-only: no code path can modify or delete prior entries.
- Each entry is self-contained (no cross-entry references).
- The log file path is explicit; no hidden state.
- JSON serialization uses sort_keys for deterministic output.
- The log never raises on serialization errors: it writes an
  ``{"error": "serialization_failed", ...}`` entry instead.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


def make_entry(
    operation: str,
    payload: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a single log entry (dict). Does not write to disk."""
    entry: Dict[str, Any] = {
        "ts": timestamp or _utc_now_iso(),
        "op": operation,
    }
    if payload is not None:
        entry["payload"] = payload
    return entry


def entry_to_line(entry: Dict[str, Any]) -> str:
    """Serialize a log entry to a single JSON line."""
    return json.dumps(entry, sort_keys=True, ensure_ascii=False)


def append_entry(
    log_path: str,
    operation: str,
    payload: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> str:
    """Append one entry to the JSON-lines log file. Returns the line written.

    Creates the file (and parent dirs) if it does not exist.
    Never raises on serialization failure: writes an error entry instead.
    """
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)

    entry = make_entry(operation, payload, timestamp)
    try:
        line = entry_to_line(entry)
    except (TypeError, ValueError):
        # Fail-safe: unserializable payload -> record the failure, don't crash
        line = json.dumps(
            {"ts": entry["ts"], "op": operation, "error": "serialization_failed"},
            sort_keys=True,
        )

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


def read_log(log_path: str) -> list[Dict[str, Any]]:
    """Read all entries from a JSON-lines log file.

    Malformed lines are skipped (fail-safe: a corrupt line must not
    prevent reading the rest of the log).
    Returns an empty list if the file does not exist.
    """
    if not os.path.isfile(log_path):
        return []
    entries = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue  # skip corrupt line
    return entries


def log_plan_generation(
    log_path: str,
    plan_dict: Dict[str, Any],
) -> str:
    """Record a plan generation event. Returns the log line."""
    return append_entry(
        log_path,
        "plan_generated",
        {
            "profile": plan_dict.get("profile"),
            "model": plan_dict.get("model"),
            "os_family": plan_dict.get("os_family"),
            "dry_run": plan_dict.get("dry_run"),
            "action_count": len(plan_dict.get("actions", [])),
            "skipped_count": len(plan_dict.get("skipped", [])),
        },
    )


def log_restoration(
    log_path: str,
    packages: list[str],
    success: bool = True,
) -> str:
    """Record a restoration event. Returns the log line."""
    return append_entry(
        log_path,
        "restoration",
        {
            "packages": packages,
            "success": success,
        },
    )
