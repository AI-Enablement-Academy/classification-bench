"""Pure, source-bound hypothetical reference alternatives for offline reports.

Every replacement needs an operator-authored scenario and an already available
reference. Prediction validity, planned membership and reference coverage stay
fixed. This module never writes sources, adjudicates labels or calls a provider.
"""

from copy import deepcopy
from html import escape

from .core import (ValidationError, _digest, _id, _list, _object, evaluate,
                   validate_reference_labels, validated_positions)
from .report_findings import evidence_url


VERSION = 1


def _hash(value, name):
    try:
        return _digest(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name}: expected finite JSON") from exc


def _validate_scenarios(scenarios, task, case_ids, references):
    if scenarios is None:
        scenarios = []
    _list(scenarios, "scenarios", minimum=0)
    allowed = {field["name"]: field["labels"] for field in task["fields"]}
    seen, result = set(), []
    for scenario in scenarios:
        _object(scenario, {"id", "title", "provenance", "changes"},
                {"id", "title", "provenance", "changes"}, "scenario")
        for key in ("id", "title", "provenance"):
            _id(scenario[key], f"scenario.{key}")
        if scenario["id"] in seen:
            raise ValidationError("scenarios: duplicate scenario ID")
        seen.add(scenario["id"])
        changes = {}
        for change in _list(scenario["changes"], "scenario.changes"):
            _object(change, {"id", "labels"}, {"id", "labels"}, "scenario change")
            case = _id(change["id"], "scenario change.id")
            if case not in case_ids:
                raise ValidationError("scenario change: unknown case ID")
            if case in changes:
                raise ValidationError("scenario change: duplicate case ID")
            _object(change["labels"], allowed, set(), "scenario change.labels")
            if not change["labels"]:
                raise ValidationError("scenario change.labels: at least one alternative is required")
            for name, label in change["labels"].items():
                if not isinstance(label, str) or label not in allowed[name]:
                    raise ValidationError("scenario change: unknown or invalid label")
                if name not in references.get(case, {}):
                    raise ValidationError("scenario change: cannot replace an unavailable reference")
                if label == references[case][name]:
                    raise ValidationError("scenario change: alternative must differ from the saved reference")
            changes[case] = change["labels"]
        # Normalize semantic change order to the canonical plan and task order.
        result.append({key: deepcopy(scenario[key]) for key in ("id", "title", "provenance")} | {
            "changes": [{"id": case, "labels": {name: changes[case][name] for name in allowed
                         if name in changes[case]}} for case in case_ids if case in changes]})
    return result


def _coverage(case_ids, references, fields):
    names = [field["name"] for field in fields]
    full = [case for case in case_ids if len(references.get(case, {})) == len(names)]
    partial = [case for case in case_ids if 0 < len(references.get(case, {})) < len(names)]
    missing = [case for case in case_ids if not references.get(case)]
    return {"status": "complete" if len(full) == len(case_ids) else "partial" if full or partial else "unlabeled",
            "planned_cases": len(case_ids), "fully_labeled_ids": full,
            "partially_labeled_ids": partial, "unlabeled_ids": missing,
            "known_field_labels": sum(len(references.get(case, {})) for case in case_ids),
            "expected_field_labels": len(case_ids) * len(names),
            "fields": {name: {"known_ids": [case for case in case_ids if name in references.get(case, {})],
                              "missing_ids": [case for case in case_ids if name not in references.get(case, {})],
                              "reference_denominator": sum(name in references.get(case, {}) for case in case_ids)}
                       for name in names}}


