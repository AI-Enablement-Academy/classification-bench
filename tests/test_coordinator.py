import multiprocessing
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path

from classification_bench.coordinator import Coordinator, CoordinatorError


MANIFEST = "a" * 64
REQUEST = "b" * 64
RESPONSE = "c" * 64


def race_worker(path, start, results):
    ledger = Coordinator(path)
    start.wait()
    claim = ledger.claim("worker", 30)
    if claim is None:
        results.put("empty")
        return
    try:
        ledger.record_dispatch_intent(claim["request_id"], claim["token"])
        results.put("intent")
    except CoordinatorError as exc:
        results.put(str(exc))


def intent_worker(path, token, start, results):
    ledger = Coordinator(path)
    start.wait()
    try:
        ledger.record_dispatch_intent("request-1", token)
        results.put("intent")
    except CoordinatorError:
        results.put("fenced")


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "coordinator.sqlite"
        self.ledger = Coordinator(self.path)
        self.ledger.enqueue("request-1", MANIFEST, REQUEST)

    def test_concurrent_workers_record_one_intent(self):
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [context.Process(target=race_worker,
                                     args=(str(self.path), start, results)) for _ in range(4)]
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(outcomes.count("intent"), 1)
        self.assertEqual(outcomes.count("empty"), 3)
        self.assertEqual([e["event_type"] for e in self.ledger.events("request-1")],
                         ["enqueued", "claimed", "dispatch_started"])

    def test_expired_unstarted_claim_recovers_and_old_token_is_fenced(self):
        first = self.ledger.claim("old", 0.01)
        time.sleep(0.03)
        reopened = Coordinator(self.path)
        second = reopened.claim("new", 30)
        self.assertEqual(first["attempt_id"], second["attempt_id"])
        self.assertEqual(second["generation"], first["generation"] + 1)
        with self.assertRaisesRegex(CoordinatorError, "stale"):
            reopened.record_dispatch_intent("request-1", first["token"])
        reopened.record_dispatch_intent("request-1", second["token"])
        with self.assertRaisesRegex(CoordinatorError, "stale"):
            reopened.complete("request-1", first["token"], "outcome_unknown", "old observation")
        self.assertEqual([e["event_type"] for e in reopened.events("request-1")],
                         ["enqueued", "claimed", "claimed", "dispatch_started"])

    def test_same_token_concurrent_intent_is_one_shot(self):
        token = self.ledger.claim("worker", 30)["token"]
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [context.Process(target=intent_worker,
                                     args=(str(self.path), token, start, results)) for _ in range(2)]
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sorted(outcomes), ["fenced", "intent"])
        self.assertEqual(sum(e["event_type"] == "dispatch_started"
                             for e in self.ledger.events("request-1")), 1)

    def test_database_file_is_private_and_symlink_is_rejected(self):
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        target = Path(self.temp.name) / "open.sqlite"
        target.write_bytes(b"not SQLite")
        target.chmod(0o644)
        with self.assertRaisesRegex(CoordinatorError, "private regular file"):
            Coordinator(target)
        link = Path(self.temp.name) / "link.sqlite"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(CoordinatorError, "private regular file"):
            Coordinator(link)
        self.assertEqual(os.stat(self.path).st_uid, os.geteuid())

    def test_crash_boundaries_and_unknown_never_auto_retry(self):
        claim = self.ledger.claim("worker", 0.01)
        time.sleep(0.03)
        recovered = Coordinator(self.path).claim("replacement", 30)
        self.assertIsNotNone(recovered)
        reopened = Coordinator(self.path)
        reopened.record_dispatch_intent("request-1", recovered["token"])
        self.assertIsNone(Coordinator(self.path).claim("another", 30))
        self.assertEqual(reopened.get("request-1")["state"], "dispatch_intent")
        reopened.complete("request-1", recovered["token"], "outcome_unknown", "timeout-1")
        self.assertIsNone(Coordinator(self.path).claim("another", 30))
        reconciled = reopened.reconcile("request-1", "provider-receipt", "response_saved",
                                      response_digest=RESPONSE)
        self.assertEqual(reconciled["state"], "reconciled")
        self.assertEqual(reconciled["outcome"], "outcome_unknown")
        self.assertIsNone(reopened.claim("another", 30))
        self.assertEqual([e["event_type"] for e in reopened.events("request-1")],
                         ["enqueued", "claimed", "claimed", "dispatch_started",
                          "outcome_unknown", "reconciled"])

    def test_completion_and_reconciliation_are_idempotent_but_conflicts_fail(self):
        claim = self.ledger.claim("worker", 30)
        self.ledger.record_dispatch_intent("request-1", claim["token"])
        first = self.ledger.complete("request-1", claim["token"], "outcome_unknown", "timeout")
        count = len(self.ledger.events("request-1"))
        self.assertEqual(first, self.ledger.complete("request-1", claim["token"],
                                                     "outcome_unknown", "timeout"))
        self.assertEqual(len(self.ledger.events("request-1")), count)
        with self.assertRaisesRegex(CoordinatorError, "conflicting"):
            self.ledger.complete("request-1", claim["token"], "not_sent", "different")
        resolved = self.ledger.reconcile("request-1", "proof", "not_sent")
        self.assertEqual(resolved, self.ledger.reconcile("request-1", "proof", "not_sent"))
        with self.assertRaisesRegex(CoordinatorError, "conflicting"):
            self.ledger.reconcile("request-1", "another", "not_sent")
        self.assertEqual(len(self.ledger.events("request-1")), count + 1)

    def test_identity_and_response_evidence_validation(self):
        before = len(self.ledger.events("request-1"))
        self.ledger.enqueue("request-1", MANIFEST, REQUEST)
        self.assertEqual(len(self.ledger.events("request-1")), before)
        with self.assertRaisesRegex(CoordinatorError, "different evidence"):
            self.ledger.enqueue("request-1", REQUEST, MANIFEST)
        claim = self.ledger.claim("worker", 30)
        with self.assertRaisesRegex(CoordinatorError, "dispatch intent"):
            self.ledger.complete("request-1", claim["token"], "response_saved", "proof",
                                 response_digest=RESPONSE)
        self.ledger.record_dispatch_intent("request-1", claim["token"])
        with self.assertRaisesRegex(CoordinatorError, "digest"):
            self.ledger.complete("request-1", claim["token"], "response_saved", "proof")
        self.ledger.complete("request-1", claim["token"], "response_saved", "proof",
                             response_digest=RESPONSE)
        self.assertEqual(Coordinator(self.path).get("request-1")["response_digest"], RESPONSE)


if __name__ == "__main__":
    unittest.main()
