"""Explicit private and sanitized download projections of validated analysis.

Sanitized means source text and identity strings are omitted, not a guarantee of
anonymity. No raw response, credentials, environment or arbitrary operation
metadata is exported in either projection.
"""

from copy import deepcopy
import base64
import gzip
import hashlib
from html import escape
import json

from .core import ValidationError, _digest
from .model_metadata import export_model_metadata


_COUNTS = ("planned", "valid", "invalid", "missing", "full_reference", "partial_reference",
           "no_reference", "exact_correct", "known_reference_exact_rate",
           "full_denominator_exact_rate", "validity_rate")
_COST = ("planned_requests", "observed_cost_requests", "observed_cost_micro_usd", "complete",
         "partial_observed_cost_micro_usd", "unresolved_hold_micro_usd", "synthetic_excluded_requests",
         "subscription_invocations", "unresolved_subscription_invocations")
_TRANSITIONS = ("gained_ids", "lost_ids", "stable_correct_ids", "stable_error_ids",
                "reference_unknown_ids", "unusable_to_valid_ids", "valid_to_unusable_ids", "unusable_both_ids")
_PAIR = ("accepted", "accepted_correct", "accepted_error", "accepted_reference_unknown", "deferred", "planned", "acceptance_rate")
_SOURCE_KEYS = ("task", "plan", "predictions", "labels", "operations", "cohort_declarations")


