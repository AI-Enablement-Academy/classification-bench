"""Declarative matrix execution over immutable requests and one shared ledger.

This module has no reference-label input. Provider dispatch is an explicit,
single-attempt operation after a durable admission record.
"""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import asdict, replace
import json
import os
import fcntl
from pathlib import Path
import stat

from .adapters import (AdapterError, OpenRouterAdapter, ParsedResponse, PreparedRequest,
                       TransportResult)
from .budget import BudgetError, BudgetLedger
from .coordinator import CoordinatorError
from .core import build_plan
from .evidence import ArtifactRef, put_artifact, read_artifact
from .manifest import canonical_bytes, digest
from .verified_execution import VerifiedExecution


class BenchmarkError(ValueError):
    pass


_CONFIG_KEYS = {"schema_version", "task", "experiment", "inputs", "database",
                "artifacts", "scope", "cap", "currency", "scale",
                "max_concurrency", "provider_limits", "authorization_file",
                "on_budget_exhausted"}
_AUTH_KEYS = {"schema_version", "run_sha256", "plan_sha256", "request_count",
              "scope", "cap"}
_AMEND_KEYS = {"schema_version", "run_sha256", "scope", "amendment_id",
               "expected_cap", "new_cap", "authorization_source"}


@contextmanager
def _runner_lock(database):
    path = Path(str(database) + ".runner.lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise BenchmarkError("runner lock must be a private regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BenchmarkError("already_running: another runner owns this database") from exc
        yield
    finally:
        os.close(descriptor)


def _load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BenchmarkError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    data = Path(path).read_bytes()
    try:
        return json.loads(data, object_pairs_hook=unique), data
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"invalid UTF-8 JSON: {path}") from exc


class SyntheticAdapter:
    """Deterministic offline matrix fixture. It does not assert OS isolation."""

    offline = True

    def __init__(self, config):
        settings = config.get("settings", {})
        if (config["model"] != "synthetic-only" or not isinstance(settings, dict) or
                set(settings) != {"adapter", "response_mode"} or
                settings["adapter"] != "synthetic" or
                settings["response_mode"] not in ("first_label", "invalid", "missing")):
            raise BenchmarkError("synthetic configuration has unsupported controls")
        self.config = config
        self.mode = settings["response_mode"]
        self.provider = "synthetic"

    def prepare(self, plan, request, prompt):
        body = canonical_bytes({"schema_version": 1, "request_id": request["request_id"],
                                "messages": [{"role": "system", "content": prompt["text"]},
                                             {"role": "user", "content": canonical_bytes({
                                                 "items": request["items"],
                                                 "fields": plan["task"]["fields"]}).decode("utf-8")}],
                                "controls": {"model": "synthetic-only", "response_mode": self.mode}})
        return PreparedRequest(body, 1, "synthetic:declared-zero-charge",
                               "synthetic:offline", request["request_id"],
                               tuple(item["id"] for item in request["items"]))

    def dispatch(self, prepared, api_key=None):
        body = json.loads(prepared.body)
        payload = json.loads(body["messages"][1]["content"])
        predictions = []
        if self.mode != "missing":
            for item in payload["items"]:
                values = {field["name"]: field["labels"][0] for field in payload["fields"]}
                if self.mode == "invalid":
                    values[payload["fields"][0]["name"]] = "__invalid_synthetic_label__"
                predictions.append({"id": item["id"], "prediction": values})
        raw = canonical_bytes({"schema_version": 1, "request_id": prepared.request_id,
                               "predictions": predictions})
        return TransportResult(raw, 200, 0)

    def parse(self, result, *, expected_request_id, expected_ids, expected_model):
        try:
            value = json.loads(result.raw_bytes)
            if (result.http_status != 200 or not isinstance(value, dict) or
                    set(value) != {"schema_version", "request_id", "predictions"} or
                    value["schema_version"] != 1 or value["request_id"] != expected_request_id or
                    not isinstance(value["predictions"], list)):
                raise ValueError("response schema or request identity mismatch")
            ids = [p.get("id") for p in value["predictions"] if isinstance(p, dict)]
            if (len(ids) != len(value["predictions"]) or len(set(ids)) != len(ids) or
                    not set(ids) <= set(expected_ids) or
                    any(set(p) != {"id", "prediction"} or not isinstance(p["prediction"], dict)
                        for p in value["predictions"])):
                raise ValueError("invalid prediction positions")
            return ParsedResponse("valid", tuple(value["predictions"]), None, 0,
                                  "synthetic-only", "synthetic", None, "stop")
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            return ParsedResponse("invalid", (), None, 0, "synthetic-only",
                                  "synthetic", None, None, str(exc))


class UnsupportedAdapter:
    """Keep declared but unavailable methods visible without dispatching them."""

    offline = True
    provider = "unsupported"

    def __init__(self, config):
        self.config = config
        self.reason = f"unsupported adapter: {config.get('settings', {}).get('adapter', '<unspecified>')}"

    def prepare(self, plan, request, prompt):
        body = canonical_bytes({"schema_version": 1, "request_id": request["request_id"],
                                "task": plan["task"], "config": self.config,
                                "prompt": prompt, "items": request["items"],
                                "blocked_reason": self.reason})
        return PreparedRequest(body, 0, self.reason, self.reason,
                               request["request_id"], tuple(item["id"] for item in request["items"]))


def _adapter(config, supplied=None):
    if supplied is not None:
        return supplied
    mode = config.get("settings", {}).get("adapter")
    if mode == "synthetic":
        return SyntheticAdapter(config)
    if mode == "openrouter":
        return OpenRouterAdapter(config)
    return UnsupportedAdapter(config)


