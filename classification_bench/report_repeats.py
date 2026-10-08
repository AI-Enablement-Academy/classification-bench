"""Source-bound repeat changes, with planned positions separate from origin.

Rates describe two valid full prediction vectors on the same saved cases. They
do not establish accuracy, independent samples or independently fresh dispatch.
"""

from collections import defaultdict
from copy import deepcopy
from html import escape
from itertools import combinations
import json
from urllib.parse import urlencode

from .core import ValidationError, _digest, validate_task
from .report_analysis import compare_runs


PAGE_SIZE = 12
ORIGINS = {"declared_fresh", "historical", "imported", "replay", "unspecified"}
ORIGIN_LABELS = {"declared_fresh": "operator-declared fresh", "historical": "historical",
                 "imported": "imported", "replay": "replay", "unspecified": "unspecified"}
INTERPRETATION = ("Descriptive paired observations on saved cases. Repeated cases and pairs are not "
                  "independent samples. Repeat numbers and supplied origin declarations do not verify fresh dispatch.")


def _url(a, b=None, case=None):
    values = {"run": a, "compareRun": b or "", "case": case or ""}
    return "#case-explorer-heading?" + urlencode(values)


def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


def _range(values):
    return [min(values), max(values)] if values and all(value is not None for value in values) else None


def _context(analysis):
    if not isinstance(analysis, dict) or analysis.get("schema_version") != 1:
        raise ValidationError("repeats: expected analysis schema version 1")
    validate_task(analysis.get("task"))
    if (not isinstance(analysis.get("analysis_id"), str) or not analysis["analysis_id"] or
            not isinstance(analysis.get("source_hashes"), dict) or not isinstance(analysis.get("runs"), list)):
        raise ValidationError("repeats: expected analysis identity, sources and runs")
    fields = analysis["task"]["fields"]
    labels = {field["name"]: set(field["labels"]) for field in fields}
    runs, positions = {}, set()
    for run in analysis["runs"]:
        if not isinstance(run, dict) or not isinstance(run.get("run_id"), str) or not run["run_id"] or run["run_id"] in runs:
            raise ValidationError("repeats: invalid or duplicate run ID")
        if (any(not isinstance(run.get(key), str) or not run[key] for key in ("config_id", "prompt_id", "model")) or
                type(run.get("repeat")) is not int or run["repeat"] < 1 or
                not isinstance(run.get("configuration"), dict) or
                not isinstance(run["configuration"].get("settings", {}), dict) or
                not isinstance(run.get("source_hashes"), dict)):
            raise ValidationError("repeats: invalid run condition")
        position = run["config_id"], run["prompt_id"], run["repeat"]
        if position in positions:
            raise ValidationError("repeats: duplicate planned repeat position")
        positions.add(position)
        cases = run.get("cases")
        if not isinstance(cases, list) or not cases or any(not isinstance(case, dict) for case in cases):
            raise ValidationError("repeats: expected planned cases")
        ids = [case.get("case_id") for case in cases]
        if (any(not isinstance(cid, str) or not cid for cid in ids) or len(set(ids)) != len(ids) or
                ids != run.get("case_ids")):
            raise ValidationError("repeats: inconsistent case membership")
        counts = run.get("counts", {})
        if (any(type(counts.get(key)) is not int or counts[key] < 0 for key in ("planned", "valid", "invalid", "missing")) or
                counts["planned"] != len(cases) or sum(counts[key] for key in ("valid", "invalid", "missing")) != len(cases)):
            raise ValidationError("repeats: inconsistent planned counts")
        for case in cases:
            status, prediction = case.get("prediction_status"), case.get("prediction")
            if status not in ("valid", "invalid", "missing"):
                raise ValidationError("repeats: invalid prediction status")
            if status == "valid" and (not isinstance(prediction, dict) or set(prediction) != set(labels) or
                                      any(prediction[name] not in values for name, values in labels.items())):
                raise ValidationError("repeats: invalid valid-prediction projection")
            if status != "valid" and prediction is not None:
                raise ValidationError("repeats: unusable prediction must be null")
            if case.get("reference_status") not in ("full", "partial", "missing"):
                raise ValidationError("repeats: invalid reference status")
            if any(case.get(key) is not None and not isinstance(case[key], str)
                   for key in ("request_id", "lifecycle_state", "parsed_status", "reason")):
                raise ValidationError("repeats: invalid saved case metadata")
        if any(sum(case["prediction_status"] == key for case in cases) != counts[key] for key in ("valid", "invalid", "missing")):
            raise ValidationError("repeats: status counts disagree")
        runs[run["run_id"]] = run
    return fields, runs


def _origins(analysis, runs, declarations):
    result = {rid: [] for rid in runs}
    if declarations is not None:
        if not isinstance(declarations, list):
            raise ValidationError("repeats: origin declarations must be a list")
        seen = set()
        for entry in declarations:
            if (not isinstance(entry, dict) or set(entry) != {"run_id", "origin", "source"} or
                    not isinstance(entry["run_id"], str) or not isinstance(entry["origin"], str) or
                    entry["run_id"] not in runs or entry["run_id"] in seen or entry["origin"] not in ORIGINS or
                    not isinstance(entry["source"], str) or not entry["source"].strip()):
                raise ValidationError("repeats: invalid or duplicate origin declaration")
            seen.add(entry["run_id"])
            result[entry["run_id"]].append({"origin": entry["origin"], "source": entry["source"],
                "declaration_scope": "entire planned run", "case_ids": list(runs[entry["run_id"]]["case_ids"]),
                "declaration_status": "operator_declared; not independently verified"})
    for cohort in analysis.get("cohorts", []):
        if cohort["origin"] == "unspecified":
            continue
        for rid in cohort["run_ids"]:
            if rid not in result:
                raise ValidationError("repeats: unknown declared cohort run")
            result[rid].append({"origin": cohort["origin"], "source": cohort["source"],
                "cohort_id": cohort["id"], "title": cohort["title"], "case_ids": list(cohort["case_ids"]),
                "declaration_scope": "declared cohort cases only", "declaration_status": "operator_declared; not independently verified"})
    return result


