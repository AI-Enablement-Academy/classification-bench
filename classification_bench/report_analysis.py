"""Deterministic run/case comparisons over one validated categorical task.

Run identity binds requested task/configuration/prompt/repeat/input membership,
not predictions or corrected references. Evaluation identity binds all supplied
evidence. Pair counts use each run's full planned case denominator; different
pairs and repeated cases are never pooled as independent samples.
"""

from copy import deepcopy
from itertools import combinations

from .core import ValidationError, _digest, validated_positions, validate_reference_labels


AGREEMENT_RULE = "two_valid_full_vectors_equal"
EVIDENCE_FIELDS = ("response_sha256", "receipt_sha256", "adapter_source_sha256",
                   "runtime_source_sha256", "transport_source_sha256", "generation_response_sha256")


def _finite_hash(value, name):
    try:
        return _digest(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name}: expected finite JSON") from exc


def _operations(plan, operations):
    if operations is None:
        return {}
    if not isinstance(operations, list) or any(not isinstance(x, dict) for x in operations):
        raise ValidationError("operations: expected list of objects")
    planned = {r["request_id"]: r for r in plan["requests"]}
    result = {}
    for op in operations:
        rid = op.get("request_id")
        if not isinstance(rid, str) or rid not in planned or rid in result:
            raise ValidationError("operations: unexpected or duplicate request ID")
        request = planned[rid]
        for name in ("config_id", "prompt_id", "repeat", "batch_index"):
            if name in op and op[name] != request[name]:
                raise ValidationError("operation: request membership mismatch")
        if "ids" in op and op["ids"] != [x["id"] for x in request["items"]]:
            raise ValidationError("operation: case membership mismatch")
        for name in ("state", "parsed_status", "reason", "blocked_reason"):
            if op.get(name) is not None and not isinstance(op[name], str):
                raise ValidationError(f"operation: {name} must be a string or null")
        for name in EVIDENCE_FIELDS:
            value = op.get(name)
            if value is not None and not isinstance(value, str):
                raise ValidationError(f"operation: {name} must be a string or null")
        result[rid] = op
    return result


def _money(run_operations, planned_count, *, synthetic=False):
    measured, total, holds, synthetic_count, subscriptions, subscription_holds = 0, 0, 0, 0, 0, 0
    hold_coverage = subscription_coverage = subscription_hold_coverage = 0
    for op in run_operations:
        if synthetic or str(op.get("route", "")).startswith("synthetic:") or op.get("cost_currency") == "SYN":
            synthetic_count += 1
            continue
        amount = op.get("observed_cost_micro_usd")
        if op.get("cost_currency") == "USD" and type(amount) is int and amount >= 0:
            measured += 1
            total += amount
        hold = op.get("unresolved_hold_micro_usd")
        if op.get("cost_currency") == "USD" and type(hold) is int and hold >= 0:
            holds += hold
            hold_coverage += 1
        if op.get("accounting_unit") == "request" or op.get("cost_currency") == "REQ":
            consumed, held = op.get("consumed_requests"), op.get("unresolved_request_hold")
            if type(consumed) is int and consumed >= 0:
                subscriptions += consumed
                subscription_coverage += 1
            if type(held) is int and held >= 0:
                subscription_holds += held
                subscription_hold_coverage += 1
    return {"planned_requests": planned_count, "observed_cost_requests": measured,
            "observed_cost_micro_usd": total if measured else None,
            "complete": measured == planned_count,
            "unresolved_hold_micro_usd": holds if hold_coverage else None,
            "synthetic_excluded_requests": synthetic_count,
            "subscription_invocations": subscriptions if subscription_coverage else None,
            "unresolved_subscription_invocations": subscription_holds if subscription_hold_coverage else None,
            "cost_scope": "selected run requests only; subscription cost unavailable"}


