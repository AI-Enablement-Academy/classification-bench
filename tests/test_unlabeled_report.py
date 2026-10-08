"""Optional references through the offline CLI and integrated local report."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from classification_bench.benchmark import run
from classification_bench.core import ValidationError, _digest, build_plan, evaluate
from classification_bench.report import generate_report
from tests.test_report_ux import Tree


class UnlabeledReportTests(unittest.TestCase):
    def setUp(self):
        self.task = {"name": "Generic support routing", "input_keys": ["message"],
                     "fields": [{"name": "decision", "labels": ["yes", "no"]},
                                {"name": "priority", "labels": ["low", "high"]}]}
        self.experiment = {"configs": [{"id": "local", "model": "synthetic-only",
                                         "settings": {"adapter": "synthetic", "response_mode": "first_label"}}],
                           "prompts": [{"id": "base", "text": "Use the task rubric."},
                                       {"id": "careful", "text": "Apply each decision field."}],
                           "repeats": 2, "batch_size": 1}
        self.inputs = {"records": [{"id": name, "input": {"message": "<script>private</script> " + name}}
                                   for name in ("a", "b", "c", "d")]}
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        self.partial = {"records": [
            {"id": "a", "labels": {"decision": "yes", "priority": "low"}},
            {"id": "b", "labels": {"decision": "no"}},
            {"id": "c", "labels": {"decision": "yes", "priority": None}}]}
        self.labels = {"records": [
            {"id": name, "labels": {"decision": "yes", "priority": "low"}}
            for name in ("a", "b", "c", "d")]}
        self.predictions = {"records": []}
        for prompt in ("base", "careful"):
            for repeat in (1, 2):
                for name, vector in (("a", {"decision": "yes", "priority": "low"}),
                                     ("b", {"decision": "invalid", "priority": "low"}),
                                     ("d", {"decision": "no", "priority": "high"})):
                    if name == "a" and prompt == "careful" and repeat == 2:
                        vector = {"decision": "no", "priority": "low"}
                    self.predictions["records"].append({"config_id": "local", "prompt_id": prompt,
                                                        "repeat": repeat, "id": name, "prediction": vector})
        self.operations = [{"request_id": request["request_id"], "state": "never_sent"}
                           for request in self.plan["requests"] if request["items"][0]["id"] == "c"]

    def html(self, labels=None, **kwargs):
        return generate_report(self.task, self.plan, labels, self.predictions, self.operations, **kwargs)

    def test_unlabeled_report_preserves_counts_and_has_no_fake_accuracy_plot(self):
        html = self.html()
        self.assertIn("Planned positions: 16; valid selected predictions: 8; no selected prediction: 4; invalid selected projection: 4", html)
        self.assertIn("Reference coverage: unlabeled; 0/4 cases fully referenced", html)
        self.assertIn("Full-denominator exact agreement is unavailable.", html)
        self.assertNotIn("id='agreement-duration-chart'", html)
        self.assertNotIn("Scored subset exact agreement by pass", html)
        self.assertIn("unavailable (no reference)", html)
        self.assertIn("unavailable (not supplied)", html)
        page = Tree(html).root
        rows = [row for row in page.descendants("tr") if row.attrs.get("data-config-id") == "local"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row.children[2].text(), "unavailable")
            self.assertEqual(row.children[2].attrs["data-sort-value"], "")
            self.assertEqual(row.children[3].text(), "unavailable")
        self.assertIn("&lt;script&gt;private&lt;/script&gt;", html)
        self.assertNotIn("<script>private</script>", html)

    def test_partial_reference_scores_have_separate_known_denominators(self):
        original = copy.deepcopy((self.task, self.plan, self.partial, self.predictions, self.operations))
        html = self.html(self.partial, allow_partial_references=True)
        self.assertEqual((self.task, self.plan, self.partial, self.predictions, self.operations), original)
        self.assertIn("1/4 cases fully referenced, 2 partially referenced, 1 without known references", html)
        self.assertIn("3/4 known references", html)
        self.assertIn("1/4 known references", html)
        self.assertIn("Scored subset exact agreement: 1/1 (100.0%)", html)
        self.assertIn("Scored subset exact agreement: 0/1 (0.0%)", html)
        self.assertIn("Scored subset paired prompt effect against base: -1 exact matches (1/1 → 0/1)", html)
        self.assertIn("Scored subset exact agreement by pass", html)
        self.assertIn("Cases without complete references are excluded from this scored subset", html)
        self.assertIn("unavailable (partial reference)", html)
        self.assertIn(_digest(self.partial), html)
        self.assertNotIn("Agreement and observed cost", html)

    def test_no_fully_referenced_cases_or_known_field_labels_is_unavailable(self):
        partial = {"records": [{"id": "a", "labels": {"decision": "yes"}}]}
        html = self.html(partial, allow_partial_references=True)
        self.assertIn("Scored subset exact agreement: unavailable; 0/4 cases have complete references", html)
        self.assertIn("0/4 known references", html)
        self.assertIn("Exact agreement chart unavailable: no cases have complete references", html)
        self.assertNotIn("Scored subset exact agreement by pass", html)

    def test_partial_opt_in_does_not_bypass_strict_reference_validation(self):
        with self.assertRaises(ValidationError):
            self.html(self.partial)
        for bad in ({"records": [{"id": "unknown", "labels": {"decision": "yes"}}]},
                    {"records": [{"id": "a", "labels": {"decision": "maybe"}}]},
                    {"records": [self.partial["records"][0], self.partial["records"][0]]}):
            with self.subTest(labels=bad), self.assertRaises(ValidationError):
                self.html(bad, allow_partial_references=True)

    def test_labeled_values_and_integrated_evidence_remain_available(self):
        html = self.html(self.labels)
        self.assertIn("Exact agreement: 1/4 (25.0%)", html)
        self.assertIn("Paired prompt effect against base: -1 exact matches (1/4 → 0/4)", html)
        self.assertIn("Exact agreement by pass", html)
        self.assertIn("id='agreement-duration-chart'", html)
        self.assertIn("id='case-explorer'", html)
        self.assertIn("id='deep-findings'", html)
        self.assertIn("href='#case-explorer-heading'", html)
        self.assertNotIn("Full-denominator exact agreement is unavailable", html)
        data = html.split("id='report-explorer-data'>", 1)[1].split("</script>", 1)[0]
        analysis = json.loads(data)
        self.assertEqual(len(analysis["runs"]), 4)
        self.assertTrue(all(entry["counts"]["planned"] == 4 for entry in analysis["runs"]))
        self.assertTrue(all(len(entry["cases"]) == 4 for entry in analysis["runs"]))

    def invoke(self, root, *arguments):
        return subprocess.run([sys.executable, "-m", "classification_bench", *arguments],
                              cwd=Path(__file__).resolve().parents[1], capture_output=True,
                              text=True, check=False, timeout=30)

    def write(self, root, name, value):
        path = root / (name + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def test_evaluate_cli_optional_partial_and_complete_references(self):
        with tempfile.TemporaryDirectory(prefix="unlabeled-evaluate-") as directory:
            root = Path(directory)
            base = ["evaluate", "--task", self.write(root, "task", self.task),
                    "--plan", self.write(root, "plan", self.plan),
                    "--predictions", self.write(root, "predictions", self.predictions)]
            unlabeled = self.invoke(root, *base)
            self.assertEqual(unlabeled.returncode, 0, unlabeled.stderr)
            output = json.loads(unlabeled.stdout)
            self.assertEqual((output["schema_version"], output["positions"]), (2, 16))
            self.assertIsNone(output["conditions"][0]["passes"][0]["all_field_exact"])
            partial_path = self.write(root, "partial", self.partial)
            denied = self.invoke(root, *base, "--labels", partial_path)
            self.assertEqual(denied.returncode, 2)
            self.assertEqual(denied.stdout, "")
            admitted = self.invoke(root, *base, "--labels", partial_path, "--allow-partial-references")
            self.assertEqual(admitted.returncode, 0, admitted.stderr)
            self.assertEqual(json.loads(admitted.stdout), evaluate(self.task, self.plan, self.partial,
                                                                 self.predictions, allow_partial_references=True))
            complete = self.invoke(root, *base, "--labels", self.write(root, "labels", self.labels))
            self.assertEqual(complete.returncode, 0, complete.stderr)
            self.assertEqual(json.loads(complete.stdout), evaluate(self.task, self.plan, self.labels, self.predictions))

    def test_report_cli_saved_synthetic_evidence_private_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="unlabeled-report-") as directory:
            root = Path(directory)
            config = {"schema_version": 1, "task": self.write(root, "task", self.task),
                      "experiment": self.write(root, "experiment", self.experiment),
                      "inputs": self.write(root, "inputs", self.inputs),
                      "database": str(root / "state.sqlite"), "artifacts": str(root / "artifacts"),
                      "scope": "synthetic:unlabeled-report", "cap": 1, "currency": "SYN", "scale": 1,
                      "max_concurrency": 2, "provider_limits": {"synthetic": 2},
                      "authorization_file": None, "on_budget_exhausted": "pause"}
            config_path = self.write(root, "config", config)
            self.assertEqual(run(config_path)["status"], "completed")
            path = root / "unlabeled.html"
            result = self.invoke(root, "report", "--config", config_path, "--out", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = path.read_bytes()
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertIn(b"valid selected predictions: 16", saved)
            self.assertIn(b"Full-denominator exact agreement is unavailable", saved)
            self.assertEqual(json.loads(result.stdout)["visibility"], "private-local")
            repeated = self.invoke(root, "report", "--config", config_path, "--out", str(path))
            self.assertEqual(repeated.returncode, 2)
            self.assertEqual(path.read_bytes(), saved)
            partial_path = self.write(root, "partial", self.partial)
            rejected_path = root / "rejected.html"
            denied = self.invoke(root, "report", "--config", config_path, "--labels", partial_path,
                                 "--out", str(rejected_path))
            self.assertEqual(denied.returncode, 2)
            self.assertFalse(rejected_path.exists())
            accepted = self.invoke(root, "report", "--config", config_path, "--labels", partial_path,
                                   "--allow-partial-references", "--out", str(root / "partial.html"))
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("Reference coverage: partial", (root / "partial.html").read_text())

    def test_integrated_dom_unknown_scores_filters_hash_and_findings_links(self):
        if not shutil.which("node"):
            self.skipTest("local Node.js is not installed")
        if subprocess.run(["node", "-e", "require.resolve('jsdom')"], capture_output=True).returncode:
            self.skipTest("local jsdom is not installed")
        script = r"""
