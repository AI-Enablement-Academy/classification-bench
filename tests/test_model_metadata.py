"""Declared model facts stay separate from routing, groups and provider input."""

from copy import deepcopy
import json
import unittest

from classification_bench.core import ValidationError, build_plan, validate_experiment
from classification_bench.model_metadata import project_model_metadata, render_model_metadata
from classification_bench.report_analysis import build_analysis
from classification_bench.report_exports import build_report_exports
from classification_bench.report_findings import build_findings
from classification_bench.report_presentation import render_presentation
from classification_bench.report import generate_report
from classification_bench.report_explorer import _panel_data
from tests import test_report_explorer as explorer_tests


def fixture():
    task = {"name": "arbitrary", "input_keys": ["text"],
            "fields": [{"name": "decision", "labels": ["yes", "no"]}]}
    experiment = {"configs": [{"id": "one", "model": "fine-tuned-name-only",
                              "model_type": "decision", "settings": {}}],
                  "prompts": [{"id": "p", "text": "Classify."}], "repeats": 1, "batch_size": 1}
    inputs = {"records": [{"id": "case", "input": {"text": "one"}}]}
    return task, experiment, inputs


def declaration(value="Unrelated family", *, status="operator_declared"):
    result = {"value": value, "status": status, "provenance": "Explicit offline operator fixture",
              "source_urls": ["https://example.org/model-card?source=a&section=family"]}
    if status == "operator_verified":
        result["reviewed_at"] = "2026-10-08T12:00:00Z"
    return result


def with_metadata(metadata):
    task, experiment, inputs = fixture()
    experiment["configs"][0]["model_metadata"] = deepcopy(metadata)
    return task, experiment, inputs


class MetadataValidationTests(unittest.TestCase):
    def test_absent_metadata_preserves_legacy_request_identity_and_bytes(self):
        task, experiment, inputs = fixture()
        plan = build_plan(task, experiment, inputs)
        self.assertEqual(plan["requests"][0]["request_id"],
                         "72b1da368ffd7d96bec3bf33899dcd7ed7f0d0570f8894101b487bfe6007317a")
        self.assertNotIn("model_metadata", plan["experiment"]["configs"][0])

    def test_separate_claims_freeze_identity_without_changing_capsules(self):
        metadata = {"schema_version": 1, "family": declaration(),
                    "declared_purpose": declaration("Classification experiment"),
                    "training_lineage": declaration("Documented training claim", status="operator_verified")}
        task, experiment, inputs = with_metadata(metadata)
        original = deepcopy(experiment)
        plan = build_plan(task, experiment, inputs)
        self.assertEqual(experiment, original)
        self.assertEqual(plan["experiment"]["configs"][0]["model_metadata"], metadata)
        self.assertEqual(plan["requests"][0]["items"], inputs["records"])
        self.assertNotIn("model_metadata", plan["requests"][0])
        metadata["family"]["provenance"] = "A changed source assertion"
        changed = build_plan(*with_metadata(metadata))
        self.assertNotEqual(changed["requests"][0]["request_id"], plan["requests"][0]["request_id"])

    def test_unknowns_are_explicit_and_partial_axes_are_allowed(self):
        for metadata in ({"schema_version": 1}, {"schema_version": 1, "family": {"status": "unknown"}}):
            _, experiment, _ = with_metadata(metadata)
            self.assertIs(validate_experiment(experiment), experiment)

    def test_lineage_and_verified_claims_require_sources_and_review_date(self):
        invalid = []
        for key in ("family", "declared_purpose", "training_lineage"):
            known = declaration(status="operator_verified")
            for change in ({"source_urls": []}, {"reviewed_at": None}, {"reviewed_at": "2026-10-08"},
                           {"reviewed_at": "2026-10-08T12:00:00+02:00"}, {"provenance": " "}):
                invalid.append({"schema_version": 1, key: {**known, **change}})
        invalid.append({"schema_version": 1, "training_lineage": {**declaration(), "source_urls": []}})
        for metadata in invalid:
            with self.subTest(metadata=metadata), self.assertRaises(ValidationError):
                validate_experiment(with_metadata(metadata)[1])


