"""Deterministic planning and offline scoring; no model or network integration."""

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import urlsplit


class ValidationError(ValueError):
    pass


def _object(value, keys, required, where):
    if not isinstance(value, dict) or set(value) - set(keys) or set(required) - set(value):
        raise ValidationError(f"{where}: expected keys {sorted(required)}, allowed {sorted(keys)}")
    return value


def _list(value, where, minimum=1):
    if not isinstance(value, list) or len(value) < minimum:
        raise ValidationError(f"{where}: expected list with at least {minimum} item(s)")
    return value


def _id(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{where}: expected nonempty string")
    return value


def _unique(values, where):
    if len(values) != len(set(values)):
        raise ValidationError(f"{where}: duplicate IDs or names")


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_task(task):
    _object(task, {"name", "input_keys", "fields"}, {"name", "input_keys", "fields"}, "task")
    _id(task["name"], "task.name")
    keys = [_id(k, "input key") for k in _list(task["input_keys"], "task.input_keys")]
    _unique(keys, "input_keys")
    names = []
    for field in _list(task["fields"], "task.fields"):
        _object(field, {"name", "labels"}, {"name", "labels"}, "field")
        names.append(_id(field["name"], "field.name"))
        labels = [_id(x, "label") for x in _list(field["labels"], "field.labels", 2)]
        _unique(labels, f"labels for {field['name']}")
    _unique(names, "field names")
    return task


MODEL_METADATA_AXES = ("family", "declared_purpose", "training_lineage")


def validate_metadata_source_url(value):
    """Accept explicit HTTP(S) citations without userinfo or ambiguous URL bytes."""
    if (not isinstance(value, str) or not value or len(value) > 2048 or
            any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value):
        raise ValidationError("model metadata source: expected a bounded HTTP(S) URL")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in ("http", "https") and parsed.hostname and
                 parsed.username is None and parsed.password is None)
        parsed.port  # Reject malformed port declarations.
    except ValueError as exc:
        raise ValidationError("model metadata source: invalid URL") from exc
    if not valid:
        raise ValidationError("model metadata source: expected HTTP(S) without userinfo")
    return value


def validate_model_metadata(metadata):
    """Validate separate operator declarations without inferring model facts."""
    _object(metadata, {"schema_version", *MODEL_METADATA_AXES}, {"schema_version"}, "model_metadata")
    if type(metadata["schema_version"]) is not int or metadata["schema_version"] != 1:
        raise ValidationError("model_metadata: expected schema_version 1")
    for axis in MODEL_METADATA_AXES:
        if axis not in metadata:
            continue
        claim = metadata[axis]
        if isinstance(claim, dict) and claim.get("status") == "unknown":
            _object(claim, {"status"}, {"status"}, f"model_metadata.{axis}")
            continue
        required = {"value", "status", "provenance", "source_urls"}
        if isinstance(claim, dict) and claim.get("status") == "operator_verified":
            required.add("reviewed_at")
        _object(claim, required, required, f"model_metadata.{axis}")
        if claim["status"] not in ("operator_declared", "operator_verified"):
            raise ValidationError(f"model_metadata.{axis}: unsupported declaration status")
        for key in ("value", "provenance"):
            _id(claim[key], f"model_metadata.{axis}.{key}")
            if len(claim[key]) > 4000:
                raise ValidationError(f"model_metadata.{axis}.{key}: text exceeds 4000 characters")
        urls = _list(claim["source_urls"], f"model_metadata.{axis}.source_urls", minimum=0)
        if len(urls) > 20:
            raise ValidationError("model metadata: at most 20 source URLs per declaration")
        for url in urls:
            validate_metadata_source_url(url)
        _unique(urls, f"model_metadata.{axis}.source_urls")
        if (axis == "training_lineage" or claim["status"] == "operator_verified") and not urls:
            raise ValidationError(f"model_metadata.{axis}: source URL required for lineage/verified claims")
        if claim["status"] == "operator_verified":
            value = claim["reviewed_at"]
            try:
                reviewed = datetime.fromisoformat(value[:-1] + "+00:00") if isinstance(value, str) and value.endswith("Z") else None
            except ValueError as exc:
                raise ValidationError("model metadata reviewed_at: invalid UTC timestamp") from exc
            if reviewed is None or reviewed.tzinfo is None or reviewed.utcoffset() != timedelta(0):
                raise ValidationError("model metadata reviewed_at: expected an aware UTC timestamp")
    return metadata


