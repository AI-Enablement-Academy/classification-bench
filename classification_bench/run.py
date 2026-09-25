"""One-config offline simulated execution through the verified ledger."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .budget import BudgetLedger
from .core import build_plan
from .evidence import ArtifactRef, read_artifact
from .isolation import SandboxedPythonWorker
from .manifest import ManifestError, build_manifest, canonical_bytes, digest, render_request, validate_manifest
from .simulated_transport import WORKER_SOURCE, build_digest, parse_response
from .verified_execution import VerifiedExecution, VerifiedExecutionError


class SimulatedRunError(ValueError):
    pass


class SimulatedInterrupt(RuntimeError):
    """Test-only interruption at a named durable boundary."""


_CONFIG_KEYS = {"schema_version", "task", "experiment", "inputs", "database", "artifacts",
                "scope", "cap", "reserve_amount", "response_mode"}


def _load_json(path):
    data = Path(path).read_bytes()
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SimulatedRunError(f"invalid UTF-8 JSON: {path}") from exc
    return value, data


def _load(config_path):
    config, config_bytes = _load_json(config_path)
    if not isinstance(config, dict) or set(config) != _CONFIG_KEYS or config.get("schema_version") != 1:
        raise SimulatedRunError("simulation config must use the exact v1 fields")
    for key in ("task", "experiment", "inputs", "database", "artifacts"):
        if not isinstance(config[key], str) or not Path(config[key]).is_absolute():
            raise SimulatedRunError(f"{key} must be an absolute path")
    if not isinstance(config["scope"], str) or not config["scope"].startswith("synthetic:"):
        raise SimulatedRunError("scope must be explicitly synthetic")
    if (type(config["cap"]) is not int or config["cap"] < 1 or
            type(config["reserve_amount"]) is not int or not 0 < config["reserve_amount"] <= config["cap"]):
        raise SimulatedRunError("synthetic cap and per-request reserve must be positive integers")
    if config["response_mode"] not in ("first_label", "invalid", "missing"):
        raise SimulatedRunError("unsupported synthetic response mode")
    task, task_bytes = _load_json(config["task"])
    experiment, experiment_bytes = _load_json(config["experiment"])
    inputs, input_bytes = _load_json(config["inputs"])
    if len(experiment.get("configs", [])) != 1 or len(experiment.get("prompts", [])) != 1:
        raise SimulatedRunError("first offline simulation accepts one config and one prompt")
    plan = build_plan(task, experiment, inputs)
    adapter_sha = build_digest()
    parser_sha = adapter_sha  # One small fake module owns the parser and responder.
    binding = digest(canonical_bytes({"config": config, "config_bytes_sha256": digest(config_bytes),
                                      "task_sha256": digest(task_bytes),
                                      "experiment_sha256": digest(experiment_bytes),
                                      "inputs_sha256": digest(input_bytes),
                                      "adapter_sha256": adapter_sha}))
    return config, plan, binding, adapter_sha, parser_sha


def _bind(verified, binding):
    with verified.execution.coordinator._transaction() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS simulated_run_binding (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), config_sha256 TEXT NOT NULL)""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS simulated_run_binding_no_update
            BEFORE UPDATE ON simulated_run_binding BEGIN
            SELECT RAISE(ABORT, 'simulation binding is immutable'); END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS simulated_run_binding_no_delete
            BEFORE DELETE ON simulated_run_binding BEGIN
            SELECT RAISE(ABORT, 'simulation binding is immutable'); END""")
        row = conn.execute("SELECT config_sha256 FROM simulated_run_binding WHERE singleton=1").fetchone()
        if row is None:
            if conn.execute("SELECT COUNT(*) FROM execution_requests").fetchone()[0]:
                raise SimulatedRunError("database already contains unrelated execution requests")
            conn.execute("INSERT INTO simulated_run_binding VALUES (1,?)", (binding,))
        elif row[0] != binding:
            raise SimulatedRunError("simulation configuration changed for this database")


def _materials(config, plan, binding, adapter_sha, parser_sha):
    one_config = plan["experiment"]["configs"][0]
    prompt = plan["experiment"]["prompts"][0]
    for ordinal, request in enumerate(plan["requests"], 1):
        request_bytes = render_request(plan, request, one_config, prompt,
                                       mode=config["response_mode"])
        manifest_bytes = build_manifest(plan, request, one_config, prompt, request_bytes,
                                        config_digest=binding, adapter_digest=adapter_sha,
                                        parser_digest=parser_sha, scope=config["scope"], ordinal=ordinal)
        validate_manifest(manifest_bytes, request_bytes, plan, request, one_config, prompt,
                          config_digest=binding, adapter_digest=adapter_sha,
                          parser_digest=parser_sha, scope=config["scope"], ordinal=ordinal)
        yield request, manifest_bytes, request_bytes


