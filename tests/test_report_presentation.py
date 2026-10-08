"""Offline source/DOM behavior; these checks do not render private artifacts."""

import copy
import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser

from classification_bench.core import build_plan
from classification_bench.report_analysis import build_analysis
from classification_bench.report_explorer import render_report_explorer
from classification_bench.report_findings import build_findings
from classification_bench.report_metrics import build_field_metrics
from classification_bench.report_presentation import render_presentation
from classification_bench.report_sensitivity import build_sensitivity


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


_DOM_START = r"""
const fs = require('fs'), assert = require('assert');
const {JSDOM, VirtualConsole} = require('jsdom');
const input = JSON.parse(fs.readFileSync(0, 'utf8')), errors = [];
function open(url = input.url, scripts = true) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error.message));
  return new JSDOM(input.html, {runScripts:scripts ? 'dangerously' : undefined, url, virtualConsole,
    beforeParse(window) {
      window.presentationScrolls = [];
      window.HTMLElement.prototype.scrollIntoView = function(options) {window.presentationScrolls.push({id:this.id, options});};
      window.matchMedia = () => ({matches:input.reduced_motion});
    }
  });
}
const dom = open(), document = dom.window.document;
const get = id => document.getElementById('presentation-' + id);
const root = document.getElementById('report-presentation');
const params = () => new URLSearchParams(new URL(dom.window.location.href).hash.split('?').slice(1).join('?'));
function change(id, value) {get(id).value = value; get(id).dispatchEvent(new dom.window.Event('change', {bubbles:true}));}
function key(target, value, options = {}) {const event = new dom.window.KeyboardEvent('keydown', {key:value,bubbles:true,cancelable:true,...options}); target.dispatchEvent(event); return event;}
"""


