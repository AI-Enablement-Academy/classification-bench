"""User-facing workflow commands preserve phase and authorization boundaries."""

import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from classification_bench import benchmark, workflow, workflow_execution as execution
from classification_bench.cli import main
from classification_bench.core import ValidationError
from classification_bench.workflow_report import generate_workflow_report
from classification_bench.manifest import canonical_bytes
from classification_bench.adapter_runtime import registry
from tests.test_workflow_scheduler import FixtureRuntime


ROOT = Path(__file__).resolve().parents[1]


class WorkflowExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="workflow-operator-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "prepared" / "workflow.json"

    def prepare(self, example="product", *, smoke_cap=100, policy="pause"):
        spec = {"schema_version": 1, "name": "Fictional <workflow>",
                **{name: str(ROOT / "examples" / example / (name + ".json"))
                   for name in ("task", "experiment", "inputs")},
                "budgets": {"SYN": smoke_cap + 300},
                "phases": {"smoke": {"selection": {"first": 1}, "repeats": 1,
                                      "caps": {"SYN": smoke_cap}, "on_budget_exhausted": policy},
                           "full": {"selection": {"all": True}, "caps": {"SYN": 300},
                                     "on_budget_exhausted": "stop"}},
                "max_concurrency": 2, "provider_limits": {"synthetic": 2},
                "authorization_source": "explicit synthetic test allocation"}
        source = self.root / "spec.json"
        source.write_bytes(canonical_bytes(spec))
        self.cli("workflow-prepare", "--spec", source, "--directory", self.path.parent)
        return workflow.load(self.path)

    def cli(self, *args, success=True):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            if success:
                main([str(arg) for arg in args])
            else:
                with self.assertRaises(SystemExit) as raised:
                    main([str(arg) for arg in args])
                self.assertEqual(raised.exception.code, 2)
                return errors.getvalue()
        self.assertEqual(errors.getvalue(), "")
        return json.loads(output.getvalue())

    def prepare_mixed(self):
        self.calls = []
        configs = []
        for unit in ("USD", "REQ"):
            name = "operator-fixture-" + unit
            registry.register(name, FixtureRuntime(unit, lambda adapter, prepared: self.calls.append(adapter.config["id"])))
            self.addCleanup(registry.unregister, name)
            configs.append({"id": unit, "model": "fixture", "settings": {"adapter": name,
                            "provider": "shared", "reserve": 1, "cost": 1 if unit == "USD" else None}})
        task = {"name": "Mixed offline fixture", "input_keys": ["text"], "fields": [{"name": "kind", "labels": ["a", "b"]}]}
        inputs = {"records": [{"id": str(i), "input": {"text": "fictional"}} for i in range(2)]}
        experiment = {"configs": configs, "prompts": [{"id": "one", "text": "Classify"}], "repeats": 1, "batch_size": 1}
        for name, value in (("task", task), ("inputs", inputs), ("experiment", experiment)):
            (self.root / (name + ".json")).write_bytes(canonical_bytes(value))
        spec = {"schema_version": 1, "name": "Mixed workflow fixture", "task": "task.json", "inputs": "inputs.json",
                "experiment": "experiment.json", "budgets": {"USD": 4, "REQ": 4},
                "phases": {name: {"selection": {"all": True}, "caps": {"USD": 2, "REQ": 2}, "on_budget_exhausted": "pause"}
                           for name in ("smoke", "full")}, "max_concurrency": 2, "provider_limits": {"shared": 2},
                "authorization_source": "offline fixture only"}
        path = self.root / "spec.json"
        path.write_bytes(canonical_bytes(spec))
        return workflow.prepare(path, self.path.parent)

    def test_exact_live_shaped_authorization_runs_only_selected_phase_and_retains_child_authority(self):
        manifest = self.prepare_mixed()
        with self.assertRaisesRegex(ValidationError, "requires --authorization"):
            execution.run(self.path, phase="smoke")
        self.assertEqual(self.calls, [])
        self.assertFalse(Path(manifest["database"]).exists())
        auth = self.root / "authorized.json"
        auth.write_bytes(canonical_bytes(execution.authorization_template(manifest, "smoke")))
        result = execution.run(self.path, phase="smoke", authorization_path=auth)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual({run["budget"]["currency"] for run in result["phases"]["smoke"]["runs"]}, {"REQ", "USD"})
        self.assertEqual(execution.status(self.path, phase="full")["phases"]["full"]["runs"][0]["states"], {"never_sent": 2})
        execution.run(self.path, phase="smoke", authorization_path=auth)
        self.assertEqual(len(self.calls), 4)
        for record in (self.path.parent / "authorizations").glob("*.json"):
            self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        with self.assertRaisesRegex(ValidationError, "does not match"):
            execution.run(self.path, phase="full", authorization_path=auth)
        self.assertEqual(len(self.calls), 4)

    def test_interrupted_aggregate_creation_status_recovery_and_report_remain_usable(self):
        manifest = self.prepare_mixed()
        benchmark.aggregate_budget(manifest["aggregates"]["REQ"]["spec_path"], create=True)
        result = execution.status(self.path)
        self.assertIsNone(result["aggregates"]["USD"])
        self.assertTrue(any(run["status"] == "not_initialized" for run in result["phases"]["smoke"]["runs"]))
        recovered = execution.recover(self.path, phase="smoke")
        self.assertEqual({run["status"] for run in recovered["phases"]["smoke"]["runs"]}, {"never_admitted"})
        snapshot = execution.report_snapshot(self.path)
        self.assertEqual(len(snapshot["phases"]["smoke"]["operations"]), 4)
        self.assertEqual(execution._initialized(manifest)[1], set())
        self.assertEqual(self.calls, [])

    def test_two_fictional_use_cases_complete_cli_smoke_full_export_and_report(self):
        for example in ("product", "candidate"):
            with self.subTest(example=example):
                self.path = self.root / example / "workflow.json"
                manifest = self.prepare(example)
                preview = self.cli("preview", "--workflow", self.path)
                self.assertEqual(set(preview["phases"]), {"smoke", "full"})
                self.assertFalse(Path(manifest["database"]).exists())
                status = self.cli("status", "--workflow", self.path)
                self.assertIsNone(status["aggregates"])
                for phase in ("smoke", "full"):
                    self.assertTrue(self.cli("preflight", "--workflow", self.path, "--phase", phase)["ready"])
                    run = self.cli("run", "--workflow", self.path, "--phase", phase)
                    self.assertEqual(run["phases"][phase]["runs"][0]["status"], "completed")
                    exported = self.cli("export", "--workflow", self.path, "--phase", phase)
                    self.assertEqual(len(exported["records"]), manifest["phases"][phase]["position_count"])
                snapshot = execution.report_snapshot(self.path)
                self.assertEqual(set(snapshot["phases"]), {"smoke", "full"})
                for phase, data in snapshot["phases"].items():
                    self.assertEqual(len(data["operations"]), manifest["phases"][phase]["request_count"])
                    self.assertEqual(len({op["request_id"] for op in data["operations"]}), len(data["operations"]))
                result_path = self.root / (example + "-report.html")
                self.cli("report", "--workflow", self.path, "--labels", ROOT / "examples" / example / "labels.json",
                         "--out", result_path)
                html = result_path.read_text()
                self.assertIn("workflow-data", html)
                self.assertIn("Fictional &lt;workflow&gt;", html)
                self.assertEqual(stat.S_IMODE(result_path.stat().st_mode), 0o600)
                self.assertIn("allow-scripts allow-downloads", html)
                self.assertNotIn("allow-same-origin", html)
                self.assertEqual(self.cli("recover", "--workflow", self.path, "--phase", "smoke")["dispatch_count"], 0)

    def test_phase_required_and_legacy_options_not_silently_ignored(self):
        manifest = self.prepare()
        for action in ("run", "preflight", "export", "recover"):
            self.assertIn("select --phase", self.cli(action, "--workflow", self.path, success=False))
        config = manifest["phases"]["smoke"]["runs"][0]["config_path"]
        self.assertIn("require --workflow", self.cli("preview", "--config", config, "--phase", "full", success=False))
        self.assertIn("require --workflow", self.cli("run", "--config", config, "--authorization", "absent", success=False))
        self.assertFalse(Path(manifest["database"]).exists())

    def test_exhausted_smoke_does_not_stop_full_and_rerun_does_not_replay(self):
        manifest = self.prepare(smoke_cap=1)
        original = benchmark.SyntheticAdapter.parse
        def charged(adapter, *args, **kwargs):
            return replace(original(adapter, *args, **kwargs), observed_cost_microusd=1)
        with patch.object(benchmark.SyntheticAdapter, "parse", charged):
            result = execution.run(self.path, phase="smoke")
            self.assertEqual(result["phases"]["smoke"]["runs"][0]["status"], "paused_budget")
            first = execution.report_snapshot(self.path, phase="smoke")
            execution.run(self.path, phase="smoke")
            self.assertEqual(first, execution.report_snapshot(self.path, phase="smoke"))
            result = execution.run(self.path, phase="full")
            self.assertEqual(result["phases"]["full"]["runs"][0]["status"], "completed")
        self.assertEqual(execution.status(self.path)["aggregates"]["SYN"]["cap"], manifest["aggregates"]["SYN"]["cap"])

    def test_prepared_report_counts_never_sent_and_reference_validation_uses_full_source(self):
        self.prepare()
        snapshot = execution.report_snapshot(self.path)
        html = generate_workflow_report(snapshot)
        self.assertIn("never sent", html)
        labels = json.loads((ROOT / "examples/product/labels.json").read_text())
        selected = execution.report_snapshot(self.path, phase="smoke")
        report = generate_workflow_report(selected, labels)
        self.assertNotIn('id="workflow-data"', report)
        labels["records"][-1]["id"] = "not-in-source"
        with self.assertRaisesRegex(ValidationError, "IDs must exactly match"):
            generate_workflow_report(selected, labels)

    def test_reference_projection_keeps_partial_policy_explicit(self):
        manifest = self.prepare()
        snapshot = execution.report_snapshot(self.path)
        labels = json.loads((ROOT / "examples/product/labels.json").read_text())
        labels["records"] = labels["records"][:1]
        with self.assertRaises(ValidationError):
            generate_workflow_report(snapshot, labels)
        self.assertIn("workflow-data", generate_workflow_report(snapshot, labels, allow_partial_references=True))
        self.assertFalse(Path(manifest["database"]).exists())

    def test_missing_exported_operation_is_rejected(self):
        self.prepare()
        execution.run(self.path, phase="smoke")
        original = benchmark._export_operations_loaded
        with patch.object(benchmark, "_export_operations_loaded", side_effect=lambda *args: original(*args)[:-1]):
            with self.assertRaisesRegex(ValidationError, "coverage is incomplete"):
                execution.report_snapshot(self.path, phase="smoke")

    def test_authorization_validator_rejects_boolean_counts_and_wrong_phase_before_writes(self):
        manifest = self.prepare()
        # Unit-test the exact workflow boundary with live metadata; no runtime is
        # invoked, and no altered manifest is accepted by the public load path.
        manifest["phases"]["smoke"]["runs"][0]["currency"] = "USD"
        auth = self.root / "authorization.json"
        expected = execution.authorization_template(manifest, "smoke")
        for change in ({"request_count": True}, {"phase": "full"}, {"caps": {"USD": 999}},
                       {"schema_version": True}, {"workflow_sha256": "0" * 64}):
            auth.write_bytes(canonical_bytes({**expected, **change}))
            with self.assertRaisesRegex(ValidationError, "does not match"):
                execution._authorize(manifest, "smoke", auth)
            self.assertFalse((self.path.parent / "authorizations").exists())
        with self.assertRaisesRegex(ValidationError, "requires --authorization"):
            execution._authorize(manifest, "smoke", None)

    def test_synthetic_authorization_and_phase_scoped_report_options_fail_usefully(self):
        self.prepare()
        self.assertIn("does not accept", self.cli("run", "--workflow", self.path, "--phase", "smoke",
                                                 "--authorization", "unused", success=False))
        self.assertIn("select --phase", self.cli("report", "--workflow", self.path, "--scenarios", "unused",
                                                 "--out", self.root / "unused.html", success=False))


if __name__ == "__main__":
    unittest.main()
