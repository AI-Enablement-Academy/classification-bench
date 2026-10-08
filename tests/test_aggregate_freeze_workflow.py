"""A committed parent overrun is visible before and after sibling allocation."""

import json
import unittest

from classification_bench.benchmark import (
    BenchmarkError, _control, _initialize, _set_control, amend_budget, run, status,
)
from classification_bench.budget import BudgetLedger
from tests import test_workflow_namespace as fixtures


class AggregateFreezeWorkflowTests(unittest.TestCase):
    setUp = fixtures.WorkflowNamespaceTests.setUp
    load = fixtures.WorkflowNamespaceTests.load

    def check_frozen_sibling(self, policy, allocated):
        self.config["on_budget_exhausted"] = policy
        smoke, full = self.load("smoke"), self.load("full")
        ledger = BudgetLedger(self.config["database"])
        ledger.create_aggregate("synthetic:experiment", 4, "SYN", 1, "offline fixture")
        verified = _initialize(smoke[0], smoke[2], smoke[3])
        if allocated:
            sibling = _initialize(full[0], full[2], full[3])
        ledger.reserve(smoke[0]["scope"], "overrun", 1, bound_source="offline bound fixture")
        ledger.settle(smoke[0]["scope"], "overrun", "saved-charge", 2)
        before = ledger.aggregate_balances("synthetic:experiment")
        for operation in (status, run, run):
            result = operation(self.root / "full.json")
            self.assertEqual(result["status"], "blocked_budget_freeze", result)
            self.assertEqual(result["action_required"], "review_budget_freeze")
            self.assertIsNone(result["admission_block"])
            self.assertEqual(result["aggregate_freeze"], before["freeze"])
            self.assertIn("above-bound charge", result["requests"][0]["blocked_reason"])
            self.assertEqual(result["states"], {"never_sent": 1})
        self.assertEqual(ledger.aggregate_balances("synthetic:experiment"), before)
        self.assertEqual(ledger.allocation_for(full[0]["scope"]) is not None, allocated)
        amendment = self.root / "amend.json"
        amendment.write_text(json.dumps({"schema_version": 1, "run_sha256": full[2],
            "scope": full[0]["scope"], "amendment_id": "fixture", "expected_cap": 2,
            "new_cap": 3, "authorization_source": "offline fixture"}))
        with self.assertRaisesRegex(BenchmarkError, "frozen aggregate"):
            amend_budget(self.root / "full.json", amendment)
        if allocated:
            for state in ("paused_budget", "stopped_budget"):
                _set_control(sibling, state, "observed budget boundary", budget_scope=full[0]["scope"])
                self.assertEqual(_control(sibling), "running")
        with verified.execution.coordinator._transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM execution_requests").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM benchmark_managed_control_events").fetchone()[0], 0)

    def test_unallocated_pause_keeps_freeze_evidence_and_no_allocation(self):
        self.check_frozen_sibling("pause", False)

    def test_unallocated_stop_keeps_freeze_evidence_and_no_allocation(self):
        self.check_frozen_sibling("stop", False)

    def test_allocated_pause_does_not_misreport_a_resumable_boundary(self):
        self.check_frozen_sibling("pause", True)

    def test_allocated_stop_does_not_overwrite_the_freeze_with_stop_control(self):
        self.check_frozen_sibling("stop", True)
