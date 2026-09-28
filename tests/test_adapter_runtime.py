"""Offline tests of the scheduler's registered adapter runtime contract."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from classification_bench.adapter_runtime import OfflineRuntime, OpenRouterRuntime, registry
from classification_bench.adapters import ParsedResponse, PreparedRequest, TransportResult
from classification_bench.benchmark import (_execute_one, _initialize, _load,
                                            export_predictions, preview, report_snapshot, run)
from classification_bench.evidence import read_artifact
from classification_bench.manifest import canonical_bytes


class OtherAdapter:
    """A different, trusted offline protocol with its own body and response."""

    provider = "fixture-provider"

    def __init__(self, config):
        settings = config["settings"]
        if (config["model"] != "other-only" or set(settings) != {"adapter", "token"} or
                settings["token"] != "declared"):
            raise ValueError("unsupported fixture controls")

    def prepare(self, plan, request, prompt):
        return PreparedRequest(canonical_bytes({"request_id": request["request_id"],
                                                "messages": [{"role": "system", "content": prompt["text"]}],
                                                "item_ids": [x["id"] for x in request["items"]]}),
                               1, "fixture:zero", "fixture:offline", request["request_id"],
                               tuple(x["id"] for x in request["items"]))

    def dispatch(self, prepared):
        body = json.loads(prepared.body)
        return TransportResult(canonical_bytes({"request_id": prepared.request_id,
                                                "answers": [{"id": item_id,
                                                             "prediction": {"kind": "b"}}
                                                            for item_id in body["item_ids"]]}),
                               200, 3)

    def parse(self, result, *, expected_request_id, expected_ids, expected_model):
        value = json.loads(result.raw_bytes)
        if (value["request_id"] != expected_request_id or expected_model != "other-only" or
                tuple(x["id"] for x in value["answers"]) != expected_ids):
            raise ValueError("response identity mismatch")
        return ParsedResponse("valid", tuple(value["answers"]), None, 0,
                              "other-only", "fixture-provider", None, "stop")


class AuthorizedOfflineFixtureRuntime(OfflineRuntime):
    """Exercises live-shaped admission with no network operation or credential."""

    offline = False


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="adapter-runtime-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        task = {"name": "fixture", "input_keys": ["text"],
                "fields": [{"name": "kind", "labels": ["a", "b"]}]}
        experiment = {"configs": [{"id": "other", "model": "other-only",
                                    "settings": {"adapter": "other-runtime", "token": "declared"}}],
                      "prompts": [{"id": "p", "text": "Classify."}],
                      "repeats": 1, "batch_size": 1}
        inputs = {"records": [{"id": "i", "input": {"text": "example"}}]}
        self.config = {"schema_version": 1, "task": str(root / "task.json"),
                       "experiment": str(root / "experiment.json"),
                       "inputs": str(root / "inputs.json"),
                       "database": str(root / "run.sqlite"),
                       "artifacts": str(root / "artifacts"),
                       "scope": "synthetic:other", "cap": 1, "currency": "SYN",
                       "scale": 1, "max_concurrency": 1,
                       "provider_limits": {"fixture-provider": 1},
                       "authorization_file": None, "on_budget_exhausted": "pause"}
        self.config_path = root / "config.json"
        for name, value in (("task", task), ("experiment", experiment),
                            ("inputs", inputs), ("config", self.config)):
            (root / f"{name}.json").write_text(json.dumps(value))
        registry.register("other-runtime", OfflineRuntime(OtherAdapter,
                          identity_status="fixture-observed", zero_charge_source="fixture:zero"))
        self.addCleanup(registry.unregister, "other-runtime")

    def test_live_preflight_binds_fresh_catalog_and_canonical_identity_hashes(self):
        adapter = Mock()
        adapter.verify_live_snapshot.return_value = {
            "catalog_sha256": "a" * 64, "identity_response_sha256": "b" * 64}
        worker = Mock()
        prepared = PreparedRequest(b"{}", 1, "frozen-snapshot", "route", "request", ("i",))
        source = OpenRouterRuntime().preflight(adapter, prepared, worker)
        self.assertEqual(source, "frozen-snapshot:catalog:" + "a" * 64 + ":identity:" + "b" * 64)
        worker.probe.assert_called_once_with()
        adapter.verify_live_snapshot.assert_called_once_with()

    def test_distinct_runtime_uses_unchanged_scheduler_and_rejects_controls(self):
        self.assertEqual(preview(self.config_path)["request_count"], 1)
        result = run(self.config_path)
        self.assertEqual(result["states"], {"response_saved": 1})
        snapshot = report_snapshot(self.config_path)
        self.assertEqual(snapshot["predictions"]["records"][0]["prediction"], {"kind": "b"})
        self.assertEqual(snapshot["operations"][0]["provider_identity_status"], "fixture-observed")
        experiment = json.loads(Path(self.config["experiment"]).read_text())
        experiment["configs"][0]["settings"]["unknown_control"] = True
        Path(self.config["experiment"]).write_text(json.dumps(experiment))
        with self.assertRaisesRegex(ValueError, "unsupported fixture controls"):
            preview(self.config_path)

    def test_saved_older_adapter_digest_is_readable_but_cannot_resume_dispatch(self):
        config, _, binding, materials, _ = _load(self.config_path)
        verified = _initialize(config, binding, materials)
        material = materials[0]
        old_manifest = json.loads(material["manifest"])
        old_manifest["adapter_source_sha256"] = "a" * 64
        old_manifest["route"] = "fixture:legacy-route"
        old_manifest.pop("runtime_source_sha256")
        old_manifest.pop("transport_source_sha256")
        refs = verified.enqueue_bytes(material["request"]["request_id"], config["scope"],
                                      canonical_bytes(old_manifest), material["prepared"].body)
        claim = verified.execution.claim("benchmark-matrix", 300)
        _execute_one(config, material, verified, claim, refs, None, None)
        self.assertEqual(len(export_predictions(self.config_path)["records"]), 1)
        operation = report_snapshot(self.config_path)["operations"][0]
        self.assertEqual(operation["parsed_status"], "valid")
        self.assertEqual(operation["route"], "fixture:legacy-route")
        self.assertEqual(operation["adapter_source_sha256"], "a" * 64)
        with self.assertRaisesRegex(ValueError, "artifact store directory is missing|frozen request bytes changed|enrolled evidence changed"):
            run(self.config_path)
        self.assertEqual(read_artifact(config["artifacts"], refs["manifest_ref"]),
                         canonical_bytes(old_manifest))

    def test_registered_live_shaped_runtime_needs_no_openrouter_credential(self):
        registry.unregister("other-runtime")
        # Replace the registry entry under its declared adapter name. The
        # runtime's dispatch is still the deterministic, no-network fixture.
        registry.register("other-runtime", AuthorizedOfflineFixtureRuntime(
            OtherAdapter, identity_status="fixture-observed",
            zero_charge_source="fixture:zero"))
        self.config.update(scope="fixture:authorized", currency="USD", scale=1_000_000,
                           authorization_file=str(self.config_path.parent / "auth.json"))
        self.config_path.write_text(json.dumps(self.config))
        planned = preview(self.config_path)
        Path(self.config["authorization_file"]).write_text(json.dumps({
            "schema_version": 1, "run_sha256": planned["run_sha256"],
            "plan_sha256": planned["plan_sha256"], "request_count": 1,
            "scope": self.config["scope"], "cap": self.config["cap"]}))
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            result = run(self.config_path)
        self.assertEqual(result["states"], {"response_saved": 1})
        self.assertEqual(report_snapshot(self.config_path)["operations"][0]["provider"],
                         "fixture-provider")


if __name__ == "__main__":
    unittest.main()
