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
    snapshot = {"source_url": contract["billing_url"],
                "response_sha256": hashlib.sha256(PAGE).hexdigest(),
                "observed_at": "2026-09-29T12:00:00Z",
                "valid_until": "2026-10-01T12:00:00Z",
                "max_input_tokens": contract["context"] or 16384,
                "input_usd_per_token": "0" if basis == "free" else "0.000001",
                "output_usd_per_token": "0", "request_usd": "0", "basis": basis}
    settings = {"adapter": kind, "billing_snapshot": snapshot}
    if kind == "qwen_decision":
        settings.update(workspace_id="ws-123", region="ap-southeast-1")
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
                self.assertEqual(prepared.reserve_microusd, 1)
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


if __name__ == "__main__":
    unittest.main()
