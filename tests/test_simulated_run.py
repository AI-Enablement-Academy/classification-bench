"""Offline integration tests use synthetic fixtures and no provider."""

import errno
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from classification_bench.budget import BudgetLedger
from classification_bench.core import build_plan, evaluate
from classification_bench.isolation import IsolationUnavailable, SandboxedPythonWorker
from classification_bench.evidence import EvidenceError
from classification_bench.manifest import ManifestError, canonical_bytes, digest, validate_manifest
from classification_bench.run import (SimulatedRunError, _load, _materials, _recovery_scan_bound,
                                      export_saved_predictions, recover_saved, simulate)
from classification_bench.verified_execution import VerifiedExecution, VerifiedExecutionError


class SimulatedRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="classification-e2e-", dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        task = {"name": "fictional", "input_keys": ["text"],
                "fields": [{"name": "kind", "labels": ["a", "b"]}]}
        experiment = {"configs": [{"id": "fake", "model": "synthetic-only"}],
                      "prompts": [{"id": "p", "text": "Classify the fiction."}],
                      "repeats": 2, "batch_size": 2}
        inputs = {"records": [{"id": "one", "input": {"text": "alpha"}},
                              {"id": "two", "input": {"text": "beta"}},
                              {"id": "three", "input": {"text": "gamma"}}]}
        for name, value in (("task", task), ("experiment", experiment), ("inputs", inputs)):
            (self.root / f"{name}.json").write_text(json.dumps(value))
        self.config = {"schema_version": 1, "task": str(self.root / "task.json"),
                       "experiment": str(self.root / "experiment.json"),
                       "inputs": str(self.root / "inputs.json"),
                       "database": str(self.root / "state.sqlite"),
                       "artifacts": str(self.root / "artifacts"),
                       "scope": "synthetic:e2e", "cap": 2, "reserve_amount": 1,
                       "response_mode": "first_label"}
        self.config_path = self.root / "config.json"
        self._write_config()

    def _write_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def _require_real_sandbox(self):
        if platform.system() != "Darwin":
            self.skipTest("real sandbox-exec integration requires macOS")
        try:
            SandboxedPythonWorker().probe()
        except IsolationUnavailable as exc:
            self.skipTest(f"sandbox unavailable in enclosing runtime: {exc}")

    def test_one_command_all_records_repeats_and_no_replay(self):
        self._require_real_sandbox()
        first = simulate(self.config_path)
        self.assertEqual(first, {"status": "completed", "planned_requests": 4,
                                 "completed_requests": 4, "model_calls": 0})
        self.assertEqual(simulate(self.config_path), first)
        self.assertEqual(recover_saved(self.config_path)["recovered"], [])
        budget = BudgetLedger(self.config["database"]).verify(self.config["scope"])
        self.assertEqual(budget["known_charges"], 0)
        self.assertEqual(budget["active_reservations"], 0)

    def test_cli_one_config_then_export_without_labels(self):
        self._require_real_sandbox()
        project = Path(__file__).resolve().parents[1]
        command = [sys.executable, "-m", "classification_bench", "simulate",
                   "--config", str(self.config_path)]
        run = subprocess.run(command, cwd=project, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["planned_requests"], 4)
        exported = subprocess.run([sys.executable, "-m", "classification_bench",
                                   "simulate-export", "--config", str(self.config_path)],
                                  cwd=project, capture_output=True, text=True)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertEqual(len(json.loads(exported.stdout)["records"]), 6)

    def test_post_intent_restart_never_calls_worker(self):
        self._require_real_sandbox()
        def stop(point, _):
            if point == "dispatch_intent":
                raise RuntimeError("synthetic crash")
        with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
            simulate(self.config_path, fault_after=stop)
        with patch("classification_bench.run._sandbox_response", side_effect=AssertionError("resent")):
            state = simulate(self.config_path)
        self.assertEqual(state["status"], "recovery_required")
        self.assertEqual(state["state"], "dispatch_intent")
        self.assertEqual(recover_saved(self.config_path)["recovered"], [])
        self.assertEqual(BudgetLedger(self.config["database"]).balances(self.config["scope"])[
            "active_reservations"], 1)

    def test_unavailable_sandbox_creates_no_dispatch_intent(self):
        class UnavailableWorker:
            def probe(self):
                raise IsolationUnavailable("synthetic unsupported host")
        with self.assertRaisesRegex(IsolationUnavailable, "unsupported host"):
            simulate(self.config_path, worker=UnavailableWorker())
        verified = VerifiedExecution(self.config["database"], self.config["artifacts"])
        with verified.execution.coordinator._transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM requests WHERE state='dispatch_intent'").fetchone()[0], 0)
        self.assertEqual(BudgetLedger(self.config["database"]).balances(self.config["scope"])[
            "active_reservations"], 0)

    def test_expired_preintent_claim_is_recovered(self):
        self._require_real_sandbox()
        def stop(point, _):
            if point == "claimed":
                raise RuntimeError("stop before intent")
        with self.assertRaises(RuntimeError):
            simulate(self.config_path, fault_after=stop)
        verified = VerifiedExecution(self.config["database"], self.config["artifacts"])
        with verified.execution.coordinator._transaction() as conn:
            conn.execute("UPDATE requests SET lease_until=0 WHERE state='claimed'")
        self.assertEqual(simulate(self.config_path)["status"], "completed")

    def test_real_process_crash_before_receipt_index_recovers_without_resend(self):
        self._require_real_sandbox()
        script = """import os,sys
from classification_bench.run import simulate
from classification_bench.verified_execution import VerifiedExecution
def crash(self, request_id, receipt_ref): os._exit(44)
VerifiedExecution._index_receipt = crash
simulate(sys.argv[1])
"""
        child = subprocess.run([sys.executable, "-c", script, str(self.config_path)],
                               cwd=Path(__file__).resolve().parents[1], capture_output=True)
        self.assertEqual(child.returncode, 44, child.stderr.decode())
        recovered = recover_saved(self.config_path)
        self.assertEqual(len(recovered["recovered"]), 1)
        with patch("classification_bench.run._sandbox_response", side_effect=AssertionError("resent")):
            # The first request is now terminal; a resumed command may execute
            # other planned requests, so only recovery is asserted no-send.
            self.assertEqual(recover_saved(self.config_path)["recovered"], [])
        self.assertEqual(BudgetLedger(self.config["database"]).balances(self.config["scope"])[
            "active_reservations"], 0)

    def test_recovery_bound_scales_and_explicit_larger_scan_checks_all_objects(self):
        self._require_real_sandbox()
        self.assertGreater(_recovery_scan_bound(2501), 10_000)
        def stop(point, _):
            if point == "receipt_indexed":
                raise RuntimeError("stop after receipt index")
        with self.assertRaises(RuntimeError):
            simulate(self.config_path, fault_after=stop)
        objects = Path(self.config["artifacts"]) / "objects"
        for index in range(10_001):
            data = f"unrelated-synthetic-{index}".encode()
            sha = hashlib.sha256(data).hexdigest()
            shard = objects / sha[:2]
            shard.mkdir(exist_ok=True)
            (shard / sha).write_bytes(data)
        with self.assertRaisesRegex(VerifiedExecutionError, "object cap exceeded"):
            recover_saved(self.config_path)
        recovered = recover_saved(self.config_path, max_objects=10_050)
        self.assertEqual(len(recovered["recovered"]), 1)
        self.assertEqual(recovered["unresolved"], [])

    def test_changed_config_and_label_field_are_rejected(self):
        def stop(point, _):
            if point == "claimed":
                raise RuntimeError("stop before dispatch")
        with self.assertRaises(RuntimeError):
            simulate(self.config_path, fault_after=stop)
        self.config["response_mode"] = "invalid"
        self._write_config()
        with self.assertRaisesRegex(SimulatedRunError, "configuration changed"):
            simulate(self.config_path)
        self.config["labels"] = str(self.root / "labels.json")
        self._write_config()
        with self.assertRaisesRegex(SimulatedRunError, "exact v1 fields"):
            simulate(self.config_path)

    def test_unimplemented_model_settings_are_rejected(self):
        experiment_path = Path(self.config["experiment"])
        experiment = json.loads(experiment_path.read_text())
        experiment["configs"][0]["settings"] = {"temperature": 0.7}
        experiment_path.write_text(json.dumps(experiment))
        with self.assertRaisesRegex(ManifestError, "empty settings"):
            simulate(self.config_path)

    def test_manifest_rejects_consistently_rehashed_message_drift(self):
        config, plan, binding, adapter_sha, parser_sha = _load(self.config_path)
        request, manifest_bytes, request_bytes = next(_materials(config, plan, binding,
                                                                  adapter_sha, parser_sha))
        body = json.loads(request_bytes)
        body["messages"][0]["content"] = "Different prompt"
        changed_request = canonical_bytes(body)
        manifest = json.loads(manifest_bytes)
        manifest["messages"] = body["messages"]
        manifest["request_sha256"] = digest(changed_request)
        with self.assertRaisesRegex(ManifestError, "selected plan"):
            validate_manifest(canonical_bytes(manifest), changed_request, plan, request,
                              plan["experiment"]["configs"][0], plan["experiment"]["prompts"][0],
                              config_digest=binding, adapter_digest=adapter_sha,
                              parser_digest=parser_sha, scope=config["scope"], ordinal=1)

    def test_rendered_capsule_cannot_read_reference_or_symlink(self):
        self._require_real_sandbox()
        config, plan, binding, adapter_sha, parser_sha = _load(self.config_path)
        _, _, request_bytes = next(_materials(config, plan, binding, adapter_sha, parser_sha))
        capsule = self.root / "capsule"
        capsule.write_bytes(request_bytes)
        reference = self.root / "reference"
        reference.write_bytes(b"synthetic-reference-label")
        link = self.root / "reference-link"
        link.symlink_to(reference)
        source = "import errno,sys; print(open(sys.argv[1],'rb').read()[:1]);\n"
        for path in (reference, link):
            source += f"try:\n open({str(path)!r},'rb').read()\n print('leak')\nexcept OSError as exc:\n print(exc.errno)\n"
        result = SandboxedPythonWorker().run(capsule, source)
        denials = result.stdout.splitlines()[1:]
        self.assertEqual(len(denials), 2)
        self.assertTrue(all(int(value) in (errno.EPERM, errno.EACCES) for value in denials))

    def test_restart_does_not_republish_missing_enrolled_request(self):
        self._require_real_sandbox()
        simulate(self.config_path)
        verified = VerifiedExecution(self.config["database"], self.config["artifacts"])
        with verified.execution.coordinator._transaction() as conn:
            sha = conn.execute("SELECT input_digest FROM execution_requests LIMIT 1").fetchone()[0]
        object_path = Path(self.config["artifacts"]) / "objects" / sha[:2] / sha
        object_path.unlink()
        with self.assertRaisesRegex(EvidenceError, "missing"):
            simulate(self.config_path)
        self.assertFalse(object_path.exists())

    def test_terminal_rerun_checks_saved_response_bytes(self):
        self._require_real_sandbox()
        simulate(self.config_path)
        verified = VerifiedExecution(self.config["database"], self.config["artifacts"])
        with verified.execution.coordinator._transaction() as conn:
            request_id = conn.execute("SELECT request_id FROM execution_requests LIMIT 1").fetchone()[0]
        state = verified.execution.get(request_id)
        receipt = verified.receipt_for(request_id)
        response = verified._verify_receipt(request_id, state["execution"]["admission_token"], receipt)
        (Path(self.config["artifacts"]) / response.path).unlink()
        with self.assertRaisesRegex(EvidenceError, "missing"):
            simulate(self.config_path)

    def test_invalid_and_missing_fake_outputs_keep_full_denominator(self):
        self._require_real_sandbox()
        task = json.loads(Path(self.config["task"]).read_text())
        experiment = json.loads(Path(self.config["experiment"]).read_text())
        inputs = json.loads(Path(self.config["inputs"]).read_text())
        plan = build_plan(task, experiment, inputs)
        labels = {"records": [{"id": item["id"], "labels": {"kind": "a"}}
                              for item in inputs["records"]]}
        for mode, expected in (("invalid", "invalid"), ("missing", "missing")):
            with self.subTest(mode=mode):
                location = self.root / mode
                location.mkdir()
                config = {**self.config, "database": str(location / "state.sqlite"),
                          "artifacts": str(location / "artifacts"),
                          "scope": f"synthetic:{mode}", "response_mode": mode}
                config_path = location / "config.json"
                config_path.write_text(json.dumps(config))
                self.assertEqual(simulate(config_path)["status"], "completed")
                result = evaluate(task, plan, labels, export_saved_predictions(config_path))
                self.assertEqual(len(result[expected]) if mode == "invalid" else result[expected], 6)
                self.assertEqual(result["conditions"][0]["passes"][0]["denominator"], 3)


if __name__ == "__main__":
    unittest.main()
