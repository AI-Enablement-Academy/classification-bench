"""A narrow, one-attempt provider boundary for categorical chat inference.

The scheduler owns admission and evidence publication. This module never retries,
persists evidence, reads labels, or treats a transport error as proof of no charge.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
from http.client import IncompleteRead
import json
import socket
import time
from urllib import error, parse, request as urlrequest
from typing import Protocol


CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_RESPONSE_BYTES = 1_000_000
MAX_CATALOG_BYTES = 2_000_000
TIMEOUT_SECONDS = 60


class AdapterError(ValueError):
    pass


class ClassificationAdapter(Protocol):
    """Scheduler-facing operations; future adapters may use other call topologies."""

    def prepare(self, plan, request, prompt) -> "PreparedRequest": ...
    def verify_live_snapshot(self) -> dict: ...
    def dispatch(self, prepared, api_key) -> "TransportResult": ...
    def parse(self, result, *, expected_request_id, expected_ids, expected_model) -> "ParsedResponse": ...


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _decimal(value, name):
    if not isinstance(value, str):
        raise AdapterError(f"{name} must be a decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise AdapterError(f"invalid {name}") from exc
    if not amount.is_finite() or amount < 0:
        raise AdapterError(f"invalid {name}")
    return amount


def _positive(value, name):
    if type(value) is not int or value < 1:
        raise AdapterError(f"{name} must be a positive integer")
    return value


def _date(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AdapterError("snapshot observed_at must be UTC ISO8601")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AdapterError("invalid snapshot observation time") from exc


def _microusd(value):
    return int((value * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def _catalog_url(model):
    if (not isinstance(model, str) or model.count("/") != 1 or ":" in model or
            model.startswith("~") or model.startswith("openrouter/") or
            any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for c in model.replace("/", ""))):
        raise AdapterError("model must be an exact OpenRouter slug")
    return f"https://openrouter.ai/api/v1/models/{model}/endpoints"


def _provider_slug(value):
    if (not isinstance(value, str) or not value or value.startswith("/") or value.endswith("/") or
            value.count("/") > 1 or any(not part or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in part)
                                      for part in value.split("/"))):
        raise AdapterError("provider must be an exact provider endpoint slug")
    return value


def _unique_endpoint(data, provider):
    endpoints = data["endpoints"]
    matches = [x for x in endpoints if isinstance(x, dict) and x.get("tag") == provider]
    if len(matches) != 1:
        raise AdapterError("pinned provider endpoint is absent or ambiguous")
    if "/" not in provider and any(isinstance(x, dict) and isinstance(x.get("tag"), str) and
                                   x["tag"].startswith(provider + "/") for x in endpoints):
        raise AdapterError("base provider slug also matches endpoint variants; select exact variant")
    return matches[0]


def _snapshot_from_endpoint(model, provider, url, endpoint, observed_at):
    if not isinstance(endpoint, dict) or endpoint.get("tag") != provider or endpoint.get("model_id") != model:
        raise AdapterError("endpoint model/provider mismatch")
    prompt_limit = endpoint.get("max_prompt_tokens")
    if prompt_limit is None:
        prompt_limit = endpoint.get("context_length")
    _positive(prompt_limit, "max_prompt_tokens/context_length")
    completion_limit = _positive(endpoint.get("max_completion_tokens"), "max_completion_tokens")
    raw_pricing = endpoint.get("pricing")
    if not isinstance(raw_pricing, dict) or not {"prompt", "completion"} <= set(raw_pricing):
        raise AdapterError("missing endpoint token pricing")
    # OpenRouter may omit zero request pricing and include a discount metadata field.
    # provider.max_price.request=0 is sent regardless, so a billed request fee cannot route.
    pricing = {k: v for k, v in raw_pricing.items() if k != "discount"}
    pricing.setdefault("request", "0")
    for key, value in pricing.items():
        _decimal(value, f"pricing.{key}")
    supported = endpoint.get("supported_parameters")
    if not isinstance(supported, list):
        raise AdapterError("endpoint parameters unavailable")
    return {"model_id": model, "provider_tag": provider, "observed_at": observed_at,
            "source_url": url, "max_prompt_tokens": prompt_limit,
            "max_completion_tokens": completion_limit,
            "supported_parameters": supported, "pricing": pricing}


def fetch_endpoint_snapshot(model, provider, *, catalog_fetch=None, now=None):
    """Capture one public catalog endpoint without a credential or inference call."""
    url = _catalog_url(model)
    _provider_slug(provider)
    fetch = catalog_fetch or _default_catalog_fetch
    clock = now or (lambda: datetime.now(timezone.utc))
    try:
        value = json.loads(fetch(url))
        data = value["data"]
        if data["id"] != model or not isinstance(data["endpoints"], list):
            raise AdapterError("catalog model mismatch")
        endpoint = _unique_endpoint(data, provider)
        observed_at = clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return _snapshot_from_endpoint(model, provider, url, endpoint, observed_at)
    except (OSError, TimeoutError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AdapterError("catalog could not be captured") from exc


@dataclass(frozen=True)
class PreparedRequest:
    body: bytes
    reserve_microusd: int
    bound_source: str
    route: str
    request_id: str
    expected_ids: tuple


@dataclass(frozen=True)
class TransportResult:
    raw_bytes: bytes
    http_status: int | None
    duration_ms: int
    error: str | None = None
    redacted: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class ParsedResponse:
    status: str
    predictions: tuple
    usage: dict | None
    observed_cost_microusd: int | None
    returned_model: str | None
    provider: str | None
    response_id: str | None
    finish_reason: str | None
    reason: str | None = None


def _capture(stream, limit):
    chunks = []
    size = 0
    partial_error = None
    while size <= limit:
        try:
            piece = stream.read(min(65536, limit + 1 - size))
        except IncompleteRead as exc:
            piece = exc.partial
            if piece:
                chunks.append(piece[:limit + 1 - size])
                size += min(len(piece), limit + 1 - size)
            partial_error = "IncompleteRead"
            break
        except (OSError, TimeoutError) as exc:
            partial_error = type(exc).__name__
            break
        if not piece:
            break
        chunks.append(piece)
        size += len(piece)
    raw = b"".join(chunks)
    return raw[:limit], len(raw) > limit, partial_error


def _default_transport(url, headers, body, timeout, limit):
    req = urlrequest.Request(url, data=body, headers=headers, method="POST")
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            raw, truncated, read_error = _capture(response, limit)
            return response.status, raw, truncated, read_error
    except error.HTTPError as exc:
        raw, truncated, read_error = _capture(exc, limit)
        return exc.code, raw, truncated, read_error


def _default_catalog_fetch(url):
    req = urlrequest.Request(url, headers={"Accept": "application/json"})
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}), _NoRedirect())
    with opener.open(req, timeout=10) as response:
        if response.status != 200:
            raise AdapterError("catalog HTTP status is not 200")
        raw, truncated, read_error = _capture(response, MAX_CATALOG_BYTES)
    if truncated or read_error:
        raise AdapterError("catalog response incomplete")
    return raw


class _NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_generation_fetch(url, headers, timeout, limit):
    req = urlrequest.Request(url, headers=headers, method="GET")
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            raw, truncated, read_error = _capture(response, limit)
            return response.status, raw, truncated, read_error
    except error.HTTPError as exc:
        raw, truncated, read_error = _capture(exc, limit)
        return exc.code, raw, truncated, read_error


class OpenRouterAdapter:
    """One pinned OpenRouter chat route, with explicit controls and price bound."""

    def __init__(self, config, *, transport=None, catalog_fetch=None, generation_fetch=None, now=None):
        if not isinstance(config, dict) or not {"id", "model"} <= set(config) or set(config) - {"id", "model", "settings"}:
            raise AdapterError("invalid experiment configuration")
        self.config = config
        self.model = config["model"]
        settings = config.get("settings", {})
        if not isinstance(settings, dict) or set(settings) - {"adapter", "provider", "max_output_tokens", "temperature", "top_p", "endpoint_snapshot"}:
            raise AdapterError("unsupported OpenRouter setting")
        if settings.get("adapter") != "openrouter":
            raise AdapterError("adapter must be openrouter")
        _catalog_url(self.model)
        self.provider = _provider_slug(settings.get("provider"))
        self.max_output_tokens = _positive(settings.get("max_output_tokens"), "max_output_tokens")
        self.snapshot = settings.get("endpoint_snapshot")
        self._validate_snapshot(self.snapshot)
        self.controls = {}
        for name, lower, upper in (("temperature", 0, 2), ("top_p", 0, 1)):
            if name in settings:
                value = settings[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not lower <= value <= upper:
                    raise AdapterError(f"invalid {name}")
                if name not in self.snapshot["supported_parameters"]:
                    raise AdapterError(f"endpoint does not support {name}")
                self.controls[name] = value
        self.transport = transport or _default_transport
        self.catalog_fetch = catalog_fetch or _default_catalog_fetch
        self.generation_fetch = generation_fetch or _default_generation_fetch
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _validate_snapshot(self, snapshot):
        required = {"model_id", "provider_tag", "observed_at", "source_url", "max_prompt_tokens", "max_completion_tokens", "supported_parameters", "pricing"}
        if not isinstance(snapshot, dict) or set(snapshot) != required:
            raise AdapterError("endpoint snapshot has missing or unknown fields")
        if snapshot["model_id"] != self.model or snapshot["provider_tag"] != self.provider:
            raise AdapterError("endpoint model/provider mismatch")
        expected_url = _catalog_url(self.model)
        if snapshot["source_url"] != expected_url:
            raise AdapterError("endpoint source URL mismatch")
        _date(snapshot["observed_at"])
        _positive(snapshot["max_prompt_tokens"], "max_prompt_tokens")
        _positive(snapshot["max_completion_tokens"], "max_completion_tokens")
        if self.max_output_tokens > snapshot["max_completion_tokens"]:
            raise AdapterError("output limit exceeds endpoint capability")
        supported = snapshot["supported_parameters"]
        if not isinstance(supported, list) or not all(isinstance(x, str) for x in supported):
            raise AdapterError("invalid endpoint parameters")
        if not ({"max_completion_tokens", "max_tokens"} & set(supported)):
            raise AdapterError("endpoint cannot enforce output limit")
        prices = snapshot["pricing"]
        if not isinstance(prices, dict) or not {"prompt", "completion", "request"} <= set(prices):
            raise AdapterError("missing endpoint prices")
        prompt_price = _decimal(prices["prompt"], "pricing.prompt")
        for key, value in prices.items():
            amount = _decimal(value, f"pricing.{key}")
            if key == "input_cache_read" and amount > prompt_price:
                raise AdapterError("cache read price exceeds prompt price bound")
            if key == "web_search" and amount != 0 and (self.model, self.provider) != (
                    "openai/gpt-4.1-nano", "openai"):
                raise AdapterError("unbounded web search price for this route")
            if key == "request" and amount != 0:
                raise AdapterError("request fee exceeds enforced zero max_price")
            if key not in ("prompt", "completion", "input_cache_read", "web_search") and amount != 0:
                raise AdapterError(f"unbounded price component: {key}")

    def prepare(self, plan, request, prompt):
        if not isinstance(plan, dict) or not isinstance(request, dict) or not isinstance(prompt, dict):
            raise AdapterError("plan, request and prompt must be objects")
        if request.get("config_id") != self.config["id"] or request.get("prompt_id") != prompt.get("id"):
            raise AdapterError("request configuration or prompt mismatch")
        items = request.get("items")
        fields = plan.get("task", {}).get("fields")
        if not isinstance(items, list) or not items or not isinstance(fields, list) or not fields:
            raise AdapterError("request must have task fields and items")
        ids = tuple(item.get("id") for item in items)
        if any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
            raise AdapterError("invalid batch IDs")
        content = _json_bytes({"request_id": request["request_id"], "items": items, "fields": fields}).decode("utf-8")
        instruction = ("Return only a JSON object with exactly request_id and predictions. "
                       f"Set request_id to {json.dumps(request['request_id'])}. "
                       "Predictions must be an array with one object for each input id, in input order. "
                       "Each object has exactly id and prediction. Prediction maps every declared field "
                       "to one of its declared labels. Do not include explanations or markdown.")
        prices = self.snapshot["pricing"]
        prompt_price = _decimal(prices["prompt"], "pricing.prompt")
        completion_price = _decimal(prices["completion"], "pricing.completion")
        bound = (_decimal(prices["request"], "pricing.request") +
                 self.snapshot["max_prompt_tokens"] * prompt_price +
                 self.max_output_tokens * completion_price)
        reserve = _microusd(bound)
        if reserve < 1:
            raise AdapterError("zero-priced routes need separate no-fee evidence")
        output_key = ("max_completion_tokens" if "max_completion_tokens" in self.snapshot["supported_parameters"]
                      else "max_tokens")
        body = {"model": self.model, "messages": [{"role": "system", "content": prompt["text"]},
                                                    {"role": "user", "content": instruction + "\n\n" + content}],
                output_key: self.max_output_tokens, "stream": False,
                "usage": {"include": True},
                "provider": {"only": [self.provider], "allow_fallbacks": False,
                             "require_parameters": True,
                             "max_price": {"prompt": float(prompt_price * 1_000_000),
                                           "completion": float(completion_price * 1_000_000),
                                           "request": 0}}}
        body.update(self.controls)
        snapshot_hash = hashlib.sha256(_json_bytes(self.snapshot)).hexdigest()
        return PreparedRequest(_json_bytes(body), reserve, f"openrouter:endpoint:{snapshot_hash}",
                               f"openrouter:{self.model}:{self.provider}", request["request_id"], ids)

    def verify_live_snapshot(self):
        """Re-read public endpoint catalog immediately before paid admission."""
        try:
            raw = self.catalog_fetch(self.snapshot["source_url"])
            value = json.loads(raw)
            data = value["data"]
            if data["id"] != self.model or not isinstance(data["endpoints"], list):
                raise AdapterError("catalog model mismatch")
            selected = _unique_endpoint(data, self.provider)
            endpoint = _snapshot_from_endpoint(self.model, self.provider, self.snapshot["source_url"],
                                               selected, self.snapshot["observed_at"])
            for name in ("max_prompt_tokens", "max_completion_tokens", "supported_parameters", "pricing"):
                if endpoint[name] != self.snapshot[name]:
                    raise AdapterError(f"endpoint {name} drifted")
            return {"catalog_sha256": hashlib.sha256(raw).hexdigest(),
                    "checked_at": self.now().isoformat(), "source_url": self.snapshot["source_url"]}
        except (OSError, TimeoutError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AdapterError("catalog could not be verified") from exc

    def dispatch(self, prepared, api_key):
        if not isinstance(prepared, PreparedRequest) or not isinstance(api_key, str) or not api_key:
            raise AdapterError("prepared request and API key required")
        if not prepared.route == f"openrouter:{self.model}:{self.provider}":
            raise AdapterError("prepared route mismatch")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                   "Accept": "application/json", "X-OpenRouter-Cache": "false"}
        start = time.monotonic_ns()
        try:
            status, raw, truncated, read_error = self.transport(CHAT_URL, headers, prepared.body,
                                                                 TIMEOUT_SECONDS, MAX_RESPONSE_BYTES)
            if not isinstance(raw, bytes) or type(status) is not int:
                raise AdapterError("transport returned invalid result")
        except (OSError, TimeoutError, socket.timeout, error.URLError) as exc:
            return TransportResult(b"", None, (time.monotonic_ns() - start) // 1_000_000,
                                   type(exc).__name__)
        key_bytes = api_key.encode("utf-8")
        redacted = key_bytes in raw
        if redacted:
            raw = raw.replace(key_bytes, b"[REDACTED_API_KEY]")
        return TransportResult(raw, status, (time.monotonic_ns() - start) // 1_000_000,
                               read_error, redacted, truncated)

    def lookup_generation(self, response_id, api_key):
        """Read generation metadata after the completion body has been saved."""
        if not isinstance(response_id, str) or not response_id or not isinstance(api_key, str) or not api_key:
            raise AdapterError("generation ID and API key required")
        url = "https://openrouter.ai/api/v1/generation?id=" + parse.quote(response_id, safe="")
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        start = time.monotonic_ns()
        try:
            status, raw, truncated, read_error = self.generation_fetch(url, headers, 10, MAX_RESPONSE_BYTES)
            if not isinstance(raw, bytes) or type(status) is not int:
                raise AdapterError("generation transport returned invalid result")
        except (OSError, TimeoutError, socket.timeout, error.URLError) as exc:
            return TransportResult(b"", None, (time.monotonic_ns() - start) // 1_000_000,
                                   type(exc).__name__)
        key_bytes = api_key.encode("utf-8")
        redacted = key_bytes in raw
        if redacted:
            raw = raw.replace(key_bytes, b"[REDACTED_API_KEY]")
        return TransportResult(raw, status, (time.monotonic_ns() - start) // 1_000_000,
                               read_error, redacted, truncated)

    def parse_generation(self, result, *, expected_response_id, expected_model):
        if not isinstance(result, TransportResult) or result.http_status != 200 or result.error or result.truncated:
            raise AdapterError("generation metadata unavailable")
        try:
            data = json.loads(result.raw_bytes)["data"]
        except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AdapterError("invalid generation metadata") from exc
        if not isinstance(data, dict) or data.get("id") != expected_response_id or data.get("model") != expected_model:
            raise AdapterError("generation identity mismatch")
        provider_name = data.get("provider_name")
        if not isinstance(provider_name, str) or not provider_name:
            raise AdapterError("generation provider identity unavailable")
        cost = data.get("total_cost")
        observed_cost = None
        if cost is not None:
            observed_cost = _microusd(_decimal(str(cost), "generation.total_cost"))
        return {"provider_name": provider_name, "observed_cost_microusd": observed_cost,
                "generation_time_ms": data.get("generation_time"),
                "request_id": data.get("request_id"), "is_byok": data.get("is_byok")}

    def parse(self, result, *, expected_request_id, expected_ids, expected_model):
        if not isinstance(result, TransportResult):
            raise AdapterError("transport result required")
        if result.http_status != 200:
            return ParsedResponse("unknown", (), None,
                                  None, None, None, None, None,
                                  f"HTTP {result.http_status}" if result.http_status is not None else result.error)
        if result.error or result.truncated:
            return ParsedResponse("invalid", (), None, None, None, None, None, None,
                                  "response body incomplete")
        try:
            value = json.loads(result.raw_bytes)
        except (UnicodeError, json.JSONDecodeError):
            return ParsedResponse("invalid", (), None, None, None, None, None, None, "invalid UTF-8 JSON")
        if not isinstance(value, dict):
            return ParsedResponse("invalid", (), None, None, None, None, None, None, "response is not object")
        model = value.get("model")
        response_id = value.get("id") if isinstance(value.get("id"), str) else None
        provider = value.get("provider") if isinstance(value.get("provider"), str) else None
        if model != expected_model or model != self.model:
            reason = "returned model mismatch"
        elif (provider is not None and provider != self.provider and
              (self.provider, provider) != ("openai", "OpenAI")):
            reason = "returned provider mismatch"
        else:
            reason = None
        usage = value.get("usage") if isinstance(value.get("usage"), dict) else None
        charge = None
        if usage and usage.get("cost") is not None:
            try:
                charge = _microusd(_decimal(str(usage["cost"]), "usage.cost"))
            except AdapterError:
                reason = reason or "invalid observed cost"
        choices = value.get("choices")
        finish = None
        predictions = ()
        if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict):
            choice = choices[0]
            finish = choice.get("finish_reason")
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                try:
                    content = json.loads(message["content"])
                    if (isinstance(content, dict) and content.get("request_id") == expected_request_id and
                            isinstance(content.get("predictions"), list)):
                        entries = content["predictions"]
                        ids = [x.get("id") for x in entries if isinstance(x, dict)]
                        if (len(ids) == len(entries) and ids == list(expected_ids) and
                                all(set(x) == {"id", "prediction"} and isinstance(x.get("prediction"), dict)
                                    for x in entries) and set(content) == {"request_id", "predictions"}):
                            predictions = tuple(entries)
                except (UnicodeError, json.JSONDecodeError, TypeError):
                    pass
        if reason:
            return ParsedResponse("invalid", (), usage, charge, model, provider, response_id, finish, reason)
        if finish in ("content_filter", "refusal") or (isinstance(choices, list) and choices and isinstance(choices[0], dict) and
                isinstance(choices[0].get("message"), dict) and choices[0]["message"].get("refusal")):
            return ParsedResponse("refused", (), usage, charge, model, provider, response_id, finish, "provider refusal")
        if not predictions or finish != "stop":
            return ParsedResponse("invalid", (), usage, charge, model, provider, response_id, finish,
                                  "missing or incomplete classification output")
        return ParsedResponse("valid", predictions, usage, charge, model, provider, response_id, finish)