def _hash(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValidationError("report export: expected a source digest, not raw metadata")
    return value


def _numbers(value, keys):
    result = {}
    for key in keys:
        if key not in value:
            continue
        item = value[key]
        if item is not None and type(item) not in (int, float, bool):
            raise ValidationError("report export: invalid numeric measure")
        result[key] = item
    return result


def build_report_exports(analysis, *, findings=None, field_metrics=None, sensitivity=None):
    """Create canonical UTF-8 downloads; return exact payload byte hashes.

Input must come from build_analysis. Downloading is an explicit browser action,
not automatic publication. Private is also allowlisted; opaque provider payloads
and operation strings are not copied even when their parent object is supplied.
"""
    sources = {name: _hash(analysis["source_hashes"].get(name)) for name in _SOURCE_KEYS}
    fields = analysis["task"]["fields"]
    case_hashes = {cid: _digest({"task": sources["task"], "case_id": cid}) for cid in analysis["case_ids"]}
    for projection in (findings, field_metrics):
        if projection is not None and projection.get("analysis_id") != analysis["analysis_id"]:
            raise ValidationError("report export: analysis identity mismatch")
    if sensitivity is not None and any(sensitivity.get("source_hashes", {}).get(name) != sources[name]
                                       for name in ("task", "plan", "predictions", "labels")):
        raise ValidationError("report export: sensitivity source mismatch")

    def bundle(private):
        case_id = (lambda value: value) if private else (lambda value: case_hashes[value])
        def ids(values):
            return [case_id(value) for value in values]
        def field_stats(value, index, *, detailed=False):
            labels = fields[index]["labels"]
            item = {"field_index": index, **_numbers(value, (
                "planned", "known_reference_count", "unknown_reference_count", "legacy_macro_f1",
                "correct", "accuracy", "reference_denominator", "reference_missing", "macro_f1"))}
            if private:
                item["name"] = fields[index]["name"]
            classes = value.get("per_label") if detailed else value.get("labels")
            item["classes"] = [] if classes is not None else None
            for label_index, label in enumerate(labels) if classes is not None else ():
                stats = classes[label]
                row = {"label": label if private else label_index,
                       **_numbers(stats, ("support", "tp", "fp", "fn", "predicted_positive"))}
                for measure in ("precision", "recall", "f1"):
                    row[measure] = (_numbers(stats[measure], ("numerator", "denominator", "value")) if detailed
                                    else stats[measure])
                if detailed:
                    row.update({name: ids(stats[name]) for name in
                                ("support_ids", "predicted_positive_ids", "tp_ids", "fp_ids", "fn_ids")})
                item["classes"].append(row)
            matrix = value.get("confusion")
            item["confusion"] = [[matrix[a][b] for b in labels] for a in labels] if matrix is not None else None
            unscored = value.get("unscored_by_true_label")
            item["unscored_by_true_label"] = [unscored.get(label, 0) for label in labels] if unscored is not None else None
            if detailed:
                item.update({name: _numbers(value[name], ("numerator", "denominator", "value"))
                             for name in ("reference_coverage", "agreement")})
                item.update({name: ids(value[name]) for name in ("known_reference_ids", "unknown_reference_ids")})
                item.update({name: _numbers(value[name], ("valid", "invalid", "missing"))
                             for name in ("outcomes", "known_reference_outcomes")})
            else:
                item["reference_coverage"] = value["reference_coverage"]
            return item
        runs = []
        for run in analysis["runs"]:
            cases = []
            for case in run["cases"]:
                item = {"case_id": case_id(case["case_id"]), "request_id": _hash(case["request_id"]),
                        "prediction_status": case["prediction_status"], "reference_status": case["reference_status"],
                        "exact_match": case["exact_match"]}
                if private:
                    item.update(input=deepcopy(case["input"]), prediction=deepcopy(case["prediction"]),
                                reference=deepcopy(case["reference"]))
                else:
                    vector = lambda values: [field["labels"].index(values[field["name"]])
                                             if values and field["name"] in values else None for field in fields]
                    item.update(prediction=vector(case["prediction"]), reference=vector(case["reference"]))
                cases.append(item)
            item = {"run_id": _hash(run["run_id"]), "configuration_sha256": _hash(run["configuration_sha256"]),
                    "prompt_sha256": _hash(run["prompt_sha256"]), "repeat": run["repeat"],
                    "counts": _numbers(run["counts"], _COUNTS), "cost": _numbers(run["cost"], _COST), "cases": cases}
            if private:
                item.update(config_id=run["config_id"], prompt_id=run["prompt_id"], model=run["model"])
            if "model_metadata" in run.get("configuration", {}):
                item["model_metadata"] = export_model_metadata(run["configuration"], private=private)
            if field_metrics is not None:
                item["field_metrics"] = [field_stats(value, index, detailed=True) for index, value in
                                         enumerate(field_metrics["runs"][run["run_id"]]["fields"])]
            runs.append(item)
        pairs = []
        for pair in analysis["agreement_pairs"]:
            pairs.append({"pair_id": _hash(pair["pair_id"]), "run_a": _hash(pair["run_a"]), "run_b": _hash(pair["run_b"]),
                          **_numbers(pair, _PAIR), "cost": _numbers(pair["cost"], _COST),
                          **{name + "_ids": ids(pair[name + "_ids"]) for name in
                             ("accepted_correct", "accepted_error", "accepted_reference_unknown", "deferred")}})
        prompts = [{"run_a": _hash(pair["run_a"]), "run_b": _hash(pair["run_b"]),
                    **_numbers(pair, ("net_gain", "scored_reference_cases", "planned")),
                    **{key: ids(pair[key]) for key in _TRANSITIONS}} for pair in analysis["prompt_comparisons"]]
        cohorts = []
        for cohort in analysis["cohorts"]:
            item = {"cohort_id": cohort["id"] if private else _digest({"cohort_id": cohort["id"], "sources": sources}),
                    "run_ids": [_hash(value) for value in cohort["run_ids"]],
                    "case_ids": ids(cohort["case_ids"]), "planned_runs": cohort["planned_runs"],
                    "distinct_configurations": cohort["distinct_configurations"],
                    "disagreement_ids": ids(cohort["disagreement_ids"]),
                    "reference_error_ids": ids(cohort["reference_error_ids"]), "unusable_ids": ids(cohort["unusable_ids"])}
            if private:
                item.update(title=cohort["title"], origin=cohort["origin"], source=cohort["source"])
            cohorts.append(item)
        exported_findings = []
        for finding in (findings or {}).get("findings", []):
            item = {"finding_id": _hash(finding["finding_id"]), "run_ids": [_hash(value) for value in finding["run_ids"]],
                    "case_ids": ids(finding["case_ids"]), "denominator": finding["denominator"]}
            if private:
                item.update({key: finding[key] for key in ("kind", "title", "observation", "scope", "next_step")})
            exported_findings.append(item)
        scenarios = None
        if sensitivity is not None:
            scenarios = {"sensitivity_id": _hash(sensitivity["sensitivity_id"]), "hypothetical": True,
                         "scenario_source_sha256": _hash(sensitivity["source_hashes"]["scenarios"]), "scenarios": []}
            all_field_keys = ("planned_denominator", "reference_denominator", "correct", "reference_rate", "full_denominator_rate")
            for scenario in sensitivity["scenarios"]:
                item = {"scenario_sha256": _hash(scenario["scenario_sha256"]),
                        "result_sha256": _hash(scenario["result_sha256"]),
                        "hypothetical_labels_sha256": _hash(scenario["hypothetical_labels_sha256"]),
                        "hypothetical": True, "changed_ids": ids(scenario["changed_ids"]), "runs": []}
                if private:
                    item.update({key: scenario[key] for key in ("id", "title", "provenance")})
                for run in scenario["runs"]:
                    item["runs"].append({"run_id": _hash(run["run_id"]),
                        "counts": _numbers(run["counts"], ("planned", "valid", "invalid", "missing")),
                        **{key: _numbers(run[key], all_field_keys) for key in
                           ("baseline_all_fields", "all_fields", "all_fields_delta")},
                        "gained_ids": ids(run["gained_ids"]), "lost_ids": ids(run["lost_ids"]),
                        "fields": [field_stats(run["fields"][field["name"]], index) for index, field in enumerate(fields)],
                        "baseline_fields": [field_stats(run["baseline_fields"][field["name"]], index) for index, field in enumerate(fields)]})
                scenarios["scenarios"].append(item)
        return {"schema_version": 1, "analysis_id": _hash(analysis["analysis_id"]), "source_hashes": sources,
                "field_metrics_id": _hash(field_metrics["metrics_id"]) if field_metrics is not None else None,
                "visibility": "private" if private else "sanitized",
                "privacy_note": ("Includes input text and reference labels; keep private." if private else
                                 "Omits source text, raw IDs, taxonomy names and narrative. IDs are pseudonymous; aggregate data may still be sensitive."),
                "fields": deepcopy(fields) if private else [{"field_index": i, "label_count": len(field["labels"])} for i, field in enumerate(fields)],
                "task_name": analysis["task"]["name"] if private else None,
                "runs": runs, "prompt_comparisons": prompts, "agreement_pairs": pairs,
                "cohorts": cohorts, "findings": exported_findings, "sensitivity": scenarios,
                "limitations": ["Repeated cases and overlapping pairs are not independent samples.",
                                "Subscription invocations are not USD charges; missing charges are unavailable.",
                                "Raw responses, invalid raw predictions, credentials and arbitrary operation metadata are excluded."]}
    result = {}
    for mode in ("sanitized", "private"):
        value = bundle(mode == "private")
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        result[mode] = {"filename": f"benchmark-{analysis['analysis_id'][:12]}-{mode}.json",
                        "payload": payload, "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                        "bytes": len(payload.encode("utf-8"))}
    return result


def render_downloads(exports):
    """Offline user-initiated downloads; private data requires an explicit choice."""
    packed = {}
    for mode, value in exports.items():
        compressed = gzip.compress(value["payload"].encode("utf-8"), mtime=0)
        packed[mode] = {"filename": value["filename"] + ".gz", "base64": base64.b64encode(compressed).decode("ascii"),
                        "sha256": hashlib.sha256(compressed).hexdigest(), "bytes": len(compressed),
                        "json_sha256": value["sha256"], "json_bytes": value["bytes"]}
    data = json.dumps(packed, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    rows = "".join(f"<li>{escape(mode)}: {value['bytes']} compressed bytes; download SHA-256 <code>{value['sha256']}</code>; "
                   f"{value['json_bytes']} uncompressed UTF-8 bytes; JSON SHA-256 <code>{value['json_sha256']}</code></li>"
                   for mode, value in packed.items())
    return ("<section id='downloads' aria-labelledby='downloads-heading'><h2 id='downloads-heading'>Download analysis data</h2>"
            "<p>Sanitized data omits inputs, raw case IDs, field/label names and narrative. It uses pseudonymous IDs and indexed labels; aggregate data may still be sensitive. No download publishes data.</p>"
            "<label for='analysis-export-mode'>Data scope <select id='analysis-export-mode'><option value='sanitized'>Sanitized metrics and indexed decisions</option>"
            "<option value='private'>Private inputs, labels and findings</option></select></label> "
            "<button type='button' id='analysis-export-download'>Download compressed JSON</button>"
            "<p>Open the .json.gz file with a local archive tool to extract JSON. Compression keeps large pair analyses out of the page DOM; it does not encrypt private data.</p>"
            "<p id='analysis-export-notice' role='status' aria-live='polite'>Sanitized projection selected.</p>"
            "<details><summary>Exact download byte hashes</summary><ul>" + rows + "</ul></details>"
            "<noscript>Downloads require JavaScript. The report remains readable offline.</noscript>"
            "<script type='application/json' id='analysis-export-data'>" + data + "</script>"
            "<script>(()=>{'use strict';const values=JSON.parse(document.getElementById('analysis-export-data').textContent);"
            "const mode=document.getElementById('analysis-export-mode'),notice=document.getElementById('analysis-export-notice');"
            "mode.addEventListener('change',()=>{notice.textContent=mode.value==='private'?'Private export includes inputs and reference labels. Keep it private.':'Sanitized projection selected.';});"
            "document.getElementById('analysis-export-download').addEventListener('click',()=>{const selected=values[mode.value];if(!selected)return;"
            "const decoded=atob(selected.base64),bytes=Uint8Array.from(decoded,c=>c.charCodeAt(0));"
            "const url=URL.createObjectURL(new Blob([bytes],{type:'application/gzip'}));"
            "const link=document.createElement('a');link.href=url;link.download=selected.filename;document.body.append(link);link.click();link.remove();"
            "setTimeout(()=>URL.revokeObjectURL(url),1000);notice.textContent='Downloaded '+mode.value+' compressed JSON; no data was uploaded.';});})();</script></section>")
