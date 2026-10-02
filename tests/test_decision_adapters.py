"""Offline fixtures for native typed-choice admission and parsing."""

from datetime import datetime, timezone
import hashlib
import json
import unittest

from classification_bench.adapters import AdapterError, TransportResult
from classification_bench.decision_adapters import DecisionAdapter, CONTRACTS


NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
PAGE = b"reviewed-offline-provider-page"


def fixture(kind="liquid_decide", *, basis="free"):
    contract = CONTRACTS[kind]
    if contract["provider"] == "cloudflare":
        basis = "metered"
    snapshot = {"source_url": contract["billing_url"],
                "response_sha256": hashlib.sha256(PAGE).hexdigest(),
                "observed_at": "2026-09-29T12:00:00Z",
                "valid_until": "2026-10-01T12:00:00Z",
                "max_input_tokens": contract["context"] or 16384,
                "input_usd_per_token": (str(contract["input_rate"]) if contract["provider"] == "cloudflare"
                                         else "0" if basis == "free" else "0.000001"),
                "output_usd_per_token": "0", "request_usd": "0", "basis": basis}
    settings = {"adapter": kind, "billing_snapshot": snapshot}
    if kind == "qwen_decision":
        settings.update(workspace_id="ws-123", region="ap-southeast-1")
    if contract["provider"] == "cloudflare":
        settings["account_id"] = "a" * 32
    config = {"id": "c", "model": contract["model"], "settings": settings}
    plan = {"task": {"name": "classify", "fields": [
        {"name": "category", "labels": ["yes", "no"]},
        {"name": "tone", "labels": ["warm", "cold"]}]}}
    request = {"request_id": "request-1", "config_id": "c", "prompt_id": "p",
               "items": [{"id": "row-1", "input": {"text": "hello"}}]}
    prompt = {"id": "p", "text": "Apply the exact task rubric."}
    return config, plan, request, prompt


def response(kind="liquid_decide", *, answers=None):
    if answers is None:
        answers = {"category": {"type": "choice", "choice": "yes",
                                "probabilities": {"yes": 0.7, "no": 0.3}, "confidence": 0.6},
                   "tone": {"type": "choice", "choice": "warm",
                            "probabilities": {"warm": 0.8, "cold": 0.2}, "confidence": 0.7}}
    value = {"model": CONTRACTS[kind]["model"], "answers": answers,
             "usage": {"input_tokens": 53, "output_tokens": 0}}
    if kind == "qwen_decision":
        value["request_id"] = "provider-request-1"
    if CONTRACTS[kind]["provider"] == "cloudflare":
        value = {"result": value, "success": True, "errors": [], "messages": []}
    return TransportResult(json.dumps(value).encode(), 200, 4)


