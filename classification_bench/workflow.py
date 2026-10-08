"""Freeze one offline workflow into ordinary, unit-specific managed runs.

Preparation and loading validate selected documents and trusted adapter controls.
Neither operation opens reference labels, reads credentials, creates a ledger,
authorizes provider work, or invokes runtime preflight or dispatch.
"""

import copy
import json
import os
from pathlib import Path
import stat

from . import benchmark
from .core import ValidationError, build_plan, validate_experiment, validate_inputs, validate_task
from .manifest import canonical_bytes, digest


class WorkflowError(ValidationError):
    pass


_PHASES = ("smoke", "full")
_SCALES = {"USD": 1_000_000, "REQ": 1, "SYN": 1}
_SPEC_KEYS = {"schema_version", "name", "task", "experiment", "inputs", "budgets",
              "phases", "max_concurrency", "provider_limits", "authorization_source"}


def _object(value, keys, where, optional=()):
    if not isinstance(value, dict) or set(value) - set(keys) - set(optional) or set(keys) - set(value):
        raise WorkflowError(f"{where}: missing or unknown fields; expected {sorted(keys)}")


def _text(value, where):
    if not isinstance(value, str) or not value or value != value.strip():
        raise WorkflowError(f"{where}: expected a nonempty string without surrounding whitespace")
    return value


def _positive(value, where):
    if type(value) is not int or value < 1:
        raise WorkflowError(f"{where}: expected positive integer")


def _json(raw, where):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise WorkflowError(f"{where}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def invalid(value):
        raise WorkflowError(f"{where}: non-finite JSON number {value}")

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"{where}: expected UTF-8 JSON") from exc


def _units(value, where):
    if not isinstance(value, dict) or not value or set(value) - set(_SCALES):
        raise WorkflowError(f"{where}: expected USD, REQ or SYN cap mapping")
    for currency, cap in value.items():
        _positive(cap, f"{where}.{currency}")


def _validate_spec(spec):
    _object(spec, _SPEC_KEYS, "workflow specification")
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1:
        raise WorkflowError("workflow.schema_version: expected 1")
    for key in ("name", "task", "experiment", "inputs", "authorization_source"):
        _text(spec[key], f"workflow.{key}")
    _positive(spec["max_concurrency"], "workflow.max_concurrency")
    limits = spec["provider_limits"]
    if not isinstance(limits, dict) or not limits:
        raise WorkflowError("workflow.provider_limits: expected nonempty object")
    for provider, limit in limits.items():
        _text(provider, "workflow provider")
        _positive(limit, f"workflow.provider_limits.{provider}")
    _units(spec["budgets"], "workflow.budgets")
    _object(spec["phases"], _PHASES, "workflow.phases")
    for phase_name in _PHASES:
        phase = spec["phases"][phase_name]
        _object(phase, {"selection", "caps", "on_budget_exhausted"},
                f"workflow.phases.{phase_name}", optional={"repeats"})
        if "repeats" in phase:
            _positive(phase["repeats"], f"workflow.phases.{phase_name}.repeats")
        if phase["on_budget_exhausted"] not in ("pause", "stop"):
            raise WorkflowError(f"workflow.phases.{phase_name}.on_budget_exhausted: expected pause or stop")
        _units(phase["caps"], f"workflow.phases.{phase_name}.caps")
        if set(phase["caps"]) != set(spec["budgets"]):
            raise WorkflowError(f"workflow.phases.{phase_name}.caps: currencies must exactly match budgets")
    for currency, cap in spec["budgets"].items():
        if sum(spec["phases"][name]["caps"][currency] for name in _PHASES) > cap:
            raise WorkflowError(f"workflow.budgets.{currency}: smoke and full allocations exceed aggregate cap")


