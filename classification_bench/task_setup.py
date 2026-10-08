"""Private, deterministic imports into the existing benchmark file contracts.

This module reads user-selected files and never dispatches inference. Source
bytes and reference notes are frozen separately from the inference documents.
"""

import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path

from .core import ValidationError, validate_experiment, validate_inputs, validate_task


def _json_bytes(value):
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                           allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("setup: expected JSON-compatible values") from exc


def _sha256(content):
    return hashlib.sha256(content).hexdigest()


def _object(value, allowed, required, where):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValidationError(f"{where}: expected keys {sorted(required)}, allowed {sorted(allowed)}")


def _string(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{where}: expected nonempty string")
    return value


def _selector(value, where):
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{where}: expected a nonempty list of field names")
    for key in value:
        _string(key, where)
    return value


def _source(value, where):
    _object(value, {"path", "format", "records_path"}, {"path", "format"}, where)
    _string(value["path"], f"{where}.path")
    if value["format"] not in ("json", "jsonl", "csv"):
        raise ValidationError(f"{where}.format: expected json, jsonl or csv")
    if "records_path" in value:
        _selector(value["records_path"], f"{where}.records_path")
        if value["format"] != "json":
            raise ValidationError(f"{where}.records_path: supported only for JSON")


def _mapping(value, task, source, where, reference=False):
    allowed = {"id", "labels", "notes"} if reference else {"id", "inputs", "split"}
    required = {"id", "labels"} if reference else {"id", "inputs"}
    _object(value, allowed, required, where)
    _selector(value["id"], f"{where}.id")
    key = "labels" if reference else "inputs"
    names = [field["name"] for field in task["fields"]] if reference else task["input_keys"]
    _object(value[key], names, names, f"{where}.{key}")
    selectors = [value["id"]]
    for name, selector in value[key].items():
        selectors.append(_selector(selector, f"{where}.{key}.{name}"))
    for optional in ("notes",) if reference else ("split",):
        if optional in value:
            selectors.append(_selector(value[optional], f"{where}.{optional}"))
    if source["format"] == "csv" and any(len(selector) != 1 for selector in selectors):
        raise ValidationError(f"{where}: CSV selectors must name exactly one column")


def validate_specification(specification):
    """Validate setup structure without reading any source or instruction file."""
    spec = specification
    _object(spec, {"schema_version", "task", "source", "mapping", "references", "instructions",
                   "prompts", "configs", "repeats", "batch_size", "splits"},
            {"schema_version", "task", "source", "mapping", "prompts", "configs", "repeats",
             "batch_size"}, "setup")
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1:
        raise ValidationError("setup.schema_version: expected 1")
    validate_task(spec["task"])
    _source(spec["source"], "setup.source")
    _mapping(spec["mapping"], spec["task"], spec["source"], "setup.mapping")
    if "references" in spec:
        _object(spec["references"], {"source", "mapping"}, {"source", "mapping"}, "setup.references")
        _source(spec["references"]["source"], "setup.references.source")
        _mapping(spec["references"]["mapping"], spec["task"], spec["references"]["source"],
                 "setup.references.mapping", reference=True)
        # A combined source is supported, but the same source selector cannot
        # supply both a reference/notes value and an inference input value.
        if spec["source"] == spec["references"]["source"]:
            private = list(spec["references"]["mapping"]["labels"].values())
            if "notes" in spec["references"]["mapping"]:
                private.append(spec["references"]["mapping"]["notes"])
            public = spec["mapping"]["inputs"].values()
            if {tuple(s) for s in private} & {tuple(s) for s in public}:
                raise ValidationError("setup.mapping: reference or notes selector overlaps an input")
    if "instructions" in spec:
        _object(spec["instructions"], {"rubric", "sop"}, set(), "setup.instructions")
        for name, path in spec["instructions"].items():
            _string(path, f"setup.instructions.{name}")
    if not isinstance(spec["prompts"], list) or not spec["prompts"]:
        raise ValidationError("setup.prompts: expected a nonempty list")
    for prompt in spec["prompts"]:
        _object(prompt, {"id", "path"}, {"id", "path"}, "setup prompt")
        _string(prompt["id"], "setup prompt.id")
        _string(prompt["path"], "setup prompt.path")
    validate_experiment({"configs": spec["configs"],
                         "prompts": [{"id": p["id"], "text": "validated file content later"}
                                     for p in spec["prompts"]],
                         "repeats": spec["repeats"], "batch_size": spec["batch_size"]})
    if "splits" in spec:
        if "split" in spec["mapping"]:
            raise ValidationError("setup.splits: choose explicit memberships or a source split selector")
        if not isinstance(spec["splits"], dict) or not spec["splits"]:
            raise ValidationError("setup.splits: expected a nonempty object")
        for name, ids in spec["splits"].items():
            _string(name, "setup split name")
            if not isinstance(ids, list) or not ids:
                raise ValidationError("setup split IDs: expected a nonempty list")
            for rid in ids:
                _string(rid, "setup split ID")
    _json_bytes(spec)
    return spec


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"JSON: duplicate object key {key!r}")
        result[key] = value
    return result


