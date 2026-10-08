"""Measured operations alongside full-denominator output and reference coverage.

Consumes exact supplied operation metadata, never raw transcripts or estimated
charges. Comparisons describe saved requests, not model compute or causality.
"""

from collections import Counter
from copy import deepcopy
from math import fsum, isfinite

from .core import ValidationError, _digest
from .report_analysis import EVIDENCE_FIELDS
from .report_comparisons import _context, build_comparative_findings


TOKEN_FIELDS = ("input_tokens", "output_tokens", "reasoning_tokens", "cache_tokens")
TIMING_FIELDS = ("duration_seconds", "provider_generation_seconds")
METRICS = ("observed_cost_micro_usd", *TOKEN_FIELDS, *TIMING_FIELDS)
INTERPRETATION = ("Descriptive measured operations on the same saved task and inputs; no causal effect, "
                  "token-efficiency claim or deployment guarantee. Supplied metadata is bound by hashes; "
                  "provider execution is not independently verified by this analysis.")


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _seconds(value):
    return value if type(value) in (int, float) and isfinite(value) and value >= 0 else None


def _token(operation, field):
    usage = operation.get("usage")
    if usage is None:
        usage = {}
    if not isinstance(usage, dict):
        return None, None
    aliases = {"input_tokens": ("prompt_tokens", "input_tokens"),
               "output_tokens": ("completion_tokens", "output_tokens"),
               "reasoning_tokens": ("reasoning_tokens",), "cache_tokens": ("cached_tokens", "cache_tokens")}
    nested = {"reasoning_tokens": ("completion_tokens_details", "reasoning_tokens"),
              "cache_tokens": ("prompt_tokens_details", "cached_tokens")}
    if field in nested:
        parent, key = nested[field]
        if parent in usage:
            if not isinstance(usage[parent], dict):
                return None, None
            if key in usage[parent]:
                return _count(usage[parent][key]), f"usage.{parent}.{key}"
    for key in aliases[field]:
        if key in usage:
            return _count(usage[key]), f"usage.{key}"
    for key in (field, *aliases[field]):
        if key in operation and operation[key] is not None:
            return _count(operation[key]), f"operation.{key}"
    return None, None


def _tokenizer(operation):
    # Catalog tokenizer families (for example "GPT") do not establish an exact
    # shared encoding. Only retain the operation's explicitly supplied label.
    value = operation.get("tokenizer")
    return value if isinstance(value, str) and value.strip() else None


def _provider_context(operation):
    digest = operation.get("generation_response_sha256")
    if (not isinstance(digest, str) or len(digest) != 64 or
            any(c not in "0123456789abcdef" for c in digest) or
            operation.get("provider_identity_status") != "observed"):
        return None
    route, provider = operation.get("route"), operation.get("returned_provider")
    source = operation.get("provider_timing_source")
    if source is None and isinstance(route, str) and route.startswith("openrouter:"):
        source = "openrouter_generation_metadata.generation_time_ms"
    if not all(isinstance(v, str) and v.strip() for v in (route, provider, source)):
        return None
    return route, provider, source


def _operation_map(analysis, operations):
    if not isinstance(operations, list) or any(not isinstance(op, dict) for op in operations):
        raise ValidationError("operational findings: expected operation objects")
    try:
        same_source = _digest(operations) == analysis["source_hashes"].get("operations")
    except (TypeError, ValueError) as exc:
        raise ValidationError("operational findings: operation sources must be finite JSON") from exc
    if not same_source:
        raise ValidationError("operational findings: operation sources do not match analysis")
    planned = {}
    for run in analysis["runs"]:
        groups = {}
        for case in run["cases"]:
            groups.setdefault(case["request_id"], []).append(case["case_id"])
        for index, request_id in enumerate(run["request_ids"], 1):
            if request_id in planned or request_id not in groups:
                raise ValidationError("operational findings: inconsistent planned request membership")
            planned[request_id] = {"config_id": run["config_id"], "prompt_id": run["prompt_id"],
                                   "repeat": run["repeat"], "batch_index": index, "ids": groups[request_id]}
    result = {}
    for operation in operations:
        rid = operation.get("request_id")
        if not isinstance(rid, str) or rid not in planned or rid in result:
            raise ValidationError("operational findings: unknown or duplicate request membership")
        if any(key in operation and operation[key] != value for key, value in planned[rid].items()):
            raise ValidationError("operational findings: operation request membership differs")
        result[rid] = operation
    return result


