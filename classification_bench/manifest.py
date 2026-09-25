"""Strict, byte-bound execution manifests for the offline simulator."""

import hashlib
import json


class ManifestError(ValueError):
    pass


def canonical_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestError("manifest data must be finite JSON") from exc


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _object(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ManifestError(f"{where} has missing or unknown fields")


def _hash(value, where):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ManifestError(f"{where} must be lowercase SHA-256")


def render_request(plan, request, config, prompt, *, mode):
    """Render exactly the bytes the isolated fake worker will receive."""
    if mode not in ("first_label", "invalid", "missing"):
        raise ManifestError("unsupported synthetic response mode")
    if config["model"] != "synthetic-only" or config.get("settings", {}) != {}:
        raise ManifestError("fake worker requires model synthetic-only and empty settings")
    message = canonical_bytes({"items": request["items"], "fields": plan["task"]["fields"]}).decode("utf-8")
    body = {
        "schema_version": 1,
        "request_id": request["request_id"],
        "messages": [{"role": "system", "content": prompt["text"]},
                     {"role": "user", "content": message}],
        "controls": {"model": config["model"], "settings": config.get("settings", {}),
                     "synthetic_response_mode": mode},
    }
    return canonical_bytes(body)


def build_manifest(plan, request, config, prompt, request_bytes, *, config_digest,
                   adapter_digest, parser_digest, scope, ordinal):
    body = json.loads(request_bytes)
    record = {
        "schema_version": 1, "request_id": request["request_id"],
        "plan_digest": digest(canonical_bytes(plan)), "run_config_digest": config_digest,
        "request_sha256": digest(request_bytes), "messages": body["messages"],
        "resolved_controls": body["controls"],
        "adapter_sha256": adapter_digest, "parser_sha256": parser_digest,
        "retry_policy": "none", "cache_policy": "off", "seed_policy": "none",
        "schedule": {"ordinal": ordinal, "repeat": request["repeat"],
                     "batch_index": request["batch_index"]},
        "budget_scope": scope,
    }
    encoded = canonical_bytes(record)
    validate_manifest(encoded, request_bytes, plan, request, config, prompt, config_digest=config_digest,
                      adapter_digest=adapter_digest, parser_digest=parser_digest,
                      scope=scope, ordinal=ordinal)
    return encoded


def validate_manifest(manifest_bytes, request_bytes, plan, request, config, prompt, *, config_digest,
                      adapter_digest, parser_digest, scope, ordinal):
    """Reject malformed, noncanonical, or drifting request/manifest evidence."""
    try:
        manifest = json.loads(manifest_bytes)
        body = json.loads(request_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest and request must be UTF-8 JSON") from exc
    _object(manifest, {"schema_version", "request_id", "plan_digest", "run_config_digest",
                       "request_sha256", "messages", "resolved_controls", "adapter_sha256",
                       "parser_sha256", "retry_policy", "cache_policy", "seed_policy",
                       "schedule", "budget_scope"}, "execution manifest")
    _object(body, {"schema_version", "request_id", "messages", "controls"}, "request")
    if canonical_bytes(manifest) != manifest_bytes or canonical_bytes(body) != request_bytes:
        raise ManifestError("manifest and request bytes must be canonical")
    for field in ("plan_digest", "run_config_digest", "request_sha256", "adapter_sha256", "parser_sha256"):
        _hash(manifest[field], field)
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or
            type(body["schema_version"]) is not int or body["schema_version"] != 1) or (
            manifest["request_id"] != request["request_id"] or body["request_id"] != request["request_id"]):
        raise ManifestError("request identity or schema version mismatch")
    expected_request = render_request(plan, request, config, prompt,
                                      mode=body["controls"].get("synthetic_response_mode")
                                      if isinstance(body["controls"], dict) else None)
    if request_bytes != expected_request:
        raise ManifestError("request bytes do not match the selected plan and rendering")
    if (manifest["plan_digest"], manifest["run_config_digest"], manifest["request_sha256"],
            manifest["adapter_sha256"], manifest["parser_sha256"], manifest["budget_scope"]) != (
            digest(canonical_bytes(plan)), config_digest, digest(request_bytes),
            adapter_digest, parser_digest, scope):
        raise ManifestError("execution evidence digest or scope mismatch")
    if manifest["messages"] != body["messages"] or manifest["resolved_controls"] != body["controls"]:
        raise ManifestError("manifest and request bytes disagree")
    if manifest["retry_policy"] != "none" or manifest["cache_policy"] != "off" or manifest["seed_policy"] != "none":
        raise ManifestError("unsupported policy")
    _object(manifest["schedule"], {"ordinal", "repeat", "batch_index"}, "schedule")
    if manifest["schedule"] != {"ordinal": ordinal, "repeat": request["repeat"],
                                 "batch_index": request["batch_index"]}:
        raise ManifestError("schedule mismatch")
    messages = body["messages"]
    if (not isinstance(messages, list) or len(messages) != 2 or
            [item.get("role") for item in messages if isinstance(item, dict)] != ["system", "user"] or
            any(not isinstance(item, dict) or set(item) != {"role", "content"} or
                not isinstance(item["content"], str) for item in messages)):
        raise ManifestError("invalid rendered message roles or content")
    _object(body["controls"], {"model", "settings", "synthetic_response_mode"}, "resolved controls")
    if (not isinstance(body["controls"]["model"], str) or not body["controls"]["model"] or
            not isinstance(body["controls"]["settings"], dict) or
            body["controls"]["synthetic_response_mode"] not in ("first_label", "invalid", "missing")):
        raise ManifestError("invalid synthetic controls")
    if type(manifest["schedule"]["ordinal"]) is not int or ordinal < 1:
        raise ManifestError("invalid schedule ordinal")
    return manifest
