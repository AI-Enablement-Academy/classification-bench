"""Descriptive configuration comparisons and explicitly declared case cohorts.

All eligible pairs retain compact counters. Exact supporting case partitions are
computed on request, rather than copying every case into every matrix cell.
"""

from copy import deepcopy
from html import escape
from itertools import combinations
import json
from urllib.parse import urlencode

from .core import ValidationError, _digest, validate_task


COMPARISON_RULE = "same_task_inputs_ordered_cases_prompt_and_repeat"
INTERPRETATION = ("Descriptive paired observations on saved inputs; no causal effect, "
                  "independent-sample claim or deployment guarantee.")


def _url(run, case=None, compare=None):
    params = {"run": run}
    if compare is not None:
        params["compareRun"] = compare
    if case is not None:
        params["case"] = case
    return "#case-explorer-heading?" + urlencode(params)


def _link(label, a, b=None, case=None):
    result = {"label": label, "run_a": a, "url": _url(a, case, b)}
    if b is not None:
        result["run_b"] = b
    if case is not None:
        result["case_id"] = case
    return result


def _ratio(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator else None


def _context(analysis):
    if not isinstance(analysis, dict) or analysis.get("schema_version") != 1:
        raise ValidationError("comparisons: expected analysis schema version 1")
    task = validate_task(analysis.get("task"))
    if (not isinstance(analysis.get("analysis_id"), str) or not analysis["analysis_id"] or
            not isinstance(analysis.get("source_hashes"), dict) or
            not isinstance(analysis.get("runs"), list)):
        raise ValidationError("comparisons: expected analysis identity, sources and runs")
    fields = task["fields"]
    names = {f["name"] for f in fields}
    by_run, indexes = {}, {}
    for run in analysis["runs"]:
        rid = run.get("run_id") if isinstance(run, dict) else None
        if not isinstance(rid, str) or not rid.strip() or rid in by_run:
            raise ValidationError("comparisons: invalid or duplicate run ID")
        for name in ("config_id", "prompt_id", "prompt_sha256", "task_sha256", "input_sha256"):
            if not isinstance(run.get(name), str) or not run[name]:
                raise ValidationError("comparisons: missing run membership")
        if (type(run.get("repeat")) is not int or run["repeat"] < 1 or
                not isinstance(run.get("source_hashes"), dict) or
                not isinstance(run.get("configuration"), dict)):
            raise ValidationError("comparisons: invalid run condition")
        config = run["configuration"]
        if (config.get("id") != run["config_id"] or not isinstance(config.get("model"), str) or
                ("settings" in config and not isinstance(config["settings"], dict))):
            raise ValidationError("comparisons: invalid configuration")
        try:
            _digest(config)
        except (ValueError, TypeError) as exc:
            raise ValidationError("comparisons: configuration must be finite JSON") from exc
        cases = run.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ValidationError("comparisons: expected nonempty planned cases")
        ids = [c.get("case_id") if isinstance(c, dict) else None for c in cases]
        if (any(not isinstance(cid, str) or not cid.strip() for cid in ids) or
                len(set(ids)) != len(ids) or ids != run.get("case_ids")):
            raise ValidationError("comparisons: duplicate or inconsistent case membership")
        for case in cases:
            status, pred, ref = case.get("prediction_status"), case.get("prediction"), case.get("reference")
            if status not in ("valid", "invalid", "missing"):
                raise ValidationError("comparisons: unknown prediction status")
            if status == "valid":
                if (not isinstance(pred, dict) or set(pred) != names or
                        any(not isinstance(pred[f["name"]], str) or pred[f["name"]] not in f["labels"] for f in fields)):
                    raise ValidationError("comparisons: invalid declared valid prediction")
            elif pred is not None:
                raise ValidationError("comparisons: unusable prediction must be null")
            if ref is not None and (not isinstance(ref, dict) or set(ref) - names or
                    any(f["name"] in ref and (not isinstance(ref[f["name"]], str) or
                        ref[f["name"]] not in f["labels"]) for f in fields)):
                raise ValidationError("comparisons: invalid known reference")
            if not isinstance(case.get("request_id"), str) or not case["request_id"]:
                raise ValidationError("comparisons: missing request membership")
        by_run[rid], indexes[rid] = run, dict(zip(ids, cases))
    return fields, by_run, indexes


def _compatible(a, b):
    return (a["task_sha256"] == b["task_sha256"] and a["input_sha256"] == b["input_sha256"]
            and a["case_ids"] == b["case_ids"])


def _eligible(a, b):
    return (a["config_id"] != b["config_id"] and _compatible(a, b) and
            a["prompt_id"] == b["prompt_id"] and a["prompt_sha256"] == b["prompt_sha256"] and
            a["repeat"] == b["repeat"])


def _batches(run):
    groups = {}
    for case in run["cases"]:
        groups.setdefault(case["request_id"], []).append(case["case_id"])
    return list(groups.values())


def _dimensions(a, b):
    """Dictionary leaves are dimensions; lists and scalars remain atomic values."""
    changed = []

    def visit(left, right, path, left_present=True, right_present=True):
        if left_present and right_present and _digest(left) == _digest(right):
            return
        if left_present and right_present and isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                visit(left.get(key), right.get(key), path + [key], key in left, key in right)
            return
        if not right_present and isinstance(left, dict) and left:
            for key in sorted(left):
                visit(left[key], None, path + [key], True, False)
            return
        if not left_present and isinstance(right, dict) and right:
            for key in sorted(right):
                visit(None, right[key], path + [key], False, True)
            return
        changed.append({"path": list(path),
                        "pointer": "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in path),
                        "a_present": left_present, "b_present": right_present,
                        "a": deepcopy(left) if left_present else None,
                        "b": deepcopy(right) if right_present else None})

    ac, bc = a["configuration"], b["configuration"]
    visit(ac["model"], bc["model"], ["model"])
    visit(ac.get("settings", {}), bc.get("settings", {}), ["settings"])
    batches_a, batches_b = _batches(a), _batches(b)
    if batches_a != batches_b:
        # Bind exact membership without duplicating all case IDs in every pair.
        changed.append({"path": ["request_batches"], "pointer": "/request_batches",
                        "a_present": True, "b_present": True,
                        "a": {"membership_sha256": _digest(batches_a), "request_count": len(batches_a)},
                        "b": {"membership_sha256": _digest(batches_b), "request_count": len(batches_b)}})
    reporting = []
    if ("model_type" in ac) != ("model_type" in bc) or ac.get("model_type") != bc.get("model_type"):
        reporting.append({"path": ["model_type"], "a_present": "model_type" in ac,
                          "b_present": "model_type" in bc, "a": ac.get("model_type"), "b": bc.get("model_type")})
    return changed, reporting


def _score(cases_a, cases_b, names, reference_compatible, field=None, include_ids=False):
    partitions = {key: [] for key in ("gained", "lost", "stable_correct", "stable_error", "reference_unknown")}
    for a, b in zip(cases_a, cases_b):
        ra, rb = a["reference"] or {}, b["reference"] or {}
        known = (reference_compatible and
                 (field in ra and field in rb and ra[field] == rb[field] if field is not None else
                  set(ra) == set(rb) == names and ra == rb))
        if not known:
            key = "reference_unknown"
        else:
            good_a = a["prediction_status"] == "valid" and (
                a["prediction"][field] == ra[field] if field is not None else a["prediction"] == ra)
            good_b = b["prediction_status"] == "valid" and (
                b["prediction"][field] == rb[field] if field is not None else b["prediction"] == rb)
            key = ("stable_correct" if good_a and good_b else "gained" if good_b else
                   "lost" if good_a else "stable_error")
        partitions[key].append(a["case_id"])
    planned = len(cases_a)
    known = planned - len(partitions["reference_unknown"])
    a_correct = len(partitions["stable_correct"]) + len(partitions["lost"])
    b_correct = len(partitions["stable_correct"]) + len(partitions["gained"])
    result = {"planned": planned, "known_references": known, "unknown_references": planned - known,
              "correct_a": a_correct if known else None, "correct_b": b_correct if known else None,
              **{key: len(value) if known else None for key, value in partitions.items() if key != "reference_unknown"},
              "net_gain": b_correct - a_correct if known else None,
              "known_reference_rate_a": _ratio(a_correct, known), "known_reference_rate_b": _ratio(b_correct, known),
              "full_denominator_rate_a": _ratio(a_correct, planned) if known == planned else None,
              "full_denominator_rate_b": _ratio(b_correct, planned) if known == planned else None}
    if include_ids:
        result.update({key + "_ids": value for key, value in partitions.items()})
    if field is not None:
        comparable = [(a, b) for a, b in zip(cases_a, cases_b)
                      if a["prediction_status"] == b["prediction_status"] == "valid"]
        changed = [a["case_id"] for a, b in comparable if a["prediction"][field] != b["prediction"][field]]
        result.update(both_valid=len(comparable), changed=len(changed),
                      not_both_valid=planned - len(comparable), flip_rate=_ratio(len(changed), len(comparable)))
        if include_ids:
            result["changed_ids"] = changed
    return result


def _comparison(a, b, fields, *, include_ids=False):
    changes, reporting = _dimensions(a, b)
    design = ("same_requested_settings" if not changes else
              "single_varying_dimension" if len(changes) == 1 else "confounded")
    outcomes = [{status: sum(c["prediction_status"] == status for c in run["cases"])
                 for status in ("valid", "invalid", "missing")} for run in (a, b)]
    partitions = {key: [] for key in ("same", "changed", "not_both_valid", "unusable_to_valid",
                                     "valid_to_unusable", "unusable_both")}
    for ca, cb in zip(a["cases"], b["cases"]):
        va, vb = ca["prediction_status"] == "valid", cb["prediction_status"] == "valid"
        if va and vb:
            partitions["same" if ca["prediction"] == cb["prediction"] else "changed"].append(ca["case_id"])
        else:
            partitions["not_both_valid"].append(ca["case_id"])
            partitions["unusable_to_valid" if vb else "valid_to_unusable" if va else "unusable_both"].append(ca["case_id"])
    planned, both = len(a["cases"]), len(partitions["same"]) + len(partitions["changed"])
    refs = a["source_hashes"].get("labels") == b["source_hashes"].get("labels")
    names = {f["name"] for f in fields}
    result = {"comparison_id": _digest({"rule": COMPARISON_RULE, "run_a": a["run_id"], "run_b": b["run_id"],
                                        "sources_a": a["source_hashes"], "sources_b": b["source_hashes"]}),
              "run_a": a["run_id"], "run_b": b["run_id"], "config_a": a["config_id"], "config_b": b["config_id"],
              "prompt_id": a["prompt_id"], "repeat": a["repeat"], "design": design,
              "configuration_changes": changes, "reporting_changes": reporting,
              "planned": planned, "outcomes_a": outcomes[0], "outcomes_b": outcomes[1], "both_valid": both,
              **{key: len(value) for key, value in partitions.items()},
              "flip_rate": _ratio(len(partitions["changed"]), both),
              "validity_rate_a": _ratio(outcomes[0]["valid"], planned),
              "validity_rate_b": _ratio(outcomes[1]["valid"], planned),
              "valid_output_delta": outcomes[1]["valid"] - outcomes[0]["valid"],
              "reference_compatible": refs,
              "all_fields": _score(a["cases"], b["cases"], names, refs, include_ids=include_ids),
              "fields": {f["name"]: _score(a["cases"], b["cases"], names, refs, f["name"], include_ids) for f in fields},
              "evidence_url": _url(a["run_id"], compare=b["run_id"])}
    if include_ids:
        result.update({key + "_ids": value for key, value in partitions.items()})
    return result


def compare_configurations(analysis, run_a, run_b):
    """Return one eligible pair and exact case partitions in the caller's A/B order."""
    fields, by_run, _ = _context(analysis)
    if run_a not in by_run or run_b not in by_run or run_a == run_b:
        raise ValidationError("comparisons: select two distinct known runs")
    a, b = by_run[run_a], by_run[run_b]
    if not _eligible(a, b):
        raise ValidationError("comparisons: different configurations require identical task, input, prompt and repeat scope")
    result = _comparison(a, b, fields, include_ids=True)
    result.update(analysis_id=analysis["analysis_id"], source_hashes=deepcopy(analysis["source_hashes"]),
                  interpretation=INTERPRETATION)
    return result


def _cohort(declaration, by_run, indexes, fields):
    required = ("id", "title", "origin", "run_ids", "one_run_per_configuration", "source", "case_ids")
    if not isinstance(declaration, dict) or not set(required) <= set(declaration):
        raise ValidationError("comparisons: incomplete cohort declaration")
    ids, case_ids = declaration["run_ids"], declaration["case_ids"]
    if (not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or any(r not in by_run for r in ids) or
            not isinstance(case_ids, list) or not case_ids or len(set(case_ids)) != len(case_ids) or
            declaration["origin"] not in ("declared_fresh", "historical", "imported", "unspecified")):
        raise ValidationError("comparisons: invalid cohort membership or origin")
    runs = [by_run[rid] for rid in ids]
    if any(not _compatible(runs[0], run) for run in runs[1:]):
        raise ValidationError("comparisons: cohort combines incompatible tasks or inputs")
    if any(cid not in indexes[ids[0]] for cid in case_ids):
        raise ValidationError("comparisons: unknown cohort case")
    config_ids = list(dict.fromkeys(r["config_id"] for r in runs))
    if declaration["one_run_per_configuration"] and len(config_ids) != len(runs):
        raise ValidationError("comparisons: cohort requires one selected run per configuration")
    rows = []
    names = {f["name"] for f in fields}
    for cid in case_ids:
        values = [(r, indexes[r["run_id"]][cid]) for r in runs]
        good = [(r, c) for r, c in values if c["prediction_status"] == "valid"]
        vectors = {config: {_digest(c["prediction"]) for r, c in good if r["config_id"] == config}
                   for config in config_ids}
        cross = any(va != vb for ca, cb in combinations(config_ids, 2) for va in vectors[ca] for vb in vectors[cb])
        variable = [config for config in config_ids if len(vectors[config]) > 1]
        full = [(r, c) for r, c in values if set(c["reference"] or {}) == names]
        errors = [(r, c) for r, c in full if c["prediction_status"] == "valid" and c["prediction"] != c["reference"]]
        known_errors = [(r, c) for r, c in good if any(
            c["prediction"][name] != label for name, label in (c["reference"] or {}).items())]
        unusable = [(r, c) for r, c in values if c["prediction_status"] != "valid"]
        evidence = []
        if cross:
            a, b = next((a, b) for a, b in combinations(good, 2)
                        if a[0]["config_id"] != b[0]["config_id"] and a[1]["prediction"] != b[1]["prediction"])
            evidence.append(_link("Inspect cross-configuration disagreement", a[0]["run_id"], b[0]["run_id"], cid))
        if variable:
            same = [(r, c) for r, c in good if r["config_id"] == variable[0]]
            a, b = next((a, b) for a, b in combinations(same, 2) if a[1]["prediction"] != b[1]["prediction"])
            evidence.append(_link("Inspect variation within one configuration", a[0]["run_id"], b[0]["run_id"], cid))
        if known_errors:
            evidence.append(_link("Inspect a known-reference disagreement", known_errors[0][0]["run_id"], case=cid))
        if unusable:
            evidence.append(_link("Inspect an unusable selected outcome", unusable[0][0]["run_id"], case=cid))
        field_rows = {}
        for field in fields:
            name = field["name"]
            known = [(r, c) for r, c in values if name in (c["reference"] or {})]
            labels = {config: {c["prediction"][name] for r, c in good if r["config_id"] == config}
                      for config in config_ids}
            field_rows[name] = {"known_reference_runs": len(known),
                "valid_reference_errors": sum(c["prediction_status"] == "valid" and c["prediction"][name] != c["reference"][name] for r, c in known) if known else None,
                "unusable_known_reference_runs": sum(c["prediction_status"] != "valid" for r, c in known) if known else None,
                "distinct_valid_labels": sorted(set().union(*labels.values())),
                "cross_configuration_disagreement": any(a != b for ca, cb in combinations(config_ids, 2) for a in labels[ca] for b in labels[cb]),
                "within_configuration_variable_count": sum(len(value) > 1 for value in labels.values())}
        reasons = (["cross_configuration_disagreement"] if cross else []) + (
            ["known_reference_disagreement"] if known_errors else []) + (["unusable_selected_outcome"] if unusable else [])
        rows.append({"case_id": cid, "planned_runs": len(runs), "distinct_configurations": len(config_ids),
                     "outcomes": {status: sum(c["prediction_status"] == status for r, c in values) for status in ("valid", "invalid", "missing")},
                     "usable_configurations": sum(bool(vectors[config]) for config in config_ids),
                     "unusable_configurations": sum(not vectors[config] for config in config_ids),
                     "configurations_with_unusable_runs": len({r["config_id"] for r, c in unusable}),
                     "cross_configuration_disagreement": cross,
                     "within_configuration_variable_count": len(variable),
                     "full_reference_runs": len(full),
                     "partial_reference_runs": sum(bool(c["reference"]) and set(c["reference"]) != names for r, c in values),
                     "no_reference_runs": sum(not c["reference"] for r, c in values),
                     "valid_full_reference_error_runs": len(errors) if full else None,
                     "configurations_with_full_reference_errors": len({r["config_id"] for r, c in errors}) if full else None,
                     "unusable_full_reference_runs": sum(c["prediction_status"] != "valid" for r, c in full) if full else None,
                     "valid_known_field_error_runs": len(known_errors) if any(c["reference"] for r, c in values) else None,
                     "configurations_with_known_field_errors": len({r["config_id"] for r, c in known_errors}) if any(c["reference"] for r, c in values) else None,
                     "fields": field_rows, "difficulty_reasons": reasons, "difficult": bool(reasons),
                     "supporting_links": evidence})
    result = {key: deepcopy(declaration[key]) for key in required}
    result.update(declaration_status="operator_declared" if declaration["origin"] != "unspecified" else "unspecified_origin",
                  distinct_configurations=len(config_ids), config_ids=config_ids, planned_runs=len(runs),
                  run_config_ids={r["run_id"]: r["config_id"] for r in runs},
                  planned_cases=len(case_ids), planned_positions=len(runs) * len(case_ids), cases=rows,
                  prompt_ids=list(dict.fromkeys(r["prompt_id"] for r in runs)),
                  repeats=list(dict.fromkeys(r["repeat"] for r in runs)),
                  difficult_ids=[row["case_id"] for row in rows if row["difficult"]],
                  disagreement_ids=[row["case_id"] for row in rows if row["cross_configuration_disagreement"]],
                  reference_error_ids=[row["case_id"] for row in rows if row["valid_known_field_error_runs"]],
                  full_reference_error_ids=[row["case_id"] for row in rows if row["valid_full_reference_error_runs"]],
                  unusable_ids=[row["case_id"] for row in rows if row["outcomes"]["invalid"] or row["outcomes"]["missing"]],
                  variable_ids=[row["case_id"] for row in rows if row["within_configuration_variable_count"]],
                  denominator_note="Selected run positions and distinct configuration IDs are separate; repeated observations are not independent votes.")
    result["condition_scope"] = ("same_prompt_and_repeat" if len(result["prompt_ids"]) == len(result["repeats"]) == 1 else
                                 "mixed_prompts_or_repeats; cohort disagreement cannot isolate configuration settings")
    return result


def _finding(analysis, kind, title, observation, scope, denominator, runs, cases, metrics, links, next_step):
    item = {"kind": kind, "title": title, "observation": observation, "scope": scope,
            "denominator": denominator, "run_ids": list(runs), "case_ids": list(cases),
            "metrics": metrics, "supporting_links": links, "next_step": next_step,
            "source_hashes": deepcopy(analysis["source_hashes"]), "interpretation": INTERPRETATION}
    item["finding_id"] = _digest({"analysis": analysis["analysis_id"], **item})
    return item


def build_comparative_findings(analysis):
    """Enumerate all eligible configuration pairs; retain fixed declared cohorts."""
    fields, by_run, indexes = _context(analysis)
    pairs, inventory = [], {"cross_configuration_candidates": 0, "different_prompt_or_repeat": 0, "incompatible_task_or_inputs": 0}
    for a, b in combinations(analysis["runs"], 2):
        if a["config_id"] == b["config_id"]:
            continue
        inventory["cross_configuration_candidates"] += 1
        if not _compatible(a, b):
            inventory["incompatible_task_or_inputs"] += 1
        elif not _eligible(a, b):
            inventory["different_prompt_or_repeat"] += 1
        else:
            pairs.append(_comparison(a, b, fields))
    inventory["eligible_pairs"] = len(pairs)
    declarations = analysis.get("cohorts", [])
    if not isinstance(declarations, list):
        raise ValidationError("comparisons: expected declared cohorts")
    cohorts = [_cohort(declaration, by_run, indexes, fields) for declaration in declarations]
    findings = []
    if pairs:
        designs = {key: sum(p["design"] == key for p in pairs) for key in
                   ("single_varying_dimension", "confounded", "same_requested_settings")}
        known = [p for p in pairs if p["all_fields"]["known_references"]]
        links, evidence = [], []
        if known:
            for boundary, key in (("minimum", min), ("maximum", max)):
                pair = key(known, key=lambda p: p["all_fields"]["net_gain"])
                score = pair["all_fields"]
                ties = sum(p["all_fields"]["net_gain"] == score["net_gain"] for p in known)
                evidence.append({"boundary": boundary, "comparison_id": pair["comparison_id"],
                                 "net_gain": score["net_gain"], "known_references": score["known_references"],
                                 "planned": pair["planned"], "tied_pairs": ties,
                                 "run_a": pair["run_a"], "run_b": pair["run_b"]})
                links.append(_link(f"Inspect {boundary} labeled-subset net agreement difference ({score['net_gain']:+d}; {ties} tied pairs)",
                                   pair["run_a"], pair["run_b"]))
            range_text = (f"Labeled-subset net agreement differences (B minus A) range from {evidence[0]['net_gain']:+d} "
                          f"to {evidence[1]['net_gain']:+d} cases. Each pair keeps its own reference coverage and repeat; this range is not a pooled score.")
        else:
            range_text = "Full-reference agreement differences are unavailable for every pair. Prediction differences and output validity remain measurable."
            links.append(_link("Inspect the first pair in canonical plan order; no score-based selection", pairs[0]["run_a"], pairs[0]["run_b"]))
        findings.append(_finding(analysis, "controlled_configuration_overview", "Configuration comparisons with fixed prompt and repeat",
            f"All {len(pairs)} eligible pairs share task, ordered inputs, prompt and repeat within each pair. "
            f"{designs['single_varying_dimension']} pairs differ in one declared requested dimension; {designs['confounded']} differ in multiple dimensions "
            f"and are confounded; {designs['same_requested_settings']} have the same requested settings under different configuration IDs. "
            + range_text + " A single declared difference does not establish a causal effect. Undeclared provider or runtime differences remain possible.",
            "Every eligible cross-configuration pair; A/B orientation follows canonical plan order; repeats remain separate",
            len(pairs), list(by_run), [], {"pair_count": len(pairs), "design_counts": designs,
                "pairs_with_known_full_references": len(known), "comparative_evidence": evidence,
                "planned_cases_per_pair_range": [min(p['planned'] for p in pairs), max(p['planned'] for p in pairs)]},
            links, "Inspect gains, losses and unusable positions together. Freeze a separately controlled comparison before changing a task-specific recommendation."))
    for cohort in cohorts:
        origin = {"declared_fresh": "declared fresh", "historical": "historical", "imported": "imported", "unspecified": "origin unspecified"}[cohort["origin"]]
        links = []
        # One exact case per reason is a navigation preview, never a selected metric subset.
        for label, key in (("disagreement", "disagreement_ids"), ("reference error", "reference_error_ids"),
                           ("unusable outcome", "unusable_ids"), ("variation within a configuration", "variable_ids")):
            if cohort[key]:
                row = next(c for c in cohort["cases"] if c["case_id"] == cohort[key][0])
                reason = {"disagreement": "cross-configuration", "reference error": "known-reference",
                          "unusable outcome": "unusable", "variation within a configuration": "within one"}[label]
                link = next(link for link in row["supporting_links"] if reason in link["label"])
                links.append({**deepcopy(link), "label": f"Inspect first {label} case in declared order: {row['case_id']}"})
        if not links:
            links.append(_link("Inspect first declared cohort case", cohort["run_ids"][0], case=cohort["case_ids"][0]))
        findings.append(_finding(analysis, "declared_cohort", "Declared cohort: " + cohort["title"],
            f"This {origin} cohort contains {cohort['distinct_configurations']} distinct configuration IDs and "
            f"{cohort['planned_runs']} selected runs over {cohort['planned_cases']} cases ({cohort['planned_positions']} planned run positions). "
            f"{len(cohort['disagreement_ids'])}/{cohort['planned_cases']} cases have differing valid answers across configurations; "
            f"{len(cohort['reference_error_ids'])} have a valid disagreement with at least one known reference field "
            f"({len(cohort['full_reference_error_ids'])} with a full reference), {len(cohort['unusable_ids'])} have an unusable selected outcome, "
            f"and {len(cohort['variable_ids'])} vary within one configuration. These groups overlap. "
            "Missing full references do not establish correctness or error. Repeats do not add configuration votes.",
            f"Cohort {cohort['id']} / {origin}; {cohort['condition_scope']}; source: {cohort['source']}",
            cohort["planned_cases"], cohort["run_ids"], [],
            {"cohort_id": cohort["id"], "origin": cohort["origin"], "distinct_configurations": cohort["distinct_configurations"],
             "planned_runs": cohort["planned_runs"], "planned_cases": cohort["planned_cases"], "planned_positions": cohort["planned_positions"],
             "disagreement_cases": len(cohort["disagreement_ids"]), "reference_error_cases": len(cohort["reference_error_ids"]),
             "full_reference_error_cases": len(cohort["full_reference_error_ids"]),
             "unusable_cases": len(cohort["unusable_ids"]), "within_configuration_variable_cases": len(cohort["variable_ids"]),
             "condition_scope": cohort["condition_scope"]}, links,
            "Inspect the declared case table and exact saved outcomes. Adjudicate absent references separately; keep historical and fresh membership declarations explicit."))
    result = {"schema_version": 1, "analysis_id": analysis["analysis_id"], "source_hashes": deepcopy(analysis["source_hashes"]),
              "rule": COMPARISON_RULE, "pair_inventory": inventory, "pairs": pairs, "cohorts": cohorts, "findings": findings,
              "scope": "All eligible pairs and complete declared cohorts; pair and repeat observations are not independent samples.",
              "limitations": [INTERPRETATION,
                  "Configuration IDs identify declared variants; reporting model_type metadata does not establish architecture or alter requested settings.",
                  "Dictionary leaves, scalar values, lists and request batch membership define declared dimensions; absent values remain distinct from null.",
                  "Cohort aggregates retain declared membership when report filters change. Mixed prompts or repeats cannot isolate configuration settings."]}
    result["comparisons_id"] = _digest(result)
    return result


def render_comparative_findings(projection):
    """Render a local, paginated matrix and fixed-membership cohort case tables."""
    h = lambda value: escape(str(value), quote=True)
    payload = {"pairs": projection["pairs"], "cohorts": projection["cohorts"]}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    options = "".join(f"<option value='{index}'>{h(c['title'])} ({h(c['origin'])})</option>" for index, c in enumerate(projection["cohorts"]))
    return ("<style>.controlled-comparisons{overflow-wrap:anywhere}.controlled-comparisons .comparison-scroll{overflow:auto;max-width:100%;margin:.8rem 0}"
            ".controlled-comparisons table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}.controlled-comparisons th,.controlled-comparisons td{padding:.65rem;border-bottom:1px solid var(--line,#dcded8);text-align:left;vertical-align:top}"
            ".controlled-comparisons caption{text-align:left;padding:.8rem 0}.controlled-comparisons .comparison-controls{display:flex;flex-wrap:wrap;align-items:center;gap:.7rem;margin:1rem 0}"
            ".controlled-comparisons button,.controlled-comparisons select{padding:.5rem;max-width:100%}.controlled-comparisons :focus-visible{outline:3px solid var(--accent,#245b4b);outline-offset:3px}"
            ".controlled-comparisons .comparison-note{color:var(--muted,#59635d);font-size:.9rem}.controlled-comparisons ul{padding-left:1.2rem}@media(max-width:600px){.controlled-comparisons td,.controlled-comparisons th{min-width:7rem;padding:.5rem}}</style>"
            "<section class='controlled-comparisons' id='controlled-comparisons' aria-labelledby='controlled-comparisons-heading'>"
            "<h2 id='controlled-comparisons-heading'>Controlled comparisons and declared cohorts</h2>"
            f"<p>{h(projection['scope'])}</p><p>One declared varying dimension describes the saved comparison design; it does not prove causation. A/B order follows the plan.</p>"
            "<h3 id='configuration-matrix-heading'>Every eligible configuration pair</h3><p>Each row fixes task, ordered inputs, prompt and repeat. Reporting group differences are disclosed separately from requested settings. Full-reference subset scores include unusable predictions.</p>"
            "<div class='comparison-controls'><label>Pair scope <select id='controlled-pair-scope'><option value='matching'>Matching report filters</option><option value='all'>All planned eligible pairs</option></select></label>"
            "<button type='button' id='controlled-pair-prev'>Previous pairs</button><button type='button' id='controlled-pair-next'>Next pairs</button></div>"
            "<p id='controlled-pair-status' role='status' aria-live='polite'></p><div class='comparison-scroll' tabindex='0' role='region' aria-labelledby='configuration-matrix-heading'>"
            "<table><caption>Compact pair counts; reference subset and whole planned denominator remain separate.</caption><thead><tr><th scope='col'>Prompt / repeat</th><th scope='col'>Configuration A → B</th><th scope='col'>Declared changes</th><th scope='col'>References / planned</th><th scope='col'>Subset agreement A → B</th><th scope='col'>Valid outputs A → B</th><th scope='col'>Different / both valid</th><th scope='col'>Exact evidence</th></tr></thead><tbody id='controlled-pair-body'></tbody></table></div>"
            "<h3 id='declared-cohorts-heading'>Declared cohort case evidence</h3><div class='comparison-controls'><label>Cohort <select id='controlled-cohort-select'>" + options + "</select></label>"
            "<button type='button' id='controlled-cohort-prev'>Previous cases</button><button type='button' id='controlled-cohort-next'>Next cases</button></div>"
            "<p id='controlled-cohort-status' role='status' aria-live='polite'></p><p class='comparison-note' id='controlled-cohort-note'></p>"
            "<div class='comparison-scroll' tabindex='0' role='region' aria-labelledby='declared-cohorts-heading'><table><caption>Fixed declared membership. A configuration is unusable here only when none of its selected runs has a valid answer for the case.</caption>"
            "<thead><tr><th scope='col'>Case</th><th scope='col'>Valid / invalid / missing run positions</th><th scope='col'>Unusable / distinct configurations</th><th scope='col'>Disagreement / within-configuration variation</th><th scope='col'>Full / partial / absent references</th><th scope='col'>Reference disagreements / unusable referenced positions</th><th scope='col'>Exact evidence</th></tr></thead><tbody id='controlled-cohort-body'></tbody></table></div>"
            "<noscript><p>This table requires local JavaScript for pagination. All pair and cohort counts remain in the source-bound comparison projection.</p></noscript>"
            f"<script type='application/json' id='controlled-comparison-data'>{encoded}</script>"
            "<script>(function(){'use strict';const data=JSON.parse(document.getElementById('controlled-comparison-data').textContent),size=12;let eligible=null,pairPage=0,casePage=0;"
            "const el=id=>document.getElementById(id),txt=(tag,value)=>{const n=document.createElement(tag);n.textContent=String(value);return n;},cell=(row,value,head=false)=>{const n=txt(head?'th':'td',value);if(head)n.scope='row';row.append(n);return n;};"
            "const link=(parent,label,url)=>{const a=txt('a',label);a.setAttribute('href',url);parent.append(a);},match=id=>eligible===null||eligible.has(id);"
            "function pairs(){const all=el('controlled-pair-scope').value==='all',rows=data.pairs.filter(p=>all||(match(p.run_a)&&match(p.run_b)));const pages=Math.max(1,Math.ceil(rows.length/size));pairPage=Math.min(pairPage,pages-1);const body=el('controlled-pair-body');body.replaceChildren();"
            "for(const p of rows.slice(pairPage*size,(pairPage+1)*size)){const row=document.createElement('tr'),s=p.all_fields;cell(row,p.prompt_id+' / '+p.repeat,true);cell(row,p.config_a+' → '+p.config_b);const design=cell(row,p.design.replaceAll('_',' '));design.append(txt('p',p.configuration_changes.map(d=>d.pointer+': '+(d.a_present?JSON.stringify(d.a):'absent')+' → '+(d.b_present?JSON.stringify(d.b):'absent')).join('; ')||'No requested setting differs'));if(p.reporting_changes.length)design.append(txt('p','Reporting model_type differs; no inference-setting difference is inferred.'));"
            "cell(row,s.known_references+'/'+p.planned+(p.reference_compatible?'':' (reference versions differ)'));cell(row,s.net_gain===null?'unavailable':s.correct_a+' → '+s.correct_b+' of '+s.known_references+'; net '+(s.net_gain>=0?'+':'')+s.net_gain+(s.known_references===p.planned?' (full planned denominator)':' (subset; whole accuracy unavailable)'));cell(row,p.outcomes_a.valid+' → '+p.outcomes_b.valid+' of '+p.planned);cell(row,p.changed+'/'+p.both_valid+'; '+p.not_both_valid+' lack two valid answers');const evidence=cell(row,'');link(evidence,'Inspect exact A/B',p.evidence_url);if(!match(p.run_a)||!match(p.run_b))evidence.append(txt('p','Outside matching report filters'));const details=document.createElement('details');details.append(txt('summary','Field reference counts'));const list=document.createElement('ul');for(const [name,f]of Object.entries(p.fields))list.append(txt('li',name+': '+f.known_references+'/'+f.planned+' references; '+(f.net_gain===null?'agreement unavailable':f.correct_a+' → '+f.correct_b+' matches; '+f.gained+' gains, '+f.lost+' losses')+'; '+f.changed+'/'+f.both_valid+' different valid predictions'));details.append(list);evidence.append(details);body.append(row);}"
            "el('controlled-pair-status').textContent=rows.length+'/'+data.pairs.length+' eligible pairs shown in '+(all?'all planned':'matching filter')+' scope; page '+(pairPage+1)+'/'+pages+'. Each pair keeps its own cases and repeat.';el('controlled-pair-prev').disabled=pairPage===0;el('controlled-pair-next').disabled=pairPage+1===pages;}"
            "function cohort(){const c=data.cohorts[Number(el('controlled-cohort-select').value)],body=el('controlled-cohort-body');body.replaceChildren();if(!c){el('controlled-cohort-status').textContent='No declared cohort.';el('controlled-cohort-prev').disabled=el('controlled-cohort-next').disabled=true;return;}const matched=c.run_ids.filter(match),matchedConfigs=new Set(matched.map(id=>c.run_config_ids[id])),pages=Math.max(1,Math.ceil(c.cases.length/size));casePage=Math.min(casePage,pages-1);"
            "el('controlled-cohort-status').textContent=c.title+' ('+c.origin+'): '+c.distinct_configurations+' distinct configurations, '+c.planned_runs+' selected runs, '+c.planned_cases+' cases; '+matched.length+'/'+c.planned_runs+' cohort runs match report filters ('+matchedConfigs.size+'/'+c.distinct_configurations+' distinct configurations). Declared aggregates remain unchanged. Page '+(casePage+1)+'/'+pages+'.';el('controlled-cohort-note').textContent='Declaration source: '+c.source+'. '+c.condition_scope+'. '+c.denominator_note+' Evidence outside matching filters stays available.';"
            "for(const v of c.cases.slice(casePage*size,(casePage+1)*size)){const row=document.createElement('tr');cell(row,v.case_id,true);cell(row,v.outcomes.valid+' / '+v.outcomes.invalid+' / '+v.outcomes.missing+' of '+v.planned_runs);cell(row,v.unusable_configurations+'/'+v.distinct_configurations+'; '+v.configurations_with_unusable_runs+' have an unusable selected run');cell(row,(v.cross_configuration_disagreement?'yes':'no')+' / '+v.within_configuration_variable_count+' configurations');cell(row,v.full_reference_runs+' / '+v.partial_reference_runs+' / '+v.no_reference_runs+' of '+v.planned_runs);cell(row,v.valid_full_reference_error_runs===null?'unavailable (no full references)':v.valid_full_reference_error_runs+' valid full-reference errors / '+v.unusable_full_reference_runs+' unusable full-reference positions');const support=cell(row,'');for(const item of v.supporting_links){const p=document.createElement('p');link(p,item.label,item.url);if(!match(item.run_a)||(item.run_b&&!match(item.run_b)))p.append(txt('span',' (outside matching report filters)'));support.append(p);}if(!v.supporting_links.length){link(support,'Inspect declared case','#case-explorer-heading?'+new URLSearchParams({run:c.run_ids[0],case:v.case_id}).toString());if(!match(c.run_ids[0]))support.append(txt('p','Outside matching report filters'));}const detail=document.createElement('details');detail.append(txt('summary','Field coverage and differences'));const list=document.createElement('ul');for(const[name,f]of Object.entries(v.fields))list.append(txt('li',name+': '+f.known_reference_runs+'/'+v.planned_runs+' references; valid labels '+JSON.stringify(f.distinct_valid_labels)+'; '+(f.valid_reference_errors===null?'reference agreement unavailable':f.valid_reference_errors+' valid errors, '+f.unusable_known_reference_runs+' unusable referenced positions')));detail.append(list);support.append(detail);body.append(row);}el('controlled-cohort-prev').disabled=casePage===0;el('controlled-cohort-next').disabled=casePage+1===pages;}"
            "el('controlled-pair-prev').addEventListener('click',()=>{pairPage--;pairs();});el('controlled-pair-next').addEventListener('click',()=>{pairPage++;pairs();});el('controlled-pair-scope').addEventListener('change',()=>{pairPage=0;pairs();});el('controlled-cohort-prev').addEventListener('click',()=>{casePage--;cohort();});el('controlled-cohort-next').addEventListener('click',()=>{casePage++;cohort();});el('controlled-cohort-select').addEventListener('change',()=>{casePage=0;cohort();});const knownRuns=new Set([...data.pairs.flatMap(p=>[p.run_a,p.run_b]),...data.cohorts.flatMap(c=>c.run_ids)]);function applyFilters(detail){const ids=detail&&detail.eligibleRunIds;if(!Array.isArray(ids)||ids.some(id=>typeof id!=='string'))return;let next=new Set(ids.filter(id=>knownRuns.has(id)));if(next.size===knownRuns.size)next=null;if(next===null&&eligible===null||next!==null&&eligible!==null&&next.size===eligible.size&&[...next].every(id=>eligible.has(id)))return;eligible=next;pairPage=casePage=0;pairs();cohort();}window.addEventListener('report-filter-change',event=>applyFilters(event.detail));pairs();cohort();if(window.reportFilters&&typeof window.reportFilters.getState==='function')applyFilters(window.reportFilters.getState());else window.dispatchEvent(new CustomEvent('report-filter-request'));})();</script></section>")
