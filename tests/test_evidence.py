import hashlib
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from classification_bench.evidence import (
    EvidenceError, bind_parsed_attempt, load_parsed_attempt, put_artifact, read_artifact,
)


PARSER = hashlib.sha256(b"parser-v1").hexdigest()


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_raw_bytes_are_content_addressed_and_identical_writes_deduplicate(self):
        data = b"\x00response\xff"
        first = put_artifact(self.root, data, "application/octet-stream")
        path = self.root / first.path
        self.assertEqual(first.schema_version, 1)
        self.assertEqual(first.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(first.size, len(data))
        self.assertEqual(first.path, f"objects/{first.sha256[:2]}/{first.sha256}")
        inode = path.stat().st_ino
        self.assertEqual(put_artifact(self.root, data, "application/octet-stream"), first)
        self.assertEqual(path.stat().st_ino, inode)
        self.assertEqual(read_artifact(self.root, first), data)
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_concurrent_first_writes_and_new_directories_are_private(self):
        for round_number in range(6):
            root = self.root / str(round_number) / "nested" / "store"
            if round_number % 2:
                (root / "objects").mkdir(parents=True, mode=0o700)
            barrier = threading.Barrier(16)
            def write(_):
                barrier.wait()
                return put_artifact(root, b"shared response", "text/plain")
            with ThreadPoolExecutor(max_workers=16) as pool:
                refs = list(pool.map(write, range(16)))
            self.assertTrue(all(ref == refs[0] for ref in refs))
            self.assertEqual(read_artifact(root, refs[0]), b"shared response")
            shard = (root / refs[0].path).parent
            self.assertEqual(stat.S_IMODE(shard.stat().st_mode), 0o700)
            if round_number % 2 == 0:
                for directory in (root, root.parent, root.parent.parent, root / "objects"):
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(list(shard.iterdir()), [root / refs[0].path])

    def test_tampered_existing_object_fails_without_overwrite(self):
        data = b"original"
        ref = put_artifact(self.root, data, "text/plain")
        path = self.root / ref.path
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(EvidenceError, "mismatch"):
            put_artifact(self.root, data, "text/plain")
        self.assertEqual(path.read_bytes(), b"tampered")
        with self.assertRaisesRegex(EvidenceError, "mismatch"):
            read_artifact(self.root, ref)

    def test_ref_path_cannot_escape_and_missing_bytes_fail(self):
        ref = put_artifact(self.root, b"response", "application/json")
        with self.assertRaisesRegex(EvidenceError, "relative content address"):
            read_artifact(self.root, replace(ref, path="../../outside"))
        (self.root / ref.path).unlink()
        with self.assertRaisesRegex(EvidenceError, "missing"):
            read_artifact(self.root, ref)

    def test_symlinked_store_directory_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        store = self.root / "store"
        store.mkdir()
        (store / "objects").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(EvidenceError, "symlink"):
            put_artifact(store, b"private", "text/plain")
        self.assertEqual(list(outside.iterdir()), [])

    def test_parser_binding_verifies_response_parser_and_attempt(self):
        response = put_artifact(self.root, b'{"raw":"saved"}', "application/json")
        binding = bind_parsed_attempt(self.root, response, "request-1", "attempt-2", PARSER,
                                      "valid", {"sentiment": "positive"})
        record = load_parsed_attempt(self.root, binding, "request-1", "attempt-2", PARSER)
        self.assertEqual(record["response"]["sha256"], response.sha256)
        self.assertEqual(record["prediction"], {"sentiment": "positive"})
        self.assertEqual(binding, bind_parsed_attempt(
            self.root, response, "request-1", "attempt-2", PARSER,
            "valid", {"sentiment": "positive"}))
        with self.assertRaisesRegex(EvidenceError, "source binding mismatch"):
            load_parsed_attempt(self.root, binding, "request-1", "attempt-3", PARSER)
        with self.assertRaisesRegex(EvidenceError, "source binding mismatch"):
            load_parsed_attempt(self.root, binding, "request-1", "attempt-2", "0" * 64)
        (self.root / response.path).write_bytes(b"different")
        with self.assertRaisesRegex(EvidenceError, "mismatch"):
            load_parsed_attempt(self.root, binding, "request-1", "attempt-2", PARSER)

    def test_failed_parse_has_reason_and_never_invents_prediction(self):
        response = put_artifact(self.root, b"not json", "text/plain")
        for status in ("invalid", "unavailable"):
            binding = bind_parsed_attempt(self.root, response, "req", status, PARSER, status,
                                          reason={"code": "parse_error", "detail": "No valid object"})
            record = load_parsed_attempt(self.root, binding, "req", status, PARSER)
            self.assertIsNone(record["prediction"])
            self.assertEqual(record["reason"]["code"], "parse_error")
        with self.assertRaises(EvidenceError):
            bind_parsed_attempt(self.root, response, "req", "a", PARSER, "invalid",
                                prediction={"sentiment": "positive"},
                                reason={"code": "parse_error", "detail": "bad"})
        with self.assertRaises(EvidenceError):
            bind_parsed_attempt(self.root, response, "req", "a", PARSER, "unavailable")

    def test_binding_rejects_unverified_response_and_bad_identifiers(self):
        response = put_artifact(self.root, b"body", "text/plain")
        (self.root / response.path).unlink()
        with self.assertRaises(EvidenceError):
            bind_parsed_attempt(self.root, response, "req", "attempt", PARSER,
                                "valid", {"field": "label"})
        response = put_artifact(self.root, b"body", "text/plain")
        with self.assertRaises(EvidenceError):
            bind_parsed_attempt(self.root, response, "req", "attempt", "not-a-hash",
                                "valid", {"field": "label"})
        with self.assertRaises(EvidenceError):
            bind_parsed_attempt(self.root, response, " ", "attempt", PARSER,
                                "valid", {"field": "label"})


if __name__ == "__main__":
    unittest.main()
