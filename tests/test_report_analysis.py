"""Generic deterministic run/case analysis, without provider execution."""

from copy import deepcopy
from itertools import combinations
import json
import unittest

from classification_bench.core import ValidationError, _digest, build_plan
from classification_bench.report_analysis import build_analysis, compare_runs, AGREEMENT_RULE


def fixture():
    task = {"name": "warehouse exception routing", "input_keys": ["operator_note", "location"],
            "fields": [{"name": "destination", "labels": ["repair", "ship"]},
                       {"name": "handling", "labels": ["ordinary", "urgent"]}]}
    experiment = {"configs": [{"id": "model-one", "model": "fixture/alpha", "model_type": "llm"},
                              {"id": "model-two", "model": "fixture/beta", "model_type": "decision"}],
                  "prompts": [{"id": "standard rubric", "text": "Classify warehouse exceptions."},
                              {"id": "SOP revision", "text": "Classify using the documented escalation procedure."}],
                  "repeats": 2, "batch_size": 2}
    ids = ["case/α", "case b", "case-c", "case-d"]
    inputs = {"records": [{"id": rid, "input": {"operator_note": f"quoted note for {rid}", "location": "bay 2"}}
                          for rid in ids]}
    plan = build_plan(task, experiment, inputs)
    labels = {"records": [{"id": rid, "labels": {"destination": destination, "handling": handling}}
                          for rid, destination, handling in [
                              (ids[0], "repair", "ordinary"), (ids[1], "repair", "urgent"),
                              (ids[2], "ship", "urgent"), (ids[3], "repair", "ordinary")]]}
    values = {
        ("model-one", "standard rubric", 1): [("repair", "ordinary"), ("ship", "ordinary"), ("outside-vocabulary", "urgent"), None],
        ("model-one", "SOP revision", 1): [("ship", "ordinary"), ("repair", "urgent"), ("ship", "urgent"), None],
        ("model-two", "standard rubric", 1): [("ship", "ordinary"), ("repair", "urgent"), ("repair", "urgent"), ("repair", "ordinary")],
    }
    predictions = {"records": [{"config_id": key[0], "prompt_id": key[1], "repeat": key[2], "id": rid,
                                 "prediction": {"destination": pair[0], "handling": pair[1]}}
                                for key, pairs in values.items() for rid, pair in zip(ids, pairs) if pair is not None]}
    return task, plan, predictions, labels


def by_run(analysis, config="model-one", prompt="standard rubric", repeat=1):
    return next(r for r in analysis["runs"] if (r["config_id"], r["prompt_id"], r["repeat"]) == (config, prompt, repeat))


class ReportAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.task, self.plan, self.predictions, self.labels = fixture()

    def test_full_planned_runs_cases_and_validity_states_are_retained(self):
        result = build_analysis(self.task, self.plan, self.predictions, self.labels)
        self.assertEqual(result["positions"], 32)
        self.assertEqual(len(result["runs"]), 8)
        baseline = by_run(result)
        self.assertEqual([c["case_id"] for c in baseline["cases"]], result["case_ids"])
        self.assertEqual([c["prediction_status"] for c in baseline["cases"]], ["valid", "valid", "invalid", "missing"])
        self.assertEqual(baseline["counts"]["planned"], 4)
        self.assertEqual(baseline["counts"]["invalid"], 1)
        self.assertEqual(baseline["counts"]["missing"], 1)
        self.assertIsNone(baseline["cases"][2]["prediction"])
        self.assertEqual(baseline["cases"][2]["raw_prediction"]["destination"], "outside-vocabulary")
        never_supplied = by_run(result, repeat=2)
        self.assertEqual(never_supplied["counts"]["missing"], 4)
        self.assertEqual(never_supplied["counts"]["full_denominator_exact_rate"], 0)

    def test_correctness_and_full_denominator_include_unusable_reference_cases(self):
        result = build_analysis(self.task, self.plan, self.predictions, self.labels)
        baseline = by_run(result)
        self.assertEqual(baseline["counts"]["full_reference"], 4)
        self.assertEqual(baseline["counts"]["exact_correct"], 1)
        self.assertEqual(baseline["counts"]["full_denominator_exact_rate"], 1 / 4)
        self.assertEqual([c["exact_match"] for c in baseline["cases"]], [True, False, None, None])
        self.assertIsNone(baseline["cases"][2]["field_matches"]["destination"])

    def test_unlabeled_analysis_has_prediction_agreement_without_accuracy(self):
        result = build_analysis(self.task, self.plan, self.predictions)
        self.assertIsNone(result["source_hashes"]["labels"])
        for run in result["runs"]:
            self.assertEqual(run["counts"]["no_reference"], 4)
            self.assertIsNone(run["counts"]["known_reference_exact_rate"])
            self.assertIsNone(run["counts"]["full_denominator_exact_rate"])
            self.assertTrue(all(c["exact_match"] is None for c in run["cases"]))
        pair = self._pair(result)
        self.assertEqual(pair["accepted_reference_unknown"], 2)
        self.assertEqual(pair["accepted_correct"], 0)
        self.assertEqual(pair["accepted_error"], 0)
        self.assertEqual(pair["deferred"], 2)
        self.assertTrue(all(x["net_gain"] is None for x in result["prompt_comparisons"]))

    def test_partial_null_and_omitted_references_do_not_invent_values(self):
        partial = {"records": [self.labels["records"][0],
            {"id": "case b", "labels": {"destination": "repair", "handling": None}}]}
        result = build_analysis(self.task, self.plan, self.predictions, partial)
        baseline = by_run(result)
        self.assertEqual([c["reference_status"] for c in baseline["cases"]], ["full", "partial", "missing", "missing"])
        self.assertEqual(baseline["cases"][1]["reference"], {"destination": "repair"})
        self.assertIsNone(baseline["cases"][1]["field_matches"]["handling"])
        self.assertEqual(baseline["counts"]["known_reference_exact_rate"], 1)
        self.assertIsNone(baseline["counts"]["full_denominator_exact_rate"])
        pair = self._pair(result)
        self.assertEqual((pair["accepted_error"], pair["accepted_reference_unknown"], pair["deferred"]), (1, 1, 2))

    def test_prediction_and_label_validation_reuses_strict_core_boundary(self):
        duplicate = deepcopy(self.predictions)
        duplicate["records"].append(deepcopy(duplicate["records"][0]))
        with self.assertRaises(ValidationError):
            build_analysis(self.task, self.plan, duplicate, self.labels)
        bad = deepcopy(self.plan)
        bad["requests"][0]["request_id"] = "0" * 64
        with self.assertRaises(ValidationError):
            build_analysis(self.task, bad, self.predictions, self.labels)
        for labels in ({"records": [{"id": "unknown", "labels": {}}]},
                       {"records": [{"id": "case/α", "labels": {"destination": "invented"}}]},
                       {"records": [{"id": "case/α", "labels": {}, "notes": "not allowed"}]}):
            with self.assertRaises(ValidationError):
                build_analysis(self.task, self.plan, self.predictions, labels)

    def test_run_ids_stay_stable_across_prediction_and_reference_versions(self):
        original = build_analysis(self.task, self.plan, self.predictions, self.labels)
        corrected = deepcopy(self.labels)
        corrected["records"][0]["labels"]["destination"] = "ship"
        alternative = build_analysis(self.task, self.plan, self.predictions, corrected)
        self.assertEqual([r["run_id"] for r in original["runs"]], [r["run_id"] for r in alternative["runs"]])
        self.assertNotEqual(original["analysis_id"], alternative["analysis_id"])
        empty = build_analysis(self.task, self.plan, {"records": []}, self.labels)
        self.assertEqual([r["run_id"] for r in original["runs"]], [r["run_id"] for r in empty["runs"]])
        self.assertNotEqual(original["analysis_id"], empty["analysis_id"])

    def test_run_id_binds_model_prompt_effort_input_repeat_and_batch_shape(self):
        baseline = build_analysis(self.task, self.plan, {"records": []})
        ids = {r["run_id"] for r in baseline["runs"]}
        self.assertEqual(len(ids), 8)
        items = [item for request in self.plan["requests"][:2] for item in request["items"]]
        variants = []
        experiment = deepcopy(self.plan["experiment"])
        experiment["configs"][0]["settings"] = {"effort": "high"}
        variants.append(build_plan(self.task, experiment, {"records": items}))
        experiment = deepcopy(self.plan["experiment"])
        experiment["prompts"][0]["text"] += " Changed."
        variants.append(build_plan(self.task, experiment, {"records": items}))
        experiment = deepcopy(self.plan["experiment"])
        experiment["batch_size"] = 1
        variants.append(build_plan(self.task, experiment, {"records": items}))
        changed = deepcopy(items)
        changed[0]["input"]["location"] = "bay 9"
        variants.append(build_plan(self.task, self.plan["experiment"], {"records": changed}))
        for plan in variants:
            altered = build_analysis(self.task, plan, {"records": []})
            self.assertNotEqual(by_run(baseline)["run_id"], by_run(altered)["run_id"])

    def test_sources_and_analysis_are_never_mutated(self):
        values = self.task, self.plan, self.predictions, self.labels
        before = [_digest(value) for value in values]
        result = build_analysis(*values[:3], values[3])
        result["runs"][0]["cases"][0]["reference"]["destination"] = "ship"
        result["runs"][0]["cases"][0]["prediction"]["destination"] = "ship"
        result["runs"][0]["configuration"]["model"] = "edited"
        self.assertEqual(before, [_digest(value) for value in values])

    def test_exact_ab_diffs_include_status_turnover_and_field_values(self):
        result = build_analysis(self.task, self.plan, self.predictions, self.labels)
        a, b = by_run(result), by_run(result, prompt="SOP revision")
        comparison = compare_runs(result, a["run_id"], b["run_id"])
        self.assertTrue(comparison["compatibility"]["compatible"])
        self.assertEqual(comparison["planned"], 4)
        self.assertEqual(comparison["comparable"], 2)
        self.assertEqual(comparison["changed_ids"], ["case/α", "case b"])
        self.assertEqual(comparison["excluded_ids"], ["case-c", "case-d"])
        self.assertEqual(comparison["fields"]["handling"]["changed_ids"], ["case b"])
        case = comparison["cases"][2]
        self.assertEqual((case["status_a"], case["status_b"]), ("invalid", "valid"))
        self.assertTrue(case["status_changed"])
        self.assertIsNone(case["fields"]["destination"]["different"])
        self.assertEqual(case["fields"]["destination"]["b"], "ship")

    def test_ab_rejects_unknown_identical_and_incompatible_scopes(self):
        result = build_analysis(self.task, self.plan, self.predictions)
        a, b = result["runs"][:2]
        for x, y in ((a["run_id"], "unknown"), (a["run_id"], a["run_id"])):
            with self.assertRaises(ValidationError):
                compare_runs(result, x, y)
        for key, value in (("task_sha256", "other-task"), ("input_sha256", "other-input"), ("case_ids", ["different"])):
            changed = deepcopy(result)
            changed["runs"][1][key] = value
            compared = compare_runs(changed, a["run_id"], b["run_id"])
            self.assertFalse(compared["compatibility"]["compatible"])
            self.assertEqual(compared["cases"], [])
            self.assertIsNone(compared["planned"])

    def test_paired_prompt_gains_losses_and_validity_turnover_keep_exact_ids(self):
        result = build_analysis(self.task, self.plan, self.predictions, self.labels)
        entry = next(x for x in result["prompt_comparisons"] if x["config_id"] == "model-one" and x["repeat"] == 1)
        self.assertEqual(entry["planned"], 4)
        self.assertEqual(entry["gained_ids"], ["case b", "case-c"])
        self.assertEqual(entry["lost_ids"], ["case/α"])
        self.assertEqual(entry["stable_error_ids"], ["case-d"])
        self.assertEqual(entry["unusable_to_valid_ids"], ["case-c"])
        self.assertEqual(entry["unusable_both_ids"], ["case-d"])
        self.assertEqual(entry["net_gain"], 1)
        self.assertEqual(entry["fields"]["handling"]["gained_ids"], ["case b", "case-c"])
        self.assertEqual(entry["fields"]["handling"]["stable_correct_ids"], ["case/α"])

    def test_all_unordered_eligible_pairs_use_full_denominator(self):
        result = build_analysis(self.task, self.plan, self.predictions, self.labels)
        self.assertEqual(len(result["agreement_pairs"]), 28)
        expected = {frozenset((a["run_id"], b["run_id"])) for a, b in combinations(result["runs"], 2)}
        actual = {frozenset((p["run_a"], p["run_b"])) for p in result["agreement_pairs"]}
        self.assertEqual(actual, expected)
        self.assertEqual(len({p["pair_id"] for p in result["agreement_pairs"]}), 28)
        for pair in result["agreement_pairs"]:
            self.assertEqual(pair["rule"], AGREEMENT_RULE)
            self.assertEqual(pair["planned"], 4)
            self.assertEqual(sum(pair[k] for k in ("accepted_correct", "accepted_error", "accepted_reference_unknown", "deferred")), 4)
        pair = self._pair(result)
        self.assertEqual(pair["accepted_correct_ids"], ["case b"])
        self.assertEqual(pair["accepted_error_ids"], ["case/α"])
        self.assertEqual(pair["deferred_ids"], ["case-c", "case-d"])
        self.assertEqual(pair["acceptance_rate"], 0.5)

    def test_equal_invalid_outputs_are_always_deferred(self):
        result = build_analysis(self.task, self.plan, {"records": []}, self.labels)
        self.assertTrue(all(p["accepted"] == 0 and p["deferred"] == 4 for p in result["agreement_pairs"]))
        predictions = deepcopy(self.predictions)
        predictions["records"].append({"config_id": "model-two", "prompt_id": "SOP revision", "repeat": 2,
            "id": "case-c", "prediction": {"destination": "outside-vocabulary", "handling": "urgent"}})
        result = build_analysis(self.task, self.plan, predictions, self.labels)
        a, b = by_run(result), by_run(result, "model-two", "SOP revision", 2)
        pair = next(p for p in result["agreement_pairs"] if {p["run_a"], p["run_b"]} == {a["run_id"], b["run_id"]})
        self.assertIn("case-c", pair["deferred_ids"])
        self.assertIn("a_invalid", pair["deferred_reasons"]["case-c"])

    def test_operation_scope_validation_and_original_lifecycle_are_preserved(self):
        request = self.plan["requests"][0]
        op = {"request_id": request["request_id"], "config_id": request["config_id"],
              "prompt_id": request["prompt_id"], "repeat": request["repeat"],
              "ids": [i["id"] for i in request["items"]], "state": "outcome_unknown", "parsed_status": "unknown",
              "reason": "ambiguous interruption", "response_sha256": "a" * 64, "receipt_sha256": "b" * 64}
        result = build_analysis(self.task, self.plan, self.predictions, self.labels, [op])
        case = by_run(result)["cases"][0]
        self.assertEqual(case["lifecycle_state"], "outcome_unknown")
        self.assertEqual(case["reason"], "ambiguous interruption")
        self.assertEqual(case["evidence"]["receipt_sha256"], "b" * 64)
        self.assertEqual(case["evidence_format"]["receipt_sha256"], "sha256")
        self.assertIn("not independently verified", case["evidence_verification"])
        self.assertEqual(result["source_hashes"]["operations"], _digest([op]))
        for bad in ([op, op], [{**op, "request_id": "not-planned"}], [{**op, "config_id": "different"}],
                    [{**op, "ids": ["different"]}], [{**op, "receipt_sha256": {"bad": "pointer"}}]):
            with self.assertRaises(ValidationError):
                build_analysis(self.task, self.plan, self.predictions, operations=bad)

    def test_legacy_opaque_receipt_pointer_is_preserved_with_explicit_format(self):
        op = {"request_id": self.plan["requests"][0]["request_id"], "receipt_sha256": "receipt-alpha-plain-1"}
        original = deepcopy(op)
        result = build_analysis(self.task, self.plan, self.predictions, operations=[op])
        case = by_run(result)["cases"][0]
        self.assertEqual(case["evidence"]["receipt_sha256"], "receipt-alpha-plain-1")
        self.assertEqual(case["evidence_format"]["receipt_sha256"], "opaque_pointer")
        self.assertEqual(result["source_hashes"]["operations"], _digest([op]))
        self.assertEqual(op, original)

    def test_two_run_costs_deduplicate_batches_and_expose_incomplete_coverage(self):
        ops = [{"request_id": r["request_id"], "cost_currency": "USD", "observed_cost_micro_usd": 10,
                "route": "provider:fixture"} for r in self.plan["requests"]]
        result = build_analysis(self.task, self.plan, self.predictions, self.labels, ops)
        pair = self._pair(result)
        self.assertEqual(pair["cost"]["observed_cost_micro_usd"], 40)
        self.assertEqual(pair["cost"]["observed_cost_requests"], 4)
        self.assertEqual(by_run(result)["cost"]["observed_cost_micro_usd"], 20)
        # Four cases in each run share two receipts; charge is not multiplied.
        del ops[0]["observed_cost_micro_usd"]
        ops[0]["unresolved_hold_micro_usd"] = 99
        result = build_analysis(self.task, self.plan, self.predictions, self.labels, ops)
        a, b = result["runs"][:2]
        pair = next(p for p in result["agreement_pairs"] if {p["run_a"], p["run_b"]} == {a["run_id"], b["run_id"]})
        self.assertIsNone(pair["cost"]["observed_cost_micro_usd"])
        self.assertEqual(pair["cost"]["partial_observed_cost_micro_usd"], 30)
        self.assertEqual(pair["cost"]["unresolved_hold_micro_usd"], 99)

    def test_subscription_hold_known_zero_is_not_unavailable(self):
        ops = [{"request_id": r["request_id"], "cost_currency": "REQ", "consumed_requests": 1,
                "unresolved_request_hold": 0} for r in self.plan["requests"]]
        result = build_analysis(self.task, self.plan, self.predictions, operations=ops)
        self.assertEqual(by_run(result)["cost"]["unresolved_subscription_invocations"], 0)
        self.assertEqual(self._pair(result)["cost"]["unresolved_subscription_invocations"], 0)
        for op in ops:
            del op["unresolved_request_hold"]
        unknown = build_analysis(self.task, self.plan, self.predictions, operations=ops)
        self.assertIsNone(by_run(unknown)["cost"]["unresolved_subscription_invocations"])
        self.assertIsNone(self._pair(unknown)["cost"]["unresolved_subscription_invocations"])

    def test_subscription_usage_and_synthetic_costs_never_become_actual_usd(self):
        ops = [{"request_id": r["request_id"], "cost_currency": "REQ", "accounting_unit": "request",
                "consumed_requests": 1, "observed_cost_micro_usd": 123, "route": "codex:fixture"}
               for r in self.plan["requests"]]
        result = build_analysis(self.task, self.plan, self.predictions, operations=ops)
        pair = self._pair(result)
        self.assertIsNone(pair["cost"]["observed_cost_micro_usd"])
        self.assertIsNone(pair["cost"]["partial_observed_cost_micro_usd"])
        self.assertEqual(pair["cost"]["subscription_invocations"], 4)
        for op in ops:
            op.update(cost_currency="USD", route="synthetic:fixture")
        result = build_analysis(self.task, self.plan, self.predictions, operations=ops)
        pair = self._pair(result)
        self.assertEqual(pair["cost"]["synthetic_excluded_requests"], 4)
        self.assertIsNone(pair["cost"]["observed_cost_micro_usd"])

    def test_cohort_denominators_distinguish_runs_configs_and_unusable_cases(self):
        result = build_analysis(self.task, self.plan, self.predictions, self.labels)
        cohort = result["cohorts"][0]
        self.assertEqual(cohort["origin"], "unspecified")
        self.assertEqual(cohort["distinct_configurations"], 2)
        self.assertEqual(cohort["planned_runs"], 8)
        self.assertIn("case/α", cohort["disagreement_ids"])
        self.assertIn("case/α", cohort["reference_error_ids"])
        self.assertIn("case-c", cohort["unusable_ids"])
        self.assertEqual(len(cohort["agreement_pair_ids"]), 28)
        self.assertEqual(cohort["cases"][0]["planned_runs"], 8)
        self.assertEqual(cohort["cases"][0]["distinct_configurations"], 2)

    def test_fresh_historical_cohorts_require_explicit_compatible_run_selection(self):
        initial = build_analysis(self.task, self.plan, self.predictions)
        fresh = [by_run(initial)["run_id"], by_run(initial, "model-two")["run_id"]]
        declarations = [{"id": "operator-fresh", "title": "Declared fresh cohort", "origin": "declared_fresh",
                         "run_ids": fresh, "one_run_per_configuration": True, "source": "operator manifest v1",
                         "case_ids": ["case/α", "case-c"]},
                        {"id": "operator-historical", "title": "Historical cohort", "origin": "historical",
                         "run_ids": [by_run(initial, repeat=2)["run_id"]],
                         "one_run_per_configuration": True, "source": "import declaration v1"}]
        result = build_analysis(self.task, self.plan, self.predictions, cohort_declarations=declarations)
        self.assertEqual(result["cohorts"][0]["case_ids"], ["case/α", "case-c"])
        self.assertEqual(result["cohorts"][0]["distinct_configurations"], 2)
        self.assertEqual(result["cohorts"][0]["declaration_status"], "operator_declared")
        self.assertEqual(len(result["cohorts"][0]["agreement_pair_ids"]), 1)
        self.assertNotEqual(result["analysis_id"], initial["analysis_id"])
        bad = deepcopy(declarations)
        bad[0]["run_ids"].append(by_run(initial, prompt="SOP revision")["run_id"])
        with self.assertRaisesRegex(ValidationError, "one explicitly selected run"):
            build_analysis(self.task, self.plan, self.predictions, cohort_declarations=bad)

    def test_reproducible_analysis_and_hashes_cover_actual_source_objects(self):
        result = build_analysis(self.task, self.plan, self.predictions, self.labels)
        again = build_analysis(self.task, self.plan, self.predictions, self.labels)
        self.assertEqual(result, again)
        self.assertEqual(result["source_hashes"]["task"], _digest(self.task))
        self.assertEqual(result["source_hashes"]["plan"], _digest(self.plan))
        self.assertEqual(result["source_hashes"]["predictions"], _digest(self.predictions))
        self.assertEqual(result["source_hashes"]["labels"], _digest(self.labels))
        self.assertIsInstance(json.dumps(result, allow_nan=False), str)

    def test_repeat_ranges_and_per_field_flips_keep_incomplete_passes(self):
        result = build_analysis(self.task, self.plan, self.predictions, self.labels)
        entry = next(x for x in result["repeat_ranges"] if x["config_id"] == "model-one" and x["prompt_id"] == "standard rubric")
        self.assertEqual(entry["planned_runs"], 2)
        self.assertEqual(entry["full_denominator_exact_rate_range"], [0, 0.25])
        self.assertEqual(entry["validity_rate_range"], [0, 0.5])
        repeats = result["repeat_comparisons"]
        self.assertEqual(len(repeats), 4)
        self.assertTrue(all(x["planned"] == 4 for x in repeats))
        self.assertTrue(all(x["flip_rate"] is None for x in repeats))
        self.assertTrue(all(x["fields"]["handling"]["flip_rate"] is None for x in repeats))
        unreferenced = build_analysis(self.task, self.plan, self.predictions)
        self.assertTrue(all(x["full_denominator_exact_rate_range"] is None for x in unreferenced["repeat_ranges"]))

    def test_declared_cohort_input_is_not_aliased_into_result(self):
        first = build_analysis(self.task, self.plan, self.predictions)
        declarations = [{"id": "selected", "title": "Explicit cohort", "origin": "historical",
                         "run_ids": [first["runs"][0]["run_id"]], "one_run_per_configuration": True,
                         "source": "operator declaration"}]
        before = _digest(declarations)
        result = build_analysis(self.task, self.plan, self.predictions, cohort_declarations=declarations)
        result["cohorts"][0]["cases"][0]["run_ids"].append("edited-output-only")
        self.assertEqual(before, _digest(declarations))
        for key, value in (("run_ids", [["invalid"]]), ("case_ids", [["invalid"]])):
            bad = deepcopy(declarations)
            bad[0][key] = value
            with self.assertRaises(ValidationError):
                build_analysis(self.task, self.plan, self.predictions, cohort_declarations=bad)

    def test_synthetic_configuration_cannot_enter_real_cost_comparison_via_route(self):
        experiment = deepcopy(self.plan["experiment"])
        experiment["configs"][0]["settings"] = {"adapter": "synthetic"}
        items = [item for request in self.plan["requests"][:2] for item in request["items"]]
        plan = build_plan(self.task, experiment, {"records": items})
        ops = [{"request_id": r["request_id"], "cost_currency": "USD", "observed_cost_micro_usd": 10,
                "route": "opaque-fixture"} for r in plan["requests"]]
        result = build_analysis(self.task, plan, {"records": []}, operations=ops)
        self.assertIsNone(by_run(result)["cost"]["observed_cost_micro_usd"])
        self.assertEqual(by_run(result)["cost"]["synthetic_excluded_requests"], 2)

    def _pair(self, result):
        a, b = by_run(result, prompt="SOP revision"), by_run(result, "model-two")
        return next(p for p in result["agreement_pairs"] if {p["run_a"], p["run_b"]} == {a["run_id"], b["run_id"]})


if __name__ == "__main__":
    unittest.main()
