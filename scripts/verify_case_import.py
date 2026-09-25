#!/usr/bin/env python3
"""Verify one saved candidate-experience run against the offline generic core.

Reads explicit external paths only. No inference, writes, or private data export by default.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from classification_bench.core import build_plan, evaluate


FIELDS = {
    "sentiment": ["positive", "negative", "mixed", "neutral", "insufficient_information"],
    "follow_up_needed": ["yes", "no", "insufficient_information"],
    "serious_concern_reported": ["yes", "no", "insufficient_information"],
    "testimonial_potential": ["yes", "no", "insufficient_information"],
}


def source(path, expected_hash, jsonl=False):
    raw = Path(path).read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != expected_hash.lower():
        raise ValueError(f"SHA-256 mismatch for {path}: {actual_hash}")
    text = raw.decode("utf-8")
    data = [json.loads(line) for line in text.splitlines() if line.strip()] if jsonl else json.loads(text)
    return data, actual_hash


def exact_ids(rows, name):
    ids = [row["id"] for row in rows]
    if len(ids) != 60 or len(set(ids)) != 60:
        raise ValueError(f"{name} must have exactly 60 unique IDs")
    return ids


def verify(args):
    inputs, input_hash = source(args.inputs, args.inputs_sha256, True)
    refs, ref_hash = source(args.references, args.references_sha256, True)
    saved, saved_hash = source(args.responses, args.responses_sha256, True)
    old, old_hash = source(args.evaluation, args.evaluation_sha256)
    ids = exact_ids(inputs, "inputs")
    if ids != exact_ids(refs, "references") or ids != exact_ids(saved, "responses"):
        raise ValueError("ordered IDs differ between inputs, references, and responses")
    if any(set(row) != {"id", "feedback"} or not isinstance(row["feedback"], str)
           for row in inputs):
        raise ValueError("unexpected input schema")
    if any(set(row["proposed_labels"]) != set(FIELDS) or any(
            row["proposed_labels"][key] not in vocabulary for key, vocabulary in FIELDS.items())
           for row in refs):
        raise ValueError("unexpected reference labels")
    if any(row.get("status") != "ok" or not isinstance(row.get("prediction"), dict)
           or set(row["prediction"]) != set(FIELDS) or any(
               row["prediction"][key] not in vocabulary for key, vocabulary in FIELDS.items())
           for row in saved):
        raise ValueError("this import requires 60 status=ok, strictly valid native predictions")

    task = {"name": "candidate-experience-historical-import", "input_keys": ["feedback"],
            "fields": [{"name": key, "labels": vocabulary} for key, vocabulary in FIELDS.items()]}
    experiment = {"configs": [{"id": "historical-openjev-fixed", "model": "openjev-0.1"}],
                  "prompts": [{"id": "historical-import", "text": "Offline replay of saved predictions; historical native request is not reconstructed."}],
                  "repeats": 1, "batch_size": 1}
    capsules = {"records": [{"id": row["id"], "input": {"feedback": row["feedback"]}} for row in inputs]}
    labels = {"records": [{"id": row["id"], "labels": row["proposed_labels"]} for row in refs]}
    predictions = {"records": [{"config_id": "historical-openjev-fixed", "prompt_id": "historical-import",
                                "repeat": 1, "id": row["id"], "prediction": row["prediction"]} for row in saved]}
    result = evaluate(task, build_plan(task, experiment, capsules), labels, predictions)
    scored = result["conditions"][0]["passes"][0]
    correct = {key: sum(row["prediction"][key] == ref["proposed_labels"][key]
                        for row, ref in zip(saved, refs)) for key in FIELDS}
    old_correct = {key: old["metrics"][key]["correct"] for key in FIELDS}
    core_correct = {key: sum(scored["fields"][key]["confusion"][label][label]
                             for label in vocabulary) for key, vocabulary in FIELDS.items()}
    core_label_counts = {key: {label: {metric: scored["fields"][key]["labels"][label][metric]
                                       for metric in ("tp", "fp", "fn")}
                               for label in vocabulary} for key, vocabulary in FIELDS.items()}
    old_label_counts = {key: {label: {metric: old["metrics"][key]["per_label"][label][metric]
                                      for metric in ("tp", "fp", "fn")}
                              for label in vocabulary} for key, vocabulary in FIELDS.items()}
    all_four = sum(row["prediction"] == ref["proposed_labels"] for row, ref in zip(saved, refs))
    checks = {"source_records": old["records"] == 60,
              "source_valid": old["valid_outputs"] == 60 and old["missing_or_failed"] == [],
              "generic_valid": result["positions"] == 60 and result["missing"] == 0
                               and result["invalid"] == [] and scored["missing"] == 0
                               and scored["invalid"] == 0,
              "per_field": old_correct == core_correct == correct
                           and all(old["metrics"][key]["denominator"] == 60 for key in FIELDS),
              "per_label_tp_fp_fn": core_label_counts == old_label_counts,
              "all_four": scored["all_field_exact"] == all_four}
    report = {"status": "verified" if all(checks.values()) else "mismatch",
              "source_sha256_bytes": {"inputs": input_hash, "references": ref_hash,
                                      "responses": saved_hash, "evaluation": old_hash},
              "checks": checks,
              "counts": {"records": 60, "valid": 60, "per_field_correct": core_correct,
                         "all_four_correct": scored["all_field_exact"]},
              "all_four_source_evaluation_available": False,
              "generic_source_hashes_canonical_json": result["source_hashes"]}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "references", "responses", "evaluation"):
        parser.add_argument(f"--{name}", required=True)
        parser.add_argument(f"--{name}-sha256", required=True)
    parser.add_argument("--out", help="Optional new report file; never overwritten")
    args = parser.parse_args()
    try:
        report = verify(args)
        content = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.out:
            with Path(args.out).open("x", encoding="utf-8") as target:
                target.write(content)
        else:
            sys.stdout.write(content)
        return 0 if report["status"] == "verified" else 1
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        parser.exit(2, f"case import verification: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
