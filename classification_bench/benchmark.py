"""Declarative matrix execution over immutable requests and one shared ledger.

This module has no reference-label input. Provider dispatch is an explicit,
single-attempt operation after a durable admission record.
"""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, replace
import json
import os
import fcntl
from pathlib import Path
import re
import stat

from .adapters import ParsedResponse, PreparedRequest, TransportResult
from .adapter_runtime import OfflineRuntime, registry
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


registry.register("synthetic", OfflineRuntime(SyntheticAdapter))
_UNSUPPORTED_RUNTIME = OfflineRuntime(UnsupportedAdapter, identity_status="unsupported")


def _runtime(config, supplied=None):
    if supplied is not None:
        return OfflineRuntime(lambda _: supplied)
    adapter = config.get("settings", {}).get("adapter")
    return (registry.get(adapter) if isinstance(adapter, str) else None) or _UNSUPPORTED_RUNTIME


def _adapter_config(config):
    """Pass execution controls to strict adapters; reporting metadata stays in the plan."""
    metadata = {"model_type", "model_metadata"}
    if not metadata.intersection(config):
        return config
    return {key: value for key, value in config.items() if key not in metadata}


def _adapter(config, supplied=None):
    return _runtime(config, supplied).create_adapter(_adapter_config(config))


def _load(config_path, adapter=None):
    config, config_bytes = _load_json(config_path)
    if not isinstance(config, dict) or type(config.get("schema_version")) is not int or config["schema_version"] not in (1, 2):
        raise BenchmarkError("benchmark config must use version 1 or 2")
    managed = config["schema_version"] == 2
    if set(config) != (_CONFIG_KEYS | {"aggregate"} if managed else _CONFIG_KEYS):
        raise BenchmarkError(f"benchmark config must use exact v{config['schema_version']} fields")
    if managed:
        terms = config["aggregate"]
        if (not isinstance(terms, dict) or set(terms) != {"parent_scope", "allocation_id", "phase"}
                or any(not isinstance(terms[k], str) or not terms[k] for k in ("parent_scope", "allocation_id"))
                or terms["phase"] not in ("smoke", "full") or terms["parent_scope"] == config["scope"]):
            raise BenchmarkError("invalid aggregate allocation or phase")
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
    runtimes = {item["id"]: _runtime(item, adapter) for item in experiment["configs"]}
    adapters = {item["id"]: runtimes[item["id"]].create_adapter(_adapter_config(item))
                for item in experiment["configs"]}
    offline = all(item.offline for item in runtimes.values())
    if offline:
        if (config["authorization_file"] is not None or config["currency"] != "SYN" or
                config["scale"] != 1 or not config["scope"].startswith("synthetic:")):
            raise BenchmarkError("synthetic runs require a synthetic scope and currency")
    else:
        currencies = {getattr(item, "accounting_currency", "USD")
                      for item in runtimes.values() if not item.offline}
        if len(currencies) != 1:
            raise BenchmarkError("different accounting units require separate run scopes")
        currency = currencies.pop()
        scale = {"USD": 1_000_000, "REQ": 1}.get(currency)
        if (scale is None or config["currency"] != currency or
                config["scale"] != scale or config["authorization_file"] is None):
            raise BenchmarkError(f"live runs require {currency} units at scale {scale} and an authorization file")
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
        current_runtime = runtimes[cfg["id"]]
        prepared = current_adapter.prepare(plan, request, by_prompt[request["prompt_id"]])
        if not isinstance(prepared.body, bytes) or prepared.request_id != request["request_id"]:
            raise BenchmarkError("adapter prepared an unbound request")
        if (type(prepared.reserve_microusd) is not int or prepared.reserve_microusd <
                (0 if isinstance(current_adapter, UnsupportedAdapter) else 1)):
            raise BenchmarkError("adapter supplied an invalid per-request bound")
        if (config["currency"] == "REQ" and not isinstance(current_adapter, UnsupportedAdapter)
                and prepared.reserve_microusd != 1):
            raise BenchmarkError("request-count admission must reserve exactly one request")
        source_digests = current_runtime.source_digests(current_adapter)
        manifest = canonical_bytes({"schema_version": 1, "request_id": request["request_id"],
                                    "plan_sha256": digest(canonical_bytes(plan)),
                                    "run_sha256": binding, "request_sha256": digest(prepared.body),
                                    "adapter": type(current_adapter).__name__,
                                    **source_digests,
                                    "resolved_controls": cfg.get("settings", {}),
                                    **({"canonical_request_controls": current_adapter.requested_controls}
                                       if hasattr(current_adapter, "requested_controls") else {}),
                                    **({"account_policy_prerequisite": current_adapter.account_policy_prerequisite}
                                       if hasattr(current_adapter, "account_policy_prerequisite") else {}),
                                    "route": prepared.route, "messages": json.loads(prepared.body).get("messages"),
                                    "retry_policy": "none", "cache_policy": "off",
                                    "schedule": {"ordinal": ordinal, "repeat": request["repeat"],
                                                 "batch_index": request["batch_index"]},
                                    "budget_scope": config["scope"]})
        materials.append({"request": request, "prepared": prepared, "manifest": manifest,
                          "adapter": current_adapter, "runtime": current_runtime,
                          "config": cfg, "scope": config["scope"],
                          "fields": plan["task"]["fields"]})
    if managed:
        for material in materials:
            logical = material["request"]["request_id"]
            storage = digest(canonical_bytes({"run_sha256": binding, "logical_request_id": logical}))
            material["logical_request_id"] = logical
            material["request"] = {**material["request"], "request_id": storage}
            manifest = json.loads(material["manifest"])
            manifest.update({"request_id": storage, "logical_request_id": logical,
                             "aggregate": config["aggregate"]})
            material["manifest"] = canonical_bytes(manifest)
    return config, plan, binding, materials, offline


