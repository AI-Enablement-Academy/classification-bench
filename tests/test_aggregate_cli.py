"""Aggregate operator commands use frozen authority and private local outputs."""

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from classification_bench.budget import BudgetLedger
from classification_bench.benchmark import _runner_lock
from classification_bench.cli import main
from classification_bench.execution import ExecutionLedger
from classification_bench.manifest import digest


ROOT = Path(__file__).resolve().parents[1]


class AggregateCLITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="aggregate-cli-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.spec_path = self.root / "aggregate.json"
        self.spec = {"schema_version": 1, "database": str(self.root / "authority.sqlite"),
                     "scope": "fixture:aggregate", "cap": 10, "currency": "USD",
                     "scale": 1_000_000, "authorization_source": "explicit offline fixture authority"}
        self.write_spec(self.spec)

    def write_spec(self, value):
        self.spec_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def invoke(self, command, *args, success=True):
        result = subprocess.run([sys.executable, "-m", "classification_bench", command,
                                 "--spec", str(self.spec_path), *map(str, args)],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0 if success else 2, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        if success:
            self.assertEqual(result.stderr, "")
            return json.loads(result.stdout) if result.stdout else None
        self.assertEqual(result.stdout, "")
        return result.stderr

    def amendment(self, *, amendment_id="larger", expected_cap=10, new_cap=20, **changes):
        value = {"schema_version": 1, "aggregate_spec_sha256": digest(self.spec_path.read_bytes()),
                 "scope": self.spec["scope"], "amendment_id": amendment_id,
                 "expected_cap": expected_cap, "new_cap": new_cap,
                 "authorization_source": "explicit offline fixture cap increase"}
        value.update(changes)
        path = self.root / "amendment.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def cap_event_count(self):
        with contextlib.closing(sqlite3.connect(self.spec["database"])) as connection:
            return connection.execute("SELECT COUNT(*) FROM cap_events WHERE scope=?",
                                      (self.spec["scope"],)).fetchone()[0]

    def test_create_status_and_increase_write_private_outputs(self):
        for command in ("aggregate-create", "aggregate-status", "aggregate-increase"):
            output = self.root / (command + ".json")
            args = ["--out", output]
            if command == "aggregate-increase":
                args += ["--authorization", self.amendment()]
            self.assertIsNone(self.invoke(command, *args))
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            value = json.loads(output.read_text())
            self.assertEqual(value["dispatch_count"], 0)
            self.assertEqual(value["aggregate_spec_sha256"], digest(self.spec_path.read_bytes()))
            self.assertEqual(value["budget"]["cap"], 20 if command == "aggregate-increase" else 10)
        self.assertEqual(stat.S_IMODE(Path(self.spec["database"]).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(self.spec["database"] + ".runner.lock").stat().st_mode), 0o600)

    def test_stdout_create_retry_and_amendment_retry_are_idempotent(self):
        original = self.invoke("aggregate-create")
        self.assertEqual(self.invoke("aggregate-create"), original)
        authorization = self.amendment()
        increased = self.invoke("aggregate-increase", "--authorization", authorization)
        self.assertEqual(self.invoke("aggregate-increase", "--authorization", authorization), increased)
        self.assertEqual(self.invoke("aggregate-create"), increased)
        self.assertEqual(self.invoke("aggregate-status"), increased)
        self.assertEqual(self.cap_event_count(), 2)

    def test_missing_database_status_and_increase_create_nothing(self):
        for command in ("aggregate-status", "aggregate-increase"):
            args = ["--authorization", self.amendment()] if command.endswith("increase") else []
            error = self.invoke(command, *args, success=False)
            self.assertIn("database does not exist", error)
            self.assertFalse(Path(self.spec["database"]).exists())
            self.assertFalse(Path(self.spec["database"] + ".runner.lock").exists())

    def test_changed_specification_cannot_read_or_amend_an_existing_authority(self):
        original = self.invoke("aggregate-create")
        raw = self.spec_path.read_bytes()
        for change in ({"cap": 999}, {"authorization_source": "changed approval"}):
            with self.subTest(change=change):
                self.write_spec({**self.spec, **change})
                error = self.invoke("aggregate-status", success=False)
                self.assertIn("frozen authority", error)
                authorization = self.amendment()
                error = self.invoke("aggregate-increase", "--authorization", authorization, success=False)
                self.assertIn("frozen authority", error)
        self.spec_path.write_bytes(raw + b"\n")
        self.assertIn("frozen authority", self.invoke("aggregate-status", success=False))
        self.spec_path.write_bytes(raw)
        self.assertEqual(self.invoke("aggregate-status"), original)
        self.assertEqual(self.cap_event_count(), 1)

    def test_amendment_requires_exact_specification_hash_scope_and_fields(self):
        self.invoke("aggregate-create")
        changes = [{"aggregate_spec_sha256": "f" * 64}, {"scope": "another scope"},
                   {"schema_version": True}, {"extra": "unsupported"}]
        for change in changes:
            with self.subTest(change=change):
                error = self.invoke("aggregate-increase", "--authorization", self.amendment(**change), success=False)
                self.assertIn("does not match frozen specification", error)
        value = json.loads(self.amendment().read_text())
        del value["new_cap"]
        authorization = self.root / "missing-field.json"
        authorization.write_text(json.dumps(value))
        self.invoke("aggregate-increase", "--authorization", authorization, success=False)
        self.assertEqual(self.invoke("aggregate-status")["budget"]["cap"], 10)
        self.assertEqual(self.cap_event_count(), 1)

    def test_stale_conflicting_and_nonincreasing_amendments_preserve_audit(self):
        self.invoke("aggregate-create")
        self.invoke("aggregate-increase", "--authorization", self.amendment())
        invalid = [{"new_cap": 30}, {"amendment_id": "stale", "new_cap": 30},
                   {"amendment_id": "no-increase", "expected_cap": 20, "new_cap": 20},
                   {"amendment_id": "smaller", "expected_cap": 20, "new_cap": 19}]
        for change in invalid:
            with self.subTest(change=change):
                self.invoke("aggregate-increase", "--authorization", self.amendment(**change), success=False)
        self.assertEqual(self.invoke("aggregate-status")["budget"]["cap"], 20)
        self.assertEqual(self.cap_event_count(), 2)

    def test_amendment_amounts_ids_and_sources_are_strict(self):
        self.invoke("aggregate-create")
        for change in ({"expected_cap": True}, {"expected_cap": 10.0}, {"new_cap": "20"},
                       {"new_cap": False}, {"new_cap": 20.0}, {"new_cap": 0},
                       {"amendment_id": " "}, {"authorization_source": ""}):
            with self.subTest(change=change):
                self.invoke("aggregate-increase", "--authorization", self.amendment(**change), success=False)
        self.assertEqual(self.invoke("aggregate-status")["budget"]["cap"], 10)
        self.assertEqual(self.cap_event_count(), 1)

    def test_frozen_parent_refuses_cli_increase_without_clearing_exposure(self):
        self.invoke("aggregate-create")
        ledger = BudgetLedger(self.spec["database"])
        ledger.allocate_child(self.spec["scope"], "smoke", "smoke", 4, "a" * 64, "fixture allocation", phase="smoke")
        ledger.reserve("smoke", "one", 1, bound_source="offline fixture ceiling")
        ledger.settle("smoke", "one", "receipt", 2)
        before = self.invoke("aggregate-status")
        self.assertTrue(before["budget"]["frozen"])
        self.assertEqual(before["budget"]["accounted_exposure"], 4)
        error = self.invoke("aggregate-increase", "--authorization", self.amendment(), success=False)
        self.assertIn("blocked aggregate", error)
        self.assertEqual(self.invoke("aggregate-status"), before)
        self.assertEqual(self.cap_event_count(), 1)

    def test_explicit_parent_safety_block_refuses_cli_increase(self):
        self.invoke("aggregate-create")
        execution = ExecutionLedger(self.spec["database"])
        execution.block_scope(self.spec["scope"], "fixture paid-extra-usage observation", "fixture receipt")
        before = self.invoke("aggregate-status")
        self.assertTrue(before["budget"]["frozen"])
        self.assertFalse(before["budget"]["scope_frozen"])
        error = self.invoke("aggregate-increase", "--authorization", self.amendment(), success=False)
        self.assertIn("blocked aggregate", error)
        self.assertEqual(self.invoke("aggregate-status"), before)
        self.assertEqual(self.cap_event_count(), 1)

    def test_supported_units_are_separate_and_never_converted(self):
        for currency, scale in (("USD", 1_000_000), ("REQ", 1), ("SYN", 1)):
            with self.subTest(currency=currency):
                spec = {**self.spec, "database": str(self.root / (currency + ".sqlite")),
                        "scope": currency + ":fixture", "currency": currency, "scale": scale}
                self.write_spec(spec)
                value = self.invoke("aggregate-create")
                self.assertEqual((value["budget"]["currency"], value["budget"]["scale"],
                                  value["budget"]["cap"]), (currency, scale, 10))
                self.assertEqual(self.invoke("aggregate-status"), value)

    def test_invalid_specification_fields_types_and_units_fail_usefully(self):
        changes = [{"schema_version": True}, {"extra": "unsupported"}, {"database": "relative.sqlite"},
                   {"scope": None}, {"scope": " "}, {"cap": True}, {"cap": 10.0}, {"cap": "10"},
                   {"cap": 0}, {"cap": -1}, {"currency": "EUR"}, {"currency": "usd"},
                   {"scale": True}, {"scale": 1_000_000.0}, {"scale": 1},
                   {"authorization_source": " "}, {"authorization_source": None}]
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                self.write_spec({**self.spec, "database": str(self.root / (str(index) + ".sqlite")), **change})
                error = self.invoke("aggregate-create", success=False)
                self.assertIn("classification-bench:", error)

    def test_boolean_and_float_request_scales_are_rejected_on_status(self):
        self.spec.update(currency="REQ", scale=1)
        self.write_spec(self.spec)
        self.invoke("aggregate-create")
        for scale in (True, 1.0):
            with self.subTest(scale=scale):
                self.write_spec({**self.spec, "scale": scale})
                error = self.invoke("aggregate-status", success=False)
                self.assertIn("declared units", error)

    def test_duplicate_json_fields_fail_without_creating_authority(self):
        raw = json.dumps(self.spec)
        self.spec_path.write_text(raw[:-1] + ', "cap": 999}')
        self.assertIn("duplicate JSON key", self.invoke("aggregate-create", success=False))
        self.assertFalse(Path(self.spec["database"]).exists())

    def test_existing_output_and_symlink_targets_are_preserved(self):
        self.invoke("aggregate-create")
        target = self.root / "existing.json"
        target.write_text("original private result")
        link = self.root / "output-link.json"
        link.symlink_to(target)
        for path in (target, link):
            with self.subTest(path=path):
                self.invoke("aggregate-status", "--out", path, success=False)
                self.assertEqual(target.read_text(), "original private result")
        self.assertTrue(link.is_symlink())

    def test_create_and_increase_respect_an_existing_runner_lock(self):
        before = self.invoke("aggregate-create")
        authorization = self.amendment()
        with _runner_lock(self.spec["database"]):
            for command in ("aggregate-create", "aggregate-increase"):
                args = ["--authorization", authorization] if command.endswith("increase") else []
                error = self.invoke(command, *args, success=False)
                self.assertIn("already_running", error)
        self.assertEqual(self.invoke("aggregate-status"), before)
        self.assertEqual(self.cap_event_count(), 1)

    def test_status_can_inspect_authority_while_an_actual_runner_holds_the_lock(self):
        before = self.invoke("aggregate-create")
        with _runner_lock(self.spec["database"]):
            current = self.invoke("aggregate-status")
        self.assertEqual(current, before)
        self.assertEqual(self.cap_event_count(), 1)


class ModelCatalogCLITests(unittest.TestCase):
    def test_models_cli_dispatches_one_mocked_public_page_to_private_output(self):
        raw = json.dumps({"data": [{"id": "vendor/arbitrary:variant", "name": "Any <name>",
                                   "reasoning": {"supported_efforts": ["medium", "high"]}}],
                          "total_count": 3, "links": {"next": "https://example.invalid/next"}}).encode()
        with tempfile.TemporaryDirectory(prefix="models-cli-") as directory:
            output = Path(directory) / "catalog.json"
            with patch("classification_bench.adapters._default_catalog_fetch", return_value=raw) as fetch:
                main(["models", "--query", "reasoning & arbitrary", "--offset", "1", "--limit", "1", "--out", str(output)])
            self.assertEqual(fetch.call_count, 1)
            url = fetch.call_args.args[0]
            self.assertEqual(parse_qs(urlsplit(url).query), {"q": ["reasoning & arbitrary"],
                             "output_modalities": ["text"], "offset": ["1"], "limit": ["1"]})
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            value = json.loads(output.read_text())
            self.assertEqual(value["response_sha256"], digest(raw))
            self.assertEqual(value["models"][0]["id"], "vendor/arbitrary:variant")
            self.assertEqual((value["offset"], value["limit"], value["next_offset"]), (1, 1, 2))
            self.assertFalse(value["complete"])

    def test_models_defaults_emit_json_and_use_cli_page_limit(self):
        raw = b'{"data":[],"total_count":0,"links":{"next":null}}'
        output = io.StringIO()
        with patch("classification_bench.adapters._default_catalog_fetch", return_value=raw) as fetch, \
                contextlib.redirect_stdout(output):
            main(["models"])
        self.assertEqual(fetch.call_count, 1)
        value = json.loads(output.getvalue())
        self.assertEqual((value["query"], value["offset"], value["limit"]), (None, 0, 100))
        self.assertTrue(value["complete"])

    def test_models_invalid_pagination_and_query_never_fetch(self):
        for args in (("--offset", "-1"), ("--limit", "0"), ("--limit", "1001"),
                     ("--query", ""), ("--offset", "not-an-integer")):
            with self.subTest(args=args), patch("classification_bench.adapters._default_catalog_fetch") as fetch, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["models", *args])
            self.assertEqual(error.exception.code, 2)
            fetch.assert_not_called()

    def test_models_failed_public_page_creates_no_output(self):
        with tempfile.TemporaryDirectory(prefix="models-cli-") as directory:
            output = Path(directory) / "catalog.json"
            with patch("classification_bench.adapters._default_catalog_fetch", side_effect=TimeoutError("offline fixture")), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["models", "--out", str(output)])
            self.assertEqual(error.exception.code, 2)
            self.assertFalse(output.exists())