def _selection(selection, inputs, where):
    if not isinstance(selection, dict) or len(selection) != 1:
        raise WorkflowError(f"{where}: choose exactly one of all, first or ids")
    records = inputs["records"]
    if set(selection) == {"all"} and selection["all"] is True:
        return records
    if set(selection) == {"first"}:
        count = selection["first"]
        _positive(count, f"{where}.first")
        if count > len(records):
            raise WorkflowError(f"{where}.first: exceeds supplied input count")
        return records[:count]
    if set(selection) == {"ids"}:
        ids = selection["ids"]
        if not isinstance(ids, list) or not ids:
            raise WorkflowError(f"{where}.ids: expected nonempty ordered list")
        for rid in ids:
            _text(rid, f"{where}.ids")
        if len(ids) != len(set(ids)):
            raise WorkflowError(f"{where}.ids: duplicate input IDs")
        by_id = {item["id"]: item for item in records}
        if set(ids) - set(by_id):
            raise WorkflowError(f"{where}.ids: unknown input IDs")
        return [by_id[rid] for rid in ids]
    raise WorkflowError(f"{where}: choose all=true, a positive first count, or explicit ids")


def _groups(experiment, limits):
    groups = {}
    adapters = {}
    for config in experiment["configs"]:
        try:
            runtime = benchmark._runtime(config)
            adapter = runtime.create_adapter(benchmark._adapter_config(config))
            currency = "SYN" if runtime.offline else getattr(runtime, "accounting_currency", "USD")
            allowed_currencies = ("SYN",) if runtime.offline else ("USD", "REQ")
            if currency not in allowed_currencies:
                raise WorkflowError(f"unsupported runtime accounting unit {currency!r}")
            if not isinstance(adapter, benchmark.UnsupportedAdapter) and adapter.provider not in limits:
                raise WorkflowError(f"missing provider limit for {adapter.provider}")
        except Exception as exc:
            raise WorkflowError(f"configuration {config['id']!r}: {exc}") from exc
        groups.setdefault(currency, []).append(config)
        adapters[config["id"]] = adapter
    return groups, adapters


def _check_prepared(plan, currency, adapters):
    """Apply the runner's request-bound checks without credentials or source lookup."""
    prompts = {prompt["id"]: prompt for prompt in plan["experiment"]["prompts"]}
    for request in plan["requests"]:
        adapter = adapters[request["config_id"]]
        try:
            prepared = adapter.prepare(plan, request, prompts[request["prompt_id"]])
            if not isinstance(prepared.body, bytes) or prepared.request_id != request["request_id"]:
                raise WorkflowError("adapter prepared an unbound request")
            minimum = 0 if isinstance(adapter, benchmark.UnsupportedAdapter) else 1
            if type(prepared.reserve_microusd) is not int or prepared.reserve_microusd < minimum:
                raise WorkflowError("adapter supplied an invalid per-request bound")
            if currency == "REQ" and prepared.reserve_microusd != 1:
                raise WorkflowError("request-count admission must reserve exactly one request")
            if not isinstance(_json(prepared.body, "prepared request"), dict):
                raise WorkflowError("adapter request must be a JSON object")
        except Exception as exc:
            raise WorkflowError(f"configuration {request['config_id']!r}: invalid prepared request: {exc}") from exc


def _run_hash(config, config_raw, task_raw, experiment_raw, inputs_raw):
    return digest(canonical_bytes({"config": config, "config_bytes_sha256": digest(config_raw),
                                   "task_sha256": digest(task_raw),
                                   "experiment_sha256": digest(experiment_raw),
                                   "inputs_sha256": digest(inputs_raw)}))


