"""Report behavior on small, fully offline evidence."""

import math
import unittest

from classification_bench.core import ValidationError, build_plan
from classification_bench.report import generate_report


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.task = {"name": "fictional", "input_keys": ["text"],
                     "fields": [{"name": "class", "labels": ["yes", "no"]}]}
        self.experiment = {"configs": [{"id": "c", "model": "fixture", "settings":
                                          {"provider": "local", "route": "simulated", "reasoning": "off"}}],
                           "prompts": [{"id": "p0", "text": "Classify."},
                                       {"id": "p1", "text": "Classify with care."}],
                           "repeats": 2, "batch_size": 2}
        self.inputs = {"records": [{"id": "a", "input": {"text": "<script>alert(1)</script>"}},
                                   {"id": "b", "input": {"text": "second"}}]}
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        self.labels = {"records": [{"id": "a", "labels": {"class": "yes"}},
                                   {"id": "b", "labels": {"class": "no"}}]}
        self.predictions = {"records": [
            {"config_id": "c", "prompt_id": "p0", "repeat": 1, "id": "a", "prediction": {"class": "yes"}},
            {"config_id": "c", "prompt_id": "p0", "repeat": 1, "id": "b", "prediction": {"class": "no"}},
            {"config_id": "c", "prompt_id": "p0", "repeat": 2, "id": "a", "prediction": {"class": "no"}},
            {"config_id": "c", "prompt_id": "p0", "repeat": 2, "id": "b", "prediction": {"class": "no"}},
            {"config_id": "c", "prompt_id": "p1", "repeat": 1, "id": "a", "prediction": {"class": "yes"}},
            {"config_id": "c", "prompt_id": "p1", "repeat": 1, "id": "b", "prediction": {"class": "yes"}},
            {"config_id": "c", "prompt_id": "p1", "repeat": 2, "id": "a", "prediction": {"class": "yes"}},
            {"config_id": "c", "prompt_id": "p1", "repeat": 2, "id": "b", "prediction": {"class": "unknown"}},
        ]}

    def test_full_denominator_pairing_flips_and_private_escaping(self):
        html = generate_report(self.task, self.plan, self.labels, self.predictions)
        self.assertIn("Planned positions: 8; valid selected predictions: 7; no selected prediction: 0; invalid selected projection: 1", html)
        self.assertIn("Paired prompt effect against p0: -1 exact matches (2/2 → 1/2)", html)
        self.assertIn("Paired prompt effect against p0: +0 exact matches (1/2 → 1/2)", html)
        self.assertIn("1/2 (50.0%)", html)
        self.assertIn("Changed case IDs", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("data-filter='route'", html)
        self.assertIn("data-route='simulated'", html)
        self.assertIn("Canonical JSON SHA-256", html)
        self.assertIn("<svg role='img'", html)
        self.assertIn("Exact agreement by pass", html)
        self.assertIn("Paired prompt effect", html)
        self.assertIn("Pass range", html)
        self.assertIn("Whole experiment summary (unfiltered)", html)
        self.assertIn("article.hidden = !article.querySelector", html)
        self.assertIn("pipeline behavior, not model variability", html)

    def test_missing_and_operation_measurements_stay_distinct(self):
        self.predictions["records"].pop()
        request = self.plan["requests"][0]
        ops = [{"request_id": request["request_id"], "state": "completed",
                "duration_seconds": 2.0, "provider_generation_seconds": None,
                "pure_inference_seconds": None, "input_tokens": 11,
                "observed_cost_micro_usd": 5, "unresolved_hold_micro_usd": 3}]
        html = generate_report(self.task, self.plan, self.labels, self.predictions, ops)
        self.assertIn("valid selected predictions: 7; no selected prediction: 1; invalid selected projection: 0", html)
        self.assertIn("Client request duration", html)
        self.assertIn("2.000 s mean across 1 request(s)", html)
        self.assertIn("Provider generation time", html)
        self.assertIn("unavailable", html)
        self.assertIn("Observed provider charges", html)
        self.assertIn("5 micro USD", html)
        self.assertIn("Unresolved budget holds", html)
        self.assertIn("3 micro USD", html)
        self.assertIn("Agreement and observed cost", html)

    def test_malformed_refused_and_failed_without_predictions_are_observed_separately(self):
        removed = {("p0", 1), ("p1", 1), ("p0", 2)}
        self.predictions["records"] = [p for p in self.predictions["records"]
                                       if (p["prompt_id"], p["repeat"]) not in removed]
        by_condition = {(r["prompt_id"], r["repeat"]): r for r in self.plan["requests"]}
        malformed = by_condition[("p0", 1)]
        refusal = by_condition[("p1", 1)]
        failure = by_condition[("p0", 2)]
        operations = [
            {"request_id": malformed["request_id"], "ids": ["a", "b"],
             "state": "response_saved", "parsed_status": "invalid", "http_status": 200},
            {"request_id": refusal["request_id"], "ids": ["a", "b"],
             "state": "response_saved", "parsed_status": "refused", "http_status": 200},
            {"request_id": failure["request_id"], "ids": ["a", "b"],
             "state": "response_saved", "parsed_status": "failed", "http_status": 429},
        ]
        html = generate_report(self.task, self.plan, self.labels, self.predictions, operations)
        self.assertIn("valid selected predictions: 1; no selected prediction: 6; invalid selected projection: 1", html)
        self.assertIn("<td>invalid</td><td>3</td><td>8</td>", html)
        self.assertIn("<td>refused</td><td>2</td><td>8</td>", html)
        self.assertIn("<td>failed</td><td>2</td><td>8</td>", html)
        self.assertIn("<td>valid selected</td><td>1</td><td>8</td>", html)
        self.assertIn("Parsed outcomes: invalid: 1", html)
        self.assertIn("Parsed outcomes: refused: 1", html)
        self.assertIn("Parsed outcomes: failed: 1", html)
        self.assertNotIn("missing: 6; invalid: 1", html)

    def test_synthetic_accounting_uses_syn_units_not_dollars(self):
        request = self.plan["requests"][0]
        html = generate_report(self.task, self.plan, self.labels, self.predictions,
                               [{"request_id": request["request_id"], "route": "synthetic:offline",
                                 "state": "response_saved", "parsed_status": "valid",
                                 "observed_cost_micro_usd": 2}])
        self.assertIn("Observed synthetic accounting", html)
        self.assertIn("2 SYN units", html)
        self.assertIn("Synthetic accounting is not a provider charge.", html)
        self.assertNotIn("micro USD", html)

    def test_duplicate_request_or_nonfinite_negative_measurements_are_rejected(self):
        request_id = self.plan["requests"][0]["request_id"]
        operation = {"request_id": request_id, "observed_cost_micro_usd": 4}
        with self.assertRaisesRegex(ValidationError, "duplicate request_id"):
            generate_report(self.task, self.plan, self.labels, self.predictions,
                            [operation, dict(operation)])
        for bad in (-1, math.nan, math.inf, True, "4"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValidationError, "measurement"):
                generate_report(self.task, self.plan, self.labels, self.predictions,
                                [{"request_id": request_id, "observed_cost_micro_usd": bad}])

    def test_rejects_unrelated_operation(self):
        with self.assertRaisesRegex(ValidationError, "unknown request_id"):
            generate_report(self.task, self.plan, self.labels, self.predictions,
                            [{"request_id": "wrong", "state": "completed"}])

    def test_unverified_provider_is_explicit_without_discarding_classification(self):
        operation = {"request_id": self.plan['requests'][0]['request_id'],
                     "provider": "requested-host", "returned_provider": None,
                     "provider_identity_status": "unverified:AdapterError",
                     "parsed_status": "valid", "observed_cost_micro_usd": 21}
        html = generate_report(self.task, self.plan, self.labels, self.predictions, [operation])
        self.assertIn("Requested provider", html)
        self.assertIn("Observed provider", html)
        self.assertIn("unverified:AdapterError", html)
        self.assertIn("Requested routing is not proof", html)

    def test_mixed_batch_invalid_status_keeps_valid_item(self):
        from classification_bench.report import _observed_outcome
        good, bad = ('c', 'p', 1, 'a'), ('c', 'p', 1, 'b')
        supplied = {good: {'class': 'yes'}, bad: {'class': 'wrong'}}
        operation = {'parsed_status': 'invalid'}
        self.assertEqual(_observed_outcome(good, {bad}, supplied, operation), 'valid selected')
        self.assertEqual(_observed_outcome(bad, {bad}, supplied, operation), 'invalid')

    def test_plan_validation_is_not_bypassed(self):
        broken = dict(self.plan)
        broken["requests"] = []
        with self.assertRaises(ValidationError):
            generate_report(self.task, broken, self.labels, self.predictions)


if __name__ == "__main__":
    unittest.main()
