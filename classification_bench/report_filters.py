"""One declared report filter state over frozen planned runs, without rescoring.

Metadata describes the requested configuration or a local adapter contract. It
never infers architecture, serving identity or correctness from a model name.
Lifecycle matching selects a whole run containing that state, not a case subset.
"""

from copy import deepcopy
from html import escape
import json

from .core import ValidationError, _digest, validate_task
from .decision_adapters import CONTRACTS
from .subscription_adapters import PROVIDERS


FILTER_LABELS = {
    "model_group": "Declared model group", "model": "Requested model",
    "provider": "Requested provider / account route", "execution_route": "Execution route",
    "output_interface": "Output interface", "effort": "Requested effort / reasoning",
    "prompt": "Prompt", "repeat": "Repeat", "lifecycle": "Run contains lifecycle state",
    "api_route": "Requested API route", "adapter_category": "Adapter category",
}
GROUP_LABELS = {"llm": "General LLM", "fine_tuned_llm": "Fine-tuned LLM",
                "decision": "Classification / decision", None: "Unspecified"}
_INTERFACES = {"openrouter": "JSON text", "claude_code": "Schema-constrained JSON",
               "codex": "Schema-constrained JSON", "synthetic": "Synthetic JSON",
               **{adapter: "Native choices and probabilities" for adapter in CONTRACTS}}


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def _category(adapter):
    if adapter is None or adapter == "":
        return "Adapter unspecified"
    if not isinstance(adapter, str):
        return "Invalid declared adapter"
    if adapter == "openrouter":
        return "OpenRouter"
    if adapter in CONTRACTS:
        return "Native decisions"
    if adapter == "claude_code":
        return "Claude Code"
    if adapter == "codex":
        return "Codex"
    if adapter == "synthetic":
        return "Synthetic"
    return "Other declared adapter"


def _option(key, value):
    label = GROUP_LABELS.get(value, value) if key == "model_group" else value
    if value is None and key != "model_group":
        label = "Unavailable / unspecified"
    elif value == "Unavailable / unspecified":
        label += " (declared)"
    return {"id": _digest({"filter": key, "value": value}), "value": value, "label": label}