def _pair_money(a, b):
    values = (a["cost"], b["cost"])
    known = [x["observed_cost_micro_usd"] for x in values if x["observed_cost_micro_usd"] is not None]
    holds = [x["unresolved_hold_micro_usd"] for x in values if x["unresolved_hold_micro_usd"] is not None]
    subscriptions = [x["subscription_invocations"] for x in values if x["subscription_invocations"] is not None]
    subscription_holds = [x["unresolved_subscription_invocations"] for x in values
                          if x["unresolved_subscription_invocations"] is not None]
    complete = all(x["complete"] for x in values)
    return {"observed_cost_micro_usd": sum(known) if complete else None,
            "partial_observed_cost_micro_usd": sum(known) if known else None,
            "complete": complete,
            "observed_cost_requests": sum(x["observed_cost_requests"] for x in values),
            "planned_requests": sum(x["planned_requests"] for x in values),
            "unresolved_hold_micro_usd": sum(holds) if holds else None,
            "subscription_invocations": sum(subscriptions) if subscriptions else None,
            "unresolved_subscription_invocations": sum(subscription_holds) if subscription_holds else None,
            "synthetic_excluded_requests": sum(x["synthetic_excluded_requests"] for x in values),
            "scope": "these two runs only; excludes other runs, smoke and human review",
            "limitation": "retrospective agreement counts do not establish deployment gains"}


def _compatibility(a, b):
    reasons = []
    if a["task_sha256"] != b["task_sha256"]:
        reasons.append("task definition differs")
    if a["case_ids"] != b["case_ids"]:
        reasons.append("ordered case membership differs")
    if a["input_sha256"] != b["input_sha256"]:
        reasons.append("input bytes differ")
    return {"compatible": not reasons, "reasons": reasons,
            "reference_compatible": a["source_hashes"]["labels"] == b["source_hashes"]["labels"],
            "rule": "same task definition, ordered cases and input content"}


def _case_diffs(a, b, fields):
    result = []
    for left, right in zip(a["cases"], b["cases"]):
        both_valid = left["prediction_status"] == right["prediction_status"] == "valid"
        equal = left["prediction"] == right["prediction"] if both_valid else None
        field_diffs = {}
        for field in fields:
            name = field["name"]
            av = left["prediction"].get(name) if left["prediction"] is not None else None
            bv = right["prediction"].get(name) if right["prediction"] is not None else None
            field_diffs[name] = {"a": av, "b": bv, "different": av != bv if both_valid else None,
                                 "reference_a": (left["reference"] or {}).get(name),
                                 "reference_b": (right["reference"] or {}).get(name),
                                 "match_a": left["field_matches"][name], "match_b": right["field_matches"][name]}
        result.append({"case_id": left["case_id"], "request_a": left["request_id"],
                       "request_b": right["request_id"], "status_a": left["prediction_status"],
                       "status_b": right["prediction_status"], "lifecycle_a": left["lifecycle_state"],
                       "lifecycle_b": right["lifecycle_state"], "comparable": both_valid,
                       "predictions_equal": equal, "different": not equal if both_valid else None,
                       "status_changed": left["prediction_status"] != right["prediction_status"],
                       "exact_a": left["exact_match"], "exact_b": right["exact_match"],
                       "fields": field_diffs, "evidence_a": left["evidence"], "evidence_b": right["evidence"]})
    return result


def compare_runs(analysis, run_a, run_b):
    """Exact A/B differences, rejecting incompatible task/case/input scopes."""
    runs = {r["run_id"]: r for r in analysis["runs"]}
    if run_a not in runs or run_b not in runs:
        raise ValidationError("comparison: unknown run ID")
    if run_a == run_b:
        raise ValidationError("comparison: choose two distinct runs")
    a, b = runs[run_a], runs[run_b]
    compatible = _compatibility(a, b)
    cases = _case_diffs(a, b, analysis["task"]["fields"]) if compatible["compatible"] else []
    comparable = [c["case_id"] for c in cases if c["comparable"]]
    changed = [c["case_id"] for c in cases if c["different"]]
    excluded = [c["case_id"] for c in cases if not c["comparable"]]
    return {"run_a": run_a, "run_b": run_b, "compatibility": compatible,
            "planned": len(cases) if compatible["compatible"] else None,
            "comparable": len(comparable), "changed": len(changed), "excluded": len(excluded),
            "changed_ids": changed, "excluded_ids": excluded,
            "flip_rate": len(changed) / len(comparable) if comparable else None,
            "cases": cases,
            "fields": {field["name"]: {"changed_ids": [c["case_id"] for c in cases
                if c["fields"][field["name"]]["different"]], "comparable": len(comparable),
                "flips": sum(c["fields"][field["name"]]["different"] is True for c in cases),
                "flip_rate": sum(c["fields"][field["name"]]["different"] is True for c in cases) / len(comparable) if comparable else None,
                "excluded_ids": excluded} for field in analysis["task"]["fields"]}}