def _load(config_path, adapter=None):
    config, config_bytes = _load_json(config_path)
    if not isinstance(config, dict) or set(config) != _CONFIG_KEYS or config.get("schema_version") != 1:
        raise BenchmarkError("benchmark config must use exact v1 fields")
    for key in ("task", "experiment", "inputs", "database", "artifacts"):
        if not isinstance(config[key], str) or not Path(config[key]).is_absolute():
            raise BenchmarkError(f"{key} must be an absolute path")
    if config["authorization_file"] is not None and (
            not isinstance(config["authorization_file"], str) or
            not Path(config["authorization_file"]).is_absolute()):
        raise BenchmarkError("authorization_file must be an absolute path or null")
    if (not isinstance(config["scope"], str) or not config["scope"] or
            type(config["cap"]) is not int or config["cap"] < 1 or
            type(config["scale"]) is not int or config["scale"] < 1 or
            type(config["max_concurrency"]) is not int or config["max_concurrency"] < 1 or
            not isinstance(config["provider_limits"], dict) or
            not config["provider_limits"] or
            any(not isinstance(k, str) or not k or type(v) is not int or v < 1
                for k, v in config["provider_limits"].items())):
        raise BenchmarkError("invalid scope, cap, scale, concurrency, or provider limits")
    if config["on_budget_exhausted"] not in ("pause", "stop"):
        raise BenchmarkError("on_budget_exhausted must be pause or stop")
    task, task_bytes = _load_json(config["task"])
    experiment, experiment_bytes = _load_json(config["experiment"])
    inputs, input_bytes = _load_json(config["inputs"])
    plan = build_plan(task, experiment, inputs)
    adapters = {item["id"]: _adapter(item, adapter) for item in experiment["configs"]}
    offline = all(getattr(item, "offline", False) for item in adapters.values())
    if offline:
        if (config["authorization_file"] is not None or config["currency"] != "SYN" or
                config["scale"] != 1 or not config["scope"].startswith("synthetic:")):
            raise BenchmarkError("synthetic runs require a synthetic scope and currency")
    elif (config["currency"] != "USD" or config["scale"] != 1_000_000 or
          config["authorization_file"] is None):
        raise BenchmarkError("live runs require USD micro-units and an authorization file")
    binding = digest(canonical_bytes({"config": config, "config_bytes_sha256": digest(config_bytes),
                                      "task_sha256": digest(task_bytes),
                                      "experiment_sha256": digest(experiment_bytes),
                                      "inputs_sha256": digest(input_bytes)}))
    by_config = {item["id"]: item for item in experiment["configs"]}
    by_prompt = {item["id"]: item for item in experiment["prompts"]}
    materials = []
    for ordinal, request in enumerate(plan["requests"], 1):
        cfg = by_config[request["config_id"]]
        current_adapter = adapters[cfg["id"]]
        prepared = current_adapter.prepare(plan, request, by_prompt[request["prompt_id"]])
        if not isinstance(prepared.body, bytes) or prepared.request_id != request["request_id"]:
            raise BenchmarkError("adapter prepared an unbound request")
        if (type(prepared.reserve_microusd) is not int or prepared.reserve_microusd <
                (0 if isinstance(current_adapter, UnsupportedAdapter) else 1)):
            raise BenchmarkError("adapter supplied an invalid per-request bound")
        manifest = canonical_bytes({"schema_version": 1, "request_id": request["request_id"],
                                    "plan_sha256": digest(canonical_bytes(plan)),
                                    "run_sha256": binding, "request_sha256": digest(prepared.body),
                                    "adapter": type(current_adapter).__name__,
                                    "adapter_source_sha256": digest(Path(__import__(type(current_adapter).__module__,
                                                                                fromlist=['x']).__file__).read_bytes()),
                                    "resolved_controls": cfg.get("settings", {}),
                                    "route": prepared.route, "messages": json.loads(prepared.body).get("messages"),
                                    "retry_policy": "none", "cache_policy": "off",
                                    "schedule": {"ordinal": ordinal, "repeat": request["repeat"],
                                                 "batch_index": request["batch_index"]},
                                    "budget_scope": config["scope"]})
        materials.append({"request": request, "prepared": prepared, "manifest": manifest,
                          "adapter": current_adapter, "config": cfg, "scope": config["scope"],
                          "fields": plan["task"]["fields"]})
    return config, plan, binding, materials, offline


def preview(config_path, *, adapter=None):
    config, plan, binding, materials, offline = _load(config_path, adapter)
    return {"run_sha256": binding, "plan_sha256": digest(canonical_bytes(plan)),
            "request_count": len(materials), "scope": config["scope"], "cap": config["cap"],
            "currency": config["currency"], "scale": config["scale"],
            "sum_request_bounds": sum(x["prepared"].reserve_microusd for x in materials),
            "max_request_bound": max(x["prepared"].reserve_microusd for x in materials),
            "offline": offline,
            "requests": [{"request_id": x["request"]["request_id"],
                          "config_id": x["request"]["config_id"],
                          "prompt_id": x["request"]["prompt_id"],
                          "repeat": x["request"]["repeat"],
                          "batch_index": x["request"]["batch_index"],
                          "ids": [i["id"] for i in x["request"]["items"]],
                          "route": x["prepared"].route,
                          "blocked_reason": x["adapter"].reason if isinstance(x["adapter"], UnsupportedAdapter)
                          else "single request exceeds declared cap" if
                          x["prepared"].reserve_microusd > config["cap"] else None,
                          "reserve_amount": x["prepared"].reserve_microusd}
                         for x in materials]}


