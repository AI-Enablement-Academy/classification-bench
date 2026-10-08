"""Private, self-contained HTML report from validated offline evidence."""

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from html import escape
import json
import math

from .core import ValidationError, _digest, evaluate, validate_reference_labels
from .report_analysis import build_analysis
from .report_explorer import render_report_explorer
from .report_findings import build_findings, render_findings
from .report_metrics import build_field_metrics, render_field_metrics
from .report_exports import build_report_exports, render_downloads
from .report_presentation import render_presentation
from .report_sensitivity import build_sensitivity, render_sensitivity
from .report_visuals import agreement_duration_plot
from .report_filters import render_report_filters
from .report_comparisons import build_comparative_findings, render_comparative_findings


def _h(value):
    return escape(str(value), quote=True)


def _rate(numerator, denominator):
    if numerator is None:
        return "unavailable"
    return f"{numerator}/{denominator} ({numerator / denominator:.1%})" if denominator else "0/0 (unavailable)"


def _number(value, unit=""):
    if value is None:
        return "unavailable"
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            (isinstance(value, float) and not math.isfinite(value)) or value < 0):
        raise ValidationError("operation measurement must be numeric or null")
    return f"{value:,.3f}{unit}" if isinstance(value, float) else f"{value:,}{unit}"


def _table(headers, rows, *, caption=None, row_header=False, numeric_columns=(), class_name=None):
    head = "".join(f"<th scope='col'>{_h(x)}</th>" for x in headers)
    body = ""
    for row in rows:
        cells = ""
        for index, value in enumerate(row):
            tag = "th" if row_header and index == 0 else "td"
            scope = " scope='row'" if tag == "th" else ""
            numeric = " class='numeric'" if index in numeric_columns else ""
            cells += f"<{tag}{scope}{numeric}>{_h(value)}</{tag}>"
        body += f"<tr>{cells}</tr>"
    label = f"<caption>{_h(caption)}</caption>" if caption else ""
    table_class = f" class='{class_name}'" if class_name else ""
    return f"<table{table_class}>{label}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _adapter_category(settings):
    """Group only declared adapter identities, never model-name guesses."""
    adapter = settings.get("adapter")
    if adapter is None or adapter == "":
        return "Adapter unspecified"
    if not isinstance(adapter, str):
        return "Invalid declared adapter"
    if adapter == "openrouter":
        return "OpenRouter"
    if adapter in {"liquid_decide", "solar_decide", "qwen_decision",
                   "clef_decide", "clef_flash_decide"}:
        return "Native decisions"
    if adapter in {"claude_code", "codex"}:
        return "Claude Code" if adapter == "claude_code" else "Codex"
    if adapter == "synthetic":
        return "Synthetic"
    return "Other declared adapter"


_MODEL_TYPE_LABELS = {
    "llm": "General LLM",
    "fine_tuned_llm": "Fine-tuned LLM",
    "decision": "Classification / decision",
    "unspecified": "Unspecified",
}


_NATIVE_PROVIDER = {"liquid_decide": "liquid", "solar_decide": "upstage",
                    "qwen_decision": "qwen", "clef_decide": "cloudflare",
                    "clef_flash_decide": "cloudflare"}
_NATIVE_MODEL = {"liquid_decide": "d1:free", "solar_decide": "solar-decide",
                 "qwen_decision": "decision-model-preview", "clef_decide": "clef",
                 "clef_flash_decide": "clef-flash"}


def _native_provider(settings):
    adapter = settings.get("adapter")
    return _NATIVE_PROVIDER.get(adapter) if isinstance(adapter, str) else None


def _first_metadata(*values):
    return next((value for value in values if value is not None and value != ""), None)


def _display_metadata(value, fallback="unavailable"):
    if value is None or value == "":
        return fallback
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _native_requested_route(config):
    settings = config.get("settings", {})
    adapter = settings.get("adapter")
    provider = _native_provider(settings)
    return f"{provider}:{config['model']}" if provider and config["model"] == _NATIVE_MODEL[adapter] else None