def build_repeat_analysis(analysis, *, origin_declarations=None):
    """Project every compatible same-condition repeat pair without rescoring.

    Optional origins are explicit operator declarations, never inferred from a
    repeat index, response pointer, model name or lifecycle state. Their digest
    binds the resulting projection without changing historical analysis sources.
    """
    fields, by_run = _context(analysis)
    origins = _origins(analysis, by_run, origin_declarations)
    groups, compact_runs = defaultdict(list), {}
    for rid, run in by_run.items():
        groups[(run["config_id"], run["prompt_id"])].append(run)
        compact_runs[rid] = {key: deepcopy(run[key]) for key in
            ("run_id", "config_id", "prompt_id", "repeat", "model", "source_hashes", "request_ids", "counts", "case_ids")}
        compact_runs[rid]["synthetic"] = (run["configuration"].get("settings", {}).get("adapter") == "synthetic" or
                                          bool(run.get("cost", {}).get("synthetic_excluded_requests")))
        compact_runs[rid]["origin_declarations"] = origins[rid]
        compact_runs[rid]["dispatch_origin"] = "not established by this analysis"
        compact_runs[rid]["cases"] = [{key: deepcopy(case.get(key)) for key in
            ("case_id", "request_id", "prediction_status", "prediction", "reference_status", "lifecycle_state", "parsed_status", "reason", "evidence")}
            for case in run["cases"]]
    pairs, conditions = [], []
    for (config, prompt), runs in groups.items():
        condition_pairs = []
        for a, b in combinations(runs, 2):
            if a["repeat"] > b["repeat"]:
                a, b = b, a
            diff = compare_runs(analysis, a["run_id"], b["run_id"])
            if (not diff["compatibility"]["compatible"] or
                    a.get("configuration_sha256") != b.get("configuration_sha256") or
                    a.get("prompt_sha256") != b.get("prompt_sha256")):
                raise ValidationError("repeats: same-condition run membership differs")
            pair = {key: deepcopy(diff[key]) for key in
                    ("run_a", "run_b", "planned", "comparable", "changed", "excluded", "changed_ids", "excluded_ids", "flip_rate", "fields", "compatibility")}
            pair.update(config_id=config, prompt_id=prompt, repeat_a=a["repeat"], repeat_b=b["repeat"],
                        pair_id=_digest({"rule": "same_condition_repeat_changes", "runs": [a["run_id"], b["run_id"]]}),
                        separately_planned_requests=not bool(set(a["request_ids"]) & set(b["request_ids"])),
                        synthetic=compact_runs[a["run_id"]]["synthetic"] or compact_runs[b["run_id"]]["synthetic"],
                        evidence_url=_url(a["run_id"], b["run_id"]),
                        source_hashes={"run_a": deepcopy(a["source_hashes"]), "run_b": deepcopy(b["source_hashes"])})
            for metric in pair["fields"].values():
                metric["excluded"] = pair["excluded"]
            pairs.append(pair)
            condition_pairs.append(pair)
        field_ranges = {}
        for field in fields:
            name = field["name"]
            rates, known_rates, coverage = [], [], []
            for run in runs:
                known = sum(name in (case["reference"] or {}) for case in run["cases"])
                correct = sum(case["field_matches"][name] is True for case in run["cases"])
                coverage.append(known)
                rates.append(_rate(correct, len(run["cases"])) if known == len(run["cases"]) else None)
                known_rates.append(_rate(correct, known))
            field_ranges[name] = {"full_denominator_agreement_range": _range(rates),
                                  "known_reference_agreement_range": _range(known_rates),
                                  "known_reference_count_range": _range(coverage)}
        conditions.append({"condition_id": _digest({"config": config, "prompt": prompt}),
            "config_id": config, "prompt_id": prompt, "run_ids": [run["run_id"] for run in runs],
            "planned_runs": len(runs), "planned_cases": len(runs[0]["cases"]), "pair_count": len(condition_pairs),
            "full_denominator_exact_rate_range": _range([run["counts"]["full_denominator_exact_rate"] for run in runs]),
            "known_reference_exact_rate_range": _range([run["counts"]["known_reference_exact_rate"] for run in runs]),
            "full_reference_count_range": _range([run["counts"]["full_reference"] for run in runs]),
            "validity_rate_range": _range([run["counts"]["validity_rate"] for run in runs]), "fields": field_ranges,
            "synthetic": any(compact_runs[run["run_id"]]["synthetic"] for run in runs),
            "scope": "all planned repeats, including missing and invalid predictions; ranges never follow visible filters"})
    result = {"schema_version": 1, "analysis_id": analysis["analysis_id"],
              "source_hashes": deepcopy(analysis["source_hashes"]),
              "origin_declarations_sha256": _digest(origin_declarations) if origin_declarations is not None else None,
              "task_name": analysis["task"]["name"], "fields": [field["name"] for field in fields],
              "runs": compact_runs, "pairs": pairs, "conditions": conditions,
              "whole": {"runs": len(by_run), "pairs": len(pairs), "conditions": len(conditions),
                        "planned_positions": sum(run["counts"]["planned"] for run in by_run.values())},
              "rule": "same frozen configuration and prompt; two valid full vectors required for every field flip",
              "interpretation": INTERPRETATION}
    result["repeat_analysis_id"] = _digest(result)
    return result


