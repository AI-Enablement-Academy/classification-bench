import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from classification_bench import ValidationError, build_plan, evaluate


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def fixture(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.task = fixture("task.json")
        self.experiment = fixture("experiment.json")
        self.inputs = fixture("inputs.json")
        self.labels = fixture("labels.json")
        self.predictions = fixture("predictions.json")

    def test_plan_is_label_isolated_and_stable(self):
        plan = build_plan(self.task, self.experiment, self.inputs)
        self.assertEqual(plan, build_plan(self.task, self.experiment, self.inputs))
        self.assertEqual(len(plan["requests"]), 6)
        self.assertNotIn("labels", json.dumps(plan["requests"]))
        self.assertEqual([[i["id"] for i in r["items"]] for r in plan["requests"][:2]],
                         [["toy-a", "toy-b"], ["toy-c"]])
        changed = copy.deepcopy(self.inputs)
        changed["records"][0]["input"]["description"] += "!"
        self.assertNotEqual(plan["requests"][0]["request_id"],
                            build_plan(self.task, self.experiment, changed)["requests"][0]["request_id"])
        altered = copy.deepcopy(self.experiment)
        altered["configs"][0]["settings"]["reasoning"] = "high"
        self.assertNotEqual(plan["requests"][0]["request_id"],
                            build_plan(self.task, altered, self.inputs)["requests"][0]["request_id"])
        self.assertEqual(len({r["request_id"] for r in plan["requests"]}), len(plan["requests"]))

    def test_model_type_is_optional_declared_metadata_bound_to_new_plans(self):
        original = build_plan(self.task, self.experiment, self.inputs)
        self.assertNotIn("model_type", original["experiment"]["configs"][0])
        for value in ("llm", "fine_tuned_llm", "decision"):
            changed = copy.deepcopy(self.experiment)
            changed["configs"][0]["model_type"] = value
            plan = build_plan(self.task, changed, self.inputs)
            self.assertEqual(plan["experiment"]["configs"][0]["model_type"], value)
            self.assertNotEqual(plan["requests"][0]["request_id"], original["requests"][0]["request_id"])
        self.assertEqual(original, build_plan(self.task, self.experiment, self.inputs))
        for value in ("unknown", "native_decision", "", None, 1):
            changed = copy.deepcopy(self.experiment)
            changed["configs"][0]["model_type"] = value
            with self.assertRaisesRegex(ValidationError, "config.model_type"):
                build_plan(self.task, changed, self.inputs)

    def test_duplicate_ids_and_unknown_input_fields(self):
        bad = copy.deepcopy(self.inputs)
        bad["records"][1]["id"] = "toy-a"
        with self.assertRaises(ValidationError):
            build_plan(self.task, self.experiment, bad)
        bad = copy.deepcopy(self.inputs)
        bad["records"][0]["input"]["secret"] = "not for models"
        with self.assertRaises(ValidationError):
            build_plan(self.task, self.experiment, bad)
        bad = copy.deepcopy(self.inputs)
        bad["records"][0]["labels"] = {"segment": "teams"}
        with self.assertRaises(ValidationError):
            build_plan(self.task, self.experiment, bad)

    def test_invalid_and_missing_remain_in_denominator_and_flips_exclude_them(self):
        plan = build_plan(self.task, self.experiment, self.inputs)
        predictions = copy.deepcopy(self.predictions)
        predictions["records"] = [r for r in predictions["records"]
                                  if not (r["repeat"] == 3 and r["id"] == "toy-c")]
        result = evaluate(self.task, plan, self.labels, predictions)
        self.assertEqual(result["positions"], 9)
        self.assertEqual(result["missing"], 1)
        self.assertEqual(len(result["invalid"]), 1)
        condition = result["conditions"][0]
        self.assertEqual([p["denominator"] for p in condition["passes"]], [3, 3, 3])
        self.assertEqual([p["all_field_exact"] for p in condition["passes"]], [3, 2, 1])
        self.assertEqual(condition["pass_score_range"], [1 / 3, 1.0])
        self.assertEqual(condition["repeat_comparisons"][0]["flips"], 1)
        self.assertEqual(condition["repeat_comparisons"][0]["fields"]["segment"]["changed_ids"], ["toy-b"])
        self.assertEqual(condition["repeat_comparisons"][0]["fields"]["urgency"]["flip_rate"], 0.0)
        self.assertEqual(condition["repeat_comparisons"][1]["comparable"], 1)
        self.assertEqual(condition["repeat_comparisons"][1]["excluded"], 2)
        self.assertEqual(condition["repeat_comparisons"][1]["excluded_ids"], ["toy-b", "toy-c"])
        self.assertEqual(set(result["source_hashes"]), {"task", "plan", "labels", "predictions"})
        self.assertTrue(all(len(value) == 64 for value in result["source_hashes"].values()))
        urgency = condition["passes"][2]["fields"]["urgency"]
        self.assertEqual(urgency["labels"]["later"]["fn"], 2)

    def test_rejects_extra_prediction_fields_and_bad_reference_labels(self):
        plan = build_plan(self.task, self.experiment, self.inputs)
        bad = copy.deepcopy(self.predictions)
        bad["records"][0]["prediction"]["extra"] = "x"
        result = evaluate(self.task, plan, self.labels, bad)
        self.assertEqual(len(result["invalid"]), 2)
        bad_labels = copy.deepcopy(self.labels)
        bad_labels["records"][0]["labels"]["urgency"] = "unknown"
        with self.assertRaises(ValidationError):
            evaluate(self.task, plan, bad_labels, self.predictions)

    def test_duplicate_prediction_position_is_rejected(self):
        plan = build_plan(self.task, self.experiment, self.inputs)
        bad = copy.deepcopy(self.predictions)
        bad["records"].append(copy.deepcopy(bad["records"][0]))
        with self.assertRaises(ValidationError):
            evaluate(self.task, plan, self.labels, bad)

    def test_noncanonical_plan_is_rejected_before_scoring(self):
        plan = build_plan(self.task, self.experiment, self.inputs)
        variants = []
        removed = copy.deepcopy(plan)
        del removed["requests"][1]
        variants.append(removed)
        changed = copy.deepcopy(plan)
        changed["requests"][0]["items"][0]["input"]["description"] = "edited"
        variants.append(changed)
        stale_hash = copy.deepcopy(plan)
        stale_hash["requests"][0]["request_id"] = "0" * 64
        variants.append(stale_hash)
        for bad in variants:
            with self.subTest(bad=bad["requests"][0]["request_id"]):
                with self.assertRaises(ValidationError):
                    evaluate(self.task, bad, self.labels, self.predictions)

    def test_zero_comparable_repeats_have_null_flip_rate(self):
        plan = build_plan(self.task, self.experiment, self.inputs)
        result = evaluate(self.task, plan, self.labels, {"records": []})
        comparison = result["conditions"][0]["repeat_comparisons"][0]
        self.assertEqual(comparison["excluded_ids"], ["toy-a", "toy-b", "toy-c"])
        self.assertIsNone(comparison["flip_rate"])
        self.assertIsNone(comparison["fields"]["segment"]["flip_rate"])

    def test_cli_output_never_overwrites_existing_sources_or_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = {}
            for name in ("task", "experiment", "inputs", "labels", "predictions"):
                path = root / f"{name}.json"
                path.write_bytes((EXAMPLES / f"{name}.json").read_bytes())
                paths[name] = path
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(build_plan(self.task, self.experiment, self.inputs)),
                                 encoding="utf-8")
            paths["plan"] = plan_path
            result_path = root / "result.json"
            result_path.write_text('{"existing": true}\n', encoding="utf-8")
            paths["result"] = result_path
            common = [sys.executable, "-m", "classification_bench"]
            plan = common + ["plan", "--task", str(paths["task"]), "--experiment",
                             str(paths["experiment"]), "--inputs", str(paths["inputs"])]
            score = common + ["evaluate", "--task", str(paths["task"]), "--plan",
                              str(paths["plan"]), "--labels", str(paths["labels"]),
                              "--predictions", str(paths["predictions"])]
            for command, targets in ((plan, ("task", "plan", "result")),
                                     (score, ("task", "plan", "labels", "result"))):
                for target in targets:
                    with self.subTest(command=command[3], target=target):
                        before = paths[target].read_bytes()
                        completed = subprocess.run(command + ["--out", str(paths[target])],
                                                   cwd=EXAMPLES.parent, capture_output=True, text=True)
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertEqual(paths[target].read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
