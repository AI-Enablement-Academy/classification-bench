"""Download allowlists, privacy modes and exact byte hashes are explicit."""

import copy
import hashlib
import json
import shutil
import subprocess
import unittest

from classification_bench.core import ValidationError, _digest, build_plan, evaluate
from classification_bench.evaluation_provenance import current_provenance, evaluation_identity
from classification_bench.report_analysis import build_analysis
from classification_bench.report_exports import build_report_exports, render_downloads
from classification_bench.report_findings import build_findings


def fixture(context=False):
    task = {"name": "TASK_CANARY", "input_keys": ["message"],
            "fields": [{"name": "FIELD_CANARY", "labels": ["LABEL_CANARY", "alternate"]}]}
    inputs = {"records": [{"id": "CASE_CANARY", "input": {"message": "INPUT_CANARY </script>"}},
                          {"id": "second", "input": {"message": "another"}}]}
    experiment = {"configs": [{"id": "CONFIG_CANARY", "model": "MODEL_CANARY"}],
                  "prompts": [{"id": "PROMPT_CANARY", "text": "PROMPT_TEXT_CANARY"}],
                  "repeats": 2, "batch_size": 1}
    plan = build_plan(task, experiment, inputs)
    labels = {"records": [{"id": "CASE_CANARY", "labels": {"FIELD_CANARY": "LABEL_CANARY"}}]}
    predictions = {"records": [
        {"config_id": "CONFIG_CANARY", "prompt_id": "PROMPT_CANARY", "repeat": 1,
         "id": "CASE_CANARY", "prediction": {"FIELD_CANARY": "LABEL_CANARY"}},
        {"config_id": "CONFIG_CANARY", "prompt_id": "PROMPT_CANARY", "repeat": 1,
         "id": "second", "prediction": "RAW_INVALID_CANARY"}]}
    operations = [{"request_id": plan["requests"][0]["request_id"], "cost_currency": "USD",
                   "observed_cost_micro_usd": 9007199254740993, "reason": "OPERATION_CANARY",
                   "secret_arbitrary_field": "OPERATION_CANARY"}]
    analysis = build_analysis(task, plan, predictions, labels, operations)
    return (analysis, task, plan, predictions, labels) if context else analysis