def validate_experiment(experiment):
    _object(experiment, {"configs", "prompts", "repeats", "batch_size"},
            {"configs", "prompts", "repeats", "batch_size"}, "experiment")
    for key in ("repeats", "batch_size"):
        if type(experiment[key]) is not int or experiment[key] < 1:
            raise ValidationError(f"experiment.{key}: expected positive integer")
    configs = _list(experiment["configs"], "experiment.configs")
    prompts = _list(experiment["prompts"], "experiment.prompts")
    for config in configs:
        _object(config, {"id", "model", "model_type", "model_metadata", "settings"}, {"id", "model"}, "config")
        _id(config["id"], "config.id")
        _id(config["model"], "config.model")
        if "model_type" in config and config["model_type"] not in (
                "llm", "fine_tuned_llm", "decision"):
            raise ValidationError("config.model_type: expected llm, fine_tuned_llm or decision")
        if "model_metadata" in config:
            validate_model_metadata(config["model_metadata"])
        if "settings" in config and not isinstance(config["settings"], dict):
            raise ValidationError("config.settings: expected object")
        _digest(config)  # reject non-JSON values and NaN
    for prompt in prompts:
        _object(prompt, {"id", "text"}, {"id", "text"}, "prompt")
        _id(prompt["id"], "prompt.id")
        _id(prompt["text"], "prompt.text")
    _unique([c["id"] for c in configs], "config IDs")
    _unique([p["id"] for p in prompts], "prompt IDs")
    return experiment


def validate_inputs(inputs, task):
    validate_task(task)
    _object(inputs, {"records"}, {"records"}, "inputs")
    records = _list(inputs["records"], "inputs.records")
    for record in records:
        _object(record, {"id", "input"}, {"id", "input"}, "input record")
        _id(record["id"], "input record.id")
        _object(record["input"], task["input_keys"], task["input_keys"], "input capsule")
        if any(not isinstance(v, str) for v in record["input"].values()):
            raise ValidationError("input capsule values must be strings")
    _unique([r["id"] for r in records], "input record IDs")
    return inputs


def build_plan(task, experiment, inputs):
    validate_task(task)
    validate_experiment(experiment)
    validate_inputs(inputs, task)
    requests = []
    records = inputs["records"]
    for config in experiment["configs"]:
        for prompt in experiment["prompts"]:
            for repeat in range(1, experiment["repeats"] + 1):
                for batch_index, start in enumerate(range(0, len(records), experiment["batch_size"]), 1):
                    items = records[start:start + experiment["batch_size"]]
                    payload = {"task": task, "config": config, "prompt": prompt,
                               "repeat": repeat, "batch_index": batch_index, "items": items}
                    requests.append({"request_id": _digest(payload), "config_id": config["id"],
                                     "prompt_id": prompt["id"], "repeat": repeat,
                                     "batch_index": batch_index, "items": items})
    return {"schema_version": 1, "task": task, "experiment": experiment, "requests": requests}


def _validate_labels(labels, task, ids):
    _object(labels, {"records"}, {"records"}, "labels")
    records = _list(labels["records"], "labels.records")
    fields = {f["name"]: set(f["labels"]) for f in task["fields"]}
    result = {}
    for record in records:
        _object(record, {"id", "labels"}, {"id", "labels"}, "label record")
        rid = _id(record["id"], "label record.id")
        if rid in result:
            raise ValidationError("labels: duplicate ID")
        _object(record["labels"], fields, fields, f"labels for {rid}")
        if any(not isinstance(value, str) or value not in fields[name]
               for name, value in record["labels"].items()):
            raise ValidationError(f"labels for {rid}: unknown label")
        result[rid] = record["labels"]
    if set(result) != ids:
        raise ValidationError("labels: IDs must exactly match plan inputs")
    return result


