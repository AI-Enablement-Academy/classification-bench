"""Declared metadata, whole-run scope and synchronized offline filter state."""

from copy import deepcopy
import json
import shutil
import subprocess
import unittest

from classification_bench.core import ValidationError, _digest, build_plan
from classification_bench.report_analysis import build_analysis
from classification_bench.report_filters import build_report_filter_data, filter_report_runs, render_report_filters


def fixture():
    task = {"name": "Parcel routing", "input_keys": ["note"], "fields": [{"name": "queue", "labels": ["hold", "ship"]}]}
    experiment = {"configs": [
        {"id": "alpha", "model": "requested / alpha?", "model_type": "llm", "settings": {
            "adapter": "openrouter", "provider": "unavailable", "reasoning": "low"}},
        {"id": "native", "model": "clef", "model_type": "decision", "settings": {"adapter": "clef_decide"}},
        {"id": "unknown", "model": "provider-name/is-not-proof", "settings": {"adapter": "unsupported <route>"}}],
        "prompts": [{"id": "plain? & route", "text": "Use the rubric."}, {"id": "careful<script>", "text": "Read the SOP."}],
        "repeats": 2, "batch_size": 1}
    inputs = {"records": [{"id": case, "input": {"note": case}} for case in ("a/é", "b #?", "c")]}
    plan = build_plan(task, experiment, inputs)
    predictions = {"records": [
        {"config_id": "alpha", "prompt_id": "plain? & route", "repeat": 1, "id": "a/é", "prediction": {"queue": "hold"}},
        {"config_id": "alpha", "prompt_id": "plain? & route", "repeat": 1, "id": "b #?", "prediction": {"queue": "invalid"}},
        *[{"config_id": "native", "prompt_id": "plain? & route", "repeat": 1, "id": case, "prediction": {"queue": "ship"}}
          for case in ("a/é", "b #?", "c")]]}
    labels = {"records": [{"id": "a/é", "labels": {"queue": "hold"}}]}
    operations = []
    for request in plan["requests"]:
        config, repeat, case = request["config_id"], request["repeat"], request["items"][0]["id"]
        if config == "alpha":
            state = {"a/é": "finished", "b #?": "refused", "c": "outcome_unknown"}[case] if repeat == 1 else "ready"
        elif config == "native":
            state = "finished"
        else:
            state = None
        operations.append({"request_id": request["request_id"], "state": state})
    return build_analysis(task, plan, predictions, labels, operations), task, plan, predictions, labels, operations


def option(data, key, value):
    return next(item["id"] for item in data["options"][key] if item["value"] == value)


