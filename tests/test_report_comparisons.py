"""Hand-calculated comparisons, declared denominators and offline DOM behavior."""

from copy import deepcopy
import json
import re
import shutil
import subprocess
import unittest
from urllib.parse import parse_qs

from classification_bench.core import ValidationError, _digest, build_plan
from classification_bench.report_analysis import build_analysis
from classification_bench.report_comparisons import (
    COMPARISON_RULE, build_comparative_findings, compare_configurations,
    render_comparative_findings,
)


def fixture(labels="full", configs=None, prompts=2, repeats=2):
    task = {"name": "stock routing", "input_keys": ["note"], "fields": [
        {"name": "route", "labels": ["a", "b"]}, {"name": "risk", "labels": ["ok", "bad"]}]}
    experiment = {"configs": configs or [
        {"id": "low", "model": "fixture/one", "settings": {"effort": "low", "temperature": 0}},
        {"id": "high", "model": "fixture/one", "settings": {"effort": "high", "temperature": 0}},
        {"id": "other", "model": "fixture/two", "settings": {"effort": "low", "temperature": 1}}],
        "prompts": [{"id": "rubric " + str(i), "text": "Classify " + str(i)} for i in range(prompts)],
        "repeats": repeats, "batch_size": 2}
    ids = ["x / α", "y", "z", "m", "u"]
    inputs = {"records": [{"id": cid, "input": {"note": cid}} for cid in ids]}
    plan = build_plan(task, experiment, inputs)
    truth = {"records": [{"id": cid, "labels": {"route": "b" if cid == "u" else "a", "risk": "ok"}}
                         for cid in ids]}
    if labels == "partial":
        truth = {"records": [truth["records"][0], {"id": "y", "labels": {"route": "a"}},
                             truth["records"][2], {"id": "u", "labels": {"risk": "ok"}}]}
    elif labels is None:
        truth = None
    values = {"low": [("a", "ok"), ("b", "bad"), ("invalid", "ok"), None, ("b", "ok")],
              "high": [("b", "ok"), ("a", "ok"), ("a", "ok"), None, ("invalid", "ok")],
              "other": [("a", "ok"), ("a", "ok"), ("a", "ok"), ("a", "ok"), ("b", "ok")]}
    predictions = {"records": []}
    for config in experiment["configs"]:
        for cid, pair in zip(ids, values.get(config["id"], values["low"])):
            if pair is not None:
                predictions["records"].append({"config_id": config["id"], "prompt_id": "rubric 0", "repeat": 1,
                    "id": cid, "prediction": {"route": pair[0], "risk": pair[1]}})
    return task, plan, predictions, truth


def run(analysis, config="low", prompt="rubric 0", repeat=1):
    return next(r for r in analysis["runs"] if (r["config_id"], r["prompt_id"], r["repeat"]) == (config, prompt, repeat))