def _read_json(content, where):
    def invalid_constant(value):
        raise ValidationError(f"{where}: nonfinite JSON value {value}")
    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{where}: malformed UTF-8 JSON: {exc}") from exc


def read_specification(path):
    """Read strict setup JSON, rejecting duplicate keys before initialization."""
    return validate_specification(_read_json(Path(path).read_bytes(), "setup"))


def _select(record, selector, where, optional=False):
    value = record
    for key in selector:
        if not isinstance(value, dict):
            if optional and value is None:
                return None
            raise ValidationError(f"{where}: source selector {selector!r} crosses a non-object value")
        if key not in value:
            if optional:
                return None
            raise ValidationError(f"{where}: missing source field {selector!r}")
        value = value[key]
    return value


def _records(content, source, where, allow_empty=False):
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{where}: expected UTF-8") from exc
    if source["format"] == "json":
        document = _read_json(content, where)
        if "records_path" in source:
            records = _select(document, source["records_path"], where)
        elif isinstance(document, dict) and "records" in document:
            records = document["records"]
        else:
            records = document
    elif source["format"] == "jsonl":
        records = []
        lines = text.split("\n")
        if lines[-1] == "":
            lines.pop()
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                raise ValidationError(f"{where}: blank JSONL line {line_number}")
            records.append(_read_json(line.encode("utf-8"), f"{where} line {line_number}"))
    else:
        try:
            reader = csv.reader(io.StringIO(text, newline=""), strict=True)
            header = next(reader, None)
            if not header or any(not h.strip() for h in header) or len(header) != len(set(header)):
                raise ValidationError(f"{where}: CSV requires unique nonempty header names")
            records = []
            for row in reader:
                if len(row) != len(header):
                    raise ValidationError(f"{where}: CSV row {reader.line_num} has wrong column count")
                records.append(dict(zip(header, row)))
        except csv.Error as exc:
            raise ValidationError(f"{where}: malformed CSV: {exc}") from exc
    if not isinstance(records, list) or (not records and not allow_empty):
        raise ValidationError(f"{where}: expected {'possibly empty' if allow_empty else 'nonempty'} record list")
    if any(not isinstance(record, dict) for record in records):
        raise ValidationError(f"{where}: each record must be an object")
    return records


def _absolute(path, base):
    target = Path(path)
    # Lexical normalization makes validation independent of later symlink or
    # existence changes at the original selected paths.
    return os.path.abspath(target if target.is_absolute() else base / target)


def _normalized_specification(specification, base):
    result = copy.deepcopy(validate_specification(specification))
    result["source"]["path"] = _absolute(result["source"]["path"], base)
    if "references" in result:
        result["references"]["source"]["path"] = _absolute(result["references"]["source"]["path"], base)
    for key, value in result.get("instructions", {}).items():
        result["instructions"][key] = _absolute(value, base)
    for prompt in result["prompts"]:
        prompt["path"] = _absolute(prompt["path"], base)
    validate_specification(result)
    return result


