"""Hand-calculated operational comparisons preserve failed planned positions."""

import copy
import json
import unittest

from classification_bench.core import ValidationError, _digest, build_plan
from classification_bench.report import generate_report
from classification_bench.report_analysis import build_analysis
from classification_bench.report_findings import build_findings, render_findings
from classification_bench.report_operations import build_operational_findings


class OperationalFindingsTests(unittest.TestCase):
    def setUp(self):
        self.task = {"name": "fictional queues", "input_keys": ["text"],
                     "fields": [{"name": "queue", "labels": ["a", "b"]}]}
        self.inputs = {"records": [{"id": cid, "input": {"text": cid}}
                                   for cid in ("x", "y", "z")]}
        self.experiment = {"configs": [{"id": cid, "model": "vendor/model",
            "settings": {"adapter": "openrouter", "provider": "host", "temperature": temp}}
            for cid, temp in (("one", 0), ("two", 1))],
            "prompts": [{"id": "baseline", "text": "Classify"}], "repeats": 1, "batch_size": 2}
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        self.labels = {"records": [{"id": cid, "labels": {"queue": "a"}}
                                  for cid in ("x", "y", "z")]}
        self.predictions = {"records": [
            {"config_id": cid, "prompt_id": "baseline", "repeat": 1, "id": case,
             "prediction": {"queue": value}}
            for cid, case, value in (("one", "x", "a"), ("one", "y", "invalid"),
                                     ("two", "x", "a"), ("two", "y", "a"), ("two", "z", "b"))]}
        self.operations = []
        for request in self.plan["requests"]:
            index = request["batch_index"] - 1
            first = request["config_id"] == "one"
            cost = (10, 20)[index] if first else (5, 7)[index]
            duration = (2, 4)[index] if first else (1, 2)[index]
            tokens = ((100, 20, 2, 10), (150, 30, 3, 20))[index] if first else (
                (80, 10, 1, 5), (120, 15, 2, 10))[index]
            self.operations.append({"request_id": request["request_id"],
                "config_id": request["config_id"], "prompt_id": request["prompt_id"],
                "repeat": request["repeat"], "batch_index": request["batch_index"],
                "ids": [item["id"] for item in request["items"]],
                "state": "outcome_unknown" if first and index else "response_saved",
                "route": "openrouter:vendor/model:host", "provider": "host",
                "returned_provider": "host", "provider_identity_status": "observed",
                "cost_currency": "USD", "observed_cost_micro_usd": cost,
                "duration_seconds": duration, "provider_generation_seconds": duration / 2,
                "generation_response_sha256": ("a" if first else "b") * 64,
                "response_sha256": "c" * 64, "receipt_sha256": "d" * 64,
                "tokenizer": "fixture-tokenizer", "reasoning_tokens": 99, "cache_tokens": 99,
                "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1],
                    "completion_tokens_details": {"reasoning_tokens": tokens[2]},
                    "prompt_tokens_details": {"cached_tokens": tokens[3]}},
                "raw_body": "PRIVATE_RAW_TRANSCRIPT_MUST_NOT_BE_COPIED"})

    def analysis(self, *, labels=True):
        return build_analysis(self.task, self.plan, self.predictions,
                              self.labels if labels else None, self.operations)

    def result(self):
        return build_operational_findings(self.analysis(), self.operations)

    def test_hand_calculated_cost_timing_tokens_and_quality_scope(self):
        result = self.result()
        a, b = result["runs"]
        self.assertEqual(a["measurements"]["observed_cost_micro_usd"]["total"], 30)
        self.assertEqual(b["measurements"]["observed_cost_micro_usd"]["total"], 12)
        self.assertEqual(a["measurements"]["duration_seconds"]["mean"], 3)
        self.assertEqual(b["measurements"]["duration_seconds"]["mean"], 1.5)
        self.assertEqual(a["measurements"]["input_tokens"]["total"], 250)
        self.assertEqual(a["measurements"]["reasoning_tokens"]["total"], 5)
        self.assertEqual(a["measurements"]["cache_tokens"]["total"], 30)
        pair = result["pairs"][0]
        self.assertEqual(pair["comparisons"]["observed_cost_micro_usd"]["delta_b_minus_a"], -18)
        self.assertEqual(pair["comparisons"]["duration_seconds"]["delta_b_minus_a"], -1.5)
        self.assertEqual(pair["comparisons"]["provider_generation_seconds"]["delta_b_minus_a"], -.75)
        self.assertEqual(pair["comparisons"]["input_tokens"]["delta_b_minus_a"], -50)
        self.assertEqual(pair["quality_a"]["planned"], 3)
        self.assertEqual(pair["quality_a"]["exact_correct"], 1)
        self.assertEqual(pair["quality_a"]["invalid"], 1)
        self.assertEqual(pair["quality_a"]["missing"], 1)
        self.assertEqual(pair["quality_b"]["exact_correct"], 2)
        self.assertEqual(pair["lifecycle_a"], {"outcome_unknown": 1, "response_saved": 1})
        self.assertEqual(pair["declared_changes"], [{"pointer": "/settings/temperature",
                                                    "a_present": True, "b_present": True}])
        finding = next(f for f in result["findings"] if f["kind"] == "operational_comparison")
        self.assertEqual(finding["denominator"], 3)
        self.assertIn("2/2", finding["observation"])
        self.assertIn("1/3", finding["observation"])
        self.assertIn("not pure inference", finding["observation"])
        self.assertIn("no causal", finding["interpretation"])

    def test_partial_and_unknown_cost_never_implies_free_or_total_comparison(self):
        self.operations[1]["observed_cost_micro_usd"] = None
        self.operations[1]["unresolved_hold_micro_usd"] = 200
        self.operations[1]["duration_seconds"] = None
        result = self.result()
        self.assertEqual(result["runs"][0]["measurements"]["observed_cost_micro_usd"]["total"], 10)
        self.assertFalse(result["runs"][0]["measurements"]["observed_cost_micro_usd"]["complete"])
        pair = result["pairs"][0]
        self.assertNotIn("observed_cost_micro_usd", pair["comparisons"])
        self.assertNotIn("duration_seconds", pair["comparisons"])
        self.assertIn("incomplete", pair["unavailable_comparisons"]["observed_cost_micro_usd"])
        self.assertEqual(pair["unresolved_hold_micro_usd_a"], 200)
        self.assertEqual(pair["quality_a"]["missing"], 1)

    def test_positive_hold_prevents_a_complete_cost_preference(self):
        self.operations[0]["unresolved_hold_micro_usd"] = 1
        pair = self.result()["pairs"][0]
        self.assertNotIn("observed_cost_micro_usd", pair["comparisons"])
        self.assertIn("unresolved", pair["unavailable_comparisons"]["observed_cost_micro_usd"])

    def test_provider_timing_requires_same_route_provider_and_source(self):
        self.operations[2]["route"] = self.operations[3]["route"] = "other:vendor/model:host"
        result = self.result()
        pair = result["pairs"][0]
        self.assertNotIn("provider_generation_seconds", pair["comparisons"])
        self.assertIn("duration_seconds", pair["comparisons"])
        self.operations[2]["route"] = self.operations[3]["route"] = "openrouter:vendor/model:host"
        self.operations[2].pop("generation_response_sha256")
        self.assertNotIn("provider_generation_seconds", self.result()["pairs"][0]["comparisons"])

    def test_provider_timing_unverified_identity_and_different_observed_hosts_are_not_compared(self):
        for op in self.operations: op["provider_identity_status"] = "unverified:AdapterError"
        self.assertNotIn("provider_generation_seconds", self.result()["pairs"][0]["comparisons"])
        for op in self.operations: op["provider_identity_status"] = "observed"; op["provider"] = "openrouter"
        for op in self.operations[:2]: op["returned_provider"] = "Provider A"
        for op in self.operations[2:]: op["returned_provider"] = "Provider B"
        self.assertNotIn("provider_generation_seconds", self.result()["pairs"][0]["comparisons"])

    def test_per_class_findings_include_support_false_negatives_and_undefined_ratios(self):
        findings = build_findings(self.analysis(), operations=self.operations)
        classes = [item for item in findings["findings"] if item["kind"] == "class_metrics"]
        self.assertEqual(len(classes), 2)
        first = classes[0]
        self.assertEqual(first["denominator"], 3)
        self.assertEqual(first["metrics"]["per_label"]["a"]["support"], 3)
        self.assertEqual(first["metrics"]["per_label"]["a"]["precision"]["value"], 1)
        self.assertEqual(first["metrics"]["per_label"]["a"]["recall"]["value"], 1/3)
        self.assertEqual(first["metrics"]["per_label"]["a"]["f1"]["value"], .5)
        self.assertIsNone(first["metrics"]["per_label"]["b"]["recall"]["value"])
        self.assertEqual(first["metrics"]["known_reference_outcomes"], {"valid": 1, "invalid": 1, "missing": 1})
        self.assertEqual(first["metrics"]["lowest_supported_recall"]["labels"], ["a"])
        self.assertEqual(set(first["case_ids"]), {"y", "z"})
        self.assertIn("false negatives", first["observation"])
        self.assertIn("small support", first["observation"])

    def test_all_tied_supported_classes_are_listed_and_unobserved_classes_not_ranked(self):
        labels = copy.deepcopy(self.labels)
        labels["records"][1]["labels"]["queue"] = "b"
        predictions = {"records": []}
        analysis = build_analysis(self.task, self.plan, predictions, labels, self.operations)
        findings = build_findings(analysis, operations=self.operations)
        classes = [item for item in findings["findings"] if item["kind"] == "class_metrics"]
        self.assertEqual(classes[0]["metrics"]["lowest_supported_recall"], {"value": 0, "labels": ["a", "b"]})
        self.assertEqual(classes[0]["metrics"]["per_label"]["a"]["support"], 2)
        self.assertEqual(classes[0]["metrics"]["per_label"]["b"]["support"], 1)
        self.assertEqual(set(classes[0]["case_ids"]), {"x", "y", "z"})
        unknown = build_findings(self.analysis(labels=False), operations=self.operations)
        first = next(item for item in unknown["findings"] if item["kind"] == "class_metrics")
        self.assertEqual(first["metrics"]["lowest_supported_recall"], {"value": None, "labels": []})
        self.assertIsNone(first["metrics"]["per_label"]["a"]["support"])

    def test_different_or_unavailable_tokenizers_suppress_token_efficiency_comparisons(self):
        self.operations[2]["tokenizer"] = self.operations[3]["tokenizer"] = "other-tokenizer"
        pair = self.result()["pairs"][0]
        self.assertNotIn("input_tokens", pair["comparisons"])
        self.assertIn("tokenizer", pair["unavailable_comparisons"]["input_tokens"])
        for op in self.operations: op.pop("tokenizer")
        self.assertNotIn("output_tokens", self.result()["pairs"][0]["comparisons"])

    def test_synthetic_measurements_are_excluded_even_with_real_looking_values(self):
        for op in self.operations[:2]: op["route"] = "synthetic:offline"
        result = self.result()
        self.assertEqual(result["runs"][0]["synthetic_excluded_requests"], 2)
        self.assertIsNone(result["runs"][0]["measurements"]["duration_seconds"]["total"])
        self.assertEqual(result["pairs"], [])

    def test_invalid_raw_token_details_do_not_fall_back_to_conflicting_flat_values(self):
        self.operations[0]["usage"]["completion_tokens_details"]["reasoning_tokens"] = "bad"
        self.operations[0]["usage"]["prompt_tokens_details"]["cached_tokens"] = 101
        a = self.result()["runs"][0]
        self.assertEqual(a["measurements"]["reasoning_tokens"]["measured_requests"], 1)
        self.assertEqual(a["measurements"]["cache_tokens"]["measured_requests"], 1)
        self.assertEqual(a["measurements"]["cache_tokens"]["total"], 20)

    def test_source_drift_and_unknown_or_duplicate_request_membership_fail_closed(self):
        analysis = self.analysis()
        changed = copy.deepcopy(self.operations)
        changed[0]["duration_seconds"] = 99
        with self.assertRaisesRegex(ValidationError, "operation sources"):
            build_operational_findings(analysis, changed)
        for changed in (self.operations + [self.operations[0]],
                        [{**self.operations[0], "request_id": "unknown"}]):
            supplied = copy.deepcopy(analysis)
            supplied["source_hashes"]["operations"] = _digest(changed)
            with self.assertRaisesRegex(ValidationError, "request membership"):
                build_operational_findings(supplied, changed)

    def test_missing_references_keep_quality_unavailable_and_reliability_measurable(self):
        result = build_operational_findings(self.analysis(labels=False), self.operations)
        pair = result["pairs"][0]
        self.assertIsNone(pair["quality_a"]["full_denominator_exact_rate"])
        self.assertEqual(pair["quality_a"]["valid"], 1)
        self.assertIn("Full-denominator reference agreement is unavailable", result["findings"][-1]["observation"])

    def test_all_prompt_and_repeat_conditions_compare_only_matching_pairs(self):
        experiment = copy.deepcopy(self.experiment)
        experiment["prompts"].append({"id": "other", "text": "A distinct prompt"})
        experiment["repeats"] = 2
        plan = build_plan(self.task, experiment, self.inputs)
        operations = []
        for request in plan["requests"]:
            template = next(op for op in self.operations if
                            op["config_id"] == request["config_id"] and
                            op["batch_index"] == request["batch_index"])
            operations.append({**template, "request_id": request["request_id"],
                               "prompt_id": request["prompt_id"], "repeat": request["repeat"]})
        analysis = build_analysis(self.task, plan, self.predictions, self.labels, operations)
        result = build_operational_findings(analysis, operations)
        self.assertEqual(len(result["pairs"]), 4)
        runs = {run["run_id"]: run for run in analysis["runs"]}
        for pair in result["pairs"]:
            a, b = runs[pair["run_a"]], runs[pair["run_b"]]
            self.assertNotEqual(a["config_id"], b["config_id"])
            self.assertEqual(a["prompt_sha256"], b["prompt_sha256"])
            self.assertEqual(a["repeat"], b["repeat"])
            self.assertEqual(pair["planned_cases"], 3)

    def test_subscription_capacity_and_price_estimates_never_become_dollar_charges(self):
        for op in self.operations[:2]:
            op["cost_currency"] = "REQ"
            op["consumed_requests"] = 1
            op["estimated_cost_micro_usd"] = 999
        result = self.result()
        self.assertIsNone(result["runs"][0]["measurements"]["observed_cost_micro_usd"]["total"])
        self.assertNotIn("observed_cost_micro_usd", result["pairs"][0]["comparisons"])

    def test_catalog_tokenizer_family_does_not_prove_shared_encoding(self):
        for op in self.operations: op.pop("tokenizer")
        for run in self.experiment["configs"]:
            raw = json.dumps({"data": {"architecture": {"tokenizer": "GPT"}}})
            import hashlib
            run["settings"]["endpoint_snapshot"] = {"model_identity": {
                "response_json": raw, "response_sha256": hashlib.sha256(raw.encode()).hexdigest()}}
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        for operation, request in zip(self.operations, self.plan["requests"]):
            operation["request_id"] = request["request_id"]
        pair = self.result()["pairs"][0]
        self.assertNotIn("input_tokens", pair["comparisons"])

    def test_determinism_detached_results_and_no_raw_transcript_copy(self):
        analysis = self.analysis(); before = copy.deepcopy((analysis, self.operations))
        result = build_operational_findings(analysis, self.operations)
        self.assertEqual(result, build_operational_findings(analysis, self.operations))
        self.assertNotIn("PRIVATE_RAW_TRANSCRIPT", json.dumps(result))
        result["runs"][0]["measurements"]["duration_seconds"]["total"] = -1
        self.assertEqual((analysis, self.operations), before)
        for finding in self.result()["findings"]:
            self.assertEqual(finding["source_hashes"], analysis["source_hashes"])
            self.assertTrue(finding["supporting_links"])

    def test_report_and_presentation_findings_receive_exact_operations(self):
        analysis = self.analysis()
        findings = build_findings(analysis, operations=self.operations)
        self.assertTrue(any(f["kind"] == "operational_comparison" for f in findings["findings"]))
        html = generate_report(self.task, self.plan, self.labels, self.predictions, self.operations)
        self.assertIn("Measured operations and output reliability", html)
        self.assertIn("request coverage", render_findings(findings))
        self.assertNotIn("PRIVATE_RAW_TRANSCRIPT", json.dumps(findings))


if __name__ == "__main__":
    unittest.main()
