"""User-owned task imports and frozen provenance, without provider calls."""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from classification_bench.core import ValidationError, build_plan
from classification_bench.task_setup import (
    import_task, initialize_task, read_specification, validate_setup, validate_specification,
)


ROOT = Path(__file__).resolve().parents[1]


class TaskSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "selected"
        self.source.mkdir()
        (self.source / "rubric.txt").write_bytes(b"Use the declared vocabulary and supplied evidence.\r\n")
        (self.source / "sop.txt").write_bytes(b"Check every decision field.\n")
        (self.source / "direct.txt").write_bytes(b"Classify the record.\n")
        (self.source / "careful.txt").write_bytes(b"Check the evidence before choosing each label.\n")

    def specification(self, kind="support"):
        if kind == "candidate":
            task = {"name": "my-feedback-review", "input_keys": ["feedback"], "fields": [
                {"name": "tone", "labels": ["positive", "negative", "insufficient"]},
                {"name": "reply", "labels": ["yes", "no"]},
            ]}
            rows = [
                ["feedback-A", "The interviewer explained the process clearly.", "positive", "yes",
                 "SECRET_REFERENCE_NOTE", "smoke"],
                ["feedback-B", "Nobody replied to my follow-up.", "negative", "no", "reviewed", "holdout"],
            ]
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerow(["stable_id", "comment", "tone_ref", "reply_ref", "review", "split"])
            writer.writerows(rows)
            (self.source / "records.csv").write_bytes(stream.getvalue().encode("utf-8"))
            source = {"path": "records.csv", "format": "csv"}
            mapping = {"id": ["stable_id"], "inputs": {"feedback": ["comment"]}, "split": ["split"]}
            refs = {"source": dict(source), "mapping": {"id": ["stable_id"],
                    "labels": {"tone": ["tone_ref"], "reply": ["reply_ref"]}, "notes": ["review"]}}
        else:
            task = {"name": "user-defined-support-routing", "input_keys": ["message", "account_context"],
                    "fields": [{"name": "queue", "labels": ["billing", "access", "other"]},
                               {"name": "priority", "labels": ["standard", "urgent"]}]}
            rows = [{"record_id": "ticket-α", "payload": {"body": "Please send a receipt.",
                                                            "account": "individual"}},
                    {"record_id": "ticket-B", "payload": {"body": "I cannot sign in.",
                                                           "account": "team"}}]
            (self.source / "records.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
            references = [{"record_id": "ticket-α", "decisions": {"queue": "billing", "priority": "standard"},
                           "review": "SECRET_REFERENCE_NOTE"},
                          {"record_id": "ticket-B", "decisions": {"queue": "access", "priority": "standard"}}]
            (self.source / "references.json").write_text(json.dumps(references), encoding="utf-8")
            source = {"path": "records.jsonl", "format": "jsonl"}
            mapping = {"id": ["record_id"], "inputs": {"message": ["payload", "body"],
                                                         "account_context": ["payload", "account"]}}
            refs = {"source": {"path": "references.json", "format": "json"}, "mapping": {
                "id": ["record_id"], "labels": {"queue": ["decisions", "queue"],
                                                   "priority": ["decisions", "priority"]}, "notes": ["review"]}}
        return {"schema_version": 1, "task": task, "source": source, "mapping": mapping,
                "references": refs, "instructions": {"rubric": "rubric.txt", "sop": "sop.txt"},
                "prompts": [{"id": "direct", "path": "direct.txt"},
                            {"id": "careful", "path": "careful.txt"}],
                "configs": [{"id": "local-check", "model": "synthetic-only", "settings": {
                    "adapter": "synthetic", "response_mode": "first_label"}}],
                "repeats": 2, "batch_size": 1}

    def write_spec(self, spec, filename="setup.json"):
        path = self.source / filename
        path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def load(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def invoke(self, *args, success=True):
        result = subprocess.run([sys.executable, "-m", "classification_bench", *map(str, args)],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout) if result.stdout.strip() else None
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def test_two_user_owned_usecases_cli_import_plan_and_synthetic_run(self):
        for kind in ("candidate", "support"):
            with self.subTest(kind=kind):
                spec_path = self.write_spec(self.specification(kind), kind + "-setup.json")
                selected = self.root / (kind + "-initialized")
                initialized = self.invoke("init", "--spec", spec_path, "--directory", selected)
                self.assertEqual(initialized["source_files_read"], 0)
                frozen = self.root / (kind + "-frozen")
                imported = self.invoke("import", "--spec", initialized["setup"], "--directory", frozen)
                self.assertEqual(imported["reference_status"], "complete")
                self.assertEqual(imported["record_count"], 2)
                self.assertTrue(self.invoke("validate", "--directory", frozen)["valid"])
                execution = self.root / (kind + "-execution")
                execution.mkdir()
                plan_path = execution / "plan.json"
                result = self.invoke("plan", "--task", frozen / "task.json", "--experiment",
                                     frozen / "experiment.json", "--inputs", frozen / "inputs.json",
                                     "--out", plan_path)
                # File output has no stdout; plan is verified below through saved bytes.
                self.assertEqual(result, None)
                plan = self.load(plan_path)
                self.assertEqual(len(plan["requests"]), 8)
                for request in plan["requests"]:
                    for item in request["items"]:
                        self.assertEqual(set(item), {"id", "input"})
                        self.assertEqual(set(item["input"]), set(plan["task"]["input_keys"]))
                self.assertNotIn("SECRET_REFERENCE_NOTE", json.dumps(plan))
                config = {"schema_version": 1, "task": str(frozen / "task.json"),
                          "experiment": str(frozen / "experiment.json"), "inputs": str(frozen / "inputs.json"),
                          "database": str(execution / "run.sqlite"), "artifacts": str(execution / "artifacts"),
                          "scope": "synthetic:" + kind, "cap": 100, "currency": "SYN", "scale": 1,
                          "max_concurrency": 1, "provider_limits": {"synthetic": 1},
                          "authorization_file": None, "on_budget_exhausted": "pause"}
                config_path = execution / "config.json"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                run = self.invoke("run", "--config", config_path)
                self.assertEqual(run["completed_requests"], 8)
                predictions = self.invoke("export", "--config", config_path)
                prediction_path = execution / "predictions.json"
                prediction_path.write_text(json.dumps(predictions), encoding="utf-8")
                scored = self.invoke("evaluate", "--task", frozen / "task.json", "--plan", plan_path,
                                     "--labels", frozen / "references/labels.json", "--predictions", prediction_path)
                self.assertEqual(scored["positions"], 8)
                self.assertEqual(scored["missing"], 0)
                self.assertEqual(scored["invalid"], [])
                self.assertEqual(scored["conditions"][0]["passes"][0]["all_field_exact"], 1)
                self.assertTrue(validate_setup(frozen)["valid"])

    def test_initialization_validates_structure_without_reading_source_files(self):
        spec = self.specification()
        spec["source"]["path"] = "not-yet-created.jsonl"
        selected = self.root / "init"
        result = initialize_task(selected, spec, base_directory=self.source)
        self.assertEqual(result["source_files_read"], 0)
        self.assertEqual(self.load(selected / "setup.json")["source"]["path"],
                         str(self.source.resolve() / "not-yet-created.jsonl"))
        self.assertEqual(spec["source"]["path"], "not-yet-created.jsonl")

    def test_deterministic_files_exact_provenance_and_private_permissions(self):
        spec_path = self.write_spec(self.specification("candidate"))
        first, second = self.root / "one", self.root / "two"
        import_task(spec_path, first)
        import_task(spec_path, second)
        first_files = {str(p.relative_to(first)): p.read_bytes() for p in first.rglob("*") if p.is_file()}
        second_files = {str(p.relative_to(second)): p.read_bytes() for p in second.rglob("*") if p.is_file()}
        self.assertEqual(first_files, second_files)
        self.assertEqual(first_files["provenance/setup.json"], spec_path.read_bytes())
        self.assertEqual(first_files["provenance/inputs-source.csv"], (self.source / "records.csv").read_bytes())
        self.assertEqual(first_files["provenance/rubric.txt"], (self.source / "rubric.txt").read_bytes())
        expected = "Use the declared vocabulary and supplied evidence.\r\n\n\nCheck every decision field.\n\n\nClassify the record.\n"
        self.assertEqual(self.load(first / "experiment.json")["prompts"][0]["text"], expected)
        for path in [first, *first.rglob("*")]:
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)

    def test_originals_can_change_or_disappear_without_affecting_frozen_validation(self):
        spec_path = self.write_spec(self.specification())
        destination = self.root / "frozen"
        import_task(spec_path, destination)
        for path in self.source.iterdir():
            path.unlink()
        self.assertTrue(validate_setup(destination)["valid"])

    def test_original_symlink_target_change_does_not_change_frozen_binding(self):
        spec = self.specification()
        os.symlink("records.jsonl", self.source / "selected-link.jsonl")
        spec["source"]["path"] = "selected-link.jsonl"
        destination = self.root / "frozen"
        import_task(self.write_spec(spec), destination)
        (self.source / "selected-link.jsonl").unlink()
        os.symlink("not-there.jsonl", self.source / "selected-link.jsonl")
        self.assertTrue(validate_setup(destination)["valid"])

    def test_json_envelope_path_and_arbitrary_names_labels_and_split_names(self):
        spec = self.specification()
        records = [{"record_id": "a", "payload": {"body": "receipt", "account": "solo"}},
                   {"record_id": "b", "payload": {"body": "access", "account": "team"}}]
        (self.source / "wrapped.json").write_text(json.dumps({"version": 9, "data": {"items": records}}))
        spec["source"] = {"path": "wrapped.json", "format": "json", "records_path": ["data", "items"]}
        del spec["references"]
        spec["task"]["name"] = "custom / task Ω"
        spec["splits"] = {"../not-a-path": ["b"], "development": ["a"]}
        destination = self.root / "frozen"
        result = import_task(self.write_spec(spec), destination)
        self.assertEqual(result["reference_status"], "unlabeled")
        splits = self.load(destination / "splits.json")["splits"]
        self.assertEqual([s["name"] for s in splits], ["../not-a-path", "development"])
        self.assertEqual(splits[0]["inputs"], "splits/0001/inputs.json")
        self.assertEqual(splits[0]["ids"], ["b"])

    def test_explicit_split_membership_preserves_source_order(self):
        spec = self.specification()
        spec["splits"] = {"reversed-selection": ["ticket-B", "ticket-α"]}
        destination = self.root / "frozen"
        import_task(self.write_spec(spec), destination)
        self.assertEqual(self.load(destination / "splits.json")["splits"][0]["ids"], ["ticket-α", "ticket-B"])

    def test_partial_references_are_separate_and_missing_fields_are_explicit(self):
        spec = self.specification()
        refs = [{"record_id": "ticket-α", "decisions": {"queue": "billing", "priority": None},
                 "review": "SECRET_REFERENCE_NOTE"}]
        (self.source / "references.json").write_text(json.dumps(refs))
        destination = self.root / "partial"
        result = import_task(self.write_spec(spec), destination)
        self.assertEqual(result["reference_status"], "partial")
        self.assertIsNone(result["labels"])
        self.assertFalse((destination / "references/labels.json").exists())
        self.assertEqual(result["missing_reference_fields"], 3)
        projection = self.load(destination / result["reference_projection"])
        self.assertEqual(projection, {"records": [{"id": "ticket-α", "labels": {"queue": "billing"}}]})
        self.assertEqual(self.load(destination / "references/coverage.json")["records"], [
            {"id": "ticket-α", "missing_fields": ["priority"]},
            {"id": "ticket-B", "missing_fields": ["queue", "priority"]}])
        self.assertTrue(validate_setup(destination)["valid"])

    def test_unlabeled_sources_have_no_accuracy_reference_artifact(self):
        spec = self.specification()
        del spec["references"]
        destination = self.root / "unlabeled"
        result = import_task(self.write_spec(spec), destination)
        self.assertEqual(result["reference_status"], "unlabeled")
        self.assertIsNone(result["labels"])
        self.assertIsNone(result["reference_projection"])
        self.assertEqual(result["missing_reference_fields"], 4)
        plan = build_plan(self.load(destination / "task.json"), self.load(destination / "experiment.json"),
                          self.load(destination / "inputs.json"))
        self.assertEqual(len(plan["requests"]), 8)

    def test_duplicate_input_ids_and_nonstring_inputs_are_rejected_before_writing(self):
        for bad in (
            [{"record_id": "a", "payload": {"body": "one", "account": "team"}},
             {"record_id": "a", "payload": {"body": "two", "account": "solo"}}],
            [{"record_id": 12, "payload": {"body": "one", "account": "team"}}],
            [{"record_id": "a", "payload": {"body": {"nested": "text"}, "account": "team"}}],
        ):
            with self.subTest(records=bad):
                spec = self.specification()
                del spec["references"]
                (self.source / "records.jsonl").write_text("\n".join(json.dumps(r) for r in bad) + "\n")
                destination = self.root / "bad"
                with self.assertRaises(ValidationError):
                    import_task(self.write_spec(spec), destination)
                self.assertFalse(destination.exists())

    def test_duplicate_unknown_and_malformed_reference_labels_are_rejected(self):
        invalid = [
            [{"record_id": "ticket-α", "decisions": {"queue": "billing", "priority": "standard"}}] * 2,
            [{"record_id": "unknown", "decisions": {"queue": "billing", "priority": "standard"}}],
            [{"record_id": "ticket-α", "decisions": {"queue": " billing", "priority": "standard"}}],
            [{"record_id": "ticket-α", "decisions": {"queue": True, "priority": "standard"}}],
            [{"record_id": "ticket-α", "decisions": {"queue": "", "priority": "standard"}}],
            [{"record_id": "ticket-α", "decisions": ["billing", "standard"]}],
            [{"record_id": "ticket-α", "decisions": 7}],
        ]
        for records in invalid:
            with self.subTest(records=records):
                spec = self.specification()
                (self.source / "references.json").write_text(json.dumps(records))
                with self.assertRaises(ValidationError):
                    import_task(self.write_spec(spec), self.root / "invalid")
                self.assertFalse((self.root / "invalid").exists())

    def test_csv_blank_labels_are_missing_but_label_whitespace_is_not_trimmed(self):
        spec = self.specification("candidate")
        raw = (self.source / "records.csv").read_text()
        (self.source / "records.csv").write_text(raw.replace(",negative,no,", ",,no,"))
        result = import_task(self.write_spec(spec), self.root / "partial")
        self.assertEqual(result["reference_status"], "partial")
        self.assertEqual(result["missing_reference_fields"], 1)
        spec = self.specification("candidate")
        raw = (self.source / "records.csv").read_text()
        (self.source / "records.csv").write_text(raw.replace(",negative,no,", ", negative,no,"))
        with self.assertRaisesRegex(ValidationError, "unknown or non-string label"):
            import_task(self.write_spec(spec), self.root / "bad")

    def test_malformed_json_jsonl_and_csv_do_not_publish_a_dataset(self):
        cases = [("jsonl", b'{"record_id":"a","record_id":"b"}\n'),
                 ("jsonl", b'{}\n\n'), ("jsonl", b'{"x": NaN}\n'),
                 ("json", b'{"records": []'), ("csv", b"id,id\na,b\n"),
                 ("csv", b"id,body\na,b,extra\n"), ("csv", b'id,body\na,"unterminated\n')]
        for index, (format_name, content) in enumerate(cases):
            with self.subTest(format=format_name, content=content):
                spec = self.specification()
                spec["source"] = {"path": "malformed." + format_name, "format": format_name}
                if format_name == "csv":
                    spec["mapping"] = {"id": ["id"], "inputs": {"message": ["body"],
                                                                               "account_context": ["body"]}}
                del spec["references"]
                (self.source / spec["source"]["path"]).write_bytes(content)
                destination = self.root / ("bad-" + str(index))
                with self.assertRaises(ValidationError):
                    import_task(self.write_spec(spec), destination)
                self.assertFalse(destination.exists())

    def test_splits_reject_duplicates_unknowns_omissions_and_conflicting_mapping(self):
        for splits in ({"one": ["ticket-α"]}, {"one": ["ticket-α", "ticket-B", "unknown"]},
                       {"one": ["ticket-α", "ticket-B"], "two": ["ticket-B"]}):
            with self.subTest(splits=splits):
                spec = self.specification()
                spec["splits"] = splits
                with self.assertRaises(ValidationError):
                    import_task(self.write_spec(spec), self.root / "bad")
        spec = self.specification("candidate")
        spec["splits"] = {"all": ["feedback-A", "feedback-B"]}
        with self.assertRaisesRegex(ValidationError, "choose explicit"):
            validate_specification(spec)

    def test_selected_reference_or_notes_field_cannot_be_an_input_from_the_same_source(self):
        for selected in ("tone_ref", "review"):
            with self.subTest(selected=selected):
                spec = self.specification("candidate")
                spec["mapping"]["inputs"]["feedback"] = [selected]
                with self.assertRaisesRegex(ValidationError, "overlaps an input"):
                    import_task(self.write_spec(spec), self.root / "bad")
        # A copy or symlink of the source must not bypass this mapping check.
        spec = self.specification("candidate")
        (self.source / "alias.csv").write_bytes((self.source / "records.csv").read_bytes())
        spec["references"]["source"]["path"] = "alias.csv"
        spec["mapping"]["inputs"]["feedback"] = ["tone_ref"]
        with self.assertRaisesRegex(ValidationError, "overlaps an input"):
            import_task(self.write_spec(spec), self.root / "bad")

    def test_unknown_setup_keys_and_duplicate_prompt_ids_are_rejected(self):
        spec = self.specification()
        spec["unexpected"] = True
        with self.assertRaises(ValidationError):
            validate_specification(spec)
        spec = self.specification()
        spec["prompts"][1]["id"] = spec["prompts"][0]["id"]
        with self.assertRaises(ValidationError):
            validate_specification(spec)

    def test_strict_specification_reader_and_cli_init_reject_duplicate_keys(self):
        spec_path = self.write_spec(self.specification())
        content = spec_path.read_text().replace('"schema_version": 1,',
                                               '"schema_version": 1, "schema_version": 1,')
        spec_path.write_text(content)
        with self.assertRaisesRegex(ValidationError, "duplicate object key"):
            read_specification(spec_path)
        destination = self.root / "duplicate-spec"
        error = self.invoke("init", "--spec", spec_path, "--directory", destination, success=False)
        self.assertIn("duplicate object key", error.stderr)
        self.assertFalse(destination.exists())

    def test_unicode_line_separator_in_jsonl_text_is_preserved(self):
        spec = self.specification()
        del spec["references"]
        record = {"record_id": "unicode", "payload": {"body": "First\u2028second\u0085third",
                                                         "account": "team"}}
        (self.source / "records.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n")
        destination = self.root / "unicode"
        import_task(self.write_spec(spec), destination)
        self.assertEqual(self.load(destination / "inputs.json")["records"][0]["input"]["message"],
                         "First\u2028second\u0085third")

    def test_no_overwrites_and_cli_errors_preserve_existing_outputs(self):
        spec_path = self.write_spec(self.specification())
        output = self.root / "frozen"
        import_task(spec_path, output)
        before = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
        self.invoke("import", "--spec", spec_path, "--directory", output, success=False)
        self.assertEqual(before, {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()})
        initialized = self.root / "initialized"
        initialize_task(initialized, self.specification(), base_directory=self.source)
        saved = (initialized / "setup.json").read_bytes()
        self.invoke("init", "--spec", spec_path, "--directory", initialized, success=False)
        self.assertEqual((initialized / "setup.json").read_bytes(), saved)

    def test_validation_rejects_modified_inputs_and_rehashed_derived_documents(self):
        spec_path = self.write_spec(self.specification())
        destination = self.root / "frozen"
        import_task(spec_path, destination)
        inputs = self.load(destination / "inputs.json")
        inputs["records"][0]["input"]["message"] = "modified after freezing"
        content = (json.dumps(inputs, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        (destination / "inputs.json").write_bytes(content)
        with self.assertRaisesRegex(ValidationError, "hash mismatch"):
            validate_setup(destination)
        manifest = self.load(destination / "setup-manifest.json")
        for entry in manifest["files"]:
            if entry["path"] == "inputs.json":
                entry["sha256"] = hashlib.sha256(content).hexdigest()
        (destination / "setup-manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValidationError, "do not match the import"):
            validate_setup(destination)

    def test_validation_rejects_extra_files_and_symlinked_artifacts(self):
        spec_path = self.write_spec(self.specification())
        destination = self.root / "frozen"
        import_task(spec_path, destination)
        extra = destination / "accidental.txt"
        extra.write_text("private content")
        with self.assertRaisesRegex(ValidationError, "unexpected files"):
            validate_setup(destination)
        extra.unlink()
        artifact = destination / "inputs.json"
        original = self.root / "outside.json"
        artifact.rename(original)
        os.symlink(original, artifact)
        with self.assertRaisesRegex(ValidationError, "symbolic links"):
            validate_setup(destination)


if __name__ == "__main__":
    unittest.main()