def repeat_case_details(data, pair_id, *, field=None, outcome="all"):
    """Return exact flip/stability/exclusion reasons for one pair, on demand."""
    pairs = {pair["pair_id"]: pair for pair in data["pairs"]}
    if pair_id not in pairs or field is not None and field not in data["fields"] or outcome not in {"all", "changed", "stable", "excluded"}:
        raise ValidationError("repeats: unknown pair, field or outcome")
    pair = pairs[pair_id]
    a, b = (data["runs"][pair[key]] for key in ("run_a", "run_b"))
    changed = set(pair["fields"][field]["changed_ids"] if field is not None else pair["changed_ids"])
    excluded = set(pair["excluded_ids"])
    rows = []
    for left, right in zip(a["cases"], b["cases"]):
        cid = left["case_id"]
        status = "excluded" if cid in excluded else "changed" if cid in changed else "stable"
        if outcome != "all" and status != outcome:
            continue
        rows.append({"case_id": cid, "outcome": status,
            "reason": f"A {left['prediction_status']}; B {right['prediction_status']}; two valid full predictions required" if status == "excluded" else
                      "different valid labels" if field is not None and status == "changed" else
                      "different valid prediction vectors" if status == "changed" else "same valid labels" if field is not None else "same valid prediction vector",
            "a": deepcopy(left), "b": deepcopy(right), "field": field,
            "evidence_url": _url(pair["run_a"], pair["run_b"], cid)})
    return rows


def _span(values):
    return "unavailable" if values is None else f"{values[0]:.1%} to {values[1]:.1%}"


def build_repeat_findings(data):
    """Return canonical supplemental findings for report/presentation reuse."""
    findings = []
    for condition in data["conditions"]:
        ids = set(condition["run_ids"])
        pairs = [pair for pair in data["pairs"] if pair["run_a"] in ids and pair["run_b"] in ids]
        rates = [pair for pair in pairs if pair["flip_rate"] is not None]
        limits = [min(rates, key=lambda pair: pair["flip_rate"]), max(rates, key=lambda pair: pair["flip_rate"])] if rates else []
        field_text, field_boundaries = [], []
        for field in data["fields"]:
            measured = [pair for pair in pairs if pair["fields"][field]["flip_rate"] is not None]
            boundaries = [min(measured, key=lambda pair: pair["fields"][field]["flip_rate"]),
                          max(measured, key=lambda pair: pair["fields"][field]["flip_rate"])] if measured else []
            field_text.append(f"{field}: flip rates {_span([boundaries[0]['fields'][field]['flip_rate'], boundaries[1]['fields'][field]['flip_rate']] if boundaries else None)}")
            field_boundaries.extend((field, boundary, pair) for boundary, pair in zip(("minimum", "maximum"), boundaries))
        origin_kinds = sorted({entry["origin"] for rid in condition["run_ids"] for entry in data["runs"][rid]["origin_declarations"]})
        origin_text = ", ".join(ORIGIN_LABELS[kind] for kind in origin_kinds) or "unspecified"
        declarations = [{"run_id": rid, **deepcopy(entry)} for rid in condition["run_ids"]
                        for entry in data["runs"][rid]["origin_declarations"]]
        origin_sources = "; ".join(f"{data['runs'][entry['run_id']]['repeat']}: {ORIGIN_LABELS[entry['origin']]} from {entry['source']} ({len(entry['case_ids'])}/{condition['planned_cases']} declared cases)"
                                   for entry in declarations)
        changed = list(dict.fromkeys(cid for pair in pairs for cid in pair["changed_ids"] + pair["excluded_ids"]))
        observation = (f"{condition['planned_runs']} planned repeat positions over {condition['planned_cases']} saved cases form {len(pairs)} pairs. "
            f"All-field flip rates span {_span([limits[0]['flip_rate'], limits[1]['flip_rate']] if limits else None)} on cases with two valid predictions; "
            f"{len(pairs) - len(rates)}/{len(pairs)} pairs lack comparable predictions. "
            + (f"Excluded cases range from {min(pair['excluded'] for pair in pairs)} to {max(pair['excluded'] for pair in pairs)} of {condition['planned_cases']} planned cases per pair. " if pairs else "No repeat pair is available. ")
            + "; ".join(field_text) + ". "
            + f"All-field exact agreement across all planned repeats spans {_span(condition['full_denominator_exact_rate_range'])}; output validity spans {_span(condition['validity_rate_range'])}. "
            + f"Full references cover {condition['full_reference_count_range'][0]} to {condition['full_reference_count_range'][1]} of {condition['planned_cases']} cases per repeat. "
            + f"Supplied origin declarations: {origin_text}. Origin claims can cover a cohort subset and do not verify independent fresh dispatch. "
            + (f"Declared sources: {origin_sources}. " if origin_sources else "No dispatch/import origin source was supplied. ")
            + ("Synthetic outputs describe pipeline behavior, not model variability." if condition["synthetic"] else "Agreement between repeat outputs does not establish correctness."))
        links = [{"label": f"Inspect {boundary} measured all-field flip rate", "run_a": pair["run_a"], "run_b": pair["run_b"],
                  **({"case_id": pair["changed_ids"][0]} if pair["changed_ids"] else {})}
                 for boundary, pair in zip(("minimum", "maximum"), limits)]
        if not links:
            links = [{"label": "Inspect planned repeat evidence", "run_a": condition["run_ids"][0],
                      **({"run_b": condition["run_ids"][1]} if len(condition["run_ids"]) > 1 else {})}]
        for field, boundary, pair in field_boundaries:
            metric = pair["fields"][field]
            case_ids = metric["changed_ids"] or [cid for cid in data["runs"][pair["run_a"]]["case_ids"] if cid not in set(pair["excluded_ids"])]
            links.append({"label": f"Inspect {field} {boundary} flip rate: {metric['flips']}/{metric['comparable']}",
                          "run_a": pair["run_a"], "run_b": pair["run_b"], "case_id": case_ids[0]})
        finding = {"kind": "repeat_analysis_summary", "title": f"Repeat changes: {condition['config_id']} / {condition['prompt_id']}",
            "observation": observation, "scope": f"{condition['config_id']} / {condition['prompt_id']}; all planned repeats, paired over the same cases",
            "denominator": condition["planned_cases"], "run_ids": list(condition["run_ids"]), "case_ids": changed,
            "next_step": "Inspect field flips and excluded states together. Audit dispatch and import provenance before interpreting changes as fresh model variability; do not pool overlapping pairs.",
            "metrics": {"planned_runs": condition["planned_runs"], "pair_count": len(pairs), "planned_cases_per_pair": condition["planned_cases"],
                        "unscored_pair_count": len(pairs) - len(rates), "fields": deepcopy(condition["fields"]),
                        "repeat_analysis_id": data["repeat_analysis_id"], "origin_declarations": declarations,
                        "origin_declarations_sha256": data["origin_declarations_sha256"]},
            "supporting_links": links, "source_hashes": deepcopy(data["source_hashes"]), "interpretation": INTERPRETATION}
        finding["finding_id"] = _digest({"analysis": data["analysis_id"], **finding})
        findings.append(finding)
    return findings


