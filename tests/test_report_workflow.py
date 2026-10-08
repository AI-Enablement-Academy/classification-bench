"""Offline operator workflows for sensitivity and shared report sections."""

import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from classification_bench.benchmark import report_snapshot, run
from classification_bench.core import build_plan
from classification_bench.report import generate_report
from classification_bench.report_analysis import build_analysis
from tests.test_report_exports import fixture


ROOT = Path(__file__).resolve().parents[1]


class ReportWorkflowTests(unittest.TestCase):
    def write(self, directory, name, value):
        path = directory / (name + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def invoke(self, *args):
        return subprocess.run([sys.executable, "-m", "classification_bench", *map(str, args)], cwd=ROOT,
                              text=True, capture_output=True, timeout=30)

    def scenarios(self):
        return [{"id": "alternative", "title": "Hypothetical policy", "provenance": "Operator scenario, not adjudication",
                 "changes": [{"id": "CASE_CANARY", "labels": {"FIELD_CANARY": "alternate"}}]}]

    def test_sensitivity_cli_private_exclusive_and_strict_partial(self):
        _, task, plan, predictions, labels = fixture(context=True)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths = {key: self.write(directory, key, value) for key, value in
                     (("task", task), ("plan", plan), ("predictions", predictions), ("labels", labels), ("scenarios", self.scenarios()))}
            before = {key: Path(path).read_bytes() for key, path in paths.items()}
            output = directory / "sensitivity.json"
            args = ["sensitivity", *[value for key, path in paths.items() for value in ("--" + key, path)], "--out", output]
            rejected = self.invoke(*args)
            self.assertEqual(rejected.returncode, 2)
            self.assertFalse(output.exists())
            accepted = self.invoke(*args, "--allow-partial-references")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            saved = output.read_bytes()
            value = json.loads(saved)
            self.assertEqual(value["status"], "available")
            self.assertTrue(value["scenarios"][0]["hypothetical"])
            self.assertEqual(value["scenarios"][0]["runs"][0]["all_fields_delta"]["correct"], -1)
            repeated = self.invoke(*args, "--allow-partial-references")
            self.assertEqual(repeated.returncode, 2)
            self.assertEqual(output.read_bytes(), saved)
            self.assertEqual(before, {key: Path(path).read_bytes() for key, path in paths.items()})

    def test_sensitivity_stdout_unlabeled_unavailable_and_invalid_changes_fail(self):
        _, task, plan, predictions, _ = fixture(context=True)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths = {key: self.write(directory, key, value) for key, value in
                     (("task", task), ("plan", plan), ("predictions", predictions), ("scenarios", []))}
            args = ["sensitivity", *[value for key, path in paths.items() for value in ("--" + key, path)]]
            unavailable = self.invoke(*args)
            self.assertEqual(unavailable.returncode, 0, unavailable.stderr)
            self.assertEqual(json.loads(unavailable.stdout)["status"], "unavailable")
            Path(paths["scenarios"]).write_text(json.dumps(self.scenarios()))
            rejected = self.invoke(*args)
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(rejected.stdout, "")
            self.assertIn("unavailable reference", rejected.stderr)

    def test_report_cli_scenarios_cohorts_exports_and_evidence_are_offline(self):
        _, task, plan, _, labels = fixture(context=True)
        experiment = copy.deepcopy(plan["experiment"])
        experiment["configs"][0]["model"] = "synthetic-only"
        experiment["configs"][0]["settings"] = {"adapter": "synthetic", "response_mode": "first_label"}
        inputs = {"records": [item for request in plan["requests"] if request["repeat"] == 1 for item in request["items"]]}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = {"schema_version": 1, "task": self.write(directory, "task", task),
                      "inputs": self.write(directory, "inputs", inputs),
                      "experiment": self.write(directory, "experiment", experiment),
                      "database": str(directory / "state.sqlite"), "artifacts": str(directory / "artifacts"),
                      "scope": "synthetic:presentation-workflow", "cap": 1, "currency": "SYN", "scale": 1,
                      "max_concurrency": 2, "provider_limits": {"synthetic": 2}, "authorization_file": None,
                      "on_budget_exhausted": "pause"}
            config_path = self.write(directory, "config", config)
            self.assertEqual(run(config_path)["status"], "completed")
            snapshot = report_snapshot(config_path)
            analysis = build_analysis(snapshot["task"], snapshot["plan"], snapshot["predictions"], labels, snapshot["operations"])
            cohort = [{"id": "declared", "title": "One frozen run", "origin": "declared_fresh",
                       "run_ids": [analysis["runs"][0]["run_id"]], "case_ids": ["CASE_CANARY"],
                       "one_run_per_configuration": True, "source": "Explicit test declaration"}]
            artifact_hashes = lambda: {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in (directory / "artifacts").rglob("*") if p.is_file()}
            before = artifact_hashes()
            output = directory / "report.html"
            result = self.invoke("report", "--config", config_path, "--labels", self.write(directory, "labels", labels),
                                 "--scenarios", self.write(directory, "scenarios", self.scenarios()),
                                 "--cohorts", self.write(directory, "cohorts", cohort),
                                 "--allow-partial-references", "--out", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            html = output.read_text()
            for marker in ("presentation-heading", "reference-sensitivity-heading", "downloads-heading", "field-metrics"):
                self.assertIn(marker, html)
            packed = json.loads(re.search(r"<script type='application/json' id='analysis-export-data'>(.*?)</script>", html, re.S)[1])
            exported = json.loads(gzip.decompress(base64.b64decode(packed["private"]["base64"])))
            self.assertEqual(exported["cohorts"][0]["case_ids"], ["CASE_CANARY"])
            self.assertEqual(exported["cohorts"][0]["distinct_configurations"], 1)
            self.assertEqual(len(exported["sensitivity"]["scenarios"]), 1)
            self.assertTrue(exported["sensitivity"]["hypothetical"])
            self.assertEqual(before, artifact_hashes())

    def test_integrated_presentation_evidence_exit_preserves_controls_and_shared_state(self):
        if not shutil.which("node") or subprocess.run(["node", "-e", "require.resolve('jsdom')"], capture_output=True).returncode:
            self.skipTest("local Node.js/jsdom unavailable")
        _, task, plan, predictions, labels = fixture(context=True)
        html = generate_report(task, plan, labels, predictions, allow_partial_references=True, scenarios=self.scenarios())
        script = r"""
const fs=require('fs'),assert=require('assert'),{JSDOM,VirtualConsole}=require('jsdom'),errors=[];
const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(fs.readFileSync(0,'utf8'),{runScripts:'dangerously',url:'file:///offline/report.html?keep=yes',virtualConsole:vc,
 beforeParse(w){w.HTMLElement.prototype.scrollIntoView=function(){};w.matchMedia=()=>({matches:true});}});
const doc=dom.window.document,get=id=>doc.getElementById(id),root=get('report-presentation');
get('presentation-start').click();assert.equal(root.getAttribute('aria-modal'),'true');
assert(get('downloads').hasAttribute('inert'));assert(get('case-explorer').hasAttribute('inert'));
const chooser=get('presentation-slide-select');chooser.value='outputs';chooser.dispatchEvent(new dom.window.Event('change'));
const link=root.querySelector('.presentation-slide:not([hidden]) a[data-presentation-evidence]');assert(link);link.click();
assert.equal(root.getAttribute('aria-modal'),null);assert(!get('downloads').hasAttribute('inert'));
assert(!get('case-explorer').hasAttribute('inert'));assert.equal(new URL(dom.window.location.href).searchParams.get('keep'),'yes');
const params=new URLSearchParams(dom.window.location.hash.split('?').slice(1).join('?'));
assert.equal(params.get('presentation'),'0');assert.equal(params.get('slide'),'outputs');assert.equal(get('explorer-run').value,params.get('run'));
get('presentation-start').click();assert.equal(get('presentation-slide-select').value,'outputs');
root.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
assert(!root.classList.contains('presentation-active'));assert.deepEqual(errors,[]);dom.window.close();
"""
        result = subprocess.run(["node", "-e", script], input=html, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
