"""Offline DOM checks for the case explorer, without a rendered-browser claim."""

import copy
import json
import shutil
import subprocess
import unittest

from classification_bench.report_explorer import render_report_explorer


def fixture():
    """Small schema-v1 evidence with full, partial and unknown references."""
    def case(case_id, prediction, reference, lifecycle="completed", raw=None):
        status = "invalid" if raw is not None else "missing" if prediction is None else "valid"
        return {"case_id": case_id, "request_id": "request:" + case_id,
                "input": {"text": "Input " + case_id}, "prediction_status": status,
                "prediction": prediction, "raw_prediction": raw, "reference": reference,
                "reference_status": "missing" if reference is None else "full" if len(reference) == 2 else "partial",
                "exact_match": None if reference is None or len(reference) != 2 else prediction == reference,
                "field_matches": {name: None if reference is None or name not in reference or prediction is None else prediction.get(name) == reference[name]
                                  for name in ("decision", "tone")},
                "lifecycle_state": lifecycle, "parsed_status": status,
                "reason": "No response" if status == "missing" else "Invalid label" if status == "invalid" else None,
                "evidence": {"response_sha256": "response-" + case_id}}

    a = [case("a", {"decision": "no", "tone": "plain"}, {"decision": "yes", "tone": "plain"}),
         case("b", {"decision": "yes", "tone": "plain"}, {"decision": "yes"}),
         case("c", None, None, "not_admitted")]
    b = [case("a", {"decision": "yes", "tone": "plain"}, {"decision": "yes", "tone": "plain"}),
         case("b", None, {"decision": "yes"}, "failed", raw={"decision": "invalid"}),
         case("c", {"decision": "no", "tone": "plain"}, None)]

    def run(run_id, prompt, cases):
        return {"run_id": run_id, "config_id": "config", "prompt_id": prompt,
                "repeat": 1, "model": "Offline fixture", "case_ids": ["a", "b", "c"],
                "cases": cases, "counts": {"planned": 3,
                    "valid": sum(item["prediction_status"] == "valid" for item in cases),
                    "invalid": sum(item["prediction_status"] == "invalid" for item in cases),
                    "missing": sum(item["prediction_status"] == "missing" for item in cases),
                    "full_reference": 1, "partial_reference": 1, "no_reference": 1,
                    "exact_correct": sum(item["exact_match"] is True for item in cases)}}

    transitions = {"gained_ids": ["a"], "lost_ids": [], "stable_correct_ids": [],
                   "stable_error_ids": [], "reference_unknown_ids": ["b", "c"],
                   "unusable_to_valid_ids": ["c"], "valid_to_unusable_ids": ["b"]}
    pairs = []
    for left, right in (("run:a", "run:b"), ("run:a", "run:c"), ("run:b", "run:c")):
        accepted = left == "run:b"
        pairs.append({"pair_id": left + right, "run_a": left, "run_b": right,
                      "compatibility": "eligible", "planned": 3,
                      "accepted_correct": 1 if accepted else 0, "accepted_error": 0,
                      "accepted_reference_unknown": 1 if accepted else 0,
                      "deferred": 1 if accepted else 3,
                      "accepted_correct_ids": ["a"] if accepted else [], "accepted_error_ids": [],
                      "accepted_reference_unknown_ids": ["c"] if accepted else [],
                      "deferred_ids": ["b"] if accepted else ["a", "b", "c"]})
    return {"schema_version": 1, "analysis_id": "fixture", "source_hashes": {},
            "task": {"name": "Generic fixture", "fields": [
                {"name": "decision", "labels": ["yes", "no"]},
                {"name": "tone", "labels": ["plain", "warm"]}]},
            "case_ids": ["a", "b", "c"],
            "runs": [run("run:a", "prompt A", a), run("run:b", "prompt B", b),
                     run("run:c", "prompt C", copy.deepcopy(b))],
            "prompt_comparisons": [{"run_a": "run:a", "run_b": "run:b", "config_id": "config",
                "repeat": 1, "prompt_a": "prompt A", "prompt_b": "prompt B", **transitions,
                "fields": {"decision": copy.deepcopy(transitions)}, "net_gain": 1}],
            "agreement_pairs": pairs, "cohorts": []}