def _h(value):
    return escape(str(value), quote=True)


def _flip_text(metric, changed="changed"):
    return f"{metric[changed]}/{metric['comparable']} ({metric['flip_rate']:.1%})" if metric["flip_rate"] is not None else "unavailable (0 comparable)"


def _pair_row(pair):
    return (f"<tr><th scope='row'>{_h(pair['config_id'])} / {_h(pair['prompt_id'])}<br>repeats {pair['repeat_a']} and {pair['repeat_b']}</th>"
            f"<td>{_flip_text(pair)}</td><td>{pair['comparable']}/{pair['planned']}</td><td>{pair['excluded']}/{pair['planned']}</td>"
            f"<td><a href='{_h(pair['evidence_url'])}'>Inspect exact A/B</a></td></tr>")


def _condition_row(condition):
    return (f"<tr><th scope='row'>{_h(condition['config_id'])} / {_h(condition['prompt_id'])}</th>"
            f"<td>{condition['planned_runs']}</td><td>{_span(condition['full_denominator_exact_rate_range'])}</td>"
            f"<td>{_span(condition['known_reference_exact_rate_range'])}; {condition['full_reference_count_range'][0]} to {condition['full_reference_count_range'][1]} / {condition['planned_cases']} full references per repeat</td>"
            f"<td>{_span(condition['validity_rate_range'])}</td><td>{condition['planned_cases']} planned cases per repeat</td></tr>")


