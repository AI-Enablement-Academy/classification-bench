"""File based command line interface for offline planning and evaluation."""

import argparse
import json
import sys
from pathlib import Path

from .core import ValidationError, build_plan, evaluate


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
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            output = build_plan(_read(args.task), _read(args.experiment), _read(args.inputs))
        else:
            output = evaluate(_read(args.task), _read(args.plan), _read(args.labels),
                              _read(args.predictions))
        _write(args.out, output)
    except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        parser.exit(2, f"classification-bench: {exc}\n")


if __name__ == "__main__":
    main()
