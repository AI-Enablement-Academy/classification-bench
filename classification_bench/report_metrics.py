"""Field metrics over validated report analysis, with explicit undefined ratios.

This view preserves the evaluator's treatment of invalid and missing vectors as
false negatives on known references. It does not change legacy core arithmetic.
"""

from copy import deepcopy
from html import escape

from .core import ValidationError, _digest, validate_task
from .report_findings import evidence_url


def _ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if numerator is not None and denominator else None}


def _cases(run, fields):
    """Fail on inconsistent projections instead of silently repairing evidence."""
    cases = run.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValidationError("field metrics: expected nonempty planned cases")
    ids = [case.get("case_id") if isinstance(case, dict) else None for case in cases]
    if any(not isinstance(value, str) or not value.strip() for value in ids) or len(set(ids)) != len(ids):
        raise ValidationError("field metrics: invalid or duplicate case IDs")
    if run.get("case_ids") != ids:
        raise ValidationError("field metrics: case membership disagrees with run")
    names = {field["name"] for field in fields}
    for case in cases:
        if not {"prediction_status", "prediction", "reference"}.issubset(case):
            raise ValidationError("field metrics: incomplete case projection")
        status, prediction = case.get("prediction_status"), case.get("prediction")
        if status not in ("valid", "invalid", "missing"):
            raise ValidationError("field metrics: unknown prediction status")
        if status == "valid":
            if (not isinstance(prediction, dict) or set(prediction) != names or
                    any(not isinstance(prediction[field["name"]], str) or
                        prediction[field["name"]] not in field["labels"] for field in fields)):
                raise ValidationError("field metrics: invalid declared valid prediction")
        elif prediction is not None:
            raise ValidationError("field metrics: unusable prediction must be null")
        reference = case.get("reference")
        if reference is not None:
            if (not isinstance(reference, dict) or set(reference) - names or
                    any(field["name"] in reference and
                        (not isinstance(reference[field["name"]], str) or
                         reference[field["name"]] not in field["labels"]) for field in fields)):
                raise ValidationError("field metrics: invalid known reference")
    return cases


def _field(field, cases):
    name, labels = field["name"], field["labels"]
    known = [case for case in cases if name in (case["reference"] or {})]
    unknown = [case["case_id"] for case in cases if name not in (case["reference"] or {})]
    matrix_ids = {actual: {predicted: [] for predicted in labels} for actual in labels}
    unscored_ids = {label: [] for label in labels}
    for case in known:
        actual = case["reference"][name]
        if case["prediction_status"] == "valid":
            matrix_ids[actual][case["prediction"][name]].append(case["case_id"])
        else:
            unscored_ids[actual].append(case["case_id"])
    per_label = {}
    legacy_f1 = []
    for label in labels:
        support = [case["case_id"] for case in known if case["reference"][name] == label]
        positive = [case["case_id"] for case in known if case["prediction_status"] == "valid" and
                    case["prediction"][name] == label]
        tp_ids = list(matrix_ids[label][label])
        fp_ids = [case["case_id"] for case in known if case["prediction_status"] == "valid" and
                  case["prediction"][name] == label and case["reference"][name] != label]
        fn_ids = [case["case_id"] for case in known if case["reference"][name] == label and
                  (case["prediction_status"] != "valid" or case["prediction"][name] != label)]
        tp, fp, fn = len(tp_ids), len(fp_ids), len(fn_ids)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        legacy_f1.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
        per_label[label] = {"support": len(support) if known else None,
                            "predicted_positive": len(positive) if known else None,
                            "tp": tp if known else None, "fp": fp if known else None, "fn": fn if known else None,
                            "precision": _ratio(tp if known else None, tp + fp),
                            "recall": _ratio(tp if known else None, tp + fn),
                            "f1": _ratio(2 * tp if known else None, 2 * tp + fp + fn),
                            "support_ids": support, "predicted_positive_ids": positive,
                            "tp_ids": tp_ids, "fp_ids": fp_ids, "fn_ids": fn_ids}
    correct = sum(len(matrix_ids[label][label]) for label in labels)
    counts = {status: sum(case["prediction_status"] == status for case in cases)
              for status in ("valid", "invalid", "missing")}
    known_counts = {status: sum(case["prediction_status"] == status for case in known)
                    for status in ("valid", "invalid", "missing")}
    return {"name": name, "labels": list(labels), "planned": len(cases),
            "known_reference_count": len(known), "unknown_reference_count": len(unknown),
            "known_reference_ids": [case["case_id"] for case in known], "unknown_reference_ids": unknown,
            "reference_coverage": _ratio(len(known), len(cases)),
            "outcomes": counts, "known_reference_outcomes": known_counts,
            "agreement": _ratio(correct if known else None, len(known)),
            "confusion": {actual: {predicted: len(ids) for predicted, ids in row.items()}
                          for actual, row in matrix_ids.items()} if known else None,
            "confusion_ids": matrix_ids if known else None,
            "unscored_by_true_label": {label: len(ids) for label, ids in unscored_ids.items()} if known else None,
            "unscored_ids": unscored_ids if known else None, "per_label": per_label,
            "legacy_macro_f1": sum(legacy_f1) / len(labels) if known else None}