def build_report_filter_data(analysis):
    """Return allowlisted run metadata and stable option IDs for a report.

    Configuration values take precedence over adapter-contract defaults. Unknown
    interfaces remain unavailable. Source objects and scoring results are untouched.
    """
    if not isinstance(analysis, dict) or analysis.get("schema_version") != 1:
        raise ValidationError("report filters: expected analysis schema version 1")
    validate_task(analysis.get("task"))
    if not isinstance(analysis.get("analysis_id"), str) or not isinstance(analysis.get("runs"), list):
        raise ValidationError("report filters: expected analysis identity and runs")
    runs, seen, options = [], set(), {key: {} for key in FILTER_LABELS}
    # All declared reporting groups remain selectable, including zero-run groups.
    for value in GROUP_LABELS:
        option = _option("model_group", value)
        options["model_group"][option["id"]] = option
    for run in analysis["runs"]:
        if not isinstance(run, dict) or not _text(run.get("run_id")) or run["run_id"] in seen:
            raise ValidationError("report filters: invalid or duplicate run ID")
        seen.add(run["run_id"])
        config = run.get("configuration")
        if not isinstance(config, dict) or not isinstance(config.get("settings", {}), dict):
            raise ValidationError("report filters: expected frozen configuration settings")
        if config.get("id") != run.get("config_id") or not _text(config.get("model")) or not _text(run.get("prompt_id")):
            raise ValidationError("report filters: inconsistent run configuration or prompt")
        if type(run.get("repeat")) is not int or run["repeat"] < 1:
            raise ValidationError("report filters: invalid repeat")
        if config.get("model_type") not in (None, "llm", "fine_tuned_llm", "decision"):
            raise ValidationError("report filters: invalid declared model group")
        settings = config.get("settings", {})
        adapter = _text(settings.get("adapter"))
        provider = _text(settings.get("provider"))
        provider_source = "declared configuration" if provider is not None else "unavailable"
        if provider is None and adapter in CONTRACTS:
            provider, provider_source = CONTRACTS[adapter]["provider"], "native adapter contract"
        elif provider is None and adapter in PROVIDERS:
            provider, provider_source = PROVIDERS[adapter], "subscription adapter contract"
        interface = _text(settings.get("output_interface"))
        interface_source = "declared configuration" if interface is not None else "unavailable"
        if interface is None and adapter in _INTERFACES:
            interface, interface_source = _INTERFACES[adapter], "adapter output contract"
        api_route = _text(settings.get("route"))
        if api_route is None and adapter in CONTRACTS and config["model"] == CONTRACTS[adapter]["model"]:
            api_route = f"{CONTRACTS[adapter]['provider']}:{config['model']}"
        elif api_route is None and adapter == "openrouter" and provider is not None:
            api_route = f"openrouter:{config['model']}:{provider}"
        elif api_route is None and adapter in PROVIDERS:
            api_route = f"{adapter}:{config['model']}:existing-account"
        cases, counts = run.get("cases"), run.get("counts")
        if not isinstance(cases, list) or not cases or not isinstance(counts, dict):
            raise ValidationError("report filters: expected planned cases and counts")
        if any(not isinstance(case, dict) for case in cases):
            raise ValidationError("report filters: invalid case projection")
        required_counts = {key: counts.get(key) for key in ("planned", "valid", "invalid", "missing")}
        if (any(type(value) is not int or value < 0 for value in required_counts.values()) or
                counts["planned"] != len(cases) or sum(counts[key] for key in ("valid", "invalid", "missing")) != len(cases)):
            raise ValidationError("report filters: inconsistent planned validity counts")
        if any(case.get("prediction_status") not in ("valid", "invalid", "missing") for case in cases):
            raise ValidationError("report filters: invalid prediction status")
        if any(sum(case["prediction_status"] == key for case in cases) != counts[key] for key in ("valid", "invalid", "missing")):
            raise ValidationError("report filters: case statuses disagree with counts")
        states = []
        for case in cases:
            value = case.get("lifecycle_state")
            if value is not None and not isinstance(value, str):
                raise ValidationError("report filters: lifecycle state must be string or null")
            value = _text(value)
            if value not in states:
                states.append(value)
        values = {"model_group": config.get("model_type"), "model": config["model"],
                  "provider": provider, "execution_route": adapter, "output_interface": interface,
                  "effort": _text(settings.get("effort")) or _text(settings.get("reasoning")),
                  "prompt": run["prompt_id"], "repeat": str(run["repeat"]), "lifecycle": states,
                  "api_route": api_route, "adapter_category": _category(settings.get("adapter"))}
        tokens = {}
        for key, value in values.items():
            tokens[key] = []
            for item in value if key == "lifecycle" else [value]:
                option = _option(key, item)
                options[key][option["id"]] = option
                tokens[key].append(option["id"])
        runs.append({"run_id": run["run_id"], "config_id": run["config_id"], "prompt_id": run["prompt_id"],
                     "repeat": run["repeat"], "counts": required_counts, "values": values, "tokens": tokens,
                     "metadata_sources": {"model_group": "operator declaration; unspecified when absent",
                                          "provider": provider_source, "output_interface": interface_source,
                                          "execution_route": "declared adapter identity; serving identity not inferred",
                                          "lifecycle": "saved case lifecycle metadata; entire run retained"}})
    result = {"schema_version": 1, "analysis_id": analysis["analysis_id"],
              "source_hashes": deepcopy(analysis.get("source_hashes", {})), "runs": runs,
              "labels": deepcopy(FILTER_LABELS),
              "options": {key: list(values.values()) for key, values in options.items()},
              "distinct_cases": len(analysis.get("case_ids", [])),
              "scope_rule": "Filters select planned runs. Lifecycle selects runs containing a matching state; every case in those runs remains in scope.",
              "condition_rule": "Condition metrics retain all planned repeats. Partial repeat visibility changes evidence scope, never the saved aggregate."}
    result["whole"] = _counts(runs, result["distinct_cases"])
    result["filter_data_id"] = _digest(result)
    return result


def _counts(runs, distinct_cases):
    return {"runs": len(runs), "positions": sum(run["counts"]["planned"] for run in runs),
            "conditions": len({(run["config_id"], run["prompt_id"]) for run in runs}),
            "distinctCases": distinct_cases if runs else 0,
            **{key: sum(run["counts"][key] for run in runs) for key in ("valid", "invalid", "missing")}}