def validate_reference_labels(labels, task, ids, *, allow_partial=False):
    """Return only known reference labels; None explicitly means unlabeled.

    A supplied incomplete document needs explicit opt-in. Unknown label values,
    unknown IDs and duplicate IDs remain errors in every mode.
    """
    validate_task(task)
    if type(allow_partial) is not bool:
        raise ValidationError("allow_partial: expected boolean")
    input_ids = list(ids)
    for rid in input_ids:
        _id(rid, "reference input ID")
    _unique(input_ids, "reference input IDs")
    id_set = set(input_ids)
    if labels is None:
        return {}
    if not allow_partial:
        return _validate_labels(labels, task, id_set)
    _object(labels, {"records"}, {"records"}, "labels")
    records = _list(labels["records"], "labels.records", minimum=0)
    fields = {f["name"]: set(f["labels"]) for f in task["fields"]}
    result = {}
    for record in records:
        _object(record, {"id", "labels"}, {"id", "labels"}, "label record")
        rid = _id(record["id"], "label record.id")
        if rid not in id_set:
            raise ValidationError(f"labels: unexpected input ID {rid}")
        if rid in result:
            raise ValidationError("labels: duplicate ID")
        _object(record["labels"], fields, set(), f"labels for {rid}")
        known = {}
        for name, value in record["labels"].items():
            if value is None:
                continue
            if not isinstance(value, str) or value not in fields[name]:
                raise ValidationError(f"labels for {rid}: unknown label")
            known[name] = value
        result[rid] = known
    return result


def _metrics(positions, fields):
    denominator = len(positions)
    exact = sum(pred == truth for truth, pred in positions if pred is not None)
    per_field = {}
    for field in fields:
        name = field["name"]
        labels = field["labels"]
        matrix = {actual: {predicted: 0 for predicted in labels} for actual in labels}
        missing = Counter()
        for truth, pred in positions:
            if pred is None:
                missing[truth[name]] += 1
            else:
                matrix[truth[name]][pred[name]] += 1
        per_label = {}
        for label in labels:
            tp = matrix[label][label]
            fp = sum(matrix[other][label] for other in labels if other != label)
            fn = missing[label] + sum(matrix[label][other] for other in labels if other != label)
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            per_label[label] = {"precision": precision, "recall": recall, "f1": f1,
                                "support": tp + fn, "tp": tp, "fp": fp, "fn": fn}
        per_field[name] = {"confusion": matrix, "unscored_by_true_label": dict(missing),
                           "labels": per_label,
                           "macro_f1": sum(x["f1"] for x in per_label.values()) / len(labels)}
    return {"denominator": denominator, "all_field_exact": exact,
            "all_field_exact_rate": exact / denominator if denominator else 0.0,
            "fields": per_field}


def _validated_plan(task, plan):
    validate_task(task)
    _object(plan, {"schema_version", "task", "experiment", "requests"},
            {"schema_version", "task", "experiment", "requests"}, "plan")
    if plan["schema_version"] != 1 or plan["task"] != task:
        raise ValidationError("plan: schema version or task mismatch")
    experiment = validate_experiment(plan["experiment"])
    _list(plan["requests"], "plan.requests")
    first = (experiment["configs"][0]["id"], experiment["prompts"][0]["id"])
    try:
        first_items = [item for req in plan["requests"]
                       if (req["config_id"], req["prompt_id"], req["repeat"]) == (*first, 1)
                       for item in req["items"]]
    except (KeyError, TypeError) as exc:
        raise ValidationError("plan: malformed request") from exc
    if not first_items or build_plan(task, experiment, {"records": first_items}) != plan:
        raise ValidationError("plan: requests or request IDs do not match canonical plan")
    record_ids = [item["id"] for item in first_items]
    positions = []
    for req in plan["requests"]:
        for item in req["items"]:
            key = (req["config_id"], req["prompt_id"], req["repeat"], item["id"])
            positions.append(key)
    if len(positions) != len(set(positions)):
        raise ValidationError("plan: duplicate prediction position")
    return record_ids, positions


def _validated_predictions(task, predictions, positions):
    _object(predictions, {"records"}, {"records"}, "predictions")
    if not isinstance(predictions["records"], list):
        raise ValidationError("predictions.records: expected list")
    expected = set(positions)
    supplied = {}
    for record in predictions["records"]:
        _object(record, {"config_id", "prompt_id", "repeat", "id", "prediction"},
                {"config_id", "prompt_id", "repeat", "id", "prediction"}, "prediction record")
        _id(record["config_id"], "prediction.config_id")
        _id(record["prompt_id"], "prediction.prompt_id")
        _id(record["id"], "prediction.id")
        if type(record["repeat"]) is not int or record["repeat"] < 1:
            raise ValidationError("prediction.repeat: expected positive integer")
        key = (record["config_id"], record["prompt_id"], record["repeat"], record["id"])
        if key not in expected:
            raise ValidationError(f"prediction: unexpected position {key}")
        if key in supplied:
            raise ValidationError(f"prediction: duplicate position {key}")
        supplied[key] = record["prediction"]
    allowed = {f["name"]: set(f["labels"]) for f in task["fields"]}
    valid = {}
    invalid = []
    for key, value in supplied.items():
        if not isinstance(value, dict) or set(value) != set(allowed) or any(
                not isinstance(v, str) or v not in allowed[k] for k, v in value.items()):
            invalid.append(key)
        else:
            valid[key] = value
    return {"supplied": supplied, "valid": valid, "invalid": invalid}


