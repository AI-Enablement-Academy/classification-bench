"""Manual arithmetic, immutable sources and offline sensitivity interactions."""

from copy import deepcopy
from html.parser import HTMLParser
import shutil
import subprocess
import unittest

from classification_bench.core import ValidationError, _digest, build_plan, evaluate
from classification_bench.report_analysis import build_analysis
from classification_bench.report_sensitivity import build_sensitivity, render_sensitivity


def fixture():
    task = {"name": "warehouse routing", "input_keys": ["note"], "fields": [
        {"name": "destination", "labels": ["repair", "ship"]},
        {"name": "handling", "labels": ["ordinary", "urgent"]}]}
    experiment = {"configs": [{"id": "alpha", "model": "fixture/alpha"},
                              {"id": "beta", "model": "fixture/beta"}],
                  "prompts": [{"id": "standard", "text": "Apply the task rubric."}],
                  "repeats": 1, "batch_size": 2}
    ids = ["case/α", "case b", "case-c", "case-d"]
    inputs = {"records": [{"id": case, "input": {"note": case}} for case in ids]}
    plan = build_plan(task, experiment, inputs)
    truths = [("repair", "ordinary"), ("repair", "urgent"), ("ship", "urgent"), ("repair", "ordinary")]
    labels = {"records": [{"id": case, "labels": {"destination": pair[0], "handling": pair[1]}}
                          for case, pair in zip(ids, truths)]}
    values = {"alpha": [("repair", "ordinary"), ("ship", "ordinary"), ("outside", "urgent"), None],
              "beta": [("ship", "ordinary"), ("repair", "urgent"), ("repair", "urgent"), ("repair", "ordinary")]}
    predictions = {"records": [{"config_id": config, "prompt_id": "standard", "repeat": 1,
                                 "id": case, "prediction": {"destination": pair[0], "handling": pair[1]}}
                                for config, pairs in values.items() for case, pair in zip(ids, pairs) if pair is not None]}
    return task, plan, predictions, labels


def scenario(sid="first", changes=None):
    return {"id": sid, "title": "Alternative destination", "provenance": "Operator review, 2026-10-08; provisional",
            "changes": changes if changes is not None else [{"id": "case/α", "labels": {"destination": "ship"}}]}