def _write_private(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(content)


def initialize_task(directory, specification, *, base_directory=None):
    """Create a private setup.json in a fresh directory; never infer task policy.

    Relative selected paths are resolved against base_directory (or the current
    directory). All task names, vocabulary and prompt files are supplied by the
    caller. File content is validated during import, not during initialization.
    """
    base = Path(base_directory or Path.cwd()).resolve()
    spec = _normalized_specification(specification, base)
    destination = Path(directory).absolute()
    destination.mkdir(mode=0o700)
    _write_private(destination / "setup.json", _json_bytes(spec))
    return {"setup": str(destination / "setup.json"), "source_files_read": 0}


def _prepare(specification, base, read_asset):
    spec = _normalized_specification(specification, base)
    assets = {}
    files = {}

    def asset(role, path, frozen_path):
        content = read_asset(role, path)
        if not isinstance(content, bytes):
            raise ValidationError(f"{role}: expected file bytes")
        assets[role] = {"original_path": path, "path": frozen_path, "sha256": _sha256(content)}
        files[frozen_path] = content
        return content

    source_bytes = asset("inputs_source", spec["source"]["path"],
                         "provenance/inputs-source." + spec["source"]["format"])
    source_records = _records(source_bytes, spec["source"], "inputs source")
    mapping = spec["mapping"]
    inputs = {"records": []}
    split_assignments = {}
    for index, record in enumerate(source_records, 1):
        rid = _string(_select(record, mapping["id"], f"input row {index}"), f"input row {index} ID")
        values = {key: _select(record, selector, f"input {rid}")
                  for key, selector in mapping["inputs"].items()}
        inputs["records"].append({"id": rid, "input": values})
        if "split" in mapping:
            split_assignments[rid] = _string(_select(record, mapping["split"], f"input {rid}"),
                                              f"input {rid} split")
    validate_inputs(inputs, spec["task"])
    ids = [record["id"] for record in inputs["records"]]
    id_set = set(ids)
    labels = {}
    notes = []
    if "references" in spec:
        ref = spec["references"]
        ref_bytes = asset("references_source", ref["source"]["path"],
                          "provenance/references-source." + ref["source"]["format"])
        if (source_bytes == ref_bytes and spec["source"]["format"] == ref["source"]["format"]
                and spec["source"].get("records_path") == ref["source"].get("records_path")):
            private = list(ref["mapping"]["labels"].values())
            if "notes" in ref["mapping"]:
                private.append(ref["mapping"]["notes"])
            if {tuple(s) for s in private} & {tuple(s) for s in mapping["inputs"].values()}:
                raise ValidationError("setup.mapping: reference or notes selector overlaps an input")
        reference_records = _records(ref_bytes, ref["source"], "references source", allow_empty=True)
        fields = {f["name"]: set(f["labels"]) for f in spec["task"]["fields"]}
        for index, record in enumerate(reference_records, 1):
            rid = _string(_select(record, ref["mapping"]["id"], f"reference row {index}"),
                          f"reference row {index} ID")
            if rid not in id_set:
                raise ValidationError(f"references: unknown input ID {rid!r}")
            if rid in labels:
                raise ValidationError(f"references: duplicate ID {rid!r}")
            labels[rid] = {}
            for name, selector in ref["mapping"]["labels"].items():
                value = _select(record, selector, f"reference {rid}", optional=True)
                missing = value is None or (ref["source"]["format"] == "csv" and value == "")
                if not missing:
                    if not isinstance(value, str) or value not in fields[name]:
                        raise ValidationError(f"reference {rid}.{name}: unknown or non-string label")
                    labels[rid][name] = value
            if "notes" in ref["mapping"]:
                note = _select(record, ref["mapping"]["notes"], f"reference {rid} notes", optional=True)
                if note is not None:
                    if not isinstance(note, str):
                        raise ValidationError(f"reference {rid} notes: expected string")
                    notes.append({"id": rid, "note": note})
    field_names = [field["name"] for field in spec["task"]["fields"]]
    coverage = {"records": [{"id": rid, "missing_fields": [name for name in field_names
                                                              if name not in labels.get(rid, {})]}
                              for rid in ids]}
    complete = all(not record["missing_fields"] for record in coverage["records"])
    reference_status = "complete" if complete else "partial" if any(labels.values()) else "unlabeled"
    label_path = "references/labels.json" if complete else None
    projection_path = "references/partial-labels.json" if reference_status == "partial" else None
    if label_path or projection_path:
        files[label_path or projection_path] = _json_bytes({"records": [
            {"id": rid, "labels": labels[rid]} for rid in ids if labels.get(rid)]})
    files["references/coverage.json"] = _json_bytes(coverage)
    if notes:
        files["references/notes.json"] = _json_bytes({"records": notes})

    instruction_texts = []
    for name in ("rubric", "sop"):
        if name in spec.get("instructions", {}):
            content = asset(name, spec["instructions"][name], f"provenance/{name}.txt")
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValidationError(f"{name}: expected UTF-8") from exc
            _string(text, name)
            instruction_texts.append(text)
    prompts = []
    for index, prompt in enumerate(spec["prompts"], 1):
        content = asset(f"prompt:{prompt['id']}", prompt["path"], f"provenance/prompts/{index:04d}.txt")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"prompt {prompt['id']}: expected UTF-8") from exc
        _string(text, f"prompt {prompt['id']}")
        prompts.append({"id": prompt["id"], "text": "\n\n".join(instruction_texts + [text])})
    experiment = {"configs": spec["configs"], "prompts": prompts,
                  "repeats": spec["repeats"], "batch_size": spec["batch_size"]}
    validate_experiment(experiment)
    files["task.json"] = _json_bytes(spec["task"])
    files["inputs.json"] = _json_bytes(inputs)
    files["experiment.json"] = _json_bytes(experiment)

    if "splits" in spec:
        memberships = spec["splits"]
    elif "split" in mapping:
        memberships = {name: [rid for rid in ids if split_assignments[rid] == name]
                       for name in sorted(set(split_assignments.values()))}
    else:
        memberships = {"all": ids}
    membership_ids = [rid for group in memberships.values() for rid in group]
    if len(membership_ids) != len(set(membership_ids)) or set(membership_ids) != id_set:
        raise ValidationError("splits: IDs must partition all imported input IDs without duplicates")
    splits = []
    for index, name in enumerate(sorted(memberships), 1):
        members = set(memberships[name])
        selected = [r for r in inputs["records"] if r["id"] in members]
        split_inputs_path = f"splits/{index:04d}/inputs.json"
        files[split_inputs_path] = _json_bytes({"records": selected})
        split_labels_path = None
        if all(not r["missing_fields"] for r in coverage["records"] if r["id"] in members):
            split_labels_path = f"references/splits/{index:04d}/labels.json"
            files[split_labels_path] = _json_bytes({"records": [
                {"id": r["id"], "labels": labels[r["id"]]} for r in selected]})
        splits.append({"name": name, "ids": [r["id"] for r in selected],
                       "inputs": split_inputs_path, "labels": split_labels_path})
    files["splits.json"] = _json_bytes({"schema_version": 1, "splits": splits})
    summary = {"task_name": spec["task"]["name"], "record_count": len(ids),
               "reference_status": reference_status, "labels": label_path,
               "reference_projection": projection_path,
               "missing_reference_fields": sum(len(r["missing_fields"]) for r in coverage["records"]),
               "prompt_count": len(prompts), "split_count": len(splits)}
    return files, assets, summary