class ReportFilterTests(unittest.TestCase):
    def setUp(self):
        self.analysis, self.task, self.plan, self.predictions, self.labels, self.operations = fixture()
        self.data = build_report_filter_data(self.analysis)

    def test_metadata_uses_declared_values_and_local_contracts_without_model_guessing(self):
        a, native, unknown = [next(run for run in self.data["runs"] if run["config_id"] == name) for name in ("alpha", "native", "unknown")]
        self.assertEqual(a["values"]["model"], "requested / alpha?")
        self.assertEqual(a["values"]["provider"], "unavailable")
        self.assertEqual(a["values"]["execution_route"], "openrouter")
        self.assertEqual(a["values"]["effort"], "low")
        self.assertEqual(a["values"]["output_interface"], "JSON text")
        self.assertEqual(native["values"]["provider"], "cloudflare")
        self.assertEqual(native["values"]["output_interface"], "Native choices and probabilities")
        self.assertEqual(native["values"]["api_route"], "cloudflare:clef")
        self.assertEqual(native["metadata_sources"]["provider"], "native adapter contract")
        self.assertIsNone(unknown["values"]["provider"])
        self.assertIsNone(unknown["values"]["output_interface"])
        self.assertIsNone(unknown["values"]["model_group"])
        self.assertEqual(unknown["values"]["execution_route"], "unsupported <route>")
        self.assertEqual(unknown["values"]["adapter_category"], "Other declared adapter")
        self.assertNotEqual(option(self.data, "provider", "unavailable"), option(self.data, "provider", None))

    def test_cli_contracts_and_explicit_interface_and_provider_take_precedence(self):
        modified = deepcopy(self.analysis)
        for run in modified["runs"]:
            if run["config_id"] == "unknown":
                run["configuration"]["settings"] = {"adapter": "codex", "effort": "xhigh"}
        result = build_report_filter_data(modified)
        first = next(run for run in result["runs"] if run["config_id"] == "unknown")
        self.assertEqual(first["values"]["provider"], "chatgpt_subscription")
        self.assertEqual(first["values"]["execution_route"], "codex")
        self.assertEqual(first["values"]["output_interface"], "Schema-constrained JSON")
        self.assertEqual(first["values"]["effort"], "xhigh")
        for run in modified["runs"]:
            run["configuration"]["settings"].update(provider="operator-declared", output_interface="custom finite labels", route="operator route")
        result = build_report_filter_data(modified)
        self.assertTrue(all(run["values"]["provider"] == "operator-declared" for run in result["runs"]))
        self.assertTrue(all(run["values"]["output_interface"] == "custom finite labels" for run in result["runs"]))
        self.assertTrue(all(run["values"]["api_route"] == "operator route" for run in result["runs"]))

    def test_preflight_invalid_adapter_categories_match_navigation_values(self):
        for adapter, category in (({"name": "openrouter"}, "Invalid declared adapter"),
                                  (["openrouter"], "Invalid declared adapter"),
                                  (True, "Invalid declared adapter"),
                                  ("   ", "Other declared adapter"),
                                  ("", "Adapter unspecified"), (None, "Adapter unspecified")):
            with self.subTest(adapter=adapter):
                modified = deepcopy(self.analysis)
                for run in modified["runs"]:
                    if run["config_id"] == "unknown":
                        run["configuration"]["settings"]["adapter"] = deepcopy(adapter)
                data = build_report_filter_data(modified)
                selected = filter_report_runs(data, {"adapter_category": option(data, "adapter_category", category)})
                self.assertEqual(selected["visible"]["runs"], 4)
                rows = [run for run in data["runs"] if run["config_id"] == "unknown"]
                self.assertTrue(all(run["values"]["execution_route"] is None for run in rows))
                self.assertTrue(all(run["values"]["provider"] is None for run in rows))
                self.assertTrue(all(run["values"]["output_interface"] is None for run in rows))
        modified = deepcopy(self.analysis)
        for run in modified["runs"]:
            if run["config_id"] == "unknown":
                run["configuration"]["settings"]["adapter"] = {"name": "openrouter"}
        self.dom("""
api.setValue('adapter_category','Invalid declared adapter');
assert.equal(api.getState().visible.runs,4);
assert.equal(api.matchesValue('adapter_category','Invalid declared adapter'),true);
""", analysis=modified)

    def test_manual_intersection_counts_and_partial_condition_scope(self):
        selected = {"model_group": option(self.data, "model_group", "llm"), "repeat": option(self.data, "repeat", "1")}
        result = filter_report_runs(self.data, selected)
        self.assertEqual(result["whole"], {"runs": 12, "positions": 36, "conditions": 6, "distinctCases": 3, "valid": 4, "invalid": 1, "missing": 31})
        self.assertEqual(result["visible"], {"runs": 2, "positions": 6, "conditions": 2, "distinctCases": 3, "valid": 1, "invalid": 1, "missing": 4})
        self.assertTrue(all(run["config_id"] == "alpha" and run["repeat"] == 1 for run in self.data["runs"] if run["run_id"] in result["eligibleRunIds"]))
        partial = [scope for scope in result["conditionScopes"] if scope["partial"]]
        self.assertEqual(len(partial), 2)
        self.assertTrue(all(scope["visibleRuns"] == 1 and scope["totalRuns"] == 2 for scope in partial))
        self.assertEqual(result["selectedValues"], {"model_group": "llm", "repeat": "1"})

    def test_lifecycle_multi_outcomes_select_whole_runs_without_case_rescoring(self):
        result = filter_report_runs(self.data, {"lifecycle": option(self.data, "lifecycle", "refused")})
        self.assertEqual(result["visible"]["runs"], 2)
        self.assertEqual(result["visible"]["positions"], 6)
        # Only one refused case per selected run; the other two retain membership.
        self.assertTrue(all(len(run["values"]["lifecycle"]) == 3 for run in self.data["runs"] if run["run_id"] in result["eligibleRunIds"]))
        unavailable = filter_report_runs(self.data, {"lifecycle": option(self.data, "lifecycle", None)})
        self.assertEqual(unavailable["visible"]["runs"], 4)
        self.assertEqual(unavailable["visible"]["positions"], 12)
        self.assertNotIn("invalid", [item["value"] for item in self.data["options"]["lifecycle"]])
        self.assertIn("refused", [item["value"] for item in self.data["options"]["lifecycle"]])

    def test_unavailable_metadata_and_zero_run_group_remain_honest(self):
        unavailable = filter_report_runs(self.data, {"provider": option(self.data, "provider", None)})
        declared = filter_report_runs(self.data, {"provider": option(self.data, "provider", "unavailable")})
        self.assertEqual(unavailable["visible"]["runs"], 4)
        self.assertEqual(declared["visible"]["runs"], 4)
        self.assertNotEqual(unavailable["eligibleRunIds"], declared["eligibleRunIds"])
        empty = filter_report_runs(self.data, {"model_group": option(self.data, "model_group", "fine_tuned_llm")})
        self.assertEqual(empty["visible"], {"runs": 0, "positions": 0, "conditions": 0, "distinctCases": 0, "valid": 0, "invalid": 0, "missing": 0})
        self.assertEqual(empty["whole"]["positions"], 36)

    def test_pure_projection_hashes_and_sources_are_immutable(self):
        saved = deepcopy(self.analysis)
        first = build_report_filter_data(self.analysis)
        self.assertEqual(first, build_report_filter_data(self.analysis))
        self.assertEqual(first["filter_data_id"], _digest({key: value for key, value in first.items() if key != "filter_data_id"}))
        filtered = filter_report_runs(first)
        filtered["selectedValues"]["provider"] = "edited"
        filtered["whole"]["positions"] = 999
        first["source_hashes"]["labels"] = "edited"
        first["runs"][0]["values"]["lifecycle"].append("edited")
        self.assertEqual(self.analysis, saved)
        projected = build_report_filter_data(self.analysis)
        # The prediction source hash remains available for source binding, while
        # raw case payloads and predictions never enter the filter projection.
        self.assertEqual(projected["source_hashes"]["predictions"], saved["source_hashes"]["predictions"])
        for run in projected["runs"]:
            self.assertNotIn("cases", run)
            self.assertNotIn("prediction", run)
            self.assertNotIn("input", run)

    def test_bad_filter_and_inconsistent_source_projection_are_rejected(self):
        for selected in ({"unknown": ""}, {"model": "unknown-option"}, {"repeat": None}, []):
            with self.assertRaises(ValidationError):
                filter_report_runs(self.data, selected)
        for edit in (lambda value: value["runs"].append(deepcopy(value["runs"][0])),
                     lambda value: value["runs"][0]["counts"].update(valid=999),
                     lambda value: value["runs"][0]["cases"][0].update(lifecycle_state={}),
                     lambda value: value["runs"][0]["configuration"].update(model_type="invented")):
            bad = deepcopy(self.analysis)
            edit(bad)
            with self.assertRaises(ValidationError):
                build_report_filter_data(bad)

    def dom(self, check, *, url="file:///offline/report.html", analysis=None):
        if not shutil.which("node"):
            self.skipTest("local Node.js unavailable")
        available = subprocess.run(["node", "-e", "require.resolve('jsdom')"], capture_output=True, text=True)
        if available.returncode:
            self.skipTest("local jsdom unavailable")
        analysis = analysis or self.analysis
        payload = {"html": render_report_filters(analysis), "url": url,
                   "data": build_report_filter_data(analysis)}
        result = subprocess.run(["node", "-e", _DOM_START + check + _DOM_END], input=json.dumps(payload), text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dom_aliases_share_one_state_reset_and_snapshot_counts(self):
        self.dom(r"""
const legacy=document.createElement('select');legacy.dataset.filter='prompt';legacy.innerHTML='<option value="old">Old independent state</option>';document.body.append(legacy);
const comparison=document.createElement('select');comparison.dataset.comparisonFilter='prompt';document.body.append(comparison);
api.refreshAliases();assert.equal(legacy.options.length,input.data.options.prompt.length+1);
assert(![...legacy.options].some(option=>option.value==='old'));
legacy.value=id('prompt','plain? & route');legacy.dispatchEvent(new dom.window.Event('change'));
assert.equal(comparison.value,legacy.value);assert.equal(document.getElementById('report-filter-prompt').value,legacy.value);
assert.equal(events.at(-1).visible.runs,6);assert.equal(events.at(-1).visible.positions,18);assert.equal(events.at(-1).whole.positions,36);
api.setValue('repeat','1');assert.equal(api.getState().visible.runs,3);assert.equal(api.getState().visible.positions,9);
assert(api.getState().conditionScopes.filter(scope=>scope.partial).every(scope=>scope.visibleRuns===1&&scope.totalRuns===2));
api.setValue('model_group','decision');assert.equal(api.getState().visible.runs,1);assert(api.matchesValue('model_group','decision'));
assert(api.matches(api.getState().eligibleRunIds));assert(!api.matches('absent'));
api.setValue('model_group',undefined);assert(api.matchesValue('model_group',undefined));assert.equal(api.getState().visible.runs,3);
document.getElementById('report-filters-reset').click();assert.equal(api.getState().visible.runs,12);
assert.equal(legacy.value,'');assert.equal(comparison.value,'');assert(api.matchesValue('prompt',undefined));
const detached=api.getState();detached.whole.positions=999;assert.equal(api.getState().whole.positions,36);
const prior=api.getState();assert.throws(()=>api.setFilters({model:'bad',repeat:id('repeat','2')}));assert.deepEqual(api.getState(),prior);
const n=events.length;dom.window.dispatchEvent(new dom.window.Event('report-filter-request'));assert.equal(events.length,n+1);
""")

    def test_dom_lifecycle_and_null_option_are_distinct_from_literal_values(self):
        self.dom(r"""
api.setValue('lifecycle','refused');assert.equal(api.getState().visible.runs,2);assert.equal(api.getState().visible.positions,6);
assert(api.getState().scopeRule.includes('every case'));api.reset();
api.setValue('provider',null);const missing=api.getState();assert.equal(missing.visible.runs,4);assert.equal(missing.selectedValues.provider,null);
api.setValue('provider','unavailable');const declared=api.getState();assert.equal(declared.visible.runs,4);
assert.notDeepEqual(missing.eligibleRunIds,declared.eligibleRunIds);assert.notEqual(missing.selectedFilters.provider,declared.selectedFilters.provider);
api.setValue('model_group','fine_tuned_llm');assert.equal(api.getState().visible.positions,0);assert.equal(api.getState().whole.positions,36);
assert(document.getElementById('report-filters-status').textContent.includes('0 / 12 planned runs'));
""")

    def test_dom_url_preserves_explorer_presentation_unknown_params_and_query_reset(self):
        token = option(self.data, "repeat", "1")
        url = f"file:///offline/report.html?experiment=private&rf_repeat={token}#presentation-heading?presentation=1&slide=fields&run=keep-run&compareRun=keep-b&case=case%20%23%3F&other=retained"
        self.dom(r"""
assert.equal(api.getState().visible.runs,6);assert.equal(api.getState().selectedValues.repeat,'1');
api.setValue('execution_route','clef_decide');let url=new URL(dom.window.location.href),p=new URLSearchParams(url.hash.split('?')[1]);
assert(url.hash.startsWith('#presentation-heading?'));assert.equal(p.get('run'),'keep-run');assert.equal(p.get('compareRun'),'keep-b');assert.equal(p.get('case'),'case #?');
assert.equal(p.get('presentation'),'1');assert.equal(p.get('slide'),'fields');assert.equal(p.get('other'),'retained');assert.equal(url.searchParams.get('experiment'),'private');
const fresh=new JSDOM(input.html,{runScripts:'dangerously',url:url.href});assert.equal(fresh.window.reportFilters.getState().visible.runs,2);
api.reset();p=new URLSearchParams(new URL(dom.window.location.href).hash.split('?')[1]);assert.equal(p.get('rf_repeat'),'');assert.equal(api.getState().visible.runs,12);
const reloaded=new JSDOM(input.html,{runScripts:'dangerously',url:dom.window.location.href});assert.equal(reloaded.window.reportFilters.getState().visible.runs,12);
dom.window.location.hash='case-explorer-heading?rf_repeat='+id('repeat','2')+'&case=retained';dom.window.dispatchEvent(new dom.window.PopStateEvent('popstate'));
assert.equal(api.getState().visible.runs,6);assert.equal(api.getState().selectedValues.repeat,'2');
""", url=url)

    def test_dom_unknown_inbound_filters_are_disclosed_and_not_invented(self):
        self.dom(r"""
assert.equal(api.getState().visible.runs,12);const notice=document.getElementById('report-filters-notice');
assert(!notice.hidden);assert(notice.textContent.includes('Requested provider'));assert(notice.textContent.includes('dimension is unapplied'));
api.setValue('repeat','2');assert(notice.hidden);assert.equal(api.getState().visible.runs,6);
""", url="file:///offline/report.html#case-explorer-heading?rf_provider=not-in-this-report&run=keep&extra=retained")

    def test_arbitrary_metadata_html_and_json_are_inert_and_selectable(self):
        attack = "</script><img src=x onerror=\"window.injected=1\"> & '?"
        task = {"name": attack, "input_keys": ["note"], "fields": [{"name": "decision", "labels": ["a", "b"]}]}
        plan = build_plan(task, {"configs": [{"id": attack, "model": attack, "settings": {"adapter": attack, "provider": attack, "output_interface": attack, "effort": attack, "route": attack}}],
                                 "prompts": [{"id": attack, "text": attack}], "repeats": 1, "batch_size": 1},
                          {"records": [{"id": attack, "input": {"note": attack}}]})
        analysis = build_analysis(task, plan, {"records": []}, operations=[{"request_id": plan["requests"][0]["request_id"], "state": attack}])
        html = render_report_filters(analysis)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;/script&gt;", html)
        self.assertIn("\\u003c/script\\u003e", html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("fetch(", html)
        self.dom(r"""
const attack=input.data.runs[0].values.model;assert.equal(document.querySelectorAll('img').length,0);assert.equal(dom.window.injected,undefined);
api.setValue('provider',attack);api.setValue('execution_route',attack);assert.equal(api.getState().visible.runs,1);
assert.equal(api.getState().selectedValues.provider,attack);assert([...document.querySelectorAll('#report-filter-model option')].some(option=>option.textContent===attack));
""", analysis=analysis)


_DOM_START = r"""
const fs=require('fs'),assert=require('assert'),{JSDOM,VirtualConsole}=require('jsdom');
const input=JSON.parse(fs.readFileSync(0,'utf8')),errors=[],events=[],vc=new VirtualConsole();
vc.on('jsdomError',error=>errors.push(error.message));
const dom=new JSDOM(input.html,{runScripts:'dangerously',url:input.url,virtualConsole:vc,beforeParse(window){window.addEventListener('report-filter-change',event=>events.push(event.detail));}});
const document=dom.window.document,api=dom.window.reportFilters;
const id=(key,value)=>input.data.options[key].find(option=>option.value===value).id;
(async()=>{
"""
_DOM_END = r"""
await new Promise(resolve=>dom.window.setTimeout(resolve,25));assert.deepEqual(errors,[]);
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
"""


if __name__ == "__main__":
    unittest.main()