def _run_contexts(task, plan, positions):
    grouped = {}
    for request in plan["requests"]:
        key = request["config_id"], request["prompt_id"], request["repeat"]
        grouped.setdefault(key, []).append(request)
    contexts = []
    for config in plan["experiment"]["configs"]:
        for prompt in plan["experiment"]["prompts"]:
            for repeat in range(1, plan["experiment"]["repeats"] + 1):
                key = config["id"], prompt["id"], repeat
                requests = grouped[key]
                items = [item for request in requests for item in request["items"]]
                # Identical to report_analysis run identity. Predictions/references
                # do not alter the evidence destination for a hypothetical key.
                run_id = _digest({"task": _digest(task), "config": config, "prompt": prompt,
                                  "repeat": repeat, "input": _digest(items),
                                  "request_ids": [request["request_id"] for request in requests]})
                cases = []
                for request in requests:
                    for item in request["items"]:
                        pos = (*key, item["id"])
                        status = "valid" if pos in positions["valid"] else "invalid" if pos in positions["supplied"] else "missing"
                        cases.append({"case_id": item["id"], "request_id": request["request_id"],
                                      "prediction_status": status,
                                      "prediction": deepcopy(positions["valid"].get(pos)),
                                      "raw_prediction": deepcopy(positions["supplied"].get(pos)) if status == "invalid" else None,
                                      "evidence_url": evidence_url(run_id, item["id"])})
                contexts.append({"run_id": run_id, "config_id": config["id"], "prompt_id": prompt["id"],
                                 "repeat": repeat, "model": config["model"], "cases": cases,
                                 "evidence_url": evidence_url(run_id)})
    return contexts


def _runs(evaluation, contexts, references, fields, coverage):
    passes = {(condition["config_id"], condition["prompt_id"], entry["repeat"]): entry
              for condition in evaluation["conditions"] for entry in condition["passes"]}
    result = []
    for context in contexts:
        entry = passes[(context["config_id"], context["prompt_id"], context["repeat"])]
        cases, n = context["cases"], entry["denominator"]
        stats = {}
        for field in fields:
            name = field["name"]
            known = coverage["fields"][name]["reference_denominator"]
            correct = sum(case["prediction"] is not None and name in references.get(case["case_id"], {}) and
                          case["prediction"][name] == references[case["case_id"]][name] for case in cases)
            stats[name] = {**deepcopy(entry["fields"][name]),
                           "correct": correct if known else None,
                           "accuracy": correct / known if known else None,
                           "reference_denominator": known, "reference_missing": n - known,
                           "reference_coverage": known / n}
        full = len(coverage["fully_labeled_ids"])
        exact = (entry["all_field_exact"] if coverage["status"] == "complete" else entry["scored_subset"]["all_field_exact"])
        result.append({key: deepcopy(context[key]) for key in ("run_id", "config_id", "prompt_id", "repeat", "model", "evidence_url")} | {
            "counts": {"planned": n, "valid": n - entry["missing"] - entry["invalid"],
                       "invalid": entry["invalid"], "missing": entry["missing"]},
            "all_fields": {"planned_denominator": n, "reference_denominator": full,
                           "correct": exact, "reference_rate": exact / full if full else None,
                           "full_denominator_rate": entry["all_field_exact_rate"]},
            "fields": stats})
    return result


def _number_delta(before, after):
    return after - before if before is not None and after is not None else None


def _metric_delta(before, after):
    """Subtract nested numeric evaluator metrics, retaining unavailable values."""
    if isinstance(before, dict) and isinstance(after, dict):
        # Core unscored counts are sparse, so absent class keys mean zero.
        return {key: _metric_delta(before.get(key, 0), after.get(key, 0)) for key in dict.fromkeys([*before, *after])}
    return _number_delta(before, after)


def _case_delta(context, old, new, changed_fields, field_names):
    case, prediction = context["case_id"], context["prediction"]
    before, after = old.get(case, {}), new.get(case, {})
    full = len(before) == len(field_names)
    exact_before = int(prediction == before) if full else None
    exact_after = int(prediction == after) if full else None
    fields = {}
    for name in changed_fields:
        baseline = int(prediction is not None and prediction[name] == before[name])
        hypothetical = int(prediction is not None and prediction[name] == after[name])
        fields[name] = {"saved_reference": before[name], "hypothetical_reference": after[name],
                        "prediction": prediction[name] if prediction is not None else None,
                        "baseline_credit": baseline, "hypothetical_credit": hypothetical,
                        "delta": hypothetical - baseline}
    return {**deepcopy(context), "reference_status": "full" if full else "partial",
            "saved_reference": deepcopy(before), "hypothetical_reference": deepcopy(after),
            "all_fields": {"baseline_credit": exact_before, "hypothetical_credit": exact_after,
                           "delta": _number_delta(exact_before, exact_after)}, "fields": fields}


