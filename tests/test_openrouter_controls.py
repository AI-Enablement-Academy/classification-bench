"""Public catalog and reasoning contracts; all HTTP is injected offline."""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from classification_bench.adapters import (
    AdapterError, OpenRouterAdapter, TransportResult, fetch_endpoint_snapshot,
    fetch_model_catalog,
)


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def offline_adapter(config, **kwargs):
    return OpenRouterAdapter(config, now=lambda: NOW, **kwargs)


def synthetic_policy():
    return {"source": "synthetic offline account-policy fixture; no real account verified",
            "verified_at": "2026-10-08T11:00:00Z", "web_disabled_or_overridable": True,
            "response_healing_disabled_or_overridable": True}
MODEL = "openai/arbitrary-test-model"


def source_fixture(*, model=MODEL, provider="azure/eu", provider_name="Azure",
                   reasoning=None, parameters=None, pricing=None, prompt_limit=100):
    if reasoning is None:
        reasoning = {"supported_efforts": ["high", "medium", "low", "none"],
                     "default_effort": "medium", "mandatory": False}
    endpoint = {"tag": provider, "provider_name": provider_name, "model_id": model,
                "max_prompt_tokens": prompt_limit, "max_completion_tokens": 40,
                "supported_parameters": parameters or ["max_completion_tokens", "reasoning", "temperature", "top_p"],
                "pricing": pricing or {"prompt": "0.000001", "completion": "0.000002", "request": "0"}}
    endpoint_raw = json.dumps({"data": {"id": model, "endpoints": [endpoint]}}).encode()
    metadata = {"id": model, "canonical_slug": model,
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                "reasoning": reasoning}
    model_raw = json.dumps({"data": metadata}).encode()
    snapshot = fetch_endpoint_snapshot(model, provider, catalog_fetch=lambda url: endpoint_raw,
                                       model_fetch=lambda url: model_raw, now=lambda: NOW)
    config = {"id": "c", "model": model, "settings": {"adapter": "openrouter", "provider": provider,
              "max_output_tokens": 20, "endpoint_snapshot": snapshot, "account_policy_assertion": synthetic_policy()}}
    return config, endpoint_raw, model_raw


def prepared(adapter):
    return adapter.prepare({"task": {"fields": [{"name": "arbitrary", "labels": ["yes", "no"]}]}},
                           {"request_id": "req", "config_id": "c", "prompt_id": "p",
                            "items": [{"id": "case", "input": {"any": [1, "text"]}}]},
                           {"id": "p", "text": "classify"})


