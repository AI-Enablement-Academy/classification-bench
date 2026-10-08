"""Findings are reproducible, reference-aware and bound to exact evidence."""

import copy
import unittest
from urllib.parse import parse_qs

from classification_bench.core import build_plan
from classification_bench.report_analysis import build_analysis
from classification_bench.report_findings import build_findings, evidence_url, render_findings


class FindingsTests(unittest.TestCase):
    def setUp(self):
        self.task = {"name": "arbitrary support task", "input_keys": ["text"],
                     "fields": [{"name": "queue", "labels": ["a", "b"]}]}
        experiment = {"configs": [{"id": "one", "model": "fixture"}],
                      "prompts": [{"id": "short", "text": "Classify"}, {"id": "long", "text": "Use the rubric"}],
                      "batch_size": 2, "repeats": 2}
        self.inputs = {"records": [{"id": cid, "input": {"text": cid}} for cid in ("x", "y", "z")]}
        self.plan = build_plan(self.task, experiment, self.inputs)
        self.labels = {"records": [{"id": cid, "labels": {"queue": "a"}} for cid in ("x", "y", "z")]}
        self.predictions = {"records": []}
        for prompt in ("short", "long"):
            for repeat in (1, 2):
                for cid in ("x", "y", "z"):
                    if cid == "z":
                        continue
                    value = "b" if cid == "x" and prompt == "short" and repeat == 1 else "a"
                    if cid == "y" and prompt == "short":
                        value = "invalid"
                    self.predictions["records"].append({"config_id": "one", "prompt_id": prompt,
                        "repeat": repeat, "id": cid, "prediction": {"queue": value}})

    def analysis(self, labels=True):
        return build_analysis(self.task, self.plan, self.predictions, self.labels if labels is True else labels)

    def test_counts_keep_invalid_missing_and_exact_links(self):
        analysis = self.analysis()
        findings = build_findings(analysis)
        run = next(x for x in findings["findings"] if x["kind"] == "run_coverage")
        self.assertEqual(run["denominator"], 3)
        self.assertEqual(run["metrics"]["valid"], 1)
        self.assertEqual(run["metrics"]["invalid"], 1)
        self.assertEqual(run["metrics"]["missing"], 1)
        field = next(x for x in findings["findings"] if x["kind"] == "field_errors")
        self.assertEqual(field["metrics"]["confusion_patterns"], [
            {"reference": "a", "prediction": "b", "case_ids": ["x"], "count": 1}])
        self.assertEqual(field["metrics"]["unusable"], 2)
        self.assertEqual(set(field["case_ids"]), {"x", "y", "z"})
        for item in findings["findings"]:
            self.assertEqual(item["source_hashes"], analysis["source_hashes"])
            self.assertLessEqual(set(item["case_ids"]), set(analysis["case_ids"]))

    def test_paired_effect_and_repeats_are_not_pooled(self):
        findings = build_findings(self.analysis())["findings"]
        prompts = [x for x in findings if x["kind"] == "prompt_effect"]
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[0]["metrics"]["gains"], 2)
        self.assertEqual(prompts[0]["metrics"]["losses"], 0)
        repeats = [x for x in findings if x["kind"] == "repeat_consistency"]
        self.assertEqual(len(repeats), 2)
        self.assertEqual(repeats[0]["metrics"]["changed"], 1)
        self.assertEqual(repeats[0]["metrics"]["excluded"], 2)
        self.assertEqual(repeats[0]["denominator"], 3)

    def test_repeat_findings_reject_sources_from_another_evaluation(self):
        from classification_bench.report_repeats import build_repeat_analysis
        analysis = self.analysis()
        repeats = build_repeat_analysis(analysis)
        integrated = build_findings(analysis, repeats=repeats)
        self.assertEqual(sum(row["kind"] == "repeat_analysis_summary"
                             for row in integrated["findings"]), 2)
        changed = copy.deepcopy(repeats)
        changed["analysis_id"] = "different evaluation"
        with self.assertRaisesRegex(ValueError, "repeat findings must match"):
            build_findings(analysis, repeats=changed)
        changed = copy.deepcopy(repeats)
        changed["source_hashes"]["unexpected_source"] = "different source"
        with self.assertRaisesRegex(ValueError, "repeat findings must match"):
            build_findings(analysis, repeats=changed)

    def test_absent_and_partial_references_do_not_imply_whole_accuracy(self):
        unknown = build_findings(self.analysis(None))
        self.assertFalse(any(x["kind"] == "field_errors" for x in unknown["findings"]))
        for item in unknown["findings"]:
            if item["kind"] == "run_coverage":
                self.assertIn("Accuracy is unavailable", item["observation"])
            if item["kind"] == "prompt_effect":
                self.assertIsNone(item["metrics"]["net_gain"])
        partial = {"records": [self.labels["records"][0]]}
        finding = next(x for x in build_findings(self.analysis(partial))["findings"] if x["kind"] == "run_coverage")
        self.assertIn("Whole-run accuracy is unavailable", finding["observation"])
        self.assertEqual(finding["denominator"], 3)

    def test_no_cost_measurement_is_not_free(self):
        costs = [x for x in build_findings(self.analysis())["findings"] if x["kind"] == "cost_coverage"]
        self.assertTrue(all(x["metrics"]["observed_cost_micro_usd"] is None for x in costs))
        self.assertTrue(all("No observed USD charge" in x["observation"] for x in costs))
        self.assertTrue(all("total-cost comparison is unavailable" in x["observation"] for x in costs))

    def test_all_agreement_pairs_keep_joint_errors_and_unknowns_separate(self):
        analysis = self.analysis(None)
        overview = next(x for x in build_findings(analysis)["findings"] if x["kind"] == "agreement_overview")
        metrics = overview["metrics"]
        self.assertEqual(metrics["pair_count"], 6)
        self.assertEqual(len(metrics["pair_ids"]), 6)
        self.assertEqual(metrics["pairs_with_joint_errors"], 0)
        self.assertEqual(metrics["pairs_with_unknown_references"], 3)
        self.assertEqual(metrics["minimum_accepted"], 0)
        self.assertEqual(metrics["maximum_accepted"], 2)
        self.assertEqual(overview["denominator"], 6)
        self.assertEqual(metrics["planned_cases_per_pair"], 3)
        html = render_findings(build_findings(self.analysis()))
        self.assertIn("Known reference class support: a: 3; b: 0", html)

    def test_source_correction_changes_findings_not_run_identity(self):
        first = self.analysis()
        before = copy.deepcopy(first)
        findings = build_findings(first)
        self.assertEqual(first, before)
        self.assertEqual(build_findings(first), findings)
        editable = build_findings(first)
        editable["source_hashes"]["task"] = "changed"
        editable["findings"][0]["source_hashes"]["task"] = "changed"
        editable["findings"][0]["case_ids"].clear()
        editable["findings"][0]["metrics"]["valid"] = -1
        self.assertEqual(first, before)
        self.labels["records"][0]["labels"]["queue"] = "b"
        second = self.analysis()
        self.assertEqual(first["runs"][0]["run_id"], second["runs"][0]["run_id"])
        self.assertNotEqual(findings["findings"][0]["finding_id"], build_findings(second)["findings"][0]["finding_id"])

    def test_url_roundtrip_and_html_escape(self):
        values = {"run": "<& a", "case": "x #?é", "compareRun": "b&c"}
        href = evidence_url(values["run"], values["case"], values["compareRun"])
        self.assertEqual(parse_qs(href.split("?", 1)[1]), {k: [v] for k, v in values.items()})
        findings = build_findings(self.analysis())
        findings["findings"][0]["title"] = "<script>alert('x')</script>"
        findings["findings"][0]["case_ids"] = ["<img src=x onerror=alert(1)>"]
        html = render_findings(findings)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("#case-explorer-heading?run=", html)


if __name__ == "__main__":
    unittest.main()
