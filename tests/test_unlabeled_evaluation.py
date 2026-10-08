"""Reference coverage is separate from output validity and planned membership."""

import copy
import json
from pathlib import Path
import unittest

from classification_bench.core import (
    ValidationError, _digest, build_plan, evaluate, validate_reference_labels, validated_positions,
)


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class OptionalReferenceEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.task = {"name": "support-routing", "input_keys": ["message"], "fields": [
            {"name": "queue", "labels": ["billing", "access"]},
            {"name": "priority", "labels": ["standard", "urgent"]},
            {"name": "needs_review", "labels": ["yes", "no"]},
        ]}
        self.experiment = {"configs": [{"id": "one", "model": "offline"}],
                           "prompts": [{"id": "direct", "text": "Use supplied evidence."}],
                           "repeats": 2, "batch_size": 2}
        self.inputs = {"records": [{"id": rid, "input": {"message": rid}} for rid in ("a", "b", "c", "d")]}
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        self.full = {"records": [{"id": rid, "labels": {
            "queue": "billing", "priority": "standard", "needs_review": "no"}}
                                for rid in ("a", "b", "c", "d")]}
        self.predictions = {"records": []}
        for repeat in (1, 2):
            for rid in ("a", "b", "c", "d"):
                value = {"queue": "billing", "priority": "standard", "needs_review": "no"}
                if repeat == 1 and rid == "b":
                    value["queue"] = "access"
                if repeat == 1 and rid == "c":
                    value["priority"] = "NOT_ALLOWED"
                if repeat == 1 and rid == "d":
                    continue
                self.predictions["records"].append({"config_id": "one", "prompt_id": "direct",
                                                    "repeat": repeat, "id": rid, "prediction": value})

    def run_eval(self, labels=None, **kwargs):
        return evaluate(self.task, self.plan, labels, self.predictions, **kwargs)

    def test_complete_reference_metric_payload_keeps_prechange_canonical_bytes(self):
        read = lambda name: json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
        task = read("task.json")
        plan = build_plan(task, read("experiment.json"), read("inputs.json"))
        for predictions, digest in ((read("predictions.json"),
                                     "e6968b88a713535aa21f1e766c1380c9f57d99d016a871f625f06cac91188254"),
                                    ({"records": []},
                                     "4a50acf9ef97ef2790139950974a9d45304e2f4d28a32183161d991e684b81a6")):
            with self.subTest(digest=digest):
                result = evaluate(task, plan, read("labels.json"), predictions)
                metrics = {key: value for key, value in result.items()
                           if key not in ("evaluation_id", "evaluation_provenance")}
                self.assertEqual(_digest(metrics), digest)
                self.assertIn("evaluation_provenance", result)
                self.assertIn("evaluation_id", result)
                self.assertEqual(result["schema_version"], 1)
                self.assertNotIn("reference_coverage", result)
                opted_in = evaluate(task, plan, read("labels.json"), predictions,
                                    allow_partial_references=True)
                self.assertEqual(opted_in, result)

    def test_unlabeled_predictions_keep_full_denominator_and_have_no_accuracy(self):
        result = self.run_eval()
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["positions"], 8)
        self.assertEqual(result["missing"], 1)
        self.assertEqual(len(result["invalid"]), 1)
        self.assertIsNone(result["source_hashes"]["labels"])
        coverage = result["reference_coverage"]
        self.assertEqual(coverage["status"], "unlabeled")
        self.assertEqual(coverage["input_count"], 4)
        self.assertEqual(coverage["known_field_labels"], 0)
        self.assertEqual(coverage["expected_field_labels"], 12)
        self.assertEqual(coverage["unlabeled_ids"], ["a", "b", "c", "d"])
        condition = result["conditions"][0]
        self.assertIsNone(condition["pass_score_mean"])
        self.assertIsNone(condition["pass_score_range"])
        self.assertIsNone(condition["scored_subset_score_mean"])
        self.assertIsNone(condition["scored_subset_score_range"])
        for entry in condition["passes"]:
            self.assertEqual(entry["denominator"], 4)
            self.assertEqual(entry["valid"] + entry["invalid"] + entry["missing"], 4)
            self.assertIsNone(entry["all_field_exact"])
            self.assertIsNone(entry["all_field_exact_rate"])
            self.assertEqual(entry["scored_subset"]["denominator"], 0)
            self.assertIsNone(entry["scored_subset"]["all_field_exact_rate"])
            for stats in entry["fields"].values():
                self.assertEqual(stats["reference_denominator"], 0)
                self.assertEqual(stats["reference_missing"], 4)
                for metric in ("accuracy", "correct", "confusion", "labels", "macro_f1"):
                    self.assertIsNone(stats[metric])
        self.assertEqual(condition["passes"][0]["valid_rate"], 0.5)

    def test_missing_predictions_argument_is_rejected_instead_of_fabricating_missing_evidence(self):
        with self.assertRaises(ValidationError):
            evaluate(self.task, self.plan)
        self.assertEqual(evaluate(self.task, self.plan, predictions=self.predictions), self.run_eval())

    def test_partial_references_require_explicit_boolean_opt_in(self):
        partial = {"records": [{"id": "a", "labels": {"queue": "billing"}}]}
        with self.assertRaises(ValidationError):
            self.run_eval(partial)
        for value in (1, "true", None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.run_eval(partial, allow_partial_references=value)
        self.assertEqual(self.run_eval(partial, allow_partial_references=True)["schema_version"], 2)

    def test_varying_per_field_coverage_scores_only_known_references(self):
        partial = {"records": [self.full["records"][0],
                               {"id": "b", "labels": {"queue": "billing", "priority": None}},
                               {"id": "c", "labels": {"priority": "urgent"}}]}
        result = self.run_eval(partial, allow_partial_references=True)
        coverage = result["reference_coverage"]
        self.assertEqual(coverage["fully_labeled_ids"], ["a"])
        self.assertEqual(coverage["partially_labeled_ids"], ["b", "c"])
        self.assertEqual(coverage["unlabeled_ids"], ["d"])
        self.assertEqual(coverage["known_field_labels"], 5)
        self.assertEqual(coverage["fields"]["queue"]["known_ids"], ["a", "b"])
        self.assertEqual(coverage["fields"]["priority"]["known_ids"], ["a", "c"])
        self.assertEqual(coverage["fields"]["needs_review"]["known_ids"], ["a"])
        first = result["conditions"][0]["passes"][0]
        self.assertEqual(first["denominator"], 4)
        self.assertIsNone(first["all_field_exact_rate"])
        self.assertEqual(first["scored_subset"], {"scope": "fully_labeled_records", "ids": ["a"],
                                                  "denominator": 1, "all_field_exact": 1,
                                                  "all_field_exact_rate": 1.0})
        queue = first["fields"]["queue"]
        self.assertEqual(queue["reference_denominator"], 2)
        self.assertEqual(queue["reference_missing"], 2)
        self.assertEqual(queue["reference_coverage"], 0.5)
        self.assertEqual(queue["correct"], 1)
        self.assertEqual(queue["accuracy"], 0.5)
        self.assertEqual(queue["labels"]["billing"]["support"], 2)
        self.assertEqual(queue["labels"]["billing"]["fn"], 1)
        self.assertEqual(queue["confusion"]["billing"]["access"], 1)
        priority = first["fields"]["priority"]
        self.assertEqual(priority["accuracy"], 0.5)
        self.assertEqual(priority["unscored_by_true_label"], {"urgent": 1})
        self.assertEqual(priority["labels"]["urgent"]["fn"], 1)
        # b has a valid priority prediction but no priority reference: no FP/FN.
        self.assertEqual(priority["labels"]["standard"]["support"], 1)
        self.assertEqual(priority["labels"]["standard"]["fp"], 0)
        self.assertEqual(first["fields"]["needs_review"]["accuracy"], 1)
        self.assertEqual(result["conditions"][0]["scored_subset_score_range"], [1.0, 1.0])

    def test_no_full_vector_references_still_allow_known_field_metrics(self):
        partial = {"records": [{"id": "a", "labels": {"queue": "billing"}},
                               {"id": "b", "labels": {"priority": "standard"}}]}
        first = self.run_eval(partial, allow_partial_references=True)["conditions"][0]["passes"][0]
        self.assertEqual(first["scored_subset"]["denominator"], 0)
        self.assertIsNone(first["scored_subset"]["all_field_exact"])
        self.assertEqual(first["fields"]["queue"]["accuracy"], 1)
        self.assertEqual(first["fields"]["priority"]["accuracy"], 1)
        self.assertIsNone(first["fields"]["needs_review"]["labels"])

    def test_invalid_and_missing_referenced_outputs_remain_false_negatives_in_the_scored_subset(self):
        partial = {"records": [self.full["records"][2], self.full["records"][3]]}
        first = self.run_eval(partial, allow_partial_references=True)["conditions"][0]["passes"][0]
        self.assertEqual(first["scored_subset"]["denominator"], 2)
        self.assertEqual(first["scored_subset"]["all_field_exact"], 0)
        self.assertEqual(first["scored_subset"]["all_field_exact_rate"], 0)
        self.assertEqual(first["missing"], 1)
        self.assertEqual(first["invalid"], 1)
        for stats in first["fields"].values():
            self.assertEqual(stats["accuracy"], 0)
            self.assertEqual(sum(label["fn"] for label in stats["labels"].values()), 2)
            self.assertEqual(sum(label["support"] for label in stats["labels"].values()), 2)

    def test_repeat_comparisons_are_identical_for_complete_partial_and_absent_references(self):
        complete = self.run_eval(self.full)["conditions"][0]["repeat_comparisons"]
        partial = self.run_eval({"records": [{"id": "a", "labels": {"queue": "access"}}]},
                                allow_partial_references=True)["conditions"][0]["repeat_comparisons"]
        unlabeled = self.run_eval()["conditions"][0]["repeat_comparisons"]
        self.assertEqual(complete, partial)
        self.assertEqual(complete, unlabeled)
        self.assertEqual(unlabeled[0]["comparable"], 2)
        self.assertEqual(unlabeled[0]["excluded_ids"], ["c", "d"])
        self.assertEqual(unlabeled[0]["changed_ids"], ["b"])

    def test_empty_and_null_only_reference_documents_are_unlabeled_with_preserved_source_hash(self):
        for labels in ({"records": []}, {"records": [{"id": "a", "labels": {"queue": None}}]}):
            with self.subTest(labels=labels):
                result = self.run_eval(labels, allow_partial_references=True)
                self.assertEqual(result["reference_coverage"]["status"], "unlabeled")
                self.assertEqual(result["source_hashes"]["labels"], _digest(labels))
                self.assertIsNone(result["conditions"][0]["passes"][0]["all_field_exact_rate"])

    def test_partial_unknown_labels_duplicate_ids_unknown_ids_and_notes_are_rejected(self):
        bad = [{"records": [{"id": "a", "labels": {"queue": "other"}}]},
               {"records": [{"id": "a", "labels": {"queue": 12}}]},
               {"records": [{"id": "a", "labels": {"extra": "billing"}}]},
               {"records": [{"id": "a", "labels": {}}] * 2},
               {"records": [{"id": "not-in-inputs", "labels": {"queue": "billing"}}]},
               {"records": [{"id": "a", "labels": {}, "note": "private adjudication"}]}]
        for labels in bad:
            with self.subTest(labels=labels), self.assertRaises(ValidationError):
                self.run_eval(labels, allow_partial_references=True)

    def test_partial_and_unlabeled_predictions_keep_duplicate_and_unexpected_position_guards(self):
        for labels, options in ((None, {}), ({"records": []}, {"allow_partial_references": True})):
            for mutation in ("duplicate", "unknown"):
                predictions = copy.deepcopy(self.predictions)
                if mutation == "duplicate":
                    predictions["records"].append(predictions["records"][0])
                else:
                    predictions["records"][0]["id"] = "not-planned"
                with self.subTest(labels=labels, mutation=mutation), self.assertRaises(ValidationError):
                    evaluate(self.task, self.plan, labels, predictions, **options)

    def test_public_position_helper_has_full_membership_and_preserves_raw_invalid_evidence(self):
        positions = validated_positions(self.task, self.plan, self.predictions)
        self.assertEqual(positions["record_ids"], ["a", "b", "c", "d"])
        self.assertEqual(len(positions["positions"]), 8)
        self.assertEqual(len(positions["supplied"]), 7)
        self.assertEqual(len(positions["valid"]), 6)
        self.assertEqual(positions["invalid"], [("one", "direct", 1, "c")])
        self.assertEqual(positions["supplied"][("one", "direct", 1, "c")]["priority"], "NOT_ALLOWED")

    def test_public_reference_helper_returns_only_known_labels_without_mutating_source(self):
        labels = {"records": [{"id": "b", "labels": {"queue": "access", "priority": None}},
                               {"id": "a", "labels": {}}]}
        before = copy.deepcopy(labels)
        result = validate_reference_labels(labels, self.task, ["a", "b", "c", "d"], allow_partial=True)
        self.assertEqual(result, {"b": {"queue": "access"}, "a": {}})
        self.assertEqual(labels, before)
        self.assertEqual(validate_reference_labels(None, self.task, ["a", "b", "c", "d"]), {})

    def test_unlabeled_multi_configuration_matrix_keeps_all_planned_positions(self):
        experiment = copy.deepcopy(self.experiment)
        experiment["configs"].append({"id": "two", "model": "another-offline"})
        experiment["prompts"].append({"id": "careful", "text": "Check both fields."})
        plan = build_plan(self.task, experiment, self.inputs)
        result = evaluate(self.task, plan, predictions={"records": []})
        self.assertEqual(result["positions"], 32)
        self.assertEqual(result["missing"], 32)
        self.assertEqual(len(result["conditions"]), 4)
        self.assertEqual(result["reference_coverage"]["input_count"], 4)
        for condition in result["conditions"]:
            for entry in condition["passes"]:
                self.assertEqual(entry["denominator"], 4)
                self.assertEqual(entry["missing"], 4)
                self.assertEqual(entry["valid"], 0)
                self.assertIsNone(entry["all_field_exact_rate"])

    def test_task_defined_abstention_label_is_a_known_reference_not_an_unavailable_label(self):
        task = copy.deepcopy(self.task)
        task["fields"][0]["labels"].append("insufficient_evidence")
        plan = build_plan(task, self.experiment, self.inputs)
        predictions = copy.deepcopy(self.predictions)
        predictions["records"][0]["prediction"]["queue"] = "insufficient_evidence"
        reference = {"records": [{"id": "a", "labels": {"queue": "insufficient_evidence"}}]}
        result = evaluate(task, plan, reference, predictions, allow_partial_references=True)
        queue = result["conditions"][0]["passes"][0]["fields"]["queue"]
        self.assertEqual(queue["reference_denominator"], 1)
        self.assertEqual(queue["correct"], 1)
        self.assertEqual(queue["labels"]["insufficient_evidence"]["support"], 1)
        self.assertEqual(queue["confusion"]["insufficient_evidence"]["insufficient_evidence"], 1)

    def test_rehashed_or_truncated_plan_is_rejected_without_references(self):
        plan = copy.deepcopy(self.plan)
        plan["requests"].pop()
        with self.assertRaises(ValidationError):
            evaluate(self.task, plan, None, self.predictions)
        plan = copy.deepcopy(self.plan)
        plan["requests"][0]["request_id"] = "0" * 64
        with self.assertRaises(ValidationError):
            validated_positions(self.task, plan, self.predictions)


if __name__ == "__main__":
    unittest.main()
