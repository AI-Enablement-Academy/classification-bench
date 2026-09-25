import multiprocessing
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from classification_bench.budget import BudgetLedger
from classification_bench.evidence import EvidenceError, put_artifact, read_artifact
from classification_bench.execution import ExecutionError
from classification_bench.verified_execution import VerifiedExecution, VerifiedExecutionError


MANIFEST = b'{"execution_schema":1,"roles":["user"]}'
REQUEST = b'{"messages":[{"role":"user","content":"example"}]}'
RESPONSE = b'{"choice":"a"}'


def receipt_worker(database, store, source_id, start, results):
    wrapper = VerifiedExecution(database, store)
    state = wrapper.execution.get("request-1")
    start.wait()
    try:
        saved = wrapper.save_response("request-1", state["request"]["token"],
                                      RESPONSE, "application/json", source_id)
        results.put((source_id, saved["receipt_ref"].sha256))
    except VerifiedExecutionError as exc:
        results.put((source_id, str(exc)))


def crash_before_receipt_index(database, store, token):
    wrapper = VerifiedExecution(database, store)
    wrapper._index_receipt = lambda request_id, receipt_ref: os._exit(77)
    wrapper.save_response("request-1", token, RESPONSE, "application/json", "crash-observation")
    os._exit(78)


def discover_after_crash(database, store, token, results):
    wrapper = VerifiedExecution(database, store)
    recovered = wrapper.recover_discovered_response(
        "request-1", token, billing_reason="usage not observed")
    results.put((recovered["request"]["state"], recovered["budget"]["unknown_holds"],
                 wrapper.receipt_for("request-1").sha256))


class VerifiedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.database = root / "ledger.sqlite"
        self.store = root / "artifacts"
        self.wrapper = VerifiedExecution(self.database, self.store)
        self.budget = BudgetLedger(self.database)
        self.budget.create_scope("shared", 10, "USD", 100, "explicit test scope")
        self.enrolled = self.wrapper.enqueue_bytes("request-1", "shared", MANIFEST, REQUEST)

    def claim_admit(self):
        claim = self.wrapper.execution.claim("worker", 30)
        admitted = self.wrapper.admit_verified(
            "request-1", claim["token"], "shared", 6,
            self.enrolled["manifest_ref"], self.enrolled["request_ref"],
            bound_source="price ceiling")
        return claim, admitted

    def test_request_artifacts_verified_before_admission(self):
        claim = self.wrapper.execution.claim("worker", 30)
        request_path = self.store / self.enrolled["request_ref"].path
        request_path.write_bytes(b"corrupted")
        with self.assertRaisesRegex(EvidenceError, "mismatch"):
            self.wrapper.admit_verified("request-1", claim["token"], "shared", 6,
                                        self.enrolled["manifest_ref"], self.enrolled["request_ref"],
                                        bound_source="price ceiling")
        self.assertEqual(self.budget.verify("shared")["active_reservations"], 0)
        self.assertEqual(self.wrapper.execution.get("request-1")["request"]["state"], "claimed")

    def test_published_receipt_recovers_response_without_another_claim(self):
        claim, _ = self.claim_admit()
        saved = self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                           "application/json", "provider-observation-1")
        self.assertNotIn(claim["token"].encode(), read_artifact(self.store, saved["receipt_ref"]))
        self.assertEqual(self.wrapper.receipt_for("request-1"), saved["receipt_ref"])
        self.assertEqual(self.wrapper.execution.get("request-1")["request"]["state"],
                         "dispatch_intent")
        reopened = VerifiedExecution(self.database, self.store)
        self.assertIsNone(reopened.execution.claim("replacement", 30))
        result = reopened.recover_response("request-1", claim["token"],
                                           billing_reason="usage not observed")
        self.assertEqual(result["request"]["state"], "response_saved")
        self.assertEqual(result["budget"]["unknown_holds"], 6)
        self.assertEqual(result["request"]["evidence_id"], saved["receipt_ref"].sha256)
        again = reopened.recover_response("request-1", claim["token"],
                                          billing_reason="usage not observed")
        self.assertEqual(again["request"]["response_digest"], saved["response_ref"].sha256)

    def test_repeated_recovery_rejects_conflicting_charge(self):
        claim, _ = self.claim_admit()
        self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                   "application/json", "observation-1")
        first = self.wrapper.recover_response("request-1", claim["token"],
                                              settlement_id="charge-1", charge=4)
        again = self.wrapper.recover_response("request-1", claim["token"],
                                              settlement_id="charge-1", charge=4)
        self.assertEqual(set(first), set(again))
        with self.assertRaisesRegex(ExecutionError, "conflicting completion"):
            self.wrapper.recover_response("request-1", claim["token"],
                                          settlement_id="charge-1", charge=5)
        self.assertEqual(self.budget.verify("shared")["known_charges"], 4)

    def test_orphan_receipt_requires_explicit_ref_and_raw_blob_is_insufficient(self):
        claim, _ = self.claim_admit()
        captured = []
        original = self.wrapper._index_receipt

        def fail_before_index(request_id, receipt_ref):
            captured.append(receipt_ref)
            raise RuntimeError("simulated crash before receipt index")

        self.wrapper._index_receipt = fail_before_index
        with self.assertRaisesRegex(RuntimeError, "simulated crash"):
            self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                       "application/json", "observation-1")
        self.wrapper._index_receipt = original
        self.assertIsNone(self.wrapper.receipt_for("request-1"))
        with self.assertRaisesRegex(VerifiedExecutionError, "explicit receipt"):
            self.wrapper.recover_response("request-1", claim["token"],
                                          billing_reason="usage missing")
        raw = put_artifact(self.store, RESPONSE, "application/json")
        with self.assertRaisesRegex(VerifiedExecutionError, "invalid response receipt schema"):
            self.wrapper.recover_response("request-1", claim["token"], receipt_ref=raw,
                                          billing_reason="usage missing")
        result = self.wrapper.recover_response("request-1", claim["token"],
                                               receipt_ref=captured[0],
                                               billing_reason="usage missing")
        self.assertEqual(result["request"]["state"], "response_saved")
        self.assertEqual(self.wrapper.receipt_for("request-1"), captured[0])

    def test_response_corruption_blocks_terminal_event_and_preserves_reserve(self):
        claim, _ = self.claim_admit()
        saved = self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                           "application/json", "observation-1")
        (self.store / saved["response_ref"].path).write_bytes(b"corrupted")
        with self.assertRaisesRegex(EvidenceError, "mismatch"):
            self.wrapper.recover_response("request-1", claim["token"],
                                          billing_reason="usage missing")
        self.assertEqual(self.wrapper.execution.get("request-1")["request"]["state"],
                         "dispatch_intent")
        self.assertEqual(self.budget.verify("shared")["active_reservations"], 6)

    def test_missing_receipt_or_response_bytes_block_recovery(self):
        claim, _ = self.claim_admit()
        saved = self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                           "application/json", "observation-1")
        receipt_path = self.store / saved["receipt_ref"].path
        receipt_bytes = receipt_path.read_bytes()
        receipt_path.unlink()
        with self.assertRaisesRegex(EvidenceError, "missing"):
            self.wrapper.recover_response("request-1", claim["token"],
                                          billing_reason="usage missing")
        receipt_path.write_bytes(receipt_bytes)
        (self.store / saved["response_ref"].path).unlink()
        with self.assertRaisesRegex(EvidenceError, "missing"):
            self.wrapper.recover_response("request-1", claim["token"],
                                          billing_reason="usage missing")
        self.assertEqual(self.wrapper.execution.get("request-1")["request"]["state"],
                         "dispatch_intent")

    def test_orphan_receipt_wrong_request_attempt_or_digest_is_rejected(self):
        claim, _ = self.claim_admit()
        captured = []

        def stop_before_index(request_id, receipt_ref):
            captured.append(receipt_ref)
            raise RuntimeError("before index")

        self.wrapper._index_receipt = stop_before_index
        with self.assertRaisesRegex(RuntimeError, "before index"):
            self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                       "application/json", "observation-1")
        self.wrapper._index_receipt = VerifiedExecution._index_receipt.__get__(self.wrapper)
        original = json.loads(read_artifact(self.store, captured[0]))
        for field, wrong in (("request_id", "other-request"),
                             ("attempt_id", "other-attempt"),
                             ("input_digest", "f" * 64)):
            forged = dict(original)
            forged[field] = wrong
            ref = put_artifact(self.store, json.dumps(forged, sort_keys=True).encode(),
                               "application/json")
            with self.subTest(field=field):
                with self.assertRaisesRegex(VerifiedExecutionError, "does not match"):
                    self.wrapper.recover_response("request-1", claim["token"], receipt_ref=ref,
                                                  billing_reason="usage missing")
        with self.assertRaisesRegex(VerifiedExecutionError, "does not match"):
            self.wrapper.recover_response("request-1", "wrong-token",
                                          receipt_ref=captured[0],
                                          billing_reason="usage missing")
        self.assertIsNone(self.wrapper.receipt_for("request-1"))

    def test_receipt_index_is_immutable(self):
        claim, _ = self.claim_admit()
        self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                   "application/json", "observation-1")
        with sqlite3.connect(self.database) as conn:
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                conn.execute("DELETE FROM verified_response_receipts WHERE request_id='request-1'")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                conn.execute("UPDATE verified_response_receipts SET receipt_size=0 WHERE request_id='request-1'")

    def test_unknown_outcome_reconciles_verified_response_without_releasing_hold(self):
        claim, _ = self.claim_admit()
        self.wrapper.record_unknown("request-1", claim["token"],
                                    "observed timeout", "charge unknown")
        saved = self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                           "application/json", "late-provider-observation")
        result = self.wrapper.recover_response("request-1", claim["token"])
        self.assertEqual(result["request"]["state"], "reconciled")
        self.assertEqual(result["request"]["reconciliation_response_digest"],
                         saved["response_ref"].sha256)
        self.assertEqual(self.budget.verify("shared")["unknown_holds"], 6)
        with self.assertRaisesRegex(VerifiedExecutionError, "does not settle cost"):
            self.wrapper.recover_response("request-1", claim["token"],
                                          settlement_id="charge-2", charge=3)
        self.wrapper.execution.settle_charge("request-1", "invoice-1", 4)
        self.assertEqual(self.budget.verify("shared")["known_charges"], 4)

    def test_concurrent_conflicting_receipts_accept_one_attribution(self):
        self.claim_admit()
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [context.Process(target=receipt_worker,
                                     args=(str(self.database), str(self.store), source, start, results))
                     for source in ("source-a", "source-b")]
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sum(len(value) == 64 for _, value in outcomes), 1)
        self.assertEqual(sum("conflicting response receipt" in value for _, value in outcomes), 1)
        self.assertIsNotNone(self.wrapper.receipt_for("request-1"))

    def test_concurrent_identical_publication_is_idempotent(self):
        self.claim_admit()
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [context.Process(target=receipt_worker,
                                     args=(str(self.database), str(self.store),
                                           "same-observation", start, results)) for _ in range(2)]
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(outcomes[0][1], outcomes[1][1])
        self.assertEqual(self.wrapper.receipt_for("request-1").sha256, outcomes[0][1])

    def test_real_subprocess_crash_before_index_is_discovered_without_returned_ref(self):
        claim, _ = self.claim_admit()
        context = multiprocessing.get_context("spawn")
        crashed = context.Process(target=crash_before_receipt_index,
                                  args=(str(self.database), str(self.store), claim["token"]))
        crashed.start()
        crashed.join(timeout=20)
        self.assertEqual(crashed.exitcode, 77)
        self.assertIsNone(self.wrapper.receipt_for("request-1"))
        results = context.Queue()
        fresh = context.Process(target=discover_after_crash,
                                args=(str(self.database), str(self.store), claim["token"], results))
        fresh.start()
        state, hold, receipt_digest = results.get(timeout=20)
        fresh.join(timeout=20)
        self.assertEqual(fresh.exitcode, 0)
        self.assertEqual((state, hold), ("response_saved", 6))
        self.assertEqual(self.wrapper.receipt_for("request-1").sha256, receipt_digest)
        self.assertIsNone(self.wrapper.execution.claim("resend", 30))
        again = self.wrapper.recover_discovered_response(
            "request-1", claim["token"], billing_reason="usage not observed")
        self.assertEqual(again["budget"]["unknown_holds"], 6)
        self.assertEqual(sum(e["event_type"] == "response_saved" for e in
                             self.wrapper.execution.coordinator.events("request-1")), 1)

    def test_conflicting_orphan_receipts_fail_closed_and_keep_hold(self):
        claim, _ = self.claim_admit()
        self.wrapper.record_unknown("request-1", claim["token"], "timeout", "charge unknown")
        original = self.wrapper._index_receipt

        def skip_index(request_id, receipt_ref):
            return None

        self.wrapper._index_receipt = skip_index
        first = self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                           "application/json", "source-a")
        second = self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                            "application/json", "source-b")
        self.wrapper._index_receipt = original
        self.assertNotEqual(first["receipt_ref"], second["receipt_ref"])
        with self.assertRaisesRegex(VerifiedExecutionError, "multiple conflicting"):
            self.wrapper.discover_orphan_receipt("request-1", claim["token"])
        self.assertIsNone(self.wrapper.receipt_for("request-1"))
        self.assertEqual(self.wrapper.execution.get("request-1")["request"]["state"],
                         "outcome_unknown")
        self.assertEqual(self.budget.verify("shared")["unknown_holds"], 6)

    def test_discovery_rejects_conflict_with_already_indexed_receipt(self):
        claim, _ = self.claim_admit()
        indexed = self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                             "application/json", "source-a")["receipt_ref"]
        original = self.wrapper._index_receipt
        self.wrapper._index_receipt = lambda request_id, receipt_ref: None
        self.wrapper.save_response("request-1", claim["token"], RESPONSE,
                                   "application/json", "source-b")
        self.wrapper._index_receipt = original
        with self.assertRaisesRegex(VerifiedExecutionError, "multiple conflicting"):
            self.wrapper.discover_orphan_receipt("request-1", claim["token"])
        self.assertEqual(self.wrapper.receipt_for("request-1"), indexed)
        self.assertEqual(self.wrapper.execution.get("request-1")["request"]["state"],
                         "dispatch_intent")

    def test_raw_blob_only_is_not_attributed_and_cap_overflow_fails_closed(self):
        claim, _ = self.claim_admit()
        put_artifact(self.store, RESPONSE, "application/json")
        self.assertIsNone(self.wrapper.discover_orphan_receipt("request-1", claim["token"]))
        with self.assertRaisesRegex(VerifiedExecutionError, "cap exceeded"):
            self.wrapper.discover_orphan_receipt("request-1", claim["token"], max_objects=1)
        self.assertIsNone(self.wrapper.receipt_for("request-1"))
        self.assertEqual(self.budget.verify("shared")["active_reservations"], 6)

    def test_corrupt_malformed_and_symlinked_objects_fail_discovery(self):
        claim, _ = self.claim_admit()
        malformed = {
            "request_id": "request-1", "attempt_id": claim["attempt_id"],
            "manifest_digest": self.enrolled["manifest_ref"].sha256,
        }
        put_artifact(self.store, json.dumps(malformed).encode(), "application/json")
        with self.assertRaisesRegex(VerifiedExecutionError, "malformed"):
            self.wrapper.discover_orphan_receipt("request-1", claim["token"])

        # A fresh store isolates each failure mode; no scan may accept a partial result.
        other_store = Path(self.temp.name) / "other-artifacts"
        corrupt = put_artifact(other_store, RESPONSE, "application/json")
        (other_store / corrupt.path).write_bytes(b"changed")
        other = VerifiedExecution(self.database, other_store)
        with self.assertRaisesRegex(EvidenceError, "mismatch"):
            other.discover_orphan_receipt("request-1", claim["token"])

        symlink_store = Path(self.temp.name) / "symlink-artifacts"
        object_ref = put_artifact(symlink_store, RESPONSE, "application/json")
        shard = symlink_store / "objects" / object_ref.sha256[:2]
        (shard / ("f" * 64)).symlink_to(shard / object_ref.sha256)
        linked = VerifiedExecution(self.database, symlink_store)
        with self.assertRaisesRegex(VerifiedExecutionError, "symlinked artifact object"):
            linked.discover_orphan_receipt("request-1", claim["token"])
        root_link = Path(self.temp.name) / "artifact-root-link"
        root_link.symlink_to(symlink_store, target_is_directory=True)
        aliased = VerifiedExecution(self.database, root_link)
        with self.assertRaisesRegex(VerifiedExecutionError, "real directory"):
            aliased.discover_orphan_receipt("request-1", claim["token"])


if __name__ == "__main__":
    unittest.main()