class ReportExportTests(unittest.TestCase):
    def test_versioned_exports_bind_the_four_inputs_and_exact_scoring_records(self):
        analysis, task, plan, predictions, labels = fixture(context=True)
        before = copy.deepcopy(analysis)
        scored = evaluate(task, plan, labels, predictions, allow_partial_references=True)
        exports = build_report_exports(analysis)
        for mode in ("sanitized", "private"):
            value = json.loads(exports[mode]["payload"])
            record = value["evaluation"]
            self.assertEqual(record["status"], "versioned")
            self.assertEqual(record["evaluation_id"], scored["evaluation_id"])
            self.assertEqual(record["evaluation_provenance"], scored["evaluation_provenance"])
            self.assertEqual(record["analysis_provenance"], analysis["analysis_provenance"])
            sources = {name: value["source_hashes"][name] for name in ("task", "plan", "labels", "predictions")}
            self.assertEqual(record["evaluation_id"], evaluation_identity(sources, record["evaluation_provenance"]))
            self.assertNotIn("CANARY", json.dumps(record))
            self.assertEqual(set(record), {"status", "evaluation_id", "evaluation_provenance", "analysis_provenance"})
        self.assertEqual(analysis, before)

    def test_provenance_export_rejects_changed_logical_sources_and_evaluation_identity(self):
        original = fixture()
        for source in ("task", "plan", "labels", "predictions"):
            with self.subTest(source=source):
                changed = copy.deepcopy(original)
                changed["source_hashes"][source] = "a" * 64
                with self.assertRaisesRegex(ValidationError, "evaluation identity mismatch"):
                    build_report_exports(changed)
        changed = copy.deepcopy(original)
        changed["evaluation_id"] = "a" * 64
        with self.assertRaisesRegex(ValidationError, "evaluation identity mismatch"):
            build_report_exports(changed)

    def test_provenance_allowlist_rejects_partial_records_private_fields_and_wrong_scopes(self):
        original = fixture()
        for missing in ("evaluation_id", "evaluation_provenance", "analysis_provenance"):
            with self.subTest(missing=missing):
                changed = copy.deepcopy(original)
                changed.pop(missing)
                with self.assertRaisesRegex(ValidationError, "incomplete evaluation provenance"):
                    build_report_exports(changed)
        for record in ("evaluation_provenance", "analysis_provenance"):
            with self.subTest(record=record):
                changed = copy.deepcopy(original)
                changed[record]["private_note"] = "PROVENANCE_SECRET_CANARY"
                with self.assertRaisesRegex(ValidationError, "invalid evaluation provenance"):
                    build_report_exports(changed)
                changed = copy.deepcopy(original)
                changed[record]["source_sha256"]["/private/account.json"] = "a" * 64
                with self.assertRaisesRegex(ValidationError, "invalid evaluation provenance"):
                    build_report_exports(changed)
        changed = copy.deepcopy(original)
        changed["analysis_provenance"] = copy.deepcopy(changed["evaluation_provenance"])
        with self.assertRaisesRegex(ValidationError, "invalid evaluation provenance"):
            build_report_exports(changed)
        changed = copy.deepcopy(original)
        changed["evaluation_provenance"]["source_sha256"]["classification_bench/core.py"] = "PROVENANCE_SECRET_CANARY"
        with self.assertRaisesRegex(ValidationError, "invalid evaluation provenance"):
            build_report_exports(changed)

    def test_historical_provenance_is_preserved_and_legacy_analysis_is_not_relabelled(self):
        historical = fixture()
        provenance = historical["evaluation_provenance"]
        provenance["source_sha256"]["classification_bench/core.py"] = "a" * 64
        provenance["implementation_sha256"] = _digest(provenance["source_sha256"])
        provenance["provenance_sha256"] = _digest({key: value for key, value in provenance.items()
                                                  if key != "provenance_sha256"})
        self.assertNotEqual(provenance, current_provenance())
        sources = {name: historical["source_hashes"][name] for name in ("task", "plan", "labels", "predictions")}
        historical["evaluation_id"] = evaluation_identity(sources, provenance)
        historical["analysis_id"] = _digest({"version": 1, "source_hashes": historical["source_hashes"],
            "evaluation_provenance_sha256": provenance["provenance_sha256"],
            "analysis_provenance_sha256": historical["analysis_provenance"]["provenance_sha256"]})
        for item in build_report_exports(historical).values():
            record = json.loads(item["payload"])["evaluation"]
            self.assertEqual(record["evaluation_provenance"], provenance)
            self.assertEqual(record["evaluation_id"], historical["evaluation_id"])
        legacy = fixture()
        for key in ("evaluation_id", "evaluation_provenance", "analysis_provenance"):
            legacy.pop(key)
        before = copy.deepcopy(legacy)
        for item in build_report_exports(legacy).values():
            self.assertEqual(json.loads(item["payload"])["evaluation"], {"status": "unversioned_legacy_analysis"})
        self.assertEqual(legacy, before)

    def test_sanitized_projection_omits_identity_text_taxonomy_and_raw_data(self):
        analysis = fixture()
        exports = build_report_exports(analysis, findings=build_findings(analysis))
        sanitized = exports["sanitized"]["payload"]
        self.assertNotIn("CANARY", sanitized)
        value = json.loads(sanitized)
        self.assertEqual(value["runs"][0]["cases"][0]["prediction"], [0])
        self.assertEqual(value["runs"][0]["cases"][1]["prediction"], [None])
        self.assertEqual(value["runs"][0]["cases"][1]["prediction_status"], "invalid")
        self.assertEqual(value["runs"][0]["cases"][1]["reference_status"], "missing")
        self.assertEqual(value["fields"], [{"field_index": 0, "label_count": 2}])
        self.assertEqual(len(value["agreement_pairs"]), 1)
        self.assertEqual(value["agreement_pairs"][0]["planned"], 2)
        self.assertEqual(value["agreement_pairs"][0]["deferred"], 2)

    def test_private_projection_still_excludes_opaque_provider_and_operation_payloads(self):
        exports = build_report_exports(fixture())
        private = exports["private"]["payload"]
        self.assertIn("INPUT_CANARY", private)
        self.assertIn("CASE_CANARY", private)
        self.assertIn("FIELD_CANARY", private)
        self.assertNotIn("RAW_INVALID_CANARY", private)
        self.assertNotIn("OPERATION_CANARY", private)
        self.assertNotIn("PROMPT_TEXT_CANARY", private)

    def test_pseudonymous_ids_join_across_every_projection(self):
        value = json.loads(build_report_exports(fixture())["sanitized"]["payload"])
        ids = {case["case_id"] for run in value["runs"] for case in run["cases"]}
        self.assertEqual(len(ids), 2)
        self.assertTrue(all(len(cid) == 64 for cid in ids))
        self.assertEqual(set(value["agreement_pairs"][0]["deferred_ids"]), ids)
        self.assertEqual(set(value["cohorts"][0]["case_ids"]), ids)

    def test_canonical_byte_hash_and_large_money_are_exact_and_pure(self):
        analysis = fixture()
        before = copy.deepcopy(analysis)
        exports = build_report_exports(analysis)
        self.assertEqual(analysis, before)
        self.assertEqual(exports, build_report_exports(analysis))
        for mode, item in exports.items():
            payload = item["payload"].encode("utf-8")
            self.assertEqual(hashlib.sha256(payload).hexdigest(), item["sha256"])
            self.assertEqual(len(payload), item["bytes"])
            self.assertEqual(json.loads(payload)["runs"][0]["cost"]["observed_cost_micro_usd"], 9007199254740993)
            self.assertTrue(item["filename"].endswith(mode + ".json"))

    def test_raw_metadata_cannot_masquerade_as_source_digest(self):
        analysis = fixture()
        analysis["source_hashes"]["operations"] = "SECRET_RAW_METADATA"
        with self.assertRaises(ValidationError):
            build_report_exports(analysis)

    def test_field_and_hypothetical_exports_keep_numeric_evidence_without_taxonomy(self):
        from classification_bench.report_metrics import build_field_metrics
        from classification_bench.report_sensitivity import build_sensitivity
        analysis, task, plan, predictions, labels = fixture(context=True)
        metrics = build_field_metrics(analysis)
        scenario = [{"id": "SCENARIO_CANARY", "title": "TITLE_CANARY", "provenance": "PROVENANCE_CANARY",
                     "changes": [{"id": "CASE_CANARY", "labels": {"FIELD_CANARY": "alternate"}}]}]
        sensitivity = build_sensitivity(task, plan, predictions, labels, scenario)
        exports = build_report_exports(analysis, field_metrics=metrics, sensitivity=sensitivity)
        value = json.loads(exports["sanitized"]["payload"])
        self.assertNotIn("CANARY", exports["sanitized"]["payload"])
        field = value["runs"][0]["field_metrics"][0]
        self.assertEqual(field["known_reference_count"], 1)
        self.assertEqual(field["classes"][0]["tp"], 1)
        self.assertEqual(field["classes"][1]["precision"]["value"], None)
        self.assertEqual(field["confusion"], [[1, 0], [0, 0]])
        scenario_run = value["sensitivity"]["scenarios"][0]["runs"][0]
        self.assertEqual(scenario_run["all_fields_delta"]["correct"], -1)
        self.assertIsNone(scenario_run["all_fields"]["full_denominator_rate"])
        self.assertEqual(scenario_run["fields"][0]["confusion"], [[0, 0], [1, 0]])
        self.assertIn("PROVENANCE_CANARY", exports["private"]["payload"])
        self.assertNotIn("RAW_INVALID_CANARY", exports["private"]["payload"])
        self.assertNotIn("OPERATION_CANARY", exports["private"]["payload"])

    def test_cannot_join_projections_from_different_analysis_sources(self):
        from classification_bench.report_metrics import build_field_metrics
        from classification_bench.report_sensitivity import build_sensitivity
        analysis, task, plan, predictions, labels = fixture(context=True)
        metrics = build_field_metrics(analysis)
        metrics["analysis_id"] = "a" * 64
        with self.assertRaises(ValidationError):
            build_report_exports(analysis, field_metrics=metrics)
        findings = build_findings(analysis)
        findings["analysis_id"] = "a" * 64
        with self.assertRaises(ValidationError):
            build_report_exports(analysis, findings=findings)
        sensitivity = build_sensitivity(task, plan, predictions, labels, [])
        sensitivity["source_hashes"]["labels"] = "a" * 64
        with self.assertRaises(ValidationError):
            build_report_exports(analysis, sensitivity=sensitivity)

    def test_download_dom_default_scope_switch_exact_blob_and_inert_text(self):
        if not shutil.which("node") or subprocess.run(["node", "-e", "require.resolve('jsdom')"], capture_output=True).returncode:
            self.skipTest("local Node.js/jsdom unavailable")
        exports = build_report_exports(fixture())
        html = render_downloads(exports)
        self.assertNotIn("INPUT_CANARY </script>", html)
        script = r"""
const fs=require('fs'),assert=require('assert'),zlib=require('zlib'),crypto=require('crypto'),{JSDOM,VirtualConsole}=require('jsdom');
const input=JSON.parse(fs.readFileSync(0,'utf8')),errors=[],saved=[],names=[];
const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(input.html,{runScripts:'dangerously',url:'file:///offline/report.html',virtualConsole:vc,beforeParse(w){
 w.Blob=class {constructor(parts,options){this.parts=parts;this.options=options;}};
 w.URL.createObjectURL=blob=>{saved.push(Buffer.from(blob.parts[0]));return 'blob:offline';};w.URL.revokeObjectURL=()=>{};
 w.HTMLAnchorElement.prototype.click=function(){names.push(this.download);};
}});
const doc=dom.window.document,mode=doc.getElementById('analysis-export-mode'),button=doc.getElementById('analysis-export-download');
assert.equal(mode.value,'sanitized');button.click();const sanitized=zlib.gunzipSync(saved[0]).toString('utf8');assert.equal(sanitized,input.exports.sanitized.payload);assert(!sanitized.includes('CANARY'));
mode.value='private';mode.dispatchEvent(new dom.window.Event('change'));assert(doc.getElementById('analysis-export-notice').textContent.includes('inputs and reference labels'));
button.click();const privateData=zlib.gunzipSync(saved[1]).toString('utf8');assert.equal(privateData,input.exports.private.payload);assert(privateData.includes('INPUT_CANARY'));assert(privateData.includes('9007199254740993'));
const packed=JSON.parse(doc.getElementById('analysis-export-data').textContent);
assert.equal(crypto.createHash('sha256').update(saved[0]).digest('hex'),packed.sanitized.sha256);
assert.equal(crypto.createHash('sha256').update(Buffer.from(privateData)).digest('hex'),packed.private.json_sha256);
assert.deepEqual(names,[input.exports.sanitized.filename+'.gz',input.exports.private.filename+'.gz']);assert.deepEqual(errors,[]);
dom.window.close();
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps({"html": html, "exports": exports}),
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
