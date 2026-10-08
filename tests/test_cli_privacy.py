"""Private CLI files stay owner-only even in shared output directories."""

import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from classification_bench.cli import main


class PrivateOutputTests(unittest.TestCase):
    def test_plan_evaluation_and_exports_are_owner_only(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = os.umask(0o022)
            try:
                plan = root / "plan.json"
                main(["plan", "--task", str(examples / "task.json"),
                      "--experiment", str(examples / "experiment.json"),
                      "--inputs", str(examples / "inputs.json"), "--out", str(plan)])
                score = root / "evaluation.json"
                main(["evaluate", "--task", str(examples / "task.json"),
                      "--plan", str(plan), "--labels", str(examples / "labels.json"),
                      "--predictions", str(examples / "predictions.json"), "--out", str(score)])
                for command, target in (("export", "classification_bench.benchmark.export_predictions"),
                                        ("simulate-export", "classification_bench.run.export_saved_predictions")):
                    path = root / (command + ".json")
                    with patch(target, return_value={"records": [{"id": "private-id"}]}):
                        main([command, "--config", "unused", "--out", str(path)])
                    self.assertEqual(json.loads(path.read_text())["records"][0]["id"], "private-id")
                for path in root.iterdir():
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)
            finally:
                os.umask(old)

    def test_existing_file_and_symlink_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.json"
            path.write_text("original")
            link = Path(directory) / "link.json"
            link.symlink_to(path)
            with patch("classification_bench.benchmark.export_predictions", return_value={"records": []}):
                for destination in (path, link):
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                        main(["export", "--config", "unused", "--out", str(destination)])
                    self.assertEqual(error.exception.code, 2)
                    self.assertEqual(path.read_text(), "original")

    def test_stdout_remains_json(self):
        output = io.StringIO()
        with patch("classification_bench.benchmark.export_predictions", return_value={"records": []}), \
                contextlib.redirect_stdout(output):
            main(["export", "--config", "unused"])
        self.assertEqual(json.loads(output.getvalue()), {"records": []})
