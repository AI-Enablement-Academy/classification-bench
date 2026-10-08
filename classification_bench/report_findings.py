"""Evidence-linked descriptive findings shared by reports and presentations.

Consumes build_analysis output. No model calls, source mutations, causal claims,
pooled independent-sample claims or estimated monetary measurements.
"""

from collections import defaultdict
from copy import deepcopy
from html import escape
from itertools import combinations
import json
from urllib.parse import urlencode

from .core import _digest
from .report_analysis import compare_runs


def evidence_url(run, case=None, compare=None):
    values = {"run": run}
    if compare is not None:
        values["compareRun"] = compare
    if case is not None:
        values["case"] = case
    return "#case-explorer-heading?" + urlencode(values)


def build_findings(analysis, *, comparative=None, repeats=None):
    """Return deterministic observations and explicitly conditional next steps."""
    findings = []

    def add(kind, title, observation, scope, denominator, runs, cases, next_step, metrics):
        item = {"kind": kind, "title": title, "observation": observation,
                "scope": scope, "denominator": denominator, "run_ids": runs,
                "case_ids": cases, "next_step": next_step, "metrics": metrics,
                "source_hashes": analysis["source_hashes"],
                "interpretation": "Descriptive evidence for this task and selected inputs; no causal or deployment guarantee."}
        item["finding_id"] = _digest({"analysis": analysis["analysis_id"], **item})
        findings.append(deepcopy(item))

    conditions = defaultdict(list)
    for run in analysis["runs"]:
        rid, counts = run["run_id"], run["counts"]
        scope = f"{run['config_id']} / {run['prompt_id']} / repeat {run['repeat']}"
        planned, known = counts["planned"], counts["full_reference"]
        conditions[(run["config_id"], run["prompt_id"])].append(run)
        text = (f"{counts['valid']}/{planned} planned cases have valid predictions; "
                f"{counts['invalid']} are invalid and {counts['missing']} have no selected prediction. "
                f"{known}/{planned} cases have all reference fields.")
        if known:
            text += f" Exact reference agreement is {counts['exact_correct']}/{known} on fully referenced cases."
            if known != planned:
                text += " Whole-run accuracy is unavailable; this is a labeled subset."
        else:
            text += " Accuracy is unavailable because no case has all reference fields."
        text += " Missing and invalid predictions retain their planned positions."
        add("run_coverage", "Output and reference coverage", text, scope, planned, [rid], run["case_ids"],
            "Inspect missing or invalid evidence before planning new inference; adjudicate absent references separately."
            if counts["invalid"] or counts["missing"] or known != planned else
            "Check field-level errors and repeat consistency before drawing a task-specific conclusion.",
            dict(counts))

        for field in analysis["task"]["fields"]:
            name = field["name"]
            known_cases = [c for c in run["cases"] if name in (c["reference"] or {})]
            if not known_cases:
                continue
            errors = [c for c in known_cases if c["field_matches"][name] is False]
            unusable = [c for c in known_cases if c["prediction_status"] != "valid"]
            correct = sum(c["field_matches"][name] is True for c in known_cases)
            confusion = defaultdict(list)
            for case in errors:
                confusion[(case["reference"][name], case["prediction"][name])].append(case["case_id"])
            patterns = [{"reference": a, "prediction": b, "case_ids": ids, "count": len(ids)}
                        for (a, b), ids in sorted(confusion.items())]
            supports = {label: sum(c["reference"][name] == label for c in known_cases)
                        for label in field["labels"]}
            add("field_errors", f"Reference checks: {name}",
                f"{correct}/{len(known_cases)} known field references match; {len(errors)} valid predictions disagree "
                f"and {len(unusable)} have no valid prediction. {planned - len(known_cases)}/{planned} references are unavailable.",
                scope, len(known_cases), [rid], [c["case_id"] for c in errors + unusable],
                "Inspect disagreement inputs and rubric wording; test any revised prompt on a separate frozen evaluation."
                if errors else "Retain missing classes and limited support as limitations when interpreting this field.",
                {"planned": planned, "known_references": len(known_cases), "correct": correct,
                 "valid_errors": len(errors), "unusable": len(unusable), "class_support": supports,
                 "confusion_patterns": patterns})

        cost = run["cost"]
        amount = cost["observed_cost_micro_usd"]
        add("cost_coverage", "Cost evidence",
            (f"Observed USD charges total {amount / 1_000_000:.6f} across "
             f"{cost['observed_cost_requests']}/{cost['planned_requests']} planned requests."
             if amount is not None else "No observed USD charge is available for this run.") +
            (" Coverage is complete." if cost["complete"] else " A total-cost comparison is unavailable because coverage is incomplete.") +
            " Subscription usage and synthetic measurements do not establish dollar charges.",
            scope, cost["planned_requests"], [rid], [],
            "Reconcile provider receipts and unresolved exposure before making a cost recommendation.", dict(cost))

    for pair in analysis["prompt_comparisons"]:
        known, planned = pair["scored_reference_cases"], pair["planned"]
        gains, losses = len(pair["gained_ids"]), len(pair["lost_ids"])
        add("prompt_effect", f"Prompt comparison: {pair['prompt_a']} → {pair['prompt_b']}",
            f"On {known}/{planned} fully referenced cases, the second prompt gains agreement on {gains} "
            f"and loses it on {losses}. {len(pair['reference_unknown_ids'])} cases have unavailable full references. "
            f"Valid-output recovery occurs on {len(pair['unusable_to_valid_ids'])} cases; "
            f"{len(pair['valid_to_unusable_ids'])} move from valid to unusable. These groups may overlap agreement changes.",
            f"{pair['config_id']} / repeat {pair['repeat']}; same configuration and input membership",
            planned, [pair["run_a"], pair["run_b"]],
            list(dict.fromkeys(pair["gained_ids"] + pair["lost_ids"] + pair["unusable_to_valid_ids"] + pair["valid_to_unusable_ids"])),
            "Inspect gains and losses together and repeat the paired comparison before preferring a prompt.",
            {"known_references": known, "gains": gains, "losses": losses, "net_gain": pair["net_gain"]})

    for (config, prompt), runs in conditions.items():
        for a, b in combinations(runs, 2):
            diff = compare_runs(analysis, a["run_id"], b["run_id"])
            add("repeat_consistency", "Repeat consistency",
                f"{diff['changed']}/{diff['comparable']} cases with two valid predictions change labels; "
                f"{diff['excluded']}/{diff['planned']} planned cases lack two valid predictions. "
                "Agreement between repeats does not establish correctness.",
                f"{config} / {prompt}; repeats {a['repeat']} and {b['repeat']}", diff["planned"],
                [a["run_id"], b["run_id"]], diff["changed_ids"] + diff["excluded_ids"],
                "Review changed cases and repeat under the same frozen settings; do not pool repeats as independent samples.",
                {key: diff[key] for key in ("planned", "comparable", "changed", "excluded", "flip_rate")})
    pairs = analysis["agreement_pairs"]
    if pairs:
        minimum = min(pairs, key=lambda pair: pair["accepted"])
        maximum = max(pairs, key=lambda pair: pair["accepted"])
        errors = sum(pair["accepted_error"] > 0 for pair in pairs)
        unknowns = sum(pair["accepted_reference_unknown"] > 0 for pair in pairs)
        planned = pairs[0]["planned"]
        add("agreement_overview", "Agreement is a filter, not proof of correctness",
            f"Across all {len(pairs)} eligible run pairs, accepted cases range from {minimum['accepted']} "
            f"to {maximum['accepted']} of {planned} planned cases per pair under the two-valid-full-vectors-equal rule. "
            f"{errors}/{len(pairs)} pairs accept at least one answer that disagrees with a full reference; "
            f"{unknowns}/{len(pairs)} pairs accept at least one answer without a full reference. "
            "Pairs overlap the same inputs. These pair counts must not be pooled into a case accuracy or a deployment policy.",
            "All eligible run pairs; acceptance ranges use each pair's full planned case denominator", len(pairs),
            [run["run_id"] for run in analysis["runs"]], [],
            "Inspect jointly wrong answers and deferred cases in the agreement explorer before testing a review policy on new inputs. Include both model costs and human-review costs.",
            {"pair_count": len(pairs), "planned_cases_per_pair": planned,
             "minimum_accepted": minimum["accepted"], "maximum_accepted": maximum["accepted"],
             "pairs_with_joint_errors": errors, "pairs_with_unknown_references": unknowns,
             "pair_ids": [pair["pair_id"] for pair in pairs],
             "range_evidence": [{"boundary": boundary, "run_a": pair["run_a"], "run_b": pair["run_b"],
                                 "accepted": pair["accepted"], "planned": pair["planned"],
                                 "tied_pairs": sum(p["accepted"] == pair["accepted"] for p in pairs)}
                                for boundary, pair in (("minimum", minimum), ("maximum", maximum))]})
    if comparative is None:
        from .report_comparisons import build_comparative_findings
        comparative = build_comparative_findings(analysis)
    if comparative["analysis_id"] != analysis["analysis_id"] or comparative["source_hashes"] != analysis["source_hashes"]:
        raise ValueError("comparative findings must match analysis sources")
    findings.extend(deepcopy(comparative["findings"]))
    from .report_repeats import build_repeat_analysis, build_repeat_findings
    if repeats is None:
        repeats = build_repeat_analysis(analysis)
    if repeats["analysis_id"] != analysis["analysis_id"] or repeats["source_hashes"] != analysis["source_hashes"]:
        raise ValueError("repeat findings must match analysis sources")
    findings.extend(build_repeat_findings(repeats))
    return {"schema_version": 1, "analysis_id": analysis["analysis_id"],
            "source_hashes": deepcopy(analysis["source_hashes"]), "findings": findings,
            "scope": "All planned runs; each finding retains its own cases and denominator.",
            "limitations": [analysis["sampling_note"],
                "No causal explanation, statistical significance, calibration or deployment guarantee is inferred.",
                "Configuration comparisons describe declared differences; a single changed setting does not establish causality. Prompt comparisons hold configuration and repeat fixed.",
                "Provider timing and client duration are different measurements; unavailable measurements cannot support a latency ranking."]}