def build_sensitivity(task, plan, predictions, labels=None, scenarios=None):
    """Evaluate explicit alternative labels without changing coverage or sources.

    ``scenarios`` is a list of ``{id, title, provenance, changes}`` objects.
    A change is ``{id: case_id, labels: {field: alternative_label}}``. All keys
    are strict. Missing references, invalid alternatives and no-op changes are
    errors. Every scenario is independent and starts from the saved references.
    """
    positions = validated_positions(task, plan, predictions)
    case_ids = positions["record_ids"]
    references = validate_reference_labels(labels, task, case_ids, allow_partial=True)
    declared = _validate_scenarios(scenarios, task, case_ids, references)
    sources = {"task": _hash(task, "task"), "plan": _hash(plan, "plan"),
               "predictions": _hash(predictions, "predictions"),
               "labels": _hash(labels, "labels") if labels is not None else None,
               "scenarios": _hash(scenarios, "scenarios") if scenarios is not None else None}
    coverage = _coverage(case_ids, references, task["fields"])
    contexts = _run_contexts(task, plan, positions)
    evaluation = evaluate(task, plan, labels, predictions, allow_partial_references=True)
    baseline = {"evaluation": evaluation, "evaluation_sha256": _digest(evaluation),
                "runs": _runs(evaluation, contexts, references, task["fields"], coverage)}
    results = []
    for declaration in declared:
        alternative = deepcopy(labels)
        changes = {change["id"]: change["labels"] for change in declaration["changes"]}
        for record in alternative["records"]:
            record["labels"].update(changes.get(record["id"], {}))
        hypothetical_references = deepcopy(references)
        for case, changed in changes.items():
            hypothetical_references[case].update(changed)
        hypothetical_evaluation = evaluate(task, plan, alternative, predictions, allow_partial_references=True)
        hypothetical_runs = _runs(hypothetical_evaluation, contexts, hypothetical_references, task["fields"], coverage)
        runs = []
        for base, hypo, context in zip(baseline["runs"], hypothetical_runs, contexts):
            affected = [_case_delta(case, references, hypothetical_references, changes[case["case_id"]],
                                   [field["name"] for field in task["fields"]])
                        for case in context["cases"] if case["case_id"] in changes]
            runs.append({**hypo, "baseline_all_fields": deepcopy(base["all_fields"]),
                         "all_fields_delta": _metric_delta(base["all_fields"], hypo["all_fields"]),
                         "baseline_fields": deepcopy(base["fields"]),
                         "field_deltas": _metric_delta(base["fields"], hypo["fields"]),
                         "gained_ids": [case["case_id"] for case in affected if case["all_fields"]["delta"] == 1],
                         "lost_ids": [case["case_id"] for case in affected if case["all_fields"]["delta"] == -1],
                         "case_deltas": affected})
        deltas = [run["all_fields_delta"]["correct"] for run in runs]
        summary = {"planned_runs": len(runs), "scored_runs": sum(delta is not None for delta in deltas),
                   "improved_runs": sum(delta is not None and delta > 0 for delta in deltas),
                   "declined_runs": sum(delta is not None and delta < 0 for delta in deltas),
                   "unchanged_runs": sum(delta == 0 for delta in deltas),
                   "unavailable_runs": sum(delta is None for delta in deltas),
                   "exact_count_delta_range": [min(deltas), max(deltas)] if all(delta is not None for delta in deltas) else None}
        scenario = {**deepcopy(declaration), "hypothetical": True, "status": "hypothetical_not_applied",
                    "scenario_sha256": _digest(declaration), "source_hashes": deepcopy(sources),
                    "hypothetical_labels_sha256": _digest(alternative),
                    "evaluation": hypothetical_evaluation, "evaluation_sha256": _digest(hypothetical_evaluation),
                    "changed_ids": [case for case in case_ids if case in changes],
                    "changed_field_labels": sum(len(value) for value in changes.values()),
                    "reference_coverage": deepcopy(coverage), "summary": summary, "runs": runs}
        scenario["result_sha256"] = _digest(scenario)
        results.append(scenario)
    result = {"schema_version": VERSION, "source_hashes": sources, "task": deepcopy(task),
              "status": "unavailable" if not coverage["known_field_labels"] else "available" if results else "no_scenarios",
              "reference_coverage": coverage, "positions": len(positions["positions"]),
              "baseline": baseline, "scenarios": results,
              "scope": "Each hypothetical scenario independently rescored the same saved predictions against explicit operator alternatives.",
              "limitations": ["Saved references and prior evaluations are unchanged. Alternatives are operator declarations, not adjudicated corrections.",
                              "Reference coverage and planned denominators stay fixed. Whole-run accuracy is unavailable with incomplete references.",
                              "Missing and invalid predictions earn no agreement credit where a reference is known and remain in the denominator.",
                              "Repeated cases and run counts are descriptive observations, not independent samples or deployment evidence."]}
    result["sensitivity_id"] = _digest(result)
    return result