_DOM_START = r"""
const fs = require('fs');
const assert = require('assert');
const {JSDOM, VirtualConsole} = require('jsdom');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const errors = [];
function open(url = input.url) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error.message));
  return new JSDOM(input.html, {runScripts: 'dangerously', url, virtualConsole,
    beforeParse(window) {
      window.explorerScrolls = [];
      window.HTMLElement.prototype.scrollIntoView = function(options) { window.explorerScrolls.push({id: this.id, options}); };
      window.matchMedia = () => ({matches: Boolean(input.reduced_motion)});
    }
  });
}
const dom = open();
const document = dom.window.document;
const byID = id => document.getElementById(id);
const selectionParams = url => new URLSearchParams(new URL(url).hash.split('?').slice(1).join('?'));
function change(id, value) {
  byID(id).value = value;
  byID(id).dispatchEvent(new dom.window.Event('change', {bubbles: true}));
}
"""


class ReportExplorerTests(unittest.TestCase):
    def dom_check(self, check, analysis=None, url="file:///offline/report.html", reduced_motion=False):
        if not shutil.which("node"):
            self.skipTest("local Node.js is not installed")
        availability = subprocess.run(["node", "-e", "require.resolve('jsdom')"],
                                      capture_output=True, text=True, check=False)
        if availability.returncode:
            self.skipTest("local jsdom is not installed")
        payload = {"html": render_report_explorer(analysis or fixture()), "url": url,
                   "reduced_motion": reduced_motion}
        script = (_DOM_START + "\n(async () => {\n" + check +
                  "\nassert.deepEqual(errors, []);\n})().catch(error => {console.error(error); process.exitCode = 1;});")
        result = subprocess.run(["node", "-e", script],
                                input=json.dumps(payload), text=True, capture_output=True,
                                check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_and_inert_json_preserve_evidence_without_mutation(self):
        analysis = fixture()
        original = copy.deepcopy(analysis)
        html = render_report_explorer(analysis)
        self.assertEqual(analysis, original)
        self.assertIn("prefers-reduced-motion", html)
        self.assertNotIn("innerHTML", html)
        self.assertNotIn("<script src=", html)
        for malformed in (None, [], {}, {"schema_version": 2}):
            with self.assertRaisesRegex(ValueError, "schema version 1"):
                render_report_explorer(malformed)

    def test_exact_field_diffs_and_all_planned_statuses(self):
        self.dom_check(r"""
assert.equal(byID('explorer-run').value, 'run:a');
change('explorer-compare', 'run:b');
const rows = [...document.querySelectorAll('#explorer-case-table tbody tr')];
assert.equal(rows.length, 3);
assert(rows.every(row => !row.hidden));
assert(rows[1].textContent.includes('invalid; lifecycle: failed; parse: invalid'));
assert(rows[2].textContent.includes('missing; lifecycle: not_admitted; parse: missing'));
assert(rows[2].textContent.includes('Unknown'));
assert(rows[2].textContent.includes('missing → valid'));
assert(byID('explorer-counts').textContent.includes('Run A: 3 planned; 2 valid; 0 invalid; 1 missing'));
assert(byID('explorer-counts').textContent.includes('Run B: 3 planned; 2 valid; 1 invalid; 0 missing'));
const diff = [...document.querySelector('[data-field=decision]').cells].map(cell => cell.textContent);
assert.deepEqual(diff, ['decision', 'yes', 'no', 'yes', 'Changed', 'A: Mismatch; B: Match']);
change('explorer-case', 'b');
assert(byID('explorer-field-table').textContent.includes('toneUnknownplainUnavailableNot comparableA: Reference unknown; B: Reference unknown'));
assert(byID('explorer-raw').textContent.includes('"decision": "invalid"'));
change('explorer-case', 'c');
assert(byID('explorer-case-status').textContent.includes('Reference: Unknown'));
assert([...document.querySelectorAll('#explorer-field-table tbody tr')].every(row => row.cells[1].textContent === 'Unknown'));
assert.equal(document.activeElement, document.body);
""")

    def test_ab_url_reload_reset_and_independent_query_parameters(self):
        self.dom_check(r"""
assert.equal(byID('explorer-run').value, 'run:b');
assert.equal(byID('explorer-compare').value, 'run:a');
assert.equal(byID('explorer-case').value, 'b');
change('explorer-case', 'c');
const selectionURL = new URL(dom.window.location.href);
assert.equal(selectionParams(selectionURL.href).get('case'), 'c');
assert.equal(selectionURL.searchParams.get('filter'), 'keep');
assert.equal(selectionURL.hash.split('?')[0], '#provenance-heading');
const reloaded = open(dom.window.location.href);
assert.equal(reloaded.window.document.getElementById('explorer-run').value, 'run:b');
assert.equal(reloaded.window.document.getElementById('explorer-compare').value, 'run:a');
assert.equal(reloaded.window.document.getElementById('explorer-case').value, 'c');
change('explorer-run', 'run:a');
assert.equal(byID('explorer-compare').value, '');
assert(byID('explorer-notice').textContent.includes('Run B must differ'));
assert([...byID('explorer-compare').options].find(option => option.value === 'run:a').disabled);
dom.window.dispatchEvent(new dom.window.CustomEvent('report-explorer-select', {detail: {run: 'run:c', compareRun: 'run:b', case: 'a'}}));
assert.equal(byID('explorer-run').value, 'run:c');
assert.equal(byID('explorer-compare').value, 'run:b');
byID('explorer-reset').click();
assert.equal(byID('explorer-run').value, 'run:a');
assert.equal(byID('explorer-case').value, 'a');
assert.equal(byID('explorer-compare').value, '');
const resetURL = new URL(dom.window.location.href);
['run', 'compareRun', 'case'].forEach(key => assert.equal(selectionParams(resetURL.href).get(key), ''));
assert.equal(resetURL.searchParams.get('filter'), 'keep');
assert.equal(resetURL.hash.split('?')[0], '#provenance-heading');
assert.equal(selectionParams(byID('explorer-permalink').href).get('case'), 'a');
const resetReload = open(resetURL.href);
assert.equal(resetReload.window.document.getElementById('explorer-run').value, 'run:a');
assert.equal(resetReload.window.document.getElementById('explorer-compare').value, '');
assert.equal(resetReload.window.document.getElementById('explorer-case').value, 'a');
""", url="file:///offline/report.html?filter=keep&run=run%3Ab&compareRun=run%3Aa&case=b#provenance-heading")

    def test_prompt_and_every_agreement_pair_have_exact_case_links(self):
        self.dom_check(r"""
const prompt = document.querySelector('#explorer-prompt-table tbody tr');
assert(prompt.textContent.includes('1 gained'));
assert(prompt.textContent.includes('0 lost'));
assert(prompt.textContent.includes('1 unusable → valid; 1 valid → unusable'));
const agreementRows = [...document.querySelectorAll('#explorer-agreement-table tbody tr')];
change('explorer-agreement-scope', 'all');
const allAgreementRows = [...document.querySelectorAll('#explorer-agreement-table tbody tr')];
assert.equal(allAgreementRows.length, 3);
assert.deepEqual([...allAgreementRows[2].cells].slice(1, 6).map(cell => cell.firstChild.textContent), ['3', '1', '0', '1', '1']);
const unknown = allAgreementRows[2].cells[4].querySelector('a');
const url = new URL(unknown.href);
assert.equal(selectionParams(url.href).get('run'), 'run:b');
assert.equal(selectionParams(url.href).get('compareRun'), 'run:c');
assert.equal(selectionParams(url.href).get('case'), 'c');
unknown.click();
assert.equal(byID('explorer-run').value, 'run:b');
assert.equal(byID('explorer-compare').value, 'run:c');
assert.equal(byID('explorer-case').value, 'c');
assert.equal(document.activeElement, byID('explorer-case-heading'));
assert(byID('explorer-field-table').textContent.includes('Same'));
assert(byID('explorer-field-table').textContent.includes('Reference unknown'));
""")

    def test_all_missing_and_unlabeled_keep_full_denominator_without_accuracy(self):
        analysis = fixture()
        analysis["prompt_comparisons"] = []
        analysis["agreement_pairs"] = []
        for run in analysis["runs"]:
            run["counts"].update(valid=0, invalid=0, missing=3, full_reference=0,
                                  partial_reference=0, no_reference=3, exact_correct=None)
            for item in run["cases"]:
                item.update(prediction_status="missing", prediction=None, raw_prediction=None,
                            reference=None, reference_status="missing", exact_match=None,
                            field_matches={"decision": None, "tone": None},
                            lifecycle_state="not_admitted", parsed_status=None, reason="Not run")
        self.dom_check(r"""
change('explorer-compare', 'run:b');
assert.equal(document.querySelectorAll('#explorer-case-table tbody tr').length, 3);
assert(byID('explorer-counts').textContent.includes('3 planned; 0 valid; 0 invalid; 3 missing'));
assert(byID('explorer-counts').textContent.includes('References: 0 full, 0 partial, 3 unknown'));
assert(byID('explorer-counts').textContent.includes('quality is unavailable'));
assert(!byID('explorer-counts').textContent.includes('Exact matches:'));
assert(!byID('explorer-content').textContent.includes('accuracy'));
assert(!byID('explorer-content').textContent.includes('0%'));
assert(byID('explorer-case-table').textContent.includes('Not comparable'));
assert(byID('explorer-prompts').textContent.includes('No paired prompt'));
assert(byID('explorer-agreement').textContent.includes('No eligible agreement'));
""", analysis)

    def test_malicious_text_is_inert_in_json_controls_tables_evidence_and_urls(self):
        attack = '</script><script>window.explorerPwned=1</script><img src=x onerror="window.explorerPwned=2">&\u2028'
        analysis = fixture()
        analysis["task"]["fields"][0]["name"] = attack
        analysis["prompt_comparisons"] = []
        analysis["agreement_pairs"] = []
        analysis["runs"][0]["run_id"] = attack
        analysis["runs"][0]["model"] = attack
        analysis["runs"][0]["case_ids"][0] = attack
        item = analysis["runs"][0]["cases"][0]
        item.update(case_id=attack, input={"text": attack}, prediction={attack: attack, "tone": "plain"},
                    raw_prediction=attack, reference={attack: attack, "tone": "plain"}, reason=attack,
                    field_matches={attack: True, "tone": True}, evidence={"response_sha256": attack})
        html = render_report_explorer(analysis)
        self.assertNotIn(attack, html)
        self.assertIn("\\u003c/script\\u003e", html)
        self.dom_check(r"""
assert.equal(dom.window.explorerPwned, undefined);
assert.equal(document.querySelectorAll('script').length, 2);
assert.equal(document.querySelectorAll('img').length, 0);
const raw = JSON.parse(byID('report-explorer-data').textContent);
const attack = raw.runs[0].run_id;
assert.equal(byID('explorer-run').value, attack);
assert.equal(byID('explorer-case').value, attack);
assert(byID('explorer-input').textContent.includes('</script>'));
assert(byID('explorer-raw').textContent.includes('explorerPwned'));
assert(document.querySelector('#explorer-field-table tbody th').textContent.includes('<img'));
const link = document.querySelector('#explorer-case-table tbody a');
assert.equal(selectionParams(link.href).get('case'), attack);
assert.equal(new URL(link.href).protocol, 'file:');
link.click();
assert.equal(dom.window.explorerPwned, undefined);
const reopened = open(dom.window.location.href);
assert.equal(reopened.window.document.getElementById('explorer-case').value, attack);
assert.equal(reopened.window.explorerPwned, undefined);
""", analysis)

    def test_invalid_url_empty_runs_native_controls_and_history_changes(self):
        self.dom_check(r"""
assert.equal(byID('explorer-run').value, 'run:a');
assert.equal(byID('explorer-compare').value, '');
assert.equal(byID('explorer-case').value, 'a');
assert(!byID('explorer-notice').hidden);
assert(byID('explorer-notice').textContent.includes('linked run is unavailable'));
['explorer-run', 'explorer-compare', 'explorer-case'].forEach(id => {
  assert.equal(byID(id).tagName, 'SELECT');
  assert(document.querySelector(`label[for="${id}"]`));
});
assert.equal(byID('explorer-selection').getAttribute('aria-live'), 'polite');
assert([...document.querySelectorAll('.explorer-scroll')].every(node => node.tabIndex === 0 && node.getAttribute('aria-label')));
dom.reconfigure({url: 'file:///offline/report.html?run=run%3Ac&compareRun=run%3Ab&case=c'});
dom.window.dispatchEvent(new dom.window.PopStateEvent('popstate'));
assert.equal(byID('explorer-run').value, 'run:c');
assert.equal(byID('explorer-compare').value, 'run:b');
assert.equal(byID('explorer-case').value, 'c');
dom.reconfigure({url: 'file:///offline/report.html?run=run%3Ab&case=b#case-explorer-heading'});
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'));
assert.equal(byID('explorer-run').value, 'run:b');
assert.equal(byID('explorer-compare').value, '');
assert.equal(byID('explorer-case').value, 'b');
""", url="file:///offline/report.html?run=gone&compareRun=gone&case=gone")
        analysis = fixture()
        analysis["runs"] = []
        analysis["case_ids"] = []
        self.dom_check(r"""
assert(!byID('explorer-empty').hidden);
assert(byID('explorer-content').hidden);
assert(byID('explorer-run').disabled);
assert(byID('explorer-compare').disabled);
assert(byID('explorer-case').disabled);
assert.equal(byID('explorer-selection').textContent, 'No run selected.');
""", analysis)

    def test_actual_analysis_builder_partial_and_unlabeled_evidence(self):
        from classification_bench.core import build_plan
        from classification_bench.report_analysis import build_analysis

        task = {"name": "Generic segments", "input_keys": ["text"], "fields": [
            {"name": "segment", "labels": ["alpha", "beta"]},
            {"name": "signal", "labels": ["present", "absent"]}]}
        experiment = {"configs": [{"id": "fixture", "model": "local", "settings": {}}],
                      "prompts": [{"id": "p0", "text": "Classify."}, {"id": "p1", "text": "Classify carefully."}],
                      "repeats": 1, "batch_size": 2}
        inputs = {"records": [{"id": case_id, "input": {"text": case_id}} for case_id in ("one", "two")]}
        plan = build_plan(task, experiment, inputs)
        predictions = {"records": [{"config_id": "fixture", "prompt_id": prompt, "repeat": 1,
                                    "id": "one", "prediction": {"segment": "alpha", "signal": "present"}}
                                   for prompt in ("p0", "p1")]}
        labels = {"records": [{"id": "one", "labels": {"segment": "alpha"}}]}
        partial = build_analysis(task, plan, predictions, labels)
        self.dom_check(r"""
change('explorer-compare', byID('explorer-compare').options[2].value);
assert.equal(document.querySelectorAll('#explorer-case-table tbody tr').length, 2);
assert(byID('explorer-counts').textContent.includes('2 planned; 1 valid; 0 invalid; 1 missing'));
assert(byID('explorer-counts').textContent.includes('0 full, 1 partial, 1 unknown'));
const fields = [...document.querySelectorAll('#explorer-field-table tbody tr')];
assert.deepEqual(fields.map(row => row.cells[0].textContent), ['segment', 'signal']);
assert.equal(fields[0].cells[5].textContent, 'A: Match; B: Match');
assert.equal(fields[1].cells[5].textContent, 'A: Reference unknown; B: Reference unknown');
assert.equal(document.querySelector('#explorer-agreement-table tbody tr').cells[4].firstChild.textContent, '1');
assert.equal(document.querySelector('#explorer-prompt-table tbody tr').cells[3].textContent, 'Unknown');
assert(byID('explorer-raw').textContent.includes('source_hashes'));
""", partial)
        unlabeled = build_analysis(task, plan, predictions)
        self.dom_check(r"""
change('explorer-compare', byID('explorer-compare').options[2].value);
assert(byID('explorer-counts').textContent.includes('0 full, 0 partial, 2 unknown'));
assert(!byID('explorer-counts').textContent.includes('Exact matches:'));
assert.equal(document.querySelector('#explorer-prompt-table tbody tr').cells[3].textContent, 'Unknown');
assert.equal(document.querySelector('#explorer-agreement-table tbody tr').cells[4].firstChild.textContent, '1');
assert.equal(document.querySelector('#explorer-agreement-table tbody tr').cells[5].firstChild.textContent, '1');
""", unlabeled)

    def test_external_findings_link_reveals_case_and_controls_preserve_focus(self):
        check = r"""
assert.equal(dom.window.explorerScrolls.length, 0);
assert.equal(document.activeElement, document.body);
const link = document.createElement('a');
link.href = '#case-explorer-heading?run=run%3Ab&case=b';
link.textContent = 'Evidence from a finding';
document.body.append(link);
link.click();
await new Promise(resolve => setTimeout(resolve, 30));
assert.equal(byID('explorer-run').value, 'run:b');
assert.equal(byID('explorer-compare').value, '');
assert.equal(byID('explorer-case').value, 'b');
assert.equal(document.activeElement, byID('explorer-case-heading'));
assert.deepEqual(dom.window.explorerScrolls.map(item => item.id), ['explorer-case-heading']);
assert.equal(dom.window.explorerScrolls[0].options.behavior, input.reduced_motion ? 'auto' : 'smooth');
byID('explorer-case').focus();
change('explorer-case', 'c');
await new Promise(resolve => setTimeout(resolve, 30));
assert.equal(byID('explorer-case').value, 'c');
assert.equal(document.activeElement, byID('explorer-case'));
assert.equal(dom.window.explorerScrolls.length, 1);
const reloaded = open(dom.window.location.href);
assert.equal(reloaded.window.document.getElementById('explorer-case').value, 'c');
assert.equal(reloaded.window.document.activeElement, reloaded.window.document.body);
assert.equal(reloaded.window.explorerScrolls.length, 0);
"""
        for reduced_motion in (False, True):
            with self.subTest(reduced_motion=reduced_motion):
                self.dom_check(check, url="file:///offline/report.html?run=run%3Aa&compareRun=run%3Ac&case=a",
                               reduced_motion=reduced_motion)

    def test_large_real_analysis_paginates_all_pairs_without_rebuilding_for_case_changes(self):
        from classification_bench.core import build_plan
        from classification_bench.report_analysis import build_analysis

        task = {"name": "Scale fixture", "input_keys": ["text"], "fields": [
            {"name": "decision", "labels": ["yes", "no"]}]}
        experiment = {"configs": [{"id": "config" + str(index), "model": "local", "settings": {}}
                                   for index in range(30)],
                      "prompts": [{"id": "p0", "text": "Classify."}, {"id": "p1", "text": "Classify carefully."}],
                      "repeats": 1, "batch_size": 3}
        inputs = {"records": [{"id": case_id, "input": {"text": case_id}} for case_id in ("a", "b", "c")]}
        analysis = build_analysis(task, build_plan(task, experiment, inputs), {"records": []})
        self.assertEqual(len(analysis["agreement_pairs"]), 1770)
        self.dom_check(r"""
assert.equal(document.querySelectorAll('#explorer-agreement-table tbody tr').length, 12);
assert(byID('explorer-agreement-page-status').textContent.includes('1770 eligible pairs available'));
assert.equal(document.querySelectorAll('#explorer-prompt-table tbody tr').length, 24);
assert(byID('explorer-prompt-page-status').textContent.includes('30 paired prompt conditions available'));
const promptTable = byID('explorer-prompt-table');
const agreementTable = byID('explorer-agreement-table');
change('explorer-case', 'b');
assert.equal(byID('explorer-prompt-table'), promptTable);
assert.equal(byID('explorer-agreement-table'), agreementTable);
change('explorer-agreement-scope', 'all');
assert(byID('explorer-agreement-page-status').textContent.includes('of 1770. All eligible pairs'));
byID('explorer-agreement-next').focus();
byID('explorer-agreement-next').click();
assert.equal(byID('explorer-agreement-page').value, '2');
assert.equal(document.activeElement, byID('explorer-agreement-next'));
change('explorer-agreement-page', '9999');
assert.equal(byID('explorer-agreement-page').value, '148');
assert.equal(document.querySelectorAll('#explorer-agreement-table tbody tr').length, 6);
assert(byID('explorer-agreement-next').disabled);
assert(byID('explorer-agreement-page-status').textContent.includes('1753–1770') === false);
assert(byID('explorer-agreement-page-status').textContent.includes('1765–1770 of 1770'));
change('explorer-agreement-page', '1');
assert.equal(document.querySelectorAll('#explorer-agreement-table tbody tr').length, 12);
change('explorer-agreement-scope', 'selection');
change('explorer-compare', byID('explorer-compare').options[2].value);
assert.equal(document.querySelectorAll('#explorer-agreement-table tbody tr').length, 1);
assert(byID('explorer-agreement-page-status').textContent.includes('Selected A/B pair'));
byID('explorer-prompt-next').click();
assert.equal(byID('explorer-prompt-page').value, '2');
change('explorer-prompt-page', '3');
assert.equal(document.querySelectorAll('#explorer-prompt-table tbody tr').length, 12);
assert(byID('explorer-prompt-next').disabled);
""", analysis)

    def test_pair_money_coverage_unknown_values_and_exact_large_ledger_units(self):
        analysis = fixture()
        analysis["runs"][0]["source_hashes"] = {"predictions": "a" * 64, "labels": "b" * 64}
        analysis["agreement_pairs"][0]["cost"] = {
            "observed_cost_micro_usd": None, "partial_observed_cost_micro_usd": 9007199254740993,
            "complete": False, "observed_cost_requests": 1, "planned_requests": 2,
            "unresolved_hold_micro_usd": 0, "subscription_invocations": 2,
            "unresolved_subscription_invocations": 0, "synthetic_excluded_requests": 1,
            "scope": "Selected two runs only; excludes smoke and human review", "limitation": "Retrospective evidence"}
        self.dom_check(r"""
change('explorer-compare', 'run:b');
const text = document.querySelector('#explorer-agreement-table tbody tr').cells[6].textContent;
assert(text.includes('USD coverage: 1/2 requests'));
assert(text.includes('Two-run USD total: Unavailable: incomplete USD coverage'));
assert(text.includes('9007199254.740993 USD (9007199254740993 micro USD)'));
assert(text.includes('Unresolved USD holds: 0.000000 USD (0 micro USD)'));
assert(text.includes('Subscription invocations: 2. Unresolved subscription invocations: 0'));
assert(text.includes('Synthetic requests excluded from USD: 1'));
assert(text.includes('Selected two runs only; excludes smoke and human review'));
assert(text.includes('a'.repeat(64)));
assert(text.includes('not independently verified'));
change('explorer-compare', 'run:c');
const unknown = document.querySelector('#explorer-agreement-table tbody tr').cells[6].textContent;
assert(unknown.includes('USD coverage: Unavailable/Unavailable'));
assert(unknown.includes('Subscription invocations: Unavailable'));
assert(!unknown.includes('0.000000 USD'));
""", analysis)


if __name__ == "__main__":
    unittest.main()