def _comparison_table(rows):
    """Keep display text and sort keys separate, especially for rates and gaps."""
    columns = (
        ("Configuration", "model", "text"), ("Prompt", "prompt", "text"),
        ("Exact agreement", "exact", "number"), ("Repeat range", "range", "number"),
        ("Invalid selected projections", "invalid", "number"),
        ("No selected prediction", "missing", "number"),
        ("Mean client request duration", "duration", "number"),
        ("Observed cost", "cost", "static"), ("Cost coverage", "coverage", "number"),
    )
    head = "".join(
        f"<th scope='col' aria-sort='none'><button type='button' class='sort-button' "
        f"data-sort='{key}' data-sort-type='{kind}' aria-label='Sort by {_h(label)}'>{_h(label)}"
        "<span class='sort-mark' aria-hidden='true'></span></button></th>"
        if kind != "static" else f"<th scope='col'>{_h(label)}</th>"
        for label, key, kind in columns)
    body = []
    for plot_id, entry in enumerate(rows):
        values = entry["display"]
        keys = entry["sort"]
        cells = []
        for index, ((_, key, _), value) in enumerate(zip(columns, values)):
            attrs = f" data-sort-value='{_h(keys[key])}'"
            if index == 0:
                content = (f"<strong class='model-name'>{_h(entry['model'])}</strong>"
                           f"<span class='model-meta'>{_h(value)} · requested provider: {_h(entry['provider'])}</span>"
                           f"<span class='model-meta'>Declared group: {_h(entry['model_type_label'])} · {_h(entry['category'])} · route: {_h(entry['route'])}</span>"
                           f"<span class='quality-note{' has-gaps' if entry['has_gaps'] else ''}'>{_h(entry['status'])}</span>"
                           f"<span class='row-actions'><label><input type='checkbox' class='compare-select' "
                           f"aria-label='Compare {_h(entry['model'])}, {_h(entry['config'])}, {_h(entry['prompt'])}'"
                           f"> Compare</label> <a href='#{_h(entry['anchor'])}'>Inspect condition</a></span>")
                cells.append(f"<th scope='row'{attrs}>{content}</th>")
            else:
                cls = " class='numeric'" if index in (2, 3, 4, 5, 6, 8) else ""
                cells.append(f"<td{cls}{attrs}>{_h(value)}</td>")
        body.append(f"<tr data-config-id='{_h(entry['config'])}' data-prompt-id='{_h(entry['prompt'])}' "
                    f"data-prompt='{_h(entry['prompt'])}' data-run-ids='{_h(json.dumps(entry['run_ids']))}' "
                    f"data-category='{_h(entry['category'])}' data-model='{_h(entry['model'])}' "
                    f"data-model-type='{_h(entry['model_type'])}' data-model-type-label='{_h(entry['model_type_label'])}' "
                    f"data-plot-id='{plot_id}' data-plot-state='{entry['plot_state']}' "
                    f"data-provider='{_h(entry['provider'])}' data-route='{_h(entry['route'])}'>"
                    + "".join(cells) + "</tr>")
    return ("<div class='table-scroll' tabindex='0' role='region' aria-label='Configuration comparison table'>"
            "<table class='comparison-table'><caption>Configuration and prompt comparison (all planned passes per condition)</caption>"
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")


_MEASUREMENTS = ("duration_seconds", "provider_generation_seconds", "pure_inference_seconds",
                 "observed_cost_micro_usd", "estimated_cost_micro_usd", "unresolved_hold_micro_usd")


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _usage_count(operation, usage, flat, nested_parent=None, nested_key=None):
    """Prefer the saved raw usage path; never turn a bad value into zero."""
    source = None
    if nested_parent is not None and nested_parent in usage:
        details = usage[nested_parent]
        if not isinstance(details, dict):
            return None, f"{nested_parent} is malformed"
        if nested_key in details:
            value = _count(details[nested_key])
            if value is None:
                return None, f"{nested_parent}.{nested_key} is malformed"
            source = f"{nested_parent}.{nested_key}"
    if source is None and flat in usage:
        value = _count(usage[flat])
        if value is None:
            return None, f"usage.{flat} is malformed"
        source = f"usage.{flat}"
    if source is None:
        value = _count(operation.get(flat))
        if value is None:
            return None, f"{flat} unavailable"
        source = f"operation.{flat}"
    return value, None


def _price(pricing, key):
    value = pricing.get(key)
    if not isinstance(value, str):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


def _derived_telemetry(operation, config):
    """Return a report view; preserve the verified operation object unchanged."""
    view = dict(operation)
    usage = operation.get("usage")
    notes = []
    if usage is None:
        usage = {}
    elif not isinstance(usage, dict):
        usage = {}
        notes.append("raw usage is malformed")
    for target, flat, parent, nested in (
        ("input_tokens", "prompt_tokens", None, None),
        ("output_tokens", "completion_tokens", None, None),
        ("reasoning_tokens", "reasoning_tokens", "completion_tokens_details", "reasoning_tokens"),
        ("cache_tokens", "cached_tokens", "prompt_tokens_details", "cached_tokens"),
    ):
        if parent is None and flat != target and flat not in usage and target in usage:
            flat = target
        value, note = _usage_count(operation, usage, flat, parent, nested)
        if value is None and target in operation and flat != target and flat not in usage and parent is None:
            value = _count(operation[target])
            note = None if value is not None else note
        if value is None and target in operation and parent is not None and parent not in usage and flat not in usage:
            value = _count(operation[target])
            note = None if value is not None else note
        if (parent is not None and isinstance(usage.get(parent), dict) and nested in usage[parent]
                and value is not None and operation.get(target) is not None and operation[target] != value):
            notes.append(f"raw {parent}.{nested} overrides conflicting flat {target}")
        view[target] = value
        if note:
            notes.append(note)
    if (view["reasoning_tokens"] is not None and view["output_tokens"] is not None and
            view["reasoning_tokens"] > view["output_tokens"]):
        view["reasoning_tokens"] = None
        notes.append("reasoning tokens exceed completion tokens")
    if (view["cache_tokens"] is not None and view["input_tokens"] is not None and
            view["cache_tokens"] > view["input_tokens"]):
        view["cache_tokens"] = None
        notes.append("cached tokens exceed prompt tokens")
    view["estimated_cost_micro_usd"] = None
    view["_estimate_basis"] = "unavailable"
    view["_snapshot_hash"] = None
    settings = config.get("settings", {})
    snapshot = settings.get("endpoint_snapshot") if isinstance(settings, dict) else None
    if settings.get("adapter") != "openrouter" or operation.get("cost_currency", "USD") != "USD":
        reason = "No USD OpenRouter endpoint snapshot applies."
    elif not isinstance(snapshot, dict) or not isinstance(snapshot.get("pricing"), dict):
        reason = "Frozen endpoint pricing is unavailable."
    else:
        view["_snapshot_hash"] = _digest(snapshot)
        pricing = snapshot["pricing"]
        prompt, completion, request = (_price(pricing, name) for name in ("prompt", "completion", "request"))
        no_tool_search_route = (config.get("model"), settings.get("provider")) == (
            "openai/gpt-4.1-nano", "openai")
        supported = {"prompt", "completion", "request", "input_cache_read"}
        extras = [key for key in pricing if key not in supported and _price(pricing, key) != Decimal(0)
                  and not (key == "web_search" and no_tool_search_route)]
        details = usage.get("prompt_tokens_details")
        write_reported = isinstance(details, dict) and "cache_write_tokens" in details
        if write_reported:
            writes = _count(details["cache_write_tokens"])
        else:
            writes = None
        returned_model = operation.get("returned_model")
        identity_error = (operation.get("provider_identity_status") == "identity_error" or
                          operation.get("reason") in ("returned provider mismatch", "returned model mismatch",
                                                      "provider generation identity mismatch"))
        if returned_model is not None and returned_model != config.get("model"):
            reason = "Returned model differs from the frozen priced model."
        elif identity_error:
            reason = "Provider identity evidence conflicts with the requested route."
        elif snapshot.get("model_id") != config.get("model") or snapshot.get("provider_tag") != settings.get("provider"):
            reason = "Frozen endpoint identity does not match the configuration."
        elif any(value is None for value in (view["input_tokens"], view["output_tokens"])):
            reason = "Prompt or completion token count is unavailable."
        elif details is not None and not isinstance(details, dict):
            reason = "Cache detail object is malformed."
        elif writes is None and (write_reported or not no_tool_search_route):
            reason = "Cache write count is unavailable or malformed."
        elif writes is not None and writes > 0:
            reason = "Cache writes need a verified write and storage price."
        elif extras:
            reason = "Frozen endpoint pricing has unsupported nonzero components."
        elif any(value is None for value in (prompt, completion, request)):
            reason = "Frozen endpoint prompt, completion or request price is invalid."
        else:
            value = (Decimal(view["input_tokens"]) * prompt +
                     Decimal(view["output_tokens"]) * completion + request)
            view["estimated_cost_micro_usd"] = int((value * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
            view["_estimate_basis"] = (f"Standard input-rate token-price estimate: ceil(1,000,000 × "
                                       f"(({view['input_tokens']} prompt × {prompt} USD) + "
                                       f"({view['output_tokens']} completion × {completion} USD) + "
                                       f"{request} USD request fee)); cache savings excluded; "
                                       "reasoning is included in completion. "
                                       "Frozen requested-route prices; actual serving endpoint price is unverified.")
            reason = None
    if reason:
        view["_estimate_basis"] = reason
    view["_telemetry_note"] = "; ".join(notes) or "none"
    return view


def _svg(title, description, contents, chart_id, height, width=760):
    return (f"<svg role='img' aria-labelledby='{chart_id}-title {chart_id}-desc' "
            f"viewBox='0 0 {width} {height}' width='100%' height='{height}' xmlns='http://www.w3.org/2000/svg'>"
            f"<title id='{chart_id}-title'>{_h(title)}</title>"
            f"<desc id='{chart_id}-desc'>{_h(description)}</desc>"
            "<style>text{font:14px system-ui,sans-serif;fill:#18222c}.score{fill:#176c8a}.delta{fill:#9a4b11}"
            ".range{stroke:#273747;stroke-width:5}</style>" + contents + "</svg>")


def _score_visual(condition, chart_id):
    passes = condition["passes"]
    partial = condition["pass_score_range"] is None
    if partial and condition["scored_subset_score_range"] is None:
        return "<p>Exact agreement chart unavailable: no cases have complete references.</p>"
    body = ""
    for index, entry in enumerate(passes):
        score = entry["scored_subset"] if partial else entry
        y = 38 + index * 42
        width = round(300 * score["all_field_exact_rate"], 2)
        body += (f"<text x='5' y='{y + 15}'>Pass {entry['repeat']}</text>"
                 f"<rect class='score' x='140' y='{y}' width='{width}' height='20'/>"
                 f"<text x='450' y='{y + 15}'>{score['all_field_exact']}/{score['denominator']} "
                 f"({score['all_field_exact_rate']:.1%})</text>")
    low, high = condition["scored_subset_score_range"] if partial else condition["pass_score_range"]
    y = 46 + len(passes) * 42
    x1, x2 = 140 + 300 * low, 140 + 300 * high
    body += (f"<text x='5' y='{y}'>Pass range</text>"
             f"<line class='range' x1='{x1:.2f}' x2='{x2:.2f}' y1='{y - 5}' y2='{y - 5}'/>"
             f"<text x='450' y='{y}'>{low:.1%} to {high:.1%}</text>")
    title = "Scored subset exact agreement by pass" if partial else "Exact agreement by pass"
    description = ("Bars include only cases with complete references; missing and invalid predictions on those cases receive no credit. Cases without complete references are excluded from this scored subset. The line shows the range across passes."
                   if partial else "Bars show all-field exact agreement divided by every planned case in each pass. The line shows the range across passes.")
    return _svg(title, description,
                body, chart_id, y + 20)


def _delta_visual(condition, baseline_scores, baseline_id, chart_id):
    body = ""
    details = []
    for index, entry in enumerate(condition["passes"]):
        before = baseline_scores[entry["repeat"]]
        delta = entry["all_field_exact"] - before
        y = 30 + index * 40
        x = 300 if delta >= 0 else 300 - 200 * abs(delta) / entry["denominator"]
        width = 200 * abs(delta) / entry["denominator"]
        body += (f"<text x='5' y='{y + 15}'>Pass {entry['repeat']}</text>"
                 f"<line x1='300' x2='300' y1='{y - 2}' y2='{y + 24}' stroke='#273747'/>"
                 f"<rect class='delta' x='{x:.2f}' y='{y}' width='{width:.2f}' height='20'/>"
                 f"<text x='520' y='{y + 15}'>{delta:+d}/{entry['denominator']}</text>")
        details.append(f"pass {entry['repeat']}: {delta:+d} exact matches")
    return _svg("Paired prompt effect", f"Difference from {baseline_id} within each pass; left is fewer exact matches and right is more. "
                + "; ".join(details), body, chart_id, 45 + len(condition["passes"]) * 40)


def _cost_visual(condition, costs, chart_id, currency):
    known = [value for value in costs.values() if value is not None]
    if not known or condition["pass_score_range"] is None:
        return ""
    highest = max(known) or 1
    body = f"<text x='140' y='20'>Agreement</text><text x='385' y='20'>Observed {_h(currency)}</text>"
    for index, entry in enumerate(condition["passes"]):
        y = 34 + index * 42
        cost = costs.get(entry["repeat"])
        body += (f"<text x='5' y='{y + 15}'>Pass {entry['repeat']}</text>"
                 f"<rect class='score' x='140' y='{y}' width='{200 * entry['all_field_exact_rate']:.2f}' height='20'/>"
                 f"<text x='345' y='{y + 15}'>{entry['all_field_exact_rate']:.0%}</text>")
        if cost is None:
            body += f"<text x='600' y='{y + 15}'>unavailable</text>"
        else:
            body += (f"<rect class='delta' x='385' y='{y}' width='{200 * cost / highest:.2f}' height='20'/>"
                     f"<text x='600' y='{y + 15}'>{_number(cost)}</text>")
    return _svg("Agreement and observed cost", f"Each row shows exact agreement on the full denominator and the sum of recorded {currency} for that pass. Cost bars scale to the largest observed pass value; missing values remain unavailable.",
                body, chart_id, 44 + len(condition["passes"]) * 42)


def _raw_usage_disclosures(records):
    parts = []
    for record in records:
        usage = record.get("usage")
        payload = json.dumps(usage, ensure_ascii=False, sort_keys=True, indent=2) if usage is not None else "unavailable"
        parts.append(f"<details class='raw-usage'><summary>Saved raw usage for request {_h(record['request_id'])}</summary>"
                     f"<pre>{_h(payload)}</pre></details>")
    return "".join(parts)


def _operation_summary(records, planned_count, currency):
    if not records:
        return f"<p>No request evidence supplied for {planned_count} planned request(s); timing, token and cost measures are unavailable.</p>"
    states = Counter(str(record.get("state") or "unavailable") for record in records)
    states["no operation record"] += planned_count - len(records)
    parsed = Counter(str(record.get("parsed_status") or "unavailable") for record in records)
    parsed["no operation record"] += planned_count - len(records)
    state_text = ", ".join(f"{state}: {count}" for state, count in sorted(states.items()) if count)
    parsed_text = ", ".join(f"{state}: {count}" for state, count in sorted(parsed.items()) if count)
    cells = []
    for key, label, unit in (
        ("duration_seconds", "Client request duration", " s"),
        ("provider_generation_seconds", "Provider generation time", " s"),
        ("pure_inference_seconds", "Pure inference time", " s"),
    ):
        values = [r.get(key) for r in records if r.get(key) is not None]
        cells.append((label, f"{_number(sum(values) / len(values), unit)} mean across {len(values)} request(s)" if values else "unavailable"))
    distinct_charge_currencies = {_cost_currency(r, currency) for r in records
                                  if r.get("observed_cost_micro_usd") is not None}
    distinct_hold_currencies = {_cost_currency(r, currency) for r in records
                                if r.get("unresolved_hold_micro_usd") is not None}
    charge_currency = next(iter(distinct_charge_currencies), currency) if len(distinct_charge_currencies) <= 1 else currency
    for key, label in (
        ("input_tokens", "Input tokens"), ("output_tokens", "Output tokens"),
        ("reasoning_tokens", "Reasoning tokens"), ("cache_tokens", "Cache tokens"),
        ("observed_cost_micro_usd", "Observed provider charges"),
        ("estimated_cost_micro_usd", "Pricing estimates"),
        ("unresolved_hold_micro_usd", "Unresolved budget holds"),
    ):
        if key == "observed_cost_micro_usd" and charge_currency == "SYN units" and len(distinct_charge_currencies) <= 1:
            label = "Observed synthetic accounting"
        if key == "observed_cost_micro_usd" and len(distinct_charge_currencies) > 1:
            for unit in sorted(distinct_charge_currencies):
                values = [r[key] for r in records if r.get(key) is not None and _cost_currency(r, currency) == unit]
                cells.append((f"Observed charges ({unit})",
                              f"{_number(sum(values), ' ' + unit)} across {len(values)} request(s)"))
            continue
        if key == "unresolved_hold_micro_usd" and len(distinct_hold_currencies) > 1:
            for unit in sorted(distinct_hold_currencies):
                values = [r[key] for r in records if r.get(key) is not None and _cost_currency(r, currency) == unit]
                cells.append((f"Unresolved budget holds ({unit})",
                              f"{_number(sum(values), ' ' + unit)} across {len(values)} request(s)"))
            continue
        values = [r.get(key) for r in records if r.get(key) is not None]
        unit = (charge_currency if key == "observed_cost_micro_usd" else
                next(iter(distinct_hold_currencies), currency) if key == "unresolved_hold_micro_usd" else
                "micro USD" if key == "estimated_cost_micro_usd" and values else currency)
        suffix = f" {unit}" if key.endswith("micro_usd") else ""
        cells.append((label, f"{_number(sum(values), suffix)} across {len(values)} request(s)" if values else "unavailable"))
    if len(distinct_charge_currencies) > 1:
        subscription = "Recorded cost units vary by request; SYN units are not provider charges. Subscription cost: unavailable."
    else:
        subscription = "Synthetic accounting is not a provider charge." if charge_currency == "SYN units" else "Subscription cost: unavailable."
    identity_rows = [(r['request_id'], r.get('model') or 'unavailable',
                      r.get('returned_model') or 'unavailable',
                      r.get('frozen_canonical_model') or 'unavailable',
                      r.get('generation_returned_model') or 'unavailable',
                      r.get('provider') or 'unavailable',
                      r.get('returned_provider') or 'unavailable',
                      r.get('provider_identity_status') or 'unavailable',
                      r.get('receipt_sha256') or 'unavailable') for r in records]
    mixed_charges = len(distinct_charge_currencies) > 1
    telemetry_rows = [
        (r["request_id"], _number(r.get("input_tokens")), _number(r.get("output_tokens")),
         _number(r.get("reasoning_tokens")), _number(r.get("cache_tokens")),
         (_number(r.get("observed_cost_micro_usd"), " " + _cost_currency(r, currency))
          if mixed_charges else _number(r.get("observed_cost_micro_usd"))),
         _number(r.get("estimated_cost_micro_usd")),
         r.get("_estimate_basis") or "unavailable", r.get("_snapshot_hash") or "unavailable",
         r.get("_telemetry_note") or "none") for r in records]
    return (f"<p>Request lifecycle: {_h(state_text)}. Parsed outcomes: {_h(parsed_text)}. "
            f"{subscription}</p>") + _table(
        ("Measure", "Recorded value"), cells, caption="Request measurement summary") + (
        "<details class='request-evidence'><summary>Full request identity and telemetry evidence</summary>"
        "<p>Frozen canonical model comes from the enrolled endpoint snapshot. "
        "Generation returned model comes from saved generation metadata. "
        "Unavailable means that evidence did not provide the value.</p>") + _table(
        ("Request ID", "Requested model", "Completion returned model", "Frozen canonical model",
         "Generation returned model", "Requested provider", "Observed provider",
         "Provider identity evidence", "Supplied receipt evidence / pointer"), identity_rows,
        caption="Request model and provider identity") + (
        "<p>Token detail comes from saved usage. Token-price estimates use the frozen endpoint snapshot at the standard input rate, exclude cache savings, and are separate from observed charges. "
        "Unavailable values are omitted from totals.</p>" + _table(
            ("Request ID", "Input tokens", "Output tokens", "Reasoning tokens", "Cached tokens",
             f"Observed charge ({'per request currency' if mixed_charges else charge_currency})",
             f"Price estimate ({'micro USD' if any(r.get('estimated_cost_micro_usd') is not None for r in records) else currency})", "Estimate basis or limit",
             "Endpoint snapshot SHA-256", "Telemetry note"), telemetry_rows,
            caption="Request token and cost telemetry", numeric_columns=(1, 2, 3, 4, 5, 6))
        + _raw_usage_disclosures(records) + "</details>")


def _observed_outcome(key, invalid, supplied, operation):
    """Classify one planned position once, using parsed evidence where present."""
    parsed = operation.get("parsed_status") if operation else None
    if key in invalid:
        return "invalid"
    if key in supplied:
        return "valid selected"
    if parsed in ("invalid", "refused", "failed", "unknown"):
        return parsed
    if parsed == "valid":
        return "valid response, no selected prediction"
    if parsed == "unavailable":
        return "parsed outcome unavailable"
    if operation is None:
        return "no operation record"
    state = operation.get("state")
    if state in ("never_sent", "ready", "claimed"):
        return "never sent"
    if state in ("dispatch_intent", "outcome_unknown"):
        return "dispatch outcome unknown"
    return "no selected prediction; outcome unavailable"


def _cost_currency(operation, fallback):
    if operation.get("cost_currency") == "SYN" or str(operation.get("route", "")).startswith("synthetic:"):
        return "SYN units"
    if operation.get("cost_currency") == "USD":
        return "micro USD"
    return fallback


_REPORT_CSS = """
:root{color-scheme:light;--paper:#f8f7f4;--surface:#fff;--ink:#222823;--muted:#59635d;--line:#dcded8;--accent:#245b4b;--soft:#e9efe9;--danger:#a3362c}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums}
.shell{width:min(100% - 3rem,1360px);margin-inline:auto}h1,h2,h3,h4{line-height:1.15;letter-spacing:-.035em;text-wrap:balance}h1{font-size:clamp(2.7rem,6vw,5.5rem);max-width:13ch;margin:.75rem 0 1rem;font-weight:750}h2{font-size:clamp(1.7rem,3vw,2.5rem);margin:0 0 .75rem}h3{font-size:1.35rem;margin:0 0 .7rem}h4{font-size:1.08rem;margin:2rem 0 .6rem}p{max-width:72ch;margin:.65rem 0 1rem}a{color:var(--accent);text-underline-offset:.18em}
.masthead{border-bottom:1px solid var(--line);padding:2.2rem 0 2.7rem}.eyebrow{color:var(--accent);font-weight:700;font-size:.76rem;letter-spacing:.13em;text-transform:uppercase}.lead{font-size:1.12rem;color:var(--muted)}.overview-meta{display:flex;flex-wrap:wrap;gap:1rem 2rem;padding:1.15rem 0;margin-top:2rem;border-top:1px solid var(--line)}.overview-meta span{display:block}.meta-label{font-size:.73rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}.meta-value{font-size:1.1rem;font-weight:650}
.jump-nav{display:flex;flex-wrap:wrap;gap:1.4rem;margin-top:1.5rem;font-size:.85rem;font-weight:650}.jump-nav a{text-decoration:none;border-bottom:2px solid transparent;padding-bottom:.2rem}.jump-nav a:hover,.jump-nav a:focus-visible{border-color:var(--accent)}
main{padding-bottom:5rem}.comparison-section{padding:3.5rem 0 3rem}.section-intro{display:flex;justify-content:space-between;align-items:end;gap:2rem;flex-wrap:wrap}.section-intro p{color:var(--muted)}.comparison-tools{display:flex;gap:.7rem;align-items:end;flex-wrap:wrap;margin:1.5rem 0 .5rem}.comparison-tools label{font-size:.8rem;font-weight:650}.comparison-tools input{display:block;margin-top:.35rem;width:min(23rem,80vw);padding:.6rem .75rem;border:1px solid #aeb9af;border-radius:3px;background:var(--surface);color:var(--ink);font:inherit}.comparison-tools small{color:var(--muted)}
.table-scroll{overflow-x:auto;max-width:100%;background:var(--surface);border-top:2px solid var(--ink);border-bottom:1px solid var(--line)}table{border-collapse:collapse;width:100%;font-size:.88rem}caption{text-align:left;font-weight:650;padding:.8rem 0;color:var(--muted)}.comparison-table{min-width:1080px}.comparison-table caption{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}.comparison-table th,.comparison-table td{padding:1rem .8rem;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}.comparison-table thead th{font-size:.73rem;letter-spacing:.02em;color:var(--muted);font-weight:600;background:#f1f2ed}.comparison-table tbody tr:hover{background:#f7f9f5}.comparison-table tbody tr:last-child th,.comparison-table tbody tr:last-child td{border-bottom:0}.comparison-table .numeric{text-align:right;white-space:nowrap}.model-name,.model-meta,.quality-note{display:block}.model-name{font-size:.97rem;line-height:1.3;color:var(--ink);font-weight:700}.model-meta{font-size:.76rem;color:var(--muted);margin-top:.23rem;font-weight:500}.quality-note{font-size:.72rem;color:var(--muted);margin-top:.5rem}.quality-note.has-gaps{color:var(--danger)}.sort-button{border:0;background:transparent;padding:0;color:inherit;font:inherit;font-weight:inherit;text-align:inherit;cursor:pointer}.sort-button:hover{color:var(--accent)}.sort-mark{margin-left:.3rem;color:var(--accent)}.sort-mark::after{content:' ↕'}.comparison-table [aria-sort=descending] .sort-mark::after{content:' ↓'}.comparison-table [aria-sort=ascending] .sort-mark::after{content:' ↑'}
.summary-section,.detail-index,.condition,.provenance{border-top:1px solid var(--line);padding:2.4rem 0}.summary-section{display:grid;grid-template-columns:minmax(15rem,.7fr) minmax(0,1.3fr);gap:2rem}.summary-section>div>p{color:var(--muted)}.summary-data{min-width:0}.summary-data table,.condition table,.pass table,.provenance table{display:block;overflow-x:auto;max-width:100%}.summary-data th,.summary-data td,.condition th,.condition td,.pass th,.pass td,.provenance th,.provenance td{padding:.55rem .7rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere}.numeric,.outcome-table td:nth-child(n+2){text-align:right;font-variant-numeric:tabular-nums}.condition{scroll-margin-top:1rem}.condition-header{display:flex;justify-content:space-between;gap:1rem;align-items:baseline;flex-wrap:wrap}.condition p,.pass p{color:var(--muted)}.condition svg{max-width:100%;height:auto;margin:1rem 0}.pass{border-top:1px solid var(--line);padding:2rem 0;scroll-margin-top:1rem}.pass h3{color:var(--accent)}.detail-index ul{columns:2;list-style:none;padding:0}.detail-index li{break-inside:avoid;margin:.3rem 0}.contents-pass{margin-left:1rem;font-size:.85rem}.provenance{font-size:.88rem;color:var(--muted)}.provenance h2{color:var(--ink)}
.filters{padding:1.5rem 0 2rem;border-top:1px solid var(--line)}.filter-grid{display:flex;flex-wrap:wrap;gap:.7rem 1rem;align-items:end}.filter-grid label{font-size:.76rem;font-weight:650;color:var(--muted)}.filter-grid select{display:block;margin-top:.25rem;min-width:7.5rem;max-width:14rem;padding:.45rem;border:1px solid #aeb9af;background:var(--surface);color:var(--ink);font:inherit;font-size:.86rem}.filter-grid button{padding:.46rem .8rem;border:1px solid var(--accent);background:transparent;color:var(--accent);font:inherit;cursor:pointer}.filter-grid button:hover{background:var(--soft)}.filter-grid button:active{transform:translateY(1px)}.filter-grid button,.sort-button,.jump-nav a{transition:background .2s,color .2s,border-color .2s}.status-line{font-size:.8rem;color:var(--muted)}
details{margin-top:1rem}.raw-usage pre{max-height:24rem;overflow:auto;padding:1rem;background:#f1f2ed;border:1px solid var(--line);font-size:.78rem;white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer;color:var(--accent);font-weight:650}.notice{border-left:3px solid var(--accent);padding-left:.75rem}.skip-link{position:absolute;left:-10000px}.skip-link:focus{left:1rem;top:1rem;z-index:2;background:var(--surface);padding:.5rem}.pass[hidden],article[hidden],[hidden]{display:none!important}a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible,summary:focus-visible,.table-scroll:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
@media(max-width:760px){.shell{width:min(100% - 2rem,1360px)}.masthead{padding-top:1.5rem}.summary-section{display:block}.detail-index ul{columns:1}.comparison-section{padding-top:2.5rem}.comparison-table{min-width:930px}}
.jump-nav{position:sticky;top:0;z-index:2;margin:0;background:rgba(248,247,244,.97);border-bottom:1px solid var(--line);backdrop-filter:blur(12px)}.jump-nav .shell{display:flex;flex-wrap:wrap;gap:.3rem 1.8rem;padding:.8rem 0}.jump-nav a{padding:.35rem 0;border-bottom:2px solid transparent}.jump-nav a[aria-current=location]{color:var(--ink);border-color:var(--accent)}
.comparison-section,.summary-section,.filters,.provenance,h2[id]{scroll-margin-top:5rem}.category-rail{display:flex;gap:.35rem;overflow-x:auto;border-bottom:1px solid var(--line);padding:1.4rem 0 .6rem}.category-rail button{white-space:nowrap;border:0;border-bottom:2px solid transparent;background:transparent;padding:.6rem .9rem;color:var(--muted);font-family:inherit;font-size:.85rem;font-weight:600;line-height:1.3;cursor:pointer}.category-rail button span{font-variant-numeric:tabular-nums;color:var(--muted);margin-left:.4rem}.category-rail button[aria-pressed=true]{border-color:var(--accent);color:var(--ink)}.category-rail button:hover{background:var(--soft)}
.comparison-tools{align-items:end;padding:.8rem 0 1rem}.comparison-tools label{display:block;color:var(--muted)}.comparison-tools select{display:block;margin-top:.35rem;min-width:9rem;max-width:14rem;padding:.6rem .75rem;border:1px solid #aeb9af;border-radius:3px;background:var(--surface);color:var(--ink);font:inherit}.comparison-tools button{padding:.6rem .75rem;border:1px solid var(--accent);background:transparent;color:var(--accent);font:inherit;cursor:pointer}.comparison-tools button:hover{background:var(--soft)}
.row-actions{display:flex;gap:.7rem;align-items:center;flex-wrap:wrap;margin-top:.8rem;font-size:.75rem;font-weight:600}.row-actions label{display:inline-flex;align-items:center;gap:.3rem;cursor:pointer}.row-actions input{accent-color:var(--accent)}.row-actions a{white-space:nowrap}.selection-section{margin-top:1.4rem;padding:1.5rem 0;border-top:1px solid var(--line)}.selection-section h3{margin:.3rem 0}.selection-section .section-intro p{font-size:.84rem;max-width:48ch}.selection-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.selection-card{padding:1.3rem;background:var(--surface);border-top:3px solid var(--accent);min-width:0}.selection-card>p{font-size:.8rem;color:var(--muted);overflow-wrap:anywhere}.selection-card dl{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.3rem .8rem;margin:1rem 0 0;font-size:.82rem}.selection-card dt,.selection-card dd{border-top:1px solid var(--line);margin:0;padding:.45rem 0}.selection-card dd{text-align:right;font-variant-numeric:tabular-nums;max-width:22ch}.selection-outside{color:var(--danger)!important;font-weight:650}.compare-select:disabled{cursor:not-allowed}
.selection-section>button{margin:.2rem 0 1rem;padding:.5rem .75rem;border:1px solid var(--accent);background:transparent;color:var(--accent);font:inherit;cursor:pointer}.selection-section>button:hover:not(:disabled){background:var(--soft)}.selection-section>button:disabled{opacity:.45;cursor:default}
.category-rail button,.comparison-tools button,.row-actions a,.selection-card,.jump-nav a{transition:background-color .18s ease,color .18s ease,transform .18s ease}.category-rail button:active,.comparison-tools button:active{transform:translateY(1px)}.category-rail button:focus-visible,.comparison-tools button:focus-visible,.row-actions input:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.rail-label{margin:1.2rem 0 0;color:var(--muted);font-size:.72rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase}.category-rail{padding-top:.35rem}.duration-overview{margin:2rem 0 0;padding:1.5rem;background:var(--surface);border-top:2px solid var(--ink)}.duration-overview-intro{display:flex;justify-content:space-between;gap:1.5rem;flex-wrap:wrap}.duration-overview-intro p{font-size:.84rem;color:var(--muted)}.agreement-duration-chart{display:block;width:min(100%,780px);height:auto;margin:1rem auto;color:var(--muted);font-size:12px;font-family:inherit}.plot-axis{stroke:var(--ink);stroke-width:1.4}.plot-guide{stroke:var(--line);stroke-width:1;stroke-dasharray:4 4}.duration-point circle{fill:var(--accent);stroke:var(--surface);stroke-width:2}.duration-point:hover circle,.duration-point:focus-visible circle{fill:var(--ink);stroke:var(--accent);stroke-width:4}.duration-point:focus-visible{outline:none}.duration-point:focus-visible circle{filter:drop-shadow(0 0 3px var(--accent))}.duration-overview .status-line{margin-bottom:0}
.plot-key{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,19rem),1fr));gap:.45rem 1.25rem;margin:0;padding:0;list-style:none}.plot-key-row{display:flex;align-items:baseline;gap:.25rem .65rem;flex-wrap:wrap;border-top:1px solid var(--line);padding:.55rem 0;font-size:.78rem}.plot-key-row a{font-weight:700}.plot-key-row span{color:var(--muted)}
@media(max-width:760px){.jump-nav .shell{flex-wrap:nowrap;overflow-x:auto}.jump-nav a{white-space:nowrap}.selection-cards{grid-template-columns:1fr}.comparison-tools label{width:calc(50% - .7rem)}.comparison-tools input,.comparison-tools select{width:100%;max-width:none}.selection-card dl{grid-template-columns:minmax(0,1fr) minmax(8rem,auto)}}
@media(max-width:500px){.comparison-tools label{width:100%}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{transition-duration:.01ms!important;animation-duration:.01ms!important;animation-iteration-count:1!important}}
"""


def generate_report(task, plan, labels=None, predictions=None, operations=None, *,
                    allow_partial_references=False, scenarios=None, cohort_declarations=None):
    """Return a local HTML report. Inputs and references remain in its case details."""
    result = evaluate(task, plan, labels, predictions,
                      allow_partial_references=allow_partial_references)
    complete_references = result["schema_version"] == 1
    if operations is None:
        operations = []
    if not isinstance(operations, list) or any(not isinstance(x, dict) for x in operations):
        raise ValidationError("operations: expected a list of records")
    request_map = {r["request_id"]: r for r in plan["requests"]}
    operation_map = defaultdict(list)
    position_operation = {}
    seen_operations = set()
    for record in operations:
        rid = record.get("request_id")
        if rid not in request_map:
            raise ValidationError(f"operation: unknown request_id {rid!r}")
        if rid in seen_operations:
            raise ValidationError(f"operation: duplicate request_id {rid!r}")
        seen_operations.add(rid)
        request = request_map[rid]
        for key in ("config_id", "prompt_id", "repeat"):
            if key in record and record[key] != request[key]:
                raise ValidationError(f"operation: {key} disagrees with plan")
        membership = [item["id"] for item in request["items"]]
        if "ids" in record and record["ids"] != membership:
            raise ValidationError("operation: ids disagree with plan membership")
        for record_id in membership:
            position_operation[(request["config_id"], request["prompt_id"],
                                request["repeat"], record_id)] = record
        for key in _MEASUREMENTS:
            if key in record and record[key] is not None:
                _number(record[key])
        operation_map[rid].append(record)

    analysis = build_analysis(task, plan, predictions, labels=labels, operations=operations,
                              cohort_declarations=cohort_declarations)
    field_metrics = build_field_metrics(analysis)
    metric_runs = {(run["config_id"], run["prompt_id"], run["repeat"]): run
                   for run in field_metrics["runs"].values()}
    analysis_runs = {(run["config_id"], run["prompt_id"], run["repeat"]): run
                     for run in analysis["runs"]}
    configs = {x["id"]: x for x in plan["experiment"]["configs"]}
    prompts = {x["id"]: x for x in plan["experiment"]["prompts"]}
    supplied = {(x["config_id"], x["prompt_id"], x["repeat"], x["id"]): x["prediction"]
                for x in predictions["records"]}
    invalid = {(x["config_id"], x["prompt_id"], x["repeat"], x["id"]) for x in result["invalid"]}
    items = {x["id"]: x["input"] for x in plan["requests"][0]["items"]}
    for req in plan["requests"]:
        if req["config_id"] == plan["experiment"]["configs"][0]["id"] and req["prompt_id"] == plan["experiment"]["prompts"][0]["id"] and req["repeat"] == 1:
            items.update({x["id"]: x["input"] for x in req["items"]})
    all_ids = list(items)
    references = validate_reference_labels(labels, task, all_ids,
                                          allow_partial=allow_partial_references)
    total = result["positions"]
    valid_count = total - result["missing"] - len(result["invalid"])
    outcomes = {key: _observed_outcome(key, invalid, supplied, position_operation.get(key))
                for request in plan["requests"] for item in request["items"]
                for key in [(request["config_id"], request["prompt_id"], request["repeat"], item["id"])]}
    outcome_counts = Counter(outcomes.values())
    if sum(outcome_counts.values()) != total:
        raise ValidationError("report outcomes do not cover the planned denominator")
    pages = []
    contents = []
    comparison_rows = []
    score_by_pass = {}
    subset_by_pass = {}
    for condition in result["conditions"]:
        cid, pid = condition["config_id"], condition["prompt_id"]
        for entry in condition["passes"]:
            score_by_pass[(cid, pid, entry["repeat"])] = entry["all_field_exact"]
            if not complete_references:
                subset_by_pass[(cid, pid, entry["repeat"])] = entry["scored_subset"]
    baseline = plan["experiment"]["prompts"][0]["id"]
    findings = [f"{valid_count} of {total} planned positions have a valid selected classification. "
                f"{result['missing']} have no selected prediction; {len(result['invalid'])} have an invalid selected projection. "
                "Observed runner outcomes are counted separately below, once per planned position. "
                + ("A valid classification may still disagree with its reference."
                   if complete_references else "Reference agreement is available only for supplied valid labels; unknown references are not counted as errors.")]
    if len(prompts) > 1:
        findings.append(f"Prompt effects compare each prompt with {_h(baseline)} within the same configuration and pass.")

    for condition_index, condition in enumerate(result["conditions"]):
        cid, pid = condition["config_id"], condition["prompt_id"]
        condition_anchor = f"condition-{condition_index}"
        contents.append(f"<li><a href='#{condition_anchor}'>{_h(cid)} · {_h(pid)}</a></li>")
        config, prompt = configs[cid], prompts[pid]
        settings = config.get("settings", {})
        currency = "SYN units" if (settings.get("adapter") == "synthetic" or
                                    any(str(op.get("route", "")).startswith("synthetic:")
                                        for op in operations
                                        if request_map[op["request_id"]]["config_id"] == cid)) else "micro USD"
        rows = []
        costs = {}
        condition_requests = []
        condition_ops = []
        for entry in condition["passes"]:
            repeat = entry["repeat"]
            requests = [r for r in plan["requests"] if (r["config_id"], r["prompt_id"], r["repeat"]) == (cid, pid, repeat)]
            ops = [_derived_telemetry(o, config) for r in requests for o in operation_map[r["request_id"]]]
            condition_requests.extend(requests)
            condition_ops.extend(ops)
            charges = [o["observed_cost_micro_usd"] for o in ops if o.get("observed_cost_micro_usd") is not None]
            costs[repeat] = sum(charges) if charges else None
            metadata = {key: next((o.get(key) for o in ops if o.get(key) is not None), None)
                        for key in ("provider", "model", "route", "effort")}
            metadata["model"] = _display_metadata(_first_metadata(metadata["model"], config["model"]))
            for key in ("provider", "route", "effort"):
                fallback = (_native_provider(settings) if key == "provider" else
                            _native_requested_route(config) if key == "route" else
                            settings.get("reasoning"))
                metadata[key] = _display_metadata(_first_metadata(metadata[key], settings.get(key), fallback))
            values = {"task": task["name"], "model": metadata["model"], "provider": metadata["provider"],
                      "effort": metadata["effort"], "prompt": pid, "repeat": str(repeat), "route": metadata["route"]}
            values["run-id"] = analysis_runs[(cid, pid, repeat)]["run_id"]
            attributes = " ".join(f"data-{key}='{_h(value)}'"
                                  for key, value in values.items())
            field_rows = []
            for field in task["fields"]:
                name = field["name"]
                stats = entry["fields"][name]
                known_denominator = entry["denominator"] if complete_references else stats["reference_denominator"]
                if stats["confusion"] is None:
                    diagonal, support, confusion, unscored = None, "unavailable", "unavailable", "unavailable"
                else:
                    diagonal = sum(stats["confusion"][label][label] for label in field["labels"])
                    support = ", ".join(f"{label}: {stats['labels'][label]['support']}" for label in field["labels"])
                    errors = [(actual, predicted, count) for actual in field["labels"]
                              for predicted in field["labels"] if actual != predicted
                              for count in [stats["confusion"][actual][predicted]] if count]
                    confusion = ", ".join(f"{a} → {b}: {n}" for a, b, n in errors) or "none"
                    unscored = json.dumps(stats["unscored_by_true_label"], ensure_ascii=False)
                field_row = (name, _rate(diagonal, known_denominator), support, confusion, unscored)
                if not complete_references:
                    field_row += (f"{known_denominator}/{entry['denominator']} known references",)
                field_rows.append(field_row)
            case_rows = []
            pass_outcomes = Counter()
            for record_id in all_ids:
                key = (cid, pid, repeat, record_id)
                status = outcomes[key]
                pass_outcomes[status] += 1
                prediction = supplied.get(key) if key not in invalid else None
                reference = references.get(record_id, {})
                full_reference = len(reference) == len(task["fields"])
                agreement = ("unavailable (partial reference)" if reference and not full_reference else
                             "unavailable (no reference)" if not reference else
                             "unscored" if prediction is None else
                             "agree" if prediction == reference else "disagree")
                case_rows.append((record_id, status, agreement,
                                  json.dumps(reference, ensure_ascii=False) if reference else "unavailable",
                                  json.dumps(supplied[key], ensure_ascii=False) if key in supplied else "unavailable",
                                  json.dumps(items[record_id], ensure_ascii=False)))
            outcome_rows = [(status, count, entry["denominator"]) for status, count in sorted(pass_outcomes.items())]
            paired = []
            if pid != baseline:
                before = score_by_pass[(cid, baseline, repeat)]
                after = entry["all_field_exact"]
                if complete_references:
                    paired.append(f"Paired prompt effect against {_h(baseline)}: {after - before:+d} exact matches "
                                  f"({before}/{entry['denominator']} → {after}/{entry['denominator']}).")
                else:
                    subset = entry["scored_subset"]
                    baseline_subset = subset_by_pass[(cid, baseline, repeat)]
                    before, after = baseline_subset["all_field_exact"], subset["all_field_exact"]
                    paired.append(f"Full-denominator paired reference effect against {_h(baseline)}: unavailable.")
                    if before is not None and after is not None:
                        paired.append(f"Scored subset paired prompt effect against {_h(baseline)}: {after - before:+d} exact matches "
                                      f"({before}/{subset['denominator']} → {after}/{subset['denominator']}); only cases with complete references.")
            subset_note = ""
            if not complete_references:
                subset = entry["scored_subset"]
                subset_note = (f"<p>Scored subset exact agreement: {_rate(subset['all_field_exact'], subset['denominator'])}; "
                               f"{subset['denominator']}/{entry['denominator']} cases have complete references. "
                               "Unknown references are excluded from this score. Missing and invalid predictions on referenced cases receive no credit.</p>")
            field_headers = ("Field", "Agreement", "Reference class support", "Valid disagreements", "Unscored by reference class")
            if not complete_references:
                field_headers = ("Field", "Known-reference agreement", "Known reference class support", "Valid disagreements", "Unscored by reference class", "Reference coverage")
            pass_anchor = f"{condition_anchor}-pass-{repeat}"
            contents.append(f"<li class='contents-pass'><a href='#{pass_anchor}'>{_h(cid)} · {_h(pid)} · pass {repeat}</a></li>")
            rows.append(f"<section class='pass' id='{pass_anchor}' {attributes}><h3>{_h(cid)} · {_h(pid)} · pass {repeat}</h3>"
                        f"<p>Requested model: {_h(metadata['model'])}; requested provider: {_h(metadata['provider'] or 'unavailable')}; "
                        f"route: {_h(metadata['route'] or 'unavailable')}; effort: {_h(metadata['effort'] or 'unavailable')}.</p>"
                        "<p>Requested routing is not proof of the serving provider. See observed identity evidence for each request below.</p>"
                        f"<p>Exact agreement: {_rate(entry['all_field_exact'], entry['denominator'])}; "
                        f"no selected prediction: {entry['missing']}; invalid selected projection: {entry['invalid']}. "
                        "Every planned position remains in the denominator. These projection counts are distinct from observed runner outcomes.</p>"
                        + subset_note
                        + "".join(f"<p>{line}</p>" for line in paired)
                        + "<h4>Observed position outcomes</h4>"
                        + _table(("Outcome", "Positions", "Planned denominator"), outcome_rows,
                                 caption=f"Observed position outcomes for {cid}, {pid}, pass {repeat}", class_name="outcome-table")
                        + "<h4>Field agreement and class errors</h4>"
                        + _table(field_headers, field_rows,
                                 caption=f"Field agreement for {cid}, {pid}, pass {repeat}", row_header=True, numeric_columns=(1,))
                        + render_field_metrics(metric_runs[(cid, pid, repeat)], id_prefix=pass_anchor + "-metrics")
                        + "<h4>Request evidence</h4>" + _operation_summary(ops, len(requests), currency)
                        + "<details><summary>Supporting cases (private input text and references)</summary>"
                        + _table(("Case", "Output", "Agreement", "Reference", "Prediction", "Input"), case_rows,
                                 caption=f"Supporting cases for {cid}, {pid}, pass {repeat}", row_header=True)
                        + "</details></section>")
        comparisons = []
        for comparison in condition["repeat_comparisons"]:
            comparisons.append((f"{comparison['repeat_a']} vs {comparison['repeat_b']}",
                                _rate(comparison["flips"], comparison["comparable"]),
                                str(comparison["excluded"]), ", ".join(comparison["changed_ids"]) or "none"))
        score_range = condition["pass_score_range"]
        range_text = f"{score_range[0]:.1%} to {score_range[1]:.1%}" if score_range is not None else "unavailable"
        exact = sum(entry["all_field_exact"] for entry in condition["passes"]) if complete_references else None
        denominator = sum(entry["denominator"] for entry in condition["passes"])
        invalid_count = sum(entry["invalid"] for entry in condition["passes"])
        missing_count = sum(entry["missing"] for entry in condition["passes"])
        duration_values = [op["duration_seconds"] for op in condition_ops if op.get("duration_seconds") is not None]
        duration = (f"{_number(sum(duration_values) / len(duration_values), ' s')} mean "
                    f"({len(duration_values)}/{len(condition_requests)} requests measured)"
                    if duration_values else f"unavailable (0/{len(condition_requests)} requests measured)")
        synthetic_timing = (settings.get("adapter") == "synthetic" or
                            any(str(op.get("route", "")).startswith("synthetic:")
                                or op.get("cost_currency") == "SYN" for op in condition_ops))
        model_type = config.get("model_type", "unspecified")
        charge_groups = defaultdict(list)
        for op in condition_ops:
            charge = op.get("observed_cost_micro_usd")
            if charge is not None:
                charge_groups[_cost_currency(op, currency)].append(charge)
        observed = "; ".join(f"{_number(sum(values))} {unit} ({len(values)}/{len(condition_requests)} requests recorded"
                             + (", partial recorded total" if len(values) < len(condition_requests) else "") + ")"
                             for unit, values in sorted(charge_groups.items()))
        observed = observed or "unavailable"
        coverage = (f"{sum(map(len, charge_groups.values()))}/{len(condition_requests)} planned requests"
                    if condition_requests else "0/0 planned requests")
        comparison_rows.append({
            "config": cid, "prompt": pid, "model": config["model"],
            "run_ids": [run["run_id"] for run in analysis["runs"]
                        if run["config_id"] == cid and run["prompt_id"] == pid],
            "anchor": condition_anchor, "category": _adapter_category(settings),
            "model_type": model_type, "model_type_label": _MODEL_TYPE_LABELS[model_type],
            "plot_state": "reference_unavailable" if not complete_references else "synthetic" if synthetic_timing else "measured" if duration_values else "unavailable",
            "duration_mean": sum(duration_values) / len(duration_values) if duration_values else None,
            "duration_measured": len(duration_values), "duration_planned": len(condition_requests),
            "exact_numerator": exact, "exact_denominator": denominator,
            "exact_fraction": exact / denominator if exact is not None and denominator else None,
            "route": _display_metadata(_first_metadata(
                settings.get("route"), _native_requested_route(config),
                ", ".join(sorted({_display_metadata(op["route"]) for op in condition_ops
                                  if _first_metadata(op.get("route")) is not None})))),
            "provider": _display_metadata(_first_metadata(
                settings.get("provider"), _native_provider(settings),
                ", ".join(sorted({_display_metadata(op["provider"]) for op in condition_ops
                                  if _first_metadata(op.get("provider")) is not None}))),
                "provider unavailable"),
            "status": (f"{invalid_count + missing_count} selected prediction gap(s)"
                       if invalid_count + missing_count else "Selected predictions complete")
                       + ("; full reference agreement unavailable" if not complete_references else ""),
            "has_gaps": invalid_count + missing_count > 0,
            "display": (cid, pid, _rate(exact, denominator), range_text,
                        invalid_count, missing_count, duration, observed, coverage),
            "sort": {"model": config["model"], "prompt": pid,
                     "exact": exact / denominator if exact is not None and denominator else "",
                     "range": score_range[0] if score_range is not None else "", "invalid": invalid_count, "missing": missing_count,
                     "duration": sum(duration_values) / len(duration_values) if duration_values else "",
                     "cost": observed, "coverage": sum(map(len, charge_groups.values())) / len(condition_requests)
                     if condition_requests else ""},
        })
        chart_id = f"chart-{len(pages)}"
        baseline_scores = {p["repeat"]: score_by_pass[(cid, baseline, p["repeat"])]
                           for p in condition["passes"]}
        visuals = _score_visual(condition, chart_id + "-score")
        if pid != baseline and complete_references:
            visuals += _delta_visual(condition, baseline_scores, baseline, chart_id + "-delta")
        if len(charge_groups) <= 1:
            chart_currency = next(iter(charge_groups), currency)
            visuals += _cost_visual(condition, costs, chart_id + "-cost", chart_currency)
        else:
            visuals += "<p>Observed costs use more than one currency; see the separate per-currency totals above and in each pass.</p>"
        pages.append(f"<article class='condition' id='{condition_anchor}'><h2>{_h(cid)} · {_h(pid)}</h2>"
                     f"<p>Prompt: {_h(prompt['text'])}</p>"
                     f"<p>Exact agreement across passes: {range_text}. "
                     "Each pass uses the same input cases; passes are separate dispatches. "
                     "For synthetic outputs, repeated passes show pipeline behavior, not model variability.</p>"
                     "<p>Condition overview below covers all passes, even when a pass filter is selected.</p>"
                     + visuals
                     + ("<h3>Repeat changes</h3>" + _table(("Passes", "Changed valid cases", "Excluded cases", "Changed case IDs"), comparisons,
                                                            caption=f"Repeat changes for {cid} and {pid}", row_header=True, numeric_columns=(1, 2))
                        if comparisons else "<p>No repeat comparison is available.</p>")
                     + "".join(rows) + "</article>")

    filters = []
    for key, label in (("task", "Task"), ("model", "Requested model"), ("provider", "Requested provider"),
                       ("effort", "Requested effort"), ("prompt", "Prompt"), ("repeat", "Pass"), ("route", "Requested API route")):
        if key == "task":
            values = [task["name"]]
        else:
            values = sorted({str(value) for value in _filter_values(key, plan, operations)})
        options = "<option value=''>All</option>" + "".join(f"<option value='{_h(v)}'>{_h(v)}</option>" for v in values)
        canonical_key = "api_route" if key == "route" else key
        mirror = f" data-report-filter='{canonical_key}'" if key != "task" else ""
        filters.append(f"<label>{label} <select data-filter='{key}'{mirror}>{options}</select></label>")
    source_rows = [(name, digest if digest is not None else "unavailable (not supplied)")
                   for name, digest in result["source_hashes"].items()]
    if operations:
        source_rows.append(("supplied operations", _digest(operations)))
    categories = Counter(row["category"] for row in comparison_rows)
    model_types = Counter(row["model_type"] for row in comparison_rows)
    model_type_buttons = ("<button type='button' data-model-type-choice='' aria-pressed='true'>"
                          "All model types <span>" + str(len(comparison_rows)) + "</span></button>")
    model_type_buttons += "".join(
        f"<button type='button' data-model-type-choice='{key}' aria-pressed='false'>"
        f"{_h(label)} <span>{model_types[key]}</span></button>"
        for key, label in _MODEL_TYPE_LABELS.items())
    category_buttons = "<button type='button' data-category-choice='' aria-pressed='true'>All conditions <span>" + str(len(comparison_rows)) + "</span></button>"
    category_buttons += "".join(
        f"<button type='button' data-category-choice='{_h(category)}' aria-pressed='false'>"
        f"{_h(category)} <span>{count}</span></button>"
        for category, count in sorted(categories.items()))
    comparison_filters = []
    for key, label in (("model", "Model"), ("provider", "Provider"),
                       ("route", "API route"), ("prompt", "Prompt condition")):
        values = sorted({str(row[key]) for row in comparison_rows})
        options = "<option value=''>All</option>" + "".join(
            f"<option value='{_h(value)}'>{_h(value)}</option>" for value in values)
        comparison_filters.append(
            f"<label>{label}<select data-comparison-filter='{key}' data-report-filter='{"api_route" if key == "route" else key}'>{options}</select></label>")
    script = """window.reportFilters.refreshAliases();
    const passes = [...document.querySelectorAll('.pass')];
    let filterSnapshot = window.reportFilters.getState();
    function applyFilters() {
      const eligible = new Set(filterSnapshot.eligibleRunIds);
      passes.forEach(section => { section.hidden = !eligible.has(section.dataset.runId); });
      document.querySelectorAll('article.condition').forEach(article => {
        article.hidden = !article.querySelector('.pass:not([hidden])');
      });
      const visible = passes.filter(section => !section.hidden).length;
      document.getElementById('filter-status').textContent = `Showing ${visible} of ${passes.length} pass sections. Shared report filters select whole runs; condition summaries retain all planned repeats.`;
      document.getElementById('filter-empty').hidden = visible !== 0;
    }
    document.getElementById('reset-filters').addEventListener('click', () => window.reportFilters.reset());
    document.querySelectorAll("[data-contents] a[href^='#'], .row-actions a[href^='#'], .duration-point[href^='#'], .plot-key-row a[href^='#']").forEach(link => link.addEventListener('click', () => {
      const target = document.getElementById(link.getAttribute('href').slice(1));
      if (target && (target.hidden || target.closest('article[hidden]'))) window.reportFilters.reset();
    }));
    const comparisonBody = document.querySelector('.comparison-table tbody');
    const comparisonRows = [...comparisonBody.rows];
    const referenceScoringUnavailable = comparisonRows.some(row => row.dataset.plotState === 'reference_unavailable');
    const comparisonSearch = document.getElementById('comparison-search');
    const comparisonFilters = [...document.querySelectorAll('[data-comparison-filter]')];
    const categoryButtons = [...document.querySelectorAll('[data-category-choice]')];
    const modelTypeButtons = [...document.querySelectorAll('[data-model-type-choice]')];
    const plotPoints = [...document.querySelectorAll('.duration-point')];
    const plotById = new Map(plotPoints.map(point => [point.dataset.plotId, point]));
    const plotLabels = new Map([...document.querySelectorAll('.plot-key-row')].map(item => [item.dataset.plotId, item]));
    function applyComparisonSearch() {
      const query = comparisonSearch.value.trim().toLocaleLowerCase();
      let visible = 0;
      comparisonRows.forEach(row => {
        const runIds = JSON.parse(row.dataset.runIds);
        const eligible = new Set(filterSnapshot.eligibleRunIds);
        const matching = runIds.filter(id => eligible.has(id)).length;
        row.hidden = (Boolean(query) && !row.textContent.toLocaleLowerCase().includes(query)) || matching === 0;
        let scope = row.querySelector('.condition-filter-scope');
        if (!scope) { scope = document.createElement('span'); scope.className = 'condition-filter-scope model-meta'; row.cells[0].append(scope); }
        scope.textContent = `${matching}/${runIds.length} runs match shared filters. Metrics cover all ${runIds.length} planned runs.`;
        if (!row.hidden) visible += 1;
      });
      let plotted = 0;
      let unavailable = 0;
      let synthetic = 0;
      let referenceUnavailable = 0;
      comparisonRows.forEach(row => {
        const point = plotById.get(row.dataset.plotId);
        const label = plotLabels.get(row.dataset.plotId);
        if (point) {
          if (row.hidden) point.setAttribute('hidden', '');
          else point.removeAttribute('hidden');
        }
        if (label) label.hidden = row.hidden;
        if (row.hidden) return;
        if (row.dataset.plotState === 'measured') plotted += 1;
        else if (row.dataset.plotState === 'synthetic') synthetic += 1;
        else if (row.dataset.plotState === 'reference_unavailable') referenceUnavailable += 1;
        else unavailable += 1;
      });
      const chart = document.getElementById('agreement-duration-chart');
      if (chart) {
        if (plotted === 0) chart.setAttribute('hidden', '');
        else chart.removeAttribute('hidden');
      }
      document.getElementById('plot-empty').hidden = plotted !== 0;
      document.getElementById('plot-status').textContent = referenceScoringUnavailable
        ? `${plotted} plotted of ${visible} visible conditions; ${referenceUnavailable} lack complete reference coverage. Full-denominator agreement is unavailable.`
        : `${plotted} plotted of ${visible} visible conditions; ${unavailable} lack measured duration; ${synthetic} synthetic conditions excluded. Axes use all measured nonsynthetic conditions.`;
      document.getElementById('comparison-status').textContent =
        `Showing ${visible} of ${comparisonRows.length} configurations and prompts in this comparison view. Whole-experiment totals remain unfiltered.`;
      document.getElementById('comparison-empty').hidden = visible !== 0;
      renderSelection();
    }
    comparisonSearch.addEventListener('input', applyComparisonSearch);
    categoryButtons.forEach(button => button.addEventListener('click', () => {
      window.reportFilters.setValue('adapter_category', button.dataset.categoryChoice || undefined);
    }));
    modelTypeButtons.forEach(button => button.addEventListener('click', () => {
      const value = button.dataset.modelTypeChoice;
      window.reportFilters.setValue('model_group', value === 'unspecified' ? null : value || undefined);
    }));
    document.getElementById('reset-comparison').addEventListener('click', () => {
      comparisonSearch.value = '';
      window.reportFilters.reset();
    });
    const selection = [];
    const selectionStatus = document.getElementById('selection-status');
    const selectionCards = document.getElementById('selection-cards');
    const clearSelection = document.getElementById('clear-selection');
    function renderSelection() {
      selectionCards.replaceChildren();
      const columns = ['Exact agreement', 'Repeat range', 'Invalid selected projections',
        'No selected prediction', 'Mean client request duration', 'Observed cost', 'Cost coverage'];
      selection.forEach(row => {
        const card = document.createElement('section');
        card.className = 'selection-card';
        const title = document.createElement('h3');
        title.textContent = `${row.dataset.model} · ${row.dataset.promptId}`;
        card.appendChild(title);
        const meta = document.createElement('p');
        meta.textContent = `${row.dataset.configId} · declared group: ${row.dataset.modelTypeLabel} · ${row.dataset.category} · requested provider: ${row.dataset.provider} · route: ${row.dataset.route}`;
        card.appendChild(meta);
        if (row.hidden) {
          const outside = document.createElement('p');
          outside.className = 'selection-outside';
          outside.textContent = 'Outside the current comparison filters';
          card.appendChild(outside);
        }
        const list = document.createElement('dl');
        columns.forEach((label, index) => {
          const term = document.createElement('dt');
          term.textContent = label;
          const value = document.createElement('dd');
          value.textContent = row.cells[index + 2].textContent.trim();
          list.append(term, value);
        });
        card.appendChild(list);
        selectionCards.appendChild(card);
      });
      selectionStatus.textContent = selection.length ?
        `${selection.length} of 2 conditions selected. Each value covers all planned passes for that condition; currencies and routes may differ.` :
        'Select up to two conditions from the table to compare their recorded values.';
      clearSelection.disabled = selection.length === 0;
      comparisonRows.forEach(row => {
        const checkbox = row.querySelector('.compare-select');
        checkbox.disabled = selection.length === 2 && !checkbox.checked;
      });
    }
    comparisonRows.forEach(row => row.querySelector('.compare-select').addEventListener('change', event => {
      if (event.target.checked) selection.push(row);
      else selection.splice(selection.indexOf(row), 1);
      renderSelection();
    }));
    clearSelection.addEventListener('click', () => {
      selection.length = 0;
      comparisonRows.forEach(row => { row.querySelector('.compare-select').checked = false; });
      renderSelection();
    });
    document.querySelectorAll('[data-sort]').forEach(button => button.addEventListener('click', () => {
      const index = button.closest('th').cellIndex;
      const heading = button.closest('th');
      const descending = heading.getAttribute('aria-sort') !== 'descending';
      document.querySelectorAll('.comparison-table thead th').forEach(th => th.setAttribute('aria-sort', 'none'));
      heading.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
      const numeric = button.dataset.sortType === 'number';
      const ordered = comparisonRows.map((row, originalIndex) => ({row, originalIndex}));
      ordered.sort((a, b) => {
        const left = a.row.cells[index].dataset.sortValue;
        const right = b.row.cells[index].dataset.sortValue;
        if (left === '' || right === '') return left === right ? a.originalIndex - b.originalIndex : left === '' ? 1 : -1;
        const result = numeric ? Number(left) - Number(right) : left.localeCompare(right, undefined, {sensitivity: 'base'});
        return (descending ? -result : result) || a.originalIndex - b.originalIndex;
      });
      ordered.forEach(item => comparisonBody.appendChild(item.row));
    }));
    const sectionLinks = [...document.querySelectorAll('.jump-nav a')];
    function setActiveSection(id) {
      if (!sectionLinks.some(link => link.hash.slice(1) === id)) return;
      sectionLinks.forEach(link => {
        if (link.hash.slice(1) === id) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      });
    }
    sectionLinks.forEach(link => link.addEventListener('click', () => setActiveSection(link.hash.slice(1))));
    function setActiveFromHash() { setActiveSection(window.location.hash.split('?')[0].slice(1)); }
    window.addEventListener('hashchange', setActiveFromHash);
    setActiveSection('comparison-heading');
    setActiveFromHash();
    if ('IntersectionObserver' in window) {
      const observed = sectionLinks.map(link => ({
        id: link.hash.slice(1),
        node: document.getElementById(link.hash.slice(1)).closest('section, footer')
      }));
      const ids = new Map(observed.map(item => [item.node, item.id]));
      const observer = new IntersectionObserver(entries => {
        const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (!visible.length) return;
        setActiveSection(ids.get(visible[0].target));
      }, {rootMargin: '-10% 0px -65% 0px'});
      observed.forEach(item => observer.observe(item.node));
    }
    function applySharedFilters(snapshot) {
      filterSnapshot = snapshot;
      categoryButtons.forEach(button => button.setAttribute('aria-pressed', String(window.reportFilters.matchesValue('adapter_category', button.dataset.categoryChoice || undefined))));
      modelTypeButtons.forEach(button => { const value = button.dataset.modelTypeChoice;
        button.setAttribute('aria-pressed', String(window.reportFilters.matchesValue('model_group', value === 'unspecified' ? null : value || undefined))); });
      const eligible = new Set(snapshot.eligibleRunIds);
      document.querySelectorAll('[data-finding-runs]').forEach(article => {
        const ids = JSON.parse(article.dataset.findingRuns);
        const matching = ids.filter(id => eligible.has(id)).length;
        article.hidden = ids.length > 0 && matching === 0;
        let note = article.querySelector('.finding-filter-scope');
        if (!note) { note = document.createElement('p'); note.className = 'finding-filter-scope finding-scope'; article.append(note); }
        note.textContent = `${matching}/${ids.length} supporting runs match shared filters. This finding retains its stated full scope and denominator; filters do not rescore it.`;
      });
      applyFilters(); applyComparisonSearch();
    }
    // Heading and evidence links change their authored selection, preserving the
    // rest of the local report state across native fragment navigation.
    document.addEventListener('click', event => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = event.target.closest('a[href]');
      if (!anchor || anchor.hasAttribute('download') || anchor.target && anchor.target !== '_self') return;
      const raw = anchor.getAttribute('href');
      if (!raw.startsWith('#')) return;
      const split = value => { const index = value.indexOf('?'); return {heading: index < 0 ? value : value.slice(0,index), params: new URLSearchParams(index < 0 ? '' : value.slice(index+1))}; };
      const current = split(window.location.hash.slice(1)), target = split(raw.slice(1));
      const selectionKeys = ['run','compareRun','case'];
      if (selectionKeys.some(key => target.params.has(key))) selectionKeys.forEach(key => current.params.set(key,''));
      target.params.forEach((value,key) => current.params.set(key,value));
      const query = current.params.toString();
      const destination = '#' + target.heading + (query ? '?' + query : '');
      event.preventDefault();
      window.location.hash = destination;
      const section = document.getElementById(target.heading);
      if (section) { if (!section.hasAttribute('tabindex')) section.setAttribute('tabindex','-1'); section.focus({preventScroll:true}); }
      if (section && typeof section.scrollIntoView === 'function') section.scrollIntoView({block:'start'});
    });
    window.addEventListener('report-filter-change', event => applySharedFilters(event.detail));
    applySharedFilters(window.reportFilters.getState());"""
    comparison = _comparison_table(comparison_rows)
    overview_plot = (agreement_duration_plot(comparison_rows) if complete_references else
                     "<section class='duration-overview' aria-labelledby='duration-overview-heading'>"
                     "<h3 id='duration-overview-heading'>Agreement and client request duration</h3>"
                     "<p id='plot-empty'>Full-denominator agreement plot unavailable: complete reference coverage is required. "
                     "Recorded duration and cost remain available in the comparison table.</p>"
                     "<p id='plot-status' class='status-line' role='status' aria-live='polite'></p></section>")
    explorer = render_report_explorer(analysis)
    comparative_data = build_comparative_findings(analysis)
    comparative_panel = render_comparative_findings(comparative_data)
    finding_data = build_findings(analysis, comparative=comparative_data)
    deep_findings = render_findings(finding_data)
    sensitivity_data = build_sensitivity(task, plan, predictions, labels, scenarios)
    sensitivity = render_sensitivity(sensitivity_data)
    downloads = render_downloads(build_report_exports(analysis, findings=finding_data,
                                 field_metrics=field_metrics, sensitivity=sensitivity_data))
    shared_filters = render_report_filters(analysis)
    presentation = render_presentation(analysis, finding_data, sensitivity=sensitivity_data,
                                      field_metrics=field_metrics)
    if complete_references:
        reference_notice = ""
        comparison_scope = "Exact agreement uses every planned position. Missing and invalid predictions earn no credit."
        score_scope = "Scores use all planned positions. Positions without valid selected predictions receive no agreement credit. "
    else:
        coverage = result["reference_coverage"]
        reference_notice = (f"<p class='notice'>Reference coverage: {_h(coverage['status'])}; "
                            f"{len(coverage['fully_labeled_ids'])}/{len(all_ids)} cases fully referenced, "
                            f"{len(coverage['partially_labeled_ids'])} partially referenced, "
                            f"{len(coverage['unlabeled_ids'])} without known references. "
                            "Full-denominator exact agreement is unavailable.</p>")
        comparison_scope = "Exact agreement and repeat score ranges are unavailable without complete reference coverage. Known-reference scores appear separately in pass evidence."
        score_scope = "All planned positions remain in the outcome counts. Reference scores include only explicitly known references; unknown references receive no correctness judgment. "
    synthetic_notice = ("<p class='notice'>Contains synthetic results: SYN units are local accounting, not provider charges.</p>"
                        if any(config.get("settings", {}).get("adapter") == "synthetic" for config in configs.values())
                        or any(str(op.get("route", "")).startswith("synthetic:") for op in operations) else "")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{_h(task['name'])} · local classification report</title>"
            "<meta name='description' content='Local classification benchmark comparison and evidence.'>"
            f"<style>{_REPORT_CSS}</style></head><body>"
            "<a class='skip-link' href='#main-content'>Skip to main content</a>"
            f"<header class='masthead'><div class='shell'><span class='eyebrow'>Private local classification report</span>"
            f"<h1>{_h(task['name'])}</h1><p class='lead'>Compare recorded classifications across models, prompts and passes.</p>"
            + synthetic_notice + reference_notice +
            f"<div class='overview-meta'><div><span class='meta-label'>Planned positions</span><span class='meta-value'>{total}</span></div>"
            f"<div><span class='meta-label'>Configurations</span><span class='meta-value'>{len(configs)}</span></div>"
            f"<div><span class='meta-label'>Prompts</span><span class='meta-value'>{len(prompts)}</span></div>"
            f"<div><span class='meta-label'>Passes per condition</span><span class='meta-value'>{plan['experiment']['repeats']}</span></div>"
            "<div><span class='meta-label'>Evidence</span><span class='meta-value'>Local source digests</span></div></div></div></header>"
            "<nav class='jump-nav' aria-label='Report sections'><div class='shell'><a href='#comparison-heading'>Comparison</a>"
            "<a href='#summary-heading'>Whole experiment</a><a href='#detail-heading'>Pass evidence</a>"
            "<a href='#case-explorer-heading'>Case explorer</a><a href='#deep-findings'>Findings and follow-up</a>"
            "<a href='#reference-sensitivity-heading'>Sensitivity</a><a href='#downloads-heading'>Downloads</a>"
            "<a href='#presentation-heading'>Presentation</a>"
            "<a href='#provenance-heading'>Provenance</a></div></nav>"
            "<main id='main-content' class='shell'>"
            "<section class='comparison-section' aria-labelledby='comparison-heading'><div class='section-intro'>"
            "<div><span class='eyebrow'>01 / Compare</span><h2 id='comparison-heading'>Compare configurations and prompts</h2>"
            f"<p>{comparison_scope}</p></div></div>"
            + shared_filters +
            "<p class='rail-label'>Operator-declared model group</p>"
            "<nav class='category-rail' aria-label='Operator-declared model groups'>" + model_type_buttons + "</nav>"
            "<p class='rail-label'>Adapter category</p>"
            "<nav class='category-rail' aria-label='Declared adapter categories'>" + category_buttons + "</nav>"
            "<div class='comparison-tools'><label for='comparison-search'>Search model, configuration or prompt"
            "<input id='comparison-search' type='search' autocomplete='off'></label>"
            + " ".join(comparison_filters) +
            "<button type='button' id='reset-comparison'>Reset comparison view</button></div>"
            "<p class='status-line'>Model groups are declared in the configuration. A decision group describes the benchmark purpose; it does not verify model architecture or training history. Adapter categories describe requested execution. Use column headings to sort; unavailable measurements sort last.</p>"
            + comparison +
            f"<p class='status-line' id='comparison-status' role='status' aria-live='polite'>Showing {len(comparison_rows)} of {len(comparison_rows)} configurations and prompts in this comparison view. Whole-experiment totals remain unfiltered.</p>"
            "<p id='comparison-empty' hidden>No conditions match these comparison filters. Reset the comparison view to show all conditions.</p>"
            + overview_plot +
            "<section class='selection-section' aria-labelledby='selection-heading'><div class='section-intro'>"
            "<div><span class='eyebrow'>Selected conditions</span><h3 id='selection-heading'>Compare two conditions</h3></div>"
            "<p>Values cover all planned passes for each selected condition. Compare costs only within the same currency and route context.</p></div>"
            "<p id='selection-status' role='status' aria-live='polite'>Select up to two conditions from the table to compare their recorded values.</p>"
            "<button type='button' id='clear-selection' disabled>Clear selections</button>"
            "<div id='selection-cards' class='selection-cards'></div></section>"
            "<p class='status-line'>Observed cost totals include recorded charges only; coverage is shown against planned requests. Estimates remain in request details.</p></section>"
            "<section class='summary-section' aria-labelledby='summary-heading'><div>"
            "<span class='eyebrow'>02 / Scope</span><h2 id='summary-heading'>Whole experiment summary (unfiltered)</h2>"
            "<p>These counts and findings cover the complete experiment. Shared filters select runs across comparison and evidence views; these whole-experiment totals remain fixed.</p>"
            f"<p>Planned positions: {total}; valid selected predictions: {valid_count}; no selected prediction: {result['missing']}; invalid selected projection: {len(result['invalid'])}.</p>"
            "</div><div class='summary-data'><h3>Observed position outcomes</h3>"
            + _table(("Outcome", "Positions", "Planned denominator"),
                     [(status, count, total) for status, count in sorted(outcome_counts.items())],
                     caption="Observed outcomes across the whole experiment", class_name="outcome-table")
            + "<p>Each planned position appears once in this table. A missing selected prediction can correspond to a refusal, failure, unknown dispatch, or a request without observed evidence.</p>"
            f"<p>{score_scope}Request timing is measured per request, which may contain a batch; it is not per-case inference latency.</p>"
            "<h3>Findings</h3>" + "".join(f"<p>{x}</p>" for x in findings)
            + "</div></section><section class='filters' aria-label='Pass filters'><span class='eyebrow'>03 / Inspect</span>"
            "<h2 id='detail-heading'>Pass evidence</h2><p>Filter the pass details without changing the comparison or experiment totals.</p>"
            + "<nav class='filter-grid' aria-label='Report filters'>" + " ".join(filters) +
            " <button type='button' id='reset-filters'>Reset filters</button></nav>"
            f"<p id='filter-status' role='status' aria-live='polite'>Showing {sum(len(c['passes']) for c in result['conditions'])} of {sum(len(c['passes']) for c in result['conditions'])} pass sections.</p>"
            "<p id='filter-empty' hidden>No pass sections match these filters. Reset filters to show all passes.</p></section>"
            + "<nav class='detail-index' data-contents aria-label='Report contents'><h2>Contents</h2><ul>" + "".join(contents) + "</ul></nav>"
            + "".join(pages) + explorer + deep_findings + comparative_panel + sensitivity + downloads + presentation + "</main>"
            + "<footer class='provenance'><div class='shell'><h2 id='provenance-heading'>Provenance</h2><p>Canonical JSON SHA-256 digests bind the task, plan, references, selected prediction set and any supplied operation records. "
            "The evaluator validates planned positions and predictions; the caller is responsible for verifying operation records. "
            "This file includes private inputs and reference labels. Keep it local.</p>"
            "<p>Usage fields retain provider-specific evidence, available in each request's raw usage disclosure. "
            "OpenRouter routes use <a href='https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion'>OpenRouter's chat response schema</a> "
            "and <a href='https://openrouter.ai/docs/guides/best-practices/prompt-caching'>caching documentation</a>; native decision routes use their own provider schemas.</p>"
            + _table(("Source", "SHA-256"), source_rows, caption="Source digests", row_header=True)
            + "</div></footer><script>" + script + "</script></body></html>")


def _filter_values(key, plan, operations):
    values = set()
    if key == "prompt":
        return {x["id"] for x in plan["experiment"]["prompts"]}
    if key == "repeat":
        return {str(x) for x in range(1, plan["experiment"]["repeats"] + 1)}
    for config in plan["experiment"]["configs"]:
        settings = config.get("settings", {})
        value = config["model"] if key == "model" else settings.get(key)
        if key == "provider" and value is None:
            value = _native_provider(settings)
        if key == "route" and value is None:
            value = _native_requested_route(config)
        if key == "effort" and value is None:
            value = settings.get("reasoning")
        values.add(_display_metadata(value))
    for op in operations:
        if key in op and op[key] is not None:
            values.add(_display_metadata(op[key]))
    return values