class MetadataProjectionTests(unittest.TestCase):
    def analysis(self, metadata=None):
        task, experiment, inputs = fixture() if metadata is None else with_metadata(metadata)
        plan = build_plan(task, experiment, inputs)
        return build_analysis(task, plan, {"records": []}), task, plan

    def test_reporting_group_and_model_name_never_fill_unknown_declarations(self):
        analysis, _, _ = self.analysis()
        self.assertNotIn("model_metadata", analysis["runs"][0])
        projection = project_model_metadata(analysis["runs"][0]["configuration"])
        self.assertIs(projection["supplied"], False)
        self.assertIsNone(projection["metadata_sha256"])
        for axis in ("family", "declared_purpose", "training_lineage"):
            self.assertEqual(projection[axis]["status"], "unknown")
            self.assertIsNone(projection[axis]["value"])
        self.assertEqual(analysis["runs"][0]["model_type"], "decision")

    def test_run_projection_is_sourced_immutable_and_has_no_independent_verification_claim(self):
        metadata = {"schema_version": 1, "family": declaration("FAMILY_CANARY"),
                    "training_lineage": declaration("TRAINING_CANARY", status="operator_verified")}
        analysis, _, plan = self.analysis(metadata)
        run = analysis["runs"][0]
        self.assertEqual(run["model_metadata"]["family"]["value"], "FAMILY_CANARY")
        self.assertEqual(run["model_metadata"]["declared_purpose"]["status"], "unknown")
        self.assertEqual(len(run["model_metadata"]["metadata_sha256"]), 64)
        self.assertIn("not independently verified", run["model_metadata"]["verification_note"])
        run["model_metadata"]["family"]["source_urls"].clear()
        self.assertEqual(plan["experiment"]["configs"][0]["model_metadata"], metadata)

    def test_explorer_reuses_frozen_declarations_across_independently_selected_repeats(self):
        task, experiment, inputs = with_metadata({"schema_version": 1, "family": declaration()})
        experiment["repeats"] = 10
        analysis = build_analysis(task, build_plan(task, experiment, inputs), {"records": []})
        panel = _panel_data(analysis)
        self.assertEqual(len(panel["model_metadata"]), 1)
        self.assertEqual(len(panel["runs"]), 10)
        self.assertEqual({run["model_metadata_sha256"] for run in panel["runs"]}, set(panel["model_metadata"]))
        self.assertTrue(all(run["counts"]["planned"] == 1 for run in panel["runs"]))

    def test_exports_allowlist_private_sources_but_sanitize_claim_text_and_urls(self):
        analysis, _, _ = self.analysis({"schema_version": 1,
                                       "training_lineage": declaration("TRAINING_CANARY", status="operator_verified")})
        original = deepcopy(analysis)
        downloads = build_report_exports(analysis)
        private = json.loads(downloads["private"]["payload"])["runs"][0]["model_metadata"]
        sanitized = json.loads(downloads["sanitized"]["payload"])["runs"][0]["model_metadata"]
        self.assertEqual(private["training_lineage"]["value"], "TRAINING_CANARY")
        self.assertEqual(private["training_lineage"]["source_urls"], declaration()["source_urls"])
        self.assertEqual(sanitized["training_lineage"], {"status": "operator_verified"})
        self.assertEqual(private["metadata_sha256"], sanitized["metadata_sha256"])
        for text in ("TRAINING_CANARY", "example.org", "Explicit offline operator fixture", "2026-10-08"):
            self.assertNotIn(text, downloads["sanitized"]["payload"])
        self.assertEqual(analysis, original)
        legacy, _, _ = self.analysis()
        self.assertNotIn("model_metadata", json.loads(build_report_exports(legacy)["private"]["payload"])["runs"][0])

    def test_report_and_presentation_show_exact_sources_with_escaped_claims(self):
        claim = declaration("<script>window.metadataInjected=true</script>", status="operator_verified")
        claim["provenance"] = "Source <img src=x onerror=alert(1)>"
        analysis, task, plan = self.analysis({"schema_version": 1, "training_lineage": claim})
        html = generate_report(task, plan, predictions={"records": []})
        slides = render_presentation(analysis, build_findings(analysis))
        for document in (html, slides, render_model_metadata(plan["experiment"]["configs"][0])):
            self.assertIn("Operator verified declaration", document)
            self.assertIn("2026-10-08T12:00:00Z", document)
            self.assertIn("https://example.org/model-card?source=a&amp;section=family", document)
            self.assertNotIn("<script>window.metadataInjected", document)
            self.assertNotIn("<img src=x", document)
            self.assertIn("do not establish causes", document)

    def test_selected_ab_explorer_retains_exact_declarations_unknowns_and_safe_source_links(self):
        task, experiment, inputs = with_metadata({"schema_version": 1, "family": declaration("<script>inert</script>")})
        experiment["configs"].append({"id": "two", "model": "llm-looking-name", "model_type": "llm"})
        analysis = build_analysis(task, build_plan(task, experiment, inputs), {"records": []})
        # Reject an unsafe source at the DOM boundary even if an external caller tampers with a projection.
        analysis["runs"][0]["model_metadata"]["family"]["source_urls"].append("javascript:alert(1)")
        check = r"""
const panel = byID('explorer-model-declarations');
assert.equal(panel.querySelectorAll('details').length, 1);
assert(panel.textContent.includes('<script>inert</script>'));
assert.equal(panel.querySelectorAll('script').length, 0);
assert.equal(panel.querySelectorAll('a').length, 1);
assert(panel.querySelector('a').href.startsWith('https://example.org/'));
assert(panel.textContent.includes('Operator declaration'));
const second = [...byID('explorer-compare').options].find(option => option.value && option.textContent.includes('two'));
change('explorer-compare', second.value);
assert.equal(panel.querySelectorAll('details').length, 2);
assert(panel.lastElementChild.textContent.includes('Unknown; no sourced declaration supplied.'));
assert(panel.lastElementChild.textContent.includes('Declared reporting group: llm'));
assert(byID('explorer-counts').textContent.includes('1 planned'));
assert.equal(dom.window.metadataInjected, undefined);
"""
        explorer_tests.ReportExplorerTests().dom_check(check, analysis=analysis)

    def test_operator_intent_can_use_nonpublic_provenance_without_claiming_verification(self):
        purpose = {**declaration("Task author's declared purpose"), "source_urls": []}
        validate_experiment(with_metadata({"schema_version": 1, "declared_purpose": purpose})[1])

    def test_unrecognized_types_claims_and_unsafe_source_urls_are_rejected(self):
        invalid = [None, [], {"schema_version": True}, {"schema_version": 2},
                   {"schema_version": 1, "model_type": "decision"},
                   {"schema_version": 1, "family": {"status": "unknown", "value": "Claim"}},
                   {"schema_version": 1, "family": {**declaration(), "status": "independently_verified"}},
                   {"schema_version": 1, "family": {**declaration(), "value": None}},
                   {"schema_version": 1, "family": {**declaration(), "reviewed_at": "2026-10-08T12:00:00Z"}}]
        for url in ("javascript:alert(1)", "file:///private/model-card", "data:text/html,test", "//example.org/path",
                    "https://user:secret@example.org/path", "https://", "https://example.org/with space",
                    "https://example.org/\\path", "https://example.org/\npath"):
            invalid.append({"schema_version": 1, "family": {**declaration(), "source_urls": [url]}})
        for metadata in invalid:
            with self.subTest(metadata=metadata), self.assertRaises(ValidationError):
                validate_experiment(with_metadata(metadata)[1])


if __name__ == "__main__":
    unittest.main()
