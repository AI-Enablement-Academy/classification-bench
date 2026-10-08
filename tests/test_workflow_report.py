"""Offline source/DOM checks; jsdom does not render or execute iframe srcdoc.

The harness opens the generated srcdoc in a separate about:srcdoc JSDOM and
relays its messages with the actual outer iframe's sender identity. Same-file
history uses reconfigure because jsdom 27 compares file path arrays by identity.
Native downloads are suppressed after their bytes are captured. These checks do
not establish browser rendering, native downloads, or browser history behavior.
"""

import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from classification_bench.core import ValidationError, build_plan, _digest
from classification_bench.report import generate_report
from classification_bench.workflow_report import generate_workflow_report


class _Scripts(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.current = dict(attrs).get("id")
            if self.current:
                self.values[self.current] = ""

    def handle_data(self, value):
        if self.current:
            self.values[self.current] += value

    def handle_endtag(self, tag):
        if tag == "script":
            self.current = None


def _data(html, key):
    return json.loads(_Scripts(html).values[key])


_DOM = r"""
const fs = require('fs'), assert = require('assert'), zlib = require('zlib');
const {JSDOM, VirtualConsole} = require('jsdom');
const input = JSON.parse(fs.readFileSync(0, 'utf8')), errors = [];
const pause = () => new Promise(resolve => setTimeout(resolve, 35));
function options(url, blobs) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error.message));
  return {url, runScripts:'dangerously', virtualConsole, beforeParse(window) {
    window.Blob = class {constructor(parts, options) {this.parts=parts;this.type=options.type;}};
    window.URL = class extends window.URL {};
    window.URL.createObjectURL = blob => {blobs.push(blob); return 'blob:offline-' + blobs.length;};
    window.URL.revokeObjectURL = () => {};
    window.HTMLElement.prototype.scrollIntoView = function() {};
    window.matchMedia = () => ({matches:true});
    window.document.addEventListener('click',event=>{
      if(event.target.closest('a[download]'))event.preventDefault();
    },true);
  }};
}
function open(url=input.url) {
  const blobs=[], settings=options(url,blobs), before=settings.beforeParse;let dom;
  settings.beforeParse=window=>{
    before(window);
    const native=window.history.replaceState.bind(window.history);
    window.history.replaceState=(state,title,value)=>{
      const current=new URL(window.location.href),target=new URL(value,current);
      if(current.protocol==='file:'&&target.protocol===current.protocol&&
          target.host===current.host&&target.pathname===current.pathname&&target.search===current.search) {
        dom.reconfigure({url:target.href});return;
      }
      return native(state,title,value);
    };
  };
  dom=new JSDOM(input.html,settings);
  return {dom,blobs,frame:dom.window.document.getElementById('phase-report'),
    document:dom.window.document};
}
function attach(host) {
  const blobs=[], posts=[], settings=options('about:srcdoc',blobs), before=settings.beforeParse;
  settings.beforeParse = window => {
    before(window);
    Object.defineProperty(window,'parent',{value:{postMessage(value) {
      posts.push(value);
      host.dom.window.dispatchEvent(new host.dom.window.MessageEvent('message',{
        data:value,source:host.frame.contentWindow}));
    }}});
  };
  const dom=new JSDOM(host.frame.srcdoc,settings);
  return {dom,document:dom.window.document,blobs,posts};
}
function change(child,id,value) {
  const node=child.document.getElementById(id);node.value=value;
  node.dispatchEvent(new child.dom.window.Event('change',{bubbles:true}));
}
function params(child) {
  return new URLSearchParams(child.dom.window.location.hash.split('?').slice(1).join('?'));
}
function outerRoute(host) {
  const raw=host.dom.window.location.hash.slice(1), slash=raw.indexOf('/');
  return {phase:slash<0?raw:raw.slice(0,slash),fragment:slash<0?'':decodeURIComponent(raw.slice(slash+1))};
}
const host=open();
"""


class WorkflowReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="workflow-report-dom-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.task = {"name": "Arbitrary </script><script>window.INJECTED=1</script> task",
                     "input_keys": ["text"],
                     "fields": [{"name": "result", "labels": ["yes", "no"]}]}
        self.inputs = {"records": [
            {"id": "a$&b", "input": {"text": "dollar $& text <img src=x onerror=window.INJECTED=1>"}},
            {"id": "second /?case", "input": {"text": '{"key":["other text",23]}'}},
            {"id": "third", "input": {"text": "no prediction"}}]}
        source = self.root / "inputs.json"
        source.write_text(json.dumps(self.inputs))
        self.experiment = {"configs": [
            {"id": "first", "model": "declared-only", "settings": {}, "model_metadata": {
                "schema_version": 1, "family": {"status": "operator_declared",
                    "value": "Family <img src=x onerror=window.INJECTED=1>",
                    "provenance": "Illustrative test declaration",
                    "source_urls": ["https://example.invalid/source?x=one&y=two"]}}},
            {"id": "second", "model": "another-declaration", "settings": {}}],
            "prompts": [{"id": "baseline", "text": "Classify arbitrary records"},
                        {"id": "other", "text": "Check the declared field"}],
            "repeats": 2, "batch_size": 2}
        phases, manifest_phases = {}, {}
        for phase, rows, repeats in (("smoke", self.inputs["records"][:1], 1),
                                     ("full", self.inputs["records"], 2)):
            experiment = {**self.experiment, "repeats": repeats}
            plan = build_plan(self.task, experiment, {"records": rows})
            operations = [{"request_id": req["request_id"], "config_id": req["config_id"],
                           "prompt_id": req["prompt_id"], "repeat": req["repeat"],
                           "batch_index": req["batch_index"],
                           "ids": [item["id"] for item in req["items"]],
                           "state": "never_sent", "parsed_status": None, "predictions": []}
                          for req in plan["requests"]]
            phases[phase] = {"task": self.task, "plan": plan,
                             "predictions": {"records": []}, "operations": operations}
            manifest_phases[phase] = {"ids": [row["id"] for row in rows], "plan_sha256": _digest(plan)}
        self.snapshot = {"manifest": {"name": "Combined <workflow> </script><script>window.INJECTED=1</script>",
                                      "workflow_sha256": _digest({"fixture": self.inputs}),
                                      "sources": {"inputs": {"path": str(source)}},
                                      "phases": manifest_phases}, "phases": phases}
        self.html = generate_workflow_report(self.snapshot)
        self.documents = _data(self.html, "workflow-data")["documents"]
        self.full_runs = _data(self.documents["full"], "report-explorer-data")["runs"]

    def dom_check(self, check, *, url="file:///offline/workflow.html#full", **extra):
        if not shutil.which("node"):
            self.skipTest("local Node.js is unavailable")
        available = subprocess.run(["node", "-e", "require.resolve('jsdom')"],
                                   capture_output=True, text=True)
        if available.returncode:
            self.skipTest("local jsdom is unavailable")
        payload = {"html": self.html, "url": url, "documents": self.documents,
                   "runs": self.full_runs, **extra}
        script = (_DOM + "\n(async()=>{\n" + check +
                  "\nassert.deepEqual(errors,[]);process.exit(0);})().catch(error=>{console.error(error);process.exit(1);});")
        result = subprocess.run(["node", "-e", script], input=json.dumps(payload),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_phase_totals_references_and_single_phase_identity(self):
        original = copy.deepcopy(self.snapshot)
        data = _data(self.html, "workflow-data")
        self.assertEqual(data["summaries"]["smoke"]["positions"], 4)
        self.assertEqual(data["summaries"]["full"]["positions"], 24)
        self.assertEqual(data["summaries"]["full"]["outcomes"], {"never sent": 24})
        self.assertIn("28 planned outputs", self.html)
        self.assertEqual(self.snapshot, original)
        self.assertTrue(all(run["counts"]["known_reference_exact_rate"] is None for run in self.full_runs))
        labels = {"records": [{"id": "a$&b", "labels": {"result": "yes"}}]}
        projected = generate_workflow_report(self.snapshot, labels, allow_partial_references=True)
        runs = _data(_data(projected, "workflow-data")["documents"]["full"], "report-explorer-data")["runs"]
        self.assertTrue(all(run["counts"]["planned"] == 3 and run["counts"]["full_reference"] == 1
                            and run["counts"]["no_reference"] == 2 for run in runs))
        selected = {**self.snapshot, "phases": {"smoke": self.snapshot["phases"]["smoke"]}}
        full_labels = {"records": [{"id": row["id"], "labels": {"result": "yes"}}
                                   for row in self.inputs["records"]]}
        ordinary = generate_report(self.task, selected["phases"]["smoke"]["plan"],
                                   {"records": full_labels["records"][:1]}, {"records": []},
                                   selected["phases"]["smoke"]["operations"])
        standalone = generate_workflow_report(selected, full_labels)
        self.assertEqual(_data(standalone, "report-explorer-data"), _data(ordinary, "report-explorer-data"))
        self.assertIn("Workflow and phase identity", standalone)
        self.assertIn(self.snapshot["manifest"]["phases"]["smoke"]["plan_sha256"], standalone)
        full_labels["records"][-1]["id"] = "not-in-original-inputs"
        with self.assertRaises(ValidationError):
            generate_workflow_report(selected, full_labels)

    def test_selected_phase_initialization_switch_and_unmodified_download(self):
        self.dom_check(r"""
assert.equal(host.document.getElementById('phase').value,'full');
assert.match(host.frame.title,/Full phase/);
assert(host.frame.getAttribute('sandbox').includes('allow-downloads'));
assert(!host.frame.getAttribute('sandbox').includes('allow-same-origin'));
assert.equal(host.blobs.at(-1).parts.join(''),input.documents.full);
assert(!host.blobs.at(-1).parts.join('').includes('classification-workflow-state'));
const oldURL=host.document.getElementById('standalone').getAttribute('href');
const child=attach(host);await pause();
assert.equal(JSON.parse(child.document.getElementById('report-explorer-data').textContent).runs.length,8);
change({document:host.document,dom:host.dom},'phase','smoke');await pause();
assert.equal(outerRoute(host).phase,'smoke');assert.match(host.frame.title,/Smoke phase/);
assert.equal(host.document.getElementById('standalone').download,'smoke-report.html');
assert.equal(host.blobs.at(-1).parts.join(''),input.documents.smoke);
assert.notEqual(host.document.getElementById('standalone').getAttribute('href'),oldURL);
const smoke=attach(host);await pause();
assert.equal(JSON.parse(smoke.document.getElementById('report-explorer-data').textContent).runs.length,4);
""")

    def test_full_state_roundtrip_filters_search_and_presentation_permalink(self):
        self.dom_check(r"""
const a=input.runs[0], b=input.runs.find(run=>run.config_id!==a.config_id);
const query=new URLSearchParams({run:a.run_id,compareRun:b.run_id,case:'second /?case',
  caseSearch:'dollar $&',presentation:'0',slide:'finding',reveal:'1'});
host.dom.window.location.hash='full/'+encodeURIComponent('case-explorer-heading?'+query);await pause();
const child=attach(host);await pause();
assert.equal(child.document.getElementById('explorer-run').value,a.run_id);
assert.equal(child.document.getElementById('explorer-compare').value,b.run_id);
assert.equal(child.document.getElementById('explorer-case').value,'second /?case');
assert.equal(child.document.getElementById('explorer-case-search').value,'dollar $&');
child.dom.window.reportFilters.setValue('prompt','other');await pause();
const filter=params(child).get('rf_prompt');assert(filter);
const search=child.document.getElementById('explorer-case-search');search.value='unmatched $& query';
search.focus();search.dispatchEvent(new child.dom.window.Event('input',{bubbles:true}));await pause();
assert.equal(child.document.activeElement,search);
assert.equal(child.document.getElementById('explorer-case').value,'second /?case');
assert.equal(outerRoute(host).fragment,child.dom.window.location.hash.slice(1));
child.document.getElementById('presentation-start').click();await pause();
change(child,'presentation-slide-select','finding');await pause();
const portable=child.document.getElementById('presentation-permalink').href;
assert(portable.startsWith('file:///offline/workflow.html#full/'));
assert.equal(params(child).get('rf_prompt'),filter);
const reload=open(portable), restored=attach(reload);await pause();
assert.equal(restored.document.getElementById('explorer-run').value,a.run_id);
assert.equal(restored.document.getElementById('explorer-compare').value,b.run_id);
assert.equal(restored.document.getElementById('explorer-case').value,'second /?case');
assert.equal(restored.document.getElementById('explorer-case-search').value,'unmatched $& query');
assert.equal(params(restored).get('rf_prompt'),filter);
assert.equal(params(restored).get('presentation'),'1');
assert.equal(restored.document.getElementById('presentation-slide-select').value,'finding');
assert.equal(outerRoute(reload).fragment,restored.dom.window.location.hash.slice(1));
""")

    def test_rewritten_dynamic_finding_evidence_selects_exact_supporting_run(self):
        self.dom_check(r"""
const child=attach(host);await pause();
const initial=child.document.getElementById('explorer-run').value;
const findings=JSON.parse(child.document.getElementById('presentation-data').textContent).findings;
const target=findings.find(item=>item.run_ids[0]&&item.run_ids[0]!==initial);assert(target);
change(child,'presentation-finding-select',target.finding_id);await pause();
const link=child.document.querySelector('#presentation-finding-detail a[data-presentation-evidence]');
assert(link.href.startsWith('file:///offline/workflow.html#full/'));
assert.equal(link.target,'_blank');
const modified=new child.dom.window.MouseEvent('click',{bubbles:true,cancelable:true,button:0,ctrlKey:true});
link.dispatchEvent(modified);await pause();
assert(!modified.defaultPrevented);assert.equal(child.document.getElementById('explorer-run').value,initial);
assert(link.href.startsWith('file:///offline/workflow.html#full/'));
const click=new child.dom.window.MouseEvent('click',{bubbles:true,cancelable:true,button:0});
link.dispatchEvent(click);await pause();assert(click.defaultPrevented);
assert.equal(child.document.getElementById('explorer-run').value,target.run_ids[0]);
assert.equal(params(child).get('run'),target.run_ids[0]);
assert.equal(outerRoute(host).fragment,child.dom.window.location.hash.slice(1));
assert(link.href.startsWith('file:///offline/workflow.html#full/'));
""")

    def test_untrusted_messages_rejected_and_exact_child_message_restored(self):
        self.dom_check(r"""
const original=host.dom.window.location.href, wrong=new JSDOM('').window;
const send=(source,data)=>host.dom.window.dispatchEvent(new host.dom.window.MessageEvent('message',{source,data}));
const valid={type:'classification-workflow-state',phase:'full',fragment:'#case-explorer-heading?case=third'};
send(wrong,valid);send(host.frame.contentWindow,{...valid,phase:'smoke'});
send(host.frame.contentWindow,{...valid,fragment:'javascript:bad'});
send(host.frame.contentWindow,{...valid,fragment:23});send(host.frame.contentWindow,null);
assert.equal(host.dom.window.location.href,original);
send(host.frame.contentWindow,valid);
assert.deepEqual(outerRoute(host),{phase:'full',fragment:valid.fragment.slice(1)});
const restored=open(host.dom.window.location.href), child=attach(restored);await pause();
assert.equal(child.document.getElementById('explorer-case').value,'third');
""")

    def test_dollar_tokens_and_script_like_input_remain_exact_and_inert(self):
        self.dom_check(r"""
const fragment='case-explorer-heading?'+new URLSearchParams({case:'a$&b',caseSearch:"$' $` $& </script><script>window.INJECTED=1</script>"});
host.dom.window.location.hash='full/'+encodeURIComponent(fragment);await pause();
const child=attach(host);await pause();
assert.equal(child.document.getElementById('explorer-case').value,'a$&b');
assert.equal(params(child).get('caseSearch'),"$' $` $& </script><script>window.INJECTED=1</script>");
assert.equal(child.dom.window.INJECTED,undefined);assert.equal(host.dom.window.INJECTED,undefined);
assert.equal(child.document.querySelectorAll('img').length,0);
const source=child.document.querySelector('#explorer-model-declarations a');
assert.equal(source.href,'https://example.invalid/source?x=one&y=two');
assert(child.document.getElementById('explorer-model-declarations').textContent.includes('Family <img'));
const portable=child.document.getElementById('explorer-permalink').href;
assert(portable.startsWith('file:///offline/report$&.html#full/'));
const saved=new URLSearchParams(decodeURIComponent(new URL(portable).hash.slice('#full/'.length)).split('?').slice(1).join('?'));
assert.equal(saved.get('case'),'a$&b');assert.equal(saved.get('caseSearch'),params(child).get('caseSearch'));
assert.equal(saved.get('run'),child.document.getElementById('explorer-run').value);
""", url="file:///offline/report$&.html#full")

    def test_phase_data_download_preserves_all_planned_positions_after_filtering(self):
        self.dom_check(r"""
const child=attach(host);await pause();
child.dom.window.reportFilters.setValue('prompt','other');await pause();
change(child,'analysis-export-mode','private');
child.document.getElementById('analysis-export-download').click();await pause();
const bytes=Buffer.from(child.blobs.at(-1).parts[0]);
const exported=JSON.parse(zlib.gunzipSync(bytes).toString('utf8'));
assert.equal(exported.runs.length,8);
assert.equal(exported.runs.reduce((total,run)=>total+run.counts.planned,0),24);
assert(exported.runs.every(run=>run.counts.missing===3));
const known=JSON.parse(child.document.getElementById('analysis-export-data').textContent).private;
assert.equal(bytes.length,known.bytes);
assert.equal(require('crypto').createHash('sha256').update(bytes).digest('hex'),known.sha256);
""")


if __name__ == "__main__":
    unittest.main()
