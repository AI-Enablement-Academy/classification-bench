"""File based command line interface for offline planning and evaluation."""

import argparse
import json
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
        else:
            from .run import export_saved_predictions
            output = export_saved_predictions(args.config)
        _write(getattr(args, "out", "-"), output)
    except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError,
            IsolationError, IsolationUnavailable) as exc:
        parser.exit(2, f"classification-bench: {exc}\n")


if __name__ == "__main__":
    main()
