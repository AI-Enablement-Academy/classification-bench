"""Deterministic planning and offline scoring; no model or network integration."""

import hashlib
import json
from collections import Counter


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


def validate_experiment(experiment):
    _object(experiment, {"configs", "prompts", "repeats", "batch_size"},
            {"configs", "prompts", "repeats", "batch_size"}, "experiment")
    for key in ("repeats", "batch_size"):
        if type(experiment[key]) is not int or experiment[key] < 1:
            raise ValidationError(f"experiment.{key}: expected positive integer")
    configs = _list(experiment["configs"], "experiment.configs")
    prompts = _list(experiment["prompts"], "experiment.prompts")
    for config in configs:
        _object(config, {"id", "model", "settings"}, {"id", "model"}, "config")
        _id(config["id"], "config.id")
        _id(config["model"], "config.model")
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


def evaluate(task, plan, labels, predictions):
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
    ids = {item["id"] for req in plan["requests"] for item in req["items"]}
    reference = _validate_labels(labels, task, ids)
    _object(predictions, {"records"}, {"records"}, "predictions")
    if not isinstance(predictions["records"], list):
        raise ValidationError("predictions.records: expected list")
    expected = {}
    for req in plan["requests"]:
        for item in req["items"]:
            key = (req["config_id"], req["prompt_id"], req["repeat"], item["id"])
            if key in expected:
                raise ValidationError("plan: duplicate prediction position")
            expected[key] = reference[item["id"]]
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
            invalid.append({"config_id": key[0], "prompt_id": key[1], "repeat": key[2], "id": key[3]})
        else:
            valid[key] = value
    results = []
    for config in experiment["configs"]:
        for prompt in experiment["prompts"]:
            passes = []
            for repeat in range(1, experiment["repeats"] + 1):
                positions = [(reference[rid], valid.get((config["id"], prompt["id"], repeat, rid)))
                             for rid in record_ids]
                passes.append({"repeat": repeat, **_metrics(positions, task["fields"]),
                               "missing": sum((config["id"], prompt["id"], repeat, rid) not in supplied for rid in record_ids),
                               "invalid": sum((config["id"], prompt["id"], repeat, rid) in supplied and
                                              (config["id"], prompt["id"], repeat, rid) not in valid for rid in record_ids)})
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
                            "pass_score_mean": sum(scores) / len(scores),
                            "pass_score_range": [min(scores), max(scores)],
                            "repeat_comparisons": comparisons})
    return {"schema_version": 1,
            "source_hashes": {"task": _digest(task), "plan": _digest(plan),
                              "labels": _digest(labels), "predictions": _digest(predictions)},
            "positions": len(expected), "missing": len(expected) - len(supplied),
            "invalid": invalid, "conditions": results}