class ReportPresentationTests(unittest.TestCase):
    def setUp(self):
        self.task = {"name": "Task with arbitrary fields", "input_keys": ["message"],
                     "fields": [{"name": "queue", "labels": ["north", "south"]},
                                {"name": "priority", "labels": ["low", "high"]}]}
        experiment = {"configs": [{"id": "model-group", "model": "fixture/model"}],
                      "prompts": [{"id": "brief", "text": "Classify"}, {"id": "rules", "text": "Read rules"}],
                      "batch_size": 1, "repeats": 2}
        self.inputs = {"records": [{"id": cid, "input": {"message": cid}} for cid in ("case:a", "case b", "case#c")]}
        self.plan = build_plan(self.task, experiment, self.inputs)
        self.labels = {"records": [{"id": "case:a", "labels": {"queue": "north", "priority": "low"}},
                                   {"id": "case b", "labels": {"queue": "north"}}]}
        self.predictions = {"records": []}
        for prompt in ("brief", "rules"):
            for repeat in (1, 2):
                for cid in ("case:a", "case b"):
                    self.predictions["records"].append({"config_id": "model-group", "prompt_id": prompt,
                        "repeat": repeat, "id": cid, "prediction": {
                            "queue": "invalid" if cid == "case b" and prompt == "brief" else "south" if cid == "case:a" and prompt == "brief" else "north",
                            "priority": "low"}})
        self.analysis = build_analysis(self.task, self.plan, self.predictions, self.labels)
        self.findings = build_findings(self.analysis)

    def html(self, analysis=None, findings=None, **kwargs):
        analysis = analysis or self.analysis
        return render_presentation(analysis, findings or build_findings(analysis), **kwargs)

    def dom_check(self, check, *, url="file:///offline/report.html", analysis=None, findings=None,
                  reduced_motion=False, **kwargs):
        if not shutil.which("node"):
            self.skipTest("local Node.js unavailable")
        available = subprocess.run(["node", "-e", "require.resolve('jsdom')"], capture_output=True, text=True)
        if available.returncode:
            self.skipTest("local jsdom unavailable")
        analysis = analysis or self.analysis
        html = ("<!doctype html><html><body><button id='outside-button'>Outside</button><main>"
                "<h2 id='deep-findings'>Full findings</h2><h2 id='downloads-heading'>Downloads</h2>"
                "<h2 id='reference-sensitivity'>Sensitivity</h2>" + render_report_explorer(analysis) +
                self.html(analysis, findings, **kwargs) + "</main><aside id='already-inert' inert>Already inert</aside></body></html>")
        payload = {"html": html, "url": url, "reduced_motion": reduced_motion,
                   "runs": [run["run_id"] for run in analysis["runs"]],
                   "findings": (findings or build_findings(analysis))["findings"]}
        script = _DOM_START + "\n(async () => {\n" + check + "\nassert.deepEqual(errors, []);\n})().catch(error => {console.error(error); process.exitCode = 1;});"
        result = subprocess.run(["node", "-e", script], input=json.dumps(payload), text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_deterministic_same_sources_no_mutation_and_bounded_slides(self):
        before = copy.deepcopy((self.analysis, self.findings))
        html = self.html()
        self.assertEqual(html, self.html())
        self.assertEqual((self.analysis, self.findings), before)
        parser = Tags()
        parser.feed(html)
        slides = [attrs for tag, attrs in parser.tags if "data-presentation-slide" in attrs]
        self.assertEqual([slide["data-presentation-slide"] for slide in slides],
                         ["scope", "overview", "outputs", "fields", "prompts", "repeats", "agreement", "cost", "sensitivity", "finding", "limits"])
        self.assertTrue(all("hidden" not in slide for slide in slides))
        self.assertEqual(sum("data-finding-id" in attrs for tag, attrs in parser.tags), 1)
        self.assertIn("6<span> / 12", html)
        self.assertIn("2 invalid and 4 missing", html)
        self.assertIn("Source hashes and scope", html)
        self.assertIn(self.analysis["analysis_id"], html)
        self.assertNotIn("fetch(", html)
        self.assertNotIn("innerHTML", html)
        self.assertNotIn("<script src=", html)

    def test_unlabeled_and_partial_states_are_readable_without_js(self):
        unlabeled = build_analysis(self.task, self.plan, self.predictions)
        html = self.html(unlabeled)
        self.assertIn("No field reference checks are available", html)
        self.assertIn("Accuracy is unavailable", html)
        self.assertIn("No hypothetical reference scenario is supplied", html)
        self.assertIn("No observed USD charge", html)
        self.assertIn("12 planned run-case positions", html)
        self.dom_check(r"""
const noJS = open(input.url, false);
const slides = [...noJS.window.document.querySelectorAll('[data-presentation-slide]')];
assert.equal(slides.length, 11); assert(slides.every(slide => !slide.hidden));
assert([...noJS.window.document.querySelectorAll('[data-presentation-reveal]')].every(node => !node.hidden));
assert(noJS.window.document.getElementById('presentation-finding-detail').textContent.includes('Scope:'));
""", analysis=unlabeled)

    def test_source_projection_mismatches_fail(self):
        for malformed in (None, [], {}, {"schema_version": 2}):
            with self.assertRaisesRegex(ValueError, "analysis schema version 1"):
                render_presentation(malformed, self.findings)
        wrong = copy.deepcopy(self.findings)
        wrong["analysis_id"] = "another-analysis"
        with self.assertRaisesRegex(ValueError, "same analysis"):
            self.html(findings=wrong)
        wrong = copy.deepcopy(self.findings)
        wrong["findings"][0]["source_hashes"]["labels"] = "other"
        with self.assertRaisesRegex(ValueError, "finding sources"):
            self.html(findings=wrong)
        metrics = build_field_metrics(self.analysis)
        metrics["source_hashes"]["predictions"] = "other"
        with self.assertRaisesRegex(ValueError, "field metrics sources"):
            self.html(field_metrics=metrics)

    def test_story_cost_unknowns_shared_errors_and_exact_ids(self):
        html = self.html(field_metrics=build_field_metrics(self.analysis))
        self.assertIn("Agreement can accept a shared error", html)
        self.assertIn("Accepted unknown", html)
        self.assertIn("Deferred", html)
        self.assertIn("Unknown charges are unavailable", html)
        self.assertIn("0/4 planned runs have complete observed USD coverage", html)
        self.assertIn("Class metrics use the same shared report projection", html)
        self.assertIn("Precision", html)
        self.assertIn("Recall", html)
        self.assertIn("F1", html)
        self.assertIn("First planned run and first declared field", html)
        self.assertIn("No timing or token comparison is derived", html)
        for run in self.analysis["runs"]:
            self.assertIn(run["run_id"], html)
        self.assertIn("role='img'", html)
        self.assertIn("2 valid, 0 invalid and 1 missing of 3 planned cases", html)

    def test_sensitivity_is_hypothetical_and_source_bound(self):
        scenarios = [{"id": "alternative", "title": "Alternative queue", "provenance": "Operator question",
                      "changes": [{"id": "case:a", "labels": {"queue": "south"}}]}]
        sensitivity = build_sensitivity(self.task, self.plan, self.predictions, self.labels, scenarios)
        before = copy.deepcopy(sensitivity)
        html = self.html(sensitivity=sensitivity)
        self.assertEqual(sensitivity, before)
        self.assertIn("Hypothetical reference sensitivity: available", html)
        self.assertIn("Alternative queue", html)
        self.assertIn("Operator question", html)
        self.assertIn("improved", html)
        self.assertIn("Reference coverage: 1 full, 1 partial and 1 absent", html)
        self.assertIn("#reference-sensitivity", html)
        sensitivity["source_hashes"]["labels"] = "other"
        with self.assertRaisesRegex(ValueError, "sensitivity sources"):
            self.html(sensitivity=sensitivity)

    def test_escaping_for_static_dynamic_html_and_inert_json(self):
        marker = "</script><img src=x onerror=alert(1)>"
        analysis, findings = copy.deepcopy((self.analysis, self.findings))
        analysis["task"]["name"] = marker
        findings["findings"][0]["title"] = marker
        findings["findings"][0]["case_ids"] = ["case #é?<>&"]
        html = self.html(analysis, findings)
        self.assertNotIn(marker, html)
        self.assertIn("&lt;/script&gt;", html)
        self.assertIn("\\u003c/script\\u003e", html)
        self.assertIn("case+%23%C3%A9%3F%3C%3E%26", html)
        self.dom_check(r"""
assert.equal(root.querySelectorAll('img').length, 0);
assert(get('finding-detail').textContent.includes('</script><img'));
change('finding-select', input.findings[1].finding_id);
change('finding-select', input.findings[0].finding_id);
assert.equal(root.querySelectorAll('img').length, 0);
assert(get('finding-detail').textContent.includes('</script><img'));
""", analysis=analysis, findings=findings)

    def test_navigation_and_url_keep_run_case_comparison_filters(self):
        a, b = self.analysis["runs"][0]["run_id"], self.analysis["runs"][1]["run_id"]
        url = f"file:///offline/report.html?experiment=private#presentation-heading?presentation=1&slide=scope&reveal=0&run={a}&compareRun={b}&case=case%3Aa&filter=route"
        self.dom_check(r"""
assert(root.classList.contains('presentation-active'));
assert.equal(params().get('run'), input.runs[0]);
assert.equal(params().get('compareRun'), input.runs[1]);
assert.equal(params().get('case'), 'case:a');
assert(document.getElementById('outside-button').hasAttribute('inert'));
assert(document.getElementById('already-inert').hasAttribute('inert'));
assert.equal(get('previous').disabled, true);
get('next').click(); assert.equal(params().get('reveal'), '1');
get('next').click(); assert.equal(params().get('slide'), 'overview');
get('previous').click(); assert.equal(params().get('slide'), 'scope'); assert.equal(params().get('reveal'), '1');
change('slide-select', 'prompts'); assert.equal(params().get('slide'), 'prompts');
assert.equal(params().get('filter'), 'route');
assert.equal(new URL(dom.window.location.href).searchParams.get('experiment'), 'private');
assert.equal(params().get('run'), input.runs[0]); assert.equal(params().get('case'), 'case:a');
const fresh = open(get('permalink').href);
assert.equal(fresh.window.document.getElementById('presentation-slide-select').value, 'prompts');
assert.equal(fresh.window.document.getElementById('explorer-run').value, input.runs[0]);
assert.equal(fresh.window.document.getElementById('explorer-case').value, 'case:a');
key(get('stage'), 'Escape'); assert.equal(params().get('presentation'), '0');
assert(!root.classList.contains('presentation-active'));
assert(!document.getElementById('outside-button').hasAttribute('inert'));
assert(document.getElementById('already-inert').hasAttribute('inert'));
assert.equal(document.activeElement.id, 'deep-findings');
""", url=url)

    def test_all_findings_selectable_exact_evidence_exit_and_case_focus(self):
        self.dom_check(r"""
get('start').click(); change('slide-select', 'finding');
assert.equal(get('finding-select').options.length, input.findings.length);
const item = input.findings.find(item => item.kind === 'prompt_effect');
change('finding-select', item.finding_id);
assert.equal(params().get('finding'), item.finding_id);
assert.equal(get('finding-detail').children.length, 1);
assert(get('finding-detail').textContent.includes(item.observation));
assert(get('finding-detail').textContent.includes('Denominator: ' + item.denominator));
get('next').click(); assert.equal(params().get('reveal'), '1');
const link = get('finding-detail').querySelector('.presentation-case-links a'); assert(link);
const expected = new URLSearchParams(new URL(link.href).hash.split('?')[1]);
link.click();
assert.equal(params().get('presentation'), '0'); assert.equal(params().get('slide'), 'finding');
assert.equal(document.getElementById('explorer-run').value, item.run_ids[0]);
assert.equal(document.getElementById('explorer-compare').value, item.run_ids[1]);
assert.equal(document.getElementById('explorer-case').value, expected.get('case'));
assert.equal(document.activeElement.id, 'explorer-case-heading');
assert(!root.classList.contains('presentation-active'));
assert(dom.window.presentationScrolls.every(item => item.options.behavior === 'auto'));
""", reduced_motion=True)

    def test_agreement_range_links_restore_exact_boundary_pairs_static_and_dynamic(self):
        agreement = next(item for item in self.findings["findings"] if item["kind"] == "agreement_overview")
        boundaries = agreement["metrics"]["range_evidence"]
        self.assertEqual([item["boundary"] for item in boundaries], ["minimum", "maximum"])
        self.assertEqual([item["accepted"] for item in boundaries], [0, 2])
        first_pair = self.analysis["agreement_pairs"][0]
        self.assertEqual(first_pair["accepted"], 1)
        self.assertTrue(all({first_pair["run_a"], first_pair["run_b"]} != {item["run_a"], item["run_b"]} for item in boundaries))
        findings = copy.deepcopy(self.findings)
        findings["findings"] = [agreement] + [item for item in findings["findings"] if item["kind"] != "agreement_overview"]
        html = self.html(findings=findings)
        data = json.loads(re.search(r"id='presentation-data'>(.*?)</script>", html, re.S).group(1))
        self.assertEqual(data["findings"][0]["metrics"]["range_evidence"], boundaries)
        self.dom_check(r"""
const item = input.findings.find(item => item.kind === 'agreement_overview');
const boundaryData = item.metrics.range_evidence;
function checkLinks(owner) {
  const detail = owner.getElementById('presentation-finding-detail');
  const links = [...detail.querySelectorAll('.presentation-boundary-links a')];
  assert.equal(links.length, 2);
  links.forEach((link, i) => {
    const selection = new URLSearchParams(new URL(link.href).hash.split('?').slice(1).join('?'));
    assert.equal(link.textContent, 'Inspect ' + boundaryData[i].boundary + ' acceptance boundary');
    assert.equal(selection.get('run'), boundaryData[i].run_a);
    assert.equal(selection.get('compareRun'), boundaryData[i].run_b);
    assert(link.parentElement.textContent.includes(boundaryData[i].accepted + '/' + boundaryData[i].planned + ' cases'));
    assert(link.parentElement.textContent.includes(boundaryData[i].tied_pairs + ' tied pairs'));
  });
  assert(!detail.textContent.includes('Inspect supporting run pair'));
  return links;
}
const noJS = open(input.url, false); checkLinks(noJS.window.document);
// Force dynamic mounting, rather than reusing the server's first finding.
change('finding-select', input.findings.find(item => item.kind === 'run_coverage').finding_id);
get('start').click(); change('slide-select', 'finding'); change('finding-select', item.finding_id);
let links = checkLinks(document);
links[0].click();
assert.equal(document.getElementById('explorer-run').value, boundaryData[0].run_a);
assert.equal(document.getElementById('explorer-compare').value, boundaryData[0].run_b);
assert.equal(params().get('presentation'), '0');
get('start').click(); change('slide-select', 'finding'); links = checkLinks(document); links[1].click();
assert.equal(document.getElementById('explorer-run').value, boundaryData[1].run_a);
assert.equal(document.getElementById('explorer-compare').value, boundaryData[1].run_b);
assert.equal(params().get('presentation'), '0');
""", findings=findings)

    def test_keyboard_respects_controls_scroll_and_modifiers_and_traps_focus(self):
        self.dom_check(r"""
get('start').click(); change('slide-select', 'outputs');
const stage = get('stage'), scroll = root.querySelector('#presentation-slide-outputs .presentation-scroll');
let before = params().toString();
for (const node of [get('next'), get('slide-select'), scroll, scroll.querySelector('td'), root.querySelector('#presentation-slide-outputs a')]) {
  const event = key(node, 'ArrowRight'); assert.equal(event.defaultPrevented, false); assert.equal(params().toString(), before);
}
for (const tag of ['input','textarea']) {const node = document.createElement(tag); stage.append(node); key(node, ' '); assert.equal(params().toString(), before);}
const edit = document.createElement('div'); edit.setAttribute('contenteditable',''); stage.append(edit); key(edit, 'ArrowRight'); assert.equal(params().toString(), before);
key(stage, 'ArrowRight', {ctrlKey:true}); assert.equal(params().toString(), before);
assert(key(stage, 'ArrowRight').defaultPrevented); assert.equal(params().get('reveal'), '1');
key(stage, 'End'); assert.equal(params().get('slide'), 'limits');
key(stage, 'Home'); assert.equal(params().get('slide'), 'scope');
const focusable = [...root.querySelectorAll('a[href],button:not([disabled]),select:not([disabled]),summary,[tabindex="0"]')].filter(node => !node.closest('[hidden]') && (!node.closest('details:not([open])') || node.tagName === 'SUMMARY'));
const first = focusable[0], last = focusable[focusable.length - 1];
last.focus(); assert(key(last, 'Tab').defaultPrevented); assert.equal(document.activeElement, first);
first.focus(); assert(key(first, 'Tab', {shiftKey:true}).defaultPrevented); assert.equal(document.activeElement, last);
""")

    def test_unknown_url_state_is_reported_and_history_restores(self):
        self.dom_check(r"""
assert(!get('notice').hidden);
assert(get('notice').textContent.includes('linked slide is unavailable'));
assert(get('notice').textContent.includes('linked finding is unavailable'));
assert(get('notice').textContent.includes('reveal is invalid'));
assert.equal(get('slide-select').value, 'scope');
dom.window.location.hash = 'presentation-heading?presentation=1&slide=repeats&reveal=1';
dom.window.dispatchEvent(new dom.window.PopStateEvent('popstate'));
assert.equal(get('slide-select').value, 'repeats'); assert.equal(get('notice').hidden, true);
assert.equal(root.querySelector('[data-presentation-slide=repeats]').hidden, false);
""", url="file:///offline/report.html#presentation-heading?presentation=1&slide=unknown&reveal=-4&finding=unknown")

    def test_print_reduced_motion_and_bounded_large_finding_payload(self):
        findings = copy.deepcopy(self.findings)
        findings["findings"][0]["case_ids"] = ["case" + str(i) for i in range(10000)]
        html = self.html(findings=findings)
        self.assertIn("@media print", html)
        self.assertIn("[data-presentation-reveal]{display:block!important", html)
        self.assertIn("prefers-reduced-motion:reduce", html)
        self.assertIn("animation:none!important", html)
        self.assertIn("focus-visible", html)
        self.assertIn("First 8 of 10000 supporting case IDs", html)
        data = json.loads(re.search(r"id='presentation-data'>(.*?)</script>", html, re.S).group(1))
        self.assertEqual(data["findings"][0]["case_count"], 10000)
        self.assertEqual(len(data["findings"][0]["case_ids"]), 8)
        self.assertNotIn("agreement_pairs", data)
        self.assertNotIn("cases", data)
        self.assertNotIn("case9999", html)


if __name__ == "__main__":
    unittest.main()