def validated_positions(task, plan, predictions):
    """Validate a canonical plan and return full membership and output states.

    Position keys are (config_id, prompt_id, repeat, case_id) tuples. Supplied
    values retain raw invalid predictions; valid contains only full allowed
    vectors. No reference labels are needed for this analysis boundary.
    """
    record_ids, positions = _validated_plan(task, plan)
    return {"record_ids": record_ids, "positions": positions,
            **_validated_predictions(task, predictions, positions)}


def _reference_coverage(record_ids, reference, fields):
    names = [field["name"] for field in fields]
    fully_labeled = [rid for rid in record_ids if len(reference.get(rid, {})) == len(names)]
    partial = [rid for rid in record_ids if 0 < len(reference.get(rid, {})) < len(names)]
    unlabeled = [rid for rid in record_ids if not reference.get(rid)]
    field_coverage = {}
    for name in names:
        known = [rid for rid in record_ids if name in reference.get(rid, {})]
        missing = [rid for rid in record_ids if name not in reference.get(rid, {})]
        field_coverage[name] = {"known_ids": known, "missing_ids": missing,
                                "reference_denominator": len(known), "reference_missing": len(missing),
                                "reference_coverage": len(known) / len(record_ids)}
    return {"status": "partial" if fully_labeled or partial else "unlabeled",
            "input_count": len(record_ids), "fully_labeled_ids": fully_labeled,
            "partially_labeled_ids": partial, "unlabeled_ids": unlabeled,
            "known_field_labels": sum(len(reference.get(rid, {})) for rid in record_ids),
            "expected_field_labels": len(record_ids) * len(names), "fields": field_coverage}


def _incomplete_metrics(positions, fields, coverage):
    complete_positions = [(truth, pred) for truth, pred in positions if len(truth) == len(fields)]
    subset = {"scope": "fully_labeled_records", "ids": coverage["fully_labeled_ids"],
              "denominator": len(complete_positions), "all_field_exact": None,
              "all_field_exact_rate": None}
    if complete_positions:
        metrics = _metrics(complete_positions, fields)
        subset.update(all_field_exact=metrics["all_field_exact"],
                      all_field_exact_rate=metrics["all_field_exact_rate"])
    per_field = {}
    for field in fields:
        name = field["name"]
        field_positions = [({name: truth[name]}, {name: pred[name]} if pred is not None else None)
                           for truth, pred in positions if name in truth]
        denominator = len(field_positions)
        if denominator:
            metrics = _metrics(field_positions, [field])
            stats = {**metrics["fields"][name], "correct": metrics["all_field_exact"],
                     "accuracy": metrics["all_field_exact_rate"]}
        else:
            stats = {"correct": None, "accuracy": None, "confusion": None,
                     "unscored_by_true_label": {}, "labels": None, "macro_f1": None}
        per_field[name] = {**stats, "reference_denominator": denominator,
                           "reference_missing": len(positions) - denominator,
                           "reference_coverage": denominator / len(positions)}
    return {"denominator": len(positions), "all_field_exact": None, "all_field_exact_rate": None,
            "scored_subset": subset, "fields": per_field, "reference_coverage": coverage}


