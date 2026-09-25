import multiprocessing
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from classification_bench.budget import BudgetError, BudgetLedger
from classification_bench.coordinator import Coordinator, CoordinatorError
from classification_bench.execution import ExecutionError, ExecutionLedger


MANIFEST = "a" * 64
INPUT = "b" * 64
RESPONSE = "c" * 64


def admission_worker(path, start, results):
    ledger = ExecutionLedger(path)
    start.wait()
    claim = ledger.claim("worker", 30)
    try:
        ledger.admit(claim["request_id"], claim["token"], MANIFEST, INPUT,
                     "shared", 7, bound_source="price ceiling")
        results.put((claim["request_id"], "admitted"))
    except (BudgetError, ExecutionError) as exc:
        results.put((claim["request_id"], str(exc)))


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "execution.sqlite"
        self.ledger = ExecutionLedger(self.path)
        self.budget = BudgetLedger(self.path)
        self.budget.create_scope("shared", 10, "USD", 100, "explicit test approval")

    def enroll_claim(self, request_id="one"):
        self.ledger.enqueue(request_id, MANIFEST, INPUT, "shared")
        return self.ledger.claim("worker", 30)

    def admit(self, claim, amount=6):
        return self.ledger.admit(claim["request_id"], claim["token"], MANIFEST, INPUT,
                                 "shared", amount, bound_source="price ceiling")

    def test_atomic_shared_cap_race(self):
        self.ledger.enqueue("one", MANIFEST, INPUT, "shared")
        self.ledger.enqueue("two", MANIFEST, INPUT, "shared")
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [context.Process(target=admission_worker,
                                     args=(str(self.path), start, results)) for _ in range(2)]
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sorted(x[1] for x in outcomes),
                         ["admitted", "reservation would exceed authorization cap"])
        self.assertEqual(self.budget.verify("shared")["active_reservations"], 7)
        self.assertEqual(sum(self.ledger.get(r)["request"]["state"] == "dispatch_intent"
                             for r in ("one", "two")), 1)

    def test_rollback_after_reserve_has_no_intent_or_leaked_reserve(self):
        claim = self.enroll_claim()
        with sqlite3.connect(self.path) as conn:
            conn.execute("""CREATE TRIGGER fail_intent BEFORE INSERT ON events
                WHEN NEW.event_type='dispatch_started'
                BEGIN SELECT RAISE(ABORT, 'injected crash'); END""")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "injected crash"):
            self.admit(claim)
        self.assertEqual(self.budget.verify("shared")["active_reservations"], 0)
        self.assertEqual(self.ledger.get("one")["request"]["state"], "claimed")
        self.assertEqual([e["event_type"] for e in self.ledger.coordinator.events("one")],
                         ["enqueued", "claimed"])

    def test_restart_preserves_ambiguous_intent_and_fences_replay(self):
        claim = self.enroll_claim()
        self.admit(claim)
        reopened = ExecutionLedger(self.path)
        self.assertIsNone(reopened.claim("another", 30))
        with self.assertRaisesRegex(ExecutionError, "already recorded"):
            reopened.admit("one", claim["token"], MANIFEST, INPUT, "shared", 6,
                           bound_source="price ceiling")
        self.assertEqual(BudgetLedger(self.path).verify("shared")["active_reservations"], 6)
        with self.assertRaisesRegex(CoordinatorError, "atomic ExecutionLedger"):
            Coordinator(self.path).complete("one", claim["token"], "outcome_unknown", "timeout")
        with self.assertRaisesRegex(BudgetError, "atomic ExecutionLedger"):
            BudgetLedger(self.path).mark_unknown("shared", claim["attempt_id"], "timeout")

    def test_missing_cost_becomes_hold_then_exact_settlement(self):
        claim = self.enroll_claim()
        self.admit(claim)
        first = self.ledger.complete("one", claim["token"], "response_saved", "response receipt",
                                     response_digest=RESPONSE, billing_reason="usage absent")
        self.assertEqual(first["budget"]["unknown_holds"], 6)
        self.assertEqual(self.budget.verify("shared")["known_charges"], 0)
        settled = self.ledger.settle_charge("one", "invoice-1", 4)
        self.assertEqual(settled["budget"]["known_charges"], 4)
        self.assertEqual(self.budget.verify("shared")["unknown_holds"], 0)
        repeated_settlement = self.ledger.settle_charge("one", "invoice-1", 4)
        self.assertEqual(set(repeated_settlement), set(settled))
        self.assertEqual(repeated_settlement["budget"], self.budget.balances("shared"))
        repeated_completion = self.ledger.complete("one", claim["token"], "response_saved",
                                                    "response receipt", response_digest=RESPONSE,
                                                    billing_reason="usage absent")
        self.assertEqual(set(repeated_completion), set(first))
        self.assertEqual(repeated_completion["budget"], self.budget.balances("shared"))
        with self.assertRaisesRegex(ExecutionError, "conflicting"):
            self.ledger.settle_charge("one", "invoice-2", 4)

    def test_atomic_terminal_settlement_above_bound_freezes_and_keeps_full_charge(self):
        claim = self.enroll_claim()
        self.admit(claim)
        first = self.ledger.complete("one", claim["token"], "response_saved", "receipt",
                                     response_digest=RESPONSE, settlement_id="charge-1", charge=12)
        self.assertEqual(first["budget"]["known_charges"], 12)
        self.assertTrue(first["budget"]["frozen"])
        self.assertEqual(self.budget.verify("shared")["known_charges"], 12)
        again = self.ledger.complete("one", claim["token"], "response_saved", "receipt",
                                     response_digest=RESPONSE, settlement_id="charge-1", charge=12)
        self.assertEqual(set(again), set(first))
        self.assertEqual(again["budget"], self.budget.balances("shared"))
        self.assertEqual(again["execution"]["charge"], 12)
        with self.assertRaisesRegex(ExecutionError, "conflicting"):
            self.ledger.complete("one", claim["token"], "response_saved", "receipt",
                                 response_digest=RESPONSE, settlement_id="charge-1", charge=9)
        self.ledger.enqueue("two", MANIFEST, INPUT, "shared")
        second = self.ledger.claim("worker", 30)
        with self.assertRaisesRegex(BudgetError, "frozen"):
            self.admit(second, 1)
        self.assertEqual(self.ledger.get("two")["request"]["state"], "claimed")

    def test_frozen_input_scope_stale_claim_and_legacy_guards(self):
        self.ledger.enqueue("one", MANIFEST, INPUT, "shared")
        self.assertIsNone(Coordinator(self.path).claim("legacy", 30))
        claim = self.ledger.claim("worker", 30)
        with self.assertRaisesRegex(ExecutionError, "does not match"):
            self.ledger.admit("one", claim["token"], MANIFEST, RESPONSE, "shared", 6,
                              bound_source="price ceiling")
        with self.assertRaisesRegex(ExecutionError, "stale"):
            self.ledger.admit("one", "wrong token", MANIFEST, INPUT, "shared", 6,
                              bound_source="price ceiling")
        with self.assertRaisesRegex(CoordinatorError, "atomic ExecutionLedger"):
            Coordinator(self.path).record_dispatch_intent("one", claim["token"])
        with self.assertRaisesRegex(BudgetError, "atomic ExecutionLedger"):
            self.budget.reserve("shared", claim["attempt_id"], 1, bound_source="bound")
        with self.assertRaisesRegex(ExecutionError, "same SQLite"):
            ExecutionLedger(self.path, budget_path=Path(self.temp.name) / "other.sqlite")
        self.assertEqual(self.budget.verify("shared")["active_reservations"], 0)

    def test_resolved_parent_alias_is_same_database_even_before_file_exists(self):
        real_dir = Path(self.temp.name) / "new-storage"
        real_dir.mkdir()
        alias_dir = Path(self.temp.name) / "storage-alias"
        alias_dir.symlink_to(real_dir, target_is_directory=True)
        real_path = real_dir / "new.sqlite"
        alias_path = alias_dir / "new.sqlite"
        ledger = ExecutionLedger(alias_path, budget_path=real_path)
        self.assertTrue(real_path.is_file())
        self.assertEqual(ledger.coordinator.path, alias_path)
        with self.assertRaisesRegex(ExecutionError, "same SQLite"):
            ExecutionLedger(alias_path, budget_path=real_dir / "different.sqlite")

    def test_expired_holder_cannot_reserve_after_reclaim(self):
        self.ledger.enqueue("one", MANIFEST, INPUT, "shared")
        old = self.ledger.claim("old", 0.01)
        time.sleep(0.03)
        new = ExecutionLedger(self.path).claim("new", 30)
        self.assertEqual(old["attempt_id"], new["attempt_id"])
        with self.assertRaisesRegex(ExecutionError, "stale"):
            self.admit(old)
        self.assertEqual(self.budget.verify("shared")["active_reservations"], 0)
        self.admit(new)
        self.assertEqual(self.budget.verify("shared")["active_reservations"], 6)

    def test_terminal_event_failure_rolls_back_settlement_and_response(self):
        claim = self.enroll_claim()
        self.admit(claim)
        with sqlite3.connect(self.path) as conn:
            conn.execute("""CREATE TRIGGER fail_response BEFORE INSERT ON events
                WHEN NEW.event_type='response_saved'
                BEGIN SELECT RAISE(ABORT, 'injected terminal crash'); END""")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "injected terminal crash"):
            self.ledger.complete("one", claim["token"], "response_saved", "receipt",
                                 response_digest=RESPONSE, settlement_id="charge-1", charge=4)
        self.assertEqual(self.budget.verify("shared")["active_reservations"], 6)
        self.assertEqual(self.budget.verify("shared")["known_charges"], 0)
        self.assertEqual(self.ledger.get("one")["request"]["state"], "dispatch_intent")


if __name__ == "__main__":
    unittest.main()