def _display(value, *, signed=False, rate=False):
    if value is None:
        return "Unavailable"
    return f"{value:+.3f}" if signed and rate else f"{value:.3f}" if rate else f"{value:+d}" if signed else str(value)


def render_sensitivity(data):
    """Return an offline report fragment with native details and a scenario selector.

    All operator text is HTML-escaped. JavaScript uses DOM text content only and
    has no embedded user data, fetching, timers or external dependencies. Native
    details remain usable with JavaScript disabled.
    """
    h = lambda value: escape(str(value), quote=True)
    panels = []
    for index, scenario in enumerate(data["scenarios"]):
        summary = scenario["summary"]
        rows, details = [], []
        for run in scenario["runs"]:
            label = f"{run['config_id']} / {run['prompt_id']} / repeat {run['repeat']}"
            old, new = run["baseline_all_fields"], run["all_fields"]
            delta = run["all_fields_delta"]
            rows.append(f"<tr><th scope='row'><a href='{h(run['evidence_url'])}'>{h(label)}</a></th>"
                        f"<td>{run['counts']['planned']}</td><td>{run['counts']['valid']} / {run['counts']['invalid']} / {run['counts']['missing']}</td>"
                        f"<td>{new['reference_denominator']}</td><td>{_display(old['correct'])}</td>"
                        f"<td>{_display(new['correct'])}</td><td>{_display(delta['correct'], signed=True)}</td></tr>")
            field_rows, class_details = [], []
            for name, stats in run["fields"].items():
                before, change = run["baseline_fields"][name], run["field_deltas"][name]
                field_rows.append(f"<tr><th scope='row'>{h(name)}</th><td>{stats['reference_denominator']} / {run['counts']['planned']}</td>"
                                  f"<td>{_display(before['correct'])}</td><td>{_display(stats['correct'])}</td>"
                                  f"<td>{_display(change['correct'], signed=True)}</td><td>{_display(before['macro_f1'], rate=True)}</td>"
                                  f"<td>{_display(stats['macro_f1'], rate=True)}</td><td>{_display(change['macro_f1'], rate=True, signed=True)}</td></tr>")
                classes = []
                for label_name, values in (stats["labels"] or {}).items():
                    base_values, delta_values = before["labels"][label_name], change["labels"][label_name]
                    cells = "".join(f"<td>{_display(base_values[key], rate=key in ('precision', 'recall', 'f1'))} → "
                                    f"{_display(values[key], rate=key in ('precision', 'recall', 'f1'))} "
                                    f"({_display(delta_values[key], signed=True, rate=key in ('precision', 'recall', 'f1'))})</td>"
                                    for key in ("support", "tp", "fp", "fn", "precision", "recall", "f1"))
                    classes.append(f"<tr><th scope='row'>{h(label_name)}</th>{cells}</tr>")
                matrix_changes = []
                for actual, predicted in (change["confusion"] or {}).items():
                    for predicted_label, amount in predicted.items():
                        if amount:
                            matrix_changes.append(f"<li>Reference {h(actual)}, prediction {h(predicted_label)}: {_display(amount, signed=True)}</li>")
                unscored = [f"<li>Unavailable prediction with reference {h(label_name)}: {_display(amount, signed=True)}</li>"
                            for label_name, amount in change["unscored_by_true_label"].items() if amount]
                class_details.append(f"<details><summary>Class and confusion deltas: {h(name)}</summary>"
                                     "<p>The evaluator records zero precision when TP + FP is zero, zero recall when TP + FN is zero, "
                                     "and zero F1 when precision + recall is zero. These arithmetic conventions also enter macro F1; "
                                     "a class with no reference support has no measured recall.</p>"
                                     + (_table("Saved → hypothetical (signed delta)", ["Label", "Support", "TP", "FP", "FN", "Precision", "Recall", "F1"], classes)
                                        if classes else "<p>Class metrics are unavailable because this field has no known references.</p>")
                                     + ("<ul>" + "".join(matrix_changes + unscored) + "</ul>" if matrix_changes or unscored else "<p>No confusion or unavailable-prediction count changed.</p>") + "</details>")
            case_rows = []
            for case in run["case_deltas"]:
                effects = "".join(f"<li>{h(name)}: saved {h(effect['saved_reference'])} → hypothetical {h(effect['hypothetical_reference'])}; "
                                  f"prediction {h(effect['prediction']) if effect['prediction'] is not None else 'Unavailable'}; "
                                  f"agreement credit {effect['baseline_credit']} → {effect['hypothetical_credit']} "
                                  f"({_display(effect['delta'], signed=True)})</li>" for name, effect in case["fields"].items())
                case_rows.append(f"<tr><th scope='row'><a href='{h(case['evidence_url'])}'>{h(case['case_id'])}</a></th>"
                                 f"<td>{h(case['prediction_status'])}</td><td>{h(case['reference_status'])}</td>"
                                 f"<td>{_display(case['all_fields']['delta'], signed=True)}</td><td><ul>{effects}</ul></td></tr>")
            details.append(f"<details class='sensitivity-run'><summary>Field and case evidence: {h(label)}</summary>"
                           + _table("Field agreement uses each field's known-reference denominator", ["Field", "References / planned", "Saved correct", "Hypothetical correct", "Delta", "Saved macro F1", "Hypothetical macro F1", "Delta"], field_rows)
                           + "".join(class_details)
                           + _table("Every changed reference case, including invalid or missing predictions", ["Case evidence", "Prediction status", "Reference status", "Exact delta", "Changed fields"], case_rows) + "</details>")
        panels.append(f"<article data-sensitivity-scenario='{index}'><h3>Hypothetical: {h(scenario['title'])}</h3>"
                      f"<p class='sensitivity-provenance'>Scenario {h(scenario['id'])}. Operator provenance: {h(scenario['provenance'])}</p>"
                      f"<p>{scenario['changed_field_labels']} alternative field labels across {len(scenario['changed_ids'])} cases. "
                      f"{summary['improved_runs']} runs gain exact agreement credit, {summary['declined_runs']} lose credit, "
                      f"{summary['unchanged_runs']} keep the same credit and {summary['unavailable_runs']} have unavailable exact metrics. "
                      "These are counts of runs, not independent samples.</p>"
                      + _table("Exact agreement credit on the fixed fully referenced case subset", ["Run evidence", "Planned", "Valid / invalid / missing", "Full references", "Saved correct", "Hypothetical correct", "Delta"], rows)
                      + "".join(details) + f"<details><summary>Scenario source hashes</summary><dl><dt>Scenario</dt><dd>{h(scenario['scenario_sha256'])}</dd>"
                      f"<dt>Result</dt><dd>{h(scenario['result_sha256'])}</dd><dt>Hypothetical reference document</dt><dd>{h(scenario['hypothetical_labels_sha256'])}</dd>"
                      "</dl></details></article>")
    coverage = data["reference_coverage"]
    options = "".join(f"<option value='{index}'>Hypothetical: {h(scenario['title'])}</option>" for index, scenario in enumerate(data["scenarios"]))
    unavailable = "<p>No sensitivity score is available because no reference field is known. Classification validity remains available in the report.</p>" if data["status"] == "unavailable" else "<p>No hypothetical scenario was declared. Supply operator-authored alternatives to inspect sensitivity.</p>"
    return (_STYLE + "<section class='reference-sensitivity' id='reference-sensitivity' aria-labelledby='reference-sensitivity-heading'>"
            "<h2 id='reference-sensitivity-heading'>Hypothetical reference sensitivity</h2>"
            "<p>Inspect how explicit alternative labels change agreement with saved predictions. Saved references and earlier evaluations remain unchanged.</p>"
            f"<p>{len(coverage['fully_labeled_ids'])}/{coverage['planned_cases']} cases have all reference fields; "
            f"{coverage['known_field_labels']}/{coverage['expected_field_labels']} field references are known. "
            "Whole-run accuracy is unavailable when references are incomplete.</p>"
            + (f"<div class='sensitivity-selector'><label for='sensitivity-scenario'>Choose a hypothetical scenario</label>"
               f"<select id='sensitivity-scenario'>{options}</select><p id='sensitivity-selection-status' role='status' aria-live='polite'></p></div>" + "".join(panels) if panels else unavailable)
            + "<aside aria-label='Sensitivity limits'><ul>" + "".join(f"<li>{h(text)}</li>" for text in data["limitations"]) + "</ul></aside>"
            + f"<details><summary>Saved source identity</summary><dl><dt>Sensitivity</dt><dd>{h(data['sensitivity_id'])}</dd>"
            + "".join(f"<dt>{h(key)}</dt><dd>{h(value) if value is not None else 'Unavailable'}</dd>" for key, value in data["source_hashes"].items())
            + "</dl></details></section>" + _SCRIPT)


