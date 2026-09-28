"""Private, self-contained HTML report from validated offline evidence."""

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from html import escape
import json
import math

from .core import ValidationError, _digest, evaluate


def _h(value):
    return escape(str(value), quote=True)


def _rate(numerator, denominator):
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
    body = ""
    for index, entry in enumerate(passes):
        y = 38 + index * 42
        width = round(300 * entry["all_field_exact_rate"], 2)
        body += (f"<text x='5' y='{y + 15}'>Pass {entry['repeat']}</text>"
                 f"<rect class='score' x='140' y='{y}' width='{width}' height='20'/>"
                 f"<text x='450' y='{y + 15}'>{entry['all_field_exact']}/{entry['denominator']} "
                 f"({entry['all_field_exact_rate']:.1%})</text>")
    low, high = condition["pass_score_range"]
    y = 46 + len(passes) * 42
    x1, x2 = 140 + 300 * low, 140 + 300 * high
    body += (f"<text x='5' y='{y}'>Pass range</text>"
             f"<line class='range' x1='{x1:.2f}' x2='{x2:.2f}' y1='{y - 5}' y2='{y - 5}'/>"
             f"<text x='450' y='{y}'>{low:.1%} to {high:.1%}</text>")
    return _svg("Exact agreement by pass", "Bars show all-field exact agreement divided by every planned case in each pass. The line shows the range across passes.",
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
    if not known:
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
         "Provider identity evidence", "Verified receipt SHA-256"), identity_rows,
        caption="Request model and provider identity") + (
        "<p>Token detail comes from saved usage. Token-price estimates use the frozen endpoint snapshot at the standard input rate, exclude cache savings, and are separate from observed charges. "
        "Unavailable values are omitted from totals.</p>" + _table(
            ("Request ID", "Input tokens", "Output tokens", "Reasoning tokens", "Cached tokens",
             f"Observed charge ({'per request currency' if mixed_charges else charge_currency})",
             f"Price estimate ({'micro USD' if any(r.get('estimated_cost_micro_usd') is not None for r in records) else currency})", "Estimate basis or limit",
             "Endpoint snapshot SHA-256", "Telemetry note"), telemetry_rows,
            caption="Request token and cost telemetry", numeric_columns=(1, 2, 3, 4, 5, 6)) + "</details>")


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


