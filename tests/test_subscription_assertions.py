"""Fresh operator evidence renews guards without rewriting frozen experiments."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from classification_bench.budget import BudgetLedger
from classification_bench.execution import ExecutionLedger
from classification_bench.manifest import digest


RUN = "a" * 64
CONFIG = "b" * 64
MANIFEST = "c" * 64
INPUT = "d" * 64
RESPONSE = "e" * 64


def timestamp(value):
    return value.isoformat().replace("+00:00", "Z")


class SubscriptionAssertionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module("classification_bench.subscription_assertions")
        except ModuleNotFoundError:
            self.fail("The append-only subscription assertion renewal ledger is unavailable")
        self.error = self.module.SubscriptionAssertionError
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.execution = ExecutionLedger(self.root / "run.sqlite")
        self.budget = BudgetLedger(self.root / "run.sqlite")
        self.budget.create_scope("own-account", 5, "REQ", 1, "explicit offline fixture grant")
        with self.execution.coordinator._transaction() as conn:
            conn.execute("CREATE TABLE benchmark_binding(singleton INTEGER PRIMARY KEY,run_sha256 TEXT NOT NULL)")
            conn.execute("INSERT INTO benchmark_binding VALUES(1,?)", (RUN,))
        self.ledger = self.module.SubscriptionAssertionLedger(self.execution, self.root / "artifacts")
        self.key = ("own-account", RUN, "own configuration")
        self.now = datetime.now(timezone.utc)
        self.initial = {"extra_usage_disabled": True,
                        "verified_at": timestamp(self.now - timedelta(days=2)),
                        "source": "original frozen account check; offline fixture"}

    def bind(self, assertion=None, **kwargs):
        terms = {"scope": self.key[0], "run_sha256": RUN, "config_id": self.key[2],
                 "configuration_sha256": CONFIG, "adapter": "codex", "assertion": assertion or self.initial}
        terms.update(kwargs)
        return self.ledger.bind_initial(**terms)

    def renewal(self, *, renewal_id="guard-1", expected_revision=0, checked_at=None, source="new operator account check; offline fixture"):
        check = json.dumps({"observed": "paid extra usage disabled", "fixture": True,
                            "source": source}, sort_keys=True).encode()
        terms = {"schema_version": 1, "renewal_id": renewal_id, "run_sha256": RUN,
                 "scope": self.key[0], "config_id": self.key[2], "configuration_sha256": CONFIG,
                 "adapter": "codex", "expected_revision": expected_revision,
                 "extra_usage_disabled": True, "verified_at": timestamp(checked_at or self.now),
                 "source": source, "account_check_sha256": digest(check)}
        return terms, check

    def claim(self, request_id="saved request"):
        self.execution.enqueue(request_id, MANIFEST, INPUT, self.key[0])
        return self.execution.claim("offline fixture", 60, request_id=request_id)

    def test_expired_initial_history_can_renew_without_changing_identity(self):
        initial = self.bind()
        self.assertEqual(initial["revision"], 0)
        with self.execution.coordinator._transaction() as conn:
            with self.assertRaisesRegex(self.error, "expired"):
                self.ledger.require_fresh_in(conn, self.key)
        before = self.budget.verify(self.key[0])
        terms, evidence = self.renewal()
        unchanged = deepcopy(terms)
        renewed = self.ledger.renew(terms, evidence)
        self.assertEqual((renewed["revision"], renewed["configuration_sha256"], renewed["run_sha256"]), (1, CONFIG, RUN))
        self.assertEqual(renewed["verification"], "operator_assertion")
        self.assertEqual(terms, unchanged)
        self.assertEqual(self.budget.verify(self.key[0]), before)
        with self.execution.coordinator._transaction() as conn:
            self.assertEqual(self.ledger.require_fresh_in(conn, self.key, expected_revision=1), renewed)
            self.assertEqual(conn.execute("SELECT run_sha256 FROM benchmark_binding").fetchone()[0], RUN)
        self.assertEqual(self.ledger.history(self.key), [initial, renewed])
        reference = renewed["account_check_ref"]
        self.assertEqual((self.root / "artifacts" / reference["path"]).read_bytes(), evidence)
        self.assertEqual((self.root / "artifacts" / reference["path"]).stat().st_mode & 0o777, 0o600)

    def test_cap_amendment_does_not_renew_an_expired_assertion(self):
        original = self.bind()
        self.budget.increase_cap(self.key[0], "explicit increase", 5, 7, "offline fixture cap approval")
        self.assertEqual(self.ledger.current(*self.key), original)
        with self.execution.coordinator._transaction() as conn:
            with self.assertRaisesRegex(self.error, "expired"):
                self.ledger.require_fresh_in(conn, self.key)

    def test_initial_binding_is_idempotent_but_changed_sources_are_rejected(self):
        original = self.bind()
        self.assertEqual(self.bind(), original)
        for changes in ({"source": "another source"}, {"verified_at": timestamp(self.now - timedelta(days=3))}):
            altered = {**self.initial, **changes}
            with self.subTest(changes=changes), self.assertRaisesRegex(self.error, "initial.*changed"):
                self.bind(altered)
        with self.assertRaises(self.error):
            self.bind(configuration_sha256="f" * 64)
        with self.assertRaises(self.error):
            self.bind(adapter="claude_code")

    def test_new_renewals_reject_false_future_expired_and_malformed_assertions(self):
        self.bind()
        terms, evidence = self.renewal()
        invalid = [{"extra_usage_disabled": False}, {"extra_usage_disabled": 1},
                   {"verified_at": timestamp(self.now + timedelta(hours=1))},
                   {"verified_at": timestamp(self.now - timedelta(days=1, seconds=1))},
                   {"verified_at": "2026-10-08Z"}, {"verified_at": "2026-10-08T12:00:00+01:00"},
                   {"source": " "}, {"source": "bad\nsource"}, {"expected_revision": True},
                   {"configuration_sha256": "f" * 64}, {"adapter": "claude_code"},
                   {"account_check_sha256": "f" * 64}, {"extra": "unsupported"}]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(self.error):
                self.ledger.renew({**terms, **change}, evidence)
        self.assertEqual(len(self.ledger.history(self.key)), 1)

    def test_renewal_retry_is_idempotent_and_conflicting_reuse_fails(self):
        self.bind()
        terms, evidence = self.renewal()
        renewed = self.ledger.renew(terms, evidence)
        with patch.object(self.module, "_now", return_value=self.now + timedelta(days=3)):
            self.assertEqual(self.ledger.renew(terms, evidence), renewed)
            with self.execution.coordinator._transaction() as conn:
                with self.assertRaisesRegex(self.error, "expired"):
                    self.ledger.require_fresh_in(conn, self.key)
        with self.assertRaisesRegex(self.error, "conflict"):
            self.ledger.renew({**terms, "source": "conflicting operator source"}, evidence)
        self.assertEqual(len(self.ledger.history(self.key)), 2)

    def test_stale_revision_and_nonincreasing_account_check_are_rejected(self):
        self.bind()
        self.ledger.renew(*self.renewal())
        with self.assertRaisesRegex(self.error, "revision"):
            self.ledger.renew(*self.renewal(renewal_id="stale"))
        with self.assertRaisesRegex(self.error, "newer"):
            self.ledger.renew(*self.renewal(renewal_id="same date", expected_revision=1))
        terms, evidence = self.renewal(renewal_id="guard-2", expected_revision=1, checked_at=self.now + timedelta(seconds=1))
        with patch.object(self.module, "_now", return_value=self.now + timedelta(seconds=2)):
            self.assertEqual(self.ledger.renew(terms, evidence)["revision"], 2)

    def test_concurrent_renewals_serialize_without_losing_the_first_revision(self):
        self.bind()
        attempts = [self.renewal(renewal_id=f"different-{i}", source=f"operator check {i}") for i in range(6)]
        def attempt(value):
            try:
                return self.ledger.renew(*value)
            except self.error as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(attempt, attempts))
        winners = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]["revision"], 1)
        self.assertTrue(all("revision" in result for result in results if isinstance(result, str)))
        self.assertEqual(len(self.ledger.history(self.key)), 2)

    def test_admission_callback_audit_uses_the_callers_transaction(self):
        self.bind()
        guard = self.ledger.renew(*self.renewal())
        claim = self.claim()
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.execution.coordinator._transaction() as conn:
                self.ledger.require_fresh_in(conn, self.key, expected_revision=1,
                                             request_id=claim["request_id"], admission_token=claim["token"])
                raise RuntimeError("rollback the admission transaction")
        with self.execution.coordinator._transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM subscription_guard_admissions").fetchone()[0], 0)
            self.ledger.require_fresh_in(conn, self.key, expected_revision=1,
                                         request_id=claim["request_id"], admission_token=claim["token"])
        with self.execution.coordinator._transaction() as conn:
            audit = dict(conn.execute("SELECT * FROM subscription_guard_admissions").fetchone())
        self.assertEqual((audit["request_id"], audit["admission_token"], audit["assertion_id"]),
                         (claim["request_id"], claim["token"], guard["assertion_id"]))
        self.assertEqual(self.budget.balances(self.key[0])["active_reservations"], 0)

    def test_expired_wrong_claim_and_changed_revision_create_no_admission_audit(self):
        self.bind()
        claim = self.claim()
        with self.execution.coordinator._transaction() as conn:
            with self.assertRaisesRegex(self.error, "expired"):
                self.ledger.require_fresh_in(conn, self.key, request_id=claim["request_id"], admission_token=claim["token"])
        self.ledger.renew(*self.renewal())
        for kwargs in ({"expected_revision": 0}, {"request_id": claim["request_id"], "admission_token": "wrong"},
                       {"request_id": claim["request_id"]}, {"request_id": "missing", "admission_token": claim["token"]}):
            with self.execution.coordinator._transaction() as conn:
                with self.subTest(kwargs=kwargs), self.assertRaises(self.error):
                    self.ledger.require_fresh_in(conn, self.key, **kwargs)
        with self.execution.coordinator._transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM subscription_guard_admissions").fetchone()[0], 0)
        self.assertEqual(self.execution.get(claim["request_id"])["request"]["state"], "claimed")
        self.assertEqual(self.budget.balances(self.key[0])["active_reservations"], 0)

    def test_renewal_preserves_safety_blocks_unknown_holds_and_saved_completion(self):
        self.bind()
        claim = self.claim()
        self.execution.admit(claim["request_id"], claim["token"], MANIFEST, INPUT, self.key[0], 1, bound_source="fixture capacity")
        self.execution.complete(claim["request_id"], claim["token"], "outcome_unknown", "ambiguous evidence", billing_reason="unknown outcome")
        block = self.execution.block_scope(self.key[0], "observed paid extra usage", "original unsafe receipt")
        before = self.budget.verify(self.key[0])
        self.ledger.renew(*self.renewal())
        self.assertEqual(self.execution.admission_block(self.key[0]), block)
        self.assertEqual(self.budget.verify(self.key[0]), before)
        self.assertEqual(self.budget.balances(self.key[0])["unknown_holds"], 1)
        with self.execution.coordinator._transaction() as conn:
            with self.assertRaisesRegex(self.error, "blocked"):
                self.ledger.require_fresh_in(conn, self.key)
        self.execution.reconcile(claim["request_id"], "saved receipt reconciliation", "response_saved", response_digest=RESPONSE)
        self.assertEqual(self.execution.get(claim["request_id"])["request"]["state"], "reconciled")

    def test_immutable_revisions_and_admission_history_reject_update_delete(self):
        self.bind()
        self.ledger.renew(*self.renewal())
        claim = self.claim()
        with self.execution.coordinator._transaction() as conn:
            self.ledger.require_fresh_in(conn, self.key, request_id=claim["request_id"], admission_token=claim["token"])
        for table in ("subscription_assertion_revisions", "subscription_guard_admissions"):
            for command in (f"UPDATE {table} SET config_id='edited'", f"DELETE FROM {table}"):
                with self.execution.coordinator._transaction() as conn:
                    with self.subTest(command=command), self.assertRaises(sqlite3.IntegrityError):
                        conn.execute(command)

    def test_unbound_wrong_unit_and_unknown_scope_fail_closed(self):
        self.budget.create_scope("dollars", 5, "USD", 1000000, "offline fixture")
        for changes in ({"scope": "missing"}, {"scope": "dollars"}, {"run_sha256": "f" * 64}, {"adapter": "openrouter"}):
            with self.subTest(changes=changes), self.assertRaises(self.error):
                self.bind(**changes)
        with self.assertRaises(self.error):
            self.ledger.current(*self.key)
        with self.execution.coordinator._transaction() as conn:
            conn.execute("DELETE FROM benchmark_binding")
        with self.assertRaisesRegex(self.error, "binding"):
            self.bind()

    def test_plural_managed_runs_bind_the_exact_scope_and_storage_request(self):
        with self.execution.coordinator._transaction() as conn:
            conn.execute("DROP TABLE benchmark_binding")
            conn.execute("CREATE TABLE benchmark_managed_runs(run_sha256 TEXT PRIMARY KEY,scope TEXT UNIQUE NOT NULL,parent_scope TEXT NOT NULL,allocation_id TEXT UNIQUE NOT NULL)")
            conn.execute("INSERT INTO benchmark_managed_runs VALUES(?,?,?,?)", (RUN, self.key[0], "parent", "allocation-one"))
        self.bind()
        self.ledger.renew(*self.renewal())
        claim = self.claim("managed-storage:logical-request")
        with self.execution.coordinator._transaction() as conn:
            self.ledger.require_fresh_in(conn, self.key, request_id=claim["request_id"], admission_token=claim["token"])
        self.budget.create_scope("other-account", 5, "REQ", 1, "separate fixture scope")
        with self.assertRaisesRegex(self.error, "binding"):
            self.bind(scope="other-account")

    def test_missing_or_changed_evidence_is_not_silently_accepted(self):
        self.bind()
        guard = self.ledger.renew(*self.renewal())
        path = self.root / "artifacts" / guard["account_check_ref"]["path"]
        path.unlink()
        with self.assertRaises(self.error):
            self.ledger.current(*self.key)
        with self.assertRaises(self.error):
            self.module.SubscriptionAssertionLedger.read_current(self.root / "run.sqlite", self.root / "artifacts", self.key)
        with self.execution.coordinator._transaction() as conn:
            with self.assertRaises(self.error):
                self.ledger.require_fresh_in(conn, self.key)

    def test_concurrent_admission_snapshot_and_renewal_cannot_mix_revisions(self):
        self.bind()
        guard = self.ledger.renew(*self.renewal(checked_at=self.now - timedelta(seconds=5)))
        claim = self.claim()
        terms, evidence = self.renewal(renewal_id="next guard", expected_revision=1)
        start = Barrier(2)
        def admit_snapshot():
            start.wait()
            try:
                with self.execution.coordinator._transaction() as conn:
                    selected = self.ledger.require_fresh_in(conn, self.key, expected_revision=1,
                        request_id=claim["request_id"], admission_token=claim["token"])
                    return selected["assertion_id"]
            except self.error as exc:
                return str(exc)
        def renew_guard():
            start.wait()
            return self.ledger.renew(terms, evidence)
        with ThreadPoolExecutor(max_workers=2) as pool:
            admission = pool.submit(admit_snapshot)
            renewal = pool.submit(renew_guard)
            admitted, renewed = admission.result(), renewal.result()
        self.assertEqual(renewed["revision"], 2)
        with self.execution.coordinator._transaction() as conn:
            audits = list(conn.execute("SELECT * FROM subscription_guard_admissions"))
        if admitted == guard["assertion_id"]:
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0]["revision"], 1)
            self.assertEqual(audits[0]["assertion_id"], guard["assertion_id"])
        else:
            self.assertIn("revision changed", admitted)
            self.assertEqual(audits, [])

    def test_expiry_does_not_prevent_completion_of_an_existing_grant(self):
        initial = {**self.initial, "verified_at": timestamp(self.now)}
        self.bind(initial)
        claim = self.claim()
        with self.execution.coordinator._transaction() as conn:
            self.ledger.require_fresh_in(conn, self.key, request_id=claim["request_id"], admission_token=claim["token"])
        self.execution.admit(claim["request_id"], claim["token"], MANIFEST, INPUT, self.key[0], 1, bound_source="fixture capacity")
        with patch.object(self.module, "_now", return_value=self.now + timedelta(days=2)):
            with self.execution.coordinator._transaction() as conn:
                with self.assertRaisesRegex(self.error, "expired"):
                    self.ledger.require_fresh_in(conn, self.key)
            self.execution.complete(claim["request_id"], claim["token"], "response_saved", "saved receipt",
                                    response_digest=RESPONSE, settlement_id="request-capacity", charge=1)
        self.assertEqual(self.execution.get(claim["request_id"])["request"]["state"], "response_saved")
        self.assertEqual(self.budget.balances(self.key[0])["known_charges"], 1)

    def test_read_current_reuses_verified_history_without_constructors_or_writes(self):
        self.bind()
        guard = self.ledger.renew(*self.renewal())
        before = {str(path.relative_to(self.root)): path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        with patch.object(self.module.SubscriptionAssertionLedger, "__init__", side_effect=AssertionError("reader initialized ledger")), \
                patch.object(BudgetLedger, "__init__", side_effect=AssertionError("reader initialized budget")):
            result = self.module.SubscriptionAssertionLedger.read_current(self.root / "run.sqlite", self.root / "artifacts", self.key)
        self.assertEqual(result, guard)
        after = {str(path.relative_to(self.root)): path.read_bytes()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_read_current_absent_database_table_or_key_creates_nothing(self):
        missing = self.root / "absent-directory" / "absent.sqlite"
        self.assertIsNone(self.module.SubscriptionAssertionLedger.read_current(missing, self.root / "absent-artifacts", self.key))
        self.assertFalse(missing.parent.exists())
        empty = self.root / "existing-no-assertions.sqlite"
        ExecutionLedger(empty)
        before = empty.read_bytes()
        self.assertIsNone(self.module.SubscriptionAssertionLedger.read_current(empty, self.root / "absent-artifacts", self.key))
        self.assertEqual(empty.read_bytes(), before)
        self.bind()
        self.assertIsNone(self.module.SubscriptionAssertionLedger.read_current(self.root / "run.sqlite", self.root / "artifacts", (*self.key[:2], "uninitialized configuration")))
        self.assertFalse((self.root / "absent-artifacts").exists())

    def test_read_current_rejects_nonprivate_database_and_evidence(self):
        self.bind()
        guard = self.ledger.renew(*self.renewal())
        database = self.root / "run.sqlite"
        database.chmod(0o644)
        with self.assertRaises(self.error):
            self.module.SubscriptionAssertionLedger.read_current(database, self.root / "artifacts", self.key)
        database.chmod(0o600)
        evidence = self.root / "artifacts" / guard["account_check_ref"]["path"]
        evidence.chmod(0o644)
        with self.assertRaises(self.error):
            self.module.SubscriptionAssertionLedger.read_current(database, self.root / "artifacts", self.key)
        with self.assertRaises(self.error):
            self.ledger.current(*self.key)


    def paid_renewal(self, *, state=False, cap=5, approval=True, **kwargs):
        terms, evidence = self.renewal(**kwargs)
        terms.update(schema_version=2, extra_usage_disabled=state,
                     paid_credit_authorization={"approved": True, "request_cap": cap,
                        "approved_at": timestamp(self.now - timedelta(days=2)),
                        "source": "explicit human paid credit approval; offline fixture"} if approval else None)
        evidence = json.dumps({"fixture": True, "extra_usage_disabled": state,
                               "verified_at": terms["verified_at"],
                               "approval": terms["paid_credit_authorization"]}, sort_keys=True).encode()
        terms["account_check_sha256"] = digest(evidence)
        return terms, evidence

    def test_v2_enabled_and_unknown_require_explicit_paid_approval(self):
        self.bind()
        for state in (False,):
            with self.subTest(state=state):
                terms, evidence = self.paid_renewal(state=state)
                guard = self.ledger.renew(terms, evidence)
                with self.execution.coordinator._transaction() as conn:
                    self.assertEqual(self.ledger.require_fresh_in(conn, self.key), guard)
                self.assertEqual(guard["extra_usage_disabled"], state)
                self.assertIsNotNone(guard["paid_credit_authorization_ref"])
                # A fresh observation can explicitly return to deny policy.
                terms, evidence = self.paid_renewal(state=state, approval=False,
                    renewal_id=f"deny-{state}", expected_revision=guard["revision"],
                    checked_at=self.now + timedelta(microseconds=10))
                with patch.object(self.module, "_now", return_value=self.now + timedelta(seconds=1)):
                    denied = self.ledger.renew(terms, evidence)
                    with self.execution.coordinator._transaction() as conn:
                        with self.assertRaisesRegex(self.error, "disabled or explicitly authorized"):
                            self.ledger.require_fresh_in(conn, self.key)
                self.assertIsNone(denied["paid_credit_authorization"])

    def test_v2_unknown_account_state_and_standing_approval_survive_observation_renewal(self):
        self.bind()
        first = self.ledger.renew(*self.paid_renewal(state=None))
        terms, evidence = self.paid_renewal(state=None, renewal_id="new-observation", expected_revision=1,
            checked_at=self.now + timedelta(days=3))
        terms["paid_credit_authorization"] = first["paid_credit_authorization"]
        with patch.object(self.module, "_now", return_value=self.now + timedelta(days=3)):
            second = self.ledger.renew(terms, evidence)
            with self.execution.coordinator._transaction() as conn:
                self.assertEqual(self.ledger.require_fresh_in(conn, self.key), second)
        self.assertEqual(second["paid_credit_authorization_ref"], first["paid_credit_authorization_ref"])
        self.assertNotEqual(second["account_check_ref"], first["account_check_ref"])
        self.assertEqual(self.ledger.history(self.key)[0]["schema_version"], 1)

    def test_v2_paid_cap_increase_requires_new_explicit_approval(self):
        self.bind()
        first = self.ledger.renew(*self.paid_renewal())
        self.budget.increase_cap(self.key[0], "raise-cap", 5, 7, "separate request-cap authorization")
        with self.execution.coordinator._transaction() as conn:
            with self.assertRaisesRegex(self.error, "request cap exceeds paid credit approval"):
                self.ledger.require_fresh_in(conn, self.key)
        terms, evidence = self.paid_renewal(cap=7, renewal_id="raise-paid-cap", expected_revision=1,
            checked_at=self.now + timedelta(seconds=1))
        with patch.object(self.module, "_now", return_value=self.now + timedelta(seconds=1)):
            with self.assertRaisesRegex(self.error, "newer explicit approval"):
                self.ledger.renew(terms, evidence)
            terms["paid_credit_authorization"]["approved_at"] = timestamp(self.now)
            second = self.ledger.renew(terms, evidence)
            with self.execution.coordinator._transaction() as conn:
                self.assertEqual(self.ledger.require_fresh_in(conn, self.key), second)
        self.assertNotEqual(first["paid_credit_authorization_ref"], second["paid_credit_authorization_ref"])

    def test_revoked_approval_cannot_return_after_multiple_deny_observations(self):
        self.bind()
        with patch.object(self.module, "_now", return_value=self.now):
            first = self.ledger.renew(*self.paid_renewal(state=None))
        for revision in (1, 2):
            denial_time = self.now + timedelta(seconds=revision)
            terms, evidence = self.paid_renewal(state=None, approval=False,
                renewal_id=f"deny-{revision}", expected_revision=revision, checked_at=denial_time)
            with patch.object(self.module, "_now", return_value=denial_time):
                self.ledger.renew(terms, evidence)
        terms, evidence = self.paid_renewal(state=None, renewal_id="reapprove", expected_revision=3,
            checked_at=self.now + timedelta(seconds=3))
        terms["paid_credit_authorization"] = deepcopy(first["paid_credit_authorization"])
        with patch.object(self.module, "_now", return_value=self.now + timedelta(seconds=3)):
            # Neither the withdrawn approval nor one between the two denials
            # covers an observation recorded after the latest withdrawal.
            for approved_at in (first["paid_credit_authorization"]["approved_at"],
                                timestamp(self.now + timedelta(seconds=1, microseconds=1)),
                                timestamp(self.now + timedelta(seconds=2))):
                terms["paid_credit_authorization"]["approved_at"] = approved_at
                with self.subTest(approved_at=approved_at), self.assertRaisesRegex(self.error, "after denial"):
                    self.ledger.renew(terms, evidence)
            self.assertEqual(len(self.ledger.history(self.key)), 4)
            with self.execution.coordinator._transaction() as conn:
                with self.assertRaisesRegex(self.error, "disabled or explicitly authorized"):
                    self.ledger.require_fresh_in(conn, self.key)
            terms["paid_credit_authorization"]["approved_at"] = timestamp(self.now + timedelta(seconds=3))
            fresh = self.ledger.renew(terms, evidence)
            with self.execution.coordinator._transaction() as conn:
                self.assertEqual(self.ledger.require_fresh_in(conn, self.key), fresh)
        self.assertNotEqual(fresh["paid_credit_authorization_ref"], first["paid_credit_authorization_ref"])

    def test_v1_deny_after_paid_permission_requires_fresh_reapproval(self):
        self.bind()
        with patch.object(self.module, "_now", return_value=self.now):
            first = self.ledger.renew(*self.paid_renewal())
        terms, evidence = self.renewal(renewal_id="legacy-deny", expected_revision=1,
            checked_at=self.now + timedelta(seconds=1))
        with patch.object(self.module, "_now", return_value=self.now + timedelta(seconds=1)):
            self.ledger.renew(terms, evidence)
        terms, evidence = self.paid_renewal(renewal_id="reapprove", expected_revision=2,
            checked_at=self.now + timedelta(seconds=2))
        terms["paid_credit_authorization"] = deepcopy(first["paid_credit_authorization"])
        with patch.object(self.module, "_now", return_value=self.now + timedelta(seconds=2)):
            with self.assertRaisesRegex(self.error, "after denial"):
                self.ledger.renew(terms, evidence)
            terms["paid_credit_authorization"]["approved_at"] = timestamp(self.now + timedelta(seconds=2))
            self.ledger.renew(terms, evidence)

    def test_uninterrupted_changed_terms_cannot_restore_older_approval(self):
        self.bind()
        with patch.object(self.module, "_now", return_value=self.now):
            first = self.ledger.renew(*self.paid_renewal())
        terms, evidence = self.paid_renewal(renewal_id="approval-b", expected_revision=1,
            checked_at=self.now + timedelta(seconds=1))
        terms["paid_credit_authorization"]["source"] = "new explicit human permission B; offline fixture"
        terms["paid_credit_authorization"]["approved_at"] = timestamp(self.now)
        with patch.object(self.module, "_now", return_value=self.now + timedelta(seconds=1)):
            second = self.ledger.renew(terms, evidence)
        terms, evidence = self.paid_renewal(renewal_id="changed-terms", expected_revision=2,
            checked_at=self.now + timedelta(seconds=2))
        with patch.object(self.module, "_now", return_value=self.now + timedelta(seconds=2)):
            for approval in (deepcopy(first["paid_credit_authorization"]),
                             {**second["paid_credit_authorization"], "request_cap": 6},
                             {**second["paid_credit_authorization"], "source": "different source with same time"}):
                terms["paid_credit_authorization"] = approval
                with self.subTest(approval=approval), self.assertRaisesRegex(self.error, "newer explicit approval"):
                    self.ledger.renew(terms, evidence)
        self.assertEqual(self.ledger.current(*self.key), second)

    def test_v2_rejects_forged_or_implicit_paid_approval(self):
        self.bind()
        for mutation in ({"approved": 1}, {"approved": False}, {"request_cap": True},
                         {"request_cap": 0}, {"source": ""},
                         {"approved_at": timestamp(self.now + timedelta(days=1))}):
            with self.subTest(mutation=mutation):
                terms, evidence = self.paid_renewal()
                terms["paid_credit_authorization"].update(mutation)
                with self.assertRaises(self.error):
                    self.ledger.renew(terms, evidence)
        terms, evidence = self.paid_renewal(cap=4)
        with self.assertRaisesRegex(self.error, "request cap exceeds"):
            self.ledger.renew(terms, evidence)
        self.assertEqual(len(self.ledger.history(self.key)), 1)

    def test_admitted_historical_policy_cannot_be_reinterpreted_after_approval(self):
        original = self.bind({**self.initial, "verified_at": timestamp(self.now - timedelta(seconds=1))})
        claim = self.claim()
        def guard(conn):
            self.ledger.require_fresh_in(conn, self.key, 0, request_id=claim["request_id"], admission_token=claim["token"])
        self.execution.admit(claim["request_id"], claim["token"], MANIFEST, INPUT,
                             self.key[0], 1, admission_guard=guard, bound_source="offline fixture REQ grant")
        self.ledger.renew(*self.paid_renewal(state=None))
        admitted = self.ledger.admitted_assertion(claim["request_id"], claim["token"])
        self.assertEqual(admitted, original)
        self.assertFalse(self.module.paid_credit_approved(admitted))
        with self.assertRaisesRegex(self.error, "exact admitted request"):
            self.ledger.admitted_assertion(claim["request_id"], "wrong-token")

    def test_v2_initial_evidence_is_bound_private_and_optional_for_restart(self):
        terms, evidence = self.paid_renewal(state=None)
        assertion = self.module.assertion_fields(terms)
        path = self.root / "initial-check.json"
        path.write_bytes(evidence)
        path.chmod(0o600)
        guard = self.ledger.bind_initial(*self.key, CONFIG, "codex", assertion, account_check_path=path)
        path.unlink()
        self.assertEqual(self.ledger.bind_initial(*self.key, CONFIG, "codex", assertion), guard)
        with self.execution.coordinator._transaction() as conn:
            self.assertEqual(self.ledger.require_fresh_in(conn, self.key), guard)
        self.assertEqual(self.module.SubscriptionAssertionLedger.read_current(
            self.root / "run.sqlite", self.root / "artifacts", self.key), guard)


if __name__ == "__main__":
    unittest.main()