def _bind(verified, binding):
    with verified.execution.coordinator._transaction() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS benchmark_binding (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), run_sha256 TEXT NOT NULL)""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS benchmark_binding_no_update
            BEFORE UPDATE ON benchmark_binding BEGIN SELECT RAISE(ABORT,'immutable benchmark binding'); END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS benchmark_binding_no_delete
            BEFORE DELETE ON benchmark_binding BEGIN SELECT RAISE(ABORT,'immutable benchmark binding'); END""")
        conn.execute("""CREATE TABLE IF NOT EXISTS benchmark_observations (
            request_id TEXT PRIMARY KEY REFERENCES execution_requests(request_id),
            response_sha256 TEXT NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS benchmark_observations_no_update
            BEFORE UPDATE ON benchmark_observations BEGIN SELECT RAISE(ABORT,'immutable observation'); END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS benchmark_observations_no_delete
            BEFORE DELETE ON benchmark_observations BEGIN SELECT RAISE(ABORT,'immutable observation'); END""")
        conn.execute("""CREATE TABLE IF NOT EXISTS benchmark_transports (
            request_id TEXT PRIMARY KEY REFERENCES execution_requests(request_id),
            response_sha256 TEXT NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS benchmark_transports_no_update
            BEFORE UPDATE ON benchmark_transports BEGIN SELECT RAISE(ABORT,'immutable transport'); END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS benchmark_transports_no_delete
            BEFORE DELETE ON benchmark_transports BEGIN SELECT RAISE(ABORT,'immutable transport'); END""")
        conn.execute("""CREATE TABLE IF NOT EXISTS benchmark_run_control (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL
            CHECK(state IN ('running','paused_budget','stopped_budget')))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS benchmark_run_control_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, state TEXT NOT NULL, reason TEXT NOT NULL)""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS benchmark_run_control_events_no_update
            BEFORE UPDATE ON benchmark_run_control_events BEGIN SELECT RAISE(ABORT,'immutable action event'); END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS benchmark_run_control_events_no_delete
            BEFORE DELETE ON benchmark_run_control_events BEGIN SELECT RAISE(ABORT,'immutable action event'); END""")
        conn.execute("""CREATE TABLE IF NOT EXISTS benchmark_preflight_errors (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL REFERENCES execution_requests(request_id),
            error_type TEXT NOT NULL)""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS benchmark_preflight_errors_no_update
            BEFORE UPDATE ON benchmark_preflight_errors BEGIN SELECT RAISE(ABORT,'immutable preflight event'); END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS benchmark_preflight_errors_no_delete
            BEFORE DELETE ON benchmark_preflight_errors BEGIN SELECT RAISE(ABORT,'immutable preflight event'); END""")
        row = conn.execute("SELECT run_sha256 FROM benchmark_binding WHERE singleton=1").fetchone()
        if row is None:
            if conn.execute("SELECT COUNT(*) FROM execution_requests").fetchone()[0]:
                raise BenchmarkError("database contains unrelated execution requests")
            conn.execute("INSERT INTO benchmark_binding VALUES(1,?)", (binding,))
            conn.execute("INSERT INTO benchmark_run_control VALUES(1,'running')")
        elif row[0] != binding:
            raise BenchmarkError("benchmark configuration changed for this database")
        elif conn.execute("SELECT 1 FROM benchmark_run_control WHERE singleton=1").fetchone() is None:
            conn.execute("INSERT INTO benchmark_run_control VALUES(1,'running')")


def _control(verified):
    with verified.execution.coordinator._transaction() as conn:
        row = conn.execute("SELECT state FROM benchmark_run_control WHERE singleton=1").fetchone()
    return row["state"]


def _set_control(verified, state, reason):
    with verified.execution.coordinator._transaction() as conn:
        current = conn.execute("SELECT state FROM benchmark_run_control WHERE singleton=1").fetchone()[0]
        if current == "stopped_budget" and state != "stopped_budget":
            raise BenchmarkError("stopped run cannot be resumed")
        if current != state:
            conn.execute("UPDATE benchmark_run_control SET state=? WHERE singleton=1", (state,))
            conn.execute("INSERT INTO benchmark_run_control_events(state,reason) VALUES(?,?)",
                         (state, reason))


def _release_claim(verified, claim):
    """Return only this still-enrolled, pre-intent claim to ready."""
    with verified.execution.coordinator._transaction() as conn:
        row = verified.execution.coordinator._row(conn, claim["request_id"])
        entry = verified.execution._entry(conn, claim["request_id"])
        if row["state"] != "claimed" or row["token"] != claim["token"] or entry["state"] != "enrolled":
            return False
        conn.execute("""UPDATE requests SET state='ready',token=NULL,worker_id=NULL,lease_until=NULL
                        WHERE request_id=?""", (claim["request_id"],))
        verified.execution.coordinator._event(conn, row, "claim_released",
                                               worker_id=row["worker_id"], token=claim["token"],
                                               details="pre-intent budget admission unavailable")
    return True


def _record_preflight_error(verified, request_id, error_type):
    with verified.execution.coordinator._transaction() as conn:
        conn.execute("INSERT INTO benchmark_preflight_errors(request_id,error_type) VALUES(?,?)",
                     (request_id, error_type))


def _preflight_error(verified, request_id):
    with verified.execution.coordinator._transaction() as conn:
        row = conn.execute("""SELECT error_type FROM benchmark_preflight_errors
            WHERE request_id=? ORDER BY seq DESC LIMIT 1""", (request_id,)).fetchone()
    return row["error_type"] if row else None


def _reclaim_interrupted_preintent_claims(verified):
    """The exclusive runner lock proves no previous matrix worker remains."""
    with verified.execution.coordinator._transaction() as conn:
        rows = conn.execute("""SELECT r.* FROM requests r JOIN execution_requests x
            ON x.request_id=r.request_id WHERE r.state='claimed' AND x.state='enrolled'
            AND r.worker_id='benchmark-matrix'""").fetchall()
        for row in rows:
            conn.execute("""UPDATE requests SET state='ready',token=NULL,worker_id=NULL,lease_until=NULL
                            WHERE request_id=?""", (row["request_id"],))
            verified.execution.coordinator._event(conn, row, "claim_released",
                                                   worker_id=row["worker_id"], token=row["token"],
                                                   details="interrupted pre-intent runner reclaimed under lock")
    return len(rows)


def _auth(config, plan, binding, count):
    if config["authorization_file"] is None:
        return
    value, _ = _load_json(config["authorization_file"])
    expected = {"schema_version": 1, "run_sha256": binding,
                "plan_sha256": digest(canonical_bytes(plan)), "request_count": count,
                "scope": config["scope"], "cap": config["cap"]}
    if not isinstance(value, dict) or set(value) != _AUTH_KEYS or value != expected:
        raise BenchmarkError("authorization does not match this exact run and cap")


def _refs(verified, material):
    manifest = material["manifest"]
    body = material["prepared"].body
    request_id = material["request"]["request_id"]
    with verified.execution.coordinator._transaction() as conn:
        existing = conn.execute("SELECT 1 FROM execution_requests WHERE request_id=?", (request_id,)).fetchone()
    if existing is None:
        return verified.enqueue_bytes(request_id, material["scope"], manifest, body)
    refs = []
    for data in (manifest, body):
        sha = digest(data)
        ref = ArtifactRef(1, sha, len(data), "application/json", f"objects/{sha[:2]}/{sha}")
        if read_artifact(verified.artifact_root, ref) != data:
            raise BenchmarkError("frozen request bytes changed")
        refs.append(ref)
    state = verified.execution.get(request_id)["execution"]
    if (state["manifest_digest"], state["input_digest"]) != (refs[0].sha256, refs[1].sha256):
        raise BenchmarkError("enrolled evidence changed")
    return {"manifest_ref": refs[0], "request_ref": refs[1]}


def _save_observation(verified, request_id, response_sha, payload):
    encoded = canonical_bytes(payload)
    with verified.execution.coordinator._transaction() as conn:
        row = conn.execute("SELECT * FROM benchmark_observations WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO benchmark_observations VALUES(?,?,?,?)",
                         (request_id, response_sha, encoded.decode("utf-8"), digest(encoded)))
        elif (row["response_sha256"], row["payload"], row["payload_sha256"]) != (
                response_sha, encoded.decode("utf-8"), digest(encoded)):
            raise BenchmarkError("conflicting operation observation")


def _save_transport(verified, request_id, result):
    payload = asdict(result)
    raw_sha = digest(result.raw_bytes)
    payload["raw_bytes"] = None
    encoded = canonical_bytes(payload)
    with verified.execution.coordinator._transaction() as conn:
        row = conn.execute("SELECT * FROM benchmark_transports WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO benchmark_transports VALUES(?,?,?,?)",
                         (request_id, raw_sha, encoded.decode("utf-8"), digest(encoded)))
        elif (row["response_sha256"], row["payload"], row["payload_sha256"]) != (
                raw_sha, encoded.decode("utf-8"), digest(encoded)):
            raise BenchmarkError("conflicting transport evidence")


def _transport(verified, request_id, raw):
    with verified.execution.coordinator._transaction() as conn:
        row = conn.execute("SELECT * FROM benchmark_transports WHERE request_id=?", (request_id,)).fetchone()
    if row is None:
        return None
    if (row["response_sha256"] != digest(raw) or
            row["payload_sha256"] != digest(row["payload"].encode("utf-8"))):
        raise BenchmarkError("transport evidence does not match raw response")
    data = json.loads(row["payload"])
    return TransportResult(raw, data["http_status"], data["duration_ms"],
                           data["error"], data["redacted"], data["truncated"])


def _observation(verified, request_id):
    with verified.execution.coordinator._transaction() as conn:
        row = conn.execute("SELECT * FROM benchmark_observations WHERE request_id=?", (request_id,)).fetchone()
    if row is None:
        return None
    if digest(row["payload"].encode("utf-8")) != row["payload_sha256"]:
        raise BenchmarkError("operation observation digest mismatch")
    return json.loads(row["payload"])


def _zero_charge_evidence(observation, offline):
    if offline:
        return "synthetic:zero-fee"
    generation_sha = observation.get("generation_response_sha256")
    if generation_sha and (observation.get("generation") or {}).get("observed_cost_microusd") == 0:
        return f"openrouter:generation:{generation_sha}"
    usage = observation["parsed"].get("usage") or {}
    if usage.get("cost") is not None:
        return f"openrouter:usage:{observation['response_sha256']}"
    return None


def _validate_task_predictions(parsed, material):
    """Check categorical vocabulary without opening reference labels."""
    if parsed.status != "valid" or not parsed.predictions:
        return parsed
    allowed = {field["name"]: set(field["labels"]) for field in material["fields"]}
    seen = set()
    for item in parsed.predictions:
        if (not isinstance(item, dict) or set(item) != {"id", "prediction"} or
                type(item["id"]) is not str or
                item["id"] not in material["prepared"].expected_ids or item["id"] in seen or
                not isinstance(item["prediction"], dict) or
                set(item["prediction"]) != set(allowed) or
                any(type(value) is not str or value not in allowed[name]
                    for name, value in item["prediction"].items())):
            return replace(parsed, status="invalid",
                           reason="prediction violates task vocabulary")
        seen.add(item["id"])
    return parsed


def _execute_one(config, material, verified, claim, refs, offline, api_key, worker):
    request = material["request"]
    request_id = request["request_id"]
    adapter = material["adapter"]
    prepared = material["prepared"]
    token = claim["token"]
    if not offline:
        # Network catalog verification and isolation probe precede any grant.
        from .network_isolation import NetworkSandboxedPythonWorker
        (worker or NetworkSandboxedPythonWorker()).probe()
        current = OpenRouterAdapter(material["config"])
        catalog = current.verify_live_snapshot()
        bound_source = f"{prepared.bound_source}:catalog:{catalog['catalog_sha256']}"
    else:
        bound_source = prepared.bound_source
    verified.admit_verified(request_id, token, config["scope"], prepared.reserve_microusd,
                            refs["manifest_ref"], refs["request_ref"], bound_source=bound_source)
    try:
        if offline:
            result = adapter.dispatch(prepared)
        else:
            from .network_isolation import isolated_dispatch
            result = isolated_dispatch(adapter, prepared, api_key, worker=worker)
        if not isinstance(result, TransportResult):
            raise BenchmarkError("adapter returned invalid transport result")
        if not result.raw_bytes:
            evidence = put_artifact(verified.artifact_root,
                                    canonical_bytes({"request_id": request_id, "error": result.error,
                                                     "http_status": result.http_status,
                                                     "duration_ms": result.duration_ms}), "application/json")
            verified.record_unknown(request_id, token, evidence.sha256, "no complete response bytes")
            return
        raw_ref = put_artifact(verified.artifact_root, result.raw_bytes, "application/json")
        read_artifact(verified.artifact_root, raw_ref)
        _save_transport(verified, request_id, result)
        saved = verified.save_response(request_id, token, result.raw_bytes,
                                       "application/json", f"{prepared.route}:http:{result.http_status}")
        if saved["response_ref"] != raw_ref:
            raise BenchmarkError("published response changed between transport and receipt")
        # Original bounded response is now durable; only then parse it.
        try:
            parsed = adapter.parse(result, expected_request_id=request_id,
                                   expected_ids=prepared.expected_ids,
                                   expected_model=material["config"]["model"])
        except Exception as exc:
            parsed = ParsedResponse("invalid", (), None, None, None, None, None, None,
                                    f"parser error: {type(exc).__name__}")
        parsed = _validate_task_predictions(parsed, material)
        generation = None
        generation_ref = None
        provider_identity_status = "synthetic" if offline else "unverified"
        if not offline and parsed.response_id:
            try:
                from .network_isolation import isolated_lookup_generation
                generation_result = isolated_lookup_generation(adapter, parsed.response_id,
                                                               api_key, worker=worker)
                if generation_result.raw_bytes:
                    generation_ref = put_artifact(verified.artifact_root,
                                                  generation_result.raw_bytes, "application/json")
                    read_artifact(verified.artifact_root, generation_ref)
                generation = adapter.parse_generation(generation_result,
                                                     expected_response_id=parsed.response_id,
                                                     expected_model=material["config"]["model"])
                provider_identity_status = "observed"
                if (parsed.observed_cost_microusd is not None and
                        generation["observed_cost_microusd"] is not None and
                        parsed.observed_cost_microusd != generation["observed_cost_microusd"]):
                    parsed = replace(parsed, status="invalid", predictions=(),
                                     observed_cost_microusd=None,
                                     reason="conflicting provider charge evidence")
                elif parsed.observed_cost_microusd is None:
                    parsed = replace(parsed, observed_cost_microusd=generation["observed_cost_microusd"])
            except Exception as exc:
                if isinstance(exc, AdapterError) and "identity mismatch" in str(exc):
                    parsed = replace(parsed, status="invalid", predictions=(),
                                     reason="provider generation identity mismatch")
                    provider_identity_status = "identity_error"
                else:
                    provider_identity_status = f"unverified:{type(exc).__name__}"
        metadata = {"transport": asdict(result), "parsed": asdict(parsed),
                    "route": prepared.route, "response_sha256": saved["response_ref"].sha256,
                    "receipt_sha256": saved["receipt_ref"].sha256,
                    "generation": generation,
                    "provider_identity_status": provider_identity_status,
                    "generation_response_sha256": generation_ref.sha256 if generation_ref else None}
        metadata["transport"]["raw_bytes"] = None
        _save_observation(verified, request_id, saved["response_ref"].sha256, metadata)
        zero_evidence = (_zero_charge_evidence(metadata, offline)
                         if parsed.observed_cost_microusd == 0 else None)
        if parsed.observed_cost_microusd is None or (
                parsed.observed_cost_microusd == 0 and zero_evidence is None):
            verified.recover_response(request_id, token, receipt_ref=saved["receipt_ref"],
                                      billing_reason="provider charge unavailable")
        else:
            verified.recover_response(request_id, token, receipt_ref=saved["receipt_ref"],
                                      settlement_id=f"observed:{request_id}",
                                      charge=parsed.observed_cost_microusd,
                                      zero_charge_evidence=zero_evidence)
    except Exception as exc:
        # A post-intent exception cannot establish whether a provider accepted work.
        state = verified.execution.get(request_id)["request"]["state"]
        if state == "dispatch_intent" and verified.receipt_for(request_id) is None:
            evidence = put_artifact(verified.artifact_root,
                                    canonical_bytes({"request_id": request_id,
                                                     "error_type": type(exc).__name__}),
                                    "application/json")
            verified.record_unknown(request_id, token, evidence.sha256,
                                    "dispatch exception; billing unknown")
        raise


def _recover_one(verified, material, *, max_objects):
    request_id = material["request"]["request_id"]
    state = verified.execution.get(request_id)
    row = state["request"]
    if row["state"] not in ("dispatch_intent", "outcome_unknown"):
        return False
    token = state["execution"]["admission_token"]
    receipt = verified.discover_orphan_receipt(request_id, token, max_objects=max_objects)
    if receipt is None:
        return False
    observation = _observation(verified, request_id)
    if observation is None:
        response_ref = verified._verify_receipt(request_id, token, receipt)
        raw = read_artifact(verified.artifact_root, response_ref)
        result = _transport(verified, request_id, raw)
        if result is not None:
            prepared = material["prepared"]
            adapter = material["adapter"]
            try:
                parsed = adapter.parse(result, expected_request_id=request_id,
                                       expected_ids=prepared.expected_ids,
                                       expected_model=material["config"]["model"])
            except Exception as exc:
                parsed = ParsedResponse("invalid", (), None, None, None, None, None,
                                        None, f"parser error: {type(exc).__name__}")
            parsed = _validate_task_predictions(parsed, material)
            payload = {"transport": {**asdict(result), "raw_bytes": None},
                       "parsed": asdict(parsed), "route": prepared.route,
                       "response_sha256": response_ref.sha256,
                       "receipt_sha256": receipt.sha256,
                       "generation": None, "generation_response_sha256": None,
                       "provider_identity_status": "synthetic" if getattr(adapter, "offline", False)
                       else "unverified:recovery"}
            _save_observation(verified, request_id, response_ref.sha256, payload)
            observation = payload
    if row["state"] == "outcome_unknown":
        verified.recover_response(request_id, token, receipt_ref=receipt)
    else:
        charge = observation["parsed"]["observed_cost_microusd"] if observation else None
        zero_evidence = (_zero_charge_evidence(observation,
                         material["adapter"].__class__ is SyntheticAdapter)
                         if charge == 0 else None)
        if charge is None or (charge == 0 and zero_evidence is None):
            verified.recover_response(request_id, token, receipt_ref=receipt,
                                      billing_reason="recovered receipt; charge unavailable")
        else:
            verified.recover_response(request_id, token, receipt_ref=receipt,
                                      settlement_id=f"observed:{request_id}", charge=charge,
                                      zero_charge_evidence=zero_evidence)
    return True


def _initialize(config, binding, materials):
    verified = VerifiedExecution(config["database"], config["artifacts"])
    _bind(verified, binding)
    BudgetLedger(config["database"]).create_scope(config["scope"], config["cap"],
                                                    config["currency"], config["scale"],
                                                    "synthetic:offline" if config["currency"] == "SYN"
                                                    else f"authorization:{config['authorization_file']}")
    return verified


def _run_unlocked(config_path, *, adapter=None, api_key=None, worker=None):
    """Execute each configuration in declared order, concurrently across configs."""
    config, plan, binding, materials, offline = _load(config_path, adapter)
    _auth(config, plan, binding, len(materials))
    if not offline:
        api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise BenchmarkError("OPENROUTER_API_KEY is required before live admission")
    verified = _initialize(config, binding, materials)
    if _control(verified) != "running":
        result = status(config_path, adapter=adapter)
        result["errors"] = []
        return result
    _reclaim_interrupted_preintent_claims(verified)
    by_config = {}
    for material in materials:
        by_config.setdefault(material["request"]["config_id"], []).append(material)
    refs = {}
    errors = []
    provider_limits = config["provider_limits"]
    active_provider = {key: 0 for key in provider_limits}
    future_info = {}
    claim_by_future = {}
    held_claims = {}

    def provider_for(material):
        value = material["adapter"].provider
        if value not in provider_limits:
            raise BenchmarkError(f"missing provider limit for {value}")
        return value

    def next_material(config_id):
        for material in by_config[config_id]:
            if isinstance(material["adapter"], UnsupportedAdapter):
                return None
            request_id = material["request"]["request_id"]
            with verified.execution.coordinator._transaction() as conn:
                exists = conn.execute("SELECT 1 FROM execution_requests WHERE request_id=?", (request_id,)).fetchone()
            if exists is None:
                refs[request_id] = _refs(verified, material)
                return material
            refs[request_id] = _refs(verified, material)
            state = verified.execution.get(request_id)["request"]["state"]
            if state in ("response_saved", "not_sent", "reconciled"):
                continue
            if state in ("dispatch_intent", "outcome_unknown"):
                _recover_one(verified, material, max_objects=max(10000, 8 * len(materials) + 32))
                state = verified.execution.get(request_id)["request"]["state"]
                if state in ("response_saved", "not_sent", "reconciled"):
                    continue
            return material
        return None

    pending = {config_id: next_material(config_id) for config_id in by_config}
    worker_count = min(config["max_concurrency"], len(by_config))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        while True:
            for request_id, (selected, claim) in list(held_claims.items()):
                if len(future_info) >= worker_count:
                    break
                selected_provider = provider_for(selected)
                remaining = BudgetLedger(config["database"]).balances(config["scope"])["remaining"]
                if (active_provider[selected_provider] >= provider_limits[selected_provider] or
                        remaining < selected["prepared"].reserve_microusd):
                    continue
                active_provider[selected_provider] += 1
                future = pool.submit(_execute_one, config, selected, verified, claim,
                                     refs[request_id], offline, api_key, worker)
                future_info[future] = (selected["request"]["config_id"], selected_provider)
                claim_by_future[future] = claim
                del held_claims[request_id]
            for config_id, material in list(pending.items()):
                if len(future_info) >= worker_count:
                    break
                if material is None or any(info[0] == config_id for info in future_info.values()):
                    continue
                provider = provider_for(material)
                if active_provider[provider] >= provider_limits[provider]:
                    continue
                state = verified.execution.get(material["request"]["request_id"])["request"]["state"]
                if state not in ("ready", "claimed"):
                    pending[config_id] = None
                    continue
                claim = verified.execution.claim("benchmark-matrix", 300)
                if claim is None:
                    continue
                selected = next((x for x in materials if x["request"]["request_id"] == claim["request_id"]), None)
                if selected is None:
                    raise BenchmarkError("claimed request outside bound matrix")
                selected_config = selected["request"]["config_id"]
                selected_provider = provider_for(selected)
                remaining = BudgetLedger(config["database"]).balances(config["scope"])["remaining"]
                if (active_provider[selected_provider] >= provider_limits[selected_provider] or
                        remaining < selected["prepared"].reserve_microusd):
                    held_claims[claim["request_id"]] = (selected, claim)
                    pending[selected_config] = None
                    continue
                active_provider[selected_provider] += 1
                future = pool.submit(_execute_one, config, selected, verified, claim,
                                     refs[claim["request_id"]], offline, api_key, worker)
                future_info[future] = (selected_config, selected_provider)
                claim_by_future[future] = claim
                pending[selected_config] = None
            if not future_info:
                if held_claims:
                    for selected, claim in held_claims.values():
                        _release_claim(verified, claim)
                        pending[selected["request"]["config_id"]] = selected
                    held_claims.clear()
                incomplete = [material for material in pending.values() if material is not None]
                if incomplete:
                    balance = BudgetLedger(config["database"]).balances(config["scope"])
                    remaining = balance["remaining"]
                    if balance["frozen"] or all(material["prepared"].reserve_microusd > remaining
                                               for material in incomplete):
                        _set_control(verified, "paused_budget" if
                                     config["on_budget_exhausted"] == "pause" else "stopped_budget",
                                     f"remaining={remaining}; pending={len(incomplete)}")
                break
            done, _ = wait(future_info, return_when=FIRST_COMPLETED)
            for future in done:
                config_id, provider = future_info.pop(future)
                active_provider[provider] -= 1
                failed = False
                try:
                    future.result()
                except BudgetError as exc:
                    _release_claim(verified, claim_by_future.pop(future))
                    errors.append({"config_id": config_id, "error": f"BudgetError: {exc}"})
                except Exception as exc:
                    claim = claim_by_future.pop(future)
                    if _release_claim(verified, claim):
                        _record_preflight_error(verified, claim["request_id"], type(exc).__name__)
                    errors.append({"config_id": config_id, "error": f"{type(exc).__name__}: {exc}"})
                    failed = True
                else:
                    claim_by_future.pop(future)
                next_item = next_material(config_id)
                if (failed and next_item is not None and
                        next_item["request"]["request_id"] == claim["request_id"]):
                    pending[config_id] = None
                else:
                    pending[config_id] = next_item
    result = status(config_path, adapter=adapter)
    result["errors"] = errors
    return result


def run(config_path, *, adapter=None, api_key=None, worker=None):
    config, _, _, _, _ = _load(config_path, adapter)
    with _runner_lock(config["database"]):
        return _run_unlocked(config_path, adapter=adapter, api_key=api_key, worker=worker)


def status(config_path, *, adapter=None):
    config, plan, binding, materials, _ = _load(config_path, adapter)
    parsed = []
    preflight = {}
    if not Path(config["database"]).exists():
        states = ["never_sent"] * len(materials)
        budget = None
        control = "running"
    else:
        verified = VerifiedExecution(config["database"], config["artifacts"])
        _bind(verified, binding)
        control = _control(verified)
        states = []
        for material in materials:
            try:
                request_id = material["request"]["request_id"]
                states.append(verified.execution.get(request_id)["request"]["state"])
            except CoordinatorError:
                states.append("never_sent")
                continue
            observation = _observation(verified, request_id)
            if observation:
                parsed.append(observation["parsed"]["status"])
            elif states[-1] in ("ready", "claimed"):
                failure = _preflight_error(verified, request_id)
                if failure:
                    preflight[request_id] = failure
        budget = BudgetLedger(config["database"]).balances(config["scope"])
    counts = {state: states.count(state) for state in sorted(set(states))}
    unsupported_count = sum(isinstance(material["adapter"], UnsupportedAdapter)
                            for material in materials)
    preflight_count = len(preflight)
    blocked = 0 if budget is None else sum(
        state in ("never_sent", "ready", "claimed") and
        (budget["frozen"] or budget["remaining"] < material["prepared"].reserve_microusd)
        for state, material in zip(states, materials))
    completed = sum(state in ("response_saved", "not_sent", "reconciled") for state in states)
    run_status = ("stopped_budget" if control == "stopped_budget" else
                  "paused_budget" if control == "paused_budget" else
                  "completed" if completed == len(states) else
                  "recovery_required" if any(x in ("dispatch_intent", "outcome_unknown") for x in states)
                  else "blocked" if (unsupported_count or preflight_count) and
                  completed + unsupported_count + preflight_count == len(states)
                  else "in_progress")
    request_status = []
    for material, state in zip(materials, states):
        reason = None
        if state in ("dispatch_intent", "outcome_unknown"):
            reason = "dispatch may have started; recovery evidence required"
        elif state in ("ready", "claimed", "never_sent"):
            if isinstance(material["adapter"], UnsupportedAdapter):
                reason = material["adapter"].reason
            elif material["request"]["request_id"] in preflight:
                reason = f"pre-admission failure: {preflight[material['request']['request_id']]}"
            elif control == "stopped_budget":
                reason = "run stopped at budget boundary"
            elif control == "paused_budget":
                reason = "budget amendment required"
            elif budget and (budget["frozen"] or
                             budget["remaining"] < material["prepared"].reserve_microusd):
                reason = "insufficient remaining budget"
        request_status.append({"request_id": material["request"]["request_id"],
                               "config_id": material["request"]["config_id"],
                               "prompt_id": material["request"]["prompt_id"],
                               "repeat": material["request"]["repeat"],
                               "batch_index": material["request"]["batch_index"],
                               "state": state, "blocked_reason": reason})
    return {"status": run_status, "planned_requests": len(states),
            "completed_requests": completed, "states": counts,
            "parsed_statuses": {value: parsed.count(value) for value in sorted(set(parsed))},
            "budget_blocked_requests": blocked,
            "unsupported_requests": unsupported_count,
            "preflight_failed_requests": preflight_count,
            "action_required": "amend_budget" if control == "paused_budget" else None,
            "budget": budget, "requests": request_status}


def amend_budget(config_path, amendment_path, *, adapter=None):
    """Apply one separately authorized increase to the bound shared scope."""
    config, _, binding, materials, _ = _load(config_path, adapter)
    amendment, _ = _load_json(amendment_path)
    if (not isinstance(amendment, dict) or set(amendment) != _AMEND_KEYS or
            amendment["schema_version"] != 1 or amendment["run_sha256"] != binding or
            amendment["scope"] != config["scope"]):
        raise BenchmarkError("budget amendment does not match bound run")
    with _runner_lock(config["database"]):
        verified = _initialize(config, binding, materials)
        if _control(verified) == "stopped_budget":
            raise BenchmarkError("stopped run cannot be resumed or amended")
        balance = BudgetLedger(config["database"]).increase_cap(
            config["scope"], amendment["amendment_id"], amendment["expected_cap"],
            amendment["new_cap"], amendment["authorization_source"])
        if _control(verified) == "paused_budget":
            _set_control(verified, "running", f"amendment:{amendment['amendment_id']}")
        return {"status": "amended", "run_sha256": binding, "budget": balance}


def _recover_unlocked(config_path, *, adapter=None, max_objects=None):
    config, _, binding, materials, _ = _load(config_path, adapter)
    verified = _initialize(config, binding, materials)
    bound = max(10000, 8 * len(materials) + 32)
    if max_objects is None:
        max_objects = bound
    elif type(max_objects) is not int or max_objects < bound:
        raise BenchmarkError("recovery object bound must cover declared run")
    recovered = []
    unresolved = []
    for material in materials:
        request_id = material["request"]["request_id"]
        try:
            state = verified.execution.get(request_id)["request"]["state"]
        except CoordinatorError:
            continue
        if state in ("dispatch_intent", "outcome_unknown"):
            _refs(verified, material)
            if _recover_one(verified, material, max_objects=max_objects):
                recovered.append(request_id)
            else:
                unresolved.append(request_id)
    return {"status": "recovery_required" if unresolved else "recovered",
            "recovered": recovered, "unresolved": unresolved}


def recover(config_path, *, adapter=None, max_objects=None):
    config, _, _, _, _ = _load(config_path, adapter)
    with _runner_lock(config["database"]):
        return _recover_unlocked(config_path, adapter=adapter, max_objects=max_objects)


def _verified_response(verified, request_id, state):
    receipt = verified.receipt_for(request_id)
    if receipt is None:
        raise BenchmarkError("terminal response has no receipt")
    token = state["execution"]["admission_token"]
    response_ref = verified._verify_receipt(request_id, token, receipt)
    row = state["request"]
    expected = (row["evidence_id"], row["response_digest"]) if row["state"] == "response_saved" else (
        row["reconciliation_id"], row["reconciliation_response_digest"])
    if expected != (receipt.sha256, response_ref.sha256):
        raise BenchmarkError("terminal evidence does not match verified receipt")
    return receipt, response_ref


def _export_operations_loaded(config, binding, materials):
    if not Path(config["database"]).exists():
        return []
    verified = VerifiedExecution(config["database"], config["artifacts"])
    _bind(verified, binding)
    operations = []
    for material in materials:
        request = material["request"]
        request_id = request["request_id"]
        try:
            state = verified.execution.get(request_id)
        except CoordinatorError:
            state = None
        if state:
            _refs(verified, material)
        row = state["request"] if state else None
        entry = state["execution"] if state else None
        operation = {"request_id": request_id, "config_id": request["config_id"],
                     "prompt_id": request["prompt_id"], "repeat": request["repeat"],
                     "batch_index": request["batch_index"],
                     "ids": [item["id"] for item in request["items"]],
                     "state": row["state"] if row else "never_sent",
                     "attempt_id": row["attempt_id"] if row else None,
                     "route": material["prepared"].route,
                     "blocked_reason": material["adapter"].reason if isinstance(
                         material["adapter"], UnsupportedAdapter) else None,
                     "provider": material["adapter"].provider,
                     "provider_identity_status": None,
                     "cost_currency": config["currency"],
                     "model": material["config"]["model"],
                     "effort": material["config"].get("settings", {}).get("reasoning"),
                     "response_sha256": None, "receipt_sha256": None,
                     "parsed_status": None, "predictions": [], "usage": None,
                     "observed_cost_micro_usd": entry["charge"] if entry and
                     config["currency"] == "USD" else None,
                     "estimated_cost_micro_usd": None,
                     "unresolved_hold_micro_usd": entry["reserve_amount"] if config["currency"] == "USD" and entry and
                     entry["charge"] is None and row["state"] in ("outcome_unknown", "response_saved", "reconciled") else None,
                     "active_reserve_micro_usd": entry["reserve_amount"] if entry and
                     row["state"] == "dispatch_intent" else None,
                     "duration_seconds": None, "provider_generation_seconds": None,
                     "pure_inference_seconds": None, "input_tokens": None,
                     "output_tokens": None, "reasoning_tokens": None, "cache_tokens": None}
        if state and row["state"] == "response_saved" or (
                state and row["state"] == "reconciled" and row["reconciliation_outcome"] == "response_saved"):
            receipt, response_ref = _verified_response(verified, request_id, state)
            operation["response_sha256"] = response_ref.sha256
            operation["receipt_sha256"] = receipt.sha256
            observation = _observation(verified, request_id)
            if observation:
                if observation["response_sha256"] != response_ref.sha256:
                    raise BenchmarkError("operation observation response mismatch")
                parsed = observation["parsed"]
                transport = observation["transport"]
                operation["parsed_status"] = parsed["status"]
                operation["predictions"] = parsed["predictions"]
                operation["usage"] = parsed["usage"]
                operation["duration_seconds"] = transport["duration_ms"] / 1000
                operation["http_status"] = transport["http_status"]
                operation["transport_error"] = transport["error"]
                operation["redacted"] = transport["redacted"]
                operation["truncated"] = transport["truncated"]
                operation["returned_model"] = parsed["returned_model"]
                operation["returned_provider"] = parsed["provider"]
                operation["provider_response_id"] = parsed["response_id"]
                operation["finish_reason"] = parsed["finish_reason"]
                operation["reason"] = parsed["reason"]
                operation["provider_identity_status"] = observation.get("provider_identity_status")
                generation = observation.get("generation")
                if generation:
                    operation["returned_provider"] = generation.get("provider_name")
                    value = generation.get("generation_time_ms")
                    if type(value) is int and value >= 0:
                        operation["provider_generation_seconds"] = value / 1000
                generation_sha = observation.get("generation_response_sha256")
                if generation_sha:
                    ref = ArtifactRef(1, generation_sha,
                                      (Path(config["artifacts"]) / "objects" /
                                       generation_sha[:2] / generation_sha).stat().st_size,
                                      "application/json", f"objects/{generation_sha[:2]}/{generation_sha}")
                    read_artifact(config["artifacts"], ref)
                    operation["generation_response_sha256"] = generation_sha
                usage = parsed["usage"] or {}
                for target, source in (("input_tokens", "prompt_tokens"),
                                       ("output_tokens", "completion_tokens"),
                                       ("reasoning_tokens", "reasoning_tokens"),
                                       ("cache_tokens", "cached_tokens")):
                    value = usage.get(source)
                    if type(value) is int and value >= 0:
                        operation[target] = value
            else:
                # Crash after receipt publication: verified raw bytes survive,
                # but transport metadata and parser outcome remain unavailable.
                read_artifact(config["artifacts"], response_ref)
                operation["parsed_status"] = "unavailable"
        operations.append(operation)
    return operations


def export_operations(config_path, *, adapter=None):
    config, _, binding, materials, _ = _load(config_path, adapter)
    return _export_operations_loaded(config, binding, materials)


def _predictions_from_operations(operations):
    """Pure allowlisted projection of one verified operation snapshot."""
    records = []
    for operation in operations:
        if operation["parsed_status"] == "invalid":
            # Preserve item-level values when the response shape identified
            # positions. Only a fully unparseable batch receives sentinels.
            items = operation["predictions"] or [
                {"id": record_id, "prediction": {"__invalid_response__": "captured"}}
                for record_id in operation["ids"]]
            for item in items:
                records.append({"config_id": operation["config_id"],
                                "prompt_id": operation["prompt_id"],
                                "repeat": operation["repeat"], "id": item["id"],
                                "prediction": item["prediction"]})
            continue
        if operation["parsed_status"] != "valid":
            continue
        for item in operation["predictions"]:
            records.append({"config_id": operation["config_id"],
                            "prompt_id": operation["prompt_id"],
                            "repeat": operation["repeat"], "id": item["id"],
                            "prediction": item["prediction"]})
    return {"records": records}


def export_predictions(config_path, *, adapter=None):
    """Allowlisted projection from verified responses; references are never opened."""
    return _predictions_from_operations(export_operations(config_path, adapter=adapter))


def report_snapshot(config_path, *, adapter=None):
    """Read one runner-exclusive, hash-verified partial or complete report input.

    The caller opens references only after this function returns. An active
    matrix runner holds the same lock, so a report cannot mix request states
    from different moments of that run.
    """
    config, plan, binding, materials, _ = _load(config_path, adapter)
    with _runner_lock(config["database"]):
        operations = _export_operations_loaded(config, binding, materials)
        predictions = _predictions_from_operations(operations)
    return {"task": plan["task"], "plan": plan,
            "predictions": predictions, "operations": operations}
