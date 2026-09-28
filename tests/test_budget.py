import multiprocessing
import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from classification_bench.budget import BudgetError, BudgetLedger


def reserve_worker(path, attempt_id, start, results):
    start.wait()
    try:
        BudgetLedger(path).reserve("shared", attempt_id, 7, bound_source="price ceiling A")
        results.put((attempt_id, "reserved"))
    except BudgetError as exc:
        results.put((attempt_id, str(exc)))


def first_open_worker(path, start, results):
    start.wait()
    try:
        ledger = BudgetLedger(path)
        ledger.create_scope("new", 10, "USD", 100, "explicit shared authorization")
        results.put("opened")
    except Exception as exc:
        results.put(f"{type(exc).__name__}: {exc}")


def cap_increase_worker(path, amendment_id, start, results):
    start.wait()
    try:
        view = BudgetLedger(path).increase_cap("shared", amendment_id, 10, 20,
                                               f"authorization {amendment_id}")
        results.put((amendment_id, view["cap"]))
    except BudgetError as exc:
        results.put((amendment_id, str(exc)))


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.sqlite"
        self.ledger = BudgetLedger(self.path)
        self.ledger.create_scope("shared", 10, "USD", 100, "explicit test authorization")

    def test_scope_terms_are_explicit_and_stable(self):
        with self.assertRaises(BudgetError):
            self.ledger.reserve("unknown", "a", 1, bound_source="bound")
        with self.assertRaises(BudgetError):
            self.ledger.create_scope("other", 0, "USD", 100, "approval")
        with self.assertRaises(BudgetError):
            self.ledger.create_scope("other", 5, "USD", 100, "")
        before = self.ledger.verify("shared")
        self.assertEqual(before["audit_events"], 1)
        self.assertEqual(self.ledger.create_scope("shared", 10, "USD", 100,
                                                  "explicit test authorization")["cap"], 10)
        with self.assertRaisesRegex(BudgetError, "different terms"):
            self.ledger.create_scope("shared", 11, "USD", 100, "explicit test authorization")
        self.assertEqual(self.ledger.verify("shared")["audit_events"], 1)

    def test_explicit_cap_increase_is_conditional_audited_and_idempotent(self):
        self.ledger.reserve("shared", "a", 8, bound_source="bound")
        self.ledger.mark_unknown("shared", "a", "possible dispatch")
        after = self.ledger.increase_cap("shared", "approval-2", 10, 20,
                                         "user authorization record 2")
        self.assertEqual(after["cap"], 20)
        self.assertEqual(after["unknown_holds"], 8)
        self.assertEqual(after["remaining"], 12)
        self.assertEqual(self.ledger.verify("shared")["audit_events"], 4)
        self.assertEqual(self.ledger.increase_cap("shared", "approval-2", 10, 20,
                                                   "user authorization record 2"), after)
        self.assertEqual(self.ledger.verify("shared")["audit_events"], 4)
        self.assertEqual(BudgetLedger(self.path).create_scope("shared", 10, "USD", 100,
                                  "explicit test authorization")["cap"], 20)
        with self.assertRaisesRegex(BudgetError, "different terms"):
            self.ledger.create_scope("shared", 20, "USD", 100, "explicit test authorization")

    def test_cap_increase_rejects_conflicting_or_stale_amendments(self):
        with self.assertRaises(BudgetError):
            self.ledger.increase_cap("shared", "a", 10, 10, "authorization")
        with self.assertRaises(BudgetError):
            self.ledger.increase_cap("shared", "a", 10, 9, "authorization")
        with self.assertRaises(BudgetError):
            self.ledger.increase_cap("shared", "a", 10, 11, "")
        self.ledger.increase_cap("shared", "a", 10, 11, "authorization")
        with self.assertRaisesRegex(BudgetError, "conflicting cap amendment"):
            self.ledger.increase_cap("shared", "a", 10, 12, "authorization")
        with self.assertRaisesRegex(BudgetError, "changed since expected"):
            self.ledger.increase_cap("shared", "b", 10, 12, "authorization 2")
        self.assertEqual(self.ledger.balances("shared")["cap"], 11)

    def test_cap_increase_does_not_clear_above_bound_freeze(self):
        self.ledger.reserve("shared", "a", 5, bound_source="bound")
        self.ledger.settle("shared", "a", "receipt", 12)
        after = self.ledger.increase_cap("shared", "approval-2", 10, 20,
                                         "user authorization record 2")
        self.assertTrue(after["frozen"])
        self.assertFalse(after["over_cap"])
        with self.assertRaisesRegex(BudgetError, "frozen"):
            self.ledger.reserve("shared", "b", 1, bound_source="bound")

    def test_cap_amendment_events_are_immutable_and_verified(self):
        self.ledger.increase_cap("shared", "approval-2", 10, 20, "authorization 2")
        with closing(sqlite3.connect(self.path)) as conn:
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE cap_events SET new_cap=30 WHERE amendment_id='approval-2'")
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM cap_events WHERE amendment_id='approval-2'")
            conn.execute("UPDATE scopes SET cap=30 WHERE scope='shared'")
            conn.commit()
        with self.assertRaisesRegex(BudgetError, "cap disagrees"):
            self.ledger.verify("shared")

    def test_concurrent_cap_increases_require_one_expected_current_cap(self):
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [context.Process(target=cap_increase_worker,
                                     args=(str(self.path), name, start, results))
                     for name in ("approval-a", "approval-b")]
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sorted(str(result) for _, result in outcomes),
                         ["20", "scope cap changed since expected value"])
        self.assertEqual(BudgetLedger(self.path).verify("shared")["audit_events"], 2)

    def test_existing_ledger_without_cap_table_is_backfilled(self):
        self.ledger.reserve("shared", "a", 3, bound_source="bound")
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("DROP TRIGGER cap_events_no_update")
            conn.execute("DROP TRIGGER cap_events_no_delete")
            conn.execute("DROP TABLE cap_events")
            conn.commit()
        reopened = BudgetLedger(self.path)
        self.assertEqual(reopened.verify("shared")["audit_events"], 2)
        self.assertEqual(reopened.increase_cap("shared", "approval-2", 10, 20,
                                                "new authorization")["cap"], 20)

    def test_new_database_and_journal_are_private_under_normal_umask(self):
        path = Path(self.temp.name) / "normal-umask.sqlite"
        old_umask = os.umask(0o022)
        try:
            ledger = BudgetLedger(path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            ledger.create_scope("private", 10, "USD", 100, "private source")
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE scopes SET authorization_source='changed' WHERE scope='private'")
                journal = Path(str(path) + "-journal")
                self.assertTrue(journal.exists())
                self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
                conn.rollback()
        finally:
            os.umask(old_umask)

    def test_existing_open_or_symlinked_database_is_rejected_without_chmod(self):
        path = Path(self.temp.name) / "open.sqlite"
        path.write_bytes(b"existing")
        path.chmod(0o644)
        with self.assertRaisesRegex(BudgetError, "not a private regular file"):
            BudgetLedger(path)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        link = Path(self.temp.name) / "linked.sqlite"
        link.symlink_to(path)
        with self.assertRaisesRegex(BudgetError, "not a private regular file"):
            BudgetLedger(link)

    def test_two_processes_can_initialize_same_private_database(self):
        path = Path(self.temp.name) / "first-open.sqlite"
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [context.Process(target=first_open_worker, args=(str(path), start, results))
                     for _ in range(2)]
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(outcomes, ["opened", "opened"])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(BudgetLedger(path).verify("new")["audit_events"], 1)

    def test_reserve_unknown_hold_and_later_settlement_survive_restart(self):
        self.ledger.reserve("shared", "a", 8, bound_source="provider ceiling snapshot")
        state = self.ledger.mark_unknown("shared", "a", "dispatch outcome not observed")
        self.assertEqual((state["known_charges"], state["active_reservations"],
                          state["unknown_holds"], state["remaining"]), (0, 0, 8, 2))
        with self.assertRaises(BudgetError):
            self.ledger.reserve("shared", "b", 3, bound_source="provider ceiling snapshot")
        reopened = BudgetLedger(self.path)
        state = reopened.settle("shared", "a", "provider-charge-1", 5)
        self.assertEqual((state["known_charges"], state["active_reservations"],
                          state["unknown_holds"], state["remaining"]), (5, 0, 0, 5))
        self.assertEqual(reopened.verify("shared")["audit_events"], 4)
        reopened.reserve("shared", "b", 5, bound_source="provider ceiling snapshot")
        self.assertEqual(reopened.balances("shared")["remaining"], 0)

    def test_settlement_is_idempotent_and_conflicts_fail(self):
        self.ledger.reserve("shared", "a", 6, bound_source="bound")
        first = self.ledger.settle("shared", "a", "receipt-1", 4)
        events = self.ledger.verify("shared")["audit_events"]
        self.assertEqual(self.ledger.settle("shared", "a", "receipt-1", 4), first)
        self.assertEqual(self.ledger.verify("shared")["audit_events"], events)
        with self.assertRaisesRegex(BudgetError, "conflicting settlement"):
            self.ledger.settle("shared", "a", "receipt-2", 4)
        with self.assertRaisesRegex(BudgetError, "conflicting settlement"):
            self.ledger.settle("shared", "a", "receipt-1", 5)
        with self.assertRaisesRegex(BudgetError, "already reserved"):
            self.ledger.reserve("shared", "a", 1, bound_source="bound")
        self.ledger.reserve("shared", "b", 1, bound_source="bound")
        with self.assertRaisesRegex(BudgetError, "identity already used"):
            self.ledger.settle("shared", "b", "receipt-1", 1)
        self.assertEqual(self.ledger.balances("shared")["active_reservations"], 1)

    def test_above_bound_records_full_charge_and_freezes_dispatch(self):
        self.ledger.reserve("shared", "a", 5, bound_source="ceiling A")
        self.ledger.reserve("shared", "b", 3, bound_source="ceiling B")
        state = self.ledger.settle("shared", "a", "receipt-a", 12)
        self.assertEqual((state["known_charges"], state["active_reservations"],
                          state["remaining"]), (12, 3, -5))
        self.assertTrue(state["over_cap"])
        self.assertTrue(state["frozen"])
        with self.assertRaisesRegex(BudgetError, "frozen"):
            self.ledger.reserve("shared", "c", 0, no_fee_evidence="provider no-fee receipt")
        self.ledger.settle("shared", "b", "receipt-b", 2)
        self.assertEqual(self.ledger.verify("shared")["known_charges"], 14)

    def test_explicit_zero_is_allowed_but_missing_cost_is_not(self):
        with self.assertRaises(BudgetError):
            self.ledger.reserve("shared", "zero", 0)
        self.ledger.reserve("shared", "zero", 0,
                            no_fee_evidence="verified local subscription no per-call fee")
        with self.assertRaises(BudgetError):
            self.ledger.settle("shared", "zero", "zero-receipt", None)
        with self.assertRaises(BudgetError):
            self.ledger.settle("shared", "zero", "zero-receipt", 0)
        state = self.ledger.settle("shared", "zero", "zero-receipt", 0,
                                   zero_charge_evidence="explicit provider zero")
        self.assertEqual(state["known_charges"], 0)
        self.assertEqual(self.ledger.verify("shared")["audit_events"], 3)

    def test_two_processes_cannot_both_reserve_past_shared_cap(self):
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [context.Process(target=reserve_worker,
                                     args=(str(self.path), attempt, start, results))
                     for attempt in ("a", "b")]
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sorted(outcome for _, outcome in outcomes),
                         ["reservation would exceed authorization cap", "reserved"])
        state = BudgetLedger(self.path).verify("shared")
        self.assertEqual(state["active_reservations"], 7)
        self.assertEqual(state["audit_events"], 2)

    def test_audit_events_are_append_only_and_balances_detect_tamper(self):
        self.ledger.reserve("shared", "a", 4, bound_source="bound")
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                with self.assertRaises(sqlite3.DatabaseError):
                    conn.execute("UPDATE audit_events SET active_after=0 WHERE event_type='reserved'")
                with self.assertRaises(sqlite3.DatabaseError):
                    conn.execute("DELETE FROM audit_events WHERE event_type='reserved'")
                conn.execute("UPDATE scopes SET active=3 WHERE scope='shared'")
        with self.assertRaisesRegex(BudgetError, "disagree"):
            self.ledger.verify("shared")


if __name__ == "__main__":
    unittest.main()