def _transitions(a, b, field=None):
    keys = ("gained_ids", "lost_ids", "stable_correct_ids", "stable_error_ids",
            "reference_unknown_ids", "unusable_to_valid_ids", "valid_to_unusable_ids", "unusable_both_ids")
    result = {key: [] for key in keys}
    for left, right in zip(a["cases"], b["cases"]):
        rid = left["case_id"]
        av, bv = left["prediction_status"] == "valid", right["prediction_status"] == "valid"
        if not av and bv:
            result["unusable_to_valid_ids"].append(rid)
        elif av and not bv:
            result["valid_to_unusable_ids"].append(rid)
        elif not av and not bv:
            result["unusable_both_ids"].append(rid)
        if field is None:
            known = left["reference_status"] == right["reference_status"] == "full"
            ac, bc = left["exact_match"] is True, right["exact_match"] is True
        else:
            known = field in (left["reference"] or {}) and field in (right["reference"] or {})
            ac, bc = left["field_matches"][field] is True, right["field_matches"][field] is True
        if not known:
            result["reference_unknown_ids"].append(rid)
        elif ac and bc:
            result["stable_correct_ids"].append(rid)
        elif not ac and bc:
            result["gained_ids"].append(rid)
        elif ac and not bc:
            result["lost_ids"].append(rid)
        else:
            result["stable_error_ids"].append(rid)
    result["net_gain"] = (len(result["gained_ids"]) - len(result["lost_ids"]) if
                          len(result["reference_unknown_ids"]) < len(a["cases"]) else None)
    result["scored_reference_cases"] = len(a["cases"]) - len(result["reference_unknown_ids"])
    result["planned"] = len(a["cases"])
    result["scope_note"] = "agreement credit on known references; missing/invalid earn no credit and retain validity states"
    return result


def _agreement_pair(a, b):
    compatibility = _compatibility(a, b)
    result = {"pair_id": _digest({"rule": AGREEMENT_RULE, "runs": sorted((a["run_id"], b["run_id"]))}),
              "run_a": a["run_id"], "run_b": b["run_id"], "compatibility": compatibility,
              "rule": AGREEMENT_RULE, "planned": len(a["cases"]),
              "accepted_correct_ids": [], "accepted_error_ids": [], "accepted_reference_unknown_ids": [],
              "deferred_ids": [], "deferred_reasons": {},
              "source_hashes": {"run_a": a["source_hashes"], "run_b": b["source_hashes"]},
              "cost": _pair_money(a, b)}
    for left, right in zip(a["cases"], b["cases"]):
        rid = left["case_id"]
        valid = left["prediction_status"] == right["prediction_status"] == "valid"
        if not valid or left["prediction"] != right["prediction"]:
            result["deferred_ids"].append(rid)
            result["deferred_reasons"][rid] = ("different_valid_predictions" if valid else
                f"a_{left['prediction_status']};b_{right['prediction_status']}")
        elif left["reference_status"] != "full" or right["reference_status"] != "full" or not compatibility["reference_compatible"]:
            result["accepted_reference_unknown_ids"].append(rid)
        elif left["prediction"] == left["reference"]:
            result["accepted_correct_ids"].append(rid)
        else:
            result["accepted_error_ids"].append(rid)
    for name in ("accepted_correct", "accepted_error", "accepted_reference_unknown", "deferred"):
        result[name] = len(result[name + "_ids"])
    result["accepted"] = result["accepted_correct"] + result["accepted_error"] + result["accepted_reference_unknown"]
    result["acceptance_rate"] = result["accepted"] / result["planned"]
    return result


