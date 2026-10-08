"""Renew a fictional expired account check without changing frozen run inputs."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from classification_bench.benchmark import preflight, preview, run, _load, _initialize
from classification_bench.cli import main
from classification_bench.manifest import canonical_bytes, digest
from classification_bench.subscription_assertions import SubscriptionAssertionLedger
from tests import test_adapter_runtime as runtime_fixtures
from tests.test_subscription_runtime import FakeCLIWorker


class SubscriptionRenewalWorkflowTests(unittest.TestCase):
    setUp = runtime_fixtures.RuntimeTests.setUp

    def configure(self):
        experiment_path = Path(self.config["experiment"])
        experiment = json.loads(experiment_path.read_text())
        experiment["repeats"] = 1
        cfg = {"id": "account", "model": "gpt-5", "settings": {
            "adapter": "codex", "executable": "/usr/bin/true", "cli_version": "offline-fixture",
            "effort": "medium", "extra_usage_disabled": True,
            "extra_usage_verified_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            "extra_usage_source": "fictional expired account check"}}
        experiment["configs"] = [cfg]
        experiment_path.write_text(json.dumps(experiment))
        self.config.update(currency="REQ", scale=1, cap=10, scope="fixture:subscription",
                           authorization_file=str(self.config_path.parent / "auth.json"),
                           provider_limits={"chatgpt_subscription": 1})
        self.config_path.write_text(json.dumps(self.config))
        plan = preview(self.config_path)
        Path(self.config["authorization_file"]).write_text(json.dumps({
            "schema_version": 1, "run_sha256": plan["run_sha256"], "plan_sha256": plan["plan_sha256"],
            "request_count": plan["request_count"], "scope": self.config["scope"], "cap": self.config["cap"]}))
        return cfg, plan

    def test_expired_guard_renews_and_admission_uses_exact_revision(self):
        cfg, plan = self.configure()
        frozen = {path: Path(path).read_bytes() for path in
                  (self.config_path, self.config["task"], self.config["inputs"], self.config["experiment"])}
        worker = FakeCLIWorker()
        self.assertFalse(preflight(self.config_path, worker=worker)["ready"])
        self.assertFalse(Path(self.config["database"]).exists())
        result = run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, 0)
        self.assertNotEqual(result["status"], "completed")
        config, _, binding, materials, _ = _load(self.config_path)
        verified = _initialize(config, binding, materials)
        ledger = SubscriptionAssertionLedger(verified.execution, verified.artifact_root)
        evidence = b'{"fixture":true,"extra_usage_disabled":true}'
        authorization = {"schema_version": 1, "renewal_id": "fresh-check", "run_sha256": binding,
            "scope": config["scope"], "config_id": cfg["id"], "configuration_sha256": digest(canonical_bytes(cfg)),
            "adapter": "codex", "expected_revision": 0, "extra_usage_disabled": True,
            "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "fictional fresh account check", "account_check_sha256": digest(evidence)}
        auth_path, evidence_path = self.config_path.parent / "renewal.json", self.config_path.parent / "check.json"
        auth_path.write_text(json.dumps(authorization))
        evidence_path.write_bytes(evidence)
        output_path = self.config_path.parent / "renewal-result.json"
        main(["account-check-renew", "--config", str(self.config_path),
              "--authorization", str(auth_path), "--evidence", str(evidence_path),
              "--out", str(output_path)])
        self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(worker.calls, 0)
        guard = json.loads(output_path.read_text())
        self.assertEqual(guard["revision"], 1)
        self.assertTrue(preflight(self.config_path, worker=worker)["ready"])
        result = run(self.config_path, worker=worker)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(worker.calls, plan["request_count"])
        with verified.execution.coordinator._transaction() as conn:
            revisions = conn.execute("SELECT revision FROM subscription_guard_admissions").fetchall()
        self.assertEqual([row[0] for row in revisions], [1] * plan["request_count"])
        self.assertEqual(preview(self.config_path)["run_sha256"], binding)
        self.assertEqual(ledger.current(config["scope"], binding, cfg["id"])["revision"], 1)
        for path, original in frozen.items():
            self.assertEqual(Path(path).read_bytes(), original)
        run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, plan["request_count"])
