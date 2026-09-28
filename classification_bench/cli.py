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
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path == "-":
        sys.stdout.write(content)
    else:
        with Path(path).open("x", encoding="utf-8") as target:
            target.write(content)


def _write_private_html(path, content):
    """Local reports contain private input/reference text; never overwrite."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        target.write(content)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="classification-bench")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="Build deterministic requests without reference labels")
    plan.add_argument("--task", required=True)
    plan.add_argument("--experiment", required=True)
    plan.add_argument("--inputs", required=True)
    plan.add_argument("--out", default="-")
    score = sub.add_parser("evaluate", help="Score saved predictions offline")
    score.add_argument("--task", required=True)
    score.add_argument("--plan", required=True)
    score.add_argument("--labels", required=True)
    score.add_argument("--predictions", required=True)
    score.add_argument("--out", default="-")
    simulation = sub.add_parser("simulate", help="Run a synthetic offline transport with verified evidence")
    simulation.add_argument("--config", required=True)
    recovery = sub.add_parser("simulate-recover", help="Verify saved synthetic receipts without dispatch")
    recovery.add_argument("--config", required=True)
    recovery.add_argument("--max-objects", type=int, help="Explicit private artifact scan bound")
    exported = sub.add_parser("simulate-export", help="Export verified synthetic predictions without labels")
    exported.add_argument("--config", required=True)
    exported.add_argument("--out", default="-")
    for command, help_text in (
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
    report.add_argument("--labels", required=True, help="Offline references; never passed to the runner")
    report.add_argument("--out", required=True)
    catalog = sub.add_parser("catalog", help="Fetch a public endpoint snapshot without credentials or inference")
    catalog.add_argument("--model", required=True)
    catalog.add_argument("--provider", required=True)
    catalog.add_argument("--out", required=True)
    increase = sub.add_parser("budget-increase", help="Apply an explicit, run-bound budget amendment")
    increase.add_argument("--config", required=True)
    increase.add_argument("--authorization", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            output = build_plan(_read(args.task), _read(args.experiment), _read(args.inputs))
        elif args.command == "evaluate":
            output = evaluate(_read(args.task), _read(args.plan), _read(args.labels),
                              _read(args.predictions))
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
        elif args.command == "budget-increase":
            from .benchmark import amend_budget
            output = amend_budget(args.config, args.authorization)
        elif args.command == "report":
            from .benchmark import report_snapshot
            from .report import generate_report
            # Verified export is performed before the evaluator opens references.
            snapshot = report_snapshot(args.config)
            html = generate_report(snapshot["task"], snapshot["plan"], _read(args.labels),
                                   snapshot["predictions"], snapshot["operations"])
            _write_private_html(args.out, html)
            output = {"report": str(Path(args.out).resolve()), "visibility": "private-local"}
            _write("-", output)
            return
        else:
            from . import benchmark
            operation = {"preview": benchmark.preview, "run": benchmark.run,
                         "status": benchmark.status, "recover": benchmark.recover,
                         "export": benchmark.export_predictions}[args.command]
            output = operation(args.config)
        _write(getattr(args, "out", "-"), output)
    except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError,
            IsolationError, IsolationUnavailable) as exc:
        parser.exit(2, f"classification-bench: {exc}\n")


if __name__ == "__main__":
    main()