class ReasoningControlsTests(unittest.TestCase):
    def test_capture_binds_exact_endpoint_and_documented_protocol(self):
        config, raw, _ = source_fixture()
        snapshot = config["settings"]["endpoint_snapshot"]
        self.assertEqual(snapshot["endpoint_evidence"]["response_json"].encode(), raw)
        self.assertEqual(snapshot["endpoint_evidence"]["response_sha256"], hashlib.sha256(raw).hexdigest())
        bound = snapshot["reasoning_bound"]
        self.assertEqual(bound["contract"], "azure-openai-max-completion-v1")
        self.assertEqual(bound["provider_tag"], "azure/eu")
        self.assertEqual(bound["parameter"], "max_completion_tokens")
        self.assertIs(bound["includes_reasoning"], True)
        self.assertTrue(bound["source_url"].startswith("https://learn.microsoft.com/"))

    def test_exact_effort_canonical_body_manifest_and_single_total_bound(self):
        config, _, _ = source_fixture()
        config["settings"].update(effort="high", temperature=0, top_p=0.9)
        adapter = offline_adapter(config)
        request = prepared(adapter)
        body = json.loads(request.body)
        self.assertEqual(body["reasoning"], {"effort": "high"})
        self.assertEqual(adapter.requested_controls, {"temperature": 0, "top_p": 0.9, "reasoning": {"effort": "high"}})
        self.assertEqual(body["max_completion_tokens"], 20)
        self.assertNotIn("max_tokens", body)
        self.assertEqual(request.reserve_microusd, 140)  # 100 prompt + 20 total completion, no second reasoning charge.
        self.assertEqual(body["provider"]["only"], ["azure/eu"])
        self.assertIs(body["provider"]["allow_fallbacks"], False)
        self.assertIs(body["provider"]["require_parameters"], True)
        copy = adapter.requested_controls
        copy["reasoning"]["effort"] = "low"
        self.assertEqual(json.loads(prepared(adapter).body)["reasoning"]["effort"], "high")

    def test_nested_controls_budget_and_disabled_reasoning(self):
        config, _, _ = source_fixture(reasoning={"supported_efforts": None, "supports_max_tokens": True,
                                               "default_enabled": False, "mandatory": False})
        config["settings"]["reasoning"] = {"max_tokens": 8, "enabled": True, "exclude": True}
        adapter = offline_adapter(config)
        self.assertEqual(json.loads(prepared(adapter).body)["reasoning"], config["settings"]["reasoning"])
        self.assertEqual(prepared(adapter).reserve_microusd, 140)
        config, _, _ = source_fixture(model="other/exact", provider="other", provider_name="Other")
        config["settings"]["reasoning"] = {"enabled": False}
        self.assertEqual(json.loads(prepared(offline_adapter(config)).body)["reasoning"], {"enabled": False})

    def test_unsupported_exact_controls_are_never_mapped_or_ignored(self):
        bad = [({"effort": "xhigh"}, "support"), ({"effort": "HIGH"}, "effort"),
               ({"effort": "high", "max_tokens": 5}, "both"),
               ({"effort": "high", "enabled": False}, "contradict"),
               ({"effort": "none", "enabled": True}, "contradict"),
               ({"max_tokens": 5}, "budget"), ({"enabled": "yes"}, "boolean"),
               ({"exclude": 1}, "boolean"), ({"mode": "pro"}, "unsupported"),
               ({}, "nonempty"), ("high", "object")]
        for controls, message in bad:
            with self.subTest(controls=controls):
                config, _, _ = source_fixture()
                config["settings"]["reasoning"] = controls
                with self.assertRaisesRegex(AdapterError, message):
                    offline_adapter(config)
        config, _, _ = source_fixture()
        config["settings"].update(effort="high", reasoning={"effort": "high"})
        with self.assertRaisesRegex(AdapterError, "duplicate"):
            offline_adapter(config)

    def test_missing_effort_selection_and_mandatory_reasoning_fail_closed(self):
        config, _, _ = source_fixture(reasoning={"default_enabled": False, "mandatory": False})
        config["settings"]["effort"] = "high"
        with self.assertRaisesRegex(AdapterError, "effort selection"):
            offline_adapter(config)
        for controls in ({"enabled": False}, {"effort": "none"}):
            config, _, _ = source_fixture(reasoning={"supported_efforts": None, "mandatory": True})
            config["settings"]["reasoning"] = controls
            with self.assertRaisesRegex(AdapterError, "mandatory"):
                offline_adapter(config)

    def test_reasoning_capability_does_not_imply_route_budget_eligibility(self):
        for kwargs in ({"model": "anthropic/arbitrary", "provider": "azure/global", "provider_name": "Azure"},
                       {"provider": "other", "provider_name": "Other"},
                       {"parameters": ["reasoning", "max_tokens"]}):
            with self.subTest(kwargs=kwargs):
                config, _, _ = source_fixture(**kwargs)
                self.assertNotIn("reasoning_bound", config["settings"]["endpoint_snapshot"])
                config["settings"]["effort"] = "high"
                with self.assertRaisesRegex(AdapterError, "combined.*bound"):
                    offline_adapter(config)
        config, _, _ = source_fixture(reasoning={"supported_efforts": ["high", "none"], "default_enabled": False,
                                               "default_effort": "none", "mandatory": False}, provider="other", provider_name="Other")
        self.assertNotIn("reasoning", offline_adapter(config).requested_controls)

    def test_enabled_default_needs_bound_and_legacy_snapshot_is_preserved(self):
        config, _, _ = source_fixture(provider="other", provider_name="Other")
        with self.assertRaisesRegex(AdapterError, "combined.*bound"):
            offline_adapter(config)
        snapshot = config["settings"]["endpoint_snapshot"]
        del snapshot["endpoint_evidence"]
        del snapshot["model_identity"]
        self.assertEqual(prepared(offline_adapter(config)).reserve_microusd, 140)
        config["settings"]["effort"] = "high"
        with self.assertRaisesRegex(AdapterError, "model.*evidence"):
            offline_adapter(config)

    def test_frozen_sources_and_bound_contract_cannot_disagree(self):
        for mutate in (lambda s: s["endpoint_evidence"].update(response_sha256="0" * 64),
                       lambda s: s["reasoning_bound"].update(provider_tag="azure/us"),
                       lambda s: s["reasoning_bound"].update(source_url="https://example.test/claim"),
                       lambda s: s["endpoint_evidence"].update(response_json="{}")):
            config, _, _ = source_fixture()
            mutate(config["settings"]["endpoint_snapshot"])
            with self.assertRaises(AdapterError):
                offline_adapter(config)

    def test_live_capability_provider_and_price_drift_block(self):
        config, endpoint_raw, model_raw = source_fixture()
        config["settings"]["reasoning"] = {"effort": "high"}
        adapter = offline_adapter(config, catalog_fetch=lambda url: endpoint_raw, model_fetch=lambda url: model_raw)
        self.assertEqual(adapter.verify_live_snapshot()["identity_response_sha256"], hashlib.sha256(model_raw).hexdigest())
        changed = json.loads(model_raw)
        changed["data"]["reasoning"]["supported_efforts"] = ["medium", "low"]
        with self.assertRaisesRegex(AdapterError, "reasoning.*drift"):
            offline_adapter(config, catalog_fetch=lambda url: endpoint_raw,
                              model_fetch=lambda url: json.dumps(changed).encode()).verify_live_snapshot()
        for key, value in (("provider_name", "Other"), ("max_completion_tokens", 41),
                           ("pricing", {"prompt": "0.000001", "completion": "0.000003", "request": "0"})):
            changed = json.loads(endpoint_raw)
            changed["data"]["endpoints"][0][key] = value
            with self.assertRaisesRegex(AdapterError, "drift"):
                offline_adapter(config, catalog_fetch=lambda url: json.dumps(changed).encode(),
                                  model_fetch=lambda url: model_raw).verify_live_snapshot()

    def test_reasoning_only_length_output_keeps_usage_cost_and_invalid_outcome(self):
        config, _, _ = source_fixture()
        adapter = offline_adapter(config)
        raw = json.dumps({"id": "generation", "model": MODEL,
                          "choices": [{"finish_reason": "length", "message": {"content": ""}}],
                          "usage": {"completion_tokens": 20, "completion_tokens_details": {"reasoning_tokens": 20},
                                    "cost": 0.00014}}).encode()
        result = adapter.parse(TransportResult(raw, 200, 1), expected_request_id="req", expected_ids=("case",), expected_model=MODEL)
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.observed_cost_microusd, 140)
        self.assertEqual(result.usage["completion_tokens_details"]["reasoning_tokens"], 20)