class SensitivityTests(unittest.TestCase):
    def setUp(self):
        self.task, self.plan, self.predictions, self.labels = fixture()

    def build(self, scenarios=None, labels="saved"):
        return build_sensitivity(self.task, self.plan, self.predictions,
                                 self.labels if labels == "saved" else labels, scenarios)

    def test_hand_calculated_single_alternative_gains_and_losses(self):
        result = self.build([scenario()])
        self.assertEqual(result["status"], "available")
        alpha, beta = result["scenarios"][0]["runs"]
        self.assertEqual((alpha["baseline_all_fields"]["correct"], alpha["all_fields"]["correct"], alpha["all_fields_delta"]["correct"]), (1, 0, -1))
        self.assertEqual((beta["baseline_all_fields"]["correct"], beta["all_fields"]["correct"], beta["all_fields_delta"]["correct"]), (2, 3, 1))
        self.assertEqual(alpha["all_fields_delta"]["full_denominator_rate"], -0.25)
        self.assertEqual(beta["all_fields_delta"]["full_denominator_rate"], 0.25)
        self.assertEqual(alpha["lost_ids"], ["case/α"])
        self.assertEqual(beta["gained_ids"], ["case/α"])
        self.assertEqual(alpha["counts"], {"planned": 4, "valid": 2, "invalid": 1, "missing": 1})
        self.assertEqual(alpha["field_deltas"]["destination"]["correct"], -1)
        self.assertEqual(alpha["field_deltas"]["handling"]["correct"], 0)
        self.assertEqual(alpha["case_deltas"][0]["fields"]["destination"]["delta"], -1)
        self.assertEqual(result["scenarios"][0]["summary"]["exact_count_delta_range"], [-1, 1])

    def test_hand_calculated_class_and_confusion_deltas(self):
        alpha = self.build([scenario()])["scenarios"][0]["runs"][0]
        delta = alpha["field_deltas"]["destination"]
        self.assertEqual(delta["labels"]["repair"]["support"], -1)
        self.assertEqual(delta["labels"]["ship"]["support"], 1)
        self.assertEqual(delta["labels"]["repair"]["tp"], -1)
        self.assertEqual(delta["labels"]["repair"]["fp"], 1)
        self.assertEqual(delta["labels"]["repair"]["fn"], 0)
        self.assertEqual(delta["labels"]["ship"]["fn"], 1)
        self.assertEqual(delta["confusion"]["repair"]["repair"], -1)
        self.assertEqual(delta["confusion"]["ship"]["repair"], 1)
        # Baseline repair recall is 1/3; its hypothetical recall is 0/2.
        self.assertEqual(delta["labels"]["repair"]["recall"], -1 / 3)
        # Baseline repair F1 is 1/2, ship F1 is 0; macro F1 loses 1/4.
        self.assertEqual(delta["macro_f1"], -0.25)

    def test_scenarios_are_independent_and_combined_deltas_match_manual_counts(self):
        first = scenario()
        second = scenario("second", [{"id": "case b", "labels": {"destination": "ship", "handling": "ordinary"}}])
        combined = scenario("combined", first["changes"] + second["changes"])
        result = self.build([first, second, combined])
        singles = [[run["all_fields_delta"]["correct"] for run in row["runs"]] for row in result["scenarios"]]
        self.assertEqual(singles, [[-1, 1], [1, -1], [0, 0]])
        self.assertEqual([run["all_fields"]["correct"] for run in result["scenarios"][2]["runs"]], [1, 2])
        self.assertEqual(result["scenarios"][1]["runs"][0]["baseline_all_fields"]["correct"], 1)
        # Multi-field changes on the same case receive one exact credit.
        self.assertEqual(result["scenarios"][1]["runs"][0]["case_deltas"][0]["all_fields"]["delta"], 1)

    def test_missing_invalid_outputs_keep_full_denominator_and_false_negatives(self):
        declared = scenario("unusable", [{"id": "case-c", "labels": {"destination": "repair"}},
                                          {"id": "case-d", "labels": {"destination": "ship"}}])
        alpha = self.build([declared])["scenarios"][0]["runs"][0]
        self.assertEqual(alpha["counts"], {"planned": 4, "valid": 2, "invalid": 1, "missing": 1})
        self.assertEqual(alpha["all_fields"]["correct"], 1)
        self.assertEqual(alpha["all_fields"]["full_denominator_rate"], 0.25)
        self.assertEqual([row["prediction_status"] for row in alpha["case_deltas"]], ["invalid", "missing"])
        self.assertEqual([row["all_fields"]["delta"] for row in alpha["case_deltas"]], [0, 0])
        self.assertEqual(alpha["case_deltas"][0]["raw_prediction"]["destination"], "outside")
        self.assertIsNone(alpha["case_deltas"][1]["prediction"])
        self.assertEqual(alpha["fields"]["destination"]["unscored_by_true_label"], {"repair": 1, "ship": 1})
        self.assertEqual(alpha["fields"]["destination"]["labels"]["repair"]["fn"], 2)

    def test_partial_references_keep_coverage_and_distinct_subset_denominators(self):
        partial = {"records": [deepcopy(self.labels["records"][0]),
                               {"id": "case b", "labels": {"destination": "repair", "handling": None}},
                               {"id": "case-c", "labels": {"handling": "urgent"}}]}
        declared = scenario("partial", [{"id": "case b", "labels": {"destination": "ship"}}])
        result = self.build([declared], partial)
        row = result["scenarios"][0]
        self.assertEqual(row["reference_coverage"], result["reference_coverage"])
        alpha = row["runs"][0]
        self.assertEqual(alpha["all_fields"]["reference_denominator"], 1)
        self.assertEqual(alpha["all_fields"]["correct"], 1)
        self.assertEqual(alpha["all_fields"]["reference_rate"], 1)
        self.assertIsNone(alpha["all_fields"]["full_denominator_rate"])
        self.assertIsNone(alpha["all_fields_delta"]["full_denominator_rate"])
        self.assertEqual(alpha["fields"]["destination"]["reference_denominator"], 2)
        self.assertEqual(alpha["fields"]["destination"]["accuracy"], 1)
        self.assertEqual(alpha["field_deltas"]["destination"]["accuracy"], 0.5)
        self.assertEqual(alpha["case_deltas"][0]["reference_status"], "partial")
        self.assertIsNone(alpha["case_deltas"][0]["all_fields"]["delta"])
        self.assertEqual(alpha["case_deltas"][0]["fields"]["destination"]["delta"], 1)

    def test_field_only_reference_scenario_has_no_invented_exact_sensitivity(self):
        partial = {"records": [{"id": "case/α", "labels": {"destination": "repair"}}]}
        result = self.build([scenario()], partial)
        self.assertEqual(result["status"], "available")
        for run in result["scenarios"][0]["runs"]:
            self.assertIsNone(run["all_fields"]["correct"])
            self.assertIsNone(run["all_fields_delta"]["correct"])
        self.assertEqual(result["scenarios"][0]["summary"]["unavailable_runs"], 2)
        self.assertIsNone(result["scenarios"][0]["summary"]["exact_count_delta_range"])
        self.assertEqual(result["scenarios"][0]["runs"][0]["field_deltas"]["destination"]["correct"], -1)

    def test_unlabeled_has_honest_unavailable_metrics_without_alternatives(self):
        for labels in (None, {"records": []}, {"records": [{"id": "case/α", "labels": {"destination": None}}]}):
            result = self.build([], labels)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["scenarios"], [])
            self.assertEqual(result["positions"], 8)
            for run in result["baseline"]["runs"]:
                self.assertIsNone(run["all_fields"]["correct"])
                self.assertIsNone(run["all_fields"]["full_denominator_rate"])
                self.assertIsNone(run["fields"]["destination"]["accuracy"])
            self.assertIn("No sensitivity score is available", render_sensitivity(result))
            with self.assertRaisesRegex(ValidationError, "unavailable reference"):
                self.build([scenario()], labels)

    def test_null_omitted_and_absent_reference_fields_cannot_be_filled(self):
        partial = {"records": [{"id": "case/α", "labels": {"destination": "repair", "handling": None}}]}
        for case, field, value in [("case/α", "handling", "urgent"), ("case b", "destination", "ship")]:
            with self.assertRaisesRegex(ValidationError, "unavailable reference"):
                self.build([scenario("absent", [{"id": case, "labels": {field: value}}])], partial)
        partial["records"][0]["labels"].pop("handling")
        with self.assertRaisesRegex(ValidationError, "unavailable reference"):
            self.build([scenario("omitted", [{"id": "case/α", "labels": {"handling": "urgent"}}])], partial)

    def test_rejects_invalid_duplicate_unknown_and_noop_scenarios(self):
        invalid = ["bad", {}, [scenario(), scenario()],
                   [scenario(changes=[])], [scenario(changes=[{"id": "unknown", "labels": {"destination": "ship"}}])],
                   [scenario(changes=[{"id": "case/α", "labels": {}}])],
                   [scenario(changes=[{"id": "case/α", "labels": {"unknown": "ship"}}])],
                   [scenario(changes=[{"id": "case/α", "labels": {"destination": "invented"}}])],
                   [scenario(changes=[{"id": "case/α", "labels": {"destination": None}}])],
                   [scenario(changes=[{"id": "case/α", "labels": {"destination": ["ship"]}}])],
                   [scenario(changes=[{"id": "case/α", "labels": {"destination": "repair"}}])],
                   [scenario(changes=scenario()["changes"] * 2)],
                   [{**scenario(), "title": " "}], [{**scenario(), "provenance": ""}],
                   [{**scenario(), "id": 1}], [{**scenario(), "extra": True}]]
        for declared in invalid:
            with self.subTest(declared=declared), self.assertRaises(ValidationError):
                self.build(declared)

    def test_source_validation_rejects_duplicate_predictions_and_unknown_references(self):
        predictions = deepcopy(self.predictions)
        predictions["records"].append(deepcopy(predictions["records"][0]))
        with self.assertRaises(ValidationError):
            build_sensitivity(self.task, self.plan, predictions, self.labels, [])
        labels = {"records": [{"id": "unknown", "labels": {"destination": "repair"}}]}
        with self.assertRaises(ValidationError):
            self.build([], labels)

    def test_input_hashes_original_evaluation_and_references_are_immutable(self):
        declared = [scenario()]
        before = _digest([self.task, self.plan, self.predictions, self.labels, declared])
        saved_evaluation = evaluate(self.task, self.plan, self.labels, self.predictions)
        result = self.build(declared)
        self.assertEqual(_digest([self.task, self.plan, self.predictions, self.labels, declared]), before)
        self.assertEqual(result["baseline"]["evaluation"], saved_evaluation)
        self.assertEqual(result["source_hashes"]["labels"], _digest(self.labels))
        self.assertNotEqual(result["scenarios"][0]["hypothetical_labels_sha256"], _digest(self.labels))
        self.assertNotEqual(result["scenarios"][0]["evaluation_sha256"], result["baseline"]["evaluation_sha256"])
        result["task"]["name"] = "mutated returned projection"
        result["scenarios"][0]["changes"][0]["labels"]["destination"] = "mutated projection"
        self.assertEqual(_digest([self.task, self.plan, self.predictions, self.labels, declared]), before)

    def test_stable_hashes_and_compatible_case_run_urls(self):
        first, second = self.build([scenario()]), self.build([scenario()])
        self.assertEqual(first, second)
        self.assertEqual(first["sensitivity_id"], _digest({key: value for key, value in first.items() if key != "sensitivity_id"}))
        item = first["scenarios"][0]
        self.assertEqual(item["result_sha256"], _digest({key: value for key, value in item.items() if key != "result_sha256"}))
        analysis = build_analysis(self.task, self.plan, self.predictions, self.labels)
        self.assertEqual([run["run_id"] for run in first["baseline"]["runs"]], [run["run_id"] for run in analysis["runs"]])
        row = item["runs"][0]["case_deltas"][0]
        self.assertIn("#case-explorer-heading?run=", row["evidence_url"])
        self.assertIn("case=case%2F%CE%B1", row["evidence_url"])
        changed = scenario()
        changed["provenance"] += "; revised"
        self.assertNotEqual(first["sensitivity_id"], self.build([changed])["sensitivity_id"])

    def test_normalized_scenario_hash_is_stable_under_change_order(self):
        changes = scenario()["changes"] + [{"id": "case b", "labels": {"handling": "ordinary", "destination": "ship"}}]
        left = self.build([scenario("both", changes)])["scenarios"][0]
        right = self.build([scenario("both", list(reversed(changes)))])["scenarios"][0]
        self.assertEqual(left["scenario_sha256"], right["scenario_sha256"])
        self.assertNotEqual(left["source_hashes"]["scenarios"], right["source_hashes"]["scenarios"])
        self.assertNotEqual(left["result_sha256"], right["result_sha256"])

    def test_report_escapes_arbitrary_task_labels_fields_and_provenance(self):
        bad = "</script><img src=x onerror=\"window.injected=1\"> & 'quoted'"
        task = {"name": bad, "input_keys": [bad], "fields": [{"name": bad, "labels": [bad, "safe"]}]}
        plan = build_plan(task, {"configs": [{"id": bad, "model": bad}], "prompts": [{"id": bad, "text": bad}],
                                 "repeats": 1, "batch_size": 1}, {"records": [{"id": bad, "input": {bad: bad}}]})
        labels = {"records": [{"id": bad, "labels": {bad: bad}}]}
        predictions = {"records": [{"config_id": bad, "prompt_id": bad, "repeat": 1, "id": bad, "prediction": {bad: bad}}]}
        declared = [{"id": bad, "title": bad, "provenance": bad, "changes": [{"id": bad, "labels": {bad: "safe"}}]}]
        html = render_sensitivity(build_sensitivity(task, plan, predictions, labels, declared))
        self.assertNotIn("<img", html)
        self.assertIn("&lt;/script&gt;&lt;img", html)
        self.assertIn("&amp;", html)
        self.assertIn("&quot;", html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("fetch(", html)
        class Tags(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)
        parser = Tags()
        parser.feed(html)
        self.assertEqual(parser.tags.count("script"), 1)
        self.assertNotIn("img", parser.tags)
        if shutil.which("node"):
            availability = subprocess.run(["node", "-e", "require.resolve('jsdom')"], capture_output=True, text=True)
            if not availability.returncode:
                check = r"""
const fs=require('fs'),assert=require('assert'),{JSDOM}=require('jsdom');
const dom=new JSDOM(fs.readFileSync(0,'utf8'),{runScripts:'dangerously',url:'file:///offline/report.html'});
assert.equal(dom.window.document.querySelectorAll('img').length,0);
assert.equal(dom.window.document.querySelectorAll('script').length,1);
assert.equal(dom.window.injected,undefined);
assert(dom.window.document.body.textContent.includes('</script><img src=x onerror="window.injected=1">'));
"""
                result = subprocess.run(["node", "-e", check], input=html, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for offline DOM checks")
    def test_offline_dom_selector_native_details_and_evidence_links(self):
        availability = subprocess.run(["node", "-e", "require.resolve('jsdom')"], capture_output=True, text=True)
        if availability.returncode:
            self.skipTest("local jsdom is not installed")
        declared = [scenario(), scenario("second", [{"id": "case b", "labels": {"destination": "ship"}}])]
        html = render_sensitivity(self.build(declared))
        result = subprocess.run(["node", "-e", _DOM], input=html, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


_DOM = r"""
const fs=require('fs'),assert=require('assert'),{JSDOM}=require('jsdom');
const html=fs.readFileSync(0,'utf8');
const dom=new JSDOM(html,{runScripts:'dangerously',url:'file:///offline/report.html'});
const d=dom.window.document,select=d.getElementById('sensitivity-scenario');
const panels=[...d.querySelectorAll('[data-sensitivity-scenario]')];
assert.equal(panels.length,2);assert.equal(panels[0].hidden,false);assert.equal(panels[1].hidden,true);
assert(d.getElementById('sensitivity-selection-status').textContent.includes('Saved references remain unchanged'));
select.value='1';select.dispatchEvent(new dom.window.Event('change'));
assert.equal(panels[0].hidden,true);assert.equal(panels[1].hidden,false);
const details=panels[1].querySelector('.sensitivity-run');details.open=true;assert(details.open);
const link=details.querySelector('a');assert(link.hash.includes('case=case+b'));
assert([...d.querySelectorAll('table')].every(t=>t.querySelector('caption')));
assert([...d.querySelectorAll('th')].every(t=>t.hasAttribute('scope')));
assert([...d.querySelectorAll('.sensitivity-table-scroll')].every(t=>t.tabIndex===0));
const plain=new JSDOM(html);assert([...plain.window.document.querySelectorAll('[data-sensitivity-scenario]')].every(p=>!p.hidden));
assert.equal(d.querySelectorAll('img').length,0);assert.equal(dom.window.injected,undefined);
"""


if __name__ == "__main__":
    unittest.main()
