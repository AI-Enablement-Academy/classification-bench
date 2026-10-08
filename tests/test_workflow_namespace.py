"""Managed phases preserve provider identities but isolate local execution state."""

import json
import tempfile
import unittest
from pathlib import Path

from classification_bench.benchmark import _bind, _control, _load, _set_control, BenchmarkError
from classification_bench.verified_execution import VerifiedExecution
from classification_bench.budget import BudgetLedger
from classification_bench.benchmark import run, status, recover, export_operations, report_snapshot


class WorkflowNamespaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        values = {
            "task": {"name": "parcel", "input_keys": ["text"], "fields": [{"name": "route", "labels": ["hold", "ship"]}]},
            "experiment": {"configs": [{"id": "one", "model": "synthetic-only", "settings": {"adapter": "synthetic", "response_mode": "first_label"}}],
                           "prompts": [{"id": "p", "text": "Classify"}], "repeats": 1, "batch_size": 1},
            "inputs": {"records": [{"id": "same", "input": {"text": "shared smoke and full case"}}]},
        }
        for key, value in values.items():
            (self.root / (key + ".json")).write_text(json.dumps(value))
        self.config = {"schema_version": 2, **{key: str(self.root / (key + ".json")) for key in values},
                       "database": str(self.root / "state.sqlite"), "artifacts": str(self.root / "raw"),
                       "scope": "synthetic:smoke", "cap": 2, "currency": "SYN", "scale": 1,
                       "max_concurrency": 1, "provider_limits": {"synthetic": 1}, "authorization_file": None,
                       "on_budget_exhausted": "pause",
                       "aggregate": {"parent_scope": "synthetic:experiment", "allocation_id": "smoke", "phase": "smoke"}}

    def load(self, phase):
        config = {**self.config, "scope": "synthetic:" + phase,
                  "aggregate": {**self.config["aggregate"], "allocation_id": phase, "phase": phase}}
        path = self.root / (phase + ".json")
        path.write_text(json.dumps(config))
        return _load(path)

    def test_overlapping_phases_have_different_storage_but_identical_provider_requests(self):
        smoke, full = self.load("smoke"), self.load("full")
        self.assertEqual(smoke[1], full[1])
        a, b = smoke[3][0], full[3][0]
        self.assertEqual(a["logical_request_id"], b["logical_request_id"])
        self.assertNotEqual(a["request"]["request_id"], b["request"]["request_id"])
        self.assertEqual(a["prepared"].body, b["prepared"].body)
        self.assertEqual(a["prepared"].request_id, a["logical_request_id"])
        for material in (a, b):
            manifest = json.loads(material["manifest"])
            self.assertEqual(manifest["request_id"], material["request"]["request_id"])
            self.assertEqual(manifest["logical_request_id"], material["logical_request_id"])

    def test_controls_are_per_run_and_stopped_phase_stays_stopped(self):
        smoke, full = self.load("smoke"), self.load("full")
        a = VerifiedExecution(self.config["database"], self.config["artifacts"])
        b = VerifiedExecution(self.config["database"], self.config["artifacts"])
        _bind(a, smoke[2], smoke[0])
        _bind(b, full[2], full[0])
        _set_control(a, "stopped_budget", "operator test")
        self.assertEqual(_control(a), "stopped_budget")
        self.assertEqual(_control(b), "running")
        with self.assertRaisesRegex(BenchmarkError, "stopped run"):
            _set_control(a, "running", "invalid resume")
        with self.assertRaisesRegex(BenchmarkError, "binding changed"):
            _bind(a, "changed", smoke[0])
        with self.assertRaisesRegex(BenchmarkError, "legacy run"):
            _bind(a, smoke[2])

    def test_managed_run_cannot_attach_legacy_database(self):
        smoke = self.load("smoke")
        verified = VerifiedExecution(self.config["database"], self.config["artifacts"])
        _bind(verified, "legacy")
        with self.assertRaisesRegex(BenchmarkError, "legacy run database"):
            _bind(verified, smoke[2], smoke[0])

    def test_two_phases_share_budget_and_keep_logical_export_ids(self):
        smoke, full = self.load("smoke"), self.load("full")
        ledger = BudgetLedger(self.config["database"])
        ledger.create_aggregate("synthetic:experiment", 4, "SYN", 1, "offline test")
        self.assertEqual(status(self.root / "smoke.json")["states"], {"never_sent": 1})
        for phase in ("smoke", "full"):
            path = self.root / (phase + ".json")
            result = run(path)
            self.assertEqual(result["status"], "completed", result)
            operation = export_operations(path)[0]
            self.assertEqual(operation["request_id"], smoke[1]["requests"][0]["request_id"])
            self.assertNotEqual(operation["request_id"], operation["storage_request_id"])
            snapshot = report_snapshot(path)
            self.assertEqual(len(snapshot["predictions"]["records"]), 1)
            self.assertEqual(run(path)["completed_requests"], 1)
            self.assertEqual(recover(path)["unresolved"], [])
        self.assertEqual(ledger.aggregate_balances("synthetic:experiment")["allocated_cap"], 4)
        with VerifiedExecution(self.config["database"], self.config["artifacts"]).execution.coordinator._transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM execution_requests").fetchone()[0], 2)
