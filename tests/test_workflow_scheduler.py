"""Shared scheduler integration tests with real ledgers and offline runtimes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from classification_bench import benchmark
from classification_bench.adapter_runtime import OfflineRuntime, registry
from classification_bench.adapters import ParsedResponse, PreparedRequest, TransportResult
from classification_bench.budget import BudgetLedger
from classification_bench.manifest import canonical_bytes, digest


class FixtureAdapter:
    def __init__(self, config):
        if set(config) != {"id", "model", "settings"}:
            raise ValueError("reporting metadata reached strict execution controls")
        self.config = config
        self.provider = config["settings"]["provider"]

    def prepare(self, plan, request, prompt):
        return PreparedRequest(canonical_bytes({
            "request_id": request["request_id"], "messages": [{"role": "user", "content": prompt["text"]}],
            "ids": [item["id"] for item in request["items"]]}),
            self.config["settings"]["reserve"], "fixture:explicit-bound", "fixture:offline-callback",
            request["request_id"], tuple(item["id"] for item in request["items"]))

    def dispatch(self, prepared):
        return TransportResult(canonical_bytes({"request_id": prepared.request_id,
            "predictions": [{"id": item, "prediction": {"kind": "a"}}
                            for item in prepared.expected_ids]}), 200, 1)

    def parse(self, result, *, expected_request_id, expected_ids, expected_model):
        value = json.loads(result.raw_bytes)
        if value["request_id"] != expected_request_id or tuple(
                item["id"] for item in value["predictions"]) != expected_ids:
            raise ValueError("fixture response identity mismatch")
        return ParsedResponse("valid", tuple(value["predictions"]), None,
            self.config["settings"]["cost"], expected_model, self.provider, None, "stop")


class FixtureRuntime(OfflineRuntime):
    """Live-shaped accounting with no credential or provider operation."""

    offline = False

    def __init__(self, currency, callback):
        super().__init__(FixtureAdapter)
        self.accounting_currency = currency
        self.callback = callback

    def dispatch(self, adapter, prepared, api_key, worker):
        self.callback(adapter, prepared)
        return adapter.dispatch(prepared)


class WorkflowSchedulerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="workflow-scheduler-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.lock = threading.Lock()
        self.calls = []
        self.active = 0
        self.peak = 0
        self.active_provider = {}
        self.peak_provider = {}
        self.dispatch_hook = lambda adapter, prepared: None
        for currency in ("USD", "REQ"):
            name = f"workflow-fixture-{currency.lower()}"
            registry.register(name, FixtureRuntime(currency, self.dispatch))
            self.addCleanup(registry.unregister, name)
        self.write("task.json", {"name": "fictional", "input_keys": ["text"],
            "fields": [{"name": "kind", "labels": ["a", "b"]}]})
        self.write("inputs.json", {"records": [
            {"id": "one", "input": {"text": "alpha"}},
            {"id": "two", "input": {"text": "beta"}}]})
        self.limits = {"shared": 2}
        self.max_concurrency = 2
        self.paths = []

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value))
        return path

    def dispatch(self, adapter, prepared):
        with self.lock:
            self.calls.append((adapter.config["id"], prepared.request_id))
            self.active += 1
            self.peak = max(self.peak, self.active)
            provider = adapter.provider
            self.active_provider[provider] = self.active_provider.get(provider, 0) + 1
            self.peak_provider[provider] = max(self.peak_provider.get(provider, 0), self.active_provider[provider])
        try:
            self.dispatch_hook(adapter, prepared)
        finally:
            with self.lock:
                self.active -= 1
                self.active_provider[provider] -= 1

    def group(self, currency, *, cap=4, count=1, provider="shared", policy="pause", suffix="", phase="smoke"):
        name = currency.lower() + suffix
        configs = [{"id": f"{name}-{index}", "model": "fixture-model", "settings": {
            "adapter": f"workflow-fixture-{currency.lower()}", "provider": provider,
            "reserve": 1, "cost": 1 if currency == "USD" else None}}
            for index in range(count)]
        experiment = self.write(f"{name}-experiment.json", {"configs": configs,
            "prompts": [{"id": "p", "text": "Classify."}], "repeats": 1, "batch_size": 1})
        config = {"schema_version": 2, "task": str(self.root / "task.json"),
            "experiment": str(experiment), "inputs": str(self.root / "inputs.json"),
            "database": str(self.root / "execution.sqlite"), "artifacts": str(self.root / "artifacts"),
            "scope": f"fixture:{name}", "cap": cap, "currency": currency,
            "scale": 1_000_000 if currency == "USD" else 1,
            "max_concurrency": self.max_concurrency, "provider_limits": self.limits,
            "authorization_file": str(self.root / f"{name}-auth.json"), "on_budget_exhausted": policy,
            "aggregate": {"parent_scope": f"fixture:{name}:aggregate", "allocation_id": f"{name}:allocation", "phase": phase}}
        path = self.write(f"{name}.json", config)
        planned = benchmark.preview(path)
        self.write(f"{name}-auth.json", {"schema_version": 1, **{
            key: planned[key] for key in ("run_sha256", "plan_sha256", "request_count", "scope", "cap")}})
        ledger = BudgetLedger(config["database"])
        ledger.create_aggregate(config["aggregate"]["parent_scope"], cap, currency, config["scale"], "explicit offline fixture")
        self.paths.append(path)
        return path

    def run_groups(self):
        return benchmark.run_groups(self.paths, max_concurrency=self.max_concurrency, provider_limits=self.limits)

    def test_usd_and_request_groups_overlap_under_one_total_limit(self):
        self.limits = {"usd-provider": 3, "req-provider": 3}
        usd = self.group("USD", provider="usd-provider")
        req = self.group("REQ", count=2, provider="req-provider")
        barrier = threading.Barrier(3)
        release = threading.Event()
        third_entered = threading.Event()

        def first_wave(adapter, prepared):
            with self.lock:
                wave = len(self.calls)
            if wave <= 2:
                barrier.wait(timeout=3)
                if not release.wait(timeout=3):
                    raise TimeoutError("test dispatch release not received")
            else:
                third_entered.set()
        self.dispatch_hook = first_wave
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.run_groups)
            try:
                barrier.wait(timeout=3)
                self.assertFalse(third_entered.wait(timeout=0.2))
            finally:
                release.set()
            results = future.result(timeout=10)
        self.assertEqual([item["config_path"] for item in results], [str(usd.resolve()), str(req.resolve())])
        self.assertEqual([item["status"] for item in results], ["completed", "completed"])
        self.assertEqual([item["completed_requests"] for item in results], [2, 4])
        self.assertEqual(self.peak, 2)
        self.assertEqual({item[0].split("-")[0] for item in self.calls[:2]}, {"usd", "req"})
        ledger = BudgetLedger(self.root / "execution.sqlite")
        self.assertEqual(ledger.verify("fixture:usd")["known_charges"], 2)
        self.assertEqual(ledger.verify("fixture:req")["known_charges"], 4)
        self.assertEqual(results[0]["budget"]["currency"], "USD")
        self.assertEqual(results[1]["budget"]["currency"], "REQ")

    def test_provider_limit_is_shared_across_accounting_units(self):
        self.max_concurrency = 3
        self.limits = {"shared": 1}
        self.group("USD")
        self.group("REQ")
        first_entered = threading.Event()
        second_entered = threading.Event()
        release = threading.Event()

        def hold_first(adapter, prepared):
            with self.lock:
                if len(self.calls) > 1:
                    second_entered.set()
            first_entered.set()
            if not release.wait(timeout=3):
                raise TimeoutError("test dispatch release not received")
        self.dispatch_hook = hold_first
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.run_groups)
            try:
                self.assertTrue(first_entered.wait(timeout=3))
                self.assertFalse(second_entered.wait(timeout=0.2))
            finally:
                release.set()
            results = future.result(timeout=10)
        self.assertEqual([item["completed_requests"] for item in results], [2, 2])
        self.assertEqual(self.peak_provider, {"shared": 1})

    def test_exhausted_unit_pauses_while_independent_group_finishes(self):
        self.group("USD", cap=1)
        self.group("REQ", cap=2)
        results = self.run_groups()
        self.assertEqual([item["status"] for item in results], ["paused_budget", "completed"])
        self.assertEqual([item["completed_requests"] for item in results], [1, 2])
        self.assertEqual(results[0]["action_required"], "amend_budget")
        self.assertEqual(results[0]["budget"]["known_charges"], 1)
        before = list(self.calls)
        self.assertEqual([item["status"] for item in self.run_groups()], ["paused_budget", "completed"])
        self.assertEqual(self.calls, before)

    def test_exhausted_group_pause_is_visible_while_other_unit_is_running(self):
        usd = self.group("USD", cap=1)
        self.group("REQ", cap=2)
        req_entered = threading.Event()
        pause_recorded = threading.Event()
        release = threading.Event()
        original_control = benchmark._set_control

        def record_control(verified, state, reason, **kwargs):
            original_control(verified, state, reason, **kwargs)
            if kwargs.get("budget_scope") == "fixture:usd" and state == "paused_budget":
                pause_recorded.set()

        def hold_req(adapter, prepared):
            if adapter.config["id"] == "req-0":
                req_entered.set()
                if not release.wait(timeout=3):
                    raise TimeoutError("test dispatch release not received")
        self.dispatch_hook = hold_req
        with patch.object(benchmark, "_set_control", side_effect=record_control):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.run_groups)
                try:
                    self.assertTrue(req_entered.wait(timeout=3))
                    self.assertTrue(pause_recorded.wait(timeout=0.5))
                    self.assertEqual(benchmark.status(usd)["status"], "paused_budget")
                    self.assertFalse(future.done())
                finally:
                    release.set()
                results = future.result(timeout=10)
        self.assertEqual([item["status"] for item in results], ["paused_budget", "completed"])

    def test_stop_is_durable_for_one_unit_without_stopping_another(self):
        self.group("USD", cap=1, policy="stop")
        self.group("REQ", cap=2, policy="stop")
        self.assertEqual([item["status"] for item in self.run_groups()], ["stopped_budget", "completed"])
        before = list(self.calls)
        self.assertEqual([item["status"] for item in self.run_groups()], ["stopped_budget", "completed"])
        self.assertEqual(self.calls, before)

    def test_ambiguous_dispatch_retains_hold_and_is_not_replayed_on_restart(self):
        usd = self.group("USD", cap=2)
        self.group("REQ", cap=2)
        first = benchmark.preview(usd)["requests"][0]
        def ambiguous(adapter, prepared):
            if prepared.request_id == first["request_id"]:
                raise TimeoutError("offline ambiguous dispatch")
        self.dispatch_hook = ambiguous
        results = self.run_groups()
        self.assertEqual([item["status"] for item in results], ["recovery_required", "completed"])
        self.assertEqual(results[0]["states"], {"never_sent": 1, "outcome_unknown": 1})
        self.assertEqual(results[0]["budget"]["unknown_holds"], 1)
        self.dispatch_hook = lambda adapter, prepared: None
        restarted = self.run_groups()
        self.assertEqual(restarted[0]["states"], results[0]["states"])
        self.assertEqual(benchmark.recover(usd)["unresolved"], [first["storage_request_id"]])
        self.assertEqual(sum(request == first["request_id"] for _, request in self.calls), 1)
        self.assertEqual(BudgetLedger(self.root / "execution.sqlite").verify("fixture:usd")["unknown_holds"], 1)

    def test_interrupted_claim_in_one_group_is_reclaimed_under_common_lock(self):
        usd = self.group("USD")
        self.group("REQ")
        config, _, binding, materials, _ = benchmark._load(usd)
        verified = benchmark._initialize(config, binding, materials)
        benchmark._refs(verified, materials[0])
        claim = verified.execution.claim("benchmark-matrix", 300)
        results = self.run_groups()
        self.assertEqual([item["status"] for item in results], ["completed", "completed"])
        events = verified.execution.coordinator.events(claim["request_id"])
        self.assertTrue(any(event["event_type"] == "claim_released" for event in events))

    def test_common_runner_lock_excludes_individual_and_group_runners(self):
        usd = self.group("USD")
        self.group("REQ")
        with benchmark._runner_lock(self.root / "execution.sqlite"):
            with self.assertRaisesRegex(benchmark.BenchmarkError, "already_running"):
                self.run_groups()
            with self.assertRaisesRegex(benchmark.BenchmarkError, "already_running"):
                benchmark.run(usd)
        self.assertEqual(self.calls, [])

    def test_invalid_final_group_authorization_prevents_any_dispatch(self):
        self.group("USD")
        req = self.group("REQ")
        config = json.loads(req.read_text())
        self.write("req-auth.json", {"schema_version": 1})
        with self.assertRaisesRegex(benchmark.BenchmarkError, "authorization"):
            self.run_groups()
        self.assertEqual(self.calls, [])
        self.assertIsNone(BudgetLedger(config["database"]).allocation_for("fixture:usd"))

    def test_incompatible_groups_are_rejected_before_dispatch(self):
        self.group("USD")
        req = self.group("REQ")
        original = json.loads(req.read_text())
        invalid = [({"database": str(self.root / "other.sqlite")}, "database"),
            ({"artifacts": str(self.root / "other-artifacts")}, "artifact"),
            ({"scope": "fixture:usd"}, "scope"),
            ({"provider_limits": {"shared": 1}}, "provider"),
            ({"max_concurrency": 1}, "concurrency"),
            ({"on_budget_exhausted": "stop"}, "exhaustion"),
            ({"aggregate": {**original["aggregate"], "phase": "full"}}, "phase")]
        for change, reason in invalid:
            with self.subTest(reason=reason):
                req.write_text(json.dumps({**original, **change}))
                with self.assertRaisesRegex(benchmark.BenchmarkError, reason):
                    self.run_groups()
                self.assertEqual(self.calls, [])
        req.write_text(json.dumps(original))
        experiment_path = Path(original["experiment"])
        experiment = json.loads(experiment_path.read_text())
        experiment["configs"][0]["id"] = "usd-0"
        experiment_path.write_text(json.dumps(experiment))
        with self.assertRaisesRegex(benchmark.BenchmarkError, "configuration ID"):
            self.run_groups()
        self.assertEqual(self.calls, [])

    def test_parent_freeze_retains_its_cause_while_other_unit_finishes(self):
        usd = self.group("USD")
        self.group("REQ", cap=2)
        experiment_path = Path(json.loads(usd.read_text())["experiment"])
        experiment = json.loads(experiment_path.read_text())
        experiment["configs"][0]["settings"]["cost"] = 2
        experiment_path.write_text(json.dumps(experiment))
        self.authorize(usd)
        results = self.run_groups()
        self.assertEqual([item["status"] for item in results], ["blocked_budget_freeze", "completed"])
        self.assertEqual(results[0]["completed_requests"], 1)
        self.assertEqual(results[0]["budget"]["known_charges"], 2)
        freeze = results[0]["aggregate_freeze"]
        before = list(self.calls)
        restarted = self.run_groups()
        self.assertEqual(restarted[0]["aggregate_freeze"], freeze)
        self.assertEqual(restarted[0]["action_required"], "review_budget_freeze")
        self.assertEqual(self.calls, before)

    def test_preexisting_parent_safety_block_does_not_allocate_or_stop_other_unit(self):
        usd = self.group("USD")
        self.group("REQ", cap=2)
        config, _, binding, materials, _ = benchmark._load(usd)
        # Bind a managed run without allocating its blocked child.
        from classification_bench.verified_execution import VerifiedExecution
        verified = VerifiedExecution(config["database"], config["artifacts"])
        benchmark._bind(verified, binding, config)
        verified.execution.block_scope(config["aggregate"]["parent_scope"], "offline safety fixture", "a" * 64)
        results = self.run_groups()
        self.assertEqual([item["status"] for item in results], ["blocked_safety", "completed"])
        self.assertEqual(results[0]["completed_requests"], 0)
        self.assertEqual(results[0]["admission_block"]["reason"], "offline safety fixture")
        self.assertIsNone(BudgetLedger(config["database"]).allocation_for(config["scope"]))
        self.assertEqual({config_id for config_id, _ in self.calls}, {"req-0"})

    def authorize(self, path):
        config = json.loads(path.read_text())
        planned = benchmark.preview(path)
        Path(config["authorization_file"]).write_text(json.dumps({"schema_version": 1,
            **{key: planned[key] for key in ("run_sha256", "plan_sha256", "request_count", "scope", "cap")}}))

    def test_reporting_metadata_is_hashed_but_removed_at_strict_adapter_boundary(self):
        usd = self.group("USD")
        self.group("REQ")
        before = benchmark.preview(usd)
        config = json.loads(usd.read_text())
        experiment_path = Path(config["experiment"])
        experiment = json.loads(experiment_path.read_text())
        metadata = {"schema_version": 1, "family": {"status": "unknown"}}
        experiment["configs"][0].update(model_type="decision", model_metadata=metadata)
        experiment_path.write_text(json.dumps(experiment))
        self.authorize(usd)
        _, plan, binding, materials, _ = benchmark._load(usd)
        self.assertEqual(plan["experiment"]["configs"][0]["model_metadata"], metadata)
        self.assertEqual(materials[0]["config"], experiment["configs"][0])
        self.assertNotIn("model_metadata", materials[0]["adapter"].config)
        self.assertNotIn("model_type", materials[0]["adapter"].config)
        self.assertNotEqual(binding, before["run_sha256"])
        self.assertNotEqual(digest(canonical_bytes(plan)), before["plan_sha256"])
        self.assertEqual([item["status"] for item in self.run_groups()], ["completed", "completed"])

    def test_request_account_guards_keep_their_own_run_scope_and_full_fingerprint(self):
        from tests.test_subscription_runtime import FakeCLIWorker
        self.limits = {"shared": 2, "chatgpt_subscription": 2}
        self.group("USD")
        req = self.group("REQ", cap=2)
        config = json.loads(req.read_text())
        experiment_path = Path(config["experiment"])
        experiment = json.loads(experiment_path.read_text())
        cfg = {"id": "req-0", "model": "fixture-model", "model_type": "llm",
            "model_metadata": {"schema_version": 1, "training_lineage": {"status": "unknown"}},
            "settings": {"adapter": "codex", "executable": "/usr/bin/true", "cli_version": "offline-fixture",
                "effort": "medium", "extra_usage_disabled": True,
                "extra_usage_verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "extra_usage_source": "offline scheduler fixture"}}
        experiment["configs"] = [cfg]
        experiment_path.write_text(json.dumps(experiment))
        self.authorize(req)
        results = benchmark.run_groups(self.paths, max_concurrency=self.max_concurrency,
                                      provider_limits=self.limits, worker=FakeCLIWorker())
        self.assertEqual([item["status"] for item in results], ["completed", "completed"])
        _, _, binding, materials, _ = benchmark._load(req)
        from classification_bench.verified_execution import VerifiedExecution
        verified = VerifiedExecution(config["database"], config["artifacts"])
        with verified.execution.coordinator._transaction() as conn:
            guards = [dict(row) for row in conn.execute("SELECT * FROM subscription_guard_admissions")]
            revision = dict(conn.execute("SELECT * FROM subscription_assertion_revisions").fetchone())
        self.assertEqual(len(guards), 2)
        self.assertTrue(all((guard["scope"], guard["run_sha256"], guard["config_id"]) ==
                           (config["scope"], binding, cfg["id"]) for guard in guards))
        self.assertEqual({guard["request_id"] for guard in guards},
                         {material["request"]["request_id"] for material in materials})
        self.assertEqual(revision["configuration_sha256"], digest(canonical_bytes(cfg)))
        self.assertEqual(results[1]["budget"]["known_charges"], 2)

    def test_synthetic_group_keeps_separate_unit_and_immutable_config_inputs(self):
        self.limits = {"shared": 2, "synthetic": 1}
        self.group("USD")
        self.group("REQ")
        config = json.loads(self.paths[0].read_text())
        config.update(currency="SYN", scale=1, cap=1, scope="synthetic:workflow", authorization_file=None,
            experiment=str(self.root / "synthetic-experiment.json"),
            aggregate={"parent_scope": "synthetic:workflow:aggregate", "allocation_id": "synthetic:allocation", "phase": "smoke"})
        self.write("synthetic-experiment.json", {"configs": [{"id": "synthetic-0", "model": "synthetic-only",
            "settings": {"adapter": "synthetic", "response_mode": "first_label"}}],
            "prompts": [{"id": "p", "text": "Classify."}], "repeats": 1, "batch_size": 1})
        self.paths.append(self.write("synthetic.json", config))
        BudgetLedger(config["database"]).create_aggregate("synthetic:workflow:aggregate", 1, "SYN", 1,
                                                         "explicit offline fixture")
        before = {path: path.read_bytes() for path in self.paths}
        results = self.run_groups()
        self.assertEqual([item["status"] for item in results], ["completed"] * 3)
        self.assertEqual([item["budget"]["currency"] for item in results], ["USD", "REQ", "SYN"])
        self.assertEqual(results[2]["budget"]["known_charges"], 0)
        self.assertEqual(before, {path: path.read_bytes() for path in self.paths})

    def test_blocked_group_skips_revoked_credentials_while_eligible_group_finishes(self):
        for cause in ("paused_budget", "stopped_budget", "safety", "unallocated_safety", "freeze"):
            with self.subTest(cause=cause):
                # Each case has independent managed scopes in the common database.
                self.paths = []
                suffix = "-" + cause
                policy = "stop" if cause == "stopped_budget" else "pause"
                usd = self.group("USD", suffix=suffix, policy=policy)
                self.group("REQ", suffix=suffix, policy=policy, cap=2)
                config, _, binding, materials, _ = benchmark._load(usd)
                if cause == "unallocated_safety":
                    from classification_bench.verified_execution import VerifiedExecution
                    verified = VerifiedExecution(config["database"], config["artifacts"])
                else:
                    verified = benchmark._initialize(config, binding, materials)
                if cause in ("paused_budget", "stopped_budget"):
                    benchmark._set_control(verified, cause, "offline exhausted fixture")
                    expected = cause
                elif cause in ("safety", "unallocated_safety"):
                    verified.execution.block_scope(config["aggregate"]["parent_scope"],
                                                   "offline inherited safety fixture", "b" * 64)
                    expected = "blocked_safety"
                else:
                    ledger = BudgetLedger(config["database"])
                    ledger.reserve(config["scope"], "offline-overrun", 1, bound_source="offline bound")
                    ledger.settle(config["scope"], "offline-overrun", "offline-charge", 2)
                    expected = "blocked_budget_freeze"

                def revoked(runtime, supplied):
                    if runtime.accounting_currency == "USD":
                        raise ValueError("offline revoked USD credential")
                    return None

                with patch.object(FixtureRuntime, "credential", new=revoked):
                    results = self.run_groups()
                self.assertEqual([item["status"] for item in results], [expected, "completed"])
                self.assertEqual(results[0]["completed_requests"], 0)
                self.assertEqual(results[0]["errors"], [])
                self.assertEqual(results[1]["completed_requests"], 2)
                if cause == "unallocated_safety":
                    self.assertIsNone(BudgetLedger(config["database"]).allocation_for(config["scope"]))
                    self.assertEqual(results[0]["admission_block"]["reason"], "offline inherited safety fixture")

    def test_all_authorizations_are_validated_before_any_credential_lookup(self):
        self.group("USD")
        self.group("REQ")
        self.write("req-auth.json", {"schema_version": 1})
        with patch.object(FixtureRuntime, "credential", side_effect=AssertionError("credential lookup preceded authorization validation")):
            with self.assertRaisesRegex(benchmark.BenchmarkError, "authorization"):
                self.run_groups()
        self.assertEqual(self.calls, [])

    def test_legacy_single_run_uses_same_runtime_scheduling_behavior(self):
        usd = self.group("USD")
        config = json.loads(usd.read_text())
        config["schema_version"] = 1
        config.pop("aggregate")
        usd.write_text(json.dumps(config))
        planned = benchmark.preview(usd)
        self.write("usd-auth.json", {"schema_version": 1, **{key: planned[key] for key in
            ("run_sha256", "plan_sha256", "request_count", "scope", "cap")}})
        result = benchmark.run(usd)
        self.assertEqual(result["states"], {"response_saved": 2})
        self.assertNotIn("config_path", result)
        self.assertEqual(benchmark.run(usd)["states"], {"response_saved": 2})
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