def _table(caption, headings, rows):
    return ("<div class='sensitivity-table-scroll' role='region' tabindex='0' aria-label='" + escape(caption, quote=True) + "'>"
            "<table><caption>" + escape(caption) + "</caption><thead><tr>"
            + "".join("<th scope='col'>" + escape(heading) + "</th>" for heading in headings)
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


_STYLE = """<style>
.reference-sensitivity{margin-block:3rem;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.reference-sensitivity h2{letter-spacing:-.035em}.reference-sensitivity h3{margin:.5rem 0;font-size:1.45rem;letter-spacing:-.025em}
.reference-sensitivity p{max-width:72ch;line-height:1.6}.reference-sensitivity article{padding:1.8rem 0;border-top:1px solid var(--line,#dcded8)}
.reference-sensitivity .sensitivity-provenance{font-size:.85rem;color:var(--muted,#59635d)}
.reference-sensitivity summary{cursor:pointer;padding:.85rem 0;line-height:1.5}.reference-sensitivity details{border-top:1px solid var(--line,#dcded8);margin-top:.5rem}
.reference-sensitivity .sensitivity-table-scroll{overflow-x:auto;max-width:100%;margin-block:1rem}
.reference-sensitivity table{width:100%;border-collapse:collapse;min-width:42rem;font-size:.86rem}
.reference-sensitivity caption{text-align:left;font-weight:600;padding-bottom:.7rem}.reference-sensitivity th,.reference-sensitivity td{padding:.7rem .6rem;text-align:left;vertical-align:top;border-bottom:1px solid var(--line,#dcded8)}
.reference-sensitivity thead{background:var(--panel,#eef1ec)}.reference-sensitivity td{font-variant-numeric:tabular-nums}
.reference-sensitivity .sensitivity-selector{display:none}.reference-sensitivity.sensitivity-enhanced .sensitivity-selector{display:block;margin-block:1.2rem}
.reference-sensitivity select{display:block;max-width:100%;padding:.65rem;margin-top:.4rem;font:inherit;background:var(--panel,#eef1ec);color:inherit;border:1px solid var(--line,#b7c1b8);border-radius:.3rem}
.reference-sensitivity :is(a,select,summary,[tabindex]):focus-visible{outline:3px solid var(--accent,#245b4b);outline-offset:3px}
.reference-sensitivity a{color:var(--accent,#245b4b)}.reference-sensitivity [hidden]{display:none!important}
.reference-sensitivity dd{margin:0 0 .7rem;font-family:monospace;font-size:.8rem}.reference-sensitivity dt{font-weight:600}
@media(max-width:40rem){.reference-sensitivity article{padding:1.2rem 0}.reference-sensitivity h3{font-size:1.2rem}}
@media print{.reference-sensitivity .sensitivity-selector{display:none!important}.reference-sensitivity article[hidden]{display:block!important}.reference-sensitivity .sensitivity-table-scroll{overflow:visible}.reference-sensitivity table{min-width:0}}
</style>"""

_SCRIPT = """<script>(()=>{const root=document.getElementById('reference-sensitivity');
if(!root)return;const select=root.querySelector('#sensitivity-scenario');if(!select)return;
const panels=[...root.querySelectorAll('[data-sensitivity-scenario]')];
const status=root.querySelector('#sensitivity-selection-status');
const update=()=>{panels.forEach(panel=>panel.hidden=panel.dataset.sensitivityScenario!==select.value);
status.textContent=select.selectedOptions[0].textContent+'. Saved references remain unchanged.';};
root.classList.add('sensitivity-enhanced');select.addEventListener('change',update);update();})();</script>"""