def import_task(specification_path, directory):
    """Validate and freeze a setup into a fresh private directory.

    The manifest is published last. An I/O failure can leave an incomplete
    directory; validation rejects it and the caller chooses a fresh destination.
    """
    source_path = Path(specification_path).resolve()
    source_bytes = source_path.read_bytes()
    spec = _read_json(source_bytes, "setup")
    base = source_path.parent
    files, assets, summary = _prepare(spec, base, lambda role, path: Path(path).read_bytes())
    files["provenance/setup.json"] = source_bytes
    manifest = {"schema_version": 1, "source_base": str(base), "assets": assets,
                "files": [{"path": path, "sha256": _sha256(content)}
                          for path, content in sorted(files.items())], "summary": summary}
    destination = Path(directory).absolute()
    destination.mkdir(mode=0o700)
    for path, content in sorted(files.items()):
        target = destination / path
        parent = destination
        for part in Path(path).parts[:-1]:
            parent = parent / part
            parent.mkdir(mode=0o700, exist_ok=True)
        _write_private(target, content)
    _write_private(destination / "setup-manifest.json", _json_bytes(manifest))
    return {"directory": str(destination), "manifest": str(destination / "setup-manifest.json"),
            **summary}


def _contained_file(directory, relative):
    if not isinstance(relative, str):
        raise ValidationError("manifest file path: expected string")
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(part in ("..", ".") for part in path.parts):
        raise ValidationError("manifest file path: expected contained relative path")
    target = directory
    for part in path.parts:
        target = target / part
        if target.is_symlink():
            raise ValidationError("frozen setup: symbolic links are not accepted")
    if not target.is_file():
        raise ValidationError(f"frozen setup: missing file {relative!r}")
    return target


