"""Offline OpenRouter adapter tests; fake HTTP cannot initiate inference."""

from datetime import datetime, timezone
import json
import unittest

from http.client import IncompleteRead

from classification_bench.adapters import (AdapterError, OpenRouterAdapter, TransportResult,
                                           fetch_endpoint_snapshot,
                                           _NoRedirect, _capture)


NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
MODEL = "example/model-v1"
PROVIDER = "test-provider"


def fixture():
    snapshot = {"model_id": MODEL, "provider_tag": PROVIDER,
                "observed_at": "2026-09-28T11:00:00Z",
                "source_url": f"https://openrouter.ai/api/v1/models/{MODEL}/endpoints",
                "max_prompt_tokens": 100, "max_completion_tokens": 20,
                "supported_parameters": ["max_completion_tokens", "temperature"],
                "pricing": {"prompt": "0.000001", "completion": "0.000002", "request": "0", "image": "0"}}
    config = {"id": "c", "model": MODEL,
              "settings": {"adapter": "openrouter", "provider": PROVIDER,
                           "max_output_tokens": 10, "temperature": 0,
                           "endpoint_snapshot": snapshot}}
    plan = {"task": {"fields": [{"name": "segment", "labels": ["yes", "no"]}]}}
    req = {"request_id": "request-1", "config_id": "c", "prompt_id": "p",
           "items": [{"id": "a", "input": {"text": "hello"}}]}
    prompt = {"id": "p", "text": "classify"}
    return config, plan, req, prompt


def completion(*, model=MODEL, content=None, cost=0.000021):
    if content is None:
        content = json.dumps({"request_id": "request-1", "predictions": [
            {"id": "a", "prediction": {"segment": "yes"}}]})
    return json.dumps({"id": "generation-1", "model": model,
                       "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 4,
                                 "cost": cost}}).encode()


