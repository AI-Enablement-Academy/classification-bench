"""Typed-choice System One adapters. No reference labels or network calls at preparation."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import re
import socket
import time
from urllib import error

from .adapters import (AdapterError, ParsedResponse, PreparedRequest, TransportResult,
                       MAX_RESPONSE_BYTES, TIMEOUT_SECONDS, _default_catalog_fetch,
                       _default_transport, _json_bytes)


CONTRACTS = {
    "liquid_decide": {"model": "d1:free", "provider": "liquid",
                      "endpoint": "https://api.liquid.ai/decisions/v1/systemone",
                      "billing_url": "https://docs.liquid.ai/lfm/models/decision-models",
                      "credential": "LIQUID_API_KEY", "context": None, "max_choices": None},
    "solar_decide": {"model": "solar-decide", "provider": "upstage",
                     "endpoint": "https://api.upstage.ai/v1/systemone",
                     "billing_url": "https://console.upstage.ai/api/systemone",
                     "credential": "UPSTAGE_API_KEY", "context": 524288, "max_choices": 26},
    "qwen_decision": {"model": "decision-model-preview", "provider": "qwen",
                      "billing_url": "https://help.aliyun.com/en/model-studio/decision-model-preview",
                      "credential": "DASHSCOPE_API_KEY", "context": 65536,
                      "max_choices": 255},
}
_REGIONS = {"ap-southeast-1", "cn-beijing"}
_HEX = re.compile(r"^[0-9a-f]{64}$")
_WORKSPACE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$")


def _date(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AdapterError("billing snapshot time must be UTC ISO8601")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AdapterError("invalid billing snapshot time") from exc


def _price(value, name):
    if not isinstance(value, str):
        raise AdapterError(f"{name} must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise AdapterError(f"invalid {name}") from exc
    if not number.is_finite() or number < 0:
        raise AdapterError(f"invalid {name}")
    return number


def _snapshot(snapshot, contract):
    keys = {"source_url", "response_sha256", "observed_at", "valid_until",
            "max_input_tokens", "input_usd_per_token", "output_usd_per_token",
            "request_usd", "basis"}
    if not isinstance(snapshot, dict) or set(snapshot) != keys:
        raise AdapterError("billing_snapshot has missing or unknown fields")
    if snapshot["source_url"] != contract["billing_url"] or not isinstance(snapshot["response_sha256"], str) or not _HEX.fullmatch(snapshot["response_sha256"]):
        raise AdapterError("billing source URL or hash mismatch")
    observed, expires = _date(snapshot["observed_at"]), _date(snapshot["valid_until"])
    if expires <= observed:
        raise AdapterError("billing snapshot validity interval is empty")
    ceiling = snapshot["max_input_tokens"]
    if type(ceiling) is not int or ceiling < 1:
        raise AdapterError("invalid max_input_tokens")
    rates = [_price(snapshot[k], k) for k in ("input_usd_per_token", "output_usd_per_token", "request_usd")]
    if snapshot["basis"] not in ("free", "metered"):
        raise AdapterError("unsupported billing basis")
    if snapshot["basis"] == "free" and any(rates):
        raise AdapterError("free attestation has nonzero rate")
    if snapshot["basis"] == "metered" and rates[0] == 0 and rates[2] == 0:
        raise AdapterError("metered attestation has no billable rate")
    if snapshot["basis"] == "metered" and rates[1] != 0:
        raise AdapterError("provider has no enforceable output-token limit")
    if snapshot["basis"] == "metered" and contract["provider"] == "upstage":
        raise AdapterError("direct Solar Decide price is not published in the pinned official source")
    if snapshot["basis"] == "metered" and (contract["context"] is None or ceiling != contract["context"]):
        raise AdapterError("metered reservation requires full published context ceiling")
    if contract["context"] is not None and ceiling > contract["context"]:
        raise AdapterError("max_input_tokens exceeds provider context")
    return rates


class DecisionAdapter:
    """One native System One call for one scheduler item and its task fields."""

    def __init__(self, config, *, transport=None, billing_fetch=None, now=None):
        if not isinstance(config, dict) or not {"id", "model", "settings"} <= set(config) or set(config) - {"id", "model", "settings"}:
            raise AdapterError("invalid decision configuration")
        settings = config["settings"]
        if not isinstance(settings, dict) or settings.get("adapter") not in CONTRACTS:
            raise AdapterError("unsupported decision adapter")
        self.kind = settings["adapter"]
        self.contract = CONTRACTS[self.kind]
        if config["model"] != self.contract["model"]:
            raise AdapterError("unsupported native decision model")
        allowed = {"adapter", "billing_snapshot"}
        if self.kind == "qwen_decision":
            allowed |= {"workspace_id", "region"}
        if set(settings) != allowed:
            raise AdapterError("unsupported or missing decision setting")
        if self.kind == "qwen_decision":
            workspace, region = settings["workspace_id"], settings["region"]
            if not isinstance(workspace, str) or not _WORKSPACE.fullmatch(workspace) or region not in _REGIONS:
                raise AdapterError("invalid Qwen workspace or region")
            self.endpoint = f"https://{workspace}.{region}.maas.aliyuncs.com/compatible-mode/v1/systemone"
        else:
            self.endpoint = self.contract["endpoint"]
        self.config = config
        self.model = config["model"]
        self.provider = self.contract["provider"]
        self.snapshot = settings["billing_snapshot"]
        self.rates = _snapshot(self.snapshot, self.contract)
        self.transport = transport or _default_transport
        self.billing_fetch = billing_fetch or _default_catalog_fetch
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._prepared_bodies = {}

    def prepare(self, plan, request, prompt):
        if request.get("config_id") != self.config["id"] or request.get("prompt_id") != prompt.get("id"):
            raise AdapterError("request configuration or prompt mismatch")
        items = request.get("items")
        fields = plan.get("task", {}).get("fields")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(fields, list) or not fields:
            raise AdapterError("native decision call requires batch_size=1 and task fields")
        item = items[0]
        if not isinstance(item.get("id"), str) or not isinstance(item.get("input"), dict):
            raise AdapterError("invalid decision item")
        questions = {}
        for field in fields:
            labels = field["labels"]
            if self.contract["max_choices"] is not None and len(labels) > self.contract["max_choices"]:
                raise AdapterError("too many native choice options")
            questions[field["name"]] = {"type": "choice", "instructions": prompt["text"],
                                        "criteria": {label: label for label in labels}}
        # State is a JSON object on these three APIs. Preserve every byte of the
        # prompt and input strings, with no generated rubric or reference data.
        state = {"request_id": request["request_id"], "task": plan["task"]["name"],
                 "prompt": prompt["text"], "item": item}
        body = _json_bytes({"model": self.model, "state": state, "questions": questions})
        self._prepared_bodies[request["request_id"]] = body
        if len(body) > self.snapshot["max_input_tokens"]:
            raise AdapterError("request bytes exceed conservative input token ceiling")
        input_rate, _, request_rate = self.rates
        # No direct provider exposes a request-level price cap. This is a
        # source-attested reservation, not a provider-enforced or observed fee.
        amount = (self.snapshot["max_input_tokens"] * input_rate + request_rate) * len(fields)
        reserve = max(1, int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING)))
        source = "decision:billing:" + hashlib.sha256(_json_bytes(self.snapshot)).hexdigest()
        return PreparedRequest(body, reserve, source,
                               f"{self.provider}:{self.model}", request["request_id"], (item["id"],))

    def verify_live_snapshot(self):
        if self.now() < _date(self.snapshot["observed_at"]):
            raise AdapterError("billing snapshot observed in the future")
        if self.now() >= _date(self.snapshot["valid_until"]):
            raise AdapterError("billing snapshot expired")
        raw = self.billing_fetch(self.snapshot["source_url"])
        if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != self.snapshot["response_sha256"]:
            raise AdapterError("billing source changed; re-review required")
        return {"billing_response_sha256": self.snapshot["response_sha256"],
                "checked_at": self.now().isoformat(), "source_url": self.snapshot["source_url"]}

    def dispatch(self, prepared, api_key):
        if not isinstance(prepared, PreparedRequest) or prepared.route != f"{self.provider}:{self.model}" or not isinstance(api_key, str) or not api_key:
            raise AdapterError("prepared decision route or credential mismatch")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                   "Accept": "application/json"}
        start = time.monotonic_ns()
        try:
            status, raw, truncated, read_error = self.transport(self.endpoint, headers, prepared.body,
                                                                 TIMEOUT_SECONDS, MAX_RESPONSE_BYTES)
            if type(status) is not int or not isinstance(raw, bytes):
                raise AdapterError("transport returned invalid result")
        except (OSError, TimeoutError, socket.timeout, error.URLError) as exc:
            return TransportResult(b"", None, (time.monotonic_ns() - start) // 1_000_000,
                                   type(exc).__name__)
        key = api_key.encode("utf-8")
        redacted = key in raw
        if redacted:
            raw = raw.replace(key, b"[REDACTED_API_KEY]")
        return TransportResult(raw, status, (time.monotonic_ns() - start) // 1_000_000,
                               read_error, redacted, truncated)

    def parse(self, result, *, expected_request_id, expected_ids, expected_model):
        if not isinstance(result, TransportResult):
            raise AdapterError("transport result required")
        if result.http_status != 200:
            return ParsedResponse("unknown", (), None, None, None, None, None, None,
                                  f"HTTP {result.http_status}" if result.http_status is not None else result.error)
        if result.error or result.truncated:
            return ParsedResponse("invalid", (), None, None, None, None, None, None,
                                  "response body incomplete")
        try:
            value = json.loads(result.raw_bytes,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            json.dumps(value, allow_nan=False)
        except (UnicodeError, json.JSONDecodeError, ValueError):
            return ParsedResponse("invalid", (), None, None, None, None, None, None, "invalid UTF-8 JSON")
        if not isinstance(value, dict):
            return ParsedResponse("invalid", (), None, None, None, None, None, None, "response is not object")
        model = value.get("model")
        raw_usage = value.get("usage")
        usage = dict(raw_usage) if isinstance(raw_usage, dict) else {}
        answers = value.get("answers")
        usage["decision_answers"] = answers
        response_id = value.get("request_id") if isinstance(value.get("request_id"), str) else None
        if model != self.model or expected_model != self.model:
            reason = "returned model mismatch"
        elif self.kind == "qwen_decision" and response_id is None:
            reason = "provider request identity missing"
        elif not isinstance(answers, dict) or not answers:
            reason = "missing decision answers"
        else:
            reason = None
        if reason:
            return ParsedResponse("invalid", (), usage, None, model, None, response_id, None, reason)
        try:
            body = json.loads(self._prepared_bodies[expected_request_id])
        except (KeyError, ValueError):
            # The runner prepares every frozen request before dispatch/recovery.
            body = None
        if body is None:
            return ParsedResponse("invalid", (), usage, None, model, None, response_id, None,
                                  "decision question binding unavailable")
        fields = body["questions"]
        if set(answers) != set(fields):
            reason = "decision answer fields mismatch"
        else:
            for field, answer in answers.items():
                if (not isinstance(answer, dict) or answer.get("type") != "choice" or
                        not isinstance(answer.get("choice"), str) or
                        answer["choice"] not in fields[field]["criteria"] or
                        not isinstance(answer.get("probabilities"), dict) or
                        set(answer["probabilities"]) != set(fields[field]["criteria"]) or
                        any(type(v) not in (int, float) or not 0 <= v <= 1 for v in answer["probabilities"].values()) or
                        type(answer.get("confidence")) not in (int, float) or
                        not 0 <= answer["confidence"] <= 1):
                    reason = "invalid typed choice answer"
                    break
        if reason:
            return ParsedResponse("invalid", (), usage, None, model, None, response_id, None, reason)
        predictions = ({"id": expected_ids[0],
                        "prediction": {name: answers[name]["choice"] for name in fields}},)
        return ParsedResponse("valid", predictions, usage, None, model, None, response_id, "complete")
