"""Literal case/input search and shared run scope, tested without rendering."""

import copy
import json
import shutil
import subprocess
import unittest

from classification_bench.core import build_plan
from classification_bench.report_analysis import build_analysis
from classification_bench.report_explorer import render_report_explorer
from classification_bench.report_findings import build_findings
from classification_bench.report_presentation import render_presentation


def fixture(configs=3):
    task = {"name": "Generic case search", "input_keys": ["message", "metadata"],
            "fields": [{"name": "queue", "labels": ["reference-only-label", "other"]}]}
    experiment = {"configs": [{"id": "config" + str(i), "model": "fixture"} for i in range(configs)],
                  "prompts": [{"id": "brief", "text": "Classify"}, {"id": "rules", "text": "Read rules"}],
                  "repeats": 2, "batch_size": 2}
    inputs = {"records": [
        {"id": "CASE-A", "input": {"message": "Invoice is late", "metadata": "billing"}},
        {"id": "CASE b", "input": {"message": 'A quoted "word" and slash \\ are literal.', "metadata": "support"}},
        {"id": "Кейс-é", "input": {"message": "Café review", "metadata": '{"region":"north","count":42}'}},
        {"id": "case#d", "input": {"message": "A pending export", "metadata": "transfer"}}]}
    predictions = {"records": []}
    for config in experiment["configs"]:
        for prompt in experiment["prompts"]:
            for repeat in (1, 2):
                for case in inputs["records"][:3]:
                    predictions["records"].append({"config_id": config["id"], "prompt_id": prompt["id"], "repeat": repeat,
                        "id": case["id"], "prediction": {"queue": "reference-only-label" if case["id"] != "CASE b" else "invalid"}})
    labels = {"records": [{"id": "CASE-A", "labels": {"queue": "reference-only-label"}},
                           {"id": "CASE b", "labels": {"queue": "other"}}]}
    analysis = build_analysis(task, build_plan(task, experiment, inputs), predictions, labels)
    # Standalone explorer projections support recursive structured input. The
    # engine's current inference capsules remain string-valued; do not change it.
    for run in analysis["runs"]:
        run["cases"][2]["input"] = {"message": "Café review", "context": {
            "nested": {"region": "north", "count": 42}, "tags": ["Renewal", True, None]}}
    return analysis


_DOM_START = r"""
const fs = require('fs'), assert = require('assert');
const {JSDOM, VirtualConsole} = require('jsdom');
const input = JSON.parse(fs.readFileSync(0, 'utf8')), errors = [];
function open(url = input.url) {
  const virtualConsole = new VirtualConsole(); virtualConsole.on('jsdomError', error => errors.push(error.message));
  return new JSDOM(input.html, {url,runScripts:'dangerously',virtualConsole,beforeParse(window) {
    window.HTMLElement.prototype.scrollIntoView = function() {};
    window.matchMedia = () => ({matches:false});
    if (input.initial_scope !== null) window.reportFilters = {getState:() => ({eligibleRunIds:input.initial_scope})};
    if (input.fallback_scope !== null) window.addEventListener('report-filter-request', () => window.dispatchEvent(new window.CustomEvent('report-filter-change', {detail:{eligibleRunIds:input.fallback_scope}})));
  }});
}
const dom = open(), document = dom.window.document;
const get = id => document.getElementById('explorer-' + id);
const rows = () => [...document.querySelectorAll('#explorer-case-table tbody tr')];
const visible = () => rows().filter(row => !row.hidden).map(row => row.dataset.caseId);
const params = () => new URLSearchParams(new URL(dom.window.location.href).hash.split('?').slice(1).join('?'));
function change(id, value) {get(id).value = value; get(id).dispatchEvent(new dom.window.Event('change', {bubbles:true}));}
function search(value) {get('case-search').value = value; get('case-search').dispatchEvent(new dom.window.Event('input', {bubbles:true}));}
function scope(ids) {dom.window.dispatchEvent(new dom.window.CustomEvent('report-filter-change', {detail:{eligibleRunIds:ids}}));}
"""