class OpenRouterTests(unittest.TestCase):
    def adapter(self, config=None, **kwargs):
        if config is None:
            config = fixture()[0]
        return OpenRouterAdapter(config, now=lambda: NOW, **kwargs)

    def test_prepare_pins_route_price_and_output(self):
        config, plan, req, prompt = fixture()
        prepared = self.adapter(config).prepare(plan, req, prompt)
        body = json.loads(prepared.body)
        self.assertEqual(prepared.reserve_microusd, 120)
        self.assertEqual(body["provider"]["only"], [PROVIDER])
        self.assertIs(body["provider"]["allow_fallbacks"], False)
        self.assertIs(body["provider"]["require_parameters"], True)
        self.assertEqual(body["provider"]["max_price"], {"prompt": 1.0, "completion": 2.0,
                                                          "request": 0})
        self.assertEqual(body["max_completion_tokens"], 10)
        self.assertEqual(body["usage"], {"include": True})
        self.assertEqual(body["messages"][0]["content"], "classify")
        self.assertNotIn("labels", body["messages"][1]["content"].split('"items"')[1])

    def test_live_catalog_match_and_drift(self):
        config, _, _, _ = fixture()
        snap = config["settings"]["endpoint_snapshot"]
        raw = json.dumps({"data": {"id": MODEL, "endpoints": [
            {"tag": PROVIDER, "model_id": MODEL, **{k: snap[k] for k in (
                "max_prompt_tokens", "max_completion_tokens", "supported_parameters", "pricing")}}]}}).encode()
        adapter = self.adapter(config, catalog_fetch=lambda url: raw)
        self.assertEqual(len(adapter.verify_live_snapshot()["catalog_sha256"]), 64)
        changed = json.loads(raw)
        changed["data"]["endpoints"][0]["pricing"]["completion"] = "0.000003"
        adapter = self.adapter(config, catalog_fetch=lambda url: json.dumps(changed).encode())
        with self.assertRaisesRegex(AdapterError, "drifted"):
            adapter.verify_live_snapshot()

    def test_unsupported_or_unbounded_settings_fail_closed(self):
        config, _, _, _ = fixture()
        config["settings"]["reasoning_effort"] = "medium"
        with self.assertRaises(AdapterError):
            self.adapter(config)
        del config["settings"]["reasoning_effort"]
        config["settings"]["endpoint_snapshot"]["pricing"]["reasoning"] = "0.000001"
        with self.assertRaisesRegex(AdapterError, "unbounded"):
            self.adapter(config)

    def test_request_fee_cannot_exceed_enforced_zero_max_price(self):
        config, _, _, _ = fixture()
        config["settings"]["endpoint_snapshot"]["pricing"]["request"] = "0.001"
        with self.assertRaisesRegex(AdapterError, "request fee"):
            self.adapter(config)

    def test_no_retry_http_error_and_redaction(self):
        config, plan, req, prompt = fixture()
        calls = []
        def fake(url, headers, body, timeout, limit):
            calls.append((url, body))
            return 429, b'{"message":"sk-secret-reflected"}', False, None
        adapter = self.adapter(config, transport=fake)
        result = adapter.dispatch(adapter.prepare(plan, req, prompt), "sk-secret-reflected")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.http_status, 429)
        self.assertTrue(result.redacted)
        self.assertNotIn(b"sk-secret-reflected", result.raw_bytes)
        self.assertEqual(adapter.parse(result, expected_request_id="request-1", expected_ids=("a",),
                                       expected_model=MODEL).status, "unknown")

    def test_timeout_is_unknown_and_partial_body_is_preserved(self):
        config, plan, req, prompt = fixture()
        def timeout(*args):
            raise TimeoutError()
        adapter = self.adapter(config, transport=timeout)
        result = adapter.dispatch(adapter.prepare(plan, req, prompt), "key")
        self.assertEqual(result.http_status, None)
        self.assertEqual(adapter.parse(result, expected_request_id="request-1", expected_ids=("a",),
                                       expected_model=MODEL).status, "unknown")
        partial = TransportResult(b'{"id":"partial', 200, 1, "ConnectionResetError")
        self.assertEqual(adapter.parse(partial, expected_request_id="request-1", expected_ids=("a",),
                                       expected_model=MODEL).status, "invalid")

    def test_model_mismatch_preserves_usage_and_cost(self):
        adapter = self.adapter()
        result = TransportResult(completion(model="other/model"), 200, 1)
        parsed = adapter.parse(result, expected_request_id="request-1", expected_ids=("a",),
                               expected_model=MODEL)
        self.assertEqual(parsed.status, "invalid")
        self.assertEqual(parsed.reason, "returned model mismatch")
        self.assertEqual(parsed.observed_cost_microusd, 21)

    def test_valid_output_and_invalid_content_are_distinct(self):
        adapter = self.adapter()
        args = {"expected_request_id": "request-1", "expected_ids": ("a",), "expected_model": MODEL}
        valid = adapter.parse(TransportResult(completion(), 200, 1), **args)
        self.assertEqual(valid.status, "valid")
        self.assertEqual(valid.predictions[0]["prediction"], {"segment": "yes"})
        invalid = adapter.parse(TransportResult(completion(content="not JSON"), 200, 1), **args)
        self.assertEqual(invalid.status, "invalid")
        self.assertEqual(invalid.observed_cost_microusd, 21)
        extra = json.dumps({"request_id": "request-1", "predictions": [
            {"id": "a", "prediction": {"segment": "yes"}, "extra": True}]} )
        self.assertEqual(adapter.parse(TransportResult(completion(content=extra), 200, 1), **args).status,
                         "invalid")

    def test_generation_lookup_preserves_metadata_and_identity(self):
        seen = []
        raw = json.dumps({"data": {"id": "generation-1", "model": MODEL,
                                   "provider_name": "Test Provider", "total_cost": 0.000021,
                                   "generation_time": 40, "request_id": "provider-request-1",
                                   "is_byok": False}}).encode()
        def fake(url, headers, timeout, limit):
            seen.append((url, headers))
            return 200, raw, False, None
        adapter = self.adapter(generation_fetch=fake)
        result = adapter.lookup_generation("generation-1", "secret")
        self.assertEqual(len(seen), 1)
        self.assertIn("id=generation-1", seen[0][0])
        parsed = adapter.parse_generation(result, expected_response_id="generation-1", expected_model=MODEL)
        self.assertEqual(parsed["provider_name"], "Test Provider")
        self.assertEqual(parsed["observed_cost_microusd"], 21)
        with self.assertRaisesRegex(AdapterError, "identity"):
            adapter.parse_generation(result, expected_response_id="wrong", expected_model=MODEL)

    def test_incomplete_read_keeps_partial_bytes_and_redirect_is_refused(self):
        class Partial:
            def read(self, count):
                raise IncompleteRead(b'{"partial":', 20)
        self.assertEqual(_capture(Partial(), 100), (b'{"partial":', False, "IncompleteRead"))
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "Found", {},
                                                         "https://example.org"))

    def test_malformed_choices_do_not_crash_parser(self):
        adapter = self.adapter()
        raw = json.dumps({"id": "generation-1", "model": MODEL, "choices": {"bad": 1}}).encode()
        parsed = adapter.parse(TransportResult(raw, 200, 1), expected_request_id="request-1",
                               expected_ids=("a",), expected_model=MODEL)
        self.assertEqual(parsed.status, "invalid")

    def test_public_snapshot_capture_uses_context_when_prompt_limit_is_null(self):
        raw = json.dumps({"data": {"id": MODEL, "endpoints": [{
            "tag": PROVIDER, "model_id": MODEL, "context_length": 100,
            "max_prompt_tokens": None, "max_completion_tokens": 20,
            "supported_parameters": ["max_tokens"],
            "pricing": {"prompt": "0.000001", "completion": "0.000002", "discount": 0}}]}}).encode()
        snapshot = fetch_endpoint_snapshot(MODEL, PROVIDER, catalog_fetch=lambda url: raw,
                                           now=lambda: NOW)
        self.assertEqual(snapshot["max_prompt_tokens"], 100)
        self.assertEqual(snapshot["pricing"]["request"], "0")
        config, plan, req, prompt = fixture()
        config["settings"]["endpoint_snapshot"] = snapshot
        del config["settings"]["temperature"]
        body = json.loads(self.adapter(config).prepare(plan, req, prompt).body)
        self.assertEqual(body["max_tokens"], 10)
        self.assertNotIn("max_completion_tokens", body)

    def test_nano_route_web_search_exception_and_cheaper_cache_reads(self):
        config, plan, req, prompt = fixture()
        config["model"] = "openai/gpt-4.1-nano"
        config["settings"]["provider"] = "openai"
        snapshot = config["settings"]["endpoint_snapshot"]
        snapshot["model_id"] = config["model"]
        snapshot["provider_tag"] = "openai"
        snapshot["source_url"] = "https://openrouter.ai/api/v1/models/openai/gpt-4.1-nano/endpoints"
        config["settings"]["endpoint_snapshot"]["pricing"] = {
            "prompt": "0.0000001", "completion": "0.0000004",
            "request": "0", "input_cache_read": "0.000000025", "web_search": "0.01"}
        adapter = self.adapter(config)
        prepared = adapter.prepare(plan, req, prompt)
        body = json.loads(prepared.body)
        self.assertEqual(prepared.reserve_microusd, 14)
        self.assertNotIn("tools", body)
        self.assertNotIn("plugins", body)
        self.assertNotIn("web_search", body)
        config["settings"]["endpoint_snapshot"]["pricing"]["input_cache_read"] = "0.0000002"
        with self.assertRaisesRegex(AdapterError, "cache read"):
            self.adapter(config)

    def test_nonzero_web_search_price_rejects_other_models(self):
        config, _, _, _ = fixture()
        config["model"] = "perplexity/sonar"
        config["settings"]["provider"] = "perplexity"
        snapshot = config["settings"]["endpoint_snapshot"]
        snapshot["model_id"] = config["model"]
        snapshot["provider_tag"] = "perplexity"
        snapshot["source_url"] = "https://openrouter.ai/api/v1/models/perplexity/sonar/endpoints"
        config["settings"]["endpoint_snapshot"]["pricing"]["web_search"] = "0.01"
        with self.assertRaisesRegex(AdapterError, "web search"):
            self.adapter(config)

    def test_snapshot_capture_rejects_missing_hard_context(self):
        raw = json.dumps({"data": {"id": MODEL, "endpoints": [{
            "tag": PROVIDER, "model_id": MODEL, "context_length": None,
            "max_prompt_tokens": None, "max_completion_tokens": 20,
            "supported_parameters": ["max_tokens"],
            "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]}}).encode()
        with self.assertRaisesRegex(AdapterError, "max_prompt_tokens"):
            fetch_endpoint_snapshot(MODEL, PROVIDER, catalog_fetch=lambda url: raw, now=lambda: NOW)

    def test_base_provider_with_variants_is_ambiguous(self):
        endpoint = {"model_id": MODEL, "context_length": 100, "max_completion_tokens": 20,
                    "supported_parameters": ["max_tokens"],
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"}}
        raw = json.dumps({"data": {"id": MODEL, "endpoints": [
            {"tag": "deepinfra", **endpoint}, {"tag": "deepinfra/turbo", **endpoint}]}}).encode()
        with self.assertRaisesRegex(AdapterError, "variants"):
            fetch_endpoint_snapshot(MODEL, "deepinfra", catalog_fetch=lambda url: raw, now=lambda: NOW)
        snapshot = fetch_endpoint_snapshot(MODEL, "deepinfra/turbo", catalog_fetch=lambda url: raw,
                                           now=lambda: NOW)
        self.assertEqual(snapshot["provider_tag"], "deepinfra/turbo")

    def test_returned_provider_mismatch_is_invalid_with_cost_preserved(self):
        adapter = self.adapter()
        value = json.loads(completion())
        value["provider"] = "other-provider"
        parsed = adapter.parse(TransportResult(json.dumps(value).encode(), 200, 1),
                               expected_request_id="request-1", expected_ids=("a",),
                               expected_model=MODEL)
        self.assertEqual(parsed.status, "invalid")
        self.assertEqual(parsed.reason, "returned provider mismatch")
        self.assertEqual(parsed.observed_cost_microusd, 21)


if __name__ == "__main__":
    unittest.main()