def filter_report_runs(data, selected_filters=None):
    """Pure selection projection, sharing the controller's opaque-ID semantics."""
    if selected_filters is None:
        selected_filters = {}
    if not isinstance(selected_filters, dict) or set(selected_filters) - set(FILTER_LABELS):
        raise ValidationError("report filters: unknown filter key")
    selected = {key: selected_filters.get(key, "") for key in FILTER_LABELS}
    selected_values = {}
    for key, option_id in selected.items():
        options = {option["id"]: option for option in data["options"][key]}
        if not isinstance(option_id, str) or option_id and option_id not in options:
            raise ValidationError("report filters: unknown option ID")
        if option_id:
            selected_values[key] = deepcopy(options[option_id]["value"])
    eligible = [run for run in data["runs"] if all(not option or option in run["tokens"][key] for key, option in selected.items())]
    eligible_ids, conditions = {run["run_id"] for run in eligible}, {}
    for run in data["runs"]:
        key = run["config_id"], run["prompt_id"]
        conditions.setdefault(key, []).append(run["run_id"])
    scopes = [{"config_id": key[0], "prompt_id": key[1], "plannedRunIds": list(ids),
               "eligibleRunIds": [run_id for run_id in ids if run_id in eligible_ids],
               "totalRuns": len(ids), "visibleRuns": sum(run_id in eligible_ids for run_id in ids),
               "partial": 0 < sum(run_id in eligible_ids for run_id in ids) < len(ids)} for key, ids in conditions.items()]
    return {"eligibleRunIds": [run["run_id"] for run in eligible], "selectedFilters": selected,
            "selectedValues": selected_values, "whole": deepcopy(data["whole"]),
            "visible": _counts(eligible, data["distinct_cases"]), "conditionScopes": scopes,
            "filterDataId": data["filter_data_id"], "scopeRule": data["scope_rule"],
            "conditionRule": data["condition_rule"]}


def render_report_filters(analysis):
    """Render one shared control state and a small offline integration API.

    Existing controls are aliases via ``data-report-filter`` (canonical key), or
    recognized legacy ``data-filter``/``data-comparison-filter`` names. Call
    ``refreshAliases`` once after later controls have been parsed. Controllers
    never hide evidence or recalculate metrics themselves; consumers apply the
    eligible-run event and retain selected evidence outside it with disclosure.
    """
    data = build_report_filter_data(analysis)
    h = lambda value: escape(str(value), quote=True)
    controls = []
    for key, label in FILTER_LABELS.items():
        if key == "adapter_category":
            continue
        options = "<option value=''>All</option>" + "".join(f"<option value='{option['id']}'>{h(option['label'])}</option>" for option in data["options"][key])
        controls.append(f"<label for='report-filter-{key}'>{h(label)}<select id='report-filter-{key}' data-report-filter='{key}'>{options}</select></label>")
    whole = data["whole"]
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return (_STYLE + "<section class='shared-report-filters' id='shared-report-filters' aria-labelledby='shared-report-filters-heading'>"
            "<h2 id='shared-report-filters-heading'>Choose the report scope</h2>"
            "<p>These controls share one state across report views. Whole-experiment totals remain fixed. "
            "Metadata describes requested configurations or declared adapter contracts; it does not prove serving identity.</p>"
            "<div class='shared-filter-controls'>" + "".join(controls) + "</div>"
            "<div class='shared-filter-actions'><button type='button' id='report-filters-reset'>Reset shared filters</button>"
            f"<p id='report-filters-status' role='status' aria-live='polite'>{whole['runs']} / {whole['runs']} planned runs; "
            f"{whole['positions']} / {whole['positions']} planned run-case positions.</p></div>"
            "<p id='report-filters-notice' role='status' hidden></p>"
            "<p>Lifecycle filtering selects whole runs containing the state. It keeps every planned case in those runs. "
            "Condition aggregates retain all planned repeats, including those outside the visible scope. "
            "Unknown adapter interfaces and absent metadata stay unavailable.</p>"
            "<noscript><p>JavaScript is disabled. Shared filters cannot apply; all planned report evidence remains visible.</p></noscript></section>"
            "<script type='application/json' id='report-filter-data'>" + encoded + "</script>" + _SCRIPT)