def _summarize(run, operations):
    measured = {key: [] for key in METRICS}
    tokenizers, provider_contexts, evidence, lifecycle = [], [], [], Counter()
    holds, hold_coverage, synthetic = 0, 0, 0
    configuration = run["configuration"]
    synthetic_config = configuration.get("settings", {}).get("adapter") == "synthetic"
    for rid in run["request_ids"]:
        op = operations.get(rid, {})
        lifecycle[op.get("state") or "unavailable"] += 1
        record = {"request_id": rid, "state": op.get("state"),
                  "hashes": {key: op[key] for key in EVIDENCE_FIELDS if op.get(key) is not None}}
        evidence.append(record)
        if synthetic_config or op.get("cost_currency") == "SYN" or str(op.get("route", "")).startswith("synthetic:"):
            synthetic += 1
            continue
        amount = _count(op.get("observed_cost_micro_usd")) if op.get("cost_currency") == "USD" else None
        if amount is not None:
            measured["observed_cost_micro_usd"].append(amount)
        hold = _count(op.get("unresolved_hold_micro_usd")) if op.get("cost_currency") == "USD" else None
        if hold is not None:
            holds += hold
            hold_coverage += 1
        tokens = {field: _token(op, field) for field in TOKEN_FIELDS}
        for subset, total in (("reasoning_tokens", "output_tokens"), ("cache_tokens", "input_tokens")):
            if tokens[subset][0] is not None and tokens[total][0] is not None and tokens[subset][0] > tokens[total][0]:
                tokens[subset] = None, None
        record["token_sources"] = {field: source for field, (value, source) in tokens.items() if value is not None}
        for field, (value, _) in tokens.items():
            if value is not None:
                measured[field].append(value)
        tokenizers.append(_tokenizer(op))
        seconds = _seconds(op.get("duration_seconds"))
        if seconds is not None:
            measured["duration_seconds"].append(seconds)
        context = _provider_context(op)
        seconds = _seconds(op.get("provider_generation_seconds"))
        if seconds is not None and context is not None:
            measured["provider_generation_seconds"].append(seconds)
            provider_contexts.append(context)
    planned = len(run["request_ids"])
    measurements = {}
    for field, values in measured.items():
        total = (fsum(values) if field in TIMING_FIELDS else sum(values)) if values else None
        measurements[field] = {"total": total, "mean": total / len(values) if values else None,
            "measured_requests": len(values), "planned_requests": planned, "complete": len(values) == planned}
    shared_tokenizer = tokenizers[0] if (len(tokenizers) == planned and tokenizers and
                        tokenizers[0] is not None and all(v == tokenizers[0] for v in tokenizers)) else None
    provider_context = provider_contexts[0] if (len(provider_contexts) == planned and provider_contexts and
                        all(v == provider_contexts[0] for v in provider_contexts)) else None
    return {"run_id": run["run_id"], "config_id": run["config_id"], "planned_requests": planned,
            "measurements": measurements, "quality": deepcopy(run["counts"]), "lifecycle": dict(sorted(lifecycle.items())),
            "synthetic_excluded_requests": synthetic, "unresolved_hold_micro_usd": holds if hold_coverage else None,
            "tokenizer": shared_tokenizer, "provider_timing_context": provider_context, "evidence": evidence}


def _quality_text(a, b):
    first = (f"A has {a['valid']}/{a['planned']} valid outputs ({a['invalid']} invalid, {a['missing']} missing); "
             f"B has {b['valid']}/{b['planned']} ({b['invalid']} invalid, {b['missing']} missing). ")
    if a["full_denominator_exact_rate"] is not None and b["full_denominator_exact_rate"] is not None:
        return first + (f"Full-denominator reference agreement is {a['exact_correct']}/{a['planned']} for A "
                        f"and {b['exact_correct']}/{b['planned']} for B. ")
    return first + "Full-denominator reference agreement is unavailable where references are incomplete. "


