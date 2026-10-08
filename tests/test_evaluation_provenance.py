"""Scoring identity is explicit without mutating historical metric evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from classification_bench import workflow, workflow_execution
from classification_bench.core import _digest, build_plan, evaluate
from classification_bench.evaluation_provenance import (
    EvaluationProvenanceError, current_provenance, evaluation_identity, validate_provenance,
)
from classification_bench.manifest import canonical_bytes
from classification_bench.report_analysis import build_analysis


ROOT = Path(__file__).resolve().parents[1]


def rehash_provenance(value):
    value["implementation_sha256"] = _digest(value["source_sha256"])
    value["provenance_sha256"] = _digest({key: item for key, item in value.items() if key != "provenance_sha256"})
    return value


class EvaluationProvenanceTests(unittest.TestCase):
    def setUp(self):
        read = lambda name: json.loads((ROOT / "examples" / name).read_bytes())
        self.task = read("task.json")
        self.plan = build_plan(self.task, read("experiment.json"), read("inputs.json"))
        self.labels = read("labels.json")
        self.predictions = read("predictions.json")

    def test_new_evaluation_has_current_provenance_and_stable_source_scope(self):
        result = evaluate(self.task, self.plan, self.labels, self.predictions)
        self.assertEqual(result["evaluation_provenance"], current_provenance())
        self.assertEqual(set(result["source_hashes"]), {"task", "plan", "labels", "predictions"})
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["evaluation_id"], evaluation_identity(result["source_hashes"], current_provenance()))
        self.assertEqual(result, evaluate(self.task, self.plan, self.labels, self.predictions))
        for name, expected in result["evaluation_provenance"]["source_sha256"].items():
            self.assertEqual(expected, hashlib.sha256((ROOT / name).read_bytes()).hexdigest())
        detached = validate_provenance(result["evaluation_provenance"])
        detached["source_sha256"].clear()
        self.assertTrue(result["evaluation_provenance"]["source_sha256"])

    def test_algorithm_and_source_changes_produce_distinct_evaluation_identities(self):
        original = evaluate(self.task, self.plan, self.labels, self.predictions)
        for mutation in ("algorithm", "source"):
            changed = deepcopy(original["evaluation_provenance"])
            if mutation == "algorithm":
                changed["algorithm_version"] += 1
            else:
                changed["source_sha256"]["classification_bench/core.py"] = "a" * 64
            rehash_provenance(changed)
            self.assertNotEqual(evaluation_identity(original["source_hashes"], changed), original["evaluation_id"])
            self.assertEqual(validate_provenance(changed), changed)
            with self.assertRaisesRegex(EvaluationProvenanceError, "frozen evaluator differs"):
                validate_provenance(changed, require_current=True)

    def test_strict_provenance_rejects_scope_hash_version_and_unknown_fields(self):
        original = current_provenance()
        for name, value in (("schema_version", True), ("algorithm_version", True),
                            ("algorithm_version", 0), ("scope", "invented"),
                            ("algorithm", "invented"), ("implementation_sha256", "a" * 64),
                            ("provenance_sha256", "a" * 64), ("source_sha256", {})):
            with self.subTest(name=name, value=value):
                changed = deepcopy(original)
                changed[name] = value
                with self.assertRaises(EvaluationProvenanceError):
                    validate_provenance(changed)
        changed = deepcopy(original)
        changed["unexpected"] = "not allowed"
        with self.assertRaises(EvaluationProvenanceError):
            validate_provenance(changed)
        with self.assertRaises(EvaluationProvenanceError):
            validate_provenance(original, scope="categorical_case_analysis")
        with self.assertRaises(EvaluationProvenanceError):
            validate_provenance(original, require_current=1)

    def test_partial_and_unlabeled_scoring_bind_absent_reference_without_inventing_accuracy(self):
        for labels, partial in ((None, False), ({"records": [self.labels["records"][0]]}, True)):
            result = evaluate(self.task, self.plan, labels, self.predictions, allow_partial_references=partial)
            self.assertEqual(result["schema_version"], 2)
            self.assertEqual(result["evaluation_id"], evaluation_identity(result["source_hashes"], current_provenance()))
            self.assertEqual(result["source_hashes"]["labels"], _digest(labels) if labels is not None else None)
            self.assertTrue(all(condition["pass_score_mean"] is None for condition in result["conditions"]))
        changed_labels = deepcopy(self.labels)
        field = self.task["fields"][0]
        record = changed_labels["records"][0]
        record["labels"][field["name"]] = next(label for label in field["labels"] if label != record["labels"][field["name"]])
        before = evaluate(self.task, self.plan, self.labels, self.predictions)
        after = evaluate(self.task, self.plan, changed_labels, self.predictions)
        self.assertNotEqual(before["evaluation_id"], after["evaluation_id"])
        self.assertEqual(before["evaluation_provenance"], after["evaluation_provenance"])

    def test_new_analysis_binds_evaluator_and_case_analysis_implementation(self):
        analysis = build_analysis(self.task, self.plan, self.predictions, self.labels)
        self.assertEqual(analysis["evaluation_provenance"], current_provenance())
        self.assertEqual(analysis["analysis_provenance"], current_provenance(scope="categorical_case_analysis"))
        self.assertEqual(analysis["evaluation_id"], evaluate(self.task, self.plan, self.labels, self.predictions)["evaluation_id"])
        original_runs = [run["run_id"] for run in analysis["runs"]]
        provenance = current_provenance(scope="categorical_case_analysis")
        provenance["algorithm_version"] += 1
        rehash_provenance(provenance)
        actual_current = current_provenance
        with patch("classification_bench.report_analysis.current_provenance",
                   side_effect=lambda **kwargs: deepcopy(provenance) if kwargs.get("scope") == "categorical_case_analysis" else actual_current()):
            changed = build_analysis(self.task, self.plan, self.predictions, self.labels)
        self.assertNotEqual(analysis["analysis_id"], changed["analysis_id"])
        self.assertEqual(original_runs, [run["run_id"] for run in changed["runs"]])
        self.assertEqual(analysis["source_hashes"], changed["source_hashes"])
        self.assertEqual(analysis["evaluation_id"], changed["evaluation_id"])


class WorkflowEvaluationProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="evaluation-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.directory = self.root / "frozen"
        self.path = self.directory / "workflow.json"
        spec = json.loads((ROOT / "examples/product/workflow.json").read_bytes())
        for name in ("task", "experiment", "inputs"):
            spec[name] = str(ROOT / "examples/product" / (name + ".json"))
        source = self.root / "workflow-spec.json"
        source.write_bytes(canonical_bytes(spec))
        self.manifest = workflow.prepare(source, self.directory)

    def rewrite_manifest(self, manifest):
        manifest["workflow_sha256"] = _digest({key: value for key, value in manifest.items() if key != "workflow_sha256"})
        self.path.write_bytes(canonical_bytes(manifest))

    def test_new_workflow_freezes_evaluator_and_legacy_workflow_remains_readable(self):
        self.assertEqual(self.manifest["schema_version"], 2)
        self.assertEqual(self.manifest["evaluation_provenance"], current_provenance())
        self.assertEqual(workflow.load(self.path, require_current_evaluation=True), self.manifest)
        legacy = deepcopy(self.manifest)
        legacy["schema_version"] = 1
        legacy.pop("evaluation_provenance")
        self.rewrite_manifest(legacy)
        self.assertEqual(workflow.load(self.path), legacy)
        snapshot = workflow_execution.report_snapshot(self.path, phase="full")
        self.assertNotIn("evaluation_provenance", snapshot["manifest"])
        scored = evaluate(snapshot["phases"]["full"]["task"], snapshot["phases"]["full"]["plan"],
                          predictions=snapshot["phases"]["full"]["predictions"])
        self.assertEqual(scored["evaluation_provenance"], current_provenance())

    def test_drift_blocks_new_workflow_scoring_but_not_read_export_recovery_or_inference(self):
        changed = current_provenance()
        changed["algorithm_version"] += 1
        rehash_provenance(changed)
        with patch("classification_bench.evaluation_provenance.current_provenance", return_value=changed):
            self.assertEqual(workflow.load(self.path), self.manifest)
            with self.assertRaisesRegex(workflow.WorkflowError, "frozen evaluator differs"):
                workflow.load(self.path, require_current_evaluation=True)
            with self.assertRaisesRegex(workflow.WorkflowError, "frozen evaluator differs"):
                workflow_execution.report_snapshot(self.path)
            self.assertEqual(workflow_execution.export_predictions(self.path, phase="full"), {"records": []})
            workflow_execution.status(self.path)
            # Synthetic dispatch tests the separation from the offline scorer.
            result = workflow_execution.run(self.path, phase="smoke")
            self.assertEqual(result["phases"]["smoke"]["runs"][0]["status"], "completed")
            workflow_execution.recover(self.path, phase="full")

    def test_rehashed_malformed_provenance_and_incorrect_flags_are_rejected(self):
        changed = deepcopy(self.manifest)
        changed["evaluation_provenance"]["algorithm_version"] = True
        rehash_provenance(changed["evaluation_provenance"])
        self.rewrite_manifest(changed)
        with self.assertRaisesRegex(workflow.WorkflowError, "positive algorithm version"):
            workflow.load(self.path)
        with self.assertRaisesRegex(workflow.WorkflowError, "expected boolean"):
            workflow.load(self.path, require_current_evaluation=1)