_STYLE = """<style>
.shared-report-filters{padding:2rem 0;border-top:1px solid var(--line,#dcded8);font-variant-numeric:tabular-nums;scroll-margin-top:5rem}
.shared-report-filters p{max-width:75ch;line-height:1.55}.shared-report-filters .shared-filter-controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,14rem),1fr));gap:1rem;margin:1.2rem 0}
.shared-report-filters label{font-size:.8rem;font-weight:600;min-width:0}.shared-report-filters select{display:block;width:100%;padding:.6rem .7rem;margin-top:.4rem;font:inherit;color:inherit;background:var(--surface,#fff);border:1px solid #aeb9af;border-radius:3px;min-width:0}
.shared-report-filters .shared-filter-actions{display:flex;flex-wrap:wrap;align-items:center;gap:1rem}.shared-report-filters button{padding:.6rem .8rem;font:inherit;cursor:pointer;color:var(--accent,#245b4b);border:1px solid currentColor;border-radius:3px;background:transparent}
.shared-report-filters button:hover{background:var(--soft,#e9efe9)}.shared-report-filters button:active{transform:translateY(1px)}.shared-report-filters :is(button,select):focus-visible{outline:3px solid var(--accent,#245b4b);outline-offset:3px}
.shared-report-filters [hidden]{display:none!important}.shared-report-filters #report-filters-notice{border-left:3px solid var(--accent,#245b4b);padding-left:.8rem;overflow-wrap:anywhere}
@media(prefers-reduced-motion:reduce){.shared-report-filters *{transition:none!important;animation:none!important}}
@media print{.shared-report-filters .shared-filter-controls,.shared-report-filters button{display:none!important}}
</style>"""