def _finding(analysis, kind, title, observation, runs, denominator, metrics):
    item = {"kind": kind, "title": title, "observation": observation,
            "scope": "Same task and ordered inputs; selected configuration, prompt and repeat; measured requests include failed outputs",
            "denominator": denominator, "run_ids": runs, "case_ids": [], "metrics": metrics,
            "source_hashes": deepcopy(analysis["source_hashes"]), "interpretation": INTERPRETATION,
            "next_step": "Inspect request receipts, failed cases and declared settings before drawing an operational conclusion; retain unknown charges and missing coverage.",
            "supporting_links": [{"label": "Inspect measured requests and output evidence", "run_a": runs[0],
                                  **({"run_b": runs[1]} if len(runs) > 1 else {})}]}
    item["finding_id"] = _digest({"analysis": analysis["analysis_id"], "algorithm_version": 1, **item})
    return item


def build_operational_findings(analysis, operations, *, comparative=None):
    """Compare complete observations, retaining partial evidence as coverage only."""
    _context(analysis)
    mapped = _operation_map(analysis, operations)
    if comparative is None:
        comparative = build_comparative_findings(analysis)
    if comparative["analysis_id"] != analysis["analysis_id"] or comparative["source_hashes"] != analysis["source_hashes"]:
        raise ValidationError("operational findings: comparison sources do not match analysis")
    summaries = [_summarize(run, mapped) for run in analysis["runs"]]
    by_run = {run["run_id"]: run for run in summaries}
    original = {run["run_id"]: run for run in analysis["runs"]}
    findings, pairs = [], []
    for run in summaries:
        metrics = run["measurements"]
        cost, duration = metrics["observed_cost_micro_usd"], metrics["duration_seconds"]
        text = (f"Observed USD charges cover {cost['measured_requests']}/{run['planned_requests']} requests; "
                + (f"their recorded subtotal is ${cost['total'] / 1_000_000:.6f}. " if cost["total"] is not None else "charges are unavailable. ")
                + f"Client duration request coverage is {duration['measured_requests']}/{run['planned_requests']}. "
                + (f"The measured mean is {duration['mean']:.3f} seconds. " if duration["mean"] is not None else "No measured mean is available. ")
                + f"Token request coverage (input/output/reasoning/cache) is "
                + "/".join(str(metrics[field]["measured_requests"]) for field in TOKEN_FIELDS)
                + f", each out of {run['planned_requests']}. "
                + "Measured token subtotals are "
                + "; ".join(f"{field}: {metrics[field]['total']}" if metrics[field]["total"] is not None else
                            f"{field}: unavailable" for field in TOKEN_FIELDS) + ". "
                + f"Provider-generation timing covers {metrics['provider_generation_seconds']['measured_requests']}/{run['planned_requests']} requests with attributed metadata. "
                + f"{run['synthetic_excluded_requests']} synthetic requests are excluded. Partial sums are not whole-run totals; "
                + "client duration includes serving and transport and is not pure inference time. Token counts are reported units, not comparable compute.")
        findings.append(_finding(analysis, "operational_coverage", "Measured request coverage", text,
                                 [run["run_id"]], run["planned_requests"], deepcopy(run)))
    for candidate in comparative["pairs"]:
        a, b = by_run[candidate["run_a"]], by_run[candidate["run_b"]]
        if a["synthetic_excluded_requests"] or b["synthetic_excluded_requests"]:
            continue
        if not any(m["measured_requests"] for run in (a, b) for m in run["measurements"].values()):
            continue
        comparisons, unavailable = {}, {}
        batches = []
        for run in (original[a["run_id"]], original[b["run_id"]]):
            groups = {}
            for case in run["cases"]:
                groups.setdefault(case["request_id"], []).append(case["case_id"])
            batches.append(list(groups.values()))
        for field in METRICS:
            ma, mb = a["measurements"][field], b["measurements"][field]
            reason = None
            if not ma["complete"] or not mb["complete"]:
                reason = "incomplete request measurement coverage"
            elif field == "observed_cost_micro_usd" and (a["unresolved_hold_micro_usd"] or b["unresolved_hold_micro_usd"]):
                reason = "unresolved monetary holds prevent a total-cost comparison"
            elif field in TOKEN_FIELDS and (a["tokenizer"] is None or a["tokenizer"] != b["tokenizer"]):
                reason = "shared tokenizer evidence unavailable or differs; no token-efficiency interpretation"
            elif field in TIMING_FIELDS and batches[0] != batches[1]:
                reason = "request batch membership differs; mean request timing is incomparable"
            elif field == "provider_generation_seconds" and (a["provider_timing_context"] is None or
                                                            a["provider_timing_context"] != b["provider_timing_context"]):
                reason = "provider route or timing source differs or is unavailable"
            if reason:
                unavailable[field] = reason
            else:
                key = "mean" if field in TIMING_FIELDS else "total"
                comparisons[field] = {"a": ma[key], "b": mb[key], "delta_b_minus_a": mb[key] - ma[key],
                                      "statistic": key, "request_coverage_a": [ma["measured_requests"], ma["planned_requests"]],
                                      "request_coverage_b": [mb["measured_requests"], mb["planned_requests"]]}
        changes = [{key: change[key] for key in ("pointer", "a_present", "b_present")}
                   for change in candidate["configuration_changes"]]
        pair = {"run_a": a["run_id"], "run_b": b["run_id"], "comparison_id": candidate["comparison_id"],
                "planned_cases": candidate["planned"], "quality_a": deepcopy(a["quality"]), "quality_b": deepcopy(b["quality"]),
                "lifecycle_a": deepcopy(a["lifecycle"]), "lifecycle_b": deepcopy(b["lifecycle"]),
                "unresolved_hold_micro_usd_a": a["unresolved_hold_micro_usd"], "unresolved_hold_micro_usd_b": b["unresolved_hold_micro_usd"],
                "declared_changes": changes, "design": candidate["design"], "comparisons": comparisons,
                "unavailable_comparisons": unavailable}
        pairs.append(pair)
        text = _quality_text(a["quality"], b["quality"])
        if "observed_cost_micro_usd" in comparisons:
            cost = comparisons["observed_cost_micro_usd"]
            text += (f"Observed charges are ${cost['a'] / 1_000_000:.6f} for A and ${cost['b'] / 1_000_000:.6f} for B "
                     f"(request coverage {a['planned_requests']}/{a['planned_requests']} and {b['planned_requests']}/{b['planned_requests']}). ")
        else:
            text += "A total-cost comparison is unavailable. "
        if "duration_seconds" in comparisons:
            timing = comparisons["duration_seconds"]
            text += f"Measured mean client duration is {timing['a']:.3f} seconds for A and {timing['b']:.3f} for B, with complete request coverage. "
        else:
            text += "A mean client-duration comparison is unavailable. "
        if "provider_generation_seconds" in comparisons:
            timing = comparisons["provider_generation_seconds"]
            text += f"Separately sourced provider-generation means are {timing['a']:.3f} and {timing['b']:.3f} seconds on the same route and metadata source. "
        token_values = [f"{field}: {comparisons[field]['a']} vs {comparisons[field]['b']}" for field in TOKEN_FIELDS if field in comparisons]
        if token_values:
            text += "Reported token totals with the same supplied tokenizer label are " + "; ".join(token_values) + ". Exact encoding equivalence is not independently verified. "
        else:
            text += "Token totals remain per-run observations; a shared tokenizer comparison is unavailable. "
        text += ("Declared requested differences: " + ", ".join(c["pointer"] for c in changes) + ". " if changes else
                 "Requested settings are identical under separate configuration IDs. ")
        text += ("Missing and invalid cases remain in the planned denominator. Failed attempts remain in measured request costs and timings; "
                 "client duration is not pure inference time. These differences do not establish causality or token efficiency.")
        findings.append(_finding(analysis, "operational_comparison", "Measured operations and output reliability", text,
                                 [a["run_id"], b["run_id"]], candidate["planned"], deepcopy(pair)))
    return {"schema_version": 1, "analysis_id": analysis["analysis_id"],
            "source_hashes": deepcopy(analysis["source_hashes"]), "runs": summaries, "pairs": pairs, "findings": findings}