class DecisionAdapterTests(unittest.TestCase):
    def test_metered_qwen_reserves_full_context_for_every_question(self):
        config, plan, request, prompt = fixture('qwen_decision', basis='metered')
        config['settings']['billing_snapshot']['request_usd'] = '0.01'
        prepared = DecisionAdapter(config).prepare(plan, request, prompt)
        self.assertEqual(prepared.reserve_microusd, 2 * (65536 + 10000))
        config['settings']['billing_snapshot']['output_usd_per_token'] = '0.000001'
        with self.assertRaisesRegex(AdapterError, 'no enforceable output-token limit'):
            DecisionAdapter(config)

    def adapter(self, kind="liquid_decide", **kwargs):
        config, plan, request, prompt = fixture(kind)
        adapter = DecisionAdapter(config, now=lambda: NOW, billing_fetch=lambda url: PAGE, **kwargs)
        prepared = adapter.prepare(plan, request, prompt)
        return adapter, prepared, config, plan, request, prompt

    def test_prepared_request_preserves_prompt_input_labels_and_one_item(self):
        for kind in CONTRACTS:
            with self.subTest(kind=kind):
                adapter, prepared, _, plan, request, prompt = self.adapter(kind)
                body = json.loads(prepared.body)
                self.assertEqual(body["state"]["prompt"], prompt["text"])
                self.assertEqual(body["state"]["item"], request["items"][0])
                self.assertEqual(body["questions"]["category"]["instructions"], prompt["text"])
                self.assertEqual(body["questions"]["category"]["criteria"],
                                 {"yes": "yes", "no": "no"})
                self.assertEqual(prepared.expected_ids, ("row-1",))
                self.assertEqual(prepared.reserve_microusd,
                                 15729 if kind == "clef_decide" else 5899 if kind == "clef_flash_decide" else 1)
                self.assertEqual(adapter.verify_live_snapshot()["billing_response_sha256"],
                                 hashlib.sha256(PAGE).hexdigest())
                request["items"].append({"id": "row-2", "input": {"text": "bye"}})
                with self.assertRaisesRegex(AdapterError, "batch_size=1"):
                    adapter.prepare(plan, request, prompt)

    def test_official_shapes_preserve_probability_and_confidence_separately(self):
        for kind in CONTRACTS:
            with self.subTest(kind=kind):
                adapter, prepared, _, _, _, _ = self.adapter(kind)
                parsed = adapter.parse(response(kind), expected_request_id=prepared.request_id,
                                       expected_ids=prepared.expected_ids, expected_model=adapter.model)
                self.assertEqual(parsed.status, "valid")
                self.assertEqual(parsed.predictions[0]["prediction"],
                                 {"category": "yes", "tone": "warm"})
                self.assertEqual(parsed.usage["decision_answers"]["category"]["confidence"], 0.6)
                self.assertEqual(parsed.usage["decision_answers"]["category"]["probabilities"]["yes"], 0.7)
                self.assertIsNone(parsed.observed_cost_microusd)

    def test_malformed_answers_are_invalid_and_serializable(self):
        adapter, prepared, _, _, _, _ = self.adapter()
        args = {"expected_request_id": prepared.request_id, "expected_ids": prepared.expected_ids,
                "expected_model": adapter.model}
        raw = response().raw_bytes
        for bad in (raw.replace(b'"yes"', b'"other"', 1),
                    raw.replace(b'"choice": "yes"', b'"choice": []'),
                    raw.replace(b'"confidence": 0.6', b'"confidence": NaN'),
                    raw.replace(b'"model": "d1:free"', b'"model": "other"')):
            with self.subTest(bad=bad):
                parsed = adapter.parse(TransportResult(bad, 200, 1), **args)
                self.assertEqual(parsed.status, "invalid")
                json.dumps(parsed.usage, allow_nan=False)

    def test_billing_snapshot_fails_closed_on_rates_context_and_drift(self):
        config, plan, request, prompt = fixture("solar_decide", basis="metered")
        with self.assertRaisesRegex(AdapterError, "direct Solar Decide price"):
            DecisionAdapter(config)
        config, _, _, _ = fixture("qwen_decision", basis="metered")
        config["settings"]["billing_snapshot"]["max_input_tokens"] = 100
        with self.assertRaisesRegex(AdapterError, "full published context"):
            DecisionAdapter(config)
        config, _, _, _ = fixture("qwen_decision", basis="metered")
        config["settings"]["billing_snapshot"]["input_usd_per_token"] = "0"
        with self.assertRaisesRegex(AdapterError, "no billable rate"):
            DecisionAdapter(config)
        config, _, _, _ = fixture()
        config["settings"]["billing_snapshot"]["request_usd"] = "0.1"
        with self.assertRaisesRegex(AdapterError, "free attestation"):
            DecisionAdapter(config)
        for clock, page, reason in ((datetime(2026, 9, 28, tzinfo=timezone.utc), PAGE, "future"),
                                    (datetime(2026, 10, 2, tzinfo=timezone.utc), PAGE, "expired"),
                                    (NOW, b"changed", "changed")):
            config, _, _, _ = fixture()
            adapter = DecisionAdapter(config, now=lambda: clock, billing_fetch=lambda url: page)
            with self.assertRaisesRegex(AdapterError, reason):
                adapter.verify_live_snapshot()

    def test_clef_exact_rates_account_and_rest_envelope(self):
        for kind, reserve in (("clef_decide", 15729), ("clef_flash_decide", 5899)):
            with self.subTest(kind=kind):
                adapter, prepared, config, _, _, _ = self.adapter(kind)
                self.assertEqual(prepared.reserve_microusd, reserve)
                self.assertIn("/ai/run/@cf/cloudflare/", adapter.endpoint)
                valid = adapter.parse(response(kind), expected_request_id=prepared.request_id,
                                      expected_ids=prepared.expected_ids, expected_model=adapter.model)
                self.assertEqual(valid.status, "valid")
                self.assertEqual(valid.usage["decision_answers"]["category"]["confidence"], 0.6)
                self.assertIsNone(valid.observed_cost_microusd)
                failed = json.loads(response(kind).raw_bytes)
                failed["success"] = False
                invalid = adapter.parse(TransportResult(json.dumps(failed).encode(), 200, 1),
                                        expected_request_id=prepared.request_id,
                                        expected_ids=prepared.expected_ids, expected_model=adapter.model)
                self.assertEqual(invalid.status, "invalid")
                failed["success"] = True
                failed["errors"] = [{"code": 1, "message": "provider error"}]
                errors = adapter.parse(TransportResult(json.dumps(failed).encode(), 200, 1),
                                       expected_request_id=prepared.request_id,
                                       expected_ids=prepared.expected_ids, expected_model=adapter.model)
                self.assertEqual(errors.status, "invalid")
                failed["errors"] = []
                failed["result"]["model"] = "other-model"
                mismatch = adapter.parse(TransportResult(json.dumps(failed).encode(), 200, 1),
                                         expected_request_id=prepared.request_id,
                                         expected_ids=prepared.expected_ids, expected_model=adapter.model)
                self.assertEqual(mismatch.status, "invalid")
                self.assertIn("model mismatch", mismatch.reason)
                failed["result"]["model"] = adapter.model
                failed["result"].pop("usage")
                no_usage = adapter.parse(TransportResult(json.dumps(failed).encode(), 200, 1),
                                         expected_request_id=prepared.request_id,
                                         expected_ids=prepared.expected_ids, expected_model=adapter.model)
                self.assertEqual(no_usage.status, "valid")
                self.assertIsNone(no_usage.observed_cost_microusd)
                config["settings"]["billing_snapshot"]["input_usd_per_token"] = "0.00000001"
                with self.assertRaisesRegex(AdapterError, "published input-only price"):
                    DecisionAdapter(config)
                config["settings"]["account_id"] = "../escape"
                with self.assertRaisesRegex(AdapterError, "invalid Cloudflare account ID"):
                    DecisionAdapter(config)

    def test_clef_question_contract_rejects_unsafe_ids_and_overflow(self):
        config, plan, request, prompt = fixture("clef_decide")
        adapter = DecisionAdapter(config)
        plan["task"]["fields"][0]["name"] = "bad/question"
        with self.assertRaisesRegex(AdapterError, "question ID"):
            adapter.prepare(plan, request, prompt)
        plan["task"]["fields"] = [{"name": f"field_{i}", "labels": ["a", "b"]}
                                    for i in range(65)]
        with self.assertRaisesRegex(AdapterError, "at most 64 questions"):
            adapter.prepare(plan, request, prompt)


if __name__ == "__main__":
    unittest.main()
