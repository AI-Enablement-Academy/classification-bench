"""Same-database aggregate allocations; no provider or credential access."""

import multiprocessing
import shutil
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from classification_bench.budget import BudgetError, BudgetLedger
from classification_bench.execution import ExecutionLedger


def allocate_worker(path, name, start, results):
    start.wait()
    try:
        BudgetLedger(path).allocate_child("parent", name, "allocation-" + name, 7,
                                          name * 64, "approved " + name)
        results.put("allocated")
    except BudgetError as exc:
        results.put(str(exc))


def amendment_worker(path, amendment, start, results):
    start.wait()
    try:
        result = BudgetLedger(path).increase_allocation("smoke", amendment, 4, 7,
                                                        "approved " + amendment)
        results.put(result["cap"])
    except BudgetError as exc:
        results.put(str(exc))


def settlement_worker(path, settled, results):
    try:
        BudgetLedger(path).settle("smoke", "one", "receipt-one", 3)
        results.put("settled")
    finally:
        settled.set()


def sibling_worker(path, settled, results):
    settled.wait()
    try:
        BudgetLedger(path).reserve("full", "later", 1, bound_source="ceiling")
        results.put("reserved")
    except BudgetError as exc:
        results.put(str(exc))


class AggregateBudgetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="aggregate-ledger-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "authority.sqlite"
        self.ledger = BudgetLedger(self.path)
        self.ledger.create_aggregate("parent", 10, "USD", 1_000_000, "explicit parent authority")

    def child(self, name="smoke", cap=4, digest="a", parent="parent", **kwargs):
        return self.ledger.allocate_child(parent, name, "allocation-" + name, cap,
                                           digest * 64, "explicit " + name, **kwargs)

    def pair(self):
        self.child(phase="smoke")
        self.child("full", 6, "b", phase="full")

    def processes(self, targets):
        context = multiprocessing.get_context("spawn")
        start, results = context.Event(), context.Queue()
        processes = [context.Process(target=target, args=(str(self.path), *args, start, results))
                     for target, args in targets]
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        return outcomes

    def test_caps_are_allocated_once_and_actuals_are_not_double_counted(self):
        self.pair()
        self.ledger.reserve("smoke", "one", 3, bound_source="ceiling")
        self.ledger.settle("smoke", "one", "receipt-one", 2)
        self.ledger.reserve("full", "unknown", 2, bound_source="ceiling")
        self.ledger.mark_unknown("full", "unknown", "interrupted after intent")
        view = BudgetLedger(self.path).verify_aggregate("parent")
        self.assertEqual((view["allocated_cap"], view["accounted_exposure"], view["remaining"]), (10, 10, 0))
        self.assertEqual((view["known_charges"], view["active_reservations"], view["unknown_holds"]), (2, 0, 2))
        self.assertEqual(view["unallocated"], 0)
        self.assertFalse(view["frozen"])
        with self.assertRaisesRegex(BudgetError, "aggregate cap"):
            self.child("another", 1, "c")
        self.assertEqual(self.ledger.balances("parent")["allocated_cap"], 10)

    def test_identical_creation_survives_amendment_and_conflicts_fail(self):
        self.child()
        self.ledger.increase_allocation("smoke", "increase", 4, 6, "explicit increase")
        self.assertEqual(self.child()["cap"], 6)
        self.assertEqual(self.ledger.create_aggregate("parent", 10, "USD", 1_000_000,
                                                       "explicit parent authority")["allocated_cap"], 6)
        for changes in ({"cap": 5}, {"digest": "b"}, {"phase": "smoke"}):
            with self.assertRaisesRegex(BudgetError, "different terms"):
                self.child(**changes)
        with self.assertRaisesRegex(BudgetError, "allocation identity"):
            self.ledger.allocate_child("parent", "other", "allocation-smoke", 1,
                                       "b" * 64, "other authority")
        with self.assertRaisesRegex(BudgetError, "run identity"):
            self.child("other", 1)
        with self.assertRaisesRegex(BudgetError, "managed child"):
            self.ledger.increase_cap("smoke", "bypass", 6, 7, "explicit bypass")
        self.assertEqual(self.ledger.allocation_for("smoke")["run_sha256"], "a" * 64)

    def test_existing_unmanaged_scopes_cannot_be_attached_or_converted(self):
        self.ledger.create_scope("legacy", 3, "USD", 1_000_000, "legacy authority")
        with self.assertRaisesRegex(BudgetError, "existing scope"):
            self.ledger.allocate_child("parent", "legacy", "attach", 3,
                                       "c" * 64, "legacy authority")
        with self.assertRaisesRegex(BudgetError, "existing scope"):
            self.ledger.create_aggregate("legacy", 3, "USD", 1_000_000, "legacy authority")
        self.assertIsNone(self.ledger.allocation_for("legacy"))
        self.ledger.reserve("legacy", "ordinary", 3, bound_source="ceiling")
        self.assertEqual(self.ledger.verify("legacy")["active_reservations"], 3)

    def test_units_are_separate_and_explicit_mismatches_fail(self):
        self.ledger.create_aggregate("requests", 3, "REQ", 1, "request authority")
        self.child("subscription", 2, "c", parent="requests", currency="REQ", scale=1)
        self.child()
        for terms in ({"currency": "REQ"}, {"scale": 1}):
            with self.assertRaisesRegex(BudgetError, "units"):
                self.child("bad", 1, "d", **terms)
        self.assertEqual(self.ledger.aggregate_balances("requests")["unallocated"], 1)
        self.assertEqual(self.ledger.aggregate_balances("parent")["unallocated"], 6)
        with self.assertRaisesRegex(BudgetError, "aggregate parent"):
            self.ledger.reserve("parent", "direct", 1, bound_source="ceiling")
        with self.assertRaisesRegex(BudgetError, "aggregate parent"):
            self.ledger.allocate_child("smoke", "nested", "nested", 1,
                                       "e" * 64, "authority")

    def test_parent_and_child_amendments_are_conditional_audited_and_atomic(self):
        self.pair()
        with self.assertRaisesRegex(BudgetError, "aggregate cap"):
            self.ledger.increase_allocation("smoke", "larger", 4, 5, "larger authority")
        self.assertEqual(self.ledger.balances("smoke")["cap"], 4)
        self.ledger.increase_cap("parent", "parent-larger", 10, 12, "parent successor")
        first = self.ledger.increase_allocation("smoke", "larger", 4, 6, "larger authority")
        count = self.ledger.verify_aggregate("parent")["allocation_events"]
        self.assertEqual(self.ledger.increase_allocation("smoke", "larger", 4, 6, "larger authority"), first)
        self.assertEqual(self.ledger.verify_aggregate("parent")["allocation_events"], count)
        with self.assertRaisesRegex(BudgetError, "conflicting"):
            self.ledger.increase_allocation("smoke", "larger", 4, 7, "larger authority")
        with self.assertRaisesRegex(BudgetError, "expected"):
            self.ledger.increase_allocation("smoke", "stale", 4, 7, "authority")
        self.assertEqual(self.ledger.verify_aggregate("parent")["allocated_cap"], 12)

    def test_overrun_freezes_sibling_even_below_child_and_parent_caps(self):
        self.pair()
        self.ledger.reserve("smoke", "one", 2, bound_source="ceiling")
        self.ledger.reserve("full", "already", 2, bound_source="ceiling")
        self.ledger.settle("smoke", "one", "receipt-one", 3)
        view = self.ledger.verify_aggregate("parent")
        self.assertEqual(view["known_charges"], 3)
        self.assertFalse(view["over_cap"])
        self.assertTrue(view["frozen"])
        self.assertEqual(view["freeze"]["child_scope"], "smoke")
        with self.assertRaisesRegex(BudgetError, "aggregate.*frozen"):
            self.ledger.reserve("full", "later", 1, bound_source="ceiling")
        # An already-admitted sibling retains its observation and charge.
        self.ledger.settle("full", "already", "receipt-full", 1)
        self.ledger.increase_cap("parent", "cap", 10, 20, "successor parent")
        self.assertTrue(BudgetLedger(self.path).verify_aggregate("parent")["frozen"])
        sibling = self.ledger.balances("full")
        self.assertTrue(sibling["frozen"])
        self.assertTrue(sibling["aggregate_frozen"])
        self.assertFalse(sibling["scope_frozen"])
        self.assertEqual((sibling["remaining"], sibling["scope_remaining"]), (0, 5))
        for operation in (lambda: self.child("later", 1, "d"),
                          lambda: self.ledger.increase_allocation("full", "increase", 6, 7, "successor")):
            with self.assertRaisesRegex(BudgetError, "frozen"):
                operation()
        count = self.ledger.verify_aggregate("parent")["audit_events"]
        self.ledger.settle("smoke", "one", "receipt-one", 3)
        self.assertEqual(self.ledger.verify_aggregate("parent")["audit_events"], count)

    def test_above_allocated_exposure_is_recorded_in_full(self):
        self.pair()
        self.ledger.reserve("smoke", "one", 4, bound_source="ceiling")
        self.ledger.settle("smoke", "one", "receipt-one", 12)
        view = self.ledger.verify_aggregate("parent")
        self.assertEqual((view["known_charges"], view["allocated_cap"], view["accounted_exposure"]), (12, 10, 18))
        self.assertEqual(view["remaining"], -8)
        self.assertTrue(view["over_cap"])

    def test_execution_ledger_admission_and_completion_use_the_same_parent_guard(self):
        self.pair()
        execution = ExecutionLedger(self.path)
        for request, scope in (("first", "smoke"), ("second", "full")):
            execution.enqueue(request, "a" * 64, "b" * 64, scope)
        first = execution.claim("worker", 30, request_id="first")
        second = execution.claim("worker", 30, request_id="second")
        execution.admit("first", first["token"], "a" * 64, "b" * 64, "smoke", 2, bound_source="ceiling")
        execution.complete("first", first["token"], "response_saved", "receipt",
                           response_digest="c" * 64, settlement_id="settled", charge=3)
        with self.assertRaisesRegex(BudgetError, "aggregate.*frozen"):
            execution.admit("second", second["token"], "a" * 64, "b" * 64, "full", 1, bound_source="ceiling")
        self.assertEqual(execution.get("second")["request"]["state"], "claimed")
        self.assertEqual(self.ledger.balances("full")["active_reservations"], 0)

    def test_settlement_and_ancestor_freeze_roll_back_together(self):
        self.pair()
        self.ledger.reserve("smoke", "one", 2, bound_source="ceiling")
        with patch.object(self.ledger, "_freeze_aggregate_in", side_effect=OSError("write failed")):
            with self.assertRaisesRegex(OSError, "write failed"):
                self.ledger.settle("smoke", "one", "receipt-one", 3)
        view = BudgetLedger(self.path).verify_aggregate("parent")
        self.assertEqual((view["known_charges"], view["active_reservations"]), (0, 2))
        self.assertFalse(view["frozen"])
        self.ledger.settle("smoke", "one", "receipt-one", 3)
        self.assertTrue(self.ledger.verify_aggregate("parent")["frozen"])

    def test_two_process_allocations_cannot_multiply_parent_cap(self):
        outcomes = self.processes([(allocate_worker, (name,)) for name in ("a", "b")])
        self.assertEqual(outcomes.count("allocated"), 1)
        self.assertTrue(any("aggregate cap" in outcome for outcome in outcomes))
        view = self.ledger.verify_aggregate("parent")
        self.assertEqual((view["allocated_cap"], len(view["children"])), (7, 1))

    def test_two_process_amendments_cannot_apply_stale_expected_cap(self):
        self.child()
        self.child("full", 3, "b")
        outcomes = self.processes([(amendment_worker, (name,)) for name in ("a", "b")])
        self.assertEqual(outcomes.count(7), 1)
        self.assertTrue(any(isinstance(outcome, str) and "expected" in outcome for outcome in outcomes))
        self.assertEqual(self.ledger.verify_aggregate("parent")["allocated_cap"], 10)

    def test_committed_overrun_blocks_a_real_sibling_process(self):
        self.pair()
        self.ledger.reserve("smoke", "one", 2, bound_source="ceiling")
        context = multiprocessing.get_context("spawn")
        settled, results = context.Event(), context.Queue()
        processes = [context.Process(target=target, args=(str(self.path), settled, results))
                     for target in (settlement_worker, sibling_worker)]
        for process in processes:
            process.start()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertIn("settled", outcomes)
        self.assertTrue(any("aggregate" in outcome and "frozen" in outcome for outcome in outcomes))

    def test_copied_authority_database_is_rejected_without_changing_copy(self):
        self.child()
        copied = self.path.with_name("copy.sqlite")
        shutil.copyfile(self.path, copied)
        copied.chmod(0o600)
        original = copied.read_bytes()
        with self.assertRaisesRegex(BudgetError, "authority database identity"):
            BudgetLedger(copied)
        self.assertEqual(copied.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(BudgetLedger(self.path).verify_aggregate("parent")["allocated_cap"], 4)

    def test_binding_and_audit_are_immutable_and_projection_tampering_is_detected(self):
        self.child()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            for statement in ("UPDATE aggregate_allocations SET run_sha256='changed'",
                              "DELETE FROM aggregate_allocations",
                              "UPDATE aggregate_allocation_events SET expected_cap=1",
                              "DELETE FROM aggregate_allocation_events",
                              "UPDATE aggregate_authority SET database_id='changed'"):
                with self.assertRaises(sqlite3.DatabaseError):
                    conn.execute(statement)
            conn.execute("UPDATE aggregate_allocations SET allocated_cap=5")
        with self.assertRaisesRegex(BudgetError, "allocation.*audit"):
            self.ledger.verify_aggregate("parent")

    def test_invalid_terms_fail_without_publishing_a_child(self):
        for changes in ({"cap": True}, {"cap": 0}, {"digest": "z"}, {"phase": "guessed"}):
            with self.assertRaises(BudgetError):
                self.child(**changes)
        self.assertEqual(self.ledger.verify_aggregate("parent")["children"], [])

    def test_unknown_hold_and_zero_charge_do_not_refund_the_allocation(self):
        self.child()
        self.ledger.reserve("smoke", "one", 4, bound_source="ceiling")
        self.ledger.mark_unknown("smoke", "one", "charge unavailable")
        self.assertEqual(self.ledger.aggregate_balances("parent")["unknown_holds"], 4)
        self.ledger.settle("smoke", "one", "receipt", 0, zero_charge_evidence="explicit fixture zero")
        view = self.ledger.verify_aggregate("parent")
        self.assertEqual((view["allocated_cap"], view["accounted_exposure"], view["remaining"]), (4, 4, 6))
        self.assertEqual((view["known_charges"], view["unknown_holds"]), (0, 0))
        self.assertEqual(self.ledger.allocation_for("smoke")["initial_cap"], 4)

    def test_failed_allocation_amendment_rolls_back_both_projections(self):
        self.child()
        original = self.ledger._increase_cap_in
        def fail_after_child_cap(*args):
            original(*args)
            raise OSError("interrupted before allocation event")
        with patch.object(self.ledger, "_increase_cap_in", side_effect=fail_after_child_cap):
            with self.assertRaises(OSError):
                self.ledger.increase_allocation("smoke", "larger", 4, 6, "explicit larger")
        self.assertEqual(self.ledger.balances("smoke")["cap"], 4)
        view = self.ledger.verify_aggregate("parent")
        self.assertEqual((view["allocated_cap"], view["allocation_events"]), (4, 1))

    def test_replacing_authority_at_the_same_path_is_not_an_implicit_restore(self):
        backup = self.path.with_name("backup.sqlite")
        shutil.copyfile(self.path, backup)
        backup.chmod(0o600)
        displaced = self.path.with_name("displaced.sqlite")
        self.path.rename(displaced)
        backup.rename(self.path)
        with self.assertRaisesRegex(BudgetError, "authority database identity"):
            BudgetLedger(self.path)

    def test_second_parent_stays_independent_after_first_parent_overrun(self):
        self.child()
        self.ledger.create_aggregate("requests", 2, "REQ", 1, "request authority")
        self.child("subscription", 2, "c", parent="requests")
        self.ledger.reserve("smoke", "one", 1, bound_source="ceiling")
        self.ledger.settle("smoke", "one", "receipt", 2)
        self.ledger.reserve("subscription", "still-allowed", 1, bound_source="one invocation")
        self.assertFalse(self.ledger.verify_aggregate("requests")["frozen"])

    def test_held_charge_settlement_through_execution_ledger_freezes_parent(self):
        self.pair()
        execution = ExecutionLedger(self.path)
        execution.enqueue("one", "a" * 64, "b" * 64, "smoke")
        claim = execution.claim("worker", 30)
        execution.admit("one", claim["token"], "a" * 64, "b" * 64, "smoke", 1, bound_source="ceiling")
        execution.complete("one", claim["token"], "outcome_unknown", "interrupted", billing_reason="charge unknown")
        self.assertEqual(self.ledger.verify_aggregate("parent")["unknown_holds"], 1)
        execution.settle_charge("one", "late-receipt", 2)
        self.assertTrue(self.ledger.balances("full")["aggregate_frozen"])

    def test_explicit_parent_safety_block_is_inherited_by_sibling_and_survives_amendments(self):
        self.pair()
        execution = ExecutionLedger(self.path)
        self.ledger.reserve("full", "already", 2, bound_source="ceiling")
        block = execution.block_scope("parent", "paid overage observed", "immutable receipt hash")
        child = self.ledger.balances("full")
        self.assertTrue(child["frozen"])
        self.assertFalse(child["scope_frozen"])
        self.assertFalse(child["aggregate_frozen"])
        self.assertEqual(child["aggregate_admission_block"], block)
        self.assertEqual((child["remaining"], child["scope_remaining"]), (0, 4))
        with self.assertRaisesRegex(BudgetError, "aggregate parent admission blocked.*paid overage"):
            self.ledger.reserve("smoke", "later", 1, bound_source="ceiling")
        self.ledger.settle("full", "already", "receipt", 1)
        self.ledger.increase_cap("parent", "successor", 10, 20, "explicit successor")
        view = BudgetLedger(self.path).verify_aggregate("parent")
        self.assertTrue(view["frozen"])
        self.assertFalse(view["scope_frozen"])
        self.assertEqual(view["admission_block"], block)
        self.assertEqual((view["remaining"], view["scope_remaining"]), (0, 10))
        for operation in (lambda: self.child("new", 1, "d"),
                          lambda: self.ledger.increase_allocation("smoke", "new", 4, 5, "successor")):
            with self.assertRaisesRegex(BudgetError, "admission blocked"):
                operation()

    def test_execution_admission_checks_parent_safety_block_inside_reservation_transaction(self):
        self.child()
        execution = ExecutionLedger(self.path)
        execution.enqueue("one", "a" * 64, "b" * 64, "smoke")
        claim = execution.claim("worker", 30)
        execution.block_scope("parent", "quota exhausted", "quota receipt")
        with self.assertRaisesRegex(BudgetError, "quota exhausted"):
            execution.admit("one", claim["token"], "a" * 64, "b" * 64, "smoke", 1, bound_source="ceiling")
        self.assertEqual(execution.get("one")["request"]["state"], "claimed")
        self.assertEqual(self.ledger.balances("smoke")["active_reservations"], 0)

    def test_child_only_safety_block_does_not_implicitly_become_a_parent_block(self):
        self.pair()
        execution = ExecutionLedger(self.path)
        execution.block_scope("smoke", "scoped finding", "scoped receipt")
        self.ledger.reserve("full", "allowed", 1, bound_source="ceiling")
        self.assertIsNone(self.ledger.aggregate_balances("parent")["admission_block"])
        self.assertFalse(self.ledger.balances("full")["frozen"])