_SCRIPT = """<script>(()=>{
'use strict';const root=document.getElementById('shared-report-filters');if(!root)return;
const data=JSON.parse(document.getElementById('report-filter-data').textContent),keys=Object.keys(data.labels);
const options=Object.fromEntries(keys.map(key=>[key,new Map(data.options[key].map(option=>[option.id,option]))]));
const selected=Object.fromEntries(keys.map(key=>[key,''])),bound=new WeakSet();
const legacy={model:'model',provider:'provider',route:'api_route',effort:'effort',prompt:'prompt',repeat:'repeat'};
const notices=document.getElementById('report-filters-notice');let snapshot=null;
const clone=value=>JSON.parse(JSON.stringify(value));
function controlKey(node){return node.dataset.reportFilter||legacy[node.dataset.filter||node.dataset.comparisonFilter];}
function controls(){return [...document.querySelectorAll('select[data-report-filter],select[data-filter],select[data-comparison-filter]')].filter(node=>keys.includes(controlKey(node)));}
function fragment(url){const pieces=url.hash.slice(1).split('?');return {heading:pieces[0],params:new URLSearchParams(pieces.slice(1).join('?'))};}
function writeURL(){const url=new URL(window.location.href),part=fragment(url);keys.forEach(key=>part.params.set('rf_'+key,selected[key]));url.hash=(part.heading||'comparison-heading')+'?'+part.params.toString();
try{window.history.replaceState(null,'',url.href);}catch(_){if(window.location.hash!==url.hash)window.location.hash=url.hash;}}
function counts(runs){return {runs:runs.length,positions:runs.reduce((n,run)=>n+run.counts.planned,0),conditions:new Set(runs.map(run=>JSON.stringify([run.config_id,run.prompt_id]))).size,distinctCases:runs.length?data.distinct_cases:0,
valid:runs.reduce((n,run)=>n+run.counts.valid,0),invalid:runs.reduce((n,run)=>n+run.counts.invalid,0),missing:runs.reduce((n,run)=>n+run.counts.missing,0)};}
function detail(){const eligible=data.runs.filter(run=>keys.every(key=>!selected[key]||run.tokens[key].includes(selected[key]))),ids=new Set(eligible.map(run=>run.run_id)),conditions=new Map();
data.runs.forEach(run=>{const key=JSON.stringify([run.config_id,run.prompt_id]);if(!conditions.has(key))conditions.set(key,{config_id:run.config_id,prompt_id:run.prompt_id,plannedRunIds:[]});conditions.get(key).plannedRunIds.push(run.run_id);});
const scopes=[...conditions.values()].map(value=>{const included=value.plannedRunIds.filter(id=>ids.has(id));return {...value,eligibleRunIds:included,totalRuns:value.plannedRunIds.length,visibleRuns:included.length,partial:included.length>0&&included.length<value.plannedRunIds.length};});
return {eligibleRunIds:[...ids],selectedFilters:{...selected},selectedValues:Object.fromEntries(keys.filter(key=>selected[key]).map(key=>[key,options[key].get(selected[key]).value])),whole:data.whole,visible:counts(eligible),conditionScopes:scopes,filterDataId:data.filter_data_id,scopeRule:data.scope_rule,conditionRule:data.condition_rule};}
function sync(){controls().forEach(control=>control.value=selected[controlKey(control)]);}
function publish(write=false){snapshot=detail();sync();const v=snapshot.visible,w=snapshot.whole;document.getElementById('report-filters-status').textContent=v.runs+' / '+w.runs+' planned runs; '+v.positions+' / '+w.positions+' planned run-case positions; '+v.conditions+' / '+w.conditions+' conditions. Whole-experiment totals remain fixed.';
if(write)writeURL();window.dispatchEvent(new CustomEvent('report-filter-change',{detail:clone(snapshot)}));return clone(snapshot);}
function clearNotice(){notices.textContent='';notices.hidden=true;}
function setFilters(next){if(!next||typeof next!=='object'||Array.isArray(next)||Object.keys(next).some(key=>!keys.includes(key)))throw new TypeError('Unknown report filter key');
Object.entries(next).forEach(([key,id])=>{if(typeof id!=='string'||id&&!options[key].has(id))throw new TypeError('Unknown report filter option');});Object.assign(selected,next);clearNotice();return publish(true);}
function setValue(key,value){if(!keys.includes(key))throw new TypeError('Unknown report filter key');if(value===undefined)return setFilters({[key]:''});const option=data.options[key].find(option=>option.value===value);if(!option)throw new TypeError('Unavailable report filter value');return setFilters({[key]:option.id});}
function refreshAliases(){controls().forEach(control=>{const key=controlKey(control);control.replaceChildren();const all=document.createElement('option');all.value='';all.textContent='All';control.append(all);
data.options[key].forEach(value=>{const option=document.createElement('option');option.value=value.id;option.textContent=value.label;control.append(option);});control.value=selected[key];
if(!bound.has(control)){bound.add(control);control.addEventListener('change',()=>setFilters({[controlKey(control)]:control.value}));}});sync();return clone(snapshot||detail());}
function fromURL(){const url=new URL(window.location.href),part=fragment(url),messages=[];keys.forEach(key=>{const name='rf_'+key,value=part.params.has(name)?part.params.get(name):url.searchParams.get(name);if(value&& !options[key].has(value)){selected[key]='';messages.push('Linked '+data.labels[key]+' filter is unavailable; that dimension is unapplied.');}else selected[key]=value||'';});
notices.textContent=messages.join(' ');notices.hidden=!messages.length;publish(false);}
window.reportFilters={getState:()=>clone(snapshot||detail()),setFilters,setValue,reset:()=>setFilters(Object.fromEntries(keys.map(key=>[key,'']))),
matchesValue:(key,value)=>keys.includes(key)&&(value===undefined?!selected[key]:!!selected[key]&&options[key].get(selected[key]).value===value),
matches:ids=>{const eligible=new Set((snapshot||detail()).eligibleRunIds);return (Array.isArray(ids)?ids:[ids]).some(id=>eligible.has(id));},refreshAliases};
document.getElementById('report-filters-reset').addEventListener('click',()=>window.reportFilters.reset());
window.addEventListener('report-filter-request',()=>publish(false));window.addEventListener('report-filter-set',event=>{if(event.detail&&typeof event.detail==='object')setFilters(event.detail);});
window.addEventListener('hashchange',fromURL);window.addEventListener('popstate',fromURL);refreshAliases();fromURL();
})();</script>"""