def _ref(data):
    sha = digest(data)
    return ArtifactRef(1, sha, len(data), "application/json", f"objects/{sha[:2]}/{sha}")


def _verify_saved_inputs(verified, request_id, manifest_bytes, request_bytes):
    state = verified.execution.get(request_id)["execution"]
    manifest_ref, request_ref = _ref(manifest_bytes), _ref(request_bytes)
    if (state["manifest_digest"], state["input_digest"]) != (
            manifest_ref.sha256, request_ref.sha256):
        raise SimulatedRunError("enrolled request or manifest bytes changed")
    if (read_artifact(verified.artifact_root, manifest_ref) != manifest_bytes or
            read_artifact(verified.artifact_root, request_ref) != request_bytes):
        raise SimulatedRunError("stored request or manifest bytes changed")
    return {"manifest_ref": manifest_ref, "request_ref": request_ref}


def _verified_terminal_response(verified, request_id, state):
    row, execution = state["request"], state["execution"]
    receipt = verified.receipt_for(request_id)
    if receipt is None:
        raise SimulatedRunError("terminal response has no indexed receipt")
    response_ref = verified._verify_receipt(request_id, execution["admission_token"], receipt)
    expected = ((row["evidence_id"], row["response_digest"])
                if row["state"] == "response_saved" else
                (row["reconciliation_id"], row["reconciliation_response_digest"]))
    if expected != (receipt.sha256, response_ref.sha256):
        raise SimulatedRunError("terminal event conflicts with verified receipt")
    return response_ref


def _fault(fault_after, point, request_id):
    if fault_after is not None:
        fault_after(point, request_id)


def _recovery_scan_bound(planned_requests):
    if type(planned_requests) is not int or planned_requests < 1:
        raise SimulatedRunError("planned request count must be positive")
    return max(10_000, 4 * planned_requests + 32)


def _sandbox_response(request_bytes, worker):
    handle, path = tempfile.mkstemp(prefix="classification-capsule-", dir="/private/tmp")
    try:
        with os.fdopen(handle, "wb") as target:
            target.write(request_bytes)
            target.flush()
            os.fsync(target.fileno())
        return worker.run(path, WORKER_SOURCE).stdout.strip()
    finally:
        os.unlink(path)


def simulate(config_path, *, fault_after=None, worker=None):
    """Run new synthetic requests; never redispatch an ambiguous attempt."""
    config, plan, binding, adapter_sha, parser_sha = _load(config_path)
    materials = list(_materials(config, plan, binding, adapter_sha, parser_sha))
    verified = VerifiedExecution(config["database"], config["artifacts"])
    _bind(verified, binding)
    BudgetLedger(config["database"]).create_scope(config["scope"], config["cap"],
                                                    "SYN", 1, "synthetic:offline-only")
    refs = {}
    for request, manifest_bytes, request_bytes in materials:
        request_id = request["request_id"]
        with verified.execution.coordinator._transaction() as conn:
            existing = conn.execute("SELECT 1 FROM requests WHERE request_id=?", (request_id,)).fetchone()
        if existing:
            refs[request_id] = _verify_saved_inputs(verified, request_id, manifest_bytes, request_bytes)
        else:
            refs[request_id] = verified.enqueue_bytes(request_id, config["scope"],
                                                      manifest_bytes, request_bytes)
    for request, _, _ in materials:
        state = verified.execution.get(request["request_id"])["request"]["state"]
        if state in ("dispatch_intent", "outcome_unknown"):
            return {"status": "recovery_required", "request_id": request["request_id"],
                    "state": state, "planned_requests": len(materials)}
    worker = worker or SandboxedPythonWorker()
    if any(verified.execution.get(request["request_id"])["request"]["state"] in ("ready", "claimed")
           for request, _, _ in materials):
        worker.probe()  # Fail before any new dispatch intent if this host cannot enforce isolation.
    completed = 0
    for request, _, request_bytes in materials:
        request_id = request["request_id"]
        state = verified.execution.get(request_id)
        outcome = state["request"]["state"]
        if outcome in ("response_saved", "reconciled", "not_sent"):
            if outcome == "response_saved" or (outcome == "reconciled" and
                    state["request"]["reconciliation_outcome"] == "response_saved"):
                _verified_terminal_response(verified, request_id, state)
            completed += 1
            continue
        claim = verified.execution.claim("offline-simulator", 60)
        if claim is None or claim["request_id"] != request_id:
            return {"status": "in_progress", "request_id": request_id,
                    "planned_requests": len(materials), "completed_requests": completed}
        token = claim["token"]
        _fault(fault_after, "claimed", request_id)
        saved = refs[request_id]
        verified.admit_verified(request_id, token, config["scope"], config["reserve_amount"],
                                saved["manifest_ref"], saved["request_ref"],
                                bound_source="synthetic:declared-zero-charge")
        _fault(fault_after, "dispatch_intent", request_id)
        response_bytes = _sandbox_response(request_bytes, worker)
        parse_response(response_bytes, request_id, {item["id"] for item in request["items"]})
        _fault(fault_after, "response_received", request_id)
        saved_response = verified.save_response(request_id, token, response_bytes,
                                                "application/json", "synthetic:local-worker")
        _fault(fault_after, "receipt_indexed", request_id)
        verified.recover_response(request_id, token, receipt_ref=saved_response["receipt_ref"],
                                  settlement_id=f"synthetic:{request_id}", charge=0,
                                  zero_charge_evidence="synthetic:local-worker-has-no-fee")
        completed += 1
    return {"status": "completed", "planned_requests": len(materials),
            "completed_requests": completed, "model_calls": 0}


