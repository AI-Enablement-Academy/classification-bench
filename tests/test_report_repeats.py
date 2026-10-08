"""Hand-counted repeat changes, provenance and offline interaction checks."""

from copy import deepcopy
import json
import shutil
import subprocess
import unittest
from urllib.parse import parse_qs, urlsplit

from classification_bench.core import ValidationError, _digest, build_plan, evaluate
from classification_bench.report_analysis import build_analysis
from classification_bench.report_repeats import (build_repeat_analysis, build_repeat_findings,
                                                  render_repeat_analysis, repeat_case_details)


def fixture(*, repeats=3, labels=True, synthetic=False, cases=4):
    task = {"name": "Parcel decisions", "input_keys": ["note"], "fields": [
        {"name": "queue / α", "labels": ["hold", "ship"]},
        {"name": "priority?", "labels": ["ordinary", "urgent"]}]}
    experiment = {"configs": [{"id": "route? α", "model": "fixture/model", "settings": {"adapter": "synthetic" if synthetic else "unsupported"}}],
                  "prompts": [{"id": "SOP & examples", "text": "Use the parcel rubric."}], "repeats": repeats, "batch_size": 1}
    ids = ["case / α", "case ? b", "case-c", "case-d", *[f"case-{i}" for i in range(4,cases)]][:cases]
    inputs = {"records": [{"id": cid, "input": {"note": cid}} for cid in ids]}
    plan = build_plan(task, experiment, inputs)
    rows = [("hold","urgent"),("ship","ordinary"),("hold","ordinary"),("ship","ordinary")]
    references = {"records": [{"id": cid, "labels": dict(zip(("queue / α", "priority?"),rows[i%4]))} for i,cid in enumerate(ids)]} if labels else None
    values = [[("hold","urgent"),("ship","ordinary"),("outside","ordinary"),None],
              [("ship","urgent"),("ship","urgent"),("hold","ordinary"),None],
              [("hold","ordinary"),None,("hold","outside"),("ship","ordinary")]]
    predictions = {"records": []}
    for repeat in range(1,repeats+1):
        for i,cid in enumerate(ids):
            value = values[(repeat-1)%3][i] if i<4 else rows[i%4]
            if value is not None:
                predictions["records"].append({"config_id": "route? α", "prompt_id": "SOP & examples", "repeat": repeat,
                                               "id": cid, "prediction": dict(zip(("queue / α", "priority?"),value))})
    operations = []
    for request in plan["requests"]:
        cid, repeat = request["items"][0]["id"], request["repeat"]
        state, reason = ("finished","outside vocabulary") if cid=="case-c" and repeat==1 else ("outcome_unknown","network interrupted") if cid=="case-d" and repeat==1 else ("refused","saved refusal") if cid=="case-d" and repeat==2 else ("ready",None) if cid=="case ? b" and repeat==3 else ("finished",None)
        operations.append({"request_id": request["request_id"], "state": state, "reason": reason,
                           "receipt_sha256": _digest(request["request_id"]), "parsed_status": "invalid" if reason=="outside vocabulary" else None})
    analysis = build_analysis(task,plan,predictions,references,operations)
    return analysis, task, plan, predictions, references, operations


