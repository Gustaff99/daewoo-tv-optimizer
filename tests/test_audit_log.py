"""Tests for engine/audit_log.py (FASE 6).

Covers:
- Entry construction and serialization
- Append to JSON-lines file
- Read back (round-trip)
- Malformed line tolerance on read
- Non-existent file handling
- Plan generation and restoration log helpers
- Unserializable payload fail-safe
"""
import json
import os
import tempfile
import unittest

from engine.audit_log import (
    append_entry,
    entry_to_line,
    log_plan_generation,
    log_restoration,
    make_entry,
    read_log,
)


class TestMakeEntry(unittest.TestCase):
    def test_basic(self):
        e = make_entry("test_op", {"key": "val"}, timestamp="2026-01-01T00:00:00.000Z")
        self.assertEqual(e["ts"], "2026-01-01T00:00:00.000Z")
        self.assertEqual(e["op"], "test_op")
        self.assertEqual(e["payload"], {"key": "val"})

    def test_no_payload(self):
        e = make_entry("bare", timestamp="2026-01-01T00:00:00.000Z")
        self.assertNotIn("payload", e)

    def test_timestamp_auto(self):
        e = make_entry("auto_ts")
        self.assertIn("ts", e)
        self.assertTrue(e["ts"].endswith("Z"))


class TestEntryToLine(unittest.TestCase):
    def test_valid(self):
        e = {"ts": "T", "op": "X", "payload": {"a": 1}}
        line = entry_to_line(e)
        parsed = json.loads(line)
        self.assertEqual(parsed["op"], "X")

    def test_sorted_keys(self):
        e = {"b": 2, "a": 1}
        line = entry_to_line(e)
        self.assertLess(line.index('"a"'), line.index('"b"'))


class TestAppendAndRead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "test", "ops.jsonl")

    def test_append_creates_file_and_dirs(self):
        line = append_entry(self.log, "op1", {"x": 1}, timestamp="T1")
        self.assertTrue(os.path.isfile(self.log))
        self.assertIn("op1", line)

    def test_round_trip(self):
        append_entry(self.log, "op1", {"a": 1}, timestamp="T1")
        append_entry(self.log, "op2", {"b": 2}, timestamp="T2")
        entries = read_log(self.log)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["op"], "op1")
        self.assertEqual(entries[1]["op"], "op2")
        self.assertEqual(entries[0]["payload"]["a"], 1)

    def test_read_nonexistent(self):
        self.assertEqual(read_log(os.path.join(self.tmp, "nope.jsonl")), [])

    def test_malformed_line_skipped(self):
        # Write a valid line, a corrupt line, and another valid line
        append_entry(self.log, "ok1", timestamp="T1")
        with open(self.log, "a") as f:
            f.write("THIS IS NOT JSON\n")
        append_entry(self.log, "ok2", timestamp="T3")
        entries = read_log(self.log)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["op"], "ok1")
        self.assertEqual(entries[1]["op"], "ok2")

    def test_blank_lines_ignored(self):
        os.makedirs(os.path.dirname(self.log), exist_ok=True)
        with open(self.log, "w") as f:
            f.write('\n{"ts":"T","op":"x"}\n\n')
        entries = read_log(self.log)
        self.assertEqual(len(entries), 1)


class TestUnserializablePayload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "ops.jsonl")

    def test_set_payload(self):
        # A set is not JSON-serializable
        append_entry(self.log, "bad", {"data": {1, 2, 3}}, timestamp="T1")
        entries = read_log(self.log)
        self.assertEqual(len(entries), 1)
        self.assertIn("serialization_failed", entries[0].get("error", ""))


class TestPlanGenerationLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "ops.jsonl")

    def test_log_plan(self):
        plan = {
            "profile": "daewoo-tizen-2022",
            "model": "32DE15HLED",
            "os_family": "tizen",
            "dry_run": True,
            "actions": [{"package": "com.a"}],
            "skipped": [{"package": "com.b"}],
        }
        line = log_plan_generation(self.log, plan)
        self.assertIn("plan_generated", line)
        entries = read_log(self.log)
        self.assertEqual(entries[0]["payload"]["action_count"], 1)
        self.assertEqual(entries[0]["payload"]["skipped_count"], 1)


class TestRestorationLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "ops.jsonl")

    def test_log_restoration(self):
        line = log_restoration(self.log, ["com.a", "com.b"], success=True)
        self.assertIn("restoration", line)
        entries = read_log(self.log)
        self.assertEqual(entries[0]["payload"]["packages"], ["com.a", "com.b"])
        self.assertTrue(entries[0]["payload"]["success"])

    def test_log_restoration_failure(self):
        log_restoration(self.log, ["com.a"], success=False)
        entries = read_log(self.log)
        self.assertFalse(entries[0]["payload"]["success"])


if __name__ == "__main__":
    unittest.main()