def recover_saved(config_path, *, max_objects=None):
    """Explicitly discover saved fake receipts; never call the fake worker."""
    config, plan, binding, adapter_sha, parser_sha = _load(config_path)
    materials = list(_materials(config, plan, binding, adapter_sha, parser_sha))
    # This simulator publishes at most one request, manifest, response and
    # receipt per planned request. Keep the existing small-run floor, but do
    # not let it prevent recovery of a supported larger run.
    planned_bound = _recovery_scan_bound(len(materials))
    if max_objects is None:
        max_objects = planned_bound
    elif type(max_objects) is not int or max_objects < planned_bound:
        raise SimulatedRunError("recovery object bound must cover the declared run")
    verified = VerifiedExecution(config["database"], config["artifacts"])
    _bind(verified, binding)
    recovered = []
    unresolved = []
    for request, manifest_bytes, request_bytes in materials:
        request_id = request["request_id"]
        state = verified.execution.get(request_id)
        row = state["request"]
        _verify_saved_inputs(verified, request_id, manifest_bytes, request_bytes)
        if row["state"] not in ("dispatch_intent", "outcome_unknown"):
            continue
        token = state["execution"]["admission_token"]
        receipt = verified.discover_orphan_receipt(request_id, token, max_objects=max_objects)
        if receipt is None:
            unresolved.append(request_id)
            continue
        if row["state"] == "dispatch_intent":
            verified.recover_response(request_id, token, receipt_ref=receipt,
                                      settlement_id=f"synthetic:{request_id}", charge=0,
                                      zero_charge_evidence="synthetic:local-worker-has-no-fee")
        else:
            verified.recover_response(request_id, token, receipt_ref=receipt)
        recovered.append(request_id)
    return {"status": "recovery_required" if unresolved else "recovered",
            "recovered": recovered, "unresolved": unresolved, "model_calls": 0}


def export_saved_predictions(config_path):
    """Read verified terminal fake responses; never read reference labels."""
    config, plan, binding, adapter_sha, parser_sha = _load(config_path)
    materials = list(_materials(config, plan, binding, adapter_sha, parser_sha))
    verified = VerifiedExecution(config["database"], config["artifacts"])
    _bind(verified, binding)
    records = []
    for request, manifest_bytes, request_bytes in materials:
        request_id = request["request_id"]
        state = verified.execution.get(request_id)
        _verify_saved_inputs(verified, request_id, manifest_bytes, request_bytes)
        row = state["request"]
        if row["state"] != "response_saved" and not (
                row["state"] == "reconciled" and row["reconciliation_outcome"] == "response_saved"):
            continue  # Missing attempt remains absent in the evaluator denominator.
        response_ref = _verified_terminal_response(verified, request_id, state)
        response = parse_response(read_artifact(config["artifacts"], response_ref), request_id,
                                  {item["id"] for item in request["items"]})
        for item in response["predictions"]:
            records.append({"config_id": request["config_id"], "prompt_id": request["prompt_id"],
                            "repeat": request["repeat"], "id": item["id"],
                            "prediction": item["prediction"]})
    return {"records": records}
