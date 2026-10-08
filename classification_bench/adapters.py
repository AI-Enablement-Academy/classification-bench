"""A narrow, one-attempt provider boundary for categorical chat inference.

The scheduler owns admission and evidence publication. This module never retries,
persists evidence, reads labels, or treats a transport error as proof of no charge.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
MODEL_CATALOG_URL = "https://openrouter.ai/api/v1/models"
REASONING_EFFORTS = frozenset(("max", "xhigh", "high", "medium", "low", "minimal", "none"))
_REASONING_BOUND_SOURCES = {
    "openai-chat-max-completion-v1": "https://developers.openai.com/api/docs/guides/token-counting",
    "azure-openai-max-completion-v1": "https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/reasoning",
}
_TOKEN_PRICE_KEYS = frozenset(("prompt", "completion", "input_cache_read", "input_cache_write", "input_cache_write_1h"))
_ZERO_PRICE_KEYS = frozenset(("image", "audio", "audio_output", "image_output", "image_token", "input_audio_cache", "internal_reasoning"))
_NO_SEARCH_POLICY = {"tools": [], "tool_choice": "none",
                     "plugins": [{"id": "web", "enabled": False}, {"id": "response-healing", "enabled": False}]}
ACCOUNT_POLICY_MAX_AGE = timedelta(hours=24)


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
            any(not part for part in model.split("/")) or model.startswith("~") or
            model.startswith("openrouter/") or
            any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for c in model.replace("/", ""))):
        raise AdapterError("model must be an exact OpenRouter slug")
    return f"https://openrouter.ai/api/v1/models/{model}/endpoints"


def _model_url(model):
    _catalog_url(model)
    return f"https://openrouter.ai/api/v1/model/{model}"


def _model_identity(raw, requested_id, source_url, observed_at):
    if not isinstance(raw, bytes) or len(raw) > MAX_CATALOG_BYTES:
        raise AdapterError("model identity response must be bounded bytes")
    try:
        response_json = raw.decode("utf-8")
        data = json.loads(response_json)["data"]
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AdapterError("invalid model identity response") from exc
    if not isinstance(data, dict) or data.get("id") != requested_id:
        raise AdapterError("model identity requested ID mismatch")
    canonical = data.get("canonical_slug")
    _model_url(canonical)
    return {"requested_id": requested_id, "canonical_id": canonical,
            "source_url": source_url, "observed_at": observed_at,
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "response_json": response_json}


def _public_json(raw, name):
    if not isinstance(raw, bytes) or len(raw) > MAX_CATALOG_BYTES:
        raise AdapterError(f"{name} response must be bounded bytes")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"invalid {name} response") from exc
    if not isinstance(value, dict):
        raise AdapterError(f"invalid {name} response")
    return value, text


def _reasoning_metadata(value):
    """Preserve absent/null/list effort semantics; never infer from model names."""
    if not isinstance(value, dict):
        raise AdapterError("model reasoning capability must be an object")
    known = {}
    for key in ("mandatory", "default_enabled", "supports_max_tokens"):
        if key in value:
            if type(value[key]) is not bool:
                raise AdapterError(f"model reasoning {key} must be boolean")
            known[key] = value[key]
    if "supported_efforts" in value:
        efforts = value["supported_efforts"]
        if efforts is not None and (not isinstance(efforts, list) or
                not all(isinstance(x, str) and x for x in efforts) or len(set(efforts)) != len(efforts)):
            raise AdapterError("invalid model reasoning supported_efforts")
        known["supported_efforts"] = efforts
    if "default_effort" in value:
        effort = value["default_effort"]
        if not isinstance(effort, str) or not effort:
            raise AdapterError("invalid model reasoning default_effort")
        known["default_effort"] = effort
    return known


def fetch_model_catalog(*, catalog_fetch=None, now=None, query=None, offset=0, limit=1000):
    """Capture one public text-model discovery page, without credentials/inference.

    Catalog controls describe models, not admission to a particular paid route.
    Paging is explicit: no returned next URL is followed and no page is hidden.
    """
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise AdapterError("catalog offset/limit must be bounded nonnegative/positive integers")
    if query is not None and (not isinstance(query, str) or not query or len(query) > 1000):
        raise AdapterError("catalog query must be nonempty text of at most 1000 characters")
    parameters = {"output_modalities": "text", "offset": offset, "limit": limit}
    if query is not None:
        parameters["q"] = query
    url = MODEL_CATALOG_URL + "?" + parse.urlencode(parameters)
    fetch = catalog_fetch or _default_catalog_fetch
    clock = now or (lambda: datetime.now(timezone.utc))
    try:
        raw = fetch(url)
        value, response_json = _public_json(raw, "model catalog")
        rows, total, links = value.get("data"), value.get("total_count"), value.get("links")
        if (not isinstance(rows, list) or len(rows) > limit or type(total) is not int or total < 0 or
                not isinstance(links, dict) or "next" not in links):
            raise AdapterError("model catalog page/count metadata unavailable")
        next_link = links["next"]
        if next_link is not None and (not isinstance(next_link, str) or not next_link):
            raise AdapterError("invalid model catalog next page")
        more = offset + len(rows) < total
        if ((more and (not rows or next_link is None)) or (not more and next_link is not None) or
                (rows and offset + len(rows) > total)):
            raise AdapterError("model catalog page is incomplete or inconsistent")
        models, seen = [], set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                raise AdapterError("model catalog has an invalid model ID")
            if row["id"] in seen:
                raise AdapterError("model catalog has duplicate model IDs")
            seen.add(row["id"])
            model = {key: row[key] for key in ("id", "canonical_slug", "name", "context_length", "pricing",
                                               "supported_parameters", "architecture", "reasoning") if key in row}
            # Variant and dynamic entries remain visible even when this adapter cannot pin them.
            try:
                _catalog_url(row["id"])
                compatible = True
                incompatibility = None
            except AdapterError as exc:
                compatible, incompatibility = False, str(exc)
            model["endpoint_snapshot_compatible"] = compatible
            model["endpoint_snapshot_incompatibility"] = incompatibility
            model["reasoning_budget_eligibility"] = "requires_pinned_endpoint_snapshot"
            models.append(model)
        observed = clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return {"schema_version": 1, "source_url": url, "observed_at": observed,
                "response_sha256": hashlib.sha256(raw).hexdigest(), "response_json": response_json,
                "query": query, "offset": offset, "limit": limit, "models": models,
                "returned_count": len(models), "total_count": total,
                "next_offset": offset + len(rows) if more else None,
                "complete": offset == 0 and len(rows) == total}
    except (OSError, TimeoutError, UnicodeError, KeyError, TypeError) as exc:
        raise AdapterError("public model catalog could not be captured") from exc


def _endpoint_evidence(raw, model, provider, url, observed_at):
    value, response_json = _public_json(raw, "endpoint evidence")
    data = value.get("data")
    if not isinstance(data, dict) or data.get("id") != model or not isinstance(data.get("endpoints"), list):
        raise AdapterError("endpoint evidence model mismatch")
    _unique_endpoint(data, provider)
    return {"model_id": model, "provider_tag": provider, "source_url": url,
            "observed_at": observed_at, "response_sha256": hashlib.sha256(raw).hexdigest(),
            "response_json": response_json}


def _reasoning_bound(endpoint, identity):
    """Selected-route protocol evidence, distinct from effort capability.

    Azure also hosts non-OpenAI models. The declared canonical model author and
    endpoint name/tag must all match the documented native OpenAI protocol.
    A max_completion_tokens parameter name alone is not sufficient evidence.
    """
    if identity is None or identity["canonical_id"].split("/", 1)[0] != "openai":
        return None
    if "max_completion_tokens" not in endpoint.get("supported_parameters", []):
        return None
    tag, name = endpoint.get("tag"), endpoint.get("provider_name")
    if name == "OpenAI" and (tag == "openai" or isinstance(tag, str) and tag.startswith("openai/")):
        contract = "openai-chat-max-completion-v1"
    elif name == "Azure" and (tag == "azure" or isinstance(tag, str) and tag.startswith("azure/")):
        contract = "azure-openai-max-completion-v1"
    else:
        return None
    return {"schema_version": 1, "contract": contract, "source_url": _REASONING_BOUND_SOURCES[contract],
            "provider_tag": tag, "provider_name": name, "model_author": "openai",
            "parameter": "max_completion_tokens", "includes_reasoning": True}


def _validate_price_schedule(pricing):
    if not isinstance(pricing, dict) or not {"prompt", "completion"} <= set(pricing):
        raise AdapterError("missing endpoint token pricing")
    for key, value in pricing.items():
        if key == "discount":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise AdapterError("invalid endpoint pricing discount")
        elif key == "overrides":
            if not isinstance(value, list):
                raise AdapterError("pricing overrides must be a list")
            for override in value:
                if (not isinstance(override, dict) or "min_prompt_tokens" not in override or
                        type(override["min_prompt_tokens"]) is not int or override["min_prompt_tokens"] < 0 or
                        set(override) - _TOKEN_PRICE_KEYS - {"min_prompt_tokens"}):
                    raise AdapterError("unsupported pricing override axis/component")
                for price_key in set(override) - {"min_prompt_tokens"}:
                    _decimal(override[price_key], f"pricing.overrides.{price_key}")
        else:
            _decimal(value, f"pricing.{key}")


def _pricing_bound(endpoint, identity, prompt_limit):
    """Conservative whole-request rates from a fully retained native schedule."""
    protocol = _reasoning_bound(endpoint, identity)
    if protocol is None or not {"tools", "tool_choice"} <= set(endpoint["supported_parameters"]):
        return None
    prices = endpoint["pricing"]
    _validate_price_schedule(prices)
    allowed = _TOKEN_PRICE_KEYS | _ZERO_PRICE_KEYS | {"request", "web_search", "discount", "overrides"}
    if set(prices) - allowed:
        raise AdapterError("unknown native pricing component")
    if _decimal(prices.get("request", "0"), "pricing.request") != 0:
        raise AdapterError("request fee exceeds enforced zero max_price")
    for key in _ZERO_PRICE_KEYS & set(prices):
        if _decimal(prices[key], f"pricing.{key}") != 0:
            raise AdapterError(f"unbounded price component: {key}")
    input_keys = _TOKEN_PRICE_KEYS - {"completion"}
    input_rates = [_decimal(prices[key], f"pricing.{key}") for key in input_keys & set(prices)]
    completion_rates = [_decimal(prices["completion"], "pricing.completion")]
    reachable = []
    for index, override in enumerate(prices.get("overrides", [])):
        # The published condition is strictly greater; equality cannot activate it.
        if override["min_prompt_tokens"] < prompt_limit:
            reachable.append(index)
            input_rates.extend(_decimal(override[key], f"pricing.overrides.{key}") for key in input_keys & set(override))
            if "completion" in override:
                completion_rates.append(_decimal(override["completion"], "pricing.overrides.completion"))
    search_source = ("https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search"
                     if protocol["contract"].startswith("azure-") else
                     "https://developers.openai.com/api/docs/guides/tools-web-search")
    return {"schema_version": 1, "contract": "native-openai-text-pricing-v1",
            "provider_protocol": protocol["contract"], "provider_tag": endpoint["tag"],
            "provider_name": endpoint["provider_name"], "pricing_schedule": json.loads(_json_bytes(prices)),
            "reachable_override_indices": reachable,
            "input_rate_ceiling": str(max(input_rates)), "completion_rate_ceiling": str(max(completion_rates)),
            "search_policy": json.loads(_json_bytes(_NO_SEARCH_POLICY)),
            "sources": {"pricing": "https://openrouter.ai/docs/guides/overview/models",
                        "cache": "https://openrouter.ai/docs/guides/best-practices/prompt-caching",
                        "native_search": search_source,
                        "plugin_disable": "https://openrouter.ai/docs/guides/features/plugins/overview"}}


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
    _validate_price_schedule(raw_pricing)
    supported = endpoint.get("supported_parameters")
    if not isinstance(supported, list):
        raise AdapterError("endpoint parameters unavailable")
    return {"model_id": model, "provider_tag": provider, "observed_at": observed_at,
            "source_url": url, "max_prompt_tokens": prompt_limit,
            "max_completion_tokens": completion_limit,
            "supported_parameters": supported, "pricing": pricing}


def fetch_endpoint_snapshot(model, provider, *, catalog_fetch=None, model_fetch=None, now=None):
    """Capture endpoint and alias identity from public catalog APIs."""
    url = _catalog_url(model)
    identity_url = _model_url(model)
    _provider_slug(provider)
    fetch = catalog_fetch or _default_catalog_fetch
    fetch_model = model_fetch or _default_catalog_fetch
    clock = now or (lambda: datetime.now(timezone.utc))
    try:
        raw_endpoint = fetch(url)
        value, _ = _public_json(raw_endpoint, "endpoint catalog")
        data = value["data"]
        if data["id"] != model or not isinstance(data["endpoints"], list):
            raise AdapterError("catalog model mismatch")
        endpoint = _unique_endpoint(data, provider)
        observed_at = clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        snapshot = _snapshot_from_endpoint(model, provider, url, endpoint, observed_at)
        snapshot["model_identity"] = _model_identity(fetch_model(identity_url), model,
                                                      identity_url, observed_at)
        snapshot["endpoint_evidence"] = _endpoint_evidence(raw_endpoint, model, provider, url, observed_at)
        bound = _reasoning_bound(endpoint, snapshot["model_identity"])
        if bound is not None:
            snapshot["reasoning_bound"] = bound
        price_bound = _pricing_bound(endpoint, snapshot["model_identity"], snapshot["max_prompt_tokens"])
        if price_bound is not None:
            snapshot["pricing_bound"] = price_bound
        return snapshot
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

    def __init__(self, config, *, transport=None, catalog_fetch=None, model_fetch=None,
                 generation_fetch=None, now=None):
        if not isinstance(config, dict) or not {"id", "model"} <= set(config) or set(config) - {"id", "model", "settings"}:
            raise AdapterError("invalid experiment configuration")
        self.config = config
        self.model = config["model"]
        settings = config.get("settings", {})
        if not isinstance(settings, dict) or set(settings) - {"adapter", "provider", "max_output_tokens", "temperature", "top_p", "effort", "reasoning", "endpoint_snapshot", "account_policy_assertion"}:
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
        self._validate_reasoning_controls(settings)
        self._account_policy = None
        if "account_policy_assertion" in settings:
            policy = settings["account_policy_assertion"]
            required_policy = {"source", "verified_at", "web_disabled_or_overridable", "response_healing_disabled_or_overridable"}
            if (not isinstance(policy, dict) or set(policy) != required_policy or
                    not isinstance(policy["source"], str) or not policy["source"].strip() or len(policy["source"]) > 1000 or
                    policy["web_disabled_or_overridable"] is not True or
                    policy["response_healing_disabled_or_overridable"] is not True):
                raise AdapterError("account policy requires explicit supported operator assertions and source")
            verified_at = _date(policy["verified_at"])
            if verified_at.tzinfo is None or verified_at.utcoffset() != timedelta(0):
                raise AdapterError("account policy verified_at must be an aware UTC timestamp")
            self._account_policy = {"schema_version": 1, "status": "operator_declared",
                "assertion": json.loads(_json_bytes(policy)), "assertion_sha256": hashlib.sha256(_json_bytes(policy)).hexdigest(),
                "expires_at": (verified_at + ACCOUNT_POLICY_MAX_AGE).isoformat().replace("+00:00", "Z"),
                "bound_condition": "provider_honors_operator_declared_account_policy"}
        self.transport = transport or _default_transport
        self.catalog_fetch = catalog_fetch or _default_catalog_fetch
        self.model_fetch = model_fetch or _default_catalog_fetch
        self.generation_fetch = generation_fetch or _default_generation_fetch
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _validate_snapshot(self, snapshot):
        required = {"model_id", "provider_tag", "observed_at", "source_url", "max_prompt_tokens", "max_completion_tokens", "supported_parameters", "pricing"}
        optional = {"model_identity", "endpoint_evidence", "reasoning_bound", "pricing_bound"}
        if not isinstance(snapshot, dict) or not required <= set(snapshot) or set(snapshot) - required - optional:
            raise AdapterError("endpoint snapshot has missing or unknown fields")
        if snapshot["model_id"] != self.model or snapshot["provider_tag"] != self.provider:
            raise AdapterError("endpoint model/provider mismatch")
        expected_url = _catalog_url(self.model)
        if snapshot["source_url"] != expected_url:
            raise AdapterError("endpoint source URL mismatch")
        _date(snapshot["observed_at"])
        if "model_identity" in snapshot:
            identity = snapshot["model_identity"]
            identity_keys = {"requested_id", "canonical_id", "source_url", "observed_at",
                             "response_sha256", "response_json"}
            if not isinstance(identity, dict) or set(identity) != identity_keys:
                raise AdapterError("model identity binding has missing or unknown fields")
            if identity["requested_id"] != self.model or identity["source_url"] != _model_url(self.model):
                raise AdapterError("model identity binding requested ID or source mismatch")
            _model_url(identity["canonical_id"])
            _date(identity["observed_at"])
            sha = identity["response_sha256"]
            if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise AdapterError("invalid model identity response hash")
            if not isinstance(identity["response_json"], str):
                raise AdapterError("model identity raw response must be UTF-8 text")
            try:
                raw_identity = identity["response_json"].encode("utf-8")
            except UnicodeEncodeError as exc:
                raise AdapterError("model identity raw response is not UTF-8") from exc
            original = _model_identity(raw_identity, self.model,
                                       identity["source_url"], identity["observed_at"])
            if (original["canonical_id"] != identity["canonical_id"] or
                    original["response_sha256"] != sha):
                raise AdapterError("model identity raw response disagrees with frozen binding")
        if "endpoint_evidence" in snapshot:
            evidence = snapshot["endpoint_evidence"]
            evidence_keys = {"model_id", "provider_tag", "source_url", "observed_at", "response_sha256", "response_json"}
            if not isinstance(evidence, dict) or set(evidence) != evidence_keys or not isinstance(evidence["response_json"], str):
                raise AdapterError("endpoint evidence has missing or unknown fields")
            _date(evidence["observed_at"])
            try:
                raw_endpoint = evidence["response_json"].encode("utf-8")
            except UnicodeEncodeError as exc:
                raise AdapterError("endpoint evidence is not UTF-8") from exc
            captured = _endpoint_evidence(raw_endpoint, self.model, self.provider, expected_url, evidence["observed_at"])
            if evidence != captured or evidence["observed_at"] != snapshot["observed_at"]:
                raise AdapterError("endpoint evidence disagrees with frozen binding")
            selected = _unique_endpoint(json.loads(raw_endpoint)["data"], self.provider)
            projected = _snapshot_from_endpoint(self.model, self.provider, expected_url, selected, snapshot["observed_at"])
            if any(projected[key] != snapshot[key] for key in required):
                raise AdapterError("endpoint evidence disagrees with frozen capability/pricing")
            expected_bound = _reasoning_bound(selected, snapshot.get("model_identity"))
            if "reasoning_bound" in snapshot:
                declared_bound = snapshot["reasoning_bound"]
                if (expected_bound is None or not isinstance(declared_bound, dict) or
                        type(declared_bound.get("schema_version")) is not int or declared_bound != expected_bound):
                    raise AdapterError("reasoning bound disagrees with captured provider protocol")
            if "pricing_bound" in snapshot:
                expected_price_bound = _pricing_bound(selected, snapshot.get("model_identity"), snapshot["max_prompt_tokens"])
                declared_price_bound = snapshot["pricing_bound"]
                if (expected_price_bound is None or not isinstance(declared_price_bound, dict) or
                        type(declared_price_bound.get("schema_version")) is not int or declared_price_bound != expected_price_bound):
                    raise AdapterError("pricing bound or search policy disagrees with captured evidence")
        elif "reasoning_bound" in snapshot or "pricing_bound" in snapshot:
            raise AdapterError("reasoning/pricing bound requires captured endpoint evidence")
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
        _validate_price_schedule(prices)
        if "pricing_bound" in snapshot:
            return  # Full selected-protocol schedule and non-token fees were validated above.
        prompt_price = _decimal(prices["prompt"], "pricing.prompt")
        for key, value in prices.items():
            if key == "overrides":
                raise AdapterError("pricing overrides require a documented native pricing bound")
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

    @property
    def requested_controls(self):
        """Canonical requested request controls, suitable for a frozen manifest."""
        return json.loads(_json_bytes(self.controls))

    @property
    def account_policy_prerequisite(self):
        """Operator evidence, never independent verification of account settings."""
        return json.loads(_json_bytes(self._account_policy)) if self._account_policy else {
            "schema_version": 1, "status": "unavailable", "bound_condition": "account_policy_must_be_verified_before_admission"}

    def _verify_account_policy(self):
        if self._account_policy is None:
            raise AdapterError("live preflight requires a fresh operator account policy assertion; effective plugin policy is unknown")
        verified_at = _date(self._account_policy["assertion"]["verified_at"])
        current = self.now()
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise AdapterError("live preflight requires an aware current time")
        age = current.astimezone(timezone.utc) - verified_at
        if age < timedelta(0) or age >= ACCOUNT_POLICY_MAX_AGE:
            raise AdapterError("operator account policy assertion is expired or future-dated")
        return {"account_policy_assertion_sha256": self._account_policy["assertion_sha256"],
                "account_policy_status": "operator_declared_current",
                "account_policy_source": self._account_policy["assertion"]["source"],
                "bound_condition": self._account_policy["bound_condition"]}

    def _model_reasoning(self, identity):
        if identity is None:
            return None
        data = json.loads(identity["response_json"])["data"]
        if "reasoning" not in data:
            return None
        return _reasoning_metadata(data["reasoning"])

    def _validate_reasoning_controls(self, settings):
        has_reasoning = "reasoning" in settings or "effort" in settings
        controls = settings.get("reasoning", {})
        if "reasoning" in settings and (not isinstance(controls, dict) or not controls):
            raise AdapterError("reasoning must be a nonempty object")
        if set(controls) - {"effort", "max_tokens", "enabled", "exclude"}:
            raise AdapterError("unsupported reasoning setting")
        controls = dict(controls)
        if "effort" in settings:
            if "effort" in controls:
                raise AdapterError("duplicate reasoning effort declaration")
            controls["effort"] = settings["effort"]
        identity = self.snapshot.get("model_identity")
        if has_reasoning and identity is None:
            raise AdapterError("reasoning controls require frozen model capability evidence")
        capabilities = self._model_reasoning(identity)
        self.reasoning_capabilities = capabilities
        if has_reasoning and capabilities is None:
            raise AdapterError("model does not advertise reasoning capability")
        if has_reasoning and "reasoning" not in self.snapshot["supported_parameters"]:
            raise AdapterError("endpoint does not support reasoning")
        for key in ("enabled", "exclude"):
            if key in controls and type(controls[key]) is not bool:
                raise AdapterError(f"reasoning {key} must be boolean")
        if "effort" in controls and "max_tokens" in controls:
            raise AdapterError("reasoning cannot declare both effort and token budget")
        effort = controls.get("effort")
        if "effort" in controls:
            if not isinstance(effort, str) or effort not in REASONING_EFFORTS:
                raise AdapterError("invalid reasoning effort")
            if "supported_efforts" not in capabilities:
                raise AdapterError("model does not advertise effort selection")
            supported = capabilities["supported_efforts"]
            if supported is not None and effort not in supported:
                raise AdapterError("model does not support the exact requested reasoning effort")
        if "max_tokens" in controls:
            budget = _positive(controls["max_tokens"], "reasoning token budget")
            if not capabilities.get("supports_max_tokens", False):
                raise AdapterError("model does not advertise reasoning token budget support")
            if budget >= self.max_output_tokens:
                raise AdapterError("reasoning token budget must be below total output limit")
        disabled = controls.get("enabled") is False or effort == "none"
        if ((controls.get("enabled") is False and (effort not in (None, "none") or "max_tokens" in controls)) or
                (controls.get("enabled") is True and effort == "none")):
            raise AdapterError("contradictory reasoning enable/effort/budget settings")
        if disabled and capabilities is not None and capabilities.get("mandatory", False):
            raise AdapterError("model reasoning is mandatory and cannot be disabled")
        if disabled:
            active = False
        elif controls.get("enabled") is True or effort is not None or "max_tokens" in controls:
            active = True
        elif capabilities is None:
            active = False  # Unmodified legacy contract; no reasoning claim is added.
        elif capabilities.get("mandatory", False):
            active = True
        elif "default_enabled" in capabilities:
            active = capabilities["default_enabled"]
        elif "default_effort" in capabilities:
            active = capabilities["default_effort"] != "none"
        else:
            active = True  # Unknown default is not evidence of a disabled billable control.
        self.reasoning_active = active
        self._reasoning_bound_missing = active and self.snapshot.get("reasoning_bound") is None
        # Old snapshots can retain active model-default metadata without the
        # newer endpoint protocol binding. Keep their saved results readable;
        # explicit controls and newly captured snapshots still validate here.
        if self._reasoning_bound_missing and (has_reasoning or "endpoint_evidence" in self.snapshot):
            raise AdapterError("enabled/default reasoning requires a documented combined completion token bound for this route")
        if has_reasoning:
            self.controls["reasoning"] = controls

    def _verify_live_reasoning(self):
        # Captured non-reasoning models omit reasoning metadata; an entirely
        # missing model identity cannot establish that same capability state.
        if self.snapshot.get("model_identity") is None:
            raise AdapterError("live execution requires frozen model identity and reasoning capability evidence")
        if self._reasoning_bound_missing or (self.reasoning_active and self.snapshot.get("reasoning_bound") is None):
            raise AdapterError("enabled/default reasoning requires a documented combined completion token bound for this route")

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
        price_bound = self.snapshot.get("pricing_bound")
        prompt_price = _decimal(price_bound["input_rate_ceiling"] if price_bound else prices["prompt"], "pricing.prompt")
        completion_price = _decimal(price_bound["completion_rate_ceiling"] if price_bound else prices["completion"], "pricing.completion")
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
        # Request plugin overrides; the separate operator prerequisite covers account policy.
        body["plugins"] = json.loads(_json_bytes(_NO_SEARCH_POLICY["plugins"]))
        if price_bound:
            body.update(json.loads(_json_bytes(price_bound["search_policy"])))
        snapshot_hash = hashlib.sha256(_json_bytes(self.snapshot)).hexdigest()
        policy_hash = self._account_policy["assertion_sha256"] if self._account_policy else "unverified"
        return PreparedRequest(_json_bytes(body), reserve, f"openrouter:endpoint:{snapshot_hash}:account-policy:{policy_hash}",
                               f"openrouter:{self.model}:{self.provider}", request["request_id"], ids)

    def verify_live_snapshot(self):
        """Re-read public endpoint catalog immediately before paid admission."""
        self._verify_live_reasoning()
        account_policy = self._verify_account_policy()
        try:
            raw = self.catalog_fetch(self.snapshot["source_url"])
            value, _ = _public_json(raw, "endpoint catalog")
            data = value["data"]
            if data["id"] != self.model or not isinstance(data["endpoints"], list):
                raise AdapterError("catalog model mismatch")
            selected = _unique_endpoint(data, self.provider)
            endpoint = _snapshot_from_endpoint(self.model, self.provider, self.snapshot["source_url"],
                                               selected, self.snapshot["observed_at"])
            for name in ("max_prompt_tokens", "max_completion_tokens", "supported_parameters", "pricing"):
                if endpoint[name] != self.snapshot[name]:
                    raise AdapterError(f"endpoint {name} drifted")
            result = {"catalog_sha256": hashlib.sha256(raw).hexdigest(),
                      "checked_at": self.now().isoformat(), "source_url": self.snapshot["source_url"], **account_policy}
            if "model_identity" in self.snapshot:
                frozen = self.snapshot["model_identity"]
                identity_raw = self.model_fetch(frozen["source_url"])
                current = _model_identity(identity_raw, self.model, frozen["source_url"],
                                          frozen["observed_at"])
                if current["canonical_id"] != frozen["canonical_id"]:
                    raise AdapterError("canonical model identity drifted")
                if self._model_reasoning(current) != self.reasoning_capabilities:
                    raise AdapterError("model reasoning capability drifted")
                if "reasoning_bound" in self.snapshot and _reasoning_bound(selected, current) != self.snapshot["reasoning_bound"]:
                    raise AdapterError("reasoning combined-budget provider protocol drifted")
                if "pricing_bound" in self.snapshot and _pricing_bound(selected, current, self.snapshot["max_prompt_tokens"]) != self.snapshot["pricing_bound"]:
                    raise AdapterError("pricing bound/provider/search policy drifted")
                result["identity_response_sha256"] = current["response_sha256"]
                result["identity_source_url"] = frozen["source_url"]
            return result
        except (OSError, TimeoutError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AdapterError("catalog could not be verified") from exc

    def dispatch(self, prepared, api_key):
        if not isinstance(prepared, PreparedRequest) or not isinstance(api_key, str) or not api_key:
            raise AdapterError("prepared request and API key required")
        if not prepared.route == f"openrouter:{self.model}:{self.provider}":
            raise AdapterError("prepared route mismatch")
        self._verify_live_reasoning()
        self._verify_account_policy()
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
        accepted_models = {self.model}
        identity = self.snapshot.get("model_identity")
        if identity is not None:
            accepted_models.add(identity["canonical_id"])
        if (not isinstance(data, dict) or data.get("id") != expected_response_id or
                expected_model != self.model or data.get("model") not in accepted_models):
            raise AdapterError("generation identity mismatch")
        provider_name = data.get("provider_name")
        if not isinstance(provider_name, str) or not provider_name:
            raise AdapterError("generation provider identity unavailable")
        cost = data.get("total_cost")
        observed_cost = None
        if cost is not None:
            observed_cost = _microusd(_decimal(str(cost), "generation.total_cost"))
        return {"provider_name": provider_name, "returned_model": data["model"],
                "observed_cost_microusd": observed_cost,
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
