"""Permanent scope blocks serialize with real SQLite admission transactions."""

from contextlib import closing
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from classification_bench.budget import BudgetError, BudgetLedger
from classification_bench.execution import ExecutionError, ExecutionLedger


MANIFEST = "a" * 64
INPUT = "b" * 64
RESPONSE = "c" * 64


def concurrent_guard_worker(path, action, claim, ready, start, results):
    ready_sent = False
    try:
        ledger = ExecutionLedger(path)
        ready.put(action)
        ready_sent = True
        start.wait()
        if action.startswith("block"):
            result = ledger.block_scope("shared", action + " observed failure", action + " receipt")
            results.put((action, result))
        else:
            try:
                ledger.admit("one", claim["token"], MANIFEST, INPUT, "shared", 5,
                             bound_source="declared request bound")
                results.put((action, "admitted"))
            except ExecutionError as exc:
                results.put((action, str(exc)))
    except Exception as exc:
        if not ready_sent:
            ready.put(action)
        results.put((action, f"worker failed: {type(exc).__name__}: {exc}"))


class AdmissionGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "execution.sqlite"
        self.ledger = ExecutionLedger(self.path)
        self.budget = BudgetLedger(self.path)
        self.budget.create_scope("shared", 20, "REQ", 1, "explicit test request authorization")

    def claim(self, request_id="one", scope="shared"):
        self.ledger.enqueue(request_id, MANIFEST, INPUT, scope)
        return self.ledger.claim("test-worker", 30, request_id=request_id)

    def admit(self, claim, scope="shared"):
        return self.ledger.admit(claim["request_id"], claim["token"], MANIFEST, INPUT, scope, 5,
                                 bound_source="declared request bound")

    def run_concurrently(self, actions, claim=None):
        context = multiprocessing.get_context("spawn")
        ready, results = context.Queue(), context.Queue()
        start = context.Event()
        processes = [context.Process(target=concurrent_guard_worker,
                                     args=(str(self.path), action, claim, ready, start, results))
                     for action in actions]
        for process in processes:
            process.start()
        for _ in processes:
            ready.get(timeout=20)
        start.set()
        output = dict(results.get(timeout=20) for _ in processes)
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        return output

    def test_blocked_claim_creates_no_reservation_or_dispatch_intent(self):
        claim = self.claim()
        before = self.budget.verify("shared")
        block = self.ledger.block_scope("shared", "quota exhausted", "quota receipt")
        self.assertEqual(block["scope"], "shared")
        self.assertEqual(block["reason"], "quota exhausted")
        self.assertEqual(block["evidence_id"], "quota receipt")
        self.assertGreater(block["blocked_at"], 0)
        with self.assertRaisesRegex(ExecutionError, "admission blocked"):
            self.admit(claim)
        self.assertEqual(self.budget.verify("shared"), before)
        saved = self.ledger.get("one")
        self.assertEqual(saved["request"]["state"], "claimed")
        self.assertEqual(saved["execution"]["state"], "enrolled")
        self.assertIsNone(saved["execution"]["reserve_amount"])
        self.assertEqual([event["event_type"] for event in self.ledger.coordinator.events("one")],
                         ["enqueued", "claimed"])
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)

    def test_first_block_is_preserved_idempotently_across_restart_and_cap_increase(self):
        self.assertIsNone(self.ledger.admission_block("shared"))
        first = self.ledger.block_scope("shared", "paid overage observed", "original receipt")
        repeated = self.ledger.block_scope("shared", "quota exhausted later", "later receipt")
        self.assertEqual(repeated, first)
        reopened = ExecutionLedger(self.path)
        self.assertEqual(reopened.admission_block("shared"), first)
        self.budget.increase_cap("shared", "approved-test-cap", 20, 30, "explicit test amendment")
        self.assertEqual(reopened.admission_block("shared"), first)
        with self.assertRaisesRegex(ExecutionError, "admission blocked"):
            self.admit(self.claim())
        self.assertFalse(self.budget.verify("shared")["frozen"])

    def test_block_does_not_affect_an_independent_scope(self):
        self.budget.create_scope("independent", 20, "REQ", 1, "separate explicit test authorization")
        self.ledger.block_scope("shared", "isolation failure", "isolation receipt")
        self.assertIsNone(self.ledger.admission_block("independent"))
        independent = self.claim("independent-one", "independent")
        self.admit(independent, "independent")
        self.assertEqual(self.budget.verify("independent")["active_reservations"], 5)
        self.assertEqual(self.budget.verify("shared")["active_reservations"], 0)

    def test_scope_must_exist_and_all_block_fields_are_validated(self):
        with self.assertRaisesRegex(BudgetError, "unknown authorization scope"):
            self.ledger.block_scope("missing", "failure", "receipt")
        with self.assertRaisesRegex(BudgetError, "unknown authorization scope"):
            self.ledger.admission_block("missing")
        for scope, reason, evidence in (("", "failure", "receipt"), (" shared", "failure", "receipt"),
                                        ("shared", "", "receipt"), ("shared", " failure", "receipt"),
                                        ("shared", "failure", ""), ("shared", "failure", 12)):
            with self.subTest(scope=scope, reason=reason, evidence=evidence):
                with self.assertRaises(ValueError):
                    self.ledger.block_scope(scope, reason, evidence)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM execution_admission_blocks").fetchone()[0], 0)

    def test_admitted_work_can_complete_reconcile_and_settle_after_blocking(self):
        known, unknown = self.claim("known"), self.claim("unknown")
        self.admit(known)
        self.admit(unknown)
        first = self.ledger.block_scope("shared", "paid overage observed", "guard receipt")
        completed = self.ledger.complete("known", known["token"], "response_saved", "response receipt",
                                         response_digest=RESPONSE, settlement_id="known charge", charge=3)
        self.assertEqual(completed["budget"]["known_charges"], 3)
        held = self.ledger.complete("unknown", unknown["token"], "outcome_unknown", "uncertain receipt",
                                    billing_reason="charge unavailable")
        self.assertEqual(held["budget"]["unknown_holds"], 5)
        reconciled = self.ledger.reconcile("unknown", "recovery receipt", "response_saved",
                                           response_digest=RESPONSE)
        self.assertEqual(reconciled["execution"]["state"], "reconciled")
        settled = self.ledger.settle_charge("unknown", "late charge", 2)
        self.assertEqual(settled["budget"]["known_charges"], 5)
        self.assertEqual(settled["budget"]["active_reservations"], 0)
        self.assertEqual(settled["budget"]["unknown_holds"], 0)
        self.assertFalse(settled["budget"]["frozen"])
        self.assertEqual(self.ledger.admission_block("shared"), first)
        with self.assertRaisesRegex(ExecutionError, "admission blocked"):
            self.admit(self.claim("later"))

    def test_first_block_audit_record_is_immutable(self):
        first = self.ledger.block_scope("shared", "tool isolation failure", "tool receipt")
        with closing(sqlite3.connect(self.path)) as conn:
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                conn.execute("UPDATE execution_admission_blocks SET reason='cleared' WHERE scope='shared'")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                conn.execute("DELETE FROM execution_admission_blocks WHERE scope='shared'")
        self.assertEqual(self.ledger.admission_block("shared"), first)

    def test_historical_database_without_guard_table_migrates_preserving_claims(self):
        claim = self.claim()
        before = self.ledger.get("one")
        budget_before = self.budget.verify("shared")
        # A historical database has the existing execution/request/budget data,
        # but no guard table. Dropping the empty new table reproduces that schema.
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("DROP TABLE execution_admission_blocks")
            conn.commit()
        reopened = ExecutionLedger(self.path)
        self.assertIsNone(reopened.admission_block("shared"))
        self.assertEqual(reopened.get("one"), before)
        self.assertEqual(reopened.budget.verify("shared"), budget_before)
        reopened.block_scope("shared", "guard after migration", "migration receipt")
        with self.assertRaisesRegex(ExecutionError, "admission blocked"):
            reopened.admit("one", claim["token"], MANIFEST, INPUT, "shared", 5,
                           bound_source="declared request bound")

    def test_concurrent_blocks_preserve_the_same_first_audit_record(self):
        outputs = self.run_concurrently(("block-a", "block-b"))
        self.assertEqual(outputs["block-a"], outputs["block-b"])
        self.assertEqual(self.ledger.admission_block("shared"), outputs["block-a"])
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM execution_admission_blocks").fetchone()[0], 1)

    def test_concurrent_admit_and_block_serialize_without_unbound_reservation(self):
        claim = self.claim()
        outputs = self.run_concurrently(("admit", "block"), claim)
        guard = outputs["block"]
        request = self.ledger.get("one")
        events = self.ledger.coordinator.events("one")
        if outputs["admit"] == "admitted":
            self.assertEqual(request["request"]["state"], "dispatch_intent")
            self.assertEqual(self.budget.verify("shared")["active_reservations"], 5)
            dispatched = next(event for event in events if event["event_type"] == "dispatch_started")
            self.assertLessEqual(dispatched["recorded_at"], guard["blocked_at"])
        else:
            self.assertIn("admission blocked", outputs["admit"])
            self.assertEqual(request["request"]["state"], "claimed")
            self.assertEqual(self.budget.verify("shared")["active_reservations"], 0)
            self.assertFalse(any(event["event_type"] == "dispatch_started" for event in events))
        self.assertEqual(self.ledger.admission_block("shared"), guard)
        with self.assertRaisesRegex(ExecutionError, "admission blocked"):
            self.admit(self.claim("subsequent"))


if __name__ == "__main__":
    unittest.main()
