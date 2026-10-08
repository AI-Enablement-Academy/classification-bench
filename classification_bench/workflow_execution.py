"""Operator actions for frozen workflows; references remain offline-only."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from . import benchmark, workflow
from .manifest import canonical_bytes, digest


def _phases(manifest, phase, *, required=False):
    if phase is None and not required:
        return [name for name in ("smoke", "full") if name in manifest["phases"]]
    if phase not in ("smoke", "full"):
        raise workflow.WorkflowError("select --phase smoke or full for this workflow action")
    return [phase]


def _result(manifest, phases):
    return {"workflow_sha256": manifest["workflow_sha256"], "name": manifest["name"],
            "phases": phases}


def preview(path, *, phase=None):
    manifest = workflow.load(path)
    phases = {}
    for name in _phases(manifest, phase):
        entry = manifest["phases"][name]
        phases[name] = {"request_count": entry["request_count"],
                        "position_count": entry["position_count"], "caps": entry["caps"],
                        "on_budget_exhausted": entry["on_budget_exhausted"],
                        "runs": [{"config_path": run["config_path"],
                                  **benchmark.preview(run["config_path"])} for run in entry["runs"]]}
    return {**_result(manifest, phases), "dispatch_count": 0,
            "aggregates": manifest["aggregates"],
            "authorization_template": {name: authorization_template(manifest, name) for name in phases}}


def authorization_template(manifest, phase):
    """An unsigned preview, never persisted as authority by preparation."""
    entry = manifest["phases"][phase]
    return {"schema_version": 1, "workflow_sha256": manifest["workflow_sha256"],
            "phase": phase, "request_count": entry["request_count"], "caps": entry["caps"]}


def _write_once(path, raw):
    target = Path(path)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if target.is_symlink() or not target.is_file() or target.stat().st_mode & 0o077:
            raise workflow.WorkflowError("authorization must be a private regular file")
        if target.read_bytes() != raw:
            raise workflow.WorkflowError("saved authorization differs; existing authority is preserved")
    else:
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())


def _authorize(manifest, phase, authorization_path):
    live = [run for run in manifest["phases"][phase]["runs"] if run["currency"] != "SYN"]
    if not live:
        if authorization_path is not None:
            raise workflow.WorkflowError("synthetic workflow execution does not accept live authorization")
        return
    if authorization_path is None:
        raise workflow.WorkflowError("live workflow requires --authorization matching this exact phase and caps")
    approval, _ = benchmark._load_json(authorization_path)
    expected = authorization_template(manifest, phase)
    if canonical_bytes(approval) != canonical_bytes(expected):
        raise workflow.WorkflowError("authorization does not match the exact workflow, phase, request count and caps")
    directory = Path(manifest["database"]).parent / "authorizations"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o077:
        raise workflow.WorkflowError("authorization directory must be private and contained")
    # Retain the approved workflow record before deriving ordinary child records.
    _write_once(directory / f"{phase}-workflow.json", canonical_bytes(expected))
    for run in live:
        config, _ = benchmark._load_json(run["config_path"])
        child = {"schema_version": 1, "run_sha256": run["run_sha256"],
                 "plan_sha256": run["plan_sha256"], "request_count": run["request_count"],
                 "scope": run["scope"], "cap": run["cap"]}
        _write_once(config["authorization_file"], canonical_bytes(child))


def preflight(path, *, phase, api_key=None, worker=None):
    manifest = workflow.load(path)
    _phases(manifest, phase, required=True)
    checks = [{"config_path": run["config_path"],
               **benchmark.preflight(run["config_path"], api_key=api_key, worker=worker)}
              for run in manifest["phases"][phase]["runs"]]
    return {**_result(manifest, {phase: {"runs": checks}}),
            "ready": all(check["ready"] for check in checks), "dispatch_count": 0}


def run(path, *, phase, authorization_path=None, api_key=None, worker=None):
    manifest = workflow.load(path)
    _phases(manifest, phase, required=True)
    _authorize(manifest, phase, authorization_path)
    # Aggregate creation is local accounting only. All provider admission remains
    # inside run_groups, after it has validated every child configuration.
    for aggregate in manifest["aggregates"].values():
        benchmark.aggregate_budget(aggregate["spec_path"], create=True)
    results = benchmark.run_groups([item["config_path"] for item in manifest["phases"][phase]["runs"]],
                                   max_concurrency=manifest["max_concurrency"],
                                   provider_limits=manifest["provider_limits"], api_key=api_key, worker=worker)
    return _result(manifest, {phase: {"runs": results}})


def status(path, *, phase=None):
    manifest = workflow.load(path)
    parents, allocations = _initialized(manifest)
    phases = {name: {"runs": [{"config_path": run["config_path"],
                              **(benchmark.status(run["config_path"]) if run["currency"] in parents else
                                 {"status": "not_initialized", "budget": None,
                                  "states": {"never_sent": run["request_count"]}, "next_action": "run"})}
                              for run in manifest["phases"][name]["runs"]]}
              for name in _phases(manifest, phase)}
    aggregates = {unit: benchmark.aggregate_budget(item["spec_path"])["budget"] if unit in parents else None
                  for unit, item in manifest["aggregates"].items()} if Path(manifest["database"]).exists() else None
    return {**_result(manifest, phases), "aggregates": aggregates}


def _initialized(manifest):
    """Inspect incomplete startup without creating scopes or allocating capacity."""
    if not Path(manifest["database"]).exists():
        return set(), set()
    with closing(sqlite3.connect(Path(manifest["database"]).as_uri() + "?mode=ro", uri=True)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        parents = {row[0] for row in conn.execute("SELECT scope FROM aggregate_scopes")} if "aggregate_scopes" in tables else set()
        children = {row[0] for row in conn.execute("SELECT child_scope FROM aggregate_allocations")} if "aggregate_allocations" in tables else set()
    return {unit for unit, entry in manifest["aggregates"].items() if entry["scope"] in parents}, children


def recover(path, *, phase):
    manifest = workflow.load(path)
    _phases(manifest, phase, required=True)
    if not Path(manifest["database"]).exists():
        raise workflow.WorkflowError("workflow has no execution database to recover")
    with benchmark._runner_lock(manifest["database"]):
        _, allocated = _initialized(manifest)
        results = [{"config_path": run["config_path"],
                    **(benchmark._recover_unlocked(run["config_path"]) if run["scope"] in allocated else
                       {"status": "never_admitted", "recovered": [], "unresolved": []})}
                   for run in manifest["phases"][phase]["runs"]]
    return {**_result(manifest, {phase: {"runs": results}}), "dispatch_count": 0}


def report_snapshot(path, *, phase=None, require_current_evaluation=True):
    """Join exact unit-group coverage under one lock, before opening references."""
    manifest = workflow.load(path, require_current_evaluation=require_current_evaluation)
    phases = {}
    loaded = {}
    for name in _phases(manifest, phase):
        entry = manifest["phases"][name]
        plan, raw = benchmark._load_json(entry["plan_path"])
        if digest(raw) != entry["plan_sha256"]:
            raise workflow.WorkflowError("phase plan hash mismatch")
        groups = [benchmark._load(run["config_path"]) for run in entry["runs"]]
        planned = {item["request_id"]: item for item in plan["requests"]}
        joined = {}
        for _, group_plan, _, _, _ in groups:
            for request in group_plan["requests"]:
                request_id = request["request_id"]
                if request_id in joined or planned.get(request_id) != request:
                    raise workflow.WorkflowError("workflow group coverage is duplicated or mismatched")
                joined[request_id] = request
        if joined != planned:
            raise workflow.WorkflowError("workflow group coverage is incomplete")
        loaded[name] = (plan, groups)
    with benchmark._runner_lock(manifest["database"]):
        for name, (plan, groups) in loaded.items():
            operations = []
            for config, _, binding, materials, _ in groups:
                if Path(manifest["database"]).exists():
                    operations.extend(benchmark._export_operations_loaded(config, binding, materials))
                else:
                    for material in materials:
                        request = material["request"]
                        operations.append({"request_id": material.get("logical_request_id", request["request_id"]),
                                           "config_id": request["config_id"], "prompt_id": request["prompt_id"],
                                           "repeat": request["repeat"], "batch_index": request["batch_index"],
                                           "ids": [item["id"] for item in request["items"]],
                                           "state": "never_sent", "parsed_status": None, "predictions": [],
                                           "currency": config["currency"], "scale": config["scale"]})
            by_id = {item["request_id"]: item for item in operations}
            if len(by_id) != len(operations):
                raise workflow.WorkflowError("workflow operations contain duplicate requests")
            if Path(manifest["database"]).exists() and set(by_id) != {item["request_id"] for item in plan["requests"]}:
                raise workflow.WorkflowError("workflow operation coverage is incomplete")
            operations = [by_id[request["request_id"]] for request in plan["requests"] if request["request_id"] in by_id]
            phases[name] = {"task": plan["task"], "plan": plan, "operations": operations,
                            "predictions": benchmark._predictions_from_operations(operations)}
    return {"manifest": manifest, "phases": phases}


def export_predictions(path, *, phase):
    if phase not in ("smoke", "full"):
        raise workflow.WorkflowError("select --phase smoke or full for this workflow action")
    snapshot = report_snapshot(path, phase=phase, require_current_evaluation=False)
    return snapshot["phases"][phase]["predictions"]