def generate_report(task, plan, labels, predictions, operations=None):
    """Return a local HTML report. Inputs and references remain in its case details."""
    result = evaluate(task, plan, labels, predictions)
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

    configs = {x["id"]: x for x in plan["experiment"]["configs"]}
    prompts = {x["id"]: x for x in plan["experiment"]["prompts"]}
    references = {x["id"]: x["labels"] for x in labels["records"]}
    supplied = {(x["config_id"], x["prompt_id"], x["repeat"], x["id"]): x["prediction"]
                for x in predictions["records"]}
    invalid = {(x["config_id"], x["prompt_id"], x["repeat"], x["id"]) for x in result["invalid"]}
    items = {x["id"]: x["input"] for x in plan["requests"][0]["items"]}
    for req in plan["requests"]:
        if req["config_id"] == plan["experiment"]["configs"][0]["id"] and req["prompt_id"] == plan["experiment"]["prompts"][0]["id"] and req["repeat"] == 1:
            items.update({x["id"]: x["input"] for x in req["items"]})
    all_ids = list(items)
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
    for condition in result["conditions"]:
        cid, pid = condition["config_id"], condition["prompt_id"]
        for entry in condition["passes"]:
            score_by_pass[(cid, pid, entry["repeat"])] = entry["all_field_exact"]
    baseline = plan["experiment"]["prompts"][0]["id"]
    findings = [f"{valid_count} of {total} planned positions have a valid selected classification. "
                f"{result['missing']} have no selected prediction; {len(result['invalid'])} have an invalid selected projection. "
                "Observed runner outcomes are counted separately below, once per planned position. "
                "A valid classification may still disagree with its reference."]
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
            metadata["model"] = metadata["model"] or config["model"]
            for key in ("provider", "route", "effort"):
                metadata[key] = metadata[key] or settings.get(key) or (settings.get("reasoning") if key == "effort" else None)
            values = {"task": task["name"], "model": metadata["model"], "provider": metadata["provider"],
                      "effort": metadata["effort"], "prompt": pid, "repeat": str(repeat), "route": metadata["route"]}
            attributes = " ".join(f"data-{key}='{_h(value if value is not None else 'unavailable')}'"
                                  for key, value in values.items())
            field_rows = []
            for field in task["fields"]:
                name = field["name"]
                stats = entry["fields"][name]
                diagonal = sum(stats["confusion"][label][label] for label in field["labels"])
                support = ", ".join(f"{label}: {stats['labels'][label]['support']}" for label in field["labels"])
                errors = [(actual, predicted, count) for actual in field["labels"]
                          for predicted in field["labels"] if actual != predicted
                          for count in [stats["confusion"][actual][predicted]] if count]
                confusion = ", ".join(f"{a} → {b}: {n}" for a, b, n in errors) or "none"
                field_rows.append((name, _rate(diagonal, entry["denominator"]), support, confusion,
                                   json.dumps(stats["unscored_by_true_label"], ensure_ascii=False)))
            case_rows = []
            pass_outcomes = Counter()
            for record_id in all_ids:
                key = (cid, pid, repeat, record_id)
                status = outcomes[key]
                pass_outcomes[status] += 1
                prediction = supplied.get(key) if key not in invalid else None
                agreement = "unscored" if prediction is None else "agree" if prediction == references[record_id] else "disagree"
                case_rows.append((record_id, status, agreement,
                                  json.dumps(references[record_id], ensure_ascii=False),
                                  json.dumps(supplied[key], ensure_ascii=False) if key in supplied else "unavailable",
                                  json.dumps(items[record_id], ensure_ascii=False)))
            outcome_rows = [(status, count, entry["denominator"]) for status, count in sorted(pass_outcomes.items())]
            paired = []
            if pid != baseline:
                before = score_by_pass[(cid, baseline, repeat)]
                after = entry["all_field_exact"]
                paired.append(f"Paired prompt effect against {_h(baseline)}: {after - before:+d} exact matches "
                              f"({before}/{entry['denominator']} → {after}/{entry['denominator']}).")
            pass_anchor = f"{condition_anchor}-pass-{repeat}"
            contents.append(f"<li class='contents-pass'><a href='#{pass_anchor}'>{_h(cid)} · {_h(pid)} · pass {repeat}</a></li>")
            rows.append(f"<section class='pass' id='{pass_anchor}' {attributes}><h3>{_h(cid)} · {_h(pid)} · pass {repeat}</h3>"
                        f"<p>Requested model: {_h(metadata['model'])}; requested provider: {_h(metadata['provider'] or 'unavailable')}; "
                        f"route: {_h(metadata['route'] or 'unavailable')}; effort: {_h(metadata['effort'] or 'unavailable')}.</p>"
                        "<p>Requested routing is not proof of the serving provider. See observed identity evidence for each request below.</p>"
                        f"<p>Exact agreement: {_rate(entry['all_field_exact'], entry['denominator'])}; "
                        f"no selected prediction: {entry['missing']}; invalid selected projection: {entry['invalid']}. "
                        "Every planned position remains in the denominator. These projection counts are distinct from observed runner outcomes.</p>"
                        + "".join(f"<p>{line}</p>" for line in paired)
                        + "<h4>Observed position outcomes</h4>"
                        + _table(("Outcome", "Positions", "Planned denominator"), outcome_rows,
                                 caption=f"Observed position outcomes for {cid}, {pid}, pass {repeat}", class_name="outcome-table")
                        + "<h4>Field agreement and class errors</h4>"
                        + _table(("Field", "Agreement", "Reference class support", "Valid disagreements", "Unscored by reference class"), field_rows,
                                 caption=f"Field agreement for {cid}, {pid}, pass {repeat}", row_header=True, numeric_columns=(1,))
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
        lo, hi = condition["pass_score_range"]
        exact = sum(entry["all_field_exact"] for entry in condition["passes"])
        denominator = sum(entry["denominator"] for entry in condition["passes"])
        invalid_count = sum(entry["invalid"] for entry in condition["passes"])
        missing_count = sum(entry["missing"] for entry in condition["passes"])
        duration_values = [op["duration_seconds"] for op in condition_ops if op.get("duration_seconds") is not None]
        duration = (f"{_number(sum(duration_values) / len(duration_values), ' s')} mean "
                    f"({len(duration_values)}/{len(condition_requests)} requests measured)"
                    if duration_values else f"unavailable (0/{len(condition_requests)} requests measured)")
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
        comparison_rows.append((cid, pid, _rate(exact, denominator), f"{lo:.1%} to {hi:.1%}",
                                invalid_count, missing_count, duration, observed, coverage))
        chart_id = f"chart-{len(pages)}"
        baseline_scores = {p["repeat"]: score_by_pass[(cid, baseline, p["repeat"])]
                           for p in condition["passes"]}
        visuals = _score_visual(condition, chart_id + "-score")
        if pid != baseline:
            visuals += _delta_visual(condition, baseline_scores, baseline, chart_id + "-delta")
        if len(charge_groups) <= 1:
            chart_currency = next(iter(charge_groups), currency)
            visuals += _cost_visual(condition, costs, chart_id + "-cost", chart_currency)
        else:
            visuals += "<p>Observed costs use more than one currency; see the separate per-currency totals above and in each pass.</p>"
        pages.append(f"<article id='{condition_anchor}'><h2>{_h(cid)} · {_h(pid)}</h2>"
                     f"<p>Prompt: {_h(prompt['text'])}</p>"
                     f"<p>Exact agreement across passes: {lo:.1%} to {hi:.1%}. "
                     "Each pass uses the same input cases; passes are separate dispatches. "
                     "For synthetic outputs, repeated passes show pipeline behavior, not model variability.</p>"
                     "<p>Condition overview below covers all passes, even when a pass filter is selected.</p>"
                     + visuals
                     + ("<h3>Repeat changes</h3>" + _table(("Passes", "Changed valid cases", "Excluded cases", "Changed case IDs"), comparisons,
                                                            caption=f"Repeat changes for {cid} and {pid}", row_header=True, numeric_columns=(1, 2))
                        if comparisons else "<p>No repeat comparison is available.</p>")
                     + "".join(rows) + "</article>")

    filters = []
    for key, label in (("task", "Task"), ("model", "Model"), ("provider", "Provider"),
                       ("effort", "Effort"), ("prompt", "Prompt"), ("repeat", "Pass"), ("route", "Route")):
        if key == "task":
            values = [task["name"]]
        else:
            values = sorted({str(value) for value in _filter_values(key, plan, operations)})
        options = "<option value=''>All</option>" + "".join(f"<option value='{_h(v)}'>{_h(v)}</option>" for v in values)
        filters.append(f"<label>{label} <select data-filter='{key}'>{options}</select></label>")
    source_rows = [(name, digest) for name, digest in result["source_hashes"].items()]
    if operations:
        source_rows.append(("supplied operations", _digest(operations)))
    script = """const filters = [...document.querySelectorAll('[data-filter]')];
    const passes = [...document.querySelectorAll('.pass')];
    function applyFilters() {
      passes.forEach(section => {
        section.hidden = filters.some(filter => filter.value && section.dataset[filter.dataset.filter] !== filter.value);
      });
      document.querySelectorAll('article').forEach(article => {
        article.hidden = !article.querySelector('.pass:not([hidden])');
      });
      const visible = passes.filter(section => !section.hidden).length;
      document.getElementById('filter-status').textContent = `Showing ${visible} of ${passes.length} pass sections.`;
      document.getElementById('filter-empty').hidden = visible !== 0;
    }
    filters.forEach(select => select.addEventListener('change', applyFilters));
    document.getElementById('reset-filters').addEventListener('click', () => {
      filters.forEach(select => { select.value = ''; });
      applyFilters();
    });
    document.querySelectorAll("[data-contents] a[href^='#']").forEach(link => link.addEventListener('click', () => {
      const target = document.getElementById(link.hash.slice(1));
      if (target && (target.hidden || target.closest('article[hidden]'))) {
        filters.forEach(select => { select.value = ''; });
        applyFilters();
      }
    }));
    applyFilters();"""
    comparison = _table(
        ("Configuration", "Prompt", "Exact agreement", "Repeat range", "Invalid selected projections",
         "No selected prediction", "Mean client request duration", "Observed cost", "Cost coverage"),
        comparison_rows, caption="Configuration and prompt comparison (unfiltered)",
        row_header=True, numeric_columns=(2, 3, 4, 5, 6, 7, 8), class_name="comparison-table")
    synthetic_notice = ("<p class='notice'>Contains synthetic results: SYN units are local accounting, not provider charges.</p>"
                        if any(config.get("settings", {}).get("adapter") == "synthetic" for config in configs.values())
                        or any(str(op.get("route", "")).startswith("synthetic:") for op in operations) else "")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{_h(task['name'])} · local classification report</title>"
            "<style>body{font:16px/1.55 system-ui,sans-serif;max-width:1100px;margin:auto;padding:2rem;color:#18222c;background:#f7f8fa;font-variant-numeric:tabular-nums}"
            "h1,h2,h3{line-height:1.2;letter-spacing:-.025em}p{max-width:70ch}article,.pass,header,footer,.overview{background:white;border:1px solid #d8dfe6;border-radius:8px;padding:1rem;margin:1rem 0}"
            "table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}caption{text-align:left;font-weight:600;padding:.5rem 0}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #d8dfe6;padding:.5rem;white-space:pre-wrap;overflow-wrap:anywhere}"
            ".numeric,.outcome-table td:nth-child(n+2){text-align:right;font-variant-numeric:tabular-nums}tbody th[scope=row]{font-weight:600}"
            "label{display:inline-block;margin:.3rem}select,button{font:inherit;max-width:14rem}button{padding:.35rem .7rem;border:1px solid #526879;border-radius:4px;background:white;color:#18222c;cursor:pointer}"
            "button:hover{background:#e9eff2}button:active{background:#dce6eb}a:focus-visible,button:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #176c8a;outline-offset:3px}"
            "details{margin-top:1rem}.notice{border-left:3px solid #176c8a;padding-left:.75rem}.contents-pass{margin-left:1rem}.skip-link{position:absolute;left:-10000px;top:auto}.skip-link:focus{left:1rem;top:1rem;z-index:2;background:white;padding:.4rem}"
            ".pass[hidden],article[hidden],[hidden]{display:none!important}svg{max-width:100%;margin:.5rem 0}</style></head><body>"
            "<a class='skip-link' href='#main-content'>Skip to main content</a>"
            f"<header><h1>{_h(task['name'])}</h1><p>Private local classification report</p>" + synthetic_notice +
            "<h2>Whole experiment summary (unfiltered)</h2><p>Filters below apply to pass details. "
            "The totals and findings in this summary always cover the complete experiment.</p>"
            f"<p>Planned positions: {total}; valid selected predictions: {valid_count}; no selected prediction: {result['missing']}; invalid selected projection: {len(result['invalid'])}.</p>"
            "<h2>Observed position outcomes</h2>"
            + _table(("Outcome", "Positions", "Planned denominator"),
                     [(status, count, total) for status, count in sorted(outcome_counts.items())],
                     caption="Observed outcomes across the whole experiment", class_name="outcome-table")
            + "<p>Each planned position appears once in this table. A missing selected prediction can correspond to a refusal, failure, unknown dispatch, or a request without observed evidence.</p>"
            "<p>Scores use all planned positions. Positions without valid selected predictions receive no agreement credit. "
            "Request timing is measured per request, which may contain a batch; it is not per-case inference latency.</p>"
            "<h2>Findings</h2>" + "".join(f"<p>{x}</p>" for x in findings)
            + "<nav aria-label='Report filters'>" + " ".join(filters) +
            " <button type='button' id='reset-filters'>Reset filters</button></nav>"
            f"<p id='filter-status' role='status' aria-live='polite'>Showing {sum(len(c['passes']) for c in result['conditions'])} of {sum(len(c['passes']) for c in result['conditions'])} pass sections.</p>"
            "<p id='filter-empty' hidden>No pass sections match these filters. Reset filters to show all passes.</p></header>"
            "<main id='main-content'>"
            "<section class='overview' aria-labelledby='comparison-heading'><h2 id='comparison-heading'>Compare configurations and prompts</h2>"
            "<p>This overview always includes every pass. Exact agreement uses every planned position; missing and invalid predictions receive no credit. "
            "Observed cost totals include recorded charges only, with coverage shown against planned requests. Estimates are reported separately in request details.</p>"
            + comparison + "</section>"
            + "<nav class='overview' data-contents aria-label='Report contents'><h2>Contents</h2><ul>" + "".join(contents) + "</ul></nav>"
            + "".join(pages) + "</main>"
            + "<footer><h2>Provenance</h2><p>Canonical JSON SHA-256 digests bind the task, plan, references, selected prediction set and any supplied operation records. "
            "The evaluator validates planned positions and predictions; the caller is responsible for verifying operation records. "
            "This file includes private inputs and reference labels. Keep it local.</p>"
            "<p>Token fields follow <a href='https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion'>OpenRouter's chat response schema</a>. "
            "Cache reads and writes follow <a href='https://openrouter.ai/docs/guides/best-practices/prompt-caching'>OpenRouter's caching documentation</a>.</p>"
            + _table(("Source", "SHA-256"), source_rows, caption="Source digests", row_header=True)
            + "</footer><script>" + script + "</script></body></html>")


def _filter_values(key, plan, operations):
    values = set()
    if key == "prompt":
        return {x["id"] for x in plan["experiment"]["prompts"]}
    if key == "repeat":
        return {str(x) for x in range(1, plan["experiment"]["repeats"] + 1)}
    for config in plan["experiment"]["configs"]:
        settings = config.get("settings", {})
        value = config["model"] if key == "model" else settings.get(key)
        if key == "effort" and value is None:
            value = settings.get("reasoning")
        values.add(value or "unavailable")
    for op in operations:
        if key in op and op[key] is not None:
            values.add(op[key])
    return values