def _build(spec_raw, source_raw, original_paths, root):
    """Reconstruct every immutable file and binding entirely from frozen bytes."""
    spec = _json(spec_raw, "workflow specification")
    _validate_spec(spec)
    task = validate_task(_json(source_raw["task"], "task"))
    experiment = validate_experiment(_json(source_raw["experiment"], "experiment"))
    inputs = validate_inputs(_json(source_raw["inputs"], "inputs"), task)
    groups, adapters = _groups(experiment, spec["provider_limits"])
    if set(groups) != set(spec["budgets"]):
        raise WorkflowError("workflow.budgets: currencies must exactly match trusted runtime accounting units")
    # Source locations are provenance, never a requirement to reopen originals.
    source_base = Path(original_paths["specification"]).parent
    for role in ("task", "experiment", "inputs"):
        expected = os.path.abspath(source_base / spec[role])
        if original_paths[role] != expected:
            raise WorkflowError(f"workflow source {role}: original path does not match specification")
    files = {"sources/specification.json": spec_raw}
    files.update({f"sources/{role}.json": raw for role, raw in source_raw.items()})
    absolute = lambda relative: str(root / relative)
    sources = {role: {"original_path": original_paths[role], "path": absolute(f"sources/{role}.json"),
                      "sha256": digest(files[f"sources/{role}.json"])}
               for role in ("specification", "task", "experiment", "inputs")}
    # Scope strings use source content, rather than operator-controlled names.
    scope_id = digest(canonical_bytes({"specification": digest(spec_raw),
                                      "sources": {role: digest(raw) for role, raw in source_raw.items()}}))
    database, artifacts = absolute("execution.sqlite"), absolute("artifacts")
    aggregates = {}
    for currency in sorted(groups):
        scope = ("synthetic:" if currency == "SYN" else "workflow:") + scope_id + ":" + currency
        relative = f"aggregates/{currency}.json"
        terms = {"schema_version": 1, "database": database, "scope": scope,
                 "cap": spec["budgets"][currency], "currency": currency, "scale": _SCALES[currency],
                 "authorization_source": spec["authorization_source"]}
        files[relative] = canonical_bytes(terms)
        aggregates[currency] = {"spec_path": absolute(relative), "spec_sha256": digest(files[relative]),
                                "scope": scope, "cap": terms["cap"], "currency": currency,
                                "scale": terms["scale"]}
    phases = {}
    for phase_name in _PHASES:
        selected = spec["phases"][phase_name]
        records = _selection(selected["selection"], inputs, f"workflow.phases.{phase_name}.selection")
        phase_inputs = {"records": records}
        phase_experiment = copy.deepcopy(experiment)
        phase_experiment["repeats"] = selected.get("repeats", experiment["repeats"])
        prefix = f"phases/{phase_name}"
        input_relative, experiment_relative, plan_relative = (f"{prefix}/{name}.json"
                                                              for name in ("inputs", "experiment", "plan"))
        files[input_relative] = canonical_bytes(phase_inputs)
        files[experiment_relative] = canonical_bytes(phase_experiment)
        phase_plan = build_plan(task, phase_experiment, phase_inputs)
        files[plan_relative] = canonical_bytes(phase_plan)
        runs = []
        for currency in sorted(groups):
            group_experiment = {**phase_experiment, "configs": groups[currency]}
            group_relative = f"runs/{phase_name}-{currency}-experiment.json"
            config_relative = f"runs/{phase_name}-{currency}.json"
            group_raw = canonical_bytes(group_experiment)
            files[group_relative] = group_raw
            group_plan = build_plan(task, group_experiment, phase_inputs)
            _check_prepared(group_plan, currency, adapters)
            parent = aggregates[currency]["scope"]
            scope = parent + ":" + phase_name
            config = {"schema_version": 2, "task": sources["task"]["path"],
                      "experiment": absolute(group_relative), "inputs": absolute(input_relative),
                      "database": database, "artifacts": artifacts, "scope": scope,
                      "cap": selected["caps"][currency], "currency": currency, "scale": _SCALES[currency],
                      "max_concurrency": spec["max_concurrency"], "provider_limits": spec["provider_limits"],
                      "authorization_file": None if currency == "SYN" else
                      absolute(f"authorizations/{phase_name}-{currency}.json"),
                      "on_budget_exhausted": selected["on_budget_exhausted"],
                      "aggregate": {"parent_scope": parent, "allocation_id": scope + ":allocation",
                                    "phase": phase_name}}
            config_raw = canonical_bytes(config)
            files[config_relative] = config_raw
            runs.append({"config_path": absolute(config_relative), "config_sha256": digest(config_raw),
                         "experiment_path": absolute(group_relative), "experiment_sha256": digest(group_raw),
                         "currency": currency, "scale": _SCALES[currency], "scope": scope,
                         "run_sha256": _run_hash(config, config_raw, source_raw["task"], group_raw,
                                                 files[input_relative]),
                         "plan_sha256": digest(canonical_bytes(group_plan)),
                         "request_count": len(group_plan["requests"]),
                         "position_count": sum(len(request["items"]) for request in group_plan["requests"]),
                         "cap": config["cap"]})
        phases[phase_name] = {"task_path": sources["task"]["path"], "task_sha256": sources["task"]["sha256"],
                              "inputs_path": absolute(input_relative), "inputs_sha256": digest(files[input_relative]),
                              "experiment_path": absolute(experiment_relative),
                              "experiment_sha256": digest(files[experiment_relative]),
                              "plan_path": absolute(plan_relative), "plan_sha256": digest(files[plan_relative]),
                              "selection": selected["selection"], "ids": [record["id"] for record in records],
                              "repeats": phase_experiment["repeats"], "caps": selected["caps"],
                              "on_budget_exhausted": selected["on_budget_exhausted"],
                              "request_count": len(phase_plan["requests"]),
                              "position_count": sum(len(request["items"]) for request in phase_plan["requests"]),
                              "runs": runs}
    manifest = {"schema_version": 1, "kind": "classification_workflow", "name": spec["name"],
                "database": database, "artifacts": artifacts, "sources": sources,
                "max_concurrency": spec["max_concurrency"], "provider_limits": spec["provider_limits"],
                "aggregates": aggregates, "phases": phases,
                "files": [{"path": absolute(relative), "sha256": digest(raw)}
                          for relative, raw in sorted(files.items())]}
    manifest["workflow_sha256"] = digest(canonical_bytes(manifest))
    return files, manifest