class ComparisonTests(unittest.TestCase):
    def analysis(self, labels="full", **kwargs):
        return build_analysis(*fixture(labels, **kwargs))

    def pair(self, analysis=None):
        analysis = analysis or self.analysis()
        return compare_configurations(analysis, run(analysis)["run_id"], run(analysis, "high")["run_id"])

    def test_hand_calculated_full_reference_transitions_keep_unusable_positions(self):
        pair = self.pair()
        self.assertEqual(pair["planned"], 5)
        self.assertEqual(pair["outcomes_a"], {"valid": 3, "invalid": 1, "missing": 1})
        self.assertEqual(pair["outcomes_b"], {"valid": 3, "invalid": 1, "missing": 1})
        self.assertEqual((pair["both_valid"], pair["changed"], pair["not_both_valid"]), (2, 2, 3))
        self.assertEqual(pair["changed_ids"], ["x / α", "y"])
        self.assertEqual(pair["unusable_to_valid_ids"], ["z"])
        self.assertEqual(pair["valid_to_unusable_ids"], ["u"])
        self.assertEqual(pair["unusable_both_ids"], ["m"])
        score = pair["all_fields"]
        self.assertEqual(score["gained_ids"], ["y", "z"])
        self.assertEqual(score["lost_ids"], ["x / α", "u"])
        self.assertEqual(score["stable_error_ids"], ["m"])
        self.assertEqual((score["correct_a"], score["correct_b"], score["net_gain"]), (2, 2, 0))
        self.assertEqual(score["full_denominator_rate_a"], 2 / 5)
        self.assertEqual(sum(score[key] for key in ("gained", "lost", "stable_correct", "stable_error")), 5)

    def test_partial_references_have_independent_field_coverage_without_whole_accuracy(self):
        pair = self.pair(self.analysis("partial"))
        all_fields = pair["all_fields"]
        self.assertEqual((all_fields["known_references"], all_fields["unknown_references"]), (2, 3))
        self.assertEqual(all_fields["reference_unknown_ids"], ["y", "m", "u"])
        self.assertEqual((all_fields["correct_a"], all_fields["correct_b"]), (1, 1))
        self.assertIsNone(all_fields["full_denominator_rate_a"])
        route, risk = pair["fields"]["route"], pair["fields"]["risk"]
        self.assertEqual((route["known_references"], route["correct_a"], route["correct_b"], route["net_gain"]), (3, 1, 2, 1))
        self.assertEqual(route["gained_ids"], ["y", "z"])
        self.assertEqual((risk["known_references"], risk["correct_a"], risk["correct_b"], risk["net_gain"]), (3, 2, 2, 0))
        self.assertIn("u", risk["lost_ids"])
        self.assertEqual(risk["known_reference_rate_a"], 2 / 3)

    def test_unlabeled_and_different_reference_versions_do_not_invent_agreement(self):
        unlabeled = self.analysis(None)
        pair = self.pair(unlabeled)
        for score in [pair["all_fields"], *pair["fields"].values()]:
            self.assertEqual(score["known_references"], 0)
            self.assertEqual(score["unknown_references"], 5)
            for key in ("correct_a", "correct_b", "gained", "lost", "stable_correct", "stable_error", "net_gain", "known_reference_rate_a"):
                self.assertIsNone(score[key])
        self.assertEqual(pair["changed"], 2)
        self.assertEqual((pair["fields"]["route"]["changed"], pair["fields"]["route"]["both_valid"]), (2, 2))
        changed = self.analysis()
        run(changed, "high")["source_hashes"]["labels"] = "another-reference-version"
        versioned = self.pair(changed)
        self.assertFalse(versioned["reference_compatible"])
        self.assertIsNone(versioned["all_fields"]["net_gain"])

    def test_all_eligible_pairs_fix_prompt_repeat_and_declared_dimensions(self):
        analysis = self.analysis()
        result = build_comparative_findings(analysis)
        self.assertEqual(result["rule"], COMPARISON_RULE)
        self.assertEqual(result["pair_inventory"], {"cross_configuration_candidates": 48,
            "different_prompt_or_repeat": 36, "incompatible_task_or_inputs": 0, "eligible_pairs": 12})
        for pair in result["pairs"]:
            self.assertEqual(pair["planned"], 5)
            self.assertNotIn("cases", pair)
            self.assertNotIn("changed_ids", pair)
        one = next(p for p in result["pairs"] if p["config_a"] == "low" and p["config_b"] == "high")
        self.assertEqual(one["design"], "single_varying_dimension")
        self.assertEqual([d["pointer"] for d in one["configuration_changes"]], ["/settings/effort"])
        confounded = next(p for p in result["pairs"] if p["config_a"] == "low" and p["config_b"] == "other")
        self.assertEqual(confounded["design"], "confounded")
        self.assertEqual([d["pointer"] for d in confounded["configuration_changes"]], ["/model", "/settings/temperature"])
        with self.assertRaises(ValidationError):
            compare_configurations(analysis, run(analysis)["run_id"], run(analysis, "high", repeat=2)["run_id"])
        with self.assertRaises(ValidationError):
            compare_configurations(analysis, run(analysis)["run_id"], run(analysis, "high", prompt="rubric 1")["run_id"])

    def test_configuration_id_and_reporting_group_are_not_requested_settings(self):
        configs = [{"id": "low", "model": "fixture", "model_type": "llm"},
                   {"id": "high", "model": "fixture", "model_type": "decision", "settings": {}}]
        result = build_comparative_findings(self.analysis(configs=configs, prompts=1, repeats=1))
        pair = result["pairs"][0]
        self.assertEqual(pair["design"], "same_requested_settings")
        self.assertEqual(pair["configuration_changes"], [])
        self.assertEqual(pair["reporting_changes"][0]["path"], ["model_type"])

    def test_missing_null_boolean_and_escaped_nested_settings_remain_distinct(self):
        configs = [{"id": "low", "model": "fixture", "settings": {"a/b": {"~flag": True}}},
                   {"id": "high", "model": "fixture", "settings": {"a/b": {"~flag": 1}, "nullable": None}}]
        changes = build_comparative_findings(self.analysis(configs=configs, prompts=1, repeats=1))["pairs"][0]["configuration_changes"]
        self.assertEqual([c["pointer"] for c in changes], ["/settings/a~1b/~0flag", "/settings/nullable"])
        self.assertFalse(changes[1]["a_present"])
        self.assertTrue(changes[1]["b_present"])
        self.assertIsNone(changes[1]["b"])

    def test_added_nested_object_exposes_every_declared_leaf_dimension(self):
        configs = [{"id": "low", "model": "fixture"}, {"id": "high", "model": "fixture",
                   "settings": {"backend": {"provider": "fixture", "route": "direct"}}}]
        pair = build_comparative_findings(self.analysis(configs=configs, prompts=1, repeats=1))["pairs"][0]
        self.assertEqual(pair["design"], "confounded")
        self.assertEqual([d["pointer"] for d in pair["configuration_changes"]], ["/settings/backend/provider", "/settings/backend/route"])
        self.assertTrue(all(not d["a_present"] for d in pair["configuration_changes"]))

    def test_batch_membership_change_is_disclosed_as_a_requested_dimension(self):
        configs = [{"id": "low", "model": "fixture"}, {"id": "high", "model": "fixture"}]
        analysis = self.analysis(configs=configs, prompts=1, repeats=1)
        for case in run(analysis, "high")["cases"]:
            case["request_id"] = "individual:" + case["case_id"]
        pair = self.pair(analysis)
        self.assertEqual(pair["design"], "single_varying_dimension")
        self.assertEqual(pair["configuration_changes"][0]["pointer"], "/request_batches")
        self.assertEqual(pair["configuration_changes"][0]["a"]["request_count"], 3)
        self.assertNotIn("x / α", json.dumps(pair["configuration_changes"][0]))

    def test_declared_cohorts_preserve_distinct_configuration_and_unusable_counts(self):
        task, plan, predictions, labels = fixture()
        baseline = build_analysis(task, plan, predictions, labels)
        selected = [run(baseline)["run_id"], run(baseline, "high")["run_id"]]
        declaration = {"id": "fresh", "title": "Frozen fresh subset", "origin": "declared_fresh", "run_ids": selected,
                       "one_run_per_configuration": True, "source": "operator manifest 7", "case_ids": ["z", "m", "u"]}
        result = build_comparative_findings(build_analysis(task, plan, predictions, labels, cohort_declarations=[declaration]))
        cohort = result["cohorts"][0]
        self.assertEqual((cohort["planned_cases"], cohort["planned_runs"], cohort["distinct_configurations"], cohort["planned_positions"]), (3, 2, 2, 6))
        self.assertEqual(cohort["origin"], "declared_fresh")
        self.assertEqual(cohort["condition_scope"], "same_prompt_and_repeat")
        z, m, u = cohort["cases"]
        self.assertEqual(z["outcomes"], {"valid": 1, "invalid": 1, "missing": 0})
        self.assertEqual((z["unusable_configurations"], m["unusable_configurations"], u["unusable_configurations"]), (1, 2, 1))
        self.assertEqual(z["unusable_full_reference_runs"], 1)
        self.assertEqual(m["unusable_full_reference_runs"], 2)
        self.assertEqual(cohort["unusable_ids"], ["z", "m", "u"])
        for row in cohort["cases"]:
            self.assertEqual(sum(row["outcomes"].values()), 2)
            for item in row["supporting_links"]:
                params = parse_qs(item["url"].split("?", 1)[1])
                self.assertEqual(params["case"], [row["case_id"]])
                self.assertIn(params["run"][0], selected)

    def test_repeats_add_run_positions_without_configuration_votes_or_freshness(self):
        task, plan, predictions, labels = fixture()
        predictions["records"].append({"config_id": "low", "prompt_id": "rubric 0", "repeat": 2,
            "id": "x / α", "prediction": {"route": "b", "risk": "ok"}})
        baseline = build_analysis(task, plan, predictions, labels)
        ids = [run(baseline)["run_id"], run(baseline, repeat=2)["run_id"], run(baseline, "high")["run_id"]]
        declaration = {"id": "history", "title": "Prior observations", "origin": "historical", "run_ids": ids,
                       "one_run_per_configuration": False, "source": "frozen historical manifest", "case_ids": ["x / α", "z"]}
        cohort = build_comparative_findings(build_analysis(task, plan, predictions, labels, cohort_declarations=[declaration]))["cohorts"][0]
        self.assertEqual((cohort["planned_runs"], cohort["distinct_configurations"], cohort["planned_positions"]), (3, 2, 6))
        x, z = cohort["cases"]
        self.assertTrue(x["cross_configuration_disagreement"])
        self.assertEqual(x["within_configuration_variable_count"], 1)
        self.assertEqual(z["configurations_with_unusable_runs"], 1)
        self.assertEqual(z["unusable_configurations"], 1)
        self.assertIn("mixed_prompts_or_repeats", cohort["condition_scope"])
        default = build_comparative_findings(baseline)["cohorts"][0]
        self.assertEqual(default["origin"], "unspecified")
        self.assertEqual(default["declaration_status"], "unspecified_origin")

    def test_partial_and_unlabeled_cohorts_keep_field_errors_and_unavailable_metrics(self):
        partial = build_comparative_findings(self.analysis("partial"))["cohorts"][0]
        y = next(c for c in partial["cases"] if c["case_id"] == "y")
        self.assertIsNone(y["valid_full_reference_error_runs"])
        self.assertEqual(y["valid_known_field_error_runs"], 1)
        self.assertIn("known_reference_disagreement", y["difficulty_reasons"])
        self.assertIn("y", partial["reference_error_ids"])
        self.assertNotIn("y", partial["full_reference_error_ids"])
        self.assertEqual(y["fields"]["route"]["known_reference_runs"], 12)
        self.assertIsNone(y["fields"]["risk"]["valid_reference_errors"])
        unlabeled = build_comparative_findings(self.analysis(None))["cohorts"][0]
        self.assertEqual(unlabeled["reference_error_ids"], [])
        for row in unlabeled["cases"]:
            self.assertIsNone(row["valid_full_reference_error_runs"])
            self.assertIsNone(row["valid_known_field_error_runs"])
            self.assertEqual(row["no_reference_runs"], 12)
            self.assertTrue(all(f["valid_reference_errors"] is None for f in row["fields"].values()))

    def test_range_links_reference_exact_boundary_pairs_and_all_ties(self):
        analysis = self.analysis()
        result = build_comparative_findings(analysis)
        overview = result["findings"][0]
        self.assertEqual(overview["kind"], "controlled_configuration_overview")
        values = [p["all_fields"]["net_gain"] for p in result["pairs"]]
        for evidence, link in zip(overview["metrics"]["comparative_evidence"], overview["supporting_links"]):
            pair = next(p for p in result["pairs"] if p["comparison_id"] == evidence["comparison_id"])
            self.assertEqual(evidence["net_gain"], min(values) if evidence["boundary"] == "minimum" else max(values))
            self.assertEqual(evidence["tied_pairs"], values.count(evidence["net_gain"]))
            self.assertEqual(link["run_a"], pair["run_a"])
            self.assertEqual(link["run_b"], pair["run_b"])
            self.assertEqual(link["url"], pair["evidence_url"])
        self.assertIn("not a pooled score", overview["observation"])

    def test_requested_reverse_ab_order_reverses_direction_without_scope_changes(self):
        analysis = self.analysis("partial")
        forward = self.pair(analysis)
        reverse = compare_configurations(analysis, forward["run_b"], forward["run_a"])
        self.assertEqual(reverse["fields"]["route"]["net_gain"], -1)
        self.assertEqual(reverse["fields"]["route"]["gained_ids"], forward["fields"]["route"]["lost_ids"])
        self.assertEqual(reverse["fields"]["route"]["lost_ids"], forward["fields"]["route"]["gained_ids"])
        self.assertEqual(reverse["planned"], forward["planned"])
        self.assertEqual(reverse["unusable_to_valid_ids"], forward["valid_to_unusable_ids"])

    def test_malformed_positions_and_incompatible_inputs_are_not_repaired(self):
        for mutation in ("duplicate_run", "duplicate_case", "invalid_label", "unknown_reference"):
            analysis = self.analysis()
            if mutation == "duplicate_run":
                analysis["runs"].append(deepcopy(analysis["runs"][0]))
            elif mutation == "duplicate_case":
                analysis["runs"][0]["cases"].append(deepcopy(analysis["runs"][0]["cases"][0]))
            elif mutation == "invalid_label":
                analysis["runs"][0]["cases"][0]["prediction"]["route"] = "not declared"
            else:
                analysis["runs"][0]["cases"][0]["reference"]["unknown"] = "a"
            with self.assertRaises(ValidationError, msg=mutation):
                build_comparative_findings(analysis)
        analysis = self.analysis()
        analysis["cohorts"] = []
        run(analysis, "high")["input_sha256"] = "different inputs"
        result = build_comparative_findings(analysis)
        self.assertEqual(result["pair_inventory"]["incompatible_task_or_inputs"], 8)
        with self.assertRaises(ValidationError):
            self.pair(analysis)

    def test_deterministic_source_bound_detached_results_and_bounded_matrix_narratives(self):
        analysis = self.analysis()
        original = deepcopy(analysis)
        result = build_comparative_findings(analysis)
        self.assertEqual(result, build_comparative_findings(analysis))
        self.assertEqual(analysis, original)
        for finding in result["findings"]:
            self.assertEqual(finding["source_hashes"], analysis["source_hashes"])
            self.assertTrue(finding["run_ids"])
        result["source_hashes"]["task"] = "edited"
        result["pairs"][0]["configuration_changes"][0]["b"] = "edited"
        result["cohorts"][0]["case_ids"].append("edited")
        self.assertEqual(analysis, original)
        configs = [{"id": "config" + str(i), "model": "fixture/" + str(i)} for i in range(30)]
        matrix = build_comparative_findings(self.analysis(None, configs=configs, prompts=1, repeats=1))
        self.assertEqual(len(matrix["pairs"]), 435)
        self.assertEqual(len(matrix["findings"]), 2)
        self.assertTrue(all("cases" not in p and not any(k.endswith("_ids") for k in p) for p in matrix["pairs"]))
        self.assertIsNone(matrix["findings"][0]["metrics"]["comparative_evidence"] or None)
        self.assertEqual(matrix["comparisons_id"], _digest({k: v for k, v in matrix.items() if k != "comparisons_id"}))