def evaluate(task, plan, labels=None, predictions=None, *, allow_partial_references=False):
    """Score complete references, or explicitly analyze unavailable references.

    Complete-reference output remains schema 1. Schema 2 retains the full planned
    denominator and publishes only clearly scoped known-reference metrics.
    """
    if type(allow_partial_references) is not bool:
        raise ValidationError("allow_partial_references: expected boolean")
    record_ids, expected = _validated_plan(task, plan)
    reference = validate_reference_labels(labels, task, record_ids, allow_partial=allow_partial_references)
    output = _validated_predictions(task, predictions, expected)
    supplied, valid = output["supplied"], output["valid"]
    invalid = [{"config_id": key[0], "prompt_id": key[1], "repeat": key[2], "id": key[3]}
               for key in output["invalid"]]
    field_names = {field["name"] for field in task["fields"]}
    complete = set(reference) == set(record_ids) and all(set(reference[rid]) == field_names for rid in record_ids)
    coverage = None if complete else _reference_coverage(record_ids, reference, task["fields"])
    experiment = plan["experiment"]
    results = []
    for config in experiment["configs"]:
        for prompt in experiment["prompts"]:
            passes = []
            for repeat in range(1, experiment["repeats"] + 1):
                positions = [(reference.get(rid, {}), valid.get((config["id"], prompt["id"], repeat, rid)))
                             for rid in record_ids]
                metrics = (_metrics(positions, task["fields"]) if complete else
                           _incomplete_metrics(positions, task["fields"], coverage))
                passes.append({"repeat": repeat, **metrics,
                               "missing": sum((config["id"], prompt["id"], repeat, rid) not in supplied for rid in record_ids),
                               "invalid": sum((config["id"], prompt["id"], repeat, rid) in supplied and
                                              (config["id"], prompt["id"], repeat, rid) not in valid for rid in record_ids)})
                if not complete:
                    entry = passes[-1]
                    entry["valid"] = entry["denominator"] - entry["missing"] - entry["invalid"]
                    entry["valid_rate"] = entry["valid"] / entry["denominator"]
            comparisons = []
            for a in range(1, experiment["repeats"] + 1):
                for b in range(a + 1, experiment["repeats"] + 1):
                    pairs = [(rid, valid.get((config["id"], prompt["id"], a, rid)),
                              valid.get((config["id"], prompt["id"], b, rid))) for rid in record_ids]
                    comparable = [(rid, x, y) for rid, x, y in pairs if x is not None and y is not None]
                    excluded_ids = [rid for rid, x, y in pairs if x is None or y is None]
                    changed_ids = [rid for rid, x, y in comparable if x != y]
                    fields = {}
                    for field in task["fields"]:
                        name = field["name"]
                        field_changed = [rid for rid, x, y in comparable if x[name] != y[name]]
                        fields[name] = {"comparable": len(comparable), "excluded": len(excluded_ids),
                                        "changed_ids": field_changed, "excluded_ids": excluded_ids,
                                        "flips": len(field_changed),
                                        "flip_rate": len(field_changed) / len(comparable) if comparable else None}
                    comparisons.append({"repeat_a": a, "repeat_b": b, "comparable": len(comparable),
                                        "excluded": len(excluded_ids), "excluded_ids": excluded_ids,
                                        "changed_ids": changed_ids, "flips": len(changed_ids),
                                        "flip_rate": len(changed_ids) / len(comparable) if comparable else None,
                                        "fields": fields})
            scores = [p["all_field_exact_rate"] for p in passes]
            results.append({"config_id": config["id"], "prompt_id": prompt["id"], "passes": passes,
                            "pass_score_mean": sum(scores) / len(scores) if complete else None,
                            "pass_score_range": [min(scores), max(scores)] if complete else None,
                            "repeat_comparisons": comparisons})
            if not complete:
                subset_scores = [entry["scored_subset"]["all_field_exact_rate"] for entry in passes]
                available = bool(coverage["fully_labeled_ids"])
                results[-1]["scored_subset_score_mean"] = sum(subset_scores) / len(subset_scores) if available else None
                results[-1]["scored_subset_score_range"] = [min(subset_scores), max(subset_scores)] if available else None
    result = {"schema_version": 1 if complete else 2,
            "source_hashes": {"task": _digest(task), "plan": _digest(plan),
                              "labels": _digest(labels) if labels is not None else None,
                              "predictions": _digest(predictions)},
            "positions": len(expected), "missing": len(expected) - len(supplied),
            "invalid": invalid, "conditions": results}
    if not complete:
        result["reference_coverage"] = coverage
    from .evaluation_provenance import current_provenance, evaluation_identity
    result["evaluation_provenance"] = current_provenance()
    result["evaluation_id"] = evaluation_identity(result["source_hashes"], result["evaluation_provenance"])
    return result