def render_repeat_analysis(data):
    """Render bounded tables with selected-pair details and exact evidence links."""
    whole, pairs, conditions = data["whole"], data["pairs"], data["conditions"]
    first = pairs[0] if pairs else None
    condition = next((item for item in conditions if first and first["run_a"] in item["run_ids"]), None)
    static_fields = ""
    if first:
        for name in [None, *data["fields"]]:
            metric = first if name is None else first["fields"][name]
            values = condition["full_denominator_exact_rate_range"] if name is None else condition["fields"][name]["full_denominator_agreement_range"]
            static_fields += (f"<tr><th scope='row'>{_h('All fields' if name is None else name)}</th><td>{_flip_text(metric, 'changed' if name is None else 'flips')}</td>"
                              f"<td>{metric['comparable']}/{first['planned']}</td><td>{metric['excluded']}/{first['planned']}</td><td>{_span(values)}</td></tr>")
    static_cases = ""
    for row in repeat_case_details(data, first["pair_id"])[:PAGE_SIZE] if first else []:
        states = [f"{row[side]['prediction_status']}; lifecycle: {row[side]['lifecycle_state'] or 'unavailable'}; reason: {row[side]['reason'] or 'not supplied'}" for side in ("a", "b")]
        static_cases += (f"<tr><th scope='row'><a href='{_h(row['evidence_url'])}'>{_h(row['case_id'])}</a></th><td>{_h(row['outcome'] + ': ' + row['reason'])}</td>"
                         f"<td>{_h(states[0])}</td><td>{_h(states[1])}</td><td>A {_h(row['a']['reference_status'])}; B {_h(row['b']['reference_status'])}</td></tr>")
    static_origins = ""
    for side in ("run_a", "run_b") if first else []:
        run = data["runs"][first[side]]
        entries = run["origin_declarations"]
        static_origins += "".join(f"<li>{_h(side)}: {_h(entry['origin'])}; {len(entry['case_ids'])}/{len(run['case_ids'])} declared cases; {_h(entry['declaration_scope'])}; source: {_h(entry['source'])}; {_h(entry['declaration_status'])}</li>" for entry in entries) if entries else f"<li>{_h(side)}: origin unspecified</li>"
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return (_STYLE + "<section class='repeat-analysis' id='repeat-analysis' aria-labelledby='repeat-analysis-heading'>"
        "<div class='repeat-intro'><div><span class='repeat-eyebrow'>Repeated observations</span><h2 id='repeat-analysis-heading'>What changes between repeats</h2>"
        f"<p>{_h(data['interpretation'])}</p></div><p class='repeat-total'>{whole['pairs']} pairs<br><span>{whole['runs']} planned runs; {whole['planned_positions']} planned positions</span></p></div>"
        "<p>A flip requires two valid full categorical outputs. Invalid and missing outputs stay in the planned denominator and receive an explicit exclusion reason. "
        "Every field uses the same full-output validity rule. Unlabeled cases can show label changes, but cannot receive invented accuracy scores.</p>"
        "<div class='repeat-controls'><label for='repeat-pair-scope'>Pair scope<select id='repeat-pair-scope'><option value='matching'>Matching shared report filters</option><option value='all'>All planned repeat pairs</option></select></label>"
        "<button type='button' id='repeat-pair-previous'>Previous pairs</button><button type='button' id='repeat-pair-next'>Next pairs</button>"
        "<button type='button' id='repeat-pair-clear'>Clear selected pair</button></div>"
        f"<p id='repeat-pair-status' role='status' aria-live='polite'>First {min(PAGE_SIZE,len(pairs))} of {len(pairs)} planned repeat pairs.</p>"
        "<div class='repeat-scroll' tabindex='0' role='region' aria-labelledby='repeat-pair-caption'><table><caption id='repeat-pair-caption'>Same configuration and prompt, different planned repeats</caption>"
        "<thead><tr><th scope='col'>Condition / repeats</th><th scope='col'>All-field flips / comparable</th><th scope='col'>Comparable / planned</th><th scope='col'>Excluded / planned</th><th scope='col'>Exact evidence</th></tr></thead>"
        "<tbody id='repeat-pair-body'>" + "".join(_pair_row(pair) for pair in pairs[:PAGE_SIZE]) + "</tbody></table></div>"
        "<p id='repeat-pair-empty' hidden>No repeat pairs match this scope. Choose all planned pairs or reset shared filters.</p>"
        "<h3 id='repeat-range-heading'>Ranges across every planned repeat</h3><p>Ranges retain all repeats, including those outside visible filters. Full-denominator agreement is unavailable when reference coverage is incomplete.</p>"
        "<div class='repeat-controls'><button type='button' id='repeat-range-previous'>Previous conditions</button><button type='button' id='repeat-range-next'>Next conditions</button></div>"
        f"<p id='repeat-range-status' role='status' aria-live='polite'>First {min(PAGE_SIZE,len(conditions))} of {len(conditions)} conditions.</p>"
        "<div class='repeat-scroll' tabindex='0' role='region' aria-labelledby='repeat-range-heading'><table><caption>Saved repeat ranges; filtering never recalculates them</caption>"
        "<thead><tr><th scope='col'>Condition</th><th scope='col'>Planned runs</th><th scope='col'>Full-denominator exact agreement</th><th scope='col'>Known-reference exact agreement / coverage</th><th scope='col'>Output validity</th><th scope='col'>Scope</th></tr></thead>"
        "<tbody id='repeat-range-body'>" + "".join(_condition_row(condition) for condition in conditions[:PAGE_SIZE]) + "</tbody></table></div>"
        f"<section id='repeat-pair-detail'{' hidden' if first is None else ''} aria-labelledby='repeat-detail-heading'><h3 id='repeat-detail-heading' tabindex='-1'>Repeat pair detail</h3>"
        f"<p id='repeat-detail-scope'>{'First planned pair; every field requires two valid full predictions.' if first else ''}</p><p id='repeat-detail-origin'>Origin is not established by a repeat index. Operator origin declarations are not independently verified.</p><details><summary>Declared origin sources</summary><ul id='repeat-origin-list'>{static_origins}</ul></details>"
        "<div class='repeat-scroll' tabindex='0' role='region' aria-labelledby='repeat-field-caption'><table><caption id='repeat-field-caption'>All-field and per-field flips for the selected pair</caption>"
        "<thead><tr><th scope='col'>Field</th><th scope='col'>Flips / comparable</th><th scope='col'>Comparable / planned</th><th scope='col'>Excluded / planned</th><th scope='col'>Agreement range across all planned repeats</th></tr></thead><tbody id='repeat-field-body'>" + static_fields + "</tbody></table></div>"
        "<div class='repeat-controls'><label for='repeat-case-field'>Case field<select id='repeat-case-field'><option value=''>All fields</option></select></label>"
        "<label for='repeat-case-outcome'>Case outcome<select id='repeat-case-outcome'><option value='all'>All planned cases</option><option value='changed'>Changed valid labels</option><option value='stable'>Stable valid labels</option><option value='excluded'>Excluded cases</option></select></label>"
        "<button type='button' id='repeat-case-previous'>Previous cases</button><button type='button' id='repeat-case-next'>Next cases</button></div>"
        f"<p id='repeat-case-status' role='status' aria-live='polite'>{f'First {min(PAGE_SIZE,first["planned"])} of {first["planned"]} planned cases.' if first else ''}</p><div class='repeat-scroll' tabindex='0' role='region' aria-labelledby='repeat-case-caption'><table>"
        "<caption id='repeat-case-caption'>Exact saved case states and comparison reasons</caption><thead><tr><th scope='col'>Case</th><th scope='col'>Comparison</th><th scope='col'>Run A</th><th scope='col'>Run B</th><th scope='col'>Reference coverage</th></tr></thead><tbody id='repeat-case-body'>" + static_cases + "</tbody></table></div></section>"
        "<noscript><p>JavaScript is disabled. The first pair, field, case and condition pages remain readable; each exact A/B link opens saved evidence. Interactive pagination requires local JavaScript.</p></noscript>"
        f"<details><summary>Repeat projection source hashes</summary><p>Analysis: {_h(data['analysis_id'])}; repeat projection: {_h(data['repeat_analysis_id'])}; origin declarations: {_h(data['origin_declarations_sha256'] or 'not supplied')}.</p>"
        "<dl>" + "".join(f"<dt>{_h(key)}</dt><dd>{_h(value or 'not supplied')}</dd>" for key,value in data["source_hashes"].items()) + "</dl></details>"
        f"<script type='application/json' id='repeat-analysis-data'>{encoded}</script>" + _SCRIPT + "</section>")