def preflight(config_path, *, adapter=None, api_key=None, worker=None):
    """Check credentials, runtime controls and isolation without admitting work."""
    config, _, binding, materials, _ = _load(config_path, adapter)
    checks = []
    seen = set()
    for material in materials:
        config_id = material["request"]["config_id"]
        if config_id in seen:
            continue
        seen.add(config_id)
        runtime = material["runtime"]
        if isinstance(material["adapter"], UnsupportedAdapter):
            checks.append({"config_id": config_id, "ready": False,
                           "reason": material["adapter"].reason})
            continue
        try:
            stage = "authentication"
            runtime.credential(api_key)
            stage = "runtime, provider controls and isolation"
            if getattr(runtime, "requires_account_assertion", False):
                from .subscription_assertions import SubscriptionAssertionLedger
                guard = SubscriptionAssertionLedger.read_current(config["database"], config["artifacts"],
                            (config["scope"], binding, material["config"]["id"]))
                source = runtime.preflight(material["adapter"], material["prepared"], worker, account_assertion=guard)
            else:
                source = runtime.preflight(material["adapter"], material["prepared"], worker)
            checks.append({"config_id": config_id, "ready": True, "evidence": source})
        except Exception as exc:
            # Runtime exception text may include account/credential details.
            checks.append({"config_id": config_id, "ready": False,
                           "error_type": type(exc).__name__, "failed_check": stage,
                           "next_action": "Verify the declared account/credential, runtime version, provider controls and host isolation prerequisites. No work was admitted."})
    return {"run_sha256": binding, "dispatch_count": 0,
            "ready": all(check["ready"] for check in checks), "checks": checks,
            "scope": "read-only checks; does not authorize execution or reserve capacity"}