def render_findings(findings):
    """Self-contained semantic HTML; all user-controlled content is escaped."""
    h = lambda value: escape(str(value), quote=True)
    items = []
    for item in findings["findings"]:
        a = item["run_ids"][0]
        b = item["run_ids"][1] if len(item["run_ids"]) > 1 else None
        links = " ".join(f"<a href='{h(evidence_url(a, case, b))}'>{h(case)}</a>" for case in item["case_ids"])
        patterns = item["metrics"].get("confusion_patterns", [])
        details = "".join(f"<li>Reference {h(p['reference'])} → prediction {h(p['prediction'])}: {p['count']} cases.</li>" for p in patterns)
        supports = item["metrics"].get("class_support", {})
        range_links = "".join(
            f"<li><a href='{h(evidence_url(p['run_a'], compare=p['run_b']))}'>Inspect {p['boundary']} acceptance boundary</a>: "
            f"{p['accepted']}/{p['planned']} cases; one of {p['tied_pairs']} tied pairs.</li>"
            for p in item["metrics"].get("range_evidence", []))
        supporting_links = "".join(f"<li><a href='{h(evidence_url(link['run_a'], link.get('case_id'), link.get('run_b')))}'>{h(link['label'])}</a></li>"
                                   for link in item.get("supporting_links", []))
        support_text = "; ".join(f"{h(label)}: {count}" for label, count in supports.items())
        items.append(f"<article class='finding' id='finding-{item['finding_id']}' data-finding-runs='{h(json.dumps(item['run_ids']))}'>"
                     f"<h3>{h(item['title'])}</h3><p class='finding-scope'>{h(item['scope'])} · denominator {item['denominator']}</p>"
                     f"<p>{h(item['observation'])}</p>" + (f"<ul>{details}</ul>" if details else "") +
                     (f"<p>Known reference class support: {support_text}. Unobserved classes have no measured performance.</p>" if supports else "") +
                     f"<p><strong>Suggested follow-up:</strong> {h(item['next_step'])}</p>" +
                     (f"<ul>{supporting_links}</ul>" if supporting_links else f"<ul>{range_links}</ul><p>All eligible pairs remain available in the agreement explorer; these boundary links explain the range, not a preferred pair.</p>" if range_links else
                      f"<a href='{h(evidence_url(a, compare=b))}'>Inspect supporting run{' pair' if b else ''}</a>")
                     + (f"<details><summary>Supporting cases ({len(item['case_ids'])})</summary><div class='finding-links'>{links}</div></details>" if links else "") + "</article>")
    return ("<style>.deep-findings .finding{padding:1.5rem 0;border-top:1px solid var(--line,#dcded8)}"
            ".deep-findings h3{margin:.2rem 0 .6rem}.finding-scope{font-size:.82rem;color:var(--muted,#59635d)}"
            ".finding-links{display:flex;flex-wrap:wrap;gap:.6rem;padding:.8rem 0}.deep-findings summary{cursor:pointer;padding:.7rem 0}"
            ".deep-findings a:focus-visible,.deep-findings summary:focus-visible{outline:3px solid var(--accent,#245b4b);outline-offset:3px}"
            ".deep-findings{overflow-wrap:anywhere}</style>"
            "<section class='deep-findings' id='deep-findings' aria-labelledby='deep-findings-heading'>"
            "<h2 id='deep-findings-heading'>Findings and follow-up</h2>"
            f"<p>{h(findings['scope'])}</p><p>Observations below are calculated from saved evidence. Follow-up suggestions are not experimental results.</p>"
            + "".join(items) + "<aside aria-label='Analysis limitations'><h3>Interpretation limits</h3><ul>"
            + "".join(f"<li>{h(text)}</li>" for text in findings["limitations"]) + "</ul></aside></section>")