_STYLE = """<style>
.repeat-analysis{padding:2.8rem 0;border-top:1px solid var(--line,#dcded8);overflow-wrap:anywhere;font-variant-numeric:tabular-nums;scroll-margin-top:5rem}.repeat-analysis p{max-width:72ch;line-height:1.55}.repeat-analysis h2{font-family:Georgia,serif;font-size:clamp(1.7rem,3vw,2.6rem);font-weight:500;letter-spacing:-.025em}.repeat-analysis h3{margin-top:2rem}.repeat-analysis .repeat-intro{display:flex;gap:2rem;align-items:baseline;justify-content:space-between;flex-wrap:wrap}.repeat-analysis .repeat-total{font-size:2rem;line-height:1.2}.repeat-analysis .repeat-total span,.repeat-analysis .repeat-eyebrow{font-size:.8rem;color:var(--muted,#59635d)}.repeat-analysis .repeat-controls{display:flex;flex-wrap:wrap;align-items:end;gap:.7rem;margin:1.2rem 0}.repeat-analysis label{font-size:.8rem;font-weight:600}.repeat-analysis :is(button,select){font:inherit;padding:.55rem .7rem;max-width:100%;background:var(--surface,#fff);color:inherit;border:1px solid #aeb9af;border-radius:3px}.repeat-analysis select{display:block;margin-top:.4rem}.repeat-analysis button{cursor:pointer;transition:background-color .18s ease}.repeat-analysis button:hover{background:var(--soft,#e9efe9)}.repeat-analysis button:disabled{cursor:default;opacity:.55}.repeat-analysis :focus-visible{outline:3px solid var(--accent,#245b4b);outline-offset:3px}.repeat-analysis .repeat-scroll{overflow:auto;max-width:100%;margin:1rem 0}.repeat-analysis table{width:100%;border-collapse:collapse}.repeat-analysis caption{text-align:left;font-size:.85rem;font-weight:650;padding:.7rem 0}.repeat-analysis :is(th,td){text-align:left;vertical-align:top;border-bottom:1px solid var(--line,#dcded8);padding:.75rem;font-size:.85rem}.repeat-analysis th{font-weight:600}.repeat-analysis tbody tr[aria-current=true]{background:var(--soft,#e9efe9)}.repeat-analysis [hidden]{display:none!important}.repeat-analysis dl{font-size:.8rem}.repeat-analysis dd{margin-bottom:.6rem}.repeat-analysis .repeat-outside{color:var(--danger,#914939);font-weight:600}
@media(max-width:600px){.repeat-analysis :is(th,td){min-width:8rem;padding:.6rem}.repeat-analysis .repeat-controls{align-items:stretch}.repeat-analysis .repeat-controls label{flex:1 1 12rem}}
@media(prefers-reduced-motion:reduce){.repeat-analysis *{transition:none!important;animation:none!important}}
@media print{.repeat-analysis .repeat-controls{display:none!important}.repeat-analysis .repeat-scroll{overflow:visible}.repeat-analysis table{font-size:9pt}.repeat-analysis :is(h2,h3){break-after:avoid}}
</style>"""


