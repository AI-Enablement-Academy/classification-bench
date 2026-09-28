"""Offline matrix runner and recovery tests; no network or model credentials."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from classification_bench.benchmark import (BenchmarkError, SyntheticAdapter, amend_budget,
                                            export_operations, export_predictions,
                                            preview, recover, report_snapshot, run, status)
from classification_bench.benchmark import _initialize, _load, _refs, _runner_lock
from classification_bench.budget import BudgetLedger
from classification_bench.core import build_plan, evaluate
from classification_bench.adapters import AdapterError, TransportResult


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="benchmark-matrix-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.task = {"name": "fictional", "input_keys": ["text"],
                     "fields": [{"name": "kind", "labels": ["a", "b"]}]}
        self.experiment = {
            "configs": [{"id": name, "model": "synthetic-only",
                         "settings": {"adapter": "synthetic", "response_mode": "first_label"}}
                        for name in ("one", "two")],
            "prompts": [{"id": "p0", "text": "Classify."},
                        {"id": "p1", "text": "Classify carefully."}],
            "repeats": 2, "batch_size": 1}
        self.inputs = {"records": [{"id": "a", "input": {"text": "alpha"}},
                                   {"id": "b", "input": {"text": "beta"}}]}
        self.labels = {"records": [{"id": "a", "labels": {"kind": "a"}},
                                   {"id": "b", "labels": {"kind": "b"}}]}
        self.config = {"schema_version": 1, "task": str(self.root / "task.json"),
                       "experiment": str(self.root / "experiment.json"),
                       "inputs": str(self.root / "inputs.json"),
                       "database": str(self.root / "state.sqlite"),
                       "artifacts": str(self.root / "artifacts"),
                       "scope": "synthetic:matrix", "cap": 2, "currency": "SYN",
                       "scale": 1, "max_concurrency": 2,
                       "provider_limits": {"synthetic": 2}, "authorization_file": None,
                       "on_budget_exhausted": "pause"}
        for name in ("task", "experiment", "inputs", "labels", "config"):
            self.write(name, getattr(self, name))

    def write(self, name, value):
        (self.root / f"{name}.json").write_text(json.dumps(value))

    @property
    def config_path(self):
        return self.root / "config.json"

    def test_preview_matrix_run_replay_and_verified_exports(self):
        before = preview(self.config_path)
        self.assertEqual(before["request_count"], 16)
        self.assertEqual(status(self.config_path)["states"], {"never_sent": 16})
        first = run(self.config_path)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["completed_requests"], 16)
        self.assertEqual(first["errors"], [])
        operations = export_operations(self.config_path)
        self.assertEqual(len(operations), 16)
        self.assertTrue(all(x["parsed_status"] == "valid" and x["response_sha256"] for x in operations))
        self.assertEqual(len(export_predictions(self.config_path)["records"]), 16)
        self.assertEqual(run(self.config_path)["states"], {"response_saved": 16})
        self.assertEqual(BudgetLedger(self.config["database"]).verify(self.config["scope"])[
            "known_charges"], 0)
        plan = build_plan(self.task, self.experiment, self.inputs)
        evaluated = evaluate(self.task, plan, self.labels, export_predictions(self.config_path))
        self.assertEqual(len(evaluated["conditions"]), 4)

    def test_ambiguous_first_config_does_not_stop_other_config_or_resend(self):
        first = preview(self.config_path)["requests"][0]["request_id"]
        original = SyntheticAdapter.dispatch
        seen = []

        def fail_once(adapter, prepared, api_key=None):
            seen.append(prepared.request_id)
            if prepared.request_id == first:
                raise TimeoutError("uncertain synthetic transport")
            return original(adapter, prepared, api_key)

        with patch.object(SyntheticAdapter, "dispatch", fail_once):
            result = run(self.config_path)
        self.assertEqual(result["status"], "recovery_required")
        self.assertEqual(result["states"].get("outcome_unknown"), 1)
        self.assertEqual(result["states"].get("response_saved"), 8)
        self.assertEqual(result["states"].get("never_sent"), 7)
        self.assertEqual(seen.count(first), 1)
        self.assertEqual(recover(self.config_path)["unresolved"], [first])
        self.assertEqual(run(self.config_path)["states"].get("outcome_unknown"), 1)
        self.assertEqual(seen.count(first), 1)
        self.assertEqual(BudgetLedger(self.config["database"]).balances(self.config["scope"])[
            "unknown_holds"], 1)
        snapshot = report_snapshot(self.config_path)
        self.assertEqual(len(snapshot["operations"]), 16)
        self.assertEqual(len(snapshot["predictions"]["records"]), 8)
        self.assertNotIn("labels", snapshot)

    def test_shared_provider_limit_one_still_drains_both_configurations(self):
        self.config["provider_limits"] = {"synthetic": 1}
        self.write("config", self.config)
        result = run(self.config_path)
        self.assertEqual(result["states"], {"response_saved": 16})
        self.assertEqual(result["errors"], [])

    def test_interrupted_preintent_claim_resumes_without_lease_wait(self):
        config, _, binding, materials, _ = _load(self.config_path)
        verified = _initialize(config, binding, materials)
        _refs(verified, materials[0])
        claim = verified.execution.claim("benchmark-matrix", 300)
        self.assertEqual(claim["request_id"], materials[0]["request"]["request_id"])
        resumed = run(self.config_path)
        self.assertEqual(resumed["states"], {"response_saved": 16})
        events = verified.execution.coordinator.events(claim["request_id"])
        self.assertTrue(any(event["event_type"] == "claim_released" for event in events))

    def test_second_orchestrator_is_rejected_before_any_dispatch(self):
        with _runner_lock(self.config["database"]):
            with self.assertRaisesRegex(BenchmarkError, "already_running"):
                run(self.config_path)
            with self.assertRaisesRegex(BenchmarkError, "already_running"):
                report_snapshot(self.config_path)
        self.assertEqual(status(self.config_path)["states"], {"never_sent": 16})

    def test_receipt_survives_failure_before_operation_projection(self):
        self.config["cap"] = 4
        self.write("config", self.config)
        original = __import__("classification_bench.benchmark", fromlist=["_save_observation"])._save_observation
        calls = []

        def interrupt(verified, request_id, response_sha, payload):
            calls.append(request_id)
            if len(calls) == 1:
                raise RuntimeError("after receipt")
            return original(verified, request_id, response_sha, payload)

        with patch("classification_bench.benchmark._save_observation", side_effect=interrupt):
            run(self.config_path)
        self.assertEqual(status(self.config_path)["status"], "completed")
        operations = export_operations(self.config_path)
        self.assertTrue(all(x["parsed_status"] == "valid" for x in operations))
        self.assertTrue(all(x["response_sha256"] for x in operations))
        self.assertEqual(recover(self.config_path)["unresolved"], [])
        self.assertEqual(run(self.config_path)["states"], {"response_saved": 16})

    def test_binding_and_label_path_are_closed(self):
        changed = dict(self.config)
        changed["labels"] = str(self.root / "labels.json")
        self.write("config", changed)
        with self.assertRaisesRegex(BenchmarkError, "exact v1 fields"):
            preview(self.config_path)
        self.write("config", self.config)
        run(self.config_path)
        self.experiment["prompts"][0]["text"] = "Changed."
        self.write("experiment", self.experiment)
        with self.assertRaisesRegex(BenchmarkError, "configuration changed"):
            status(self.config_path)

    def test_captured_invalid_response_counts_as_invalid_on_full_denominator(self):
        self.experiment["configs"][0]["settings"]["response_mode"] = "invalid"
        self.write("experiment", self.experiment)
        result = run(self.config_path)
        self.assertEqual(result["states"], {"response_saved": 16})
        evaluated = evaluate(self.task, build_plan(self.task, self.experiment, self.inputs),
                             self.labels, export_predictions(self.config_path))
        self.assertEqual(evaluated["positions"], 16)
        self.assertEqual(len(evaluated["invalid"]), 8)
        self.assertEqual(evaluated["missing"], 0)
        self.assertEqual(result["parsed_statuses"], {"invalid": 8, "valid": 8})

    def test_missing_batch_remains_missing_in_snapshot(self):
        self.experiment["configs"][0]["settings"]["response_mode"] = "missing"
        self.write("experiment", self.experiment)
        run(self.config_path)
        snapshot = report_snapshot(self.config_path)
        self.assertEqual(len(snapshot["operations"]), 16)
        self.assertEqual(len(snapshot["predictions"]["records"]), 8)
        evaluated = evaluate(snapshot["task"], snapshot["plan"], self.labels,
                             snapshot["predictions"])
        self.assertEqual(evaluated["missing"], 8)
        self.assertEqual(len(evaluated["invalid"]), 0)

    def test_one_bad_label_preserves_other_valid_item_in_same_batch(self):
        self.experiment["configs"] = self.experiment["configs"][:1]
        self.experiment["prompts"] = self.experiment["prompts"][:1]
        self.experiment["repeats"] = 1
        self.experiment["batch_size"] = 2
        self.write("experiment", self.experiment)
        original = SyntheticAdapter.parse

        def one_bad(adapter, result, **kwargs):
            parsed = original(adapter, result, **kwargs)
            items = list(parsed.predictions)
            items[1] = {"id": items[1]["id"], "prediction": {"kind": "__bad__"}}
            return replace(parsed, predictions=tuple(items))

        with patch.object(SyntheticAdapter, "parse", one_bad):
            run(self.config_path)
        snapshot = report_snapshot(self.config_path)
        self.assertEqual(snapshot["operations"][0]["parsed_status"], "invalid")
        self.assertEqual(len(snapshot["predictions"]["records"]), 2)
        result = evaluate(snapshot["task"], snapshot["plan"], self.labels,
                          snapshot["predictions"])
        self.assertEqual(len(result["invalid"]), 1)
        self.assertEqual(result["missing"], 0)

    def test_pause_can_resume_after_bound_cap_amendment_without_resending_unknown(self):
        self.config["cap"] = 1
        self.config["provider_limits"] = {"synthetic": 1}
        self.write("config", self.config)
        first = preview(self.config_path)["requests"][0]["request_id"]
        original = SyntheticAdapter.dispatch
        calls = []

        def uncertain(adapter, prepared, api_key=None):
            calls.append(prepared.request_id)
            if prepared.request_id == first:
                raise TimeoutError("unknown start")
            return original(adapter, prepared, api_key)

        with patch.object(SyntheticAdapter, "dispatch", uncertain):
            paused = run(self.config_path)
        self.assertEqual(paused["status"], "paused_budget")
        self.assertEqual(paused["action_required"], "amend_budget")
        self.assertEqual(paused["states"].get("outcome_unknown"), 1)
        amendment = {"schema_version": 1, "run_sha256": preview(self.config_path)["run_sha256"],
                     "scope": self.config["scope"], "amendment_id": "test-topup-1",
                     "expected_cap": 1, "new_cap": 2,
                     "authorization_source": "explicit offline test amendment"}
        self.write("amendment", amendment)
        self.assertEqual(amend_budget(self.config_path, self.root / "amendment.json")["budget"]["cap"], 2)
        resumed = run(self.config_path)
        self.assertEqual(resumed["status"], "recovery_required")
        self.assertEqual(resumed["states"].get("response_saved"), 8)
        self.assertEqual(calls.count(first), 1)

    def test_stop_is_durable_and_rejects_amendment(self):
        self.config["cap"] = 1
        self.config["provider_limits"] = {"synthetic": 1}
        self.config["on_budget_exhausted"] = "stop"
        self.write("config", self.config)
        first = preview(self.config_path)["requests"][0]["request_id"]
        with patch.object(SyntheticAdapter, "dispatch", side_effect=TimeoutError("unknown")):
            stopped = run(self.config_path)
        self.assertEqual(stopped["status"], "stopped_budget")
        self.assertEqual(run(self.config_path)["status"], "stopped_budget")
        amendment = {"schema_version": 1, "run_sha256": preview(self.config_path)["run_sha256"],
                     "scope": self.config["scope"], "amendment_id": "test-topup-2",
                     "expected_cap": 1, "new_cap": 2,
                     "authorization_source": "explicit offline test amendment"}
        self.write("amendment", amendment)
        with self.assertRaisesRegex(BenchmarkError, "stopped run"):
            amend_budget(self.config_path, self.root / "amendment.json")
        self.assertEqual(status(self.config_path)["states"].get("outcome_unknown"), 1)

    def test_stop_after_observed_charge_exhausts_cap(self):
        self.config["cap"] = 1
        self.config["provider_limits"] = {"synthetic": 1}
        self.config["on_budget_exhausted"] = "stop"
        self.write("config", self.config)
        original = SyntheticAdapter.parse

        def paid(adapter, result, **kwargs):
            return replace(original(adapter, result, **kwargs), observed_cost_microusd=1)

        with patch.object(SyntheticAdapter, "parse", paid):
            stopped = run(self.config_path)
        self.assertEqual(stopped["status"], "stopped_budget")
        self.assertEqual(stopped["states"].get("response_saved"), 1)
        self.assertEqual(sum(count for state, count in stopped["states"].items()
                             if state in ("never_sent", "ready", "claimed")), 15)
        self.assertEqual(BudgetLedger(self.config["database"]).balances(self.config["scope"])[
            "known_charges"], 1)

    def configure_mock_live(self, *, cost=0.000021, generation_model=None):
        model = "example/model-v1"
        provider = "test-provider"
        snapshot = {"model_id": model, "provider_tag": provider,
                    "observed_at": "2026-09-28T11:00:00Z",
                    "source_url": f"https://openrouter.ai/api/v1/models/{model}/endpoints",
                    "max_prompt_tokens": 100, "max_completion_tokens": 20,
                    "supported_parameters": ["max_completion_tokens"],
                    "pricing": {"prompt": "0.000001", "completion": "0.000002",
                                "request": "0", "image": "0"}}
        self.experiment = {"configs": [{"id": "live", "model": model,
                                         "settings": {"adapter": "openrouter",
                                                      "provider": provider,
                                                      "max_output_tokens": 10,
                                                      "endpoint_snapshot": snapshot}}],
                           "prompts": [{"id": "p", "text": "Classify."}],
                           "repeats": 1, "batch_size": 1}
        self.inputs = {"records": self.inputs["records"][:1]}
        self.config.update({"scope": "test:mocked-live", "cap": 200,
                            "currency": "USD", "scale": 1_000_000,
                            "max_concurrency": 1, "provider_limits": {provider: 1},
                            "authorization_file": str(self.root / "authorization.json")})
        for name in ("experiment", "inputs", "config"):
            self.write(name, getattr(self, name))
        planned = preview(self.config_path)
        authorization = {key: planned[key] for key in
                         ("run_sha256", "plan_sha256", "request_count", "scope", "cap")}
        authorization["schema_version"] = 1
        self.write("authorization", authorization)
        request_id = planned["requests"][0]["request_id"]
        content = {"request_id": request_id,
                   "predictions": [{"id": "a", "prediction": {"kind": "a"}}]}
        completion = json.dumps({"id": "generation-1", "model": model,
                                 "choices": [{"finish_reason": "stop",
                                              "message": {"content": json.dumps(content)}}],
                                 "usage": {"prompt_tokens": 5, "completion_tokens": 4,
                                           "cost": cost}}).encode()
        generation = json.dumps({"data": {"id": "generation-1", "model": generation_model or model,
                                          "provider_name": "Test Provider",
                                          "total_cost": cost,
                                          "generation_time": 40}}).encode()
        return completion, generation

    def run_mock_live(self, completion, generation):
        with (patch("classification_bench.network_isolation.NetworkSandboxedPythonWorker.probe",
                    return_value={}),
              patch("classification_bench.adapters.OpenRouterAdapter.verify_live_snapshot",
                    return_value={"catalog_sha256": "a" * 64}),
              patch("classification_bench.network_isolation.isolated_dispatch",
                    return_value=TransportResult(completion, 200, 125)),
              patch("classification_bench.network_isolation.isolated_lookup_generation",
                    return_value=TransportResult(generation, 200, 30))):
            return run(self.config_path, api_key="synthetic-test-key")

    def test_mocked_openrouter_path_saves_generation_identity_and_charge(self):
        completion, generation = self.configure_mock_live()
        result = self.run_mock_live(completion, generation)
        self.assertEqual(result["status"], "completed")
        operation = export_operations(self.config_path)[0]
        self.assertEqual(operation["provider_identity_status"], "observed")
        self.assertEqual(operation["returned_provider"], "Test Provider")
        self.assertEqual(operation["provider_generation_seconds"], 0.04)
        self.assertEqual(operation["observed_cost_micro_usd"], 21)
        self.assertEqual(operation["input_tokens"], 5)
        self.assertEqual(export_predictions(self.config_path)["records"][0]["prediction"],
                         {"kind": "a"})

    def test_definitive_generation_identity_mismatch_is_invalid(self):
        completion, generation = self.configure_mock_live(generation_model="wrong/model")
        result = self.run_mock_live(completion, generation)
        self.assertEqual(result["status"], "completed")
        operation = export_operations(self.config_path)[0]
        self.assertEqual(operation["provider_identity_status"], "identity_error")
        self.assertEqual(operation["parsed_status"], "invalid")
        self.assertEqual(operation["observed_cost_micro_usd"], 21)
        self.assertEqual(export_predictions(self.config_path)["records"][0]["prediction"],
                         {"__invalid_response__": "captured"})

    def test_zero_live_charge_uses_raw_provider_evidence(self):
        completion, generation = self.configure_mock_live(cost=0)
        result = self.run_mock_live(completion, generation)
        self.assertEqual(result["status"], "completed")
        operation = export_operations(self.config_path)[0]
        self.assertEqual(operation["observed_cost_micro_usd"], 0)
        self.assertEqual(BudgetLedger(self.config["database"]).balances(self.config["scope"])[
            "known_charges"], 0)

    def test_generation_lookup_unavailable_keeps_classification_and_usage_charge(self):
        completion, _ = self.configure_mock_live()
        with (patch("classification_bench.network_isolation.NetworkSandboxedPythonWorker.probe",
                    return_value={}),
              patch("classification_bench.adapters.OpenRouterAdapter.verify_live_snapshot",
                    return_value={"catalog_sha256": "a" * 64}),
              patch("classification_bench.network_isolation.isolated_dispatch",
                    return_value=TransportResult(completion, 200, 125)),
              patch("classification_bench.network_isolation.isolated_lookup_generation",
                    side_effect=TimeoutError("metadata unavailable"))):
            result = run(self.config_path, api_key="synthetic-test-key")
        self.assertEqual(result["status"], "completed")
        operation = export_operations(self.config_path)[0]
        self.assertEqual(operation["parsed_status"], "valid")
        self.assertEqual(operation["provider_identity_status"], "unverified:TimeoutError")
        self.assertEqual(operation["observed_cost_micro_usd"], 21)

    def test_preview_shows_request_above_cap_and_run_pauses_without_dispatch(self):
        self.configure_mock_live()
        self.config["cap"] = 100
        self.write("config", self.config)
        planned = preview(self.config_path)
        self.assertEqual(planned["requests"][0]["blocked_reason"],
                         "single request exceeds declared cap")
        authorization = {key: planned[key] for key in
                         ("run_sha256", "plan_sha256", "request_count", "scope", "cap")}
        authorization["schema_version"] = 1
        self.write("authorization", authorization)
        with patch("classification_bench.network_isolation.isolated_dispatch",
                   side_effect=AssertionError("must not dispatch")):
            result = run(self.config_path, api_key="synthetic-test-key")
        self.assertEqual(result["status"], "paused_budget")
        self.assertEqual(result["states"].get("response_saved"), None)

    def test_catalog_drift_blocks_before_admission_and_is_visible_in_status(self):
        self.configure_mock_live()
        with (patch("classification_bench.network_isolation.NetworkSandboxedPythonWorker.probe",
                    return_value={}),
              patch("classification_bench.adapters.OpenRouterAdapter.verify_live_snapshot",
                    side_effect=AdapterError("endpoint pricing drifted")),
              patch("classification_bench.network_isolation.isolated_dispatch",
                    side_effect=AssertionError("must not dispatch"))):
            blocked = run(self.config_path, api_key="synthetic-test-key")
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["preflight_failed_requests"], 1)
        self.assertEqual(blocked["requests"][0]["blocked_reason"],
                         "pre-admission failure: AdapterError")
        self.assertEqual(BudgetLedger(self.config["database"]).balances(self.config["scope"])[
            "active_reservations"], 0)

    def test_unsupported_method_stays_in_roster_without_dispatch(self):
        self.experiment["configs"].append({"id": "native-choice", "model": "fictional-native",
                                            "settings": {"adapter": "native-choice"}})
        self.write("experiment", self.experiment)
        planned = preview(self.config_path)
        self.assertEqual(planned["request_count"], 24)
        self.assertTrue(any(item["blocked_reason"] == "unsupported adapter: native-choice"
                            for item in planned["requests"]))
        result = run(self.config_path)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["states"].get("response_saved"), 16)
        self.assertEqual(result["unsupported_requests"], 8)
        self.assertEqual(result["states"].get("never_sent"), 8)


if __name__ == "__main__":
    unittest.main()