def _cohorts(runs, pairs, declarations, fields):
    if declarations is None:
        declarations = [{"id": "all_planned_runs", "title": "All planned runs", "origin": "unspecified",
                         "run_ids": [r["run_id"] for r in runs], "one_run_per_configuration": False,
                         "source": "canonical plan; freshness and import origin not declared"}]
    if not isinstance(declarations, list):
        raise ValidationError("cohorts: expected declared list")
    by_run = {r["run_id"]: r for r in runs}
    seen, result = set(), []
    for declaration in declarations:
        required = {"id", "title", "origin", "run_ids", "one_run_per_configuration", "source"}
        if not isinstance(declaration, dict) or set(declaration) - required - {"case_ids"} or not required <= set(declaration):
            raise ValidationError("cohort: missing or unknown fields")
        name, ids = declaration["id"], declaration["run_ids"]
        if not isinstance(name, str) or not name or name in seen:
            raise ValidationError("cohort: empty or duplicate ID")
        seen.add(name)
        if (declaration["origin"] not in ("declared_fresh", "historical", "imported", "unspecified") or
                type(declaration["one_run_per_configuration"]) is not bool or
                any(not isinstance(declaration[key], str) or not declaration[key] for key in ("title", "source")) or
                not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids) or
                len(set(ids)) != len(ids) or any(x not in by_run for x in ids)):
            raise ValidationError("cohort: invalid declared membership, origin or source")
        selected = [by_run[rid] for rid in ids]
        configs = list(dict.fromkeys(r["config_id"] for r in selected))
        if declaration["one_run_per_configuration"] and len(configs) != len(selected):
            raise ValidationError("cohort: expected one explicitly selected run per configuration")
        cases = declaration.get("case_ids", selected[0]["case_ids"])
        if (not isinstance(cases, list) or not cases or any(not isinstance(x, str) for x in cases) or
                len(set(cases)) != len(cases) or any(x not in selected[0]["case_ids"] for x in cases)):
            raise ValidationError("cohort: invalid case subset")
        indexes = [{c["case_id"]: c for c in r["cases"]} for r in selected]
        case_rows = []
        for cid in cases:
            values = [index[cid] for index in indexes]
            good = [c for c in values if c["prediction_status"] == "valid"]
            vectors = {_digest(c["prediction"]) for c in good}
            case_rows.append({"case_id": cid, "planned_runs": len(selected), "distinct_configurations": len(configs),
                              "valid": len(good), "invalid": sum(c["prediction_status"] == "invalid" for c in values),
                              "missing": sum(c["prediction_status"] == "missing" for c in values),
                              "disagreement": len(vectors) > 1,
                              "reference_errors": sum(c["exact_match"] is False for c in values),
                              "unusable_configurations": sum(not any(r["config_id"] == config and c["prediction_status"] == "valid"
                                  for r, c in zip(selected, values)) for config in configs),
                              "fields": {f["name"]: {"distinct_valid_labels": sorted({c["prediction"][f["name"]] for c in good})}
                                         for f in fields},
                              "run_ids": list(ids)})
        result.append({**deepcopy(declaration), "case_ids": list(cases),
                       "declaration_status": "operator_declared" if declaration["origin"] != "unspecified" else "unspecified_origin",
                       "distinct_configurations": len(configs), "config_ids": configs,
                       "planned_runs": len(selected), "cases": case_rows,
                       "disagreement_ids": [c["case_id"] for c in case_rows if c["disagreement"]],
                       "reference_error_ids": [c["case_id"] for c in case_rows if c["reference_errors"]],
                       "unusable_ids": [c["case_id"] for c in case_rows if c["invalid"] or c["missing"]],
                       "agreement_pair_ids": [p["pair_id"] for p in pairs if p["run_a"] in ids and p["run_b"] in ids],
                       "agreement_pair_case_scope": "full planned run cases; a cohort case subset does not relabel pair totals",
                       "denominator_note": "selected runs and distinct declared configuration IDs are separate; repeated cases are not independent samples"})
    return result