def preview(config_path, *, adapter=None):
    config, plan, binding, materials, offline = _load(config_path, adapter)
    return {"run_sha256": binding, "plan_sha256": digest(canonical_bytes(plan)),
            "request_count": len(materials), "scope": config["scope"], "cap": config["cap"],
            "currency": config["currency"], "scale": config["scale"],
            "sum_request_bounds": sum(x["prepared"].reserve_microusd for x in materials),
            "max_request_bound": max(x["prepared"].reserve_microusd for x in materials),
            "offline": offline,
            "requests": [{"request_id": x.get("logical_request_id", x["request"]["request_id"]),
                          **({"storage_request_id": x["request"]["request_id"]} if "logical_request_id" in x else {}),
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


def _bind(verified, binding, config=None):
    verified.benchmark_run_sha256 = binding
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
        managed = config is not None and config["schema_version"] == 2
        if managed:
            if conn.execute("SELECT 1 FROM benchmark_binding").fetchone():
                raise BenchmarkError("managed workflow cannot reuse a legacy run database")
            conn.execute("""CREATE TABLE IF NOT EXISTS benchmark_managed_runs (
                run_sha256 TEXT PRIMARY KEY, scope TEXT UNIQUE NOT NULL,
                parent_scope TEXT NOT NULL, allocation_id TEXT UNIQUE NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS benchmark_managed_control (
                run_sha256 TEXT PRIMARY KEY REFERENCES benchmark_managed_runs(run_sha256),
                state TEXT NOT NULL CHECK(state IN ('running','paused_budget','stopped_budget')))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS benchmark_managed_control_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                run_sha256 TEXT NOT NULL REFERENCES benchmark_managed_runs(run_sha256),
                state TEXT NOT NULL, reason TEXT NOT NULL)""")
            for table in ("benchmark_managed_runs", "benchmark_managed_control_events"):
                for action in ("UPDATE", "DELETE"):
                    conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} "
                                 f"BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable managed binding'); END")
            terms = (binding, config["scope"], config["aggregate"]["parent_scope"], config["aggregate"]["allocation_id"])
            existing = conn.execute("SELECT * FROM benchmark_managed_runs WHERE run_sha256=? OR scope=? OR allocation_id=?",
                                    (binding, config["scope"], config["aggregate"]["allocation_id"])).fetchall()
            if existing and (len(existing) != 1 or tuple(existing[0]) != terms):
                raise BenchmarkError("managed run binding changed")
            if not existing:
                if conn.execute("""SELECT 1 FROM execution_requests x LEFT JOIN benchmark_managed_runs r
                                   ON x.scope=r.scope WHERE r.scope IS NULL LIMIT 1""").fetchone():
                    raise BenchmarkError("database contains unrelated execution requests")
                conn.execute("INSERT INTO benchmark_managed_runs VALUES(?,?,?,?)", terms)
                conn.execute("INSERT INTO benchmark_managed_control VALUES(?,'running')", (binding,))
            verified.benchmark_managed_run = binding
            return
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='benchmark_managed_runs'").fetchone():
            raise BenchmarkError("legacy run cannot reuse a managed workflow database")
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
        binding = getattr(verified, "benchmark_managed_run", None)
        row = (conn.execute("SELECT state FROM benchmark_managed_control WHERE run_sha256=?", (binding,)).fetchone()
               if binding else conn.execute("SELECT state FROM benchmark_run_control WHERE singleton=1").fetchone())
    return row["state"]


def _effective_admission_block_in(verified, conn, scope, *, parent_scope=None):
    """Read the local or inherited first block from one ledger snapshot."""
    block = None
    if conn.execute("SELECT 1 FROM scopes WHERE scope=?", (scope,)).fetchone():
        verified.execution.budget._scope(conn, scope)
        block = verified.execution._admission_block_in(conn, scope)
        allocation = verified.execution.budget._allocation(conn, scope)
        if allocation is not None:
            parent_scope = allocation["parent_scope"]
    elif parent_scope is None:
        verified.execution.budget._scope(conn, scope)  # An unknown independent scope is an error.
    if (block is None and parent_scope is not None
            and conn.execute("SELECT 1 FROM scopes WHERE scope=?", (parent_scope,)).fetchone()):
        verified.execution.budget._scope(conn, parent_scope)
        block = verified.execution._admission_block_in(conn, parent_scope)
    return block


def _effective_admission_block(verified, scope, *, parent_scope=None):
    with verified.execution.coordinator._transaction() as conn:
        return _effective_admission_block_in(verified, conn, scope, parent_scope=parent_scope)


def _configured_admission_block(verified, config):
    parent = config.get("aggregate", {}).get("parent_scope")
    return _effective_admission_block(verified, config["scope"], parent_scope=parent)


def _aggregate_freeze(verified, config):
    if config["schema_version"] != 2:
        return None
    return verified.execution.budget.aggregate_balances(config["aggregate"]["parent_scope"])["freeze"]


def _set_control(verified, state, reason, *, budget_scope=None):
    with verified.execution.coordinator._transaction() as conn:
        binding = getattr(verified, "benchmark_managed_run", None)
        current = (conn.execute("SELECT state FROM benchmark_managed_control WHERE run_sha256=?", (binding,)).fetchone()[0]
                   if binding else conn.execute("SELECT state FROM benchmark_run_control WHERE singleton=1").fetchone()[0])
        if current == "stopped_budget" and state != "stopped_budget":
            raise BenchmarkError("stopped run cannot be resumed")
        if (budget_scope is not None and state in ("paused_budget", "stopped_budget")
                and _effective_admission_block_in(verified, conn, budget_scope) is not None):
            return
        if budget_scope is not None and state in ("paused_budget", "stopped_budget"):
            allocation = verified.execution.budget._allocation(conn, budget_scope)
            if allocation is not None and verified.execution.budget._scope(conn, allocation["parent_scope"])["frozen"]:
                return
        if current != state:
            if binding:
                conn.execute("UPDATE benchmark_managed_control SET state=? WHERE run_sha256=?", (state, binding))
                conn.execute("INSERT INTO benchmark_managed_control_events(run_sha256,state,reason) VALUES(?,?,?)",
                             (binding, state, reason))
            else:
                conn.execute("UPDATE benchmark_run_control SET state=? WHERE singleton=1", (state,))
                conn.execute("INSERT INTO benchmark_run_control_events(state,reason) VALUES(?,?)", (state, reason))


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


def _saved_refs(verified, material):
    """Verify an enrolled request using its immutable historical artifacts.

    Reading results must not require the adapter and runtime source files to
    retain the same bytes forever. Dispatch still uses `_refs` above, which
    deliberately checks the current build's complete manifest and body.
    """
    request = material["request"]
    entry = verified.execution.get(request["request_id"])["execution"]
    refs = []
    values = []
    for sha in (entry["manifest_digest"], entry["input_digest"]):
        path = verified.artifact_root / "objects" / sha[:2] / sha
        ref = ArtifactRef(1, sha, path.stat().st_size, "application/json",
                          f"objects/{sha[:2]}/{sha}")
        values.append(json.loads(read_artifact(verified.artifact_root, ref)))
        refs.append(ref)
    manifest, body = values
    expected = json.loads(material["manifest"])
    frozen_fields = ("schema_version", "request_id", "plan_sha256", "run_sha256",
                     "resolved_controls", "retry_policy", "cache_policy", "schedule",
                     "budget_scope")
    if "logical_request_id" in material:
        frozen_fields += ("logical_request_id", "aggregate")
    if isinstance(manifest, dict) and "canonical_request_controls" in manifest:
        frozen_fields += ("canonical_request_controls",)
    if isinstance(manifest, dict) and "account_policy_prerequisite" in manifest:
        frozen_fields += ("account_policy_prerequisite",)
    if (not isinstance(manifest, dict) or not isinstance(body, dict) or
            any(manifest.get(key) != expected.get(key) for key in frozen_fields) or
            manifest.get("request_sha256") != refs[1].sha256 or
            body.get("request_id", material.get("logical_request_id", request["request_id"])) != material.get("logical_request_id", request["request_id"]) or
            body.get("messages") != manifest.get("messages") or
            not isinstance(manifest.get("adapter_source_sha256"), str) or
            re.fullmatch(r"[0-9a-f]{64}", manifest["adapter_source_sha256"]) is None or
            not isinstance(manifest.get("route"), str) or not manifest["route"]):
        raise BenchmarkError("saved request binding mismatch")
    for name in ("runtime_source_sha256", "transport_source_sha256"):
        value = manifest.get(name)
        if value is not None and (not isinstance(value, str) or
                                  re.fullmatch(r"[0-9a-f]{64}", value) is None):
            raise BenchmarkError("saved runtime binding invalid")
    return {"manifest_ref": refs[0], "request_ref": refs[1], "manifest": manifest}


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


def _record_subscription_block(verified, material, observation):
    if getattr(material["runtime"], "accounting_currency", "USD") != "REQ" or not observation:
        return
    parsed = observation["parsed"]
    evidence = (parsed.get("usage") or {}).get("subscription") or {}
    reason = None
    if evidence.get("overage_observed") and evidence.get("paid_credit_authorized") is not True:
        reason = "subscription paid extra usage observed"
    elif evidence.get("quota_exhausted"):
        reason = "subscription quota exhausted"
    elif parsed.get("reason") in (
            "CLI context, tool or authentication isolation violation",
            "CLI tool isolation violation", "returned model mismatch", "CLI billing policy receipt mismatch"):
        reason = parsed["reason"]
    if reason:
        verified.execution.block_scope(material["scope"], reason, observation["response_sha256"])
        allocation = verified.execution.budget.allocation_for(material["scope"])
        if allocation is not None:
            verified.execution.block_scope(allocation["parent_scope"], reason, observation["response_sha256"])


def _execute_one(config, material, verified, claim, refs, api_key, worker):
    request = material["request"]
    request_id = request["request_id"]
    adapter = material["adapter"]
    runtime = material["runtime"]
    prepared = material["prepared"]
    token = claim["token"]
    # Provider preflight and any isolation proof precede the durable grant.
    admission_guard = None
    if getattr(runtime, "requires_account_assertion", False):
        from .subscription_assertions import SubscriptionAssertionLedger
        assertions = SubscriptionAssertionLedger(verified.execution, verified.artifact_root)
        key = (config["scope"], verified.benchmark_run_sha256, material["config"]["id"])
        guard = assertions.current(*key)
        bound_source = runtime.preflight(adapter, prepared, worker, account_assertion=guard)
        def admission_guard(conn):
            assertions.require_fresh_in(conn, key, guard["revision"], request_id=request_id, admission_token=token)
    else:
        bound_source = runtime.preflight(adapter, prepared, worker)
    verified.admit_verified(request_id, token, config["scope"], prepared.reserve_microusd,
                            refs["manifest_ref"], refs["request_ref"], bound_source=bound_source,
                            admission_guard=admission_guard)
    try:
        result = runtime.dispatch(adapter, prepared, api_key, worker)
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
        source = (f"{prepared.route}:cli-receipt" if config["currency"] == "REQ"
                  else f"{prepared.route}:http:{result.http_status}")
        saved = verified.save_response(request_id, token, result.raw_bytes,
                                       "application/json", source)
        if saved["response_ref"] != raw_ref:
            raise BenchmarkError("published response changed between transport and receipt")
        # Original bounded response is now durable; only then parse it.
        try:
            policy_args = {"account_assertion": assertions.admitted_assertion(request_id, token)} if admission_guard else {}
            parsed = runtime.parse(adapter, result, expected_request_id=material.get("logical_request_id", request_id),
                                   expected_ids=prepared.expected_ids,
                                   expected_model=material["config"]["model"], **policy_args)
        except Exception as exc:
            parsed = ParsedResponse("invalid", (), None, None, None, None, None, None,
                                    f"parser error: {type(exc).__name__}")
        parsed = _validate_task_predictions(parsed, material)
        supplement = runtime.supplement(adapter, parsed, api_key, worker,
                                        verified.artifact_root, material["config"])
        parsed = supplement.parsed
        metadata = {"transport": asdict(result), "parsed": asdict(parsed),
                    "route": prepared.route, "response_sha256": saved["response_ref"].sha256,
                    "receipt_sha256": saved["receipt_ref"].sha256,
                    "generation": supplement.generation,
                    "provider_identity_status": supplement.identity_status,
                    "generation_response_sha256": supplement.generation_response_sha256}
        metadata["transport"]["raw_bytes"] = None
        _save_observation(verified, request_id, saved["response_ref"].sha256, metadata)
        _record_subscription_block(verified, material, metadata)
        zero_evidence = (runtime.zero_charge_evidence(metadata)
                         if parsed.observed_cost_microusd == 0 else None)
        if config["currency"] == "REQ":
            # This settles consumed dispatch capacity, never a provider USD charge.
            verified.recover_response(request_id, token, receipt_ref=saved["receipt_ref"],
                                      settlement_id=f"request:{request_id}", charge=1)
        elif parsed.observed_cost_microusd is None or (
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
                policy_args = {}
                if getattr(material["runtime"], "requires_account_assertion", False):
                    from .subscription_assertions import SubscriptionAssertionLedger
                    policy_args["account_assertion"] = SubscriptionAssertionLedger(
                        verified.execution, verified.artifact_root).admitted_assertion(request_id, token)
                parsed = material["runtime"].parse(
                    adapter, result, expected_request_id=material.get("logical_request_id", request_id),
                    expected_ids=prepared.expected_ids,
                    expected_model=material["config"]["model"], **policy_args)
            except Exception as exc:
                parsed = ParsedResponse("invalid", (), None, None, None, None, None,
                                        None, f"parser error: {type(exc).__name__}")
            parsed = _validate_task_predictions(parsed, material)
            payload = {"transport": {**asdict(result), "raw_bytes": None},
                       "parsed": asdict(parsed), "route": prepared.route,
                       "response_sha256": response_ref.sha256,
                       "receipt_sha256": receipt.sha256,
                       "generation": None, "generation_response_sha256": None,
                       "provider_identity_status": material["runtime"].recovery_identity_status()}
            _save_observation(verified, request_id, response_ref.sha256, payload)
            observation = payload
    _record_subscription_block(verified, material, observation)
    if row["state"] == "outcome_unknown":
        verified.recover_response(request_id, token, receipt_ref=receipt)
    else:
        charge = observation["parsed"]["observed_cost_microusd"] if observation else None
        zero_evidence = (material["runtime"].zero_charge_evidence(observation)
                         if charge == 0 else None)
        if getattr(material["runtime"], "accounting_currency", "USD") == "REQ":
            verified.recover_response(request_id, token, receipt_ref=receipt,
                                      settlement_id=f"request:{request_id}", charge=1)
        elif charge is None or (charge == 0 and zero_evidence is None):
            verified.recover_response(request_id, token, receipt_ref=receipt,
                                      billing_reason="recovered receipt; charge unavailable")
        else:
            verified.recover_response(request_id, token, receipt_ref=receipt,
                                      settlement_id=f"observed:{request_id}", charge=charge,
                                      zero_charge_evidence=zero_evidence)
    return True


def _initialize(config, binding, materials):
    verified = VerifiedExecution(config["database"], config["artifacts"])
    _bind(verified, binding, config)
    ledger = BudgetLedger(config["database"])
    source = "synthetic:offline" if config["currency"] == "SYN" else f"authorization:{config['authorization_file']}"
    if config["schema_version"] == 2:
        terms = config["aggregate"]
        if ledger.allocation_for(config["scope"]) is None and (
                _configured_admission_block(verified, config) or _aggregate_freeze(verified, config)):
            return verified
        try:
            ledger.allocate_child(terms["parent_scope"], config["scope"], terms["allocation_id"],
                                  config["cap"], binding, source, phase=terms["phase"],
                                  currency=config["currency"], scale=config["scale"])
        except BudgetError:
            # The parent may have been blocked between the initial read and allocation.
            if ledger.allocation_for(config["scope"]) is None and (
                    _configured_admission_block(verified, config) or _aggregate_freeze(verified, config)):
                return verified
            raise
    else:
        ledger.create_scope(config["scope"], config["cap"], config["currency"], config["scale"], source)
    if any(getattr(material["runtime"], "requires_account_assertion", False) for material in materials):
        from .subscription_assertions import SubscriptionAssertionLedger
        assertions = SubscriptionAssertionLedger(verified.execution, verified.artifact_root)
        seen = set()
        for material in materials:
            cfg = material["config"]
            if cfg["id"] in seen or not getattr(material["runtime"], "requires_account_assertion", False):
                continue
            seen.add(cfg["id"])
            settings = cfg["settings"]
            current_adapter = material["adapter"]
            assertions.bind_initial(config["scope"], binding, cfg["id"], digest(canonical_bytes(cfg)),
                                    settings["adapter"], current_adapter.initial_account_assertion,
                                    account_check_path=current_adapter.account_check_file)
    return verified


def _loaded_group(config_path, *, adapter=None):
    config, plan, binding, materials, _ = _load(config_path, adapter)
    return {"config_path": str(Path(config_path).resolve()), "adapter": adapter,
            "config": config, "plan": plan, "binding": binding,
            "materials": materials, "errors": []}


def _validate_schedule(groups, max_concurrency, provider_limits, *, managed=False):
    """Reject incompatible frozen controls and identities before admitting work."""
    if (type(max_concurrency) is not int or max_concurrency < 1 or
            not isinstance(provider_limits, dict) or not provider_limits or
            any(not isinstance(key, str) or not key or type(value) is not int or value < 1
                for key, value in provider_limits.items())):
        raise BenchmarkError("invalid shared concurrency or provider limits")
    first = groups[0]["config"]
    scopes, allocation_ids, config_ids = set(), set(), set()
    for group in groups:
        config = group["config"]
        if managed:
            if config["schema_version"] != 2:
                raise BenchmarkError("run groups require managed version-2 configurations")
            if Path(config["database"]).resolve() != Path(first["database"]).resolve():
                raise BenchmarkError("run groups must share one authoritative database")
            if Path(config["artifacts"]).resolve() != Path(first["artifacts"]).resolve():
                raise BenchmarkError("run groups must share one artifact store")
            if config["aggregate"]["phase"] != first["aggregate"]["phase"]:
                raise BenchmarkError("run groups must share the same managed phase")
            if config["on_budget_exhausted"] != first["on_budget_exhausted"]:
                raise BenchmarkError("run groups must share one exhaustion policy")
            if config["scope"] in scopes:
                raise BenchmarkError("run groups require distinct scopes")
            allocation_id = config["aggregate"]["allocation_id"]
            if allocation_id in allocation_ids:
                raise BenchmarkError("run groups require distinct allocation IDs")
            allocation_ids.add(allocation_id)
            scopes.add(config["scope"])
        if config["max_concurrency"] != max_concurrency:
            raise BenchmarkError("frozen group concurrency differs from the shared concurrency")
        if config["provider_limits"] != provider_limits:
            raise BenchmarkError("frozen group provider limits differ from the shared provider limits")
        for cfg in group["plan"]["experiment"]["configs"]:
            if cfg["id"] in config_ids:
                raise BenchmarkError("run groups require distinct configuration IDs")
            config_ids.add(cfg["id"])
        for material in group["materials"]:
            if (not isinstance(material["adapter"], UnsupportedAdapter) and
                    material["adapter"].provider not in provider_limits):
                raise BenchmarkError(f"missing provider limit for {material['adapter'].provider}")


def _run_loaded(groups, *, max_concurrency, provider_limits, api_key=None, worker=None):
    """Schedule every group on one pool, retaining each scope's admission authority."""
    # Validate every group's authority before any credential lookup or initialization.
    for group in groups:
        _auth(group["config"], group["plan"], group["binding"], len(group["materials"]))
    credentials = {}
    for group in groups:
        group["verified"] = _initialize(group["config"], group["binding"], group["materials"])
        for material in group["materials"]:
            _record_subscription_block(group["verified"], material,
                _observation(group["verified"], material["request"]["request_id"]))
    # The single database lock proves that all previous matrix workers are gone.
    _reclaim_interrupted_preintent_claims(groups[0]["verified"])
    by_config, group_by_config = {}, {}
    for group in groups:
        for material in group["materials"]:
            config_id = material["request"]["config_id"]
            by_config.setdefault(config_id, []).append(material)
            group_by_config[config_id] = group
    refs, future_info, claim_by_future, held_claims = {}, {}, {}, {}
    recovery_objects = max(10000, 8 * sum(len(group["materials"]) for group in groups) + 32)
    active_provider = {key: 0 for key in provider_limits}

    def blocked(group):
        verified, config = group["verified"], group["config"]
        return (_configured_admission_block(verified, config) or
                _aggregate_freeze(verified, config) or _control(verified) != "running")

    def next_material(config_id):
        group = group_by_config[config_id]
        verified = group["verified"]
        if blocked(group):
            return None
        for material in by_config[config_id]:
            if isinstance(material["adapter"], UnsupportedAdapter):
                return None
            request_id = material["request"]["request_id"]
            with verified.execution.coordinator._transaction() as conn:
                exists = conn.execute("SELECT 1 FROM execution_requests WHERE request_id=?", (request_id,)).fetchone()
            refs[request_id] = _refs(verified, material)
            if exists is None:
                return material
            state = verified.execution.get(request_id)["request"]["state"]
            if state in ("response_saved", "not_sent", "reconciled"):
                continue
            if state in ("dispatch_intent", "outcome_unknown"):
                _recover_one(verified, material, max_objects=recovery_objects)
                state = verified.execution.get(request_id)["request"]["state"]
                if state in ("response_saved", "not_sent", "reconciled"):
                    continue
            return material
        return None

    def remaining(group):
        return group["verified"].execution.budget.balances(group["config"]["scope"])["remaining"]

    def submit(pool, material, claim):
        config_id = material["request"]["config_id"]
        group = group_by_config[config_id]
        provider = material["adapter"].provider
        active_provider[provider] += 1
        future = pool.submit(_execute_one, group["config"], material, group["verified"], claim,
                             refs[claim["request_id"]], credentials[config_id], worker)
        future_info[future] = (config_id, provider)
        claim_by_future[future] = claim

    pending = {config_id: next_material(config_id) for config_id in by_config}
    for config_id, material in pending.items():
        group = group_by_config[config_id]
        if (material is None or blocked(group) or
                remaining(group) < material["prepared"].reserve_microusd or
                group["verified"].execution.get(material["request"]["request_id"])["request"]["state"]
                not in ("ready", "claimed")):
            continue
        try:
            credentials[config_id] = material["runtime"].credential(api_key)
        except ValueError as exc:
            raise BenchmarkError(str(exc)) from exc
    worker_count = min(max_concurrency, len(by_config))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        while True:
            for group in groups:
                if not blocked(group):
                    continue
                for request_id, (material, claim) in list(held_claims.items()):
                    if group_by_config[material["request"]["config_id"]] is group:
                        _release_claim(group["verified"], claim)
                        del held_claims[request_id]
                for config_id in pending:
                    if group_by_config[config_id] is group:
                        pending[config_id] = None
            for request_id, (material, claim) in list(held_claims.items()):
                if len(future_info) >= worker_count:
                    break
                group = group_by_config[material["request"]["config_id"]]
                provider = material["adapter"].provider
                if (active_provider[provider] >= provider_limits[provider] or
                        remaining(group) < material["prepared"].reserve_microusd):
                    continue
                submit(pool, material, claim)
                del held_claims[request_id]
            for config_id, material in list(pending.items()):
                if len(future_info) >= worker_count:
                    break
                if material is None or any(info[0] == config_id for info in future_info.values()):
                    continue
                provider = material["adapter"].provider
                if active_provider[provider] >= provider_limits[provider]:
                    continue
                group = group_by_config[config_id]
                verified = group["verified"]
                state = verified.execution.get(material["request"]["request_id"])["request"]["state"]
                if state not in ("ready", "claimed"):
                    pending[config_id] = None
                    continue
                claim = verified.execution.claim("benchmark-matrix", 300,
                                                 request_id=material["request"]["request_id"])
                if claim is None:
                    continue
                if remaining(group) < material["prepared"].reserve_microusd:
                    held_claims[claim["request_id"]] = (material, claim)
                else:
                    submit(pool, material, claim)
                pending[config_id] = None
            # Apply a unit's policy as soon as its admitted workers have drained,
            # even while independent groups still have in-flight work.
            for group in groups:
                if blocked(group) or any(group_by_config[info[0]] is group for info in future_info.values()):
                    continue
                incomplete = [material for config_id, material in pending.items()
                              if material is not None and group_by_config[config_id] is group]
                incomplete.extend(material for material, _ in held_claims.values()
                                  if group_by_config[material["request"]["config_id"]] is group)
                if not incomplete:
                    continue
                balance = group["verified"].execution.budget.balances(group["config"]["scope"])
                if balance["frozen"] or all(material["prepared"].reserve_microusd > balance["remaining"]
                                           for material in incomplete):
                    for request_id, (material, claim) in list(held_claims.items()):
                        config_id = material["request"]["config_id"]
                        if group_by_config[config_id] is group:
                            _release_claim(group["verified"], claim)
                            pending[config_id] = material
                            del held_claims[request_id]
                    _set_control(group["verified"], "paused_budget" if
                                 group["config"]["on_budget_exhausted"] == "pause" else "stopped_budget",
                                 f"remaining={balance['remaining']}; pending={len(incomplete)}",
                                 budget_scope=group["config"]["scope"])
            if not future_info:
                for material, claim in held_claims.values():
                    _release_claim(group_by_config[material["request"]["config_id"]]["verified"], claim)
                held_claims.clear()
                break
            done, _ = wait(future_info, return_when=FIRST_COMPLETED)
            for future in done:
                config_id, provider = future_info.pop(future)
                active_provider[provider] -= 1
                group = group_by_config[config_id]
                verified = group["verified"]
                claim = claim_by_future.pop(future)
                failed = False
                try:
                    future.result()
                except BudgetError as exc:
                    _release_claim(verified, claim)
                    group["errors"].append({"config_id": config_id, "error": f"BudgetError: {exc}"})
                except Exception as exc:
                    if _release_claim(verified, claim):
                        _record_preflight_error(verified, claim["request_id"], type(exc).__name__)
                    group["errors"].append({"config_id": config_id, "error": f"{type(exc).__name__}: {exc}"})
                    failed = True
                next_item = next_material(config_id)
                pending[config_id] = (None if failed and next_item is not None and
                    next_item["request"]["request_id"] == claim["request_id"] else next_item)
    results = []
    for group in groups:
        result = status(group["config_path"], adapter=group["adapter"])
        result["errors"] = group["errors"]
        results.append(result)
    return results


def _run_unlocked(config_path, *, adapter=None, api_key=None, worker=None):
    group = _loaded_group(config_path, adapter=adapter)
    config = group["config"]
    _validate_schedule([group], config["max_concurrency"], config["provider_limits"])
    return _run_loaded([group], max_concurrency=config["max_concurrency"],
                       provider_limits=config["provider_limits"], api_key=api_key, worker=worker)[0]


def run(config_path, *, adapter=None, api_key=None, worker=None):
    group = _loaded_group(config_path, adapter=adapter)
    config = group["config"]
    _validate_schedule([group], config["max_concurrency"], config["provider_limits"])
    with _runner_lock(Path(config["database"]).resolve()):
        return _run_loaded([group], max_concurrency=config["max_concurrency"],
                           provider_limits=config["provider_limits"], api_key=api_key, worker=worker)[0]


def run_groups(config_paths, *, max_concurrency, provider_limits, api_key=None, worker=None):
    """Run ordered managed groups concurrently under one database runner lock."""
    if isinstance(config_paths, (str, bytes, Path)):
        raise BenchmarkError("config_paths must be a nonempty sequence of configuration paths")
    paths = list(config_paths)
    if not paths:
        raise BenchmarkError("config_paths must be a nonempty sequence of configuration paths")
    groups = [_loaded_group(path) for path in paths]
    _validate_schedule(groups, max_concurrency, provider_limits, managed=True)
    with _runner_lock(Path(groups[0]["config"]["database"]).resolve()):
        results = _run_loaded(groups, max_concurrency=max_concurrency,
                              provider_limits=provider_limits, api_key=api_key, worker=worker)
    return [{**result, "config_path": group["config_path"]} for group, result in zip(groups, results)]


def status(config_path, *, adapter=None):
    config, plan, binding, materials, _ = _load(config_path, adapter)
    parsed = []
    preflight = {}
    admission_block = None
    aggregate_freeze = None
    if not Path(config["database"]).exists():
        states = ["never_sent"] * len(materials)
        budget = None
        control = "running"
    else:
        verified = VerifiedExecution(config["database"], config["artifacts"])
        _bind(verified, binding, config)
        control = _control(verified)
        ledger = BudgetLedger(config["database"])
        allocated = config["schema_version"] == 1 or ledger.allocation_for(config["scope"]) is not None
        admission_block = _configured_admission_block(verified, config)
        aggregate_freeze = _aggregate_freeze(verified, config)
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
        budget = ledger.balances(config["scope"]) if allocated else None
    counts = {state: states.count(state) for state in sorted(set(states))}
    unsupported_count = sum(isinstance(material["adapter"], UnsupportedAdapter)
                            for material in materials)
    preflight_count = len(preflight)
    blocked = 0 if budget is None else sum(
        state in ("never_sent", "ready", "claimed") and
        (budget["frozen"] or budget["remaining"] < material["prepared"].reserve_microusd)
        for state, material in zip(states, materials))
    completed = sum(state in ("response_saved", "not_sent", "reconciled") for state in states)
    run_status = ("blocked_safety" if admission_block else
                  "blocked_budget_freeze" if aggregate_freeze else
                  "stopped_budget" if control == "stopped_budget" else
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
            if admission_block:
                reason = admission_block["reason"]
            elif aggregate_freeze:
                reason = "aggregate frozen after an above-bound charge; review retained settlement evidence"
            elif isinstance(material["adapter"], UnsupportedAdapter):
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
        request_status.append({"request_id": material.get("logical_request_id", material["request"]["request_id"]),
                               **({"storage_request_id": material["request"]["request_id"]} if "logical_request_id" in material else {}),
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
            "admission_block": admission_block,
            **({"aggregate_freeze": aggregate_freeze} if config["schema_version"] == 2 else {}),
            "action_required": "review_safety_block" if admission_block else
                               "review_budget_freeze" if aggregate_freeze else
                               "amend_budget" if control == "paused_budget" else None,
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
        if _configured_admission_block(verified, config):
            raise BenchmarkError("blocked scope cannot be resumed by increasing its budget")
        if _aggregate_freeze(verified, config):
            raise BenchmarkError("frozen aggregate cannot be resumed by increasing its budget")
        if _control(verified) == "stopped_budget":
            raise BenchmarkError("stopped run cannot be resumed or amended")
        ledger = BudgetLedger(config["database"])
        amend = ledger.increase_allocation if config["schema_version"] == 2 else ledger.increase_cap
        balance = amend(
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


def _frozen_canonical_model(saved):
    """Read catalog identity only from an enrolled, verified manifest."""
    controls = saved["manifest"].get("resolved_controls") if saved else None
    snapshot = controls.get("endpoint_snapshot") if isinstance(controls, dict) else None
    identity = snapshot.get("model_identity") if isinstance(snapshot, dict) else None
    canonical = identity.get("canonical_id") if isinstance(identity, dict) else None
    return canonical if isinstance(canonical, str) and canonical else None


def _export_operations_loaded(config, binding, materials):
    if not Path(config["database"]).exists():
        return []
    verified = VerifiedExecution(config["database"], config["artifacts"])
    _bind(verified, binding, config)
    operations = []
    for material in materials:
        request = material["request"]
        request_id = request["request_id"]
        try:
            state = verified.execution.get(request_id)
        except CoordinatorError:
            state = None
        saved = _saved_refs(verified, material) if state else None
        row = state["request"] if state else None
        entry = state["execution"] if state else None
        operation = {"request_id": material.get("logical_request_id", request_id), "config_id": request["config_id"],
                     "prompt_id": request["prompt_id"], "repeat": request["repeat"],
                     "batch_index": request["batch_index"],
                     "ids": [item["id"] for item in request["items"]],
                     "state": row["state"] if row else "never_sent",
                     "attempt_id": row["attempt_id"] if row else None,
                     "route": saved["manifest"]["route"] if saved else material["prepared"].route,
                     "adapter_source_sha256": saved["manifest"].get("adapter_source_sha256") if saved else None,
                     "runtime_source_sha256": saved["manifest"].get("runtime_source_sha256") if saved else None,
                     "transport_source_sha256": saved["manifest"].get("transport_source_sha256") if saved else None,
                     "blocked_reason": material["adapter"].reason if isinstance(
                         material["adapter"], UnsupportedAdapter) else None,
                     "provider": material["adapter"].provider,
                     "provider_identity_status": None,
                     "frozen_canonical_model": _frozen_canonical_model(saved),
                     "generation_returned_model": None,
                     "cost_currency": config["currency"],
                     "model": material["config"]["model"],
                     "effort": material["config"].get("settings", {}).get("reasoning",
                         material["config"].get("settings", {}).get("effort")),
                     "response_sha256": None, "receipt_sha256": None,
                     "parsed_status": None, "predictions": [], "usage": None,
                     "observed_cost_micro_usd": entry["charge"] if entry and
                     config["currency"] == "USD" else None,
                     "estimated_cost_micro_usd": None,
                     "unresolved_hold_micro_usd": entry["reserve_amount"] if config["currency"] == "USD" and entry and
                     entry["charge"] is None and row["state"] in ("outcome_unknown", "response_saved", "reconciled") else None,
                     "active_reserve_micro_usd": entry["reserve_amount"] if entry and config["currency"] != "REQ" and
                     row["state"] == "dispatch_intent" else None,
                     "duration_seconds": None, "provider_generation_seconds": None,
                     "pure_inference_seconds": None, "input_tokens": None,
                     "output_tokens": None, "reasoning_tokens": None, "cache_tokens": None}
        if config["currency"] == "REQ":
            operation.update(accounting_unit="request", subscription_cost_status="unavailable",
                             consumed_requests=entry["charge"] if entry else None,
                             unresolved_request_hold=entry["reserve_amount"] if entry and
                             entry["charge"] is None and row["state"] in
                             ("dispatch_intent", "outcome_unknown", "response_saved", "reconciled") else None)
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
                    operation["generation_returned_model"] = generation.get("returned_model")
                    operation["returned_provider"] = generation.get("provider_name") or operation["returned_provider"]
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
                for target, sources in (("input_tokens", ("prompt_tokens", "input_tokens")),
                                        ("output_tokens", ("completion_tokens", "output_tokens")),
                                        ("reasoning_tokens", ("reasoning_tokens",)),
                                        ("cache_tokens", ("cached_tokens",))):
                    value = next((usage[key] for key in sources if key in usage), None)
                    if type(value) is int and value >= 0:
                        operation[target] = value
            else:
                # Crash after receipt publication: verified raw bytes survive,
                # but transport metadata and parser outcome remain unavailable.
                read_artifact(config["artifacts"], response_ref)
                operation["parsed_status"] = "unavailable"
        if "logical_request_id" in material:
            operation["storage_request_id"] = request_id
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


def renew_account_assertion(config_path, authorization_path, evidence_path, *, adapter=None):
    """Append a checked operator declaration; never dispatch or alter run identity."""
    config, _, binding, materials, _ = _load(config_path, adapter)
    if config["currency"] != "REQ":
        raise BenchmarkError("account assertions apply only to subscription request scopes")
    authorization, _ = _load_json(authorization_path)
    if (not isinstance(authorization, dict) or authorization.get("run_sha256") != binding
            or authorization.get("scope") != config["scope"]):
        raise BenchmarkError("account assertion renewal does not match bound run")
    with _runner_lock(config["database"]):
        verified = _initialize(config, binding, materials)
        from .subscription_assertions import SubscriptionAssertionLedger
        ledger = SubscriptionAssertionLedger(verified.execution, verified.artifact_root)
        with Path(evidence_path).open("rb") as source:
            evidence = source.read(1_000_001)
        return ledger.renew(authorization, evidence)


def aggregate_budget(spec_path, *, create=False, amendment_path=None):
    """Create or inspect explicit aggregate terms without model dispatch."""
    spec, raw = _load_json(spec_path)
    keys = {"schema_version", "database", "scope", "cap", "currency", "scale", "authorization_source"}
    if (not isinstance(spec, dict) or set(spec) != keys or type(spec["schema_version"]) is not int
            or spec["schema_version"] != 1 or not isinstance(spec["database"], str)
            or not Path(spec["database"]).is_absolute()
            or not isinstance(spec["scope"], str) or not spec["scope"]
            or spec["scope"] != spec["scope"].strip()
            or type(spec["cap"]) is not int or spec["cap"] <= 0
            or not isinstance(spec["authorization_source"], str) or not spec["authorization_source"].strip()
            or spec["authorization_source"] != spec["authorization_source"].strip()
            or spec["currency"] not in ("USD", "REQ", "SYN")
            or type(spec["scale"]) is not int
            or spec["scale"] != (1_000_000 if spec["currency"] == "USD" else 1)):
        raise BenchmarkError("aggregate specification must use exact fields, absolute database and declared units")
    if not create and not Path(spec["database"]).exists():
        raise BenchmarkError("aggregate database does not exist")
    # Observing aggregate usage must remain available while a runner owns the
    # database. Ledger reads verify balances inside their SQLite transaction.
    with (_runner_lock(spec["database"]) if create or amendment_path is not None else nullcontext()):
        ledger = BudgetLedger(spec["database"])
        if create:
            ledger.create_aggregate(spec["scope"], spec["cap"], spec["currency"], spec["scale"],
                                    f"{spec['authorization_source']}; specification:{digest(raw)}")
        ledger.verify_aggregate(spec["scope"])
        balance = ledger.aggregate_balances(spec["scope"])
        if balance["authorization_source"] != f"{spec['authorization_source']}; specification:{digest(raw)}":
            raise BenchmarkError("aggregate specification does not match frozen authority")
        if balance["currency"] != spec["currency"] or balance["scale"] != spec["scale"]:
            raise BenchmarkError("aggregate specification units do not match saved authority")
        if amendment_path is not None:
            amendment, _ = _load_json(amendment_path)
            required = {"schema_version", "aggregate_spec_sha256", "scope", "amendment_id",
                        "expected_cap", "new_cap", "authorization_source"}
            if (not isinstance(amendment, dict) or set(amendment) != required
                    or type(amendment["schema_version"]) is not int or amendment["schema_version"] != 1
                    or amendment["aggregate_spec_sha256"] != digest(raw) or amendment["scope"] != spec["scope"]):
                raise BenchmarkError("aggregate amendment does not match frozen specification")
            if balance["frozen"] or balance.get("admission_block"):
                raise BenchmarkError("blocked aggregate cannot be resumed by increasing its budget")
            ledger.increase_cap(spec["scope"], amendment["amendment_id"], amendment["expected_cap"],
                                amendment["new_cap"], amendment["authorization_source"])
            balance = ledger.aggregate_balances(spec["scope"])
        return {"dispatch_count": 0, "aggregate_spec_sha256": digest(raw), "budget": balance,
                "scope": "explicit local allocation authority; does not authorize provider inference"}
