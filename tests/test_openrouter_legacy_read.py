"""Committed OpenRouter snapshots stay readable without authorizing new calls."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from classification_bench import adapters, benchmark
from classification_bench.budget import BudgetLedger
from classification_bench.evidence import EvidenceError, read_artifact
from classification_bench.manifest import canonical_bytes, digest
from classification_bench.report import generate_report


# Snapshot schema, request fields and source digests were captured once from
# d1c1ed4. The fixture uses fictional public metadata and needs no Git history.
LEGACY_ADAPTER_SHA256 = "4c47fd09bb7b9312c48bc4f1501f9a46bf2402bf48d16ccbfc644e4fad2ded73"
LEGACY_RUNTIME_SHA256 = "579ad5aa22055ee8814037c5a2f97e0ec0828f96d85b7ca152c4d3bb0c64d106"
LEGACY_SNAPSHOT_SHA256 = "529c6a36072c8bac00fbf693abbab34a24cab2ccce05661340da14302049070f"
LEGACY_FIXED_REQUEST_SHA256 = "ef3160d3501a7a71f21a9654f10df69151262195a81626bf816d29308c636d1e"
NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
MODEL = "openai/arbitrary-test-model"
PROVIDER = "azure/eu"


class LegacyOpenRouterReadTests(unittest.TestCase):
    def fixture(self, reasoning=None, *, include_reasoning=True):
        if reasoning is None:
            reasoning = {"supported_efforts": ["high", "medium", "none"],
                         "default_effort": "medium", "mandatory": False}
        endpoint = {"tag": PROVIDER, "provider_name": "Azure", "model_id": MODEL,
                    "max_prompt_tokens": 100, "max_completion_tokens": 40,
                    "supported_parameters": ["max_completion_tokens", "reasoning", "temperature", "top_p"],
                    "pricing": {"prompt": "0.000001", "completion": "0.000002", "request": "0"}}
        endpoint_raw = json.dumps({"data": {"id": MODEL, "endpoints": [endpoint]}}).encode()
        metadata = {"id": MODEL, "canonical_slug": MODEL}
        if include_reasoning:
            metadata["reasoning"] = reasoning
        model_raw = json.dumps({"data": metadata}).encode()
        snapshot = {"model_id": MODEL, "provider_tag": PROVIDER, "observed_at": "2026-10-08T12:00:00Z",
                    "source_url": f"https://openrouter.ai/api/v1/models/{MODEL}/endpoints",
                    "max_prompt_tokens": 100, "max_completion_tokens": 40,
                    "supported_parameters": endpoint["supported_parameters"], "pricing": endpoint["pricing"],
                    "model_identity": {"requested_id": MODEL, "canonical_id": MODEL,
                        "source_url": f"https://openrouter.ai/api/v1/model/{MODEL}",
                        "observed_at": "2026-10-08T12:00:00Z", "response_sha256": digest(model_raw),
                        "response_json": model_raw.decode()}}
        config = {"id": "legacy", "model": MODEL, "settings": {"adapter": "openrouter",
                  "provider": PROVIDER, "max_output_tokens": 20, "endpoint_snapshot": snapshot}}
        plan = {"task": {"fields": [{"name": "kind", "labels": ["a", "b"]}]}}
        request = {"request_id": "saved-request", "config_id": config["id"], "prompt_id": "p",
                   "items": [{"id": "case", "input": {"text": "fictional legacy input"}}]}
        return config, plan, request, {"id": "p", "text": "Classify."}, endpoint_raw, model_raw

    @staticmethod
    def legacy_prepared(config, plan, request, prompt):
        instruction = ("Return only a JSON object with exactly request_id and predictions. "
                       f"Set request_id to {json.dumps(request['request_id'])}. "
                       "Predictions must be an array with one object for each input id, in input order. "
                       "Each object has exactly id and prediction. Prediction maps every declared field "
                       "to one of its declared labels. Do not include explanations or markdown.")
        content = canonical_bytes({"request_id": request["request_id"], "items": request["items"],
                                   "fields": plan["task"]["fields"]}).decode()
        body = {"model": MODEL, "messages": [{"role": "system", "content": prompt["text"]},
                    {"role": "user", "content": instruction + "\n\n" + content}],
                "max_completion_tokens": 20, "stream": False, "usage": {"include": True},
                "provider": {"only": [PROVIDER], "allow_fallbacks": False, "require_parameters": True,
                             "max_price": {"prompt": 1.0, "completion": 2.0, "request": 0}}}
        return adapters.PreparedRequest(canonical_bytes(body), 140,
                    "openrouter:endpoint:" + digest(canonical_bytes(config["settings"]["endpoint_snapshot"])),
                    f"openrouter:{MODEL}:{PROVIDER}", request["request_id"],
                    tuple(item["id"] for item in request["items"]))

    def test_default_active_and_unknown_legacy_metadata_remain_readable(self):
        for reasoning in ({"default_enabled": True}, {"mandatory": True},
                          {"default_effort": "medium"}, {"supported_efforts": ["high", "none"]}):
            with self.subTest(reasoning=reasoning):
                config, plan, request, prompt, _, _ = self.fixture(reasoning)
                original = deepcopy(config)
                old = self.legacy_prepared(config, plan, request, prompt)
                current = adapters.OpenRouterAdapter(config, now=lambda: NOW)
                prepared = current.prepare(plan, request, prompt)
                self.assertEqual(prepared.reserve_microusd, old.reserve_microusd)
                body = json.loads(prepared.body)
                old_body = json.loads(old.body)
                body.pop("plugins")
                self.assertEqual(body, old_body)
                self.assertNotIn("reasoning", current.requested_controls)
                self.assertTrue(current.reasoning_active)
                self.assertEqual(config, original)

    def test_captured_legacy_shape_matches_independent_snapshot_and_request_hashes(self):
        config, plan, request, prompt, _, _ = self.fixture()
        self.assertEqual(digest(canonical_bytes(config["settings"]["endpoint_snapshot"])), LEGACY_SNAPSHOT_SHA256)
        prepared = self.legacy_prepared(config, plan, request, prompt)
        self.assertEqual(digest(prepared.body), LEGACY_FIXED_REQUEST_SHA256)
        self.assertEqual(prepared.reserve_microusd, 140)

    def test_unbounded_legacy_default_blocks_preflight_and_dispatch_before_io(self):
        config, plan, request, prompt, _, _ = self.fixture()
        for include_policy in (False, True):
            with self.subTest(include_policy=include_policy):
                candidate = deepcopy(config)
                if include_policy:
                    candidate["settings"]["account_policy_assertion"] = {
                        "source": "fictional offline account policy", "verified_at": "2026-10-08T11:00:00Z",
                        "web_disabled_or_overridable": True, "response_healing_disabled_or_overridable": True}
                fetch, model_fetch, transport = Mock(), Mock(), Mock()
                adapter = adapters.OpenRouterAdapter(candidate, catalog_fetch=fetch,
                           model_fetch=model_fetch, transport=transport, now=lambda: NOW)
                prepared = adapter.prepare(plan, request, prompt)
                with self.assertRaisesRegex(adapters.AdapterError, "combined.*bound"):
                    adapter.verify_live_snapshot()
                with self.assertRaisesRegex(adapters.AdapterError, "combined.*bound"):
                    adapter.dispatch(prepared, "offline-fixture-not-a-credential")
                fetch.assert_not_called()
                model_fetch.assert_not_called()
                transport.assert_not_called()

    def test_new_or_explicit_enabled_reasoning_snapshots_remain_strict(self):
        config, _, _, _, endpoint_raw, model_raw = self.fixture()
        for controls in ({"effort": "high"}, {"reasoning": {"enabled": True}},
                         {"reasoning": {"exclude": True}}):
            with self.subTest(controls=controls):
                candidate = deepcopy(config)
                candidate["settings"].update(controls)
                with self.assertRaisesRegex(adapters.AdapterError, "combined.*bound"):
                    adapters.OpenRouterAdapter(candidate, now=lambda: NOW)
        snapshot = adapters.fetch_endpoint_snapshot(MODEL, PROVIDER,
                        catalog_fetch=lambda url: endpoint_raw, model_fetch=lambda url: model_raw,
                        now=lambda: NOW)
        self.assertIn("endpoint_evidence", snapshot)
        self.assertIn("reasoning_bound", snapshot)
        del snapshot["reasoning_bound"]
        candidate = deepcopy(config)
        candidate["settings"]["endpoint_snapshot"] = snapshot
        with self.assertRaisesRegex(adapters.AdapterError, "combined.*bound"):
            adapters.OpenRouterAdapter(candidate, now=lambda: NOW)

    def test_missing_frozen_identity_never_authorizes_a_live_default(self):
        config, plan, request, prompt, _, _ = self.fixture({"mandatory": True})
        del config["settings"]["endpoint_snapshot"]["model_identity"]
        config["settings"]["account_policy_assertion"] = {
            "source": "fictional offline account policy", "verified_at": "2026-10-08T11:00:00Z",
            "web_disabled_or_overridable": True, "response_healing_disabled_or_overridable": True}
        original = deepcopy(config)
        fetch, model_fetch, transport = Mock(), Mock(), Mock()
        adapter = adapters.OpenRouterAdapter(config, now=lambda: NOW,
                    catalog_fetch=fetch, model_fetch=model_fetch, transport=transport)
        prepared = adapter.prepare(plan, request, prompt)
        self.assertEqual(prepared.reserve_microusd, 140)
        with self.assertRaisesRegex(adapters.AdapterError, "frozen model identity"):
            adapter.verify_live_snapshot()
        with self.assertRaisesRegex(adapters.AdapterError, "frozen model identity"):
            adapter.dispatch(prepared, "offline-fixture-not-a-credential")
        fetch.assert_not_called()
        model_fetch.assert_not_called()
        transport.assert_not_called()
        self.assertEqual(config, original)

    def test_captured_identity_with_omitted_reasoning_is_a_nonreasoning_contract(self):
        config, plan, request, prompt, endpoint_raw, model_raw = self.fixture(include_reasoning=False)
        config["settings"]["account_policy_assertion"] = {
            "source": "fictional offline account policy", "verified_at": "2026-10-08T11:00:00Z",
            "web_disabled_or_overridable": True, "response_healing_disabled_or_overridable": True}
        fetch, model_fetch = Mock(return_value=endpoint_raw), Mock(return_value=model_raw)
        transport = Mock(return_value=(200, b'{"fictional":"response"}', False, None))
        adapter = adapters.OpenRouterAdapter(config, now=lambda: NOW,
                    catalog_fetch=fetch, model_fetch=model_fetch, transport=transport)
        self.assertFalse(adapter.reasoning_active)
        adapter.verify_live_snapshot()
        adapter.dispatch(adapter.prepare(plan, request, prompt), "offline-fixture-not-a-credential")
        self.assertEqual((fetch.call_count, model_fetch.call_count, transport.call_count), (1, 1, 1))

    def test_null_reasoning_is_not_a_documented_nonreasoning_capability(self):
        config, _, _, _, _, _ = self.fixture()
        identity = config["settings"]["endpoint_snapshot"]["model_identity"]
        value = json.loads(identity["response_json"])
        value["data"]["reasoning"] = None
        raw = json.dumps(value).encode()
        identity.update(response_json=raw.decode(), response_sha256=digest(raw))
        with self.assertRaisesRegex(adapters.AdapterError, "reasoning capability must be an object"):
            adapters.OpenRouterAdapter(config, now=lambda: NOW)

    def test_saved_legacy_response_parsing_keeps_usage_and_original_values(self):
        config, _, request, _, _, _ = self.fixture()
        content = json.dumps({"request_id": request["request_id"],
                              "predictions": [{"id": "case", "prediction": {"kind": "b"}}]})
        raw = json.dumps({"id": "old-generation", "model": MODEL,
                          "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                          "usage": {"prompt_tokens": 5, "completion_tokens": 4, "cost": 0.000021}}).encode()
        current = adapters.OpenRouterAdapter(config, now=lambda: NOW).parse(
            adapters.TransportResult(raw, 200, 3), expected_request_id=request["request_id"],
            expected_ids=("case",), expected_model=MODEL)
        self.assertEqual(current.status, "valid")
        self.assertEqual(current.predictions, ({"id": "case", "prediction": {"kind": "b"}},))
        self.assertEqual(current.returned_model, MODEL)
        self.assertEqual(current.usage, {"prompt_tokens": 5, "completion_tokens": 4, "cost": 0.000021})
        self.assertEqual(current.observed_cost_microusd, 21)

    def test_historical_status_export_and_report_use_unchanged_saved_evidence(self):
        self.historical_read(pending=False)

    def test_pending_historical_recovery_preserves_evidence_under_original_parser_contract(self):
        self.historical_read(pending=True)

    def historical_read(self, *, pending):
        config, _, _, _, _, _ = self.fixture()
        with tempfile.TemporaryDirectory(prefix="legacy-openrouter-history-") as directory:
            root = Path(directory)
            task = {"name": "fictional legacy task", "input_keys": ["text"],
                    "fields": [{"name": "kind", "labels": ["a", "b"]}]}
            experiment = {"configs": [config], "prompts": [{"id": "p", "text": "Classify."}],
                          "repeats": 1, "batch_size": 1}
            inputs = {"records": [{"id": "case", "input": {"text": "fictional legacy input"}}]}
            runner = {"schema_version": 1, "task": str(root / "task.json"),
                      "experiment": str(root / "experiment.json"), "inputs": str(root / "inputs.json"),
                      "database": str(root / "state.sqlite"), "artifacts": str(root / "artifacts"),
                      "scope": "legacy:USD", "cap": 1000, "currency": "USD", "scale": 1_000_000,
                      "max_concurrency": 1, "provider_limits": {PROVIDER: 1},
                      "authorization_file": str(root / "authorization.json"), "on_budget_exhausted": "pause"}
            for name, value in (("task", task), ("experiment", experiment), ("inputs", inputs), ("config", runner)):
                (root / (name + ".json")).write_text(json.dumps(value))
            path = root / "config.json"
            loaded, planned, binding, materials, _ = benchmark._load(path)
            verified = benchmark._initialize(loaded, binding, materials)
            current = materials[0]
            old_prepared = self.legacy_prepared(config, planned, current["request"], experiment["prompts"][0])
            manifest = json.loads(current["manifest"])
            manifest.pop("canonical_request_controls")
            manifest.pop("account_policy_prerequisite")
            manifest.update(adapter_source_sha256=LEGACY_ADAPTER_SHA256,
                            runtime_source_sha256=LEGACY_RUNTIME_SHA256,
                            request_sha256=digest(old_prepared.body),
                            messages=json.loads(old_prepared.body)["messages"])
            material = {**current, "prepared": old_prepared, "manifest": canonical_bytes(manifest)}
            request_id = material["request"]["request_id"]
            refs = benchmark._refs(verified, material)
            claim = verified.execution.claim("offline historical fixture", 60, request_id=request_id)
            verified.admit_verified(request_id, claim["token"], runner["scope"],
                material["prepared"].reserve_microusd, refs["manifest_ref"], refs["request_ref"],
                bound_source="committed legacy preparation; fictional offline evidence")
            content = json.dumps({"request_id": request_id,
                                  "predictions": [{"id": "case", "prediction": {"kind": "b"}}]})
            raw = json.dumps({"id": "old-generation", "model": MODEL,
                              "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                              "usage": {"prompt_tokens": 5, "completion_tokens": 4, "cost": 0.000021}}).encode()
            result = adapters.TransportResult(raw, 200, 3)
            benchmark._save_transport(verified, request_id, result)
            saved = verified.save_response(request_id, claim["token"], raw, "application/json", "offline legacy receipt")
            parsed = adapters.OpenRouterAdapter(config, now=lambda: NOW).parse(result,
                expected_request_id=request_id, expected_ids=("case",), expected_model=MODEL)
            observation = {"transport": {**asdict(result), "raw_bytes": None}, "parsed": asdict(parsed),
                           "route": material["prepared"].route, "response_sha256": saved["response_ref"].sha256,
                           "receipt_sha256": saved["receipt_ref"].sha256, "generation": None,
                           "provider_identity_status": "legacy fixture; provider-unverified",
                           "generation_response_sha256": None}
            if not pending:
                benchmark._save_observation(verified, request_id, saved["response_ref"].sha256, observation)
                verified.recover_response(request_id, claim["token"], receipt_ref=saved["receipt_ref"],
                                           settlement_id="old-charge", charge=21)
            frozen_files = {source: source.read_bytes() for source in
                            (path, root / "task.json", root / "experiment.json", root / "inputs.json")}
            pending_state = verified.execution.get(request_id)
            pending_balance = BudgetLedger(runner["database"]).balances(runner["scope"])
            with patch("classification_bench.adapters._default_catalog_fetch", side_effect=AssertionError("no public fetch")), \
                    patch("classification_bench.adapters._default_transport", side_effect=AssertionError("no provider call")):
                if pending:
                    # Changed implementation/request hashes cannot silently
                    # reparse a pending old outcome with a new parser contract.
                    with self.assertRaises(EvidenceError):
                        benchmark.recover(path)
                    self.assertEqual(verified.execution.get(request_id), pending_state)
                    self.assertEqual(BudgetLedger(runner["database"]).balances(runner["scope"]), pending_balance)
                    self.assertEqual(pending_balance["active_reservations"], 140)
                    self.assertEqual(read_artifact(verified.artifact_root, refs["manifest_ref"]), material["manifest"])
                    self.assertEqual(read_artifact(verified.artifact_root, refs["request_ref"]), material["prepared"].body)
                    self.assertEqual(read_artifact(verified.artifact_root, saved["response_ref"]), raw)
                    for source, original in frozen_files.items():
                        self.assertEqual(source.read_bytes(), original)
                    return
                self.assertEqual(benchmark.status(path)["status"], "completed")
                self.assertEqual(benchmark.export_predictions(path)["records"][0]["prediction"], {"kind": "b"})
                snapshot = benchmark.report_snapshot(path)
                operation = snapshot["operations"][0]
                self.assertEqual(operation["adapter_source_sha256"], LEGACY_ADAPTER_SHA256)
                self.assertEqual(operation["response_sha256"], digest(raw))
                self.assertEqual(operation["observed_cost_micro_usd"], 21)
                self.assertEqual(operation["frozen_canonical_model"], MODEL)
                html = generate_report(snapshot["task"], snapshot["plan"], None,
                                       snapshot["predictions"], snapshot["operations"])
                self.assertIn("fictional legacy task", html)
            self.assertEqual(read_artifact(verified.artifact_root, refs["manifest_ref"]), material["manifest"])
            self.assertEqual(read_artifact(verified.artifact_root, refs["request_ref"]), material["prepared"].body)
            self.assertEqual(read_artifact(verified.artifact_root, saved["response_ref"]), raw)
            for source, original in frozen_files.items():
                self.assertEqual(source.read_bytes(), original)