def _write_private(path, raw):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def prepare(spec_path, directory):
    """Write a new private workflow; publish its manifest last and return it.

    Validation precedes directory creation. An I/O failure can retain an
    incomplete destination; load rejects it and callers choose a fresh path.
    """
    specification = Path(os.path.abspath(spec_path))
    spec_raw = specification.read_bytes()
    spec = _json(spec_raw, "workflow specification")
    _validate_spec(spec)
    originals = {"specification": str(specification)}
    originals.update({role: os.path.abspath(specification.parent / spec[role])
                      for role in ("task", "experiment", "inputs")})
    source_raw = {role: Path(originals[role]).read_bytes() for role in ("task", "experiment", "inputs")}
    destination = Path(directory).absolute()
    if destination.is_symlink():
        raise WorkflowError("workflow destination: symbolic links are not accepted")
    root = destination.resolve()
    files, manifest = _build(spec_raw, source_raw, originals, root)
    root.mkdir(mode=0o700)
    for relative, raw in sorted(files.items()):
        target = root / relative
        parent = root
        for part in Path(relative).parts[:-1]:
            parent = parent / part
            parent.mkdir(mode=0o700, exist_ok=True)
        _write_private(target, raw)
    _write_private(root / "workflow.json", canonical_bytes(manifest))
    return manifest


def _private(info, directory, where):
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise WorkflowError(f"{where}: expected private owned {'directory' if directory else 'regular file'}")


def _contained(root, value, *, must_exist=True, directory=False):
    _text(value, "workflow path")
    path = Path(value)
    if not path.is_absolute() or os.path.normpath(value) != value:
        raise WorkflowError("workflow path: expected normalized absolute contained path")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise WorkflowError("workflow path escapes the prepared directory") from exc
    if not relative.parts:
        raise WorkflowError("workflow file path cannot be the prepared directory")
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if must_exist:
                raise WorkflowError(f"frozen workflow: missing file {value!r}")
            break
        final = index == len(relative.parts) - 1
        _private(info, directory if final else True, "frozen workflow path")
    return path