class PublicDiscoveryTests(unittest.TestCase):
    def fixture(self):
        return {"data": [{"id": "other/arbitrary", "canonical_slug": "other/arbitrary", "name": "Arbitrary",
                          "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                          "context_length": 100, "supported_parameters": ["max_tokens", "reasoning"],
                          "reasoning": {"mandatory": True, "supported_efforts": ["high", "low"]},
                          "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
                         {"id": "openrouter/auto", "name": "Dynamic router"},
                         {"id": "other/arbitrary:free", "name": "Variant"}],
                "total_count": 5, "links": {"next": "https://openrouter.ai/api/v1/models?offset=3&limit=3"}}

    def test_capture_page_keeps_capability_separate_from_route_eligibility(self):
        raw = json.dumps(self.fixture()).encode()
        calls = []
        def fetch(url):
            calls.append(url)
            return raw
        result = fetch_model_catalog(catalog_fetch=fetch, now=lambda: NOW, query="odd / + &# text", limit=3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(parse_qs(urlsplit(calls[0]).query)["q"], ["odd / + &# text"])
        self.assertEqual(result["returned_count"], 3)
        self.assertEqual(result["total_count"], 5)
        self.assertEqual(result["next_offset"], 3)
        self.assertIs(result["complete"], False)
        self.assertEqual(result["response_json"].encode(), raw)
        self.assertEqual(result["response_sha256"], hashlib.sha256(raw).hexdigest())
        one, router, variant = result["models"]
        self.assertEqual(one["reasoning"]["supported_efforts"], ["high", "low"])
        self.assertEqual(one["reasoning_budget_eligibility"], "requires_pinned_endpoint_snapshot")
        self.assertIs(one["endpoint_snapshot_compatible"], True)
        self.assertIs(router["endpoint_snapshot_compatible"], False)
        self.assertIs(variant["endpoint_snapshot_compatible"], False)
        self.assertEqual([x["id"] for x in result["models"]], [x["id"] for x in self.fixture()["data"]])

    def test_complete_page_and_validation_fail_without_fetch(self):
        value = self.fixture()
        value["total_count"] = 3
        value["links"]["next"] = None
        result = fetch_model_catalog(catalog_fetch=lambda url: json.dumps(value).encode(), now=lambda: NOW)
        self.assertIs(result["complete"], True)
        self.assertIsNone(result["next_offset"])
        for arguments in ({"limit": 0}, {"limit": 1001}, {"offset": -1}, {"offset": True}, {"query": []}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(AdapterError):
                    fetch_model_catalog(catalog_fetch=lambda url: self.fail("invalid args fetched"), **arguments)

    def test_catalog_incomplete_duplicate_or_malformed_evidence_is_rejected(self):
        values = [b'{}', b'{"data":[]}', b'\xff']
        duplicate = self.fixture()
        duplicate["data"][1]["id"] = duplicate["data"][0]["id"]
        values.append(json.dumps(duplicate).encode())
        truncated = self.fixture()
        truncated["links"]["next"] = None
        values.append(json.dumps(truncated).encode())
        for raw in values:
            with self.subTest(raw=raw[:60]):
                with self.assertRaises(AdapterError):
                    fetch_model_catalog(catalog_fetch=lambda url: raw)

    def test_last_page_has_no_next_offset_without_claiming_complete_collection(self):
        value = self.fixture()
        value["data"] = value["data"][:2]
        value["links"]["next"] = None
        result = fetch_model_catalog(catalog_fetch=lambda url: json.dumps(value).encode(),
                                     now=lambda: NOW, offset=3, limit=3)
        self.assertEqual(result["returned_count"], 2)
        self.assertEqual(result["total_count"], 5)
        self.assertIsNone(result["next_offset"])
        self.assertIs(result["complete"], False)


class BoundedPricingTests(unittest.TestCase):
    def fixture(self, *, prompt_limit=100, pricing=None, **kwargs):
        return source_fixture(prompt_limit=prompt_limit, pricing=pricing or {
            "prompt": "0.000001", "completion": "0.000002", "input_cache_read": "0.0000002",
            "input_cache_write": "0.00000125", "web_search": "0.01", "discount": 0,
            "overrides": [{"min_prompt_tokens": 100, "prompt": "0.000003", "completion": "0.000004",
                           "input_cache_write": "0.000005"}]},
            parameters=["max_completion_tokens", "reasoning", "tools", "tool_choice"], **kwargs)

    def test_exact_tier_boundary_cache_maximum_and_explicit_search_disable(self):
        for ceiling, reserve, input_rate, output_rate in ((100, 165, 1.25, 2.0), (101, 585, 5.0, 4.0)):
            config, _, _ = self.fixture(prompt_limit=ceiling)
            config["settings"]["effort"] = "high"
            adapter = offline_adapter(config)
            body = json.loads(prepared(adapter).body)
            self.assertEqual(prepared(adapter).reserve_microusd, reserve)
            self.assertEqual(body["provider"]["max_price"]["prompt"], input_rate)
            self.assertEqual(body["provider"]["max_price"]["completion"], output_rate)
            self.assertEqual(body["tools"], [])
            self.assertEqual(body["tool_choice"], "none")
            self.assertIn({"id": "web", "enabled": False}, body["plugins"])
            bound = config["settings"]["endpoint_snapshot"]["pricing_bound"]
            self.assertEqual(Decimal(bound["input_rate_ceiling"]), Decimal(str(input_rate)) / 1_000_000)
            self.assertEqual(bound["search_policy"]["tool_choice"], "none")

    def test_all_reachable_overrides_and_cache_write_variants_are_covered(self):
        prices = {"prompt": "0.000001", "completion": "0.000002", "request": "0",
                  "input_cache_write_1h": "0.000008", "overrides": [
                      {"min_prompt_tokens": 1, "prompt": "0.000004", "completion": "0.000009"},
                      {"min_prompt_tokens": 2, "prompt": "0.000002", "input_cache_write_1h": "0.000010"}]}
        config, _, _ = self.fixture(pricing=prices)
        self.assertEqual(prepared(offline_adapter(config)).reserve_microusd, 1180)

    def test_unknown_axes_nonzero_fees_and_unsupported_search_controls_fail(self):
        invalid = [
            {"prompt": "0.000001", "completion": "0.000002", "request": "0.001"},
            {"prompt": "0.000001", "completion": "0.000002", "internal_reasoning": "0.000003"},
            {"prompt": "0.000001", "completion": "0.000002", "overrides": [{"utc_start": 100, "prompt": "0.000003"}]},
            {"prompt": "0.000001", "completion": "0.000002", "overrides": [{"min_prompt_tokens": 50, "mystery": "0"}]},
            {"prompt": "0.000001", "completion": "0.000002", "overrides": [{"min_prompt_tokens": True, "prompt": "0.000003"}]},
            {"prompt": "0.000001", "completion": "0.000002", "overrides": [{"min_prompt_tokens": 50, "prompt": "NaN"}]},
        ]
        for prices in invalid:
            with self.subTest(prices=prices), self.assertRaises(AdapterError):
                config, _, _ = self.fixture(pricing=prices)
                offline_adapter(config)
        config, _, _ = source_fixture(pricing={"prompt": "0.000001", "completion": "0.000002", "web_search": "0.01"})
        with self.assertRaisesRegex(AdapterError, "search.*control|unbounded.*search"):
            offline_adapter(config)
        config, _, _ = self.fixture(model="other/arbitrary", provider="other", provider_name="Other")
        with self.assertRaises(AdapterError):
            offline_adapter(config)

    def test_price_schedule_and_policy_drift_remain_bound(self):
        config, endpoint_raw, model_raw = self.fixture(prompt_limit=101)
        adapter = offline_adapter(config, catalog_fetch=lambda url: endpoint_raw, model_fetch=lambda url: model_raw)
        adapter.verify_live_snapshot()
        changed = json.loads(endpoint_raw)
        changed["data"]["endpoints"][0]["pricing"]["overrides"][0]["input_cache_write"] = "0.000006"
        with self.assertRaisesRegex(AdapterError, "pricing.*drift"):
            offline_adapter(config, catalog_fetch=lambda url: json.dumps(changed).encode(), model_fetch=lambda url: model_raw).verify_live_snapshot()
        config["settings"]["endpoint_snapshot"]["pricing_bound"]["search_policy"]["tools"] = [{"type": "web_search"}]
        with self.assertRaisesRegex(AdapterError, "pricing.*bound|policy"):
            offline_adapter(config)
        config, _, _ = source_fixture(model="other/arbitrary", provider="other", provider_name="Other",
                                       reasoning={"mandatory": False, "default_enabled": False})
        config["settings"]["endpoint_snapshot"]["pricing_bound"] = None
        with self.assertRaisesRegex(AdapterError, "pricing bound"):
            offline_adapter(config)

    def test_public_endpoint_projection_is_eligible_without_dispatch(self):
        # Public GET projection observed 2026-10-08; no provider call or credential.
        # Full endpoint response SHA: 11994baf649345d7e24420609268be4caf925ff9de7674ef4273da931eb35d03.
        # https://openrouter.ai/api/v1/models/openai/gpt-6.1-sol-pro/endpoints
        model = "openai/gpt-6.1-sol-pro"
        endpoint = {"model_id": model, "tag": "azure/eu", "provider_name": "Azure",
                    "max_prompt_tokens": None, "context_length": 1050000, "max_completion_tokens": 128000,
                    "supported_parameters": ["reasoning", "include_reasoning", "max_completion_tokens", "tools", "tool_choice",
                                             "verbosity", "response_format", "seed", "structured_outputs", "reasoning_effort"],
                    "pricing": {"prompt": "0.0000022", "completion": "0.000011", "discount": 0,
                                "web_search": "0.01", "input_cache_read": "0.00000011", "input_cache_write": "0.00000275",
                                "overrides": [{"min_prompt_tokens": 272000, "prompt": "0.0000044", "completion": "0.0000165",
                                               "input_cache_read": "0.00000022", "input_cache_write": "0.0000055"}]}}
        metadata = {"id": model, "canonical_slug": "openai/gpt-6.1-sol-pro-20260929",
                    "reasoning": {"mandatory": True, "default_enabled": True, "default_effort": "medium",
                                  "supported_efforts": ["max", "xhigh", "high", "medium", "low"]}}
        raw = json.dumps({"data": {"id": model, "endpoints": [endpoint]}}).encode()
        model_raw = json.dumps({"data": metadata}).encode()
        snapshot = fetch_endpoint_snapshot(model, "azure/eu", catalog_fetch=lambda url: raw,
                                           model_fetch=lambda url: model_raw, now=lambda: NOW)
        adapter = offline_adapter({"id": "c", "model": model, "settings": {
            "adapter": "openrouter", "provider": "azure/eu", "max_output_tokens": 128,
            "effort": "high", "endpoint_snapshot": snapshot, "account_policy_assertion": synthetic_policy()}},
            transport=lambda *args: self.fail("offline preflight dispatched"),
            catalog_fetch=lambda url: raw, model_fetch=lambda url: model_raw)
        self.assertEqual(prepared(adapter).reserve_microusd, 5777112)
        self.assertEqual(adapter.verify_live_snapshot()["catalog_sha256"], hashlib.sha256(raw).hexdigest())


class OperatorPolicyTests(unittest.TestCase):
    def test_missing_effective_policy_keeps_offline_results_readable_but_blocks_live(self):
        config, raw, model_raw = source_fixture()
        del config["settings"]["account_policy_assertion"]
        adapter = offline_adapter(config, catalog_fetch=lambda url: self.fail("missing policy fetched"))
        self.assertEqual(prepared(adapter).reserve_microusd, 140)
        self.assertEqual(adapter.account_policy_prerequisite["status"], "unavailable")
        self.assertIn("account-policy:unverified", prepared(adapter).bound_source)
        with self.assertRaisesRegex(AdapterError, "effective plugin policy is unknown"):
            adapter.verify_live_snapshot()

    def test_current_operator_assertion_is_frozen_separately_and_honestly(self):
        config, raw, model_raw = source_fixture()
        adapter = offline_adapter(config, catalog_fetch=lambda url: raw, model_fetch=lambda url: model_raw)
        prerequisite = adapter.account_policy_prerequisite
        self.assertEqual(prerequisite["status"], "operator_declared")
        self.assertEqual(prerequisite["bound_condition"], "provider_honors_operator_declared_account_policy")
        self.assertIn(prerequisite["assertion_sha256"], prepared(adapter).bound_source)
        self.assertNotIn("account_policy_assertion", adapter.requested_controls)
        checked = adapter.verify_live_snapshot()
        self.assertEqual(checked["account_policy_status"], "operator_declared_current")
        self.assertEqual(checked["account_policy_assertion_sha256"], prerequisite["assertion_sha256"])
        prerequisite["assertion"]["source"] = "changed externally"
        self.assertEqual(adapter.account_policy_prerequisite["assertion"]["source"], synthetic_policy()["source"])

    def test_expired_future_malformed_or_negative_policy_fails_closed(self):
        for when in ("2026-10-07T12:00:00Z", "2026-10-08T12:00:01Z"):
            config, raw, model_raw = source_fixture()
            config["settings"]["account_policy_assertion"]["verified_at"] = when
            with self.subTest(when=when), self.assertRaisesRegex(AdapterError, "expired or future"):
                offline_adapter(config, catalog_fetch=lambda url: self.fail("stale policy fetched")).verify_live_snapshot()
        for change in ({"source": ""}, {"verified_at": "bad"}, {"verified_at": "2026-10-08Z"}, {"web_disabled_or_overridable": False},
                       {"response_healing_disabled_or_overridable": 1}, {"independently_verified": True}):
            config, _, _ = source_fixture()
            config["settings"]["account_policy_assertion"].update(change)
            with self.subTest(change=change), self.assertRaises(AdapterError):
                offline_adapter(config)

    def test_direct_dispatch_rechecks_policy_before_transport_and_after_clock_advances(self):
        config, _, _ = source_fixture()
        del config["settings"]["account_policy_assertion"]
        adapter = offline_adapter(config, transport=lambda *args: self.fail("unknown policy dispatched"))
        with self.assertRaisesRegex(AdapterError, "effective plugin policy is unknown"):
            adapter.dispatch(prepared(adapter), "synthetic-offline-key")

        config, raw, model_raw = source_fixture()
        current = [NOW]
        calls = []
        adapter = OpenRouterAdapter(config, now=lambda: current[0],
            catalog_fetch=lambda url: raw, model_fetch=lambda url: model_raw,
            transport=lambda *args: (calls.append(args) or (200, b"{}", False, None)))
        request = prepared(adapter)
        adapter.verify_live_snapshot()
        adapter.dispatch(request, "synthetic-offline-key")
        self.assertEqual(len(calls), 1)
        current[0] = datetime(2026, 10, 9, 11, tzinfo=timezone.utc)
        with self.assertRaisesRegex(AdapterError, "expired or future"):
            adapter.dispatch(request, "synthetic-offline-key")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