def build_field_metrics(analysis):
    """Project each run once; unknown references never become scoring outcomes."""
    if not isinstance(analysis, dict) or analysis.get("schema_version") != 1:
        raise ValidationError("field metrics: expected analysis schema version 1")
    task = validate_task(analysis.get("task"))
    if not isinstance(analysis.get("analysis_id"), str) or not isinstance(analysis.get("runs"), list):
        raise ValidationError("field metrics: expected analysis identity and runs")
    runs = {}
    for run in analysis["runs"]:
        run_id = run.get("run_id") if isinstance(run, dict) else None
        if not isinstance(run_id, str) or not run_id.strip() or run_id in runs:
            raise ValidationError("field metrics: invalid or duplicate run ID")
        cases = _cases(run, task["fields"])
        runs[run_id] = {"run_id": run_id, "config_id": run["config_id"], "prompt_id": run["prompt_id"],
                        "repeat": run["repeat"], "planned": len(cases),
                        "fields": [_field(field, cases) for field in task["fields"]]}
    result = {"schema_version": 1, "analysis_id": analysis["analysis_id"],
              "source_hashes": deepcopy(analysis.get("source_hashes", {})), "runs": runs,
              "ratio_rule": "precision=TP/(TP+FP); recall=TP/(TP+FN); F1=2TP/(2TP+FP+FN); zero denominators are unavailable",
              "legacy_macro_rule": "core assigns zero to undefined label ratios and averages F1 across every declared label"}
    result["metrics_id"] = _digest(result)
    return result


def _h(value):
    return escape(str(value), quote=True)


def _rate(ratio, reason):
    if ratio["value"] is None:
        return "unavailable (" + reason + ")"
    return f"{ratio['numerator']}/{ratio['denominator']} ({ratio['value']:.1%})"


def _count(value, ids, run_id, description):
    if value is None:
        return "unavailable"
    if not ids:
        return str(value)
    url = evidence_url(run_id, ids[0])
    return f"<a href='{_h(url)}' aria-label='{_h(description + ': inspect first of ' + str(value) + ' cases')}'>{value}</a>"


_CSS = """<style>
.field-metrics{margin:1.5rem 0;border-top:1px solid var(--line,#dcded8);padding-top:1rem;min-width:0}
.field-metrics h5{font-size:1rem;margin:.2rem 0 .75rem}.field-metrics p{max-width:70ch}
.field-metrics .metric-scroll{max-width:100%;overflow-x:auto;margin:.8rem 0 1rem;border:1px solid var(--line,#dcded8)}
.field-metrics table{margin:0;min-width:42rem;font-variant-numeric:tabular-nums}
.field-metrics caption{text-align:left;padding:.7rem .8rem;color:var(--muted,#59635d);font-weight:600}
.field-metrics .numeric{text-align:right;white-space:nowrap}.field-metrics th[scope=row]{overflow-wrap:anywhere;max-width:16rem}
.field-metrics .metric-scroll:focus-visible,.field-metrics a:focus-visible{outline:3px solid var(--accent,#245b4b);outline-offset:3px}
@media(max-width:600px){.field-metrics{margin:1rem 0}.field-metrics table{font-size:.8rem}.field-metrics th,.field-metrics td{padding:.55rem}}
</style>"""


