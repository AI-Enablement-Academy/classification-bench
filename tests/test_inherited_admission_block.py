"""Inherited safety blocks retain their cause and never consume stop/pause policy."""

import json
import unittest

from classification_bench.benchmark import (
    BenchmarkError, _control, _initialize, _set_control, amend_budget, run, status,
)
from classification_bench.budget import BudgetError, BudgetLedger
from classification_bench.verified_execution import VerifiedExecution
from tests import test_workflow_namespace as fixtures


class InheritedAdmissionBlockTests(unittest.TestCase):
    setUp = fixtures.WorkflowNamespaceTests.setUp
    load = fixtures.WorkflowNamespaceTests.load

    def blocked_full(self, policy="pause"):
        self.config["on_budget_exhausted"] = policy
        config, _, binding, materials, _ = self.load("full")
        ledger = BudgetLedger(config["database"])
        ledger.create_aggregate("synthetic:experiment", 4, "SYN", 1,
                                "offline inherited-block fixture")
        verified = _initialize(config, binding, materials)
        block = verified.execution.block_scope(
            "synthetic:experiment", "subscription paid extra usage observed",
            "offline inherited-block evidence")
        return config, binding, verified, block

    def assert_safety_status(self, result, block):
        self.assertEqual(result["status"], "blocked_safety")
        self.assertEqual(result["action_required"], "review_safety_block")
        self.assertEqual(result["admission_block"], block)
        self.assertEqual(result["requests"][0]["blocked_reason"],
                         "subscription paid extra usage observed")
        self.assertEqual(result["completed_requests"], 0)

    def test_status_exposes_inherited_parent_reason_and_evidence(self):
        _, _, _, block = self.blocked_full()
        self.assert_safety_status(status(self.root / "full.json"), block)

    def check_restart_policy(self, policy):
        _, _, verified, block = self.blocked_full(policy)
        for _ in range(2):
            self.assert_safety_status(run(self.root / "full.json"), block)
        self.assertEqual(_control(verified), "running")
        with verified.execution.coordinator._transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM execution_requests").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM benchmark_managed_control_events").fetchone()[0], 0)

    def test_pause_policy_does_not_replace_safety_block_with_budget_pause(self):
        self.check_restart_policy("pause")

    def test_stop_policy_does_not_permanently_stop_safety_blocked_sibling(self):
        self.check_restart_policy("stop")

    def test_budget_amendment_explains_inherited_safety_block(self):
        config, binding, verified, _ = self.blocked_full()
        path = self.root / "amendment.json"
        path.write_text(json.dumps({"schema_version": 1, "run_sha256": binding,
            "scope": config["scope"], "amendment_id": "larger", "expected_cap": 2,
            "new_cap": 3, "authorization_source": "offline fixture amendment"}))
        try:
            amend_budget(self.root / "full.json", path)
        except BenchmarkError as exc:
            self.assertIn("blocked scope", str(exc))
        except BudgetError:
            self.fail("the benchmark did not identify its inherited safety block before amending")
        else:
            self.fail("the inherited safety block allowed a budget amendment")
        self.assertEqual(_control(verified), "running")
        self.assertEqual(BudgetLedger(config["database"]).balances(config["scope"])["cap"], 2)

    def test_child_block_retains_precedence_when_parent_is_also_blocked(self):
        config, _, verified, _ = self.blocked_full()
        local = verified.execution.block_scope(config["scope"], "local tool isolation failure",
                                              "offline local evidence")
        result = status(self.root / "full.json")
        self.assertEqual(result["status"], "blocked_safety")
        self.assertEqual(result["admission_block"], local)
        self.assertEqual(result["requests"][0]["blocked_reason"], "local tool isolation failure")

    def test_budget_boundary_rechecks_safety_block_in_control_transaction(self):
        config, _, verified, _ = self.blocked_full()
        for state in ("paused_budget", "stopped_budget"):
            with self.subTest(state=state):
                try:
                    _set_control(verified, state, "budget boundary",
                                 budget_scope=config["scope"])
                except TypeError:
                    self.fail("budget control has no transaction-bound safety-block check")
                self.assertEqual(_control(verified), "running")
        with verified.execution.coordinator._transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM benchmark_managed_control_events").fetchone()[0], 0)

    def unallocated_full(self, policy="pause"):
        self.config["on_budget_exhausted"] = policy
        config, _, _, _, _ = self.load("full")
        ledger = BudgetLedger(config["database"])
        ledger.create_aggregate("synthetic:experiment", 4, "SYN", 1,
                                "offline unallocated sibling fixture")
        verified = VerifiedExecution(config["database"], config["artifacts"])
        block = verified.execution.block_scope(
            "synthetic:experiment", "subscription paid extra usage observed",
            "offline inherited-block evidence")
        return config, ledger, verified, block

    def test_status_exposes_parent_block_before_child_allocation_exists(self):
        config, ledger, _, block = self.unallocated_full()
        self.assert_safety_status(status(self.root / "full.json"), block)
        self.assertIsNone(ledger.allocation_for(config["scope"]))
        self.assertEqual(ledger.aggregate_balances("synthetic:experiment")["allocated_cap"], 0)

    def check_unallocated_restart_policy(self, policy):
        config, ledger, verified, block = self.unallocated_full(policy)
        for _ in range(2):
            self.assert_safety_status(run(self.root / "full.json"), block)
        self.assertIsNone(ledger.allocation_for(config["scope"]))
        with verified.execution.coordinator._transaction() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM scopes WHERE scope=?", (config["scope"],)).fetchone())
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM execution_requests").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM benchmark_managed_control_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT state FROM benchmark_managed_control").fetchone()[0], "running")

    def test_pause_reports_unallocated_sibling_block_without_allocating(self):
        self.check_unallocated_restart_policy("pause")

    def test_stop_reports_unallocated_sibling_block_without_allocating(self):
        self.check_unallocated_restart_policy("stop")


if __name__ == "__main__":
    unittest.main()