def load(manifest_path):
    """Verify all frozen files, derived plans, grouping and bindings; never repair."""
    path = Path(manifest_path).absolute()
    if path.is_symlink() or path.parent.is_symlink():
        raise WorkflowError("frozen workflow: symbolic links are not accepted")
    root = path.parent.resolve()
    _private(root.lstat(), True, "frozen workflow")
    path = _contained(root, str(root / path.name))
    if path.name != "workflow.json":
        raise WorkflowError("frozen workflow: expected workflow.json manifest")
    manifest = _json(path.read_bytes(), "workflow manifest")
    if not isinstance(manifest, dict) or "workflow_sha256" not in manifest:
        raise WorkflowError("workflow manifest: missing identity")
    identity = manifest["workflow_sha256"]
    if not isinstance(identity, str) or identity != digest(canonical_bytes(
            {key: value for key, value in manifest.items() if key != "workflow_sha256"})):
        raise WorkflowError("workflow manifest: workflow identity mismatch")
    _object(manifest, {"schema_version", "kind", "name", "workflow_sha256", "database", "artifacts",
                       "sources", "max_concurrency", "provider_limits", "aggregates", "phases", "files"},
            "workflow manifest")
    _object(manifest["sources"], {"specification", "task", "experiment", "inputs"}, "workflow sources")
    originals = {}
    for role, source in manifest["sources"].items():
        _object(source, {"original_path", "path", "sha256"}, f"workflow source {role}")
        original = _text(source["original_path"], f"workflow source {role}.original_path")
        if not Path(original).is_absolute() or os.path.normpath(original) != original:
            raise WorkflowError("workflow original source path must be normalized and absolute")
        originals[role] = original
    if not isinstance(manifest["files"], list) or not manifest["files"]:
        raise WorkflowError("workflow.files: expected nonempty file list")
    contents = {}
    for entry in manifest["files"]:
        _object(entry, {"path", "sha256"}, "workflow file")
        file_path = _contained(root, entry["path"])
        relative = str(file_path.relative_to(root))
        if relative in contents or relative == "workflow.json":
            raise WorkflowError("workflow.files: duplicate or invalid file path")
        raw = file_path.read_bytes()
        if digest(raw) != entry["sha256"]:
            raise WorkflowError(f"frozen workflow: hash mismatch for {relative!r}")
        contents[relative] = raw
    for role, source in manifest["sources"].items():
        source_path = _contained(root, source["path"])
        relative = str(source_path.relative_to(root))
        if relative not in contents or digest(contents[relative]) != source["sha256"]:
            raise WorkflowError(f"workflow source {role}: invalid hash binding")
        if relative != f"sources/{role}.json":
            raise WorkflowError(f"workflow source {role}: invalid frozen path")
    spec_raw = contents["sources/specification.json"]
    source_raw = {role: contents[f"sources/{role}.json"] for role in ("task", "experiment", "inputs")}
    files, expected = _build(spec_raw, source_raw, originals, root)
    if files != contents or expected != manifest:
        raise WorkflowError("frozen workflow: source, derived files or manifest bindings do not match preparation")
    _contained(root, manifest["database"], must_exist=False)
    _contained(root, manifest["artifacts"], must_exist=False, directory=True)
    for phase in manifest["phases"].values():
        for run in phase["runs"]:
            config = _json(contents[str(Path(run["config_path"]).relative_to(root))], "run config")
            if config["authorization_file"] is not None:
                _contained(root, config["authorization_file"], must_exist=False)
    # Runtime files can grow independently; immutable subtrees must stay exact.
    actual = set()
    for subtree in ("sources", "phases", "runs", "aggregates"):
        folder = root / subtree
        for child in folder.rglob("*"):
            info = child.lstat()
            _private(info, stat.S_ISDIR(info.st_mode), "frozen workflow entry")
            if not stat.S_ISDIR(info.st_mode):
                actual.add(str(child.relative_to(root)))
    if actual != set(files):
        raise WorkflowError("frozen workflow: unexpected immutable files")
    return manifest