def _table(headers, rows, caption, caption_id):
    head = "".join(f"<th scope='col'>{_h(header)}</th>" for header in headers)
    body = "".join("<tr><th scope='row'>" + row[0] + "</th>" +
                   "".join(f"<td class='numeric'>{cell}</td>" for cell in row[1:]) + "</tr>" for row in rows)
    return (f"<div class='metric-scroll' tabindex='0' role='region' aria-labelledby='{_h(caption_id)}'>"
            f"<table><caption id='{_h(caption_id)}'>{_h(caption)}</caption><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def render_field_metrics(run_metrics, *, id_prefix):
    """Render per-label counts and full matrices; count links inspect exact cases."""
    parts = ["<h4>Per-label metrics and full confusion</h4>"]
    scope = f"{run_metrics['config_id']}, {run_metrics['prompt_id']}, pass {run_metrics['repeat']}"
    for index, field in enumerate(run_metrics["fields"]):
        field_id = f"{id_prefix}-field-{index}"
        known, planned = field["known_reference_count"], field["planned"]
        outcomes, referenced = field["outcomes"], field["known_reference_outcomes"]
        parts.append(f"<section class='field-metrics' id='{_h(field_id)}' aria-labelledby='{_h(field_id)}-heading'>"
                     f"<h5 id='{_h(field_id)}-heading'>{_h(field['name'])}: class metrics</h5>"
                     f"<p>Reference coverage: {known}/{planned} planned cases; {field['unknown_reference_count']} unknown references. "
                     f"Output validity: {outcomes['valid']}/{planned} valid, {outcomes['invalid']} invalid, {outcomes['missing']} missing. "
                     f"Known-reference agreement: {_rate(field['agreement'], 'no known references')}.</p>")
        parts.append(f"<p>Among known references: {referenced['valid']} valid predictions, {referenced['invalid']} invalid, {referenced['missing']} missing. "
                     "Invalid and missing full predictions remain false negatives for their known reference class. "
                     "Unknown references are excluded from class support, confusion and reference scores.</p>")
        rows = []
        for label in field["labels"]:
            values = field["per_label"][label]
            cells = [_h(label)]
            for key in ("support", "predicted_positive", "tp", "fp", "fn"):
                cells.append(_count(values[key], values[key + "_ids"], run_metrics["run_id"], f"{field['name']}, {label}, {key}"))
            reason = "no known references" if not known else None
            cells.extend(_h(_rate(values[key], reason or explanation)) for key, explanation in
                         (("precision", "no predicted positives"), ("recall", "no actual positives"),
                          ("f1", "no actual or predicted positives")))
            rows.append(cells)
        parts.append(_table(("Label", "Reference support", "Predicted positives", "TP", "FP", "FN", "Precision", "Recall", "F1"),
                            rows, f"Per-label metrics for {field['name']}; {scope}; {known} known references / {planned} planned cases",
                            field_id + "-labels-caption"))
        parts.append("<p>TP: matching valid predictions. FP: valid predictions of this class with another known reference. "
                     "FN: another predicted class, an invalid full prediction, or missing output for this reference class. "
                     "Precision = TP / (TP + FP); recall = TP / (TP + FN); F1 = 2TP / (2TP + FP + FN). "
                     "A zero denominator is unavailable. Count links open the first supporting case in this run.</p>")
        if field["confusion"] is None:
            parts.append("<p>Confusion matrix unavailable: no known references for this field.</p>")
        else:
            matrix_rows = []
            for label in field["labels"]:
                cells = [_h(label)]
                for predicted in field["labels"]:
                    cells.append(_count(field["confusion"][label][predicted], field["confusion_ids"][label][predicted],
                                        run_metrics["run_id"], f"{field['name']}, reference {label}, predicted {predicted}"))
                cells.append(_count(field["unscored_by_true_label"][label], field["unscored_ids"][label],
                                    run_metrics["run_id"], f"{field['name']}, reference {label}, invalid or missing prediction"))
                matrix_rows.append(cells)
            parts.append(_table(("Reference / prediction", *field["labels"], "No valid prediction (invalid or missing)"), matrix_rows,
                                f"Full confusion for {field['name']}; {scope}; rows are references, columns are valid predictions; {known} known references / {planned} planned cases",
                                field_id + "-confusion-caption"))
        macro = f"{field['legacy_macro_f1']:.3f}" if field["legacy_macro_f1"] is not None else "unavailable"
        parts.append(f"<p>Legacy evaluator macro F1: {macro}. The evaluator assigns zero to undefined precision, recall and F1, "
                     "then averages F1 across every declared label. That existing convention is separate from the unavailable label ratios shown here.</p></section>")
    return _CSS + "".join(parts)