def build_analysis(task, plan, predictions, labels=None, operations=None, *, cohort_declarations=None):
    """Build immutable descriptive projections; never execute, write or correct sources."""
    positions = validated_positions(task, plan, predictions)
    case_ids = positions["record_ids"]
    references = validate_reference_labels(labels, task, set(case_ids), allow_partial=True)
    operations_by_id = _operations(plan, operations)
    sources = {"task": _finite_hash(task, "task"), "plan": _finite_hash(plan, "plan"),
               "predictions": _finite_hash(predictions, "predictions"),
               "labels": _finite_hash(labels, "labels") if labels is not None else None,
               "operations": _finite_hash(operations, "operations") if operations is not None else None,
               "cohort_declarations": _finite_hash(cohort_declarations, "cohorts") if cohort_declarations is not None else None}
    requests_by_run = {}
    for request in plan["requests"]:
        requests_by_run.setdefault((request["config_id"], request["prompt_id"], request["repeat"]), []).append(request)
    field_names = [f["name"] for f in task["fields"]]
    runs = []
    for config in plan["experiment"]["configs"]:
        for prompt in plan["experiment"]["prompts"]:
            for repeat in range(1, plan["experiment"]["repeats"] + 1):
                key = config["id"], prompt["id"], repeat
                requests = requests_by_run[key]
                request_ids = [r["request_id"] for r in requests]
                inputs = [item for r in requests for item in r["items"]]
                input_hash = _digest(inputs)
                run_id = _digest({"task": sources["task"], "config": config, "prompt": prompt,
                                  "repeat": repeat, "input": input_hash, "request_ids": request_ids})
                cases = []
                for request in requests:
                    op = operations_by_id.get(request["request_id"], {})
                    for item in request["items"]:
                        pos = (*key, item["id"])
                        pred = positions["valid"].get(pos)
                        status = "valid" if pos in positions["valid"] else "invalid" if pos in positions["supplied"] else "missing"
                        reference = references.get(item["id"], {})
                        ref_status = "full" if set(reference) == set(field_names) else "partial" if reference else "missing"
                        cases.append({"case_id": item["id"], "request_id": request["request_id"],
                                      "input": deepcopy(item["input"]), "input_sha256": _digest(item["input"]),
                                      "prediction_status": status, "prediction": deepcopy(pred),
                                      "raw_prediction": deepcopy(positions["supplied"].get(pos)) if status == "invalid" else None,
                                      "reference": deepcopy(reference) if reference else None, "reference_status": ref_status,
                                      "exact_match": pred == reference if pred is not None and ref_status == "full" else None,
                                      "field_matches": {name: pred[name] == reference[name] if pred is not None and name in reference else None
                                                        for name in field_names},
                                      "lifecycle_state": op.get("state", "unavailable"),
                                      "parsed_status": op.get("parsed_status"), "reason": op.get("reason") or op.get("blocked_reason"),
                                      "evidence": {name: op[name] for name in EVIDENCE_FIELDS if op.get(name) is not None},
                                      "evidence_format": {name: "sha256" if len(op[name]) == 64 and
                                                          all(c in "0123456789abcdef" for c in op[name]) else "opaque_pointer"
                                                          for name in EVIDENCE_FIELDS if op.get(name) is not None},
                                      "evidence_verification": "supplied metadata; not independently verified by analysis"})
                counts = {"planned": len(cases), **{state: sum(c["prediction_status"] == state for c in cases)
                          for state in ("valid", "invalid", "missing")},
                          "full_reference": sum(c["reference_status"] == "full" for c in cases),
                          "partial_reference": sum(c["reference_status"] == "partial" for c in cases),
                          "no_reference": sum(c["reference_status"] == "missing" for c in cases),
                          "exact_correct": sum(c["exact_match"] is True for c in cases)}
                counts["known_reference_exact_rate"] = counts["exact_correct"] / counts["full_reference"] if counts["full_reference"] else None
                counts["full_denominator_exact_rate"] = counts["exact_correct"] / counts["planned"] if counts["full_reference"] == counts["planned"] else None
                counts["validity_rate"] = counts["valid"] / counts["planned"]
                runs.append({"run_id": run_id, "config_id": config["id"], "prompt_id": prompt["id"],
                             "repeat": repeat, "model": config["model"], "model_type": config.get("model_type"),
                             "configuration": deepcopy(config), "prompt_sha256": _digest(prompt),
                             "configuration_sha256": _digest(config), "task_sha256": sources["task"],
                             "input_sha256": input_hash, "request_ids": request_ids,
                             "source_hashes": deepcopy(sources), "case_ids": list(case_ids),
                             "counts": counts, "cases": cases,
                             "cost": _money([operations_by_id[rid] for rid in request_ids if rid in operations_by_id], len(request_ids),
                                            synthetic=config.get("settings", {}).get("adapter") == "synthetic")})
    prompt_comparisons = []
    for a, b in combinations(runs, 2):
        if a["config_id"] == b["config_id"] and a["repeat"] == b["repeat"] and a["prompt_id"] != b["prompt_id"]:
            prompt_comparisons.append({"run_a": a["run_id"], "run_b": b["run_id"],
                "config_id": a["config_id"], "repeat": a["repeat"], "prompt_a": a["prompt_id"], "prompt_b": b["prompt_id"],
                **_transitions(a, b), "fields": {name: _transitions(a, b, name) for name in field_names},
                "source_hashes": {"run_a": a["source_hashes"], "run_b": b["source_hashes"]}})
    pairs = [_agreement_pair(a, b) for a, b in combinations(runs, 2) if _compatibility(a, b)["compatible"]]
    cohorts = _cohorts(runs, pairs, cohort_declarations, task["fields"])
    analysis = {"schema_version": 1, "analysis_id": _digest({"version": 1, "source_hashes": sources}),
            "source_hashes": sources, "task": deepcopy(task), "case_ids": list(case_ids),
            "positions": len(positions["positions"]), "runs": runs, "prompt_comparisons": prompt_comparisons,
            "agreement_pairs": pairs, "cohorts": cohorts, "agreement_rule": AGREEMENT_RULE,
            "pair_scope": "all unordered compatible planned runs; each pair retains its own full case denominator",
            "sampling_note": "descriptive paired observations; repeated cases and pairs are not independent samples"}
    repeats, ranges = [], []
    for a, b in combinations(runs, 2):
        if a["config_id"] == b["config_id"] and a["prompt_id"] == b["prompt_id"]:
            comparison = compare_runs(analysis, a["run_id"], b["run_id"])
            comparison.pop("cases")
            repeats.append({**comparison, "repeat_a": a["repeat"], "repeat_b": b["repeat"],
                            "config_id": a["config_id"], "prompt_id": a["prompt_id"],
                            "source_hashes": {"run_a": a["source_hashes"], "run_b": b["source_hashes"]}})
    for config in plan["experiment"]["configs"]:
        for prompt in plan["experiment"]["prompts"]:
            selected = [r for r in runs if r["config_id"] == config["id"] and r["prompt_id"] == prompt["id"]]
            scores = [r["counts"]["full_denominator_exact_rate"] for r in selected]
            validity = [r["counts"]["validity_rate"] for r in selected]
            ranges.append({"config_id": config["id"], "prompt_id": prompt["id"],
                           "run_ids": [r["run_id"] for r in selected], "planned_runs": len(selected),
                           "full_denominator_exact_rate_range": [min(scores), max(scores)] if all(s is not None for s in scores) else None,
                           "validity_rate_range": [min(validity), max(validity)],
                           "scope": "all planned repeats, including unusable outcomes; origin not inferred"})
    analysis.update(repeat_comparisons=repeats, repeat_ranges=ranges)
    return analysis
