"""Private, deterministic presentation of the report's frozen evidence.

No new measurements, model calls or source edits. Layout/interaction acceptance
requires a permitted rendered review; offline DOM checks have narrower scope.
"""

import json
from collections import Counter
from decimal import Decimal
from html import escape
from urllib.parse import urlencode

from .report_findings import evidence_url
from .model_metadata import render_model_metadata


PREVIEW_LIMIT = 6
CASE_LINK_LIMIT = 8


def _h(value):
    return escape(str(value), quote=True)


def _json(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _run_label(run):
    return f"{run['config_id']} / {run['prompt_id']} / repeat {run['repeat']}"


def _link(run, text, case=None, compare=None):
    return f"<a data-presentation-evidence href='{_h(evidence_url(run, case, compare))}'>{_h(text)}</a>"


def _table(caption, headers, rows):
    return ("<div class='presentation-scroll' tabindex='0' role='region' aria-label='" + _h(caption) + "'>"
            "<table><caption>" + _h(caption) + "</caption><thead><tr>" +
            "".join("<th scope='col'>" + _h(name) + "</th>" for name in headers) +
            "</tr></thead><tbody>" + "".join("<tr>" + "".join(
                ("<th scope='row'>" if i == 0 else "<td>") + cell + ("</th>" if i == 0 else "</td>")
                for i, cell in enumerate(row)) + "</tr>" for row in rows) + "</tbody></table></div>")


def _reveal(html):
    return "<div data-presentation-reveal>" + html + "</div>"


def _preview_note(total, label):
    if total <= PREVIEW_LIMIT:
        return ""
    return (f"<p class='presentation-note'>Showing the first {PREVIEW_LIMIT} of {total} {_h(label)} in planned order. "
            "The full report and finding chooser retain the whole scope.</p>")


def _coverage_chart(runs):
    charts = []
    for run in runs[:PREVIEW_LIMIT]:
        counts = run["counts"]
        planned = counts["planned"]
        x, rectangles = 0, []
        description = (f"{counts['valid']} valid, {counts['invalid']} invalid and {counts['missing']} missing "
                       f"of {planned} planned cases in {_run_label(run)}")
        for status in ("valid", "invalid", "missing"):
            width = counts[status] / planned * 600 if planned else 0
            rectangles.append(f"<rect class='presentation-bar-{status}' x='{x:.6f}' y='1' width='{width:.6f}' height='24'/>")
            x += width
        charts.append("<figure class='presentation-coverage-chart'><figcaption>" +
                      _link(run["run_id"], _run_label(run)) + "</figcaption>"
                      f"<svg role='img' aria-label='{_h(description)}' viewBox='0 0 600 26'>" +
                      "".join(rectangles) + "</svg><p class='presentation-note'>" + _h(description) + "</p></figure>")
    return "<div class='presentation-coverage-charts'>" + "".join(charts) + "</div>"


def _class_preview(field_metrics, runs):
    """One disclosed run-field example; the report retains all matrices and IDs."""
    if field_metrics is None or not runs:
        return ""
    first = runs[0]
    field = field_metrics["runs"][first["run_id"]]["fields"][0]
    rows = []
    for label in field["labels"][:PREVIEW_LIMIT]:
        values = field["per_label"][label]
        ratios = []
        for name in ("precision", "recall", "f1"):
            ratio = values[name]
            ratios.append(_h(f"{ratio['numerator']}/{ratio['denominator']} ({ratio['value']:.1%})"
                              if ratio["value"] is not None else "Unavailable"))
        support = values["support"]
        ids = values["fn_ids"] or values["fp_ids"] or values["tp_ids"] or values["support_ids"]
        rows.append([_link(first["run_id"], label, ids[0]) if ids else _h(label),
                     _h(support if support is not None else "Unavailable"), *ratios])
    return (f"<p class='presentation-note'>Class example: {_h(field['name'])}, {_h(_run_label(first))}. "
            f"{field['known_reference_count']}/{field['planned']} known references. First planned run and first declared field; no preferred model is implied.</p>" +
            _table("Class metrics use the same shared report projection; label links inspect a supporting case",
                   ["Label", "Reference support", "Precision", "Recall", "F1"], rows) +
            _preview_note(len(field["labels"]), "declared labels"))


def _finding_html(item):
    runs, cases = item["run_ids"], item["case_ids"]
    a, b = (runs[0] if runs else None), (runs[1] if len(runs) > 1 else None)
    links = " ".join(_link(a, case, case, b) for case in cases[:CASE_LINK_LIMIT]) if a else ""
    support = item["metrics"].get("class_support", {})
    support_text = "; ".join(f"{_h(label)}: {_h(count)}" for label, count in support.items())
    supporting = item.get("supporting_links", [])[:PREVIEW_LIMIT]
    supporting_html = "".join("<li>" + _link(link["run_a"], link["label"], compare=link.get("run_b"), case=link.get("case_id")) + "</li>" for link in supporting)
    boundaries = item["metrics"].get("range_evidence", [])[:2]
    boundary_links = "".join(
        "<li>" + _link(boundary["run_a"], f"Inspect {boundary['boundary']} acceptance boundary", compare=boundary["run_b"]) +
        f": {_h(boundary['accepted'])}/{_h(boundary['planned'])} cases; one of {_h(boundary['tied_pairs'])} tied pairs.</li>"
        for boundary in boundaries)
    run_links = " ".join(_link(run, run) for run in runs[:PREVIEW_LIMIT])
    source = "".join(f"<dt>{_h(name)}</dt><dd>{_h(value) if value is not None else 'Unavailable'}</dd>"
                     for name, value in item["source_hashes"].items())
    return (f"<article class='presentation-finding' data-finding-id='{_h(item['finding_id'])}'>"
            f"<h3>{_h(item['title'])}</h3><p class='presentation-note'>Scope: {_h(item['scope'])}. "
            f"Denominator: {_h(item['denominator'])}. Supporting cases: {len(cases)}.</p>"
            f"<p class='presentation-lede'>{_h(item['observation'])}</p>" +
            (f"<p>Known reference class support: {support_text}. Unobserved classes have no measured performance.</p>" if support else "") +
            _reveal(f"<p class='presentation-note'>Interpretation: {_h(item['interpretation'])}</p>"
                    f"<p>Suggested follow-up: {_h(item['next_step'])}</p>") +
            ("<ul class='presentation-supporting-links'>" + supporting_html + "</ul>" if supporting else "<ul class='presentation-boundary-links'>" + boundary_links + "</ul>"
             "<p class='presentation-note'>These pairs explain the acceptance range. Every eligible pair remains in the agreement explorer; no preferred pair is implied.</p>" if boundaries else
             f"<p>{_link(a, 'Inspect supporting run pair' if b else 'Inspect supporting run', compare=b)}</p>" if a else "") +
            (f"<p class='presentation-case-links'>Supporting cases: {links}</p>" if links else "") +
            (f"<p class='presentation-note'>First {CASE_LINK_LIMIT} of {len(cases)} supporting case IDs. Open the run evidence for every planned case.</p>" if len(cases) > CASE_LINK_LIMIT else "") +
            f"<details><summary>Exact run and source identities</summary><p>{run_links or 'No supporting run'}</p>"
            + (f"<p>{len(runs)} supporting runs; first {PREVIEW_LIMIT} identities shown. The full finding retains every identity.</p>" if len(runs) > PREVIEW_LIMIT else "") +
            "<dl class='presentation-hashes'>" + source + "</dl>"
            "<p>Hashes describe the supplied logical sources; receipt pointers are not independently verified by this view.</p></details></article>")


def _slide(key, title, content, index):
    return (f"<section class='presentation-slide' id='presentation-slide-{key}' data-presentation-slide='{key}' "
            f"aria-labelledby='presentation-title-{key}'><p class='presentation-kicker'>{index:02d} / Saved evidence</p>"
            f"<h3 id='presentation-title-{key}' tabindex='-1'>{_h(title)}</h3>" + content +
            "<p class='presentation-source-line'><a data-presentation-report href='#presentation-sources'>Source hashes and scope</a>"
            " · <a data-presentation-report href='#deep-findings'>Full findings</a></p></section>")


def render_presentation(analysis, findings, *, sensitivity=None, field_metrics=None):
    """Return a self-contained report section sharing the existing explorer URL.

    Fragment params: presentation=1|0, slide=<stable key>, reveal=<integer>,
    finding=<content-derived finding ID>. Preserve run/compareRun/case and all
    unrelated fragment and search params. Evidence links leave presentation mode.
    """
    if not isinstance(analysis, dict) or analysis.get("schema_version") != 1:
        raise ValueError("presentation requires analysis schema version 1")
    if (not isinstance(findings, dict) or findings.get("schema_version") != 1 or
            findings.get("analysis_id") != analysis.get("analysis_id") or
            findings.get("source_hashes") != analysis.get("source_hashes")):
        raise ValueError("presentation requires findings from the same analysis and source hashes")
    if sensitivity is not None:
        if not isinstance(sensitivity, dict) or sensitivity.get("schema_version") != 1:
            raise ValueError("presentation requires sensitivity schema version 1")
        if any(sensitivity.get("source_hashes", {}).get(key) != analysis["source_hashes"].get(key)
               for key in ("task", "plan", "predictions", "labels")):
            raise ValueError("presentation sensitivity sources differ from analysis")
    if field_metrics is not None and (
            not isinstance(field_metrics, dict) or field_metrics.get("schema_version") != 1 or
            field_metrics.get("analysis_id") != analysis.get("analysis_id") or
            field_metrics.get("source_hashes") != analysis.get("source_hashes")):
        raise ValueError("presentation field metrics sources differ from analysis")
    items, runs = findings["findings"], analysis["runs"]
    by_kind = {}
    for item in items:
        if item.get("source_hashes") != analysis["source_hashes"]:
            raise ValueError("presentation finding sources differ from analysis")
        by_kind.setdefault(item["kind"], []).append(item)
    planned = sum(run["counts"]["planned"] for run in runs)
    counts = Counter()
    for run in runs:
        counts.update({key: run["counts"][key] for key in ("valid", "invalid", "missing")})
    case_count, field_count = len(analysis["case_ids"]), len(analysis["task"]["fields"])
    first = runs[0] if runs else None
    reference_counts = first["counts"] if first else {}
    lifecycle = Counter(case["lifecycle_state"] for run in runs for case in run["cases"])
    slides = []
    add = lambda key, title, content: slides.append(_slide(key, title, content, len(slides) + 1))
    definitions = "".join(f"<li><strong>{_h(field['name'])}</strong>: " +
                          ", ".join(_h(label) for label in field["labels"]) + "</li>"
                          for field in analysis["task"]["fields"])
    add("scope", analysis["task"]["name"],
        f"<p class='presentation-lede'>{case_count} distinct input IDs, {field_count} categorical decision fields and "
        f"{len(runs)} planned runs. This presentation describes the saved experiment.</p>"
        f"<p>{planned} planned run-case positions retain valid, invalid and missing outcomes. Repeats reuse the same inputs.</p>"
        "<div class='presentation-two-column'><div><h4>Task definition</h4><ul>" + definitions + "</ul></div>"
        "<div><h4>Method</h4><p>Exact agreement requires every referenced field to match. "
        "Partial references support field checks only. Missing references never receive an invented accuracy score.</p>"
        "<p>All counts, comparisons and evidence selections come from deterministic offline analysis.</p></div></div>" +
        _reveal(f"<p>Reference coverage on the shared input membership: {reference_counts.get('full_reference', 0)} full, "
                f"{reference_counts.get('partial_reference', 0)} partial and {reference_counts.get('no_reference', 0)} absent "
                f"of {case_count} inputs.</p><p>Reference labels remain outside inference capsules. "
                "A correction creates a new evaluation; it does not rewrite saved model output.</p>"))
    overview_links = "".join(
        f"<li><a data-presentation-finding-link='{_h(group[0]['finding_id'])}' "
        f"href='#presentation-heading?{_h(urlencode({'presentation': '1', 'slide': 'finding', 'reveal': '0', 'finding': group[0]['finding_id']}))}'>"
        f"{_h(group[0]['title'])}</a><span> {len(group)} finding{'s' if len(group) != 1 else ''}; each keeps its own denominator.</span></li>"
        for group in by_kind.values())
    add("overview", "Read coverage before comparing answers",
        f"<div class='presentation-hero-number'>{counts['valid']}<span> / {planned}</span></div>"
        "<p class='presentation-lede'>Planned run-case positions with valid output.</p>"
        f"<p>{counts['invalid']} invalid and {counts['missing']} missing positions remain in the experiment. "
        "These are repeated observations, not distinct new cases.</p>" +
        _reveal("<h4>Evidence-backed findings</h4><ul class='presentation-findings-index'>" + overview_links + "</ul>"
                "<p class='presentation-note'>Open a category to read its first finding, then choose any scoped finding. "
                "Category counts are not pooled performance scores.</p>"))
    if any("model_metadata" in run.get("configuration", {}) for run in runs):
        by_configuration = {}
        for run in runs:
            by_configuration.setdefault(run["config_id"], run)
        declaration_runs = sorted(by_configuration.values(),
                                  key=lambda run: "model_metadata" not in run.get("configuration", {}))
        add("model-declarations", "Keep declared model context separate from measured results",
            "<p class='presentation-lede'>Family, intended purpose and training lineage are separate operator declarations. "
            "A reporting group, route or interface does not verify any of them.</p>" +
            "".join("<div>" + _link(run["run_id"], _run_label(run)) +
                    render_model_metadata(run.get("configuration", {}), heading="Read model declarations and sources") + "</div>"
                    for run in declaration_runs[:PREVIEW_LIMIT]) + _preview_note(len(declaration_runs), "configurations") +
            "<p class='presentation-note'>Source review is operator-declared. The harness has not independently verified the claims, "
            "and they do not explain observed performance causally. Inspect any exact run in the case explorer for its complete declarations.</p>")
    coverage_rows = [[_link(run["run_id"], _run_label(run)),
        _h(f"{run['counts']['valid']}/{run['counts']['planned']}"), _h(run["counts"]["invalid"]),
        _h(run["counts"]["missing"]), _h(f"{run['counts']['full_reference']}/{run['counts']['planned']}"),
        _h(f"{run['counts']['exact_correct']}/{run['counts']['full_reference']} labeled" if run["counts"]["full_reference"] else "Unavailable")]
        for run in runs[:PREVIEW_LIMIT]]
    add("outputs", "A usable answer and a correct answer are different checks",
        "<p class='presentation-lede'>Reference agreement is conditional on reference coverage. "
        "Valid output can still disagree with the reference.</p>" +
        _coverage_chart(runs) +
        _table("Planned runs and their own case denominators", ["Run", "Valid", "Invalid", "Missing", "Full references", "Exact matches"], coverage_rows) +
        _preview_note(len(runs), "runs") + _reveal("<h4>Saved lifecycle states across run-case positions</h4><p>" +
            "; ".join(f"{_h(state)}: {count}" for state, count in sorted(lifecycle.items())) +
            ". Lifecycle and prediction validity remain separate. Missing operation metadata is unavailable.</p>"))
    fields = by_kind.get("field_errors", [])
    field_rows = [[_link(item["run_ids"][0], item["title"] + ": " + item["scope"]),
        _h(f"{item['metrics']['correct']}/{item['metrics']['known_references']}"),
        _h(item["metrics"]["valid_errors"]), _h(item["metrics"]["unusable"]),
        _h(item["metrics"]["planned"] - item["metrics"]["known_references"])] for item in fields[:PREVIEW_LIMIT]]
    add("fields", "Inspect errors one decision field at a time",
        f"<p class='presentation-lede'>{len(fields)} run-field reference checks are available. "
        "Class support and disagreement patterns belong to each run's own references.</p>" +
        (_table("Known field references; invalid and missing predictions retain their positions",
                ["Field and run", "Matches / known", "Valid errors", "Unusable", "Unknown reference"], field_rows)
         if fields else "<p>No field reference checks are available. Label agreement and repeat differences can still be inspected without accuracy scores.</p>") +
        _preview_note(len(fields), "run-field checks") + _reveal("<p>Read per-class support, precision, recall, F1 and confusion in the report. "
            "A class with no known examples has no measured recall. Missing positive predictions count against recall under the evaluator's declared rule.</p>"))
    if field_metrics is not None:
        slides[-1] = slides[-1].replace("<p class='presentation-source-line'>", _reveal(_class_preview(field_metrics, runs)) + "<p class='presentation-source-line'>", 1)
    prompts = analysis["prompt_comparisons"]
    prompt_rows = [[_link(pair["run_a"], f"{pair['config_id']} / repeat {pair['repeat']}: {pair['prompt_a']} → {pair['prompt_b']}", compare=pair["run_b"]),
        _h(f"{pair['scored_reference_cases']}/{pair['planned']}"), _h(len(pair["gained_ids"])),
        _h(len(pair["lost_ids"])), _h(f"{len(pair['unusable_to_valid_ids'])} / {len(pair['valid_to_unusable_ids'])}")]
        for pair in prompts[:PREVIEW_LIMIT]]
    add("prompts", "Inspect prompt gains and losses together",
        f"<p class='presentation-lede'>{len(prompts)} matched prompt comparisons hold configuration and repeat fixed. "
        "A net change can conceal losses on other cases.</p>" +
        (_table("Agreement transitions on fully referenced cases; validity transitions can overlap",
                ["Matched prompt pair", "Known / planned", "Gains", "Losses", "Recovered / became unusable"], prompt_rows)
         if prompts else "<p>No matched prompt pairs are available. Different settings do not establish a controlled prompt effect.</p>") +
        _preview_note(len(prompts), "prompt pairs") + _reveal("<p>Inspect exact changed inputs before preferring a prompt. "
            "Reasoning, batching and model effects require their own controlled comparisons. "
            "Observed differences here do not identify a cause.</p>"))
    repeats = analysis.get("repeat_comparisons", [])
    repeat_rows = [[_link(pair["run_a"], f"{pair['config_id']} / {pair['prompt_id']}: repeats {pair['repeat_a']} and {pair['repeat_b']}", compare=pair["run_b"]),
        _h(f"{pair['changed']}/{pair['comparable']}"), _h(f"{pair['excluded']}/{pair['planned']}")]
        for pair in repeats[:PREVIEW_LIMIT]]
    add("repeats", "Equal totals can conceal changed labels",
        f"<p class='presentation-lede'>{len(repeats)} repeat pairs compare saved predictions on the same inputs. "
        "A label flip requires two valid predictions.</p>" +
        (_table("Repeat differences; excluded outcomes remain in the planned denominator",
                ["Repeat pair", "Changed / comparable", "Excluded / planned"], repeat_rows)
         if repeats else "<p>No repeat pairs are available. One run cannot establish repeat consistency.</p>") +
        _preview_note(len(repeats), "repeat pairs") + _reveal("<p>Stable repeats can share the same wrong answer. "
            "Origin and session independence require recorded execution evidence; this view does not infer freshness from a repeat number.</p>"))
    pairs = analysis["agreement_pairs"]
    error_pairs = sum(pair["accepted_error"] > 0 for pair in pairs)
    unknown_pairs = sum(pair["accepted_reference_unknown"] > 0 for pair in pairs)
    agreement_rows = [[_link(pair["run_a"], pair["run_a"][:12] + " / " + pair["run_b"][:12], compare=pair["run_b"]),
        _h(pair["planned"]), _h(pair["accepted_correct"]), _h(pair["accepted_error"]),
        _h(pair["accepted_reference_unknown"]), _h(pair["deferred"])] for pair in pairs[:PREVIEW_LIMIT]]
    add("agreement", "Agreement can accept a shared error",
        (f"<p class='presentation-lede'>{error_pairs}/{len(pairs)} eligible pairs accept at least one answer that disagrees with a full reference. "
        f"{unknown_pairs}/{len(pairs)} accept at least one answer without a full reference.</p>" if pairs else
        "<p class='presentation-lede'>No eligible run pairs are available for agreement-policy analysis.</p>") +
        "<p>Declared rule: accept only two valid, equal full prediction vectors. Otherwise defer. "
        "Agreement is not evidence that the accepted answer is correct.</p>" +
        (_table("Each pair retains its own full planned denominator; do not sum overlapping pairs",
                ["Run pair", "Planned", "Accepted correct", "Accepted error", "Accepted unknown", "Deferred"], agreement_rows)
         if pairs else "<p>No eligible agreement pairs are available. A single run cannot evaluate a two-run policy.</p>") +
        _preview_note(len(pairs), "eligible pairs") + _reveal("<p>The report's agreement explorer includes all eligible pairs, joint errors and deferrals. "
            "Inspect both source runs. Model charges and human review costs belong in any future workflow evaluation; "
            "these retrospective counts do not measure deployment gains.</p>"))
    cost_rows = []
    for run in runs[:PREVIEW_LIMIT]:
        cost = run["cost"]
        amount = cost["observed_cost_micro_usd"]
        dollars = f"${Decimal(amount) / Decimal(1_000_000):.6f}" if amount is not None else "Unavailable"
        cost_rows.append([_link(run["run_id"], _run_label(run)), _h(dollars),
            _h(f"{cost['observed_cost_requests']}/{cost['planned_requests']}"),
            "Complete" if cost["complete"] else "Incomplete", _h(cost["synthetic_excluded_requests"])])
    complete_costs = sum(run["cost"]["complete"] for run in runs)
    add("cost", "Read measured cost beside coverage",
        f"<p class='presentation-lede'>{complete_costs}/{len(runs)} planned runs have complete observed USD coverage. "
        "Unknown charges are unavailable, and subscription usage does not establish a dollar charge.</p>" +
        _table("Observed charges for each run's planned requests; partial amounts are not total prices",
                ["Run", "Observed USD", "Requests covered", "Coverage", "Synthetic excluded"], cost_rows) +
        _preview_note(len(runs), "runs") + _reveal("<p>Known charges, unresolved holds, subscription invocations and estimates remain separate in the report. "
            "Synthetic measurements do not support real-provider comparisons.</p>"
            "<p>No timing or token comparison is derived by this presentation projection. Read the report's recorded measurements and coverage: "
            "client request duration, provider timing, pure inference time and run elapsed time are different quantities.</p>"))
    if sensitivity is None:
        sensitivity_html = ("<p class='presentation-lede'>No hypothetical reference scenario is supplied.</p>"
            "<p>Saved references remain unchanged. Alternative labels need an explicit allowed-label scenario and provenance before re-scoring.</p>")
    else:
        scenarios = sensitivity.get("scenarios", [])
        coverage = sensitivity.get("reference_coverage", {})
        sensitivity_html = (f"<p class='presentation-lede'>Hypothetical reference sensitivity: {_h(sensitivity.get('status', 'unavailable'))}. "
            f"{len(scenarios)} supplied scenarios.</p><p>These scenarios re-score fixed saved predictions. "
            "They do not change the saved reference or demonstrate that an alternative label is correct.</p>"
            f"<p>Reference coverage: {len(coverage.get('fully_labeled_ids', []))} full, "
            f"{len(coverage.get('partially_labeled_ids', []))} partial and {len(coverage.get('unlabeled_ids', []))} absent "
            f"of {_h(coverage.get('planned_cases', 'unavailable'))} planned cases.</p><ul>" +
            "".join(f"<li>{_h(scenario.get('title', scenario.get('id', 'Unnamed scenario')))}: "
                    f"{_h(scenario.get('provenance', 'Provenance unavailable'))}. Hypothetical. "
                    f"{_h(scenario.get('summary', {}).get('improved_runs', 'unavailable'))} improved, "
                    f"{_h(scenario.get('summary', {}).get('declined_runs', 'unavailable'))} declined and "
                    f"{_h(scenario.get('summary', {}).get('unchanged_runs', 'unavailable'))} unchanged scoped run counts. "
                    "Repeated runs are not independent samples.</li>"
                    for scenario in scenarios[:PREVIEW_LIMIT]) + "</ul>" + _preview_note(len(scenarios), "hypothetical scenarios") +
            "<p><a data-presentation-report href='#reference-sensitivity'>Inspect scenario deltas and exact supporting cases</a></p>")
    add("sensitivity", "Reference policy changes the meaning of a score", sensitivity_html +
        _reveal("<p>Adjudicate disputed labels against the task rubric and version any correction. "
            "Unknown references cannot be filled by pretending that an alternative is an observed reference.</p>"))
    chosen = items[0] if items else None
    add("finding", "Follow one finding to its evidence",
        "<div class='presentation-finding-control' hidden><label for='presentation-finding-select'>Scoped finding</label>"
        "<select id='presentation-finding-select'></select></div>"
        "<div id='presentation-finding-detail'>" + (_finding_html(chosen) if chosen else "<p>No findings are available.</p>") + "</div>"
        "<p class='presentation-note'>The chooser includes every finding. Only the selected detail is mounted. "
        "Without JavaScript, the first finding and the full report links remain readable.</p>")
    limits = "".join("<li>" + _h(note) + "</li>" for note in findings["limitations"])
    sources = "".join(f"<dt>{_h(name)}</dt><dd>{_h(value) if value is not None else 'Unavailable'}</dd>"
                      for name, value in analysis["source_hashes"].items())
    add("limits", "Choose the next test from the remaining uncertainty",
        "<ul>" + limits + "</ul>" + _reveal("<ol><li>Inspect failed and missing outputs before dispatching new work.</li>"
            "<li>Adjudicate disputed or absent references with the task rubric.</li>"
            "<li>Use new frozen inputs for a follow-up experiment; keep prompt and repeat conditions distinct.</li>"
            "<li>Reconcile cost and timing coverage before making a workflow recommendation.</li></ol>"
            "<p>These are follow-up suggestions. They neither establish experimental results nor authorize additional inference.</p>") +
        "<div class='presentation-actions'><a data-presentation-report href='#case-explorer-heading'>Inspect saved runs and cases</a>"
        "<a data-presentation-report href='#downloads-heading'>Download allowlisted evidence</a></div>")
    # Keep only narrative data and bounded links. Cases/predictions and the O(n²)
    # agreement projection are already held by the explorer, not copied here.
    compact_items = [{**item, "case_ids": item["case_ids"][:CASE_LINK_LIMIT],
                      "supporting_links": item.get("supporting_links", [])[:PREVIEW_LIMIT],
                      "case_count": len(item["case_ids"]), "run_ids": item["run_ids"][:PREVIEW_LIMIT],
                      "run_count": len(item["run_ids"]),
                      "metrics": {"class_support": item["metrics"].get("class_support", {}),
                                  "range_evidence": item["metrics"].get("range_evidence", [])[:2]}}
                     for item in items]
    data = {"schema_version": 1, "analysis_id": analysis["analysis_id"], "findings": compact_items}
    return (_STYLE + "<section class='report-presentation' id='report-presentation' aria-labelledby='presentation-heading'>"
        "<header class='presentation-header'><div><p class='presentation-kicker'>Private benchmark / Evidence presentation</p>"
        "<h2 id='presentation-heading' tabindex='-1'>Present the findings</h2></div>"
        "<div class='presentation-actions'><button id='presentation-start' type='button' hidden>Start presentation</button>"
        "<a id='presentation-exit' data-presentation-report href='#deep-findings'>Return to report</a></div></header>"
        "<p id='presentation-notice' class='presentation-note' role='status' hidden></p>"
        "<nav class='presentation-controls' aria-label='Presentation navigation' hidden>"
        "<button id='presentation-previous' type='button'>Previous</button>"
        "<label for='presentation-slide-select'>Slide<select id='presentation-slide-select'></select></label>"
        "<p id='presentation-progress' aria-live='polite' aria-atomic='true'></p>"
        "<button id='presentation-next' type='button'>Next</button>"
        "<a id='presentation-permalink' href='#presentation-heading'>Link to this slide</a></nav>"
        "<div id='presentation-stage' tabindex='-1'>" + "".join(slides) + "</div>"
        "<aside id='presentation-sources'><h3>Scope and source identities</h3>"
        f"<p>Analysis ID: <code>{_h(analysis['analysis_id'])}</code>. Logical source hashes bind the same frozen evidence as the report.</p>"
        "<dl class='presentation-hashes'>" + sources + "</dl>"
        "<p class='presentation-note'>Offline analytical and DOM checks do not establish rendered visual acceptance. "
        "The private report requires permitted desktop, narrow-window, keyboard, reduced-motion and print observations.</p></aside>"
        "<p class='presentation-keyboard'>Arrow keys or Space move through reveals. Home and End choose the first or last slide. "
        "Escape returns to the report. Form controls and scrollable tables keep their own keys.</p>"
        "<noscript><p>JavaScript is disabled. All narrative slides and reveals remain readable. "
        "The report contains every finding and supporting run.</p></noscript></section>"
        "<script type='application/json' id='presentation-data'>" + _json(data) + "</script>" + _SCRIPT)


_STYLE = """<style>
.report-presentation{--presentation-ink:#202922;--presentation-muted:#566459;--presentation-line:#c9d2c7;--presentation-accent:#285747;--presentation-paper:#f3f4ed;color:var(--presentation-ink);background:var(--presentation-paper);font-family:Avenir Next,Avenir,Segoe UI,sans-serif;font-variant-numeric:tabular-nums;padding:clamp(1.25rem,4vw,3.5rem);margin:3rem 0;border-top:3px solid var(--presentation-accent);overflow-wrap:anywhere;scroll-margin-top:5rem}
.report-presentation *{box-sizing:border-box}.report-presentation [hidden]{display:none!important}
.report-presentation p,.report-presentation li{max-width:70ch;line-height:1.55}.report-presentation p{margin:.7rem 0 1rem}
.report-presentation h2,.report-presentation h3{font-family:Iowan Old Style,Palatino Linotype,Book Antiqua,Georgia,serif;font-weight:500;letter-spacing:-.035em;line-height:1.08;text-wrap:balance}
.report-presentation h2{font-size:clamp(2rem,3.8vw,3.5rem);margin:.2rem 0}.report-presentation .presentation-slide>h3{font-size:clamp(2.3rem,5.3vw,4.75rem);max-width:20ch;margin:.35rem 0 1.4rem}
.report-presentation h4{font-size:1rem;font-weight:650;margin:1.2rem 0 .5rem}.report-presentation .presentation-lede{font-size:clamp(1.15rem,2vw,1.5rem);max-width:58ch;line-height:1.4}
.report-presentation .presentation-kicker{font-size:.74rem;letter-spacing:.07em;font-weight:650;color:var(--presentation-muted)}
.report-presentation .presentation-note,.report-presentation .presentation-source-line,.report-presentation .presentation-keyboard{font-size:.82rem;color:var(--presentation-muted)}
.report-presentation .presentation-header{display:flex;gap:1.5rem;align-items:center;justify-content:space-between;border-bottom:1px solid var(--presentation-line);padding-bottom:1.5rem}
.report-presentation .presentation-actions{display:flex;align-items:center;gap:1rem;flex-wrap:wrap}.report-presentation .presentation-actions a{font-size:.88rem}
.report-presentation a{color:var(--presentation-accent);text-underline-offset:.2em}.report-presentation :is(a,button,select,input,summary,[tabindex]):focus-visible{outline:3px solid var(--presentation-accent);outline-offset:4px}
.report-presentation button,.report-presentation select{font:inherit;color:var(--presentation-ink);background:#fcfdf7;border:1px solid #849a87;border-radius:2px;padding:.55rem .75rem;min-height:2.75rem}
.report-presentation button{cursor:pointer;font-size:.85rem;transition:background-color .18s,transform .18s}.report-presentation button:hover{background:#e4ece0}.report-presentation button:active{transform:translateY(1px)}.report-presentation button:disabled{opacity:.45;cursor:default}
.report-presentation .presentation-controls{display:flex;flex-wrap:wrap;align-items:end;gap:1rem;padding:1rem 0;border-bottom:1px solid var(--presentation-line)}
.report-presentation .presentation-controls label{font-size:.75rem;display:grid;gap:.25rem;flex:1;min-width:10rem;max-width:24rem}.report-presentation .presentation-controls select{width:100%;font-size:.9rem}.report-presentation #presentation-progress{font-size:.8rem;max-width:25ch;margin:.5rem 0;min-width:11ch}
.report-presentation .presentation-controls a{font-size:.78rem}.report-presentation .presentation-slide{padding:2.5rem 0;border-bottom:1px solid var(--presentation-line);max-width:78rem;margin:auto}
.report-presentation .presentation-two-column{display:grid;grid-template-columns:1fr 1.15fr;gap:clamp(1rem,4vw,4rem);margin-top:2rem}.report-presentation .presentation-two-column>div{min-width:0}
.report-presentation .presentation-hero-number{font-size:clamp(4rem,11vw,8.5rem);font-weight:550;letter-spacing:-.06em;line-height:1.1;margin-top:1.4rem}.report-presentation .presentation-hero-number span{font-size:.4em;color:var(--presentation-muted);letter-spacing:-.04em}
.report-presentation .presentation-coverage-charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem 2rem;margin:1.6rem 0}.report-presentation .presentation-coverage-chart{margin:0;min-width:0}.report-presentation .presentation-coverage-chart figcaption{font-size:.85rem;margin-bottom:.45rem}.report-presentation .presentation-coverage-chart svg{display:block;width:100%;height:auto;border:1px solid var(--presentation-line)}.report-presentation .presentation-bar-valid{fill:var(--presentation-accent)}.report-presentation .presentation-bar-invalid{fill:#8d795e}.report-presentation .presentation-bar-missing{fill:#dce3d7}.report-presentation .presentation-coverage-chart .presentation-note{font-size:.72rem}
.report-presentation .presentation-scroll{overflow:auto;max-width:100%;margin:1.5rem 0;border-top:2px solid var(--presentation-ink);border-bottom:1px solid var(--presentation-line)}
.report-presentation table{border-collapse:collapse;width:100%;min-width:42rem;font-size:.86rem}.report-presentation caption{text-align:left;padding:.75rem 0;color:var(--presentation-muted);font-size:.78rem}
.report-presentation :is(td,th){padding:.65rem .6rem;border-bottom:1px solid var(--presentation-line);vertical-align:top;text-align:right}.report-presentation th:first-child{text-align:left;max-width:26rem}.report-presentation thead th{font-weight:650;font-size:.75rem}.report-presentation tbody th{font-weight:500}.report-presentation tbody tr:last-child>*{border-bottom:0}
.report-presentation .presentation-finding-control{display:grid;gap:.4rem;margin:1rem 0}.report-presentation .presentation-finding-control select{width:100%;max-width:58rem}.report-presentation .presentation-finding h3{font-size:2rem;margin:1.5rem 0 .5rem}
.report-presentation .presentation-case-links a{display:inline-block;margin:.25rem .65rem .25rem 0}.report-presentation details{margin:1.2rem 0;border-top:1px solid var(--presentation-line);padding-top:.75rem}.report-presentation summary{cursor:pointer;color:var(--presentation-accent);font-size:.85rem;padding:.5rem 0}
.report-presentation .model-declarations dt{font-weight:650;margin-top:1rem}.report-presentation .model-declarations dd{margin:.3rem 0 1rem;overflow-wrap:anywhere}.report-presentation .model-declarations code,.report-presentation .model-declarations a{overflow-wrap:anywhere}
.report-presentation .presentation-hashes{font-size:.72rem;display:grid;grid-template-columns:minmax(6rem,auto) minmax(0,1fr);gap:.4rem 1rem;max-width:78rem}.report-presentation .presentation-hashes dt{color:var(--presentation-muted)}.report-presentation .presentation-hashes dd{font-family:ui-monospace,Menlo,monospace;margin:0;overflow-wrap:anywhere}
.report-presentation #presentation-sources{padding-top:2rem}.report-presentation #presentation-sources>h3{font-size:1.5rem}.report-presentation .presentation-findings-index li{margin:.6rem 0}.report-presentation .presentation-findings-index span{font-size:.85rem;color:var(--presentation-muted)}
.report-presentation.presentation-active{position:fixed;inset:0;z-index:50;margin:0;overflow:auto;border:0;padding-top:1rem;overscroll-behavior:contain}.report-presentation.presentation-active .presentation-controls{position:sticky;top:0;background:var(--presentation-paper);z-index:1}.report-presentation.presentation-active .presentation-header{max-width:78rem;margin:auto}.report-presentation.presentation-active #presentation-stage{min-height:65dvh}
.report-presentation.presentation-active #presentation-sources{max-width:78rem;margin:auto}.report-presentation.presentation-active .presentation-keyboard{max-width:78rem;margin:1rem auto}
.report-presentation.presentation-enhanced [data-presentation-reveal]:not([hidden]){animation:presentation-reveal .2s ease-out}
@keyframes presentation-reveal{from{opacity:.4;transform:translateY(.3rem)}to{opacity:1;transform:translateY(0)}}
@media(max-width:700px){.report-presentation .presentation-two-column,.report-presentation .presentation-coverage-charts{grid-template-columns:1fr}.report-presentation .presentation-header{align-items:start;flex-direction:column}.report-presentation .presentation-controls{gap:.55rem}.report-presentation .presentation-controls label{order:-1;flex-basis:100%;max-width:none}.report-presentation .presentation-hashes{grid-template-columns:1fr}.report-presentation .presentation-slide{padding-top:1.5rem}.report-presentation.presentation-active{padding:1rem}}
@media(prefers-reduced-motion:reduce){.report-presentation *{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
@media print{.report-presentation,.report-presentation.presentation-active{position:static!important;overflow:visible!important;margin:0;padding:0;background:white;border:0}.report-presentation :is(.presentation-controls,.presentation-actions,.presentation-keyboard,.presentation-finding-control){display:none!important}.report-presentation .presentation-slide,.report-presentation [data-presentation-reveal]{display:block!important;opacity:1!important;transform:none!important;animation:none!important}.report-presentation .presentation-slide{break-before:page;break-inside:auto;padding:1rem 0}.report-presentation .presentation-scroll{overflow:visible}.report-presentation table{min-width:0;font-size:9pt}.report-presentation :is(h2,h3,h4){break-after:avoid}.report-presentation details>*{display:block!important}.report-presentation .presentation-slide>h3{font-size:28pt}.report-presentation .presentation-hero-number{font-size:60pt}}
</style>"""


_SCRIPT = """<script>
(() => {
  'use strict';
  const root = document.getElementById('report-presentation');
  if (!root) return;
  const get = id => document.getElementById('presentation-' + id);
  const data = JSON.parse(get('data').textContent);
  const slides = Array.from(root.querySelectorAll('[data-presentation-slide]'));
  const keys = slides.map(slide => slide.dataset.presentationSlide);
  const items = data.findings, byFinding = new Map(items.map(item => [item.finding_id, item]));
  const stage = get('stage'), notice = get('notice'), chooser = get('slide-select'), findingChooser = get('finding-select');
  let state = {slide: 0, reveal: 0, finding: items[0] && items[0].finding_id || '', active: false};
  let restoreFocus = null, inertSiblings = [];
  const element = (tag, text, cls) => {const node = document.createElement(tag); if (text !== undefined) node.textContent = String(text); if (cls) node.className = cls; return node;};
  function fragment(url) {const parts = url.hash.slice(1).split('?'); return {heading: parts[0], params: new URLSearchParams(parts.slice(1).join('?'))};}
  function stateURL(heading = 'presentation-heading', active = state.active) {
    const url = new URL(window.location.href), part = fragment(url);
    part.params.set('presentation', active ? '1' : '0'); part.params.set('slide', keys[state.slide]);
    part.params.set('reveal', String(state.reveal)); part.params.set('finding', state.finding);
    url.hash = heading + '?' + part.params.toString(); return url;
  }
  function writeURL(url) {try {window.history.replaceState(null, '', url.href);} catch (_) {window.location.hash = url.hash;}}
  function evidenceURL(run, compare, caseID) {
    const url = stateURL('case-explorer-heading', false), part = fragment(url);
    part.params.set('run', run || ''); part.params.set('compareRun', compare || ''); part.params.set('case', caseID || '');
    url.hash = 'case-explorer-heading?' + part.params.toString(); return url;
  }
  function link(run, text, compare, caseID) {const a = element('a', text); a.dataset.presentationEvidence = ''; a.href = evidenceURL(run, compare, caseID).href; return a;}
  function renderFinding() {
    const item = byFinding.get(state.finding); const container = get('finding-detail');
    if (!item) return;
    if (container.firstElementChild && container.firstElementChild.dataset.findingId === item.finding_id) return;
    const article = element('article', undefined, 'presentation-finding'); article.dataset.findingId = item.finding_id;
    const a = item.run_ids[0], b = item.run_ids[1];
    article.append(element('h3', item.title), element('p', 'Scope: ' + item.scope + '. Denominator: ' + item.denominator + '. Supporting cases: ' + item.case_count + '.', 'presentation-note'), element('p', item.observation, 'presentation-lede'));
    const supports = item.metrics.class_support || {};
    if (Object.keys(supports).length) article.append(element('p', 'Known reference class support: ' + Object.entries(supports).map(entry => entry[0] + ': ' + entry[1]).join('; ') + '. Unobserved classes have no measured performance.'));
    const reveal = element('div'); reveal.dataset.presentationReveal = '';
    reveal.append(element('p', 'Interpretation: ' + item.interpretation, 'presentation-note'), element('p', 'Suggested follow-up: ' + item.next_step)); article.append(reveal);
    const boundaries = (item.metrics.range_evidence || []).slice(0, 2);
    const supporting = item.supporting_links || [];
    if (supporting.length) {
      const list = element('ul', undefined, 'presentation-supporting-links');
      supporting.forEach(item => { const row = element('li'); row.append(link(item.run_a, item.label, item.run_b, item.case_id)); list.append(row); }); article.append(list);
    } else if (boundaries.length) {
      const list = element('ul', undefined, 'presentation-boundary-links');
      boundaries.forEach(boundary => {const row = element('li'); row.append(link(boundary.run_a, 'Inspect ' + boundary.boundary + ' acceptance boundary', boundary.run_b), document.createTextNode(': ' + boundary.accepted + '/' + boundary.planned + ' cases; one of ' + boundary.tied_pairs + ' tied pairs.')); list.append(row);});
      article.append(list, element('p', 'These pairs explain the acceptance range. Every eligible pair remains in the agreement explorer; no preferred pair is implied.', 'presentation-note'));
    } else if (a) {const p = element('p'); p.append(link(a, b ? 'Inspect supporting run pair' : 'Inspect supporting run', b)); article.append(p);}
    if (a && item.case_ids.length) {const p = element('p', 'Supporting cases: ', 'presentation-case-links'); item.case_ids.forEach(id => p.append(link(a, id, b, id), document.createTextNode(' '))); article.append(p);}
    if (item.case_count > item.case_ids.length) article.append(element('p', 'First ' + item.case_ids.length + ' of ' + item.case_count + ' supporting case IDs. Open the run evidence for every planned case.', 'presentation-note'));
    const details = element('details'); details.append(element('summary', 'Exact run and source identities'));
    const ids = element('p'); item.run_ids.forEach(id => ids.append(link(id, id), document.createTextNode(' '))); details.append(ids);
    if (item.run_count > item.run_ids.length) details.append(element('p', item.run_count + ' supporting runs; first ' + item.run_ids.length + ' identities shown. The full finding retains every identity.'));
    const hashes = element('dl', undefined, 'presentation-hashes'); Object.entries(item.source_hashes).forEach(entry => hashes.append(element('dt', entry[0]), element('dd', entry[1] === null ? 'Unavailable' : entry[1]))); details.append(hashes, element('p', 'Hashes describe the supplied logical sources; receipt pointers are not independently verified by this view.'));
    article.append(details); container.replaceChildren(article);
  }
  function setActive(active) {
    if (state.active === active) return;
    state.active = active; root.classList.toggle('presentation-active', active);
    if (active) {
      restoreFocus = document.activeElement;
      root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true');
      let ancestor = root;
      while (ancestor.parentElement) {
        Array.from(ancestor.parentElement.children).forEach(sibling => {
          if (sibling !== ancestor && !['SCRIPT', 'STYLE'].includes(sibling.tagName)) {
            inertSiblings.push({node:sibling, inert:sibling.hasAttribute('inert')}); sibling.setAttribute('inert', '');
          }
        }); ancestor = ancestor.parentElement;
        if (ancestor === document.body) break;
      }
      stage.focus({preventScroll:true});
    } else {
      root.removeAttribute('role'); root.removeAttribute('aria-modal');
      inertSiblings.forEach(item => {if (!item.inert) item.node.removeAttribute('inert');}); inertSiblings = [];
      if (restoreFocus && restoreFocus.isConnected) restoreFocus.focus({preventScroll:true});
    }
    get('start').hidden = active;
  }
  function revealItems() {return Array.from(slides[state.slide].querySelectorAll('[data-presentation-reveal]'));}
  function paint(write = true, focus = false) {
    renderFinding(); const reveals = revealItems();
    state.reveal = Math.min(state.reveal, reveals.length);
    slides.forEach((slide, i) => {slide.hidden = i !== state.slide; Array.from(slide.querySelectorAll('[data-presentation-reveal]')).forEach((node, j) => {node.hidden = i !== state.slide || j >= state.reveal;});});
    chooser.value = keys[state.slide]; findingChooser.value = state.finding;
    get('previous').disabled = state.slide === 0 && state.reveal === 0;
    get('next').disabled = state.slide === slides.length - 1 && state.reveal === reveals.length;
    get('next').textContent = state.reveal < reveals.length ? 'Reveal details' : 'Next';
    get('progress').textContent = (state.slide + 1) + ' / ' + slides.length + ' · ' + state.reveal + ' / ' + reveals.length + ' reveals';
    get('permalink').href = stateURL('presentation-heading', true).href;
    if (write) writeURL(stateURL());
    if (focus) {slides[state.slide].querySelector('h3').focus({preventScroll:true}); stage.scrollTop = 0; if (state.active) root.scrollTop = 0;}
  }
  function move(direction) {
    const count = revealItems().length;
    if (direction > 0) {if (state.reveal < count) state.reveal++; else if (state.slide < slides.length - 1) {state.slide++; state.reveal = 0;}}
    else if (state.reveal > 0) state.reveal--; else if (state.slide > 0) {state.slide--; state.reveal = revealItems().length;}
    paint(true, true);
  }
  function fromURL() {
    const url = new URL(window.location.href), part = fragment(url);
    const value = key => part.params.has(key) ? part.params.get(key) : url.searchParams.get(key);
    const key = value('slide'), requestedFinding = value('finding'); let message = '';
    if (key && !keys.includes(key)) message = 'The linked slide is unavailable. Showing the scope slide.';
    state.slide = key && keys.includes(key) ? keys.indexOf(key) : 0;
    const raw = value('reveal'); state.reveal = raw && /^\\d+$/.test(raw) && Number.isSafeInteger(Number(raw)) ? Number(raw) : 0;
    if (raw && (!/^\\d+$/.test(raw) || !Number.isSafeInteger(Number(raw)))) message += ' The linked reveal is invalid. Showing the first reveal state.';
    if (requestedFinding && !byFinding.has(requestedFinding)) message += ' The linked finding is unavailable. Showing the first finding.';
    state.finding = byFinding.has(requestedFinding) ? requestedFinding : items[0] && items[0].finding_id || '';
    notice.textContent = message; notice.hidden = !message;
    setActive(value('presentation') === '1'); paint(false);
  }
  keys.forEach((key, i) => {const option = element('option', (i + 1) + '. ' + slides[i].querySelector('h3').textContent); option.value = key; chooser.append(option);});
  items.forEach(item => {const option = element('option', item.title + ' / ' + item.scope); option.value = item.finding_id; findingChooser.append(option);});
  get('previous').addEventListener('click', () => move(-1)); get('next').addEventListener('click', () => move(1));
  chooser.addEventListener('change', () => {state.slide = keys.indexOf(chooser.value); state.reveal = 0; paint(true, true);});
  findingChooser.addEventListener('change', () => {state.finding = findingChooser.value; state.reveal = 0; paint(true);});
  get('start').addEventListener('click', () => {setActive(true); paint(true);});
  function toReport(heading, selected) {
    setActive(false); const url = stateURL(heading, false), part = fragment(url);
    if (selected) ['run', 'compareRun', 'case'].forEach(key => part.params.set(key, selected.get(key) || ''));
    url.hash = heading + '?' + part.params.toString(); writeURL(url);
    if (selected) window.dispatchEvent(new CustomEvent('report-explorer-select', {detail:Object.fromEntries(['run', 'compareRun', 'case'].map(key => [key, selected.get(key) || '']))}));
    const caseHeading = selected && selected.get('case') && document.getElementById('explorer-case-heading');
    const target = caseHeading || document.getElementById(heading);
    if (target) {if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1'); target.focus({preventScroll:true}); if (typeof target.scrollIntoView === 'function') target.scrollIntoView({behavior:'auto', block:'start'});}
  }
  root.addEventListener('click', event => {
    const anchor = event.target.closest('a'); if (!anchor || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (anchor.hasAttribute('data-presentation-finding-link')) {
      event.preventDefault(); state.finding = anchor.dataset.presentationFindingLink; state.slide = keys.indexOf('finding'); state.reveal = 0; setActive(true); paint(true, true);
    } else if (anchor.hasAttribute('data-presentation-evidence')) {
      event.preventDefault(); const target = fragment(new URL(anchor.href, window.location.href)); toReport('case-explorer-heading', target.params);
    } else if (anchor.hasAttribute('data-presentation-report')) {
      event.preventDefault(); toReport(fragment(new URL(anchor.href, window.location.href)).heading || 'deep-findings');
    }
  });
  document.addEventListener('keydown', event => {
    if (event.altKey || event.ctrlKey || event.metaKey || (!state.active && !root.contains(event.target))) return;
    if (event.key === 'Escape' && state.active) {event.preventDefault(); toReport('deep-findings'); return;}
    if (event.key === 'Tab' && state.active) {
      const focusable = Array.from(root.querySelectorAll('a[href],button:not([disabled]),select:not([disabled]),summary,[tabindex="0"]')).filter(node => !node.closest('[hidden]') && (!node.closest('details:not([open])') || node.tagName === 'SUMMARY'));
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || !focusable.includes(document.activeElement))) {event.preventDefault(); if (last) last.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); if (first) first.focus();}
      return;
    }
    if (event.target.closest('input,select,textarea,button,a,summary,[contenteditable]:not([contenteditable="false"]),.presentation-scroll,pre')) return;
    if (['ArrowRight','ArrowDown','PageDown',' ','ArrowLeft','ArrowUp','PageUp','Home','End'].includes(event.key)) {
      event.preventDefault(); if (['ArrowRight','ArrowDown','PageDown',' '].includes(event.key)) move(1);
      else if (['ArrowLeft','ArrowUp','PageUp'].includes(event.key)) move(-1);
      else {state.slide = event.key === 'Home' ? 0 : slides.length - 1; state.reveal = 0; paint(true, true);}
    }
  });
  root.classList.add('presentation-enhanced'); root.querySelector('.presentation-controls').hidden = false;
  root.querySelector('.presentation-finding-control').hidden = !items.length; get('start').hidden = false;
  window.addEventListener('hashchange', fromURL); window.addEventListener('popstate', fromURL); fromURL();
})();
</script>"""