def validate_setup(directory):
    """Verify frozen bytes and reconstruct the import without opening originals."""
    root = Path(directory).absolute()
    if root.is_symlink():
        raise ValidationError("frozen setup: symbolic link directory is not accepted")
    manifest = _read_json(_contained_file(root, "setup-manifest.json").read_bytes(), "manifest")
    _object(manifest, {"schema_version", "source_base", "assets", "files", "summary"},
            {"schema_version", "source_base", "assets", "files", "summary"}, "manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValidationError("manifest.schema_version: expected 1")
    _string(manifest["source_base"], "manifest.source_base")
    if not Path(manifest["source_base"]).is_absolute():
        raise ValidationError("manifest.source_base: expected absolute path")
    if not isinstance(manifest["files"], list) or not manifest["files"]:
        raise ValidationError("manifest.files: expected nonempty list")
    contents = {}
    for entry in manifest["files"]:
        _object(entry, {"path", "sha256"}, {"path", "sha256"}, "manifest file")
        path = entry["path"]
        if not isinstance(path, str) or path in contents or path == "setup-manifest.json":
            raise ValidationError("manifest.files: duplicate or invalid path")
        content = _contained_file(root, path).read_bytes()
        if _sha256(content) != entry["sha256"]:
            raise ValidationError(f"frozen setup: hash mismatch for {path!r}")
        contents[path] = content
    if not isinstance(manifest["assets"], dict):
        raise ValidationError("manifest.assets: expected object")
    for role, asset in manifest["assets"].items():
        _object(asset, {"original_path", "path", "sha256"}, {"original_path", "path", "sha256"},
                f"manifest asset {role}")
        if asset["path"] not in contents or _sha256(contents[asset["path"]]) != asset["sha256"]:
            raise ValidationError(f"manifest asset {role}: invalid binding")
    if "provenance/setup.json" not in contents:
        raise ValidationError("frozen setup: missing setup specification")
    spec = _read_json(contents["provenance/setup.json"], "frozen setup")

    def read_asset(role, path):
        if role not in manifest["assets"]:
            raise ValidationError(f"frozen setup: missing asset {role}")
        return contents[manifest["assets"][role]["path"]]

    expected_files, expected_assets, summary = _prepare(spec, Path(manifest["source_base"]), read_asset)
    expected_files["provenance/setup.json"] = contents["provenance/setup.json"]
    if expected_files != contents or expected_assets != manifest["assets"] or summary != manifest["summary"]:
        raise ValidationError("frozen setup: manifest or derived documents do not match the import")
    actual_files = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    if actual_files != set(expected_files) | {"setup-manifest.json"}:
        raise ValidationError("frozen setup: unexpected files")
    return {"valid": True, "directory": str(root), **summary}