const fs = require('fs');
const assert = require('assert');
const {JSDOM, VirtualConsole} = require('jsdom');
const errors = [];
const console = new VirtualConsole();
console.on('jsdomError', error => errors.push(error.message));
const dom = new JSDOM(fs.readFileSync(0, 'utf8'), {runScripts: 'dangerously',
  url: 'file:///offline/report.html#case-explorer-heading?case=d', virtualConsole: console});
const document = dom.window.document;
const byID = id => document.getElementById(id);
assert.equal(document.querySelector('.jump-nav a[aria-current=location]').hash, '#case-explorer-heading');
assert.equal(byID('explorer-case').value, 'd');
assert(byID('explorer-field-table').textContent.includes('Reference unknown'));
assert.equal(byID('agreement-duration-chart'), null);
assert(byID('plot-status').textContent.includes('lack complete reference coverage'));
const rows = [...document.querySelectorAll('.comparison-table tbody tr')];
rows[0].querySelector('.compare-select').click();
rows[1].querySelector('.compare-select').click();
assert.equal(document.querySelectorAll('.selection-card').length, 2);
assert([...document.querySelectorAll('.selection-card')].every(card => card.textContent.includes('unavailable')));
const filter = document.querySelector('[data-filter=prompt]');
filter.value = 'careful'; filter.dispatchEvent(new dom.window.Event('change'));
assert(byID('condition-0').hidden);
assert(!byID('case-explorer').hidden);
assert([...document.querySelectorAll('.finding')].every(item => !item.hidden));
const link = document.querySelector('.finding-links a');
assert(link);
const target = new URL(link.href).hash;
dom.reconfigure({url: 'file:///offline/report.html' + target});
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'));
assert.equal(byID('explorer-case').value, new URLSearchParams(target.split('?')[1]).get('case'));
assert.equal(document.querySelector('.jump-nav a[aria-current=location]').hash, '#case-explorer-heading');
assert.deepEqual(errors, []);
"""
        html = self.html(self.partial, allow_partial_references=True)
        result = subprocess.run(["node", "-e", script], input=html, text=True,
                                capture_output=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