class ComparisonDomTests(unittest.TestCase):
    def dom_check(self, projection, code, *, initial_scope=None, fallback_scope=None):
        if not shutil.which("node"):
            self.skipTest("local Node.js unavailable")
        available = subprocess.run(["node", "-e", "require.resolve('jsdom')"], capture_output=True, text=True)
        if available.returncode:
            self.skipTest("local jsdom unavailable")
        script = r"""
const fs=require('fs'),assert=require('assert'),{JSDOM,VirtualConsole}=require('jsdom');
const input=JSON.parse(fs.readFileSync(0,'utf8')),errors=[];
const console=new VirtualConsole();console.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(input.html,{runScripts:'dangerously',url:'file:///offline/report.html',virtualConsole:console,beforeParse(window){
if(input.initial_scope!==null)window.reportFilters={getState:()=>({eligibleRunIds:input.initial_scope})};
if(input.fallback_scope!==null)window.addEventListener('report-filter-request',()=>window.dispatchEvent(new window.CustomEvent('report-filter-change',{detail:{eligibleRunIds:input.fallback_scope}})));
}});
const document=dom.window.document,get=id=>document.getElementById(id);
function change(id,value){get(id).value=value;get(id).dispatchEvent(new dom.window.Event('change',{bubbles:true}));}
function filter(ids){dom.window.dispatchEvent(new dom.window.CustomEvent('report-filter-change',{detail:{eligibleRunIds:ids}}));}
""" + code + "\nassert.deepEqual(errors,[]);"
        result = subprocess.run(["node", "-e", script], input=json.dumps({"html": render_comparative_findings(projection),
            "projection": projection, "initial_scope": initial_scope,
            "fallback_scope": fallback_scope}), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pair_filter_and_declared_cohort_totals_are_separate(self):
        projection = build_comparative_findings(build_analysis(*fixture()))
        self.dom_check(projection, r"""
assert.equal(get('controlled-pair-body').children.length,12);
const first=input.projection.pairs[0];filter([first.run_a,first.run_b]);
assert.equal(get('controlled-pair-body').children.length,1);
assert.match(get('controlled-pair-status').textContent,/1\/12 eligible pairs/);
assert.match(get('controlled-cohort-status').textContent,/3 distinct configurations, 12 selected runs, 5 cases/);
assert.match(get('controlled-cohort-status').textContent,/2\/12 cohort runs match/);
assert.match(get('controlled-cohort-status').textContent,/aggregates remain unchanged/);
change('controlled-pair-scope','all');assert.equal(get('controlled-pair-body').children.length,12);
assert.match(get('controlled-pair-body').textContent,/Outside matching report filters/);
filter([]);change('controlled-pair-scope','matching');assert.equal(get('controlled-pair-body').children.length,0);
assert.equal(get('controlled-cohort-body').children.length,5);
assert.match(get('controlled-cohort-body').textContent,/outside matching report filters/);
const region=document.querySelector('.comparison-scroll');assert.equal(region.tabIndex,0);assert.equal(region.getAttribute('role'),'region');
assert.ok(document.querySelector('caption'));assert.ok(document.querySelector('th[scope="row"]'));
""")

    def test_many_pairs_paginate_without_truncating_data_or_selecting_score_winners(self):
        configs = [{"id": "config" + str(i), "model": "fixture/" + str(i)} for i in range(8)]
        projection = build_comparative_findings(build_analysis(*fixture(None, configs=configs, prompts=1, repeats=1)))
        self.dom_check(projection, r"""
assert.equal(input.projection.pairs.length,28);assert.equal(get('controlled-pair-body').children.length,12);
get('controlled-pair-next').click();assert.equal(get('controlled-pair-body').children.length,12);
get('controlled-pair-next').click();assert.equal(get('controlled-pair-body').children.length,4);
assert.equal(get('controlled-pair-next').disabled,true);assert.match(get('controlled-pair-status').textContent,/28\/28/);
assert.match(get('controlled-pair-body').textContent,/unavailable/);
filter([input.projection.pairs[0].run_a,input.projection.pairs[0].run_b]);assert.match(get('controlled-pair-status').textContent,/page 1\/1/);
""")

    def test_arbitrary_labels_titles_and_script_fragments_are_escaped(self):
        task, plan, predictions, labels = fixture()
        analysis = build_analysis(task, plan, predictions, labels)
        analysis["cohorts"][0]["title"] = "</script><img src=x onerror=alert(1)> & cohort"
        analysis["cohorts"][0]["source"] = "<b>operator</b>"
        projection = build_comparative_findings(analysis)
        html = render_comparative_findings(projection)
        data = re.search(r"<script type='application/json' id='controlled-comparison-data'>(.*?)</script>", html, re.S).group(1)
        self.assertNotIn("<", data)
        self.assertEqual(json.loads(data)["cohorts"][0]["title"], analysis["cohorts"][0]["title"])
        self.dom_check(projection, r"""
assert.equal(document.querySelectorAll('img').length,0);assert.equal(document.querySelectorAll('b').length,0);
assert.match(get('controlled-cohort-status').textContent,/<img src=x/);
assert.match(get('controlled-cohort-note').textContent,/<b>operator<\/b>/);
""")

    def test_initial_snapshot_and_request_fallback_apply_matching_scope(self):
        analysis = build_analysis(*fixture())
        projection = build_comparative_findings(analysis)
        ids = [r["run_id"] for r in analysis["runs"] if r["repeat"] == 1]
        check = r"""
assert.equal(get('controlled-pair-body').children.length,6);
assert.match(get('controlled-pair-status').textContent,/6\/12 eligible pairs/);
assert.match(get('controlled-cohort-status').textContent,/6\/12 cohort runs match/);
assert.match(get('controlled-cohort-status').textContent,/3\/3 distinct configurations/);
"""
        self.dom_check(projection, check, initial_scope=ids)
        self.dom_check(projection, check, fallback_scope=ids)

    def test_unchanged_scope_preserves_pagination_and_malformed_events_are_ignored(self):
        configs = [{"id": "config" + str(i), "model": "fixture/" + str(i)} for i in range(8)]
        projection = build_comparative_findings(build_analysis(*fixture(None, configs=configs, prompts=1, repeats=1)))
        self.dom_check(projection, r"""
const ids=[...new Set(input.projection.pairs.flatMap(p=>[p.run_a,p.run_b]))];
get('controlled-pair-next').click();assert.match(get('controlled-pair-status').textContent,/page 2\/3/);
filter(ids.slice().reverse());assert.match(get('controlled-pair-status').textContent,/page 2\/3/);
filter([...ids,ids[0],'unknown']);assert.match(get('controlled-pair-status').textContent,/page 2\/3/);
for(const detail of [null,{}, {eligibleRunIds:'bad'}, {eligibleRunIds:[1]}])dom.window.dispatchEvent(new dom.window.CustomEvent('report-filter-change',{detail}));
assert.match(get('controlled-pair-status').textContent,/page 2\/3/);
filter(ids.slice(0,2));assert.match(get('controlled-pair-status').textContent,/page 1\/1/);
assert.equal(get('controlled-pair-body').children.length,1);
""")


if __name__ == "__main__":
    unittest.main()
