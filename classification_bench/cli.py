"""File based command line interface for offline planning and evaluation."""

import argparse
import json
import os
import sys
from pathlib import Path

from .core import ValidationError, build_plan, evaluate
from .isolation import IsolationError, IsolationUnavailable


def _read(path):
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def _write(path, value):
    """Create owner-only JSON artifacts; existing paths are never overwritten."""
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path == "-":
        sys.stdout.write(content)
    else:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(content)


def _write_private_html(path, content):
    """Local reports contain private input/reference text; never overwrite."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        target.write(content)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="classification-bench")
    sub = parser.add_subparsers(dest="command", required=True)
    initialize = sub.add_parser("init", help="Create a private task setup from an explicit import specification")
    initialize.add_argument("--spec", required=True)
    initialize.add_argument("--directory", required=True)
    imported = sub.add_parser("import", help="Freeze and validate user-owned JSON, JSONL or CSV task data")
    imported.add_argument("--spec", required=True)
    imported.add_argument("--directory", required=True)
    validated = sub.add_parser("validate", help="Verify an imported task package and its frozen source bindings")
    validated.add_argument("--directory", required=True)
    plan = sub.add_parser("plan", help="Build deterministic requests without reference labels")
    plan.add_argument("--task", required=True)
    plan.add_argument("--experiment", required=True)
    plan.add_argument("--inputs", required=True)
    plan.add_argument("--out", default="-")
    score = sub.add_parser("evaluate", help="Score saved predictions offline")
    score.add_argument("--task", required=True)
    score.add_argument("--plan", required=True)
    score.add_argument("--labels", help="Optional offline reference file")
    score.add_argument("--allow-partial-references", action="store_true",
                       help="Score only known references and report their coverage explicitly")
    score.add_argument("--predictions", required=True)
    score.add_argument("--out", default="-")
    sensitivity = sub.add_parser("sensitivity", help="Evaluate explicitly hypothetical reference alternatives offline")
    sensitivity.add_argument("--task", required=True)
    sensitivity.add_argument("--plan", required=True)
    sensitivity.add_argument("--predictions", required=True)
    sensitivity.add_argument("--labels", help="Original offline references; never modified")
    sensitivity.add_argument("--scenarios", required=True, help="JSON list of declared hypothetical alternatives")
    sensitivity.add_argument("--allow-partial-references", action="store_true")
    sensitivity.add_argument("--out", default="-")
    simulation = sub.add_parser("simulate", help="Run a synthetic offline transport with verified evidence")
    simulation.add_argument("--config", required=True)
    recovery = sub.add_parser("simulate-recover", help="Verify saved synthetic receipts without dispatch")
    recovery.add_argument("--config", required=True)
    recovery.add_argument("--max-objects", type=int, help="Explicit private artifact scan bound")
    exported = sub.add_parser("simulate-export", help="Export verified synthetic predictions without labels")
    exported.add_argument("--config", required=True)
    exported.add_argument("--out", default="-")
    for command, help_text in (
        ("preflight", "Check authentication, runtime controls and isolation without inference"),
        ("preview", "Preview matrix, exact request identities and spending bounds"),
        ("run", "Execute an admitted matrix; never replay ambiguous dispatches"),
        ("status", "Inspect all planned requests and shared budget"),
        ("recover", "Recover saved receipts without sending requests"),
        ("export", "Export verified predictions for private offline scoring"),
    ):
        child = sub.add_parser(command, help=help_text)
        child.add_argument("--config", required=True)
        child.add_argument("--out", default="-")
    report = sub.add_parser("report", help="Write a private local HTML report from verified saved evidence")
    report.add_argument("--config", required=True)
    report.add_argument("--labels", help="Optional offline references; never passed to the runner")
    report.add_argument("--allow-partial-references", action="store_true",
                        help="Show known-reference scores separately from the full planned denominator")
    report.add_argument("--out", required=True)
    report.add_argument("--scenarios", help="Optional JSON list of hypothetical reference alternatives")
    report.add_argument("--cohorts", help="Optional JSON list of explicitly declared run cohorts")
    report.add_argument("--repeat-origins", help="Optional offline JSON list of declared repeat origins; does not verify fresh dispatch")
    catalog = sub.add_parser("catalog", help="Fetch a public endpoint snapshot without credentials or inference")
    catalog.add_argument("--model", required=True)
    catalog.add_argument("--provider", required=True)
    catalog.add_argument("--out", required=True)
    models = sub.add_parser("models", help="Discover public OpenRouter models without credentials or inference")
    models.add_argument("--query", help="Filter the public model catalog by text")
    models.add_argument("--offset", type=int, default=0)
    models.add_argument("--limit", type=int, default=100)
    models.add_argument("--out", default="-")
    increase = sub.add_parser("budget-increase", help="Apply an explicit, run-bound budget amendment")
    increase.add_argument("--config", required=True)
    increase.add_argument("--authorization", required=True)
    renewal = sub.add_parser("account-check-renew", help="Append a fresh, evidenced subscription account assertion without dispatch")
    renewal.add_argument("--config", required=True)
    renewal.add_argument("--authorization", required=True)
    renewal.add_argument("--evidence", required=True)
    renewal.add_argument("--out", default="-")
    for command in ("aggregate-create", "aggregate-status", "aggregate-increase"):
        aggregate = sub.add_parser(command, help="Create or inspect an explicit aggregate budget without inference")
        aggregate.add_argument("--spec", required=True)
        aggregate.add_argument("--out", default="-")
        if command == "aggregate-increase":
            aggregate.add_argument("--authorization", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            from .task_setup import initialize_task, read_specification
            output = initialize_task(args.directory, read_specification(args.spec),
                                     base_directory=Path(args.spec).resolve().parent)
        elif args.command == "import":
            from .task_setup import import_task
            output = import_task(args.spec, args.directory)
        elif args.command == "validate":
            from .task_setup import validate_setup
            output = validate_setup(args.directory)
        elif args.command == "plan":
            output = build_plan(_read(args.task), _read(args.experiment), _read(args.inputs))
        elif args.command == "evaluate":
            output = evaluate(_read(args.task), _read(args.plan),
                              _read(args.labels) if args.labels else None,
                              _read(args.predictions),
                              allow_partial_references=args.allow_partial_references)
        elif args.command == "sensitivity":
            from .report_sensitivity import build_sensitivity
            task, plan_data = _read(args.task), _read(args.plan)
            predictions = _read(args.predictions)
            labels = _read(args.labels) if args.labels else None
            # The same explicit partial-reference policy applies to every CLI evaluator.
            evaluate(task, plan_data, labels, predictions,
                     allow_partial_references=args.allow_partial_references)
            output = build_sensitivity(task, plan_data, predictions, labels, _read(args.scenarios))
        elif args.command == "simulate":
            from .run import simulate
            output = simulate(args.config)
        elif args.command == "simulate-recover":
            from .run import recover_saved
            output = recover_saved(args.config, max_objects=args.max_objects)
        elif args.command == "simulate-export":
            from .run import export_saved_predictions
            output = export_saved_predictions(args.config)
        elif args.command == "catalog":
            from .adapters import fetch_endpoint_snapshot
            output = fetch_endpoint_snapshot(args.model, args.provider)
        elif args.command == "models":
            from .adapters import fetch_model_catalog
            output = fetch_model_catalog(query=args.query, offset=args.offset, limit=args.limit)
        elif args.command == "budget-increase":
            from .benchmark import amend_budget
            output = amend_budget(args.config, args.authorization)
        elif args.command == "account-check-renew":
            from .benchmark import renew_account_assertion
            output = renew_account_assertion(args.config, args.authorization, args.evidence)
        elif args.command in ("aggregate-create", "aggregate-status", "aggregate-increase"):
            from .benchmark import aggregate_budget
            output = aggregate_budget(args.spec, create=args.command == "aggregate-create",
                                      amendment_path=getattr(args, "authorization", None))
        elif args.command == "report":
            from .benchmark import report_snapshot
            from .report import generate_report
            # Verified export is performed before the evaluator opens references.
            snapshot = report_snapshot(args.config)
            html = generate_report(snapshot["task"], snapshot["plan"],
                                   _read(args.labels) if args.labels else None,
                                   snapshot["predictions"], snapshot["operations"],
                                   allow_partial_references=args.allow_partial_references,
                                   scenarios=_read(args.scenarios) if args.scenarios else None,
                                   cohort_declarations=_read(args.cohorts) if args.cohorts else None,
                                   repeat_origins=_read(args.repeat_origins) if args.repeat_origins else None)
            _write_private_html(args.out, html)
            output = {"report": str(Path(args.out).resolve()), "visibility": "private-local"}
            _write("-", output)
            return
        else:
            from . import benchmark
            operation = {"preflight": benchmark.preflight, "preview": benchmark.preview, "run": benchmark.run,
                         "status": benchmark.status, "recover": benchmark.recover,
                         "export": benchmark.export_predictions}[args.command]
            output = operation(args.config)
        _write(getattr(args, "out", "-"), output)
    except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError,
            IsolationError, IsolationUnavailable) as exc:
        parser.exit(2, f"classification-bench: {exc}\n")


if __name__ == "__main__":
    main()
