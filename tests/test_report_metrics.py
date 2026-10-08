"""Hand-calculated categorical metrics, coverage and accessible report tables."""

import copy
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from classification_bench.core import ValidationError, build_plan, evaluate
from classification_bench.report import generate_report
from classification_bench.report_analysis import build_analysis
from classification_bench.report_metrics import build_field_metrics, render_field_metrics
from tests.test_report_ux import Tree, normalized, table_rows


class ReportMetricsTests(unittest.TestCase):
    def setUp(self):
        self.task = {"name": "Generic categorical fixture", "input_keys": ["content"],
                     "fields": [{"name": "decision", "labels": ["major", "rare", "unused"]},
                                {"name": "tone", "labels": ["plain", "verbose", "never"]}]}
        self.experiment = {"configs": [{"id": "fixture", "model": "offline"}],
                           "prompts": [{"id": "base", "text": "Use the supplied rubric."}],
                           "repeats": 1, "batch_size": 2}
        self.inputs = {"records": [{"id": name, "input": {"content": "Source " + name}}
                                   for name in "abcdefgh"]}
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        self.labels = {"records": [
            {"id": "a", "labels": {"decision": "major", "tone": "plain"}},
            {"id": "b", "labels": {"decision": "major"}},
            {"id": "c", "labels": {"decision": "major", "tone": None}},
            {"id": "d", "labels": {"decision": "major"}},
            {"id": "e", "labels": {"decision": "major"}},
            {"id": "f", "labels": {"decision": "rare", "tone": "verbose"}},
            {"id": "g", "labels": {"decision": "rare"}},
            {"id": "h", "labels": {"tone": "verbose"}}]}
        vectors = {"a": {"decision": "major", "tone": "plain"},
                   "b": {"decision": "major", "tone": "plain"},
                   "c": {"decision": "rare", "tone": "plain"},
                   "d": {"decision": "major", "tone": "invalid"},
                   "f": {"decision": "major", "tone": "plain"},
                   "g": {"decision": "rare", "tone": "plain"},
                   "h": {"decision": "major", "tone": "plain"}}
        self.predictions = {"records": [{"config_id": "fixture", "prompt_id": "base", "repeat": 1,
                                          "id": name, "prediction": vector} for name, vector in vectors.items()]}

    def analysis(self, labels="partial"):
        return build_analysis(self.task, self.plan, self.predictions,
                              self.labels if labels == "partial" else labels)

    def metrics(self, labels="partial"):
        return next(iter(build_field_metrics(self.analysis(labels))["runs"].values()))

    def test_imbalanced_counts_precision_recall_f1_and_full_denominator(self):
        run = self.metrics()
        decision, tone = run["fields"]
        self.assertEqual(run["planned"], 8)
        self.assertEqual(decision["outcomes"], {"valid": 6, "invalid": 1, "missing": 1})
        self.assertEqual(decision["known_reference_outcomes"], {"valid": 5, "invalid": 1, "missing": 1})
        self.assertEqual((decision["known_reference_count"], decision["unknown_reference_count"]), (7, 1))
        self.assertEqual(decision["agreement"], {"numerator": 3, "denominator": 7, "value": 3 / 7})
        major, rare = decision["per_label"]["major"], decision["per_label"]["rare"]
        self.assertEqual((major["support"], major["tp"], major["fp"], major["fn"], major["predicted_positive"]), (5, 2, 1, 3, 3))
        self.assertEqual(major["precision"], {"numerator": 2, "denominator": 3, "value": 2 / 3})
        self.assertEqual(major["recall"], {"numerator": 2, "denominator": 5, "value": 2 / 5})
        self.assertEqual(major["f1"], {"numerator": 4, "denominator": 8, "value": .5})
        self.assertEqual((rare["support"], rare["tp"], rare["fp"], rare["fn"]), (2, 1, 1, 1))
        self.assertEqual([rare[key]["value"] for key in ("precision", "recall", "f1")], [.5, .5, .5])
        self.assertEqual(major["fn_ids"], ["c", "d", "e"])
        self.assertEqual(major["fp_ids"], ["f"])
        self.assertEqual(decision["unknown_reference_ids"], ["h"])
        self.assertEqual(tone["known_reference_count"], 3)
        self.assertEqual(tone["agreement"]["value"], 1 / 3)

    def test_complete_confusion_rows_reconcile_support_including_unusable(self):
        decision = self.metrics()["fields"][0]
        self.assertEqual(decision["confusion"], {"major": {"major": 2, "rare": 1, "unused": 0},
                                                "rare": {"major": 1, "rare": 1, "unused": 0},
                                                "unused": {"major": 0, "rare": 0, "unused": 0}})
        self.assertEqual(decision["unscored_by_true_label"], {"major": 2, "rare": 0, "unused": 0})
        self.assertEqual(decision["unscored_ids"]["major"], ["d", "e"])
        self.assertEqual(decision["confusion_ids"]["major"]["rare"], ["c"])
        for label in decision["labels"]:
            self.assertEqual(sum(decision["confusion"][label].values()) + decision["unscored_by_true_label"][label],
                             decision["per_label"][label]["support"])

    def test_zero_prediction_precision_and_zero_reference_recall_are_unavailable(self):
        decision, tone = self.metrics()["fields"]
        unused = decision["per_label"]["unused"]
        self.assertEqual((unused["support"], unused["predicted_positive"]), (0, 0))
        self.assertTrue(all(unused[key]["value"] is None for key in ("precision", "recall", "f1")))
        verbose = tone["per_label"]["verbose"]
        self.assertIsNone(verbose["precision"]["value"])
        self.assertEqual(verbose["recall"], {"numerator": 0, "denominator": 2, "value": 0})
        self.assertEqual(verbose["f1"], {"numerator": 0, "denominator": 2, "value": 0})
        corrected = copy.deepcopy(self.labels)
        corrected["records"][0]["labels"]["decision"] = "rare"
        corrected["records"] = [row for row in corrected["records"] if row["id"] not in "bcdefg"]
        major = self.metrics(corrected)["fields"][0]["per_label"]["major"]
        self.assertEqual(major["precision"]["value"], 0)
        self.assertIsNone(major["recall"]["value"])
        self.assertEqual(major["f1"]["value"], 0)

    def test_unlabeled_counts_and_confusion_are_unavailable_without_fake_support(self):
        run = self.metrics(None)
        for field in run["fields"]:
            self.assertEqual(field["reference_coverage"], {"numerator": 0, "denominator": 8, "value": 0})
            self.assertEqual(field["unknown_reference_ids"], list("abcdefgh"))
            self.assertIsNone(field["confusion"])
            self.assertIsNone(field["unscored_by_true_label"])
            self.assertIsNone(field["agreement"]["value"])
            self.assertIsNone(field["legacy_macro_f1"])
            for values in field["per_label"].values():
                self.assertTrue(all(values[key] is None for key in ("support", "tp", "fp", "fn", "predicted_positive")))
                self.assertTrue(all(values[key]["value"] is None for key in ("precision", "recall", "f1")))
        html = render_field_metrics(run, id_prefix="unlabeled")
        self.assertIn("unavailable (no known references)", html)
        self.assertIn("Confusion matrix unavailable: no known references for this field", html)

    def test_legacy_macro_convention_matches_unchanged_evaluator(self):
        fields = self.metrics()["fields"]
        evaluated = evaluate(self.task, self.plan, self.labels, self.predictions, allow_partial_references=True)
        for field in fields:
            legacy = evaluated["conditions"][0]["passes"][0]["fields"][field["name"]]
            self.assertEqual(field["legacy_macro_f1"], legacy["macro_f1"])
            self.assertEqual(field["confusion"], legacy["confusion"])
        self.assertAlmostEqual(fields[0]["legacy_macro_f1"], 1 / 3)
        html = render_field_metrics(self.metrics(), id_prefix="metrics")
        self.assertIn("Legacy evaluator macro F1: 0.333", html)
        self.assertIn("That existing convention is separate from the unavailable label ratios shown here", html)

    def test_many_runs_preserve_each_pass_and_do_not_pool_repeat_cases(self):
        self.experiment["prompts"].append({"id": "other", "text": "Another prompt."})
        self.experiment["repeats"] = 2
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        analysis = self.analysis()
        metrics = build_field_metrics(analysis)
        self.assertEqual(len(metrics["runs"]), 4)
        self.assertTrue(all(run["planned"] == 8 for run in metrics["runs"].values()))
        unanswered = [run for run in metrics["runs"].values() if (run["prompt_id"], run["repeat"]) != ("base", 1)]
        for run in unanswered:
            field = run["fields"][0]
            self.assertEqual(field["outcomes"], {"valid": 0, "invalid": 0, "missing": 8})
            self.assertEqual(field["per_label"]["major"]["fn"], 5)
            self.assertIsNone(field["per_label"]["major"]["precision"]["value"])

    def test_projection_is_deterministic_and_does_not_alias_source(self):
        analysis = self.analysis()
        original = copy.deepcopy(analysis)
        metrics = build_field_metrics(analysis)
        self.assertEqual(metrics, build_field_metrics(analysis))
        json.dumps(metrics, allow_nan=False)
        metrics["source_hashes"]["task"] = "edited"
        next(iter(metrics["runs"].values()))["fields"][0]["per_label"]["major"]["fn_ids"].append("edited")
        self.assertEqual(analysis, original)

    def test_malformed_case_projections_are_rejected_without_coercion(self):
        for change in (lambda run: run["cases"].append(copy.deepcopy(run["cases"][0])),
                       lambda run: run["cases"][0].update(prediction_status="refused"),
                       lambda run: run["cases"][0].update(prediction={"decision": "wrong", "tone": "plain"}),
                       lambda run: run["cases"][0].update(reference={"decision": "unknown"}),
                       lambda run: run["cases"][0].update(reference={"decision": None}),
                       lambda run: run["cases"][3].update(prediction={"decision": "major", "tone": "plain"})):
            analysis = self.analysis()
            change(analysis["runs"][0])
            with self.assertRaises(ValidationError):
                build_field_metrics(analysis)

    def test_semantic_tables_cover_all_labels_counts_and_exact_case_links(self):
        run = self.metrics()
        page = Tree(render_field_metrics(run, id_prefix="condition-0-pass-1-metrics")).root
        tables = list(page.descendants("table"))
        self.assertEqual(len(tables), 4)
        self.assertEqual(table_rows(tables[0])[0], ["Label", "Reference support", "Predicted positives", "TP", "FP", "FN", "Precision", "Recall", "F1"])
        self.assertEqual(table_rows(tables[0])[1][1:6], ["5", "3", "2", "1", "3"])
        self.assertEqual(table_rows(tables[0])[1][6:], ["2/3 (66.7%)", "2/5 (40.0%)", "4/8 (50.0%)"])
        self.assertEqual(table_rows(tables[1])[0], ["Reference / prediction", "major", "rare", "unused", "No valid prediction (invalid or missing)"])
        self.assertEqual(table_rows(tables[1])[1], ["major", "2", "1", "0", "2"])
        for table in tables:
            self.assertEqual(len(list(table.descendants("caption"))), 1)
            self.assertTrue(all(node.attrs.get("scope") in ("col", "row") for node in table.descendants("th")))
        wrappers = [node for node in page.descendants("div") if node.attrs.get("class") == "metric-scroll"]
        self.assertTrue(all(node.attrs.get("tabindex") == "0" and node.attrs.get("role") == "region" for node in wrappers))
        for link in page.descendants("a"):
            fragment = urlsplit(link.attrs["href"]).fragment
            parameters = parse_qs(fragment.split("?", 1)[1])
            self.assertEqual(parameters["run"], [run["run_id"]])
            self.assertIn(parameters["case"][0], list("abcdefgh"))
        self.assertIn("@media(max-width:600px)", render_field_metrics(run, id_prefix="responsive"))

    def test_arbitrary_html_field_labels_and_ids_are_inert(self):
        attack = "</th><script>alert('private')</script>&\""
        self.task["fields"][0]["name"] = attack
        self.task["fields"][0]["labels"][0] = attack
        for row in self.labels["records"]:
            if "decision" in row["labels"]:
                value = row["labels"].pop("decision")
                row["labels"][attack] = attack if value == "major" else value
        for row in self.predictions["records"]:
            value = row["prediction"].pop("decision")
            row["prediction"][attack] = attack if value == "major" else value
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        html = render_field_metrics(self.metrics(), id_prefix=attack)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;alert", html)
        page = Tree(html).root
        self.assertFalse(list(page.descendants("script")))
        self.assertIn(attack, normalized(page))

    def test_integrated_report_builds_analysis_and_metrics_once_for_all_fields(self):
        with patch("classification_bench.report.build_analysis", wraps=build_analysis) as analysis_builder, \
                patch("classification_bench.report.build_field_metrics", wraps=build_field_metrics) as metrics_builder:
            html = generate_report(self.task, self.plan, self.labels, self.predictions,
                                   allow_partial_references=True)
        self.assertEqual(analysis_builder.call_count, 1)
        self.assertEqual(metrics_builder.call_count, 1)
        self.assertIn("Per-label metrics and full confusion", html)
        self.assertIn("7 known references / 8 planned cases", html)
        self.assertIn("3 known references / 8 planned cases", html)
        self.assertIn("unavailable (no predicted positives)", html)
        ids = [node.attrs["id"] for node in Tree(html).root.descendants() if "id" in node.attrs]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
