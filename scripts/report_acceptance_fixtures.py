"""Generate fictional, offline report states for exact-artifact operator checks.

Run from the checkout with ``python3 -m scripts.report_acceptance_fixtures
--directory /private/new-directory``. No provider configuration or dispatch is
used. The network guard is a Python test guard, not process isolation.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
from unittest.mock import patch

from classification_bench.core import build_plan, evaluate
from classification_bench.report import generate_report


def generate(directory):
    root = Path(__file__).resolve().parents[1]
    target = Path(directory).absolute()
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    files = []

    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    def save(name, value):
        payload = (value if isinstance(value, str) else
                   json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        files.append({"file": name, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})

    def deny_network(*args, **kwargs):
        raise AssertionError("Acceptance fixture generation must remain offline")

    with patch.object(socket.socket, "connect", deny_network), patch.object(socket, "create_connection", deny_network):
        source = root / "examples"
        task, experiment, inputs, labels, predictions = (
            read(source / (name + ".json"))
            for name in ("task", "experiment", "inputs", "labels", "predictions"))
        plan = build_plan(task, experiment, inputs)
        complete = copy.deepcopy(predictions)
        # Deliberately repair only this fictional fixture to exercise a fully
        # valid report. Original fixture bytes and historical results stay intact.
        for record in complete["records"]:
            for field in task["fields"]:
                if record["prediction"][field["name"]] not in field["labels"]:
                    record["prediction"][field["name"]] = field["labels"][0]
        partial = copy.deepcopy(labels)
        partial["records"] = partial["records"][:1]
        cases = [("complete", labels, complete, False, []),
                 ("invalid", labels, predictions, False, []),
                 ("partial", partial, predictions, True, []),
                 ("unlabeled", None, predictions, False, []),
                 ("all-missing", labels, {"records": []}, False, [])]
        failed = [{"request_id": request["request_id"], "state": "failed",
                   "reason": "Fictional failure fixture; no dispatch occurred",
                   "route": "synthetic:acceptance-fixture", "cost_currency": "SYN"}
                  for request in plan["requests"]]
        cases.append(("failed", labels, {"records": []}, False, failed))
        summaries = {}
        for name, references, outputs, allow_partial, operations in cases:
            result = evaluate(task, plan, references, outputs, allow_partial_references=allow_partial)
            save(name + ".html", generate_report(task, plan, references, outputs, operations,
                                                 allow_partial_references=allow_partial))
            save(name + "-evaluation.json", result)
            save(name + "-predictions.json", outputs)
            save(name + "-references.json", references)
            save(name + "-operations.json", operations)
            summaries[name] = {key: result[key] for key in ("positions", "invalid", "missing")}
        save("task.json", task)
        save("plan.json", plan)
        ref = labels["records"][0]
        field = task["fields"][0]
        alternative = next(label for label in field["labels"] if label != ref["labels"][field["name"]])
        scenarios = [{"id": "illustrative-reference-change", "title": "Illustrative alternate reference",
                      "provenance": "Fictional operator scenario; not an applied correction.",
                      "changes": [{"id": ref["id"], "labels": {field["name"]: alternative}}]}]
        save("scenarios.json", scenarios)
        save("sensitivity.html", generate_report(task, plan, labels, predictions, scenarios=scenarios))
        source_paths = sorted((root / "classification_bench").glob("*.py")) + [Path(__file__).resolve()]
        manifest = {"schema_version": 1, "purpose": "Fictional offline UI acceptance; no provider-performance evidence",
                    "rendered_acceptance": "pending", "live_dispatches": 0,
                    "network_guard": "Python socket connect/create_connection denied; not process isolation",
                    "cases": summaries, "files": list(files),
                    "generator_sources": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                          for p in source_paths},
                    "source_examples": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in sorted(source.glob("*.json"))}}
        save("verification.json", manifest)
    return {"directory": str(target), "files": len(files), "cases": summaries,
            "rendered_acceptance": "pending", "live_dispatches": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, help="New private destination; existing directories are rejected")
    args = parser.parse_args()
    print(json.dumps(generate(args.directory), indent=2))


if __name__ == "__main__":
    main()