class RepeatReportTests(unittest.TestCase):
    def setUp(self):
        self.analysis, self.task, self.plan, self.predictions, self.labels, self.operations = fixture()
        self.data = build_repeat_analysis(self.analysis)

    def test_manual_pair_counts_per_field_validity_and_ranges_match_evaluator(self):
        first, second, third = self.data["pairs"]
        self.assertEqual((first["planned"],first["comparable"],first["changed"],first["excluded"],first["flip_rate"]),(4,2,2,2,1))
        for name in self.data["fields"]:
            self.assertEqual((first["fields"][name]["flips"],first["fields"][name]["flip_rate"]),(1,.5))
            self.assertEqual(first["fields"][name]["excluded_ids"],["case-c","case-d"])
        self.assertEqual(second["fields"]["queue / α"]["flip_rate"],0)
        self.assertEqual(second["fields"]["priority?"]["flip_rate"],1)
        self.assertEqual((third["comparable"],third["excluded"]),(1,3))
        condition = self.data["conditions"][0]
        self.assertEqual(condition["full_denominator_exact_rate_range"],[.25,.5])
        self.assertEqual(condition["validity_rate_range"],[.5,.75])
        self.assertEqual(condition["fields"]["priority?"]["full_denominator_agreement_range"],[.25,.5])
        evaluated = evaluate(self.task,self.plan,self.labels,self.predictions)
        for projected, original in zip(self.data["pairs"],evaluated["conditions"][0]["repeat_comparisons"]):
            self.assertEqual(projected["changed"],original["flips"])
            self.assertEqual(projected["comparable"],original["comparable"])
            self.assertEqual(projected["fields"],original["fields"])

    def test_exact_case_reasons_and_arbitrary_evidence_urls(self):
        first = self.data["pairs"][0]
        excluded = repeat_case_details(self.data,first["pair_id"],outcome="excluded")
        self.assertEqual([row["case_id"] for row in excluded],["case-c","case-d"])
        self.assertIn("A invalid; B valid",excluded[0]["reason"])
        self.assertEqual(excluded[0]["a"]["reason"],"outside vocabulary")
        self.assertEqual(excluded[1]["a"]["lifecycle_state"],"outcome_unknown")
        self.assertEqual(excluded[1]["b"]["lifecycle_state"],"refused")
        field = repeat_case_details(self.data,first["pair_id"],field="priority?",outcome="changed")
        self.assertEqual([row["case_id"] for row in field],["case ? b"])
        params = parse_qs(urlsplit(field[0]["evidence_url"]).fragment.split("?",1)[1])
        self.assertEqual(params,{"run":[first["run_a"]],"compareRun":[first["run_b"]],"case":["case ? b"]})
        self.assertEqual(field[0]["a"]["evidence"]["receipt_sha256"],self.analysis["runs"][0]["cases"][1]["evidence"]["receipt_sha256"])
        for kwargs in ({"field":"unknown"},{"outcome":"unknown"}):
            with self.assertRaises(ValidationError):repeat_case_details(self.data,first["pair_id"],**kwargs)

    def test_partial_unlabeled_and_zero_comparable_do_not_invent_scores(self):
        partial = {"records":[{"id":"case / α","labels":{"queue / α":"hold"}},self.labels["records"][1]]}
        for references in (partial,None):
            analysis = build_analysis(self.task,self.plan,self.predictions,references,self.operations)
            data = build_repeat_analysis(analysis)
            self.assertEqual([pair["flip_rate"] for pair in data["pairs"]],[1,1,1])
            self.assertIsNone(data["conditions"][0]["full_denominator_exact_rate_range"])
            self.assertTrue(all(field["full_denominator_agreement_range"] is None for field in data["conditions"][0]["fields"].values()))
        absent = build_repeat_analysis(build_analysis(self.task,self.plan,{"records":[]}))
        self.assertTrue(all(pair["flip_rate"] is None and pair["excluded"]==4 for pair in absent["pairs"]))
        self.assertIsNone(absent["conditions"][0]["known_reference_exact_rate_range"])
        self.assertIn("3/3 pairs lack comparable predictions",build_repeat_findings(absent)[0]["observation"])

    def test_origin_declarations_are_explicit_bound_and_subset_scoped(self):
        second = self.analysis["runs"][1]["run_id"]
        declarations = [{"run_id":second,"origin":"replay","source":"immutable replay manifest v2"}]
        data = build_repeat_analysis(self.analysis,origin_declarations=declarations)
        self.assertEqual(data["origin_declarations_sha256"],_digest(declarations))
        self.assertNotEqual(data["repeat_analysis_id"],self.data["repeat_analysis_id"])
        self.assertEqual(data["source_hashes"],self.data["source_hashes"])
        self.assertTrue(all(pair["separately_planned_requests"] for pair in data["pairs"]))
        self.assertTrue(all(run["dispatch_origin"]=="not established by this analysis" for run in data["runs"].values()))
        finding = build_repeat_findings(data)[0]
        self.assertIn("replay from immutable replay manifest v2",finding["observation"])
        self.assertEqual(finding["metrics"]["origin_declarations"], [{"run_id":second,**data["runs"][second]["origin_declarations"][0]}])
        cohort = [{"id":"subset","title":"Imported subset","origin":"imported","source":"archive manifest","run_ids":[second],"case_ids":["case ? b"],"one_run_per_configuration":True}]
        scoped = build_repeat_analysis(build_analysis(self.task,self.plan,self.predictions,self.labels,self.operations,cohort_declarations=cohort))
        entry = scoped["runs"][second]["origin_declarations"][0]
        self.assertEqual(entry["declaration_scope"],"declared cohort cases only")
        self.assertEqual(entry["case_ids"],["case ? b"])
        self.assertIn("1/4 declared cases",build_repeat_findings(scoped)[0]["observation"])

    def test_findings_are_source_bound_explain_fields_and_link_boundaries(self):
        finding = build_repeat_findings(self.data)[0]
        self.assertIn("priority?: flip rates 50.0% to 100.0%",finding["observation"])
        self.assertIn("Excluded cases range from 2 to 3 of 4",finding["observation"])
        self.assertEqual(finding["denominator"],4)
        self.assertEqual(finding["source_hashes"],self.analysis["source_hashes"])
        self.assertEqual(len(finding["supporting_links"]),6)
        field_links = [link for link in finding["supporting_links"] if "priority?" in link["label"]]
        self.assertEqual(field_links[0]["case_id"],"case ? b")
        self.assertEqual(field_links[1]["case_id"],"case / α")
        self.assertIn("do not pool overlapping pairs",finding["next_step"])
        self.assertEqual(build_repeat_findings(self.data),build_repeat_findings(self.data))

    def test_single_repeat_and_synthetic_are_honest(self):
        analysis,*_ = fixture(repeats=1,synthetic=True)
        data = build_repeat_analysis(analysis)
        self.assertEqual(data["pairs"],[])
        self.assertEqual(data["whole"]["runs"],1)
        self.assertEqual(data["conditions"][0]["full_denominator_exact_rate_range"],[.5,.5])
        finding = build_repeat_findings(data)[0]
        self.assertIn("No repeat pair is available",finding["observation"])
        self.assertIn("Synthetic outputs describe pipeline behavior",finding["observation"])
        self.assertEqual(len(finding["supporting_links"]),1)
        self.assertNotIn("run_b",finding["supporting_links"][0])

    def test_determinism_immutability_invalid_origins_and_static_fallback(self):
        before = deepcopy(self.analysis)
        self.assertEqual(self.data,build_repeat_analysis(self.analysis))
        self.assertEqual(self.data["repeat_analysis_id"],_digest({key:value for key,value in self.data.items() if key!="repeat_analysis_id"}))
        repeat_case_details(self.data,self.data["pairs"][0]["pair_id"])[0]["a"]["evidence"]["receipt_sha256"]="edited"
        self.assertEqual(self.analysis,before)
        for declarations in ({},[{"run_id":{},"origin":"replay","source":"s"}],[{"run_id":self.analysis["runs"][0]["run_id"],"origin":[],"source":"s"}],[{"run_id":"unknown","origin":"replay","source":"s"}]):
            with self.assertRaises(ValidationError):build_repeat_analysis(self.analysis,origin_declarations=declarations)
        html = render_repeat_analysis(self.data)
        static = html.split("<script type='application/json'")[0]
        self.assertIn("queue / α",static);self.assertIn("1/2 (50.0%)",static)
        self.assertIn("outside vocabulary",static);self.assertIn("network interrupted",static)
        self.assertIn("role='region'",static);self.assertIn("prefers-reduced-motion",html)
        self.assertNotIn("https://",html)

    def dom(self,check,*,data=None,url="file:///report.html#repeat-analysis-heading?keep=yes",setup="",full_html=None):
        if not shutil.which("node") or subprocess.run(["node","-e","require.resolve('jsdom')"],capture_output=True).returncode:
            self.skipTest("local Node.js/jsdom unavailable")
        payload = {"html":full_html or render_repeat_analysis(data or self.data),"url":url,"data":data or self.data}
        script = r"""
const assert=require('assert'),{JSDOM,VirtualConsole}=require('jsdom'),input=JSON.parse(require('fs').readFileSync(0,'utf8'));
(async()=>{const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(input.html,{runScripts:'dangerously',url:input.url,virtualConsole:vc,beforeParse(w){SETUP}}),w=dom.window,d=w.document;
const el=id=>d.getElementById('repeat-'+id),event=ids=>w.dispatchEvent(new w.CustomEvent('report-filter-change',{detail:{eligibleRunIds:ids}})),pause=()=>new Promise(r=>setTimeout(r,100));
CHECK
assert.deepEqual(errors,[]);w.close();})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
""".replace("SETUP",setup).replace("CHECK",check)
        result = subprocess.run(["node","-e",script],input=json.dumps(payload),text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr[-8000:])

    def test_dom_fields_exclusions_exact_links_keep_latest_filter_search_and_focus(self):
        self.dom(r"""
assert.equal(el('pair-body').rows.length,3);el('pair-body').rows[0].querySelector('button').click();
assert.equal(d.activeElement.id,'repeat-detail-heading');assert.equal(el('field-body').rows.length,3);
el('case-field').value='priority?';el('case-outcome').value='changed';el('case-field').dispatchEvent(new w.Event('change'));
assert.equal(el('case-body').rows.length,1);assert.equal(el('case-body').rows[0].dataset.caseId,'case ? b');
el('case-outcome').value='excluded';el('case-outcome').dispatchEvent(new w.Event('change'));
assert(el('case-body').textContent.includes('outside vocabulary'));assert(el('case-body').textContent.includes('outcome_unknown'));
const url=new w.URL(w.location.href),params=new w.URLSearchParams(url.hash.split('?')[1]);params.set('caseSearch','latest search');params.set('rf_prompt','opaque');url.hash='repeat-analysis-heading?'+params;w.location.hash=url.hash;await pause();
el('case-body').rows[1].querySelector('a').click();await pause();const after=new w.URLSearchParams(w.location.hash.split('?')[1]);
assert.equal(after.get('caseSearch'),'latest search');assert.equal(after.get('rf_prompt'),'opaque');assert.equal(after.get('keep'),'yes');assert.equal(after.get('case'),'case-d');assert.equal(after.get('compareRun'),input.data.pairs[0].run_b);
""")

    def test_dom_shared_scope_requires_both_runs_and_retains_selected_exception(self):
        self.dom(r"""
const runs=Object.keys(input.data.runs),pair=input.data.pairs[0];event([runs[0]]);assert.equal(el('pair-body').rows.length,0);assert(el('pair-status').textContent.includes('0/3'));
event([runs[0],runs[1]]);assert.equal(el('pair-body').rows.length,1);el('pair-body').rows[0].querySelector('button').click();
event([runs[2]]);assert.equal(el('pair-body').rows.length,1);assert.equal(el('pair-body').rows[0].dataset.pairId,pair.pair_id);
assert(el('pair-status').textContent.includes('retained outside scope'));assert(el('detail-scope').textContent.includes('4 planned cases; 2 comparable, 2 excluded'));
assert(el('range-body').textContent.includes('25.0% to 50.0%'));assert(el('range-body').textContent.includes('1/3 runs match filters'));
el('pair-clear').click();assert.equal(el('pair-body').rows.length,0);assert.equal(new w.URLSearchParams(w.location.hash.split('?')[1]).get('compareRun'),'');
el('pair-scope').value='all';el('pair-scope').dispatchEvent(new w.Event('change'));assert.equal(el('pair-body').rows.length,3);
""")

    def test_dom_initial_snapshot_history_pagination_and_same_case_stability(self):
        large,*_ = fixture(repeats=7,cases=18)
        data = build_repeat_analysis(large)
        self.dom(r"""
assert.equal(el('pair-body').rows.length,12);assert(el('pair-status').textContent.includes('21/21'));el('pair-next').click();assert(el('pair-status').textContent.includes('Page 2/2'));
event(Object.keys(input.data.runs));assert(el('pair-status').textContent.includes('Page 2/2'));
event(Object.keys(input.data.runs).slice(0,6));assert(el('pair-status').textContent.includes('15/21'));assert(el('pair-status').textContent.includes('Page 1/2'));
el('pair-next').click();event(Object.keys(input.data.runs).slice(0,6).reverse());assert(el('pair-status').textContent.includes('Page 2/2'));
el('pair-body').rows[0].querySelector('button').click();el('case-next').click();assert(el('case-status').textContent.includes('page 2/2'));
const pair=input.data.pairs.find(p=>p.pair_id===el('pair-body').rows[0].dataset.pairId);w.dispatchEvent(new w.CustomEvent('report-explorer-change',{detail:{run:pair.run_a,compareRun:pair.run_b,case:'case-17'}}));
assert(el('case-status').textContent.includes('page 2/2'));assert(el('pair-status').textContent.includes('Page 2/2'));
const reload=new JSDOM(dom.serialize(),{runScripts:'dangerously',url:w.location.href,virtualConsole:vc});assert.equal(reload.window.document.getElementById('repeat-pair-detail').hidden,false);reload.window.close();
""",data=data)
        self.dom("assert.equal(el('pair-body').rows.length,1);assert(el('pair-status').textContent.includes('1/3'));",
                 setup="w.reportFilters={getState:()=>({eligibleRunIds:"+json.dumps([self.data["pairs"][0]["run_a"],self.data["pairs"][0]["run_b"]])+"})};")

    def test_dom_arbitrary_text_is_inert_and_zero_pair_view_is_readable(self):
        modified = deepcopy(self.data)
        marker = "</script><img src=x onerror=window.injected=1>"
        modified["task_name"]=marker
        modified["runs"][self.data["pairs"][0]["run_a"]]["cases"][0]["reason"]=marker
        self.dom("assert.equal(w.injected,undefined);assert.equal(d.querySelector('img'),null);assert(el('case-body').textContent.includes('</script>'));",data=modified)
        single,*_ = fixture(repeats=1)
        self.dom("assert.equal(el('pair-body').rows.length,0);assert.equal(el('pair-detail').hidden,true);assert.equal(el('range-body').rows.length,1);assert.equal(el('pair-next').disabled,true);",data=build_repeat_analysis(single))

    def test_generated_report_and_presentation_share_origin_findings_and_evidence(self):
        from classification_bench.report import generate_report
        origins=[{"run_id":self.analysis["runs"][1]["run_id"],"origin":"replay","source":"offline replay source v7"}]
        html=generate_report(self.task,self.plan,self.labels,self.predictions,self.operations,repeat_origins=origins)
        self.dom(r"""
const findings=JSON.parse(d.getElementById('presentation-data').textContent).findings.filter(f=>f.kind==='repeat_analysis_summary');
assert.equal(findings.length,1);assert(findings[0].observation.includes('offline replay source v7'));assert(findings[0].observation.includes('priority?: flip rates'));
assert(d.querySelector('.deep-findings').textContent.includes('offline replay source v7'));assert.equal(el('pair-body').rows.length,3);
const chosen=d.getElementById('presentation-finding-select');chosen.value=findings[0].finding_id;chosen.dispatchEvent(new w.Event('change'));
assert(d.getElementById('presentation-finding-detail').textContent.includes('offline replay source v7'));
el('pair-body').rows[0].querySelector('button').click();const pair=input.data.pairs[0];assert.equal(d.getElementById('explorer-run').value,pair.run_a);assert.equal(d.getElementById('explorer-compare').value,pair.run_b);
""",full_html=html)


if __name__ == "__main__":
    unittest.main()