class ReportCaseSearchTests(unittest.TestCase):
    def dom_check(self, check, *, analysis=None, url="file:///offline/report.html", presentation=False,
                  initial_scope=None, fallback_scope=None):
        if not shutil.which("node"):
            self.skipTest("local Node.js unavailable")
        if subprocess.run(["node", "-e", "require.resolve('jsdom')"], capture_output=True).returncode:
            self.skipTest("local jsdom unavailable")
        analysis = analysis or fixture()
        before = copy.deepcopy(analysis)
        html = "<!doctype html><html><body><h2 id='deep-findings'>Findings</h2>" + render_report_explorer(analysis)
        if presentation:
            html += render_presentation(analysis, build_findings(analysis))
        html += "</body></html>"
        self.assertEqual(analysis, before)
        payload = {"html": html, "url": url, "runs": [run["run_id"] for run in analysis["runs"]],
                   "initial_scope": initial_scope, "fallback_scope": fallback_scope}
        script = _DOM_START + "\n(async () => {\n" + check + "\nassert.deepEqual(errors, []);\n})().catch(error => {console.error(error); process.exitCode = 1;});"
        result = subprocess.run(["node", "-e", script], input=json.dumps(payload), text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_case_ids_and_recursive_input_are_literal_case_insensitive(self):
        self.dom_check(r"""
assert(document.querySelector('label[for=explorer-case-search]'));
assert.equal(get('case-search').type, 'search');
for (const [query, expected] of [
  ['case b',['CASE b']], ['INVOICE',['CASE-A']], ['quoted "word"',['CASE b']], ['slash \\',['CASE b']],
  ['cafe\u0301',['Кейс-é']], ['REGION',['Кейс-é']], ['42',['Кейс-é']], ['true',['Кейс-é']],
  ['null',['Кейс-é']], ['renewal',['Кейс-é']], ['case#d',['case#d']], ['  billing  ',['CASE-A']]
]) {search(query); assert.deepEqual(visible(), expected, query);}
search('reference-only-label'); assert.deepEqual(visible(), []);
search('invalid'); assert.deepEqual(visible(), []);
search('[.*]'); assert.deepEqual(visible(), []); // literal text, never a regexp
""")

    def test_no_matches_keep_selected_detail_denominators_focus_and_reset(self):
        self.dom_check(r"""
const counts = get('counts').textContent, raw = get('raw').textContent;
get('case-search').focus(); search('support');
assert.deepEqual(visible(), ['CASE b']); assert.equal(get('case').value, 'CASE-A');
assert.equal(get('case').options.length, 4); assert(!get('detail').hidden);
assert(get('case-search-count').textContent.includes('1/4 planned cases shown'));
assert(get('case-search-count').textContent.includes('Selected case CASE-A is outside the search'));
assert.equal(get('counts').textContent, counts); assert.equal(get('raw').textContent, raw);
search('absent phrase'); await new Promise(resolve => setTimeout(resolve, 25));
assert.equal(document.activeElement, get('case-search'));
assert.equal(get('case').value, 'CASE-A'); assert.equal(rows().length, 4);
assert(get('case-search-count').textContent.includes('0/4 planned cases shown'));
assert(!get('case-search-empty').hidden); assert(!get('detail').hidden);
assert.equal(get('case-search-count').getAttribute('aria-live'), 'polite');
get('case-search-reset').click(); assert.equal(document.activeElement, get('case-search'));
assert.equal(get('case-search').value, ''); assert.equal(params().get('caseSearch'), '');
assert.equal(visible().length, 4); assert(get('case-search-empty').hidden);
assert(get('case-search-reset').disabled); assert.equal(get('counts').textContent, counts);
""")

    def test_search_url_reload_history_and_empty_override_preserve_other_state(self):
        analysis = fixture()
        a, b = [run["run_id"] for run in analysis["runs"][:2]]
        self.dom_check(r"""
assert.equal(get('case-search').value, 'café'); assert.deepEqual(visible(), ['Кейс-é']);
get('case-search').focus(); search('support');
assert.equal(params().get('caseSearch'), 'support'); assert.equal(params().get('run'), input.runs[0]);
assert.equal(params().get('compareRun'), input.runs[1]); assert.equal(params().get('case'), 'CASE-A');
assert.equal(params().get('presentation'), '0'); assert.equal(params().get('slide'), 'prompts');
assert.equal(params().get('reveal'), '1'); assert.equal(params().get('finding'), 'kept');
assert.equal(params().get('rf_model'), 'opaque'); assert.equal(params().get('other'), 'keep');
assert.equal(new URL(dom.window.location.href).searchParams.get('experiment'), 'private');
const restored = open(get('permalink').href);
assert.equal(restored.window.document.getElementById('explorer-case-search').value, 'support');
assert.equal(restored.window.document.getElementById('explorer-case').value, 'CASE-A');
get('case-search-reset').click();
const cleared = open(dom.window.location.href);
assert.equal(cleared.window.document.getElementById('explorer-case-search').value, '');
assert.equal([...cleared.window.document.querySelectorAll('#explorer-case-table tbody tr')].filter(row => !row.hidden).length, 4);
dom.reconfigure({url:'file:///offline/report.html#case-explorer-heading?caseSearch=invoice&case=CASE%20b'});
dom.window.dispatchEvent(new dom.window.PopStateEvent('popstate'));
assert.equal(get('case-search').value, 'invoice'); assert.equal(get('case').value, 'CASE b');
assert(get('case-search-count').textContent.includes('Selected case CASE b is outside the search'));
""", analysis=analysis, url=f"file:///offline/report.html?experiment=private&caseSearch=query-fallback#presentation-heading?run={a}&compareRun={b}&case=CASE-A&caseSearch=caf%C3%A9&presentation=0&slide=prompts&reveal=1&finding=kept&rf_model=opaque&other=keep")

    def test_evidence_and_presentation_keep_search_and_exact_case_selection(self):
        self.dom_check(r"""
search('invoice'); const counts = get('counts').textContent;
dom.window.dispatchEvent(new dom.window.CustomEvent('report-explorer-select', {detail:{run:input.runs[1],compareRun:input.runs[0],case:'CASE b'}}));
assert.equal(get('case-search').value, 'invoice'); assert.equal(params().get('caseSearch'), 'invoice');
assert.equal(get('case').value, 'CASE b'); assert(get('case-search-count').textContent.includes('outside the search'));
assert(get('input').textContent.includes('quoted'));
document.getElementById('presentation-start').click();
const slide = document.getElementById('presentation-slide-select'); slide.value = 'finding'; slide.dispatchEvent(new dom.window.Event('change',{bubbles:true}));
const link = document.querySelector('#presentation-finding-detail .presentation-case-links a'); assert(link);
const target = new URLSearchParams(new URL(link.href).hash.split('?')[1]); link.click();
assert.equal(params().get('caseSearch'), 'invoice'); assert.equal(get('case-search').value, 'invoice');
assert.equal(get('run').value, target.get('run')); assert.equal(get('case').value, target.get('case'));
assert.equal(document.activeElement, get('case-heading'));
assert(!document.getElementById('report-presentation').classList.contains('presentation-active'));
assert.equal(rows().length, 4); assert(get('counts').textContent.includes('4 planned'));
""", presentation=True)

    def test_shared_run_scope_filters_both_runs_and_preserves_exact_selected_pair(self):
        self.dom_check(r"""
scope([input.runs[2], input.runs[3]]);
assert.equal(get('run').value, input.runs[0]);
assert(![...get('run').options].find(option => option.value === input.runs[0]).hidden);
assert([...get('run').options].find(option => option.value === input.runs[4]).hidden);
assert([...get('run').options].find(option => option.value === input.runs[4]).disabled);
assert(get('filter-scope').textContent.includes('2/12 planned runs'));
assert(get('filter-scope').textContent.includes('Selected run A lies outside'));
assert(get('counts').textContent.includes('4 planned'));
assert(get('prompts').textContent.includes('No paired prompt conditions match'));
assert(get('prompt-page-status').textContent.includes('6 paired prompt conditions available in the full report'));
change('agreement-scope', 'all');
assert.equal(document.querySelectorAll('#explorer-agreement-table tbody tr').length, 1);
assert(get('agreement-page-status').textContent.includes('1/66 pairs satisfy both-run report filters'));
change('compare', input.runs[2]);
let agreement = [...document.querySelectorAll('#explorer-agreement-table tbody tr')];
assert.equal(agreement.length, 2); assert(agreement[0].textContent.includes('outside report filters'));
assert(get('agreement-page-status').textContent.includes('1 exact selected pair(s) retained outside scope'));
const prompt = document.querySelector('#explorer-prompt-table tbody tr');
assert(prompt.textContent.includes('Exact selected pair outside report filters'));
assert(get('prompt-page-status').textContent.includes('0/6 pairs satisfy both-run report filters'));
const saved = get('counts').textContent; scope([]);
assert.equal(get('run').value, input.runs[0]); assert.equal(get('compare').value, input.runs[2]);
assert.equal(get('counts').textContent, saved); assert(get('filter-scope').textContent.includes('run A and run B'));
assert.equal(document.querySelectorAll('#explorer-agreement-table tbody tr').length, 1);
assert(document.querySelector('#explorer-agreement-table tbody tr').textContent.includes('outside report filters'));
scope(input.runs); assert(get('filter-scope').hidden);
assert.equal(document.querySelectorAll('#explorer-agreement-table tbody tr').length, 12);
""")

    def test_filter_pagination_resets_only_on_a_changed_scope_and_keeps_full_totals(self):
        self.dom_check(r"""
change('agreement-scope', 'all'); get('agreement-next').click(); get('prompt-next').click();
assert.equal(get('agreement-page').value, '2'); assert.equal(get('prompt-page').value, '2');
scope(input.runs.slice(0,28)); assert.equal(get('agreement-page').value, '1'); assert.equal(get('prompt-page').value, '1');
assert(get('agreement-page-status').textContent.includes('378/780 pairs satisfy both-run report filters'));
assert(get('prompt-page-status').textContent.includes('14/20 pairs satisfy both-run report filters'));
get('agreement-next').click(); get('prompt-next').click();
scope(input.runs.slice(0,28).reverse()); assert.equal(get('agreement-page').value, '2'); assert.equal(get('prompt-page').value, '2');
change('case', 'CASE b'); assert.equal(get('agreement-page').value, '2'); assert.equal(get('prompt-page').value, '2');
scope(input.runs.slice(0,4)); assert.equal(get('agreement-page').value, '1'); assert.equal(get('prompt-page').value, '1');
assert(get('agreement-page-status').textContent.includes('6/780 pairs satisfy both-run report filters'));
assert(get('prompt-page-status').textContent.includes('2/20 pairs satisfy both-run report filters'));
assert(get('counts').textContent.includes('4 planned'));
""", analysis=fixture(configs=10))

    def test_initial_filter_snapshot_request_and_malformed_events(self):
        analysis = fixture()
        ids = [run["run_id"] for run in analysis["runs"][2:4]]
        check = r"""
assert(get('filter-scope').textContent.includes('2/12 planned runs'));
const before = get('filter-scope').textContent, pairs = get('agreement-page-status').textContent;
for (const detail of [undefined,{}, {eligibleRunIds:'bad'}, {eligibleRunIds:[null]}, {eligibleRunIds:[1]}]) dom.window.dispatchEvent(new dom.window.CustomEvent('report-filter-change',{detail}));
assert.equal(get('filter-scope').textContent, before); assert.equal(get('agreement-page-status').textContent, pairs);
scope([input.runs[2], input.runs[2], 'not-a-frozen-run']);
assert(get('filter-scope').textContent.includes('1/12 planned runs'));
assert.equal(get('run').value, input.runs[0]);
"""
        self.dom_check(check, analysis=analysis, initial_scope=ids)
        self.dom_check(check, analysis=analysis, fallback_scope=ids)

    def test_hostile_text_is_inert_and_missing_unlabeled_cases_stay_planned(self):
        analysis = fixture()
        attack = '</script><img src=x onerror="window.searchPwned=1">'
        for run in analysis["runs"]:
            run["cases"][3]["input"]["message"] = attack
            run["counts"].update(full_reference=0, no_reference=4, exact_correct=None)
            for case in run["cases"]:
                case.update(reference=None, reference_status="missing", exact_match=None, field_matches={"queue":None})
        self.dom_check(r"""
const before = get('counts').textContent;
search('</script><img'); assert.deepEqual(visible(), ['case#d']);
change('case', 'case#d'); assert(get('case-status').textContent.includes('missing'));
assert(get('case-status').textContent.includes('Reference: Unknown'));
assert(get('input').textContent.includes('<img')); assert.equal(document.querySelectorAll('img').length, 0);
assert.equal(dom.window.searchPwned, undefined);
search('<img src=x onerror="window.searchPwned=1">');
assert.deepEqual(visible(), ['case#d']); assert.equal(get('counts').textContent, before);
assert(get('counts').textContent.includes('quality is unavailable')); assert(!get('counts').textContent.includes('Exact matches:'));
assert.equal(rows().length, 4); assert.equal(get('case').options.length, 4);
""", analysis=analysis)


if __name__ == "__main__":
    unittest.main()