_SCRIPT = """<script>(()=>{
'use strict';const root=document.getElementById('repeat-analysis');if(!root)return;const data=JSON.parse(document.getElementById('repeat-analysis-data').textContent),size=12;
const get=id=>document.getElementById('repeat-'+id),byPair=new Map(data.pairs.map(p=>[p.pair_id,p]));let eligible=null,selected=null,explicit=false,selectedCase='',pairPage=0,rangePage=0,casePage=0;
const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);return n;},cell=(row,text,head=false)=>{const n=node(head?'th':'td',text);if(head)n.scope='row';row.append(n);return n;};
const rate=m=>m.flip_rate===null?'unavailable (0 comparable)':(m.changed===undefined?m.flips:m.changed)+'/'+m.comparable+' ('+(100*m.flip_rate).toFixed(1)+'%)';
const span=value=>value===null?'unavailable':(100*value[0]).toFixed(1)+'% to '+(100*value[1]).toFixed(1)+'%',match=id=>eligible===null||eligible.has(id);
const pairMatch=p=>match(p.run_a)&&match(p.run_b),pairKey=(a,b)=>data.pairs.find(p=>p.run_a===a&&p.run_b===b||p.run_a===b&&p.run_b===a);
function fragment(url){const i=url.hash.indexOf('?');return {heading:url.hash.slice(1,i<0?undefined:i),params:new URLSearchParams(i<0?'':url.hash.slice(i+1))};}
function evidenceURL(p,cid='',heading='case-explorer-heading'){const url=new URL(window.location.href),part=fragment(url);part.params.set('run',p.run_a);part.params.set('compareRun',p.run_b);part.params.set('case',cid);url.hash=heading+'?'+part.params.toString();return url;}
function link(parent,text,p,cid=''){const a=node('a',text);a.setAttribute('href','#case-explorer-heading?'+new URLSearchParams({run:p.run_a,compareRun:p.run_b,case:cid}).toString());parent.append(a);return a;}
function visiblePairs(){const all=get('pair-scope').value==='all',rows=data.pairs.filter(p=>all||pairMatch(p));const pinned=explicit&&byPair.get(selected);if(pinned&&!rows.includes(pinned))rows.unshift(pinned);return rows;}
function pages(prefix,total,page){const count=Math.max(1,Math.ceil(total/size));page=Math.max(0,Math.min(page,count-1));get(prefix+'-previous').disabled=page===0;get(prefix+'-next').disabled=page+1===count;return [page,count];}
function showPair(p,write=false){selected=p.pair_id;explicit=true;casePage=0;if(write){const cid=p.planned&&data.runs[p.run_a].case_ids.includes(selectedCase)?selectedCase:data.runs[p.run_a].case_ids[0]||'';selectedCase=cid;const url=evidenceURL(p,cid,'repeat-analysis-heading');try{window.history.replaceState(null,'',url.href);}catch(_){window.location.hash=url.hash;}window.dispatchEvent(new CustomEvent('report-explorer-select',{detail:{run:p.run_a,compareRun:p.run_b,case:cid}}));}pairs();ranges();detail();}
function pairs(){const rows=visiblePairs();let count;[pairPage,count]=pages('pair',rows.length,pairPage);const body=get('pair-body');body.replaceChildren();const matching=data.pairs.filter(pairMatch).length,pinned=explicit&&byPair.get(selected)&&!pairMatch(byPair.get(selected));
get('pair-status').textContent=matching+'/'+data.pairs.length+' pairs match shared filters; '+rows.length+' displayed in '+(get('pair-scope').value==='all'?'all planned':'matching')+' scope'+(pinned&&get('pair-scope').value!=='all'?'; one exact selected pair is retained outside scope':'')+'. Page '+(pairPage+1)+'/'+count+'. Each pair keeps its full planned case denominator.';
get('pair-empty').hidden=rows.length!==0;get('pair-clear').disabled=!explicit;
for(const p of rows.slice(pairPage*size,(pairPage+1)*size)){const row=node('tr');row.dataset.pairId=p.pair_id;row.setAttribute('aria-current',String(p.pair_id===selected));cell(row,p.config_id+' / '+p.prompt_id+'; repeats '+p.repeat_a+' and '+p.repeat_b,true);cell(row,rate(p));cell(row,p.comparable+'/'+p.planned);cell(row,p.excluded+'/'+p.planned);const action=cell(row);const button=node('button','Show fields and cases');button.type='button';button.addEventListener('click',()=>{showPair(p,true);get('detail-heading').focus({preventScroll:true});});action.append(button);link(action,'Inspect exact A/B',p);if(!pairMatch(p))action.append(node('p','Outside shared filter scope'));if(p.synthetic)action.append(node('p','Synthetic: pipeline behavior'));body.append(row);}
if(!explicit){selected=rows[0]?rows[0].pair_id:null;detail();}}
function ranges(){const all=get('pair-scope').value==='all',p=byPair.get(selected),rows=data.conditions.filter(c=>all||c.run_ids.some(match)||explicit&&p&&c.run_ids.includes(p.run_a));let count;[rangePage,count]=pages('range',rows.length,rangePage);const body=get('range-body');body.replaceChildren();get('range-status').textContent=rows.length+'/'+data.conditions.length+' conditions displayed; page '+(rangePage+1)+'/'+count+'. All ranges retain every planned repeat.';
for(const c of rows.slice(rangePage*size,(rangePage+1)*size)){const row=node('tr');cell(row,c.config_id+' / '+c.prompt_id,true);cell(row,c.planned_runs);cell(row,span(c.full_denominator_exact_rate_range));cell(row,span(c.known_reference_exact_rate_range)+'; '+c.full_reference_count_range[0]+' to '+c.full_reference_count_range[1]+' / '+c.planned_cases+' full references per repeat');cell(row,span(c.validity_rate_range));const scope=cell(row,c.run_ids.filter(match).length+'/'+c.planned_runs+' runs match filters; '+c.planned_cases+' cases per repeat');for(const id of c.run_ids){const run=data.runs[id];const a=node('a','Repeat '+run.repeat);a.setAttribute('href','#case-explorer-heading?'+new URLSearchParams({run:id,compareRun:'',case:''}).toString());scope.append(a,document.createTextNode(' '));}if(c.synthetic)scope.append(node('p','Synthetic: pipeline behavior'));body.append(row);}}
function caseRows(p){const a=data.runs[p.run_a],b=data.runs[p.run_b],field=get('case-field').value,metric=field?p.fields[field]:p,changed=new Set(metric.changed_ids),excluded=new Set(p.excluded_ids),outcome=get('case-outcome').value;
return a.cases.map((left,i)=>{const right=b.cases[i],state=excluded.has(left.case_id)?'excluded':changed.has(left.case_id)?'changed':'stable';return {a:left,b:right,state};}).filter(row=>outcome==='all'||row.state===outcome);}
function detail(){const p=byPair.get(selected);get('pair-detail').hidden=!p;if(!p)return;const a=data.runs[p.run_a],b=data.runs[p.run_b],c=data.conditions.find(c=>c.run_ids.includes(p.run_a));get('detail-heading').textContent=p.config_id+' / '+p.prompt_id+': repeats '+p.repeat_a+' and '+p.repeat_b;
get('detail-scope').textContent=p.planned+' planned cases; '+p.comparable+' comparable, '+p.excluded+' excluded. '+(pairMatch(p)?'Both runs match shared filters.':'Exact selected evidence remains outside shared filter scope.');get('detail-scope').classList.toggle('repeat-outside',!pairMatch(p));
get('detail-origin').textContent=(p.separately_planned_requests?'Distinct planned request identities. ':'Planned request identities overlap. ')+'Actual fresh dispatch is not established by repeat numbers or this analysis. '+(p.synthetic?'Synthetic outputs describe pipeline behavior. ':'')+'Supplied origins are operator declarations; cohort subsets do not relabel whole runs.';
const origins=get('origin-list');origins.replaceChildren();for(const [name,run] of [['A',a],['B',b]]){if(!run.origin_declarations.length)origins.append(node('li',name+': origin unspecified'));for(const entry of run.origin_declarations)origins.append(node('li',name+': '+entry.origin+'; '+entry.case_ids.length+'/'+run.case_ids.length+' declared cases; '+entry.declaration_scope+'; source: '+entry.source+'; '+entry.declaration_status));}
const body=get('field-body');body.replaceChildren();for(const name of [null,...data.fields]){const m=name===null?p:p.fields[name],row=node('tr');cell(row,name===null?'All fields':name,true);cell(row,rate(m));cell(row,m.comparable+'/'+p.planned);cell(row,m.excluded+'/'+p.planned);const target=cell(row,span(name===null?c.full_denominator_exact_rate_range:c.fields[name].full_denominator_agreement_range));const changed=node('button','Show changed cases');changed.type='button';changed.addEventListener('click',()=>{get('case-field').value=name||'';get('case-outcome').value='changed';casePage=0;cases();});target.append(changed);body.append(row);}cases();}
function cases(){const p=byPair.get(selected);if(!p)return;const rows=caseRows(p);let count;[casePage,count]=pages('case',rows.length,casePage);const body=get('case-body');body.replaceChildren();get('case-status').textContent=rows.length+'/'+p.planned+' planned cases in this outcome view; page '+(casePage+1)+'/'+count+'. Pair metrics remain unchanged.'+(selectedCase&&!rows.some(r=>r.a.case_id===selectedCase)?' Exact explorer case '+selectedCase+' remains selected outside this outcome view.':'');
for(const r of rows.slice(casePage*size,(casePage+1)*size)){const row=node('tr');row.dataset.caseId=r.a.case_id;row.setAttribute('aria-current',String(r.a.case_id===selectedCase));link(cell(row,undefined,true),r.a.case_id,p,r.a.case_id);cell(row,r.state+': '+(r.state==='excluded'?'two valid full predictions required':r.state==='changed'?'different valid labels':'same valid labels'));
for(const value of [r.a,r.b]){const field=get('case-field').value,pred=value.prediction;cell(row,value.prediction_status+'; lifecycle: '+(value.lifecycle_state||'unavailable')+'; parsed: '+(value.parsed_status||'unavailable')+'; reason: '+(value.reason||'not supplied')+'; prediction: '+(pred===null?'unavailable':field?pred[field]:JSON.stringify(pred)));}cell(row,'A '+r.a.reference_status+'; B '+r.b.reference_status);body.append(row);}if(!rows.length){const row=node('tr'),empty=cell(row,'No cases match this outcome view. Choose all planned cases.');empty.colSpan=5;body.append(row);}}
function applyFilters(value){const ids=value&&value.eligibleRunIds;if(!Array.isArray(ids)||ids.some(id=>typeof id!=='string'))return;let next=new Set(ids.filter(id=>Object.hasOwn(data.runs,id)));if(next.size===Object.keys(data.runs).length)next=null;if(next===null&&eligible===null||next!==null&&eligible!==null&&next.size===eligible.size&&[...next].every(id=>eligible.has(id)))return;eligible=next;pairPage=rangePage=0;pairs();ranges();detail();}
function fromSelection(value){const p=pairKey(value.run,value.compareRun);if(!p){selectedCase=value.case||'';cases();return;}const pairChanged=p.pair_id!==selected,caseChanged=value.case!==selectedCase;selected=p.pair_id;explicit=true;selectedCase=value.case||'';if(pairChanged)pairPage=casePage=0;if(caseChanged){const index=caseRows(p).findIndex(row=>row.a.case_id===selectedCase);if(index>=0)casePage=Math.floor(index/size);}pairs();ranges();detail();}
function fromURL(){const url=new URL(window.location.href),part=fragment(url),read=key=>part.params.has(key)?part.params.get(key):url.searchParams.get(key);fromSelection({run:read('run'),compareRun:read('compareRun'),case:read('case')});}
for(const field of data.fields){const option=node('option',field);option.value=field;get('case-field').append(option);}get('pair-scope').addEventListener('change',()=>{pairPage=rangePage=0;pairs();ranges();detail();});get('pair-clear').addEventListener('click',()=>{explicit=false;selected=null;pairPage=casePage=0;const url=new URL(window.location.href),part=fragment(url);part.params.set('compareRun','');url.hash=(part.heading||'repeat-analysis-heading')+'?'+part.params.toString();try{window.history.replaceState(null,'',url.href);}catch(_){window.location.hash=url.hash;}window.dispatchEvent(new CustomEvent('report-explorer-select',{detail:{run:part.params.get('run')||'',compareRun:'',case:part.params.get('case')||''}}));pairs();ranges();});
for(const prefix of ['pair','range','case'])for(const [direction,delta]of [['previous',-1],['next',1]])get(prefix+'-'+direction).addEventListener('click',()=>{if(prefix==='pair'){pairPage+=delta;pairs();}else if(prefix==='range'){rangePage+=delta;ranges();}else{casePage+=delta;cases();}});
for(const id of ['case-field','case-outcome'])get(id).addEventListener('change',()=>{casePage=0;cases();});window.addEventListener('report-filter-change',event=>applyFilters(event.detail));window.addEventListener('report-explorer-change',event=>fromSelection(event.detail||{}));window.addEventListener('hashchange',fromURL);window.addEventListener('popstate',fromURL);
root.addEventListener('click',event=>{if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;const anchor=event.target.closest('a[href]');if(!anchor||!anchor.getAttribute('href').startsWith('#case-explorer-heading?'))return;const target=new URL(anchor.href,window.location.href),part=fragment(target),url=new URL(window.location.href),current=fragment(url);part.params.forEach((value,key)=>current.params.set(key,value));url.hash='case-explorer-heading?'+current.params.toString();event.preventDefault();window.location.hash=url.hash;const heading=document.getElementById('explorer-case-heading')||document.getElementById('case-explorer-heading');if(heading){if(!heading.hasAttribute('tabindex'))heading.tabIndex=-1;heading.focus({preventScroll:true});}});
pairs();ranges();fromURL();if(window.reportFilters&&typeof window.reportFilters.getState==='function')applyFilters(window.reportFilters.getState());else window.dispatchEvent(new CustomEvent('report-filter-request'));
})();</script>"""
