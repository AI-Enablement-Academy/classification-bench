"""Self-contained workflow report with independent, evidence-backed phase views."""

from collections import Counter
from html import escape
import json

from . import benchmark
from .core import evaluate, validate_reference_labels
from .report import generate_report, _observed_outcome


def generate_workflow_report(snapshot, labels=None, *, allow_partial_references=False,
                             scenarios=None, cohort_declarations=None, repeat_origins=None):
    manifest = snapshot["manifest"]
    source, _ = benchmark._load_json(manifest["sources"]["inputs"]["path"])
    task = next(iter(snapshot["phases"].values()))["task"]
    # References are checked against all original inputs before projection. An
    # unknown ID outside the selected phase must not disappear silently.
    reference = validate_reference_labels(labels, task, [row["id"] for row in source["records"]],
                                          allow_partial=allow_partial_references)
    documents, summaries = {}, {}
    for name, phase in snapshot["phases"].items():
        selected = manifest["phases"][name]["ids"]
        projected = None if labels is None else {"records": [
            {"id": rid, "labels": reference[rid]} for rid in selected if rid in reference]}
        documents[name] = generate_report(phase["task"], phase["plan"], projected,
                                          phase["predictions"], phase["operations"],
                                          allow_partial_references=allow_partial_references,
                                          scenarios=scenarios, cohort_declarations=cohort_declarations,
                                          repeat_origins=repeat_origins)
        provenance = ("<aside aria-label='Workflow provenance' style='padding:12px 24px;border-bottom:1px solid #dcded8;overflow-wrap:anywhere'>"
                      f"<strong>{escape(manifest['name'])} / {escape(name.capitalize())}</strong>"
                      "<details><summary>Workflow and phase identity</summary>"
                      f"<p>Workflow SHA-256: <code>{escape(manifest['workflow_sha256'])}</code></p>"
                      f"<p>Phase plan SHA-256: <code>{escape(manifest['phases'][name]['plan_sha256'])}</code></p>"
                      "<p>Metrics and findings apply to this phase. Identical cases scheduled in another phase are separate work.</p>"
                      "</details></aside>")
        documents[name] = documents[name].replace("<body>", "<body>" + provenance, 1)
        scored = evaluate(phase["task"], phase["plan"], projected, phase["predictions"],
                          allow_partial_references=allow_partial_references)
        invalid = {(row["config_id"], row["prompt_id"], row["repeat"], row["id"]) for row in scored["invalid"]}
        supplied = {(row["config_id"], row["prompt_id"], row["repeat"], row["id"]): row["prediction"]
                    for row in phase["predictions"]["records"]}
        operations = {row["request_id"]: row for row in phase["operations"]}
        outcomes = Counter(_observed_outcome((req["config_id"], req["prompt_id"], req["repeat"], item["id"]),
                                            invalid, supplied, operations.get(req["request_id"]))
                           for req in phase["plan"]["requests"] for item in req["items"])
        summaries[name] = {"requests": len(phase["plan"]["requests"]), "positions": scored["positions"],
                           "outcomes": dict(outcomes)}
    # Explicit single-phase output remains an ordinary standalone report.
    if len(documents) == 1:
        return next(iter(documents.values()))
    totals = Counter()
    for summary in summaries.values():
        totals.update(summary["outcomes"])
    positions = sum(value["positions"] for value in summaries.values())
    requests = sum(value["requests"] for value in summaries.values())
    h = lambda value: escape(str(value), quote=True)
    options = "".join(f'<option value="{h(name)}">{h(name.capitalize())} · '
                      f'{summary["positions"]:,} planned outputs</option>' for name, summary in summaries.items())
    outcome_text = " · ".join(f'{h(name.replace("_", " "))}: {count:,}' for name, count in sorted(totals.items()))
    payload = json.dumps({"documents": documents, "summaries": summaries}, ensure_ascii=False).replace("<", "\\u003c")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{h(manifest['name'])} · Workflow report</title>
<style>
:root{{color-scheme:light;--ink:#183934;--paper:#f5f3ec;--line:#c8d2c9;--accent:#16634d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 'Avenir Next',Avenir,sans-serif}}
.workflow-bar{{padding:18px clamp(16px,3vw,44px);border-bottom:1px solid var(--line)}}
.eyebrow{{font-size:11px;letter-spacing:.13em;text-transform:uppercase;margin:0 0 4px}}
h1{{font:500 clamp(22px,2.3vw,34px)/1.15 Georgia,serif;margin:0}}p{{margin:7px 0}}
.top{{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap}}
.controls{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}select,a{{font:inherit;color:var(--ink)}}
select{{padding:10px;background:#fff;border:1px solid var(--line);border-radius:5px;max-width:100%}}
a{{text-underline-offset:4px}}:focus-visible{{outline:3px solid var(--accent);outline-offset:4px}}
details{{font-size:13px}}summary{{cursor:pointer}}code{{overflow-wrap:anywhere}}
iframe{{width:100%;height:calc(100dvh - 190px);min-height:540px;display:block;border:0;background:white}}
.skip{{position:absolute;left:16px;top:-100px;background:white;padding:10px;z-index:2}}.skip:focus{{top:8px}}
@media(max-width:640px){{.workflow-bar{{padding:16px}}.controls{{width:100%}}iframe{{height:75dvh;min-height:500px}}}}
@media print{{iframe{{display:none}}.controls{{display:none}}.print-note{{display:block!important}}}}
</style></head><body><a class="skip" href="#phase-report">Skip to selected phase report</a>
<header class="workflow-bar"><div class="top"><div><p class="eyebrow">Private local classification workflow</p>
<h1>{h(manifest['name'])}</h1></div><div class="controls"><label for="phase">Report phase</label>
<select id="phase">{options}</select><a id="standalone" download="phase-report.html">Download selected phase</a></div></div>
<p><strong>{positions:,} planned outputs · {requests:,} requests</strong> across smoke and full.</p>
<details><summary>Whole-workflow outcomes and scope</summary><p>{outcome_text}</p>
<p>These totals count scheduled outputs, including repeated cases. Accuracy, comparisons, filters and findings belong to the selected phase. Smoke and full may use different inputs or repeats.</p>
<p>Workflow identity: <code>{h(manifest['workflow_sha256'])}</code></p></details>
<p class="print-note" style="display:none">Download the selected phase and print its standalone report for complete findings.</p>
<noscript>This workflow selector needs JavaScript. Generate a standalone phase with report --workflow ... --phase smoke or full.</noscript></header>
<iframe id="phase-report" title="Smoke phase: detailed classification report" sandbox="allow-scripts allow-downloads allow-popups allow-popups-to-escape-sandbox"></iframe>
<script id="workflow-data" type="application/json">{payload}</script>
<script>
(()=>{{'use strict';const data=JSON.parse(document.getElementById('workflow-data').textContent);
const select=document.getElementById('phase'),frame=document.getElementById('phase-report'),link=document.getElementById('standalone');let url=null,current=null;
function bridge(phase,outer,initial){{
  if(initial)window.location.hash=initial;
  const address=fragment=>outer+'#'+phase+(fragment?'/'+encodeURIComponent(fragment.replace(/^#/,'')):'');
  const authored=new WeakMap();
  function links(){{document.querySelectorAll('a[href]').forEach(a=>{{if(a.getAttribute('href').startsWith('about:srcdoc#')){{
    const previous=authored.get(a);authored.set(a,{{href:a.getAttribute('href'),target:previous?previous.target:a.getAttribute('target')}});
    a.href=address(a.getAttribute('href').slice('about:srcdoc'.length));a.target='_blank';a.rel='noopener';}}}});}}
  // Authored report handlers parse their own fragments. Keep those exact inputs
  // for ordinary clicks, while copied links and modified clicks stay portable.
  document.addEventListener('click',event=>{{const a=event.target.closest('a[href]'),saved=a&&authored.get(a);
    if(!saved||event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
    a.setAttribute('href',saved.href);if(saved.target===null)a.removeAttribute('target');else a.setAttribute('target',saved.target);
    queueMicrotask(links);
  }},true);
  function publish(){{window.parent.postMessage({{type:'classification-workflow-state',phase,fragment:window.location.hash}},'*');links();}}
  const replace=window.history.replaceState.bind(window.history);
  window.history.replaceState=function(...args){{const result=replace(...args);queueMicrotask(publish);return result;}};
  window.addEventListener('hashchange',publish);
  window.addEventListener('DOMContentLoaded',()=>{{new MutationObserver(links).observe(document.body,{{subtree:true,childList:true,attributes:true,attributeFilter:['href']}});publish();}});
}}
function route(){{const raw=location.hash.slice(1),slash=raw.indexOf('/'),name=slash<0?raw:raw.slice(0,slash);let fragment='';
try{{fragment=slash<0?'':decodeURIComponent(raw.slice(slash+1));}}catch(_){{return null;}}
return Object.hasOwn(data.documents,name)?{{name,fragment}}:null;}}
function show(initial=false){{const target=route();if(!target&&!initial)return;const name=target?target.name:Object.keys(data.documents)[0],fragment=target?target.fragment:'';
current=name;select.value=name;frame.title=name.charAt(0).toUpperCase()+name.slice(1)+' phase: detailed classification report';
const args=[name,location.href.split('#')[0],fragment].map(v=>JSON.stringify(v).split('<').join(String.fromCharCode(92)+'u003c')).join(',');
const injected='<scr'+'ipt>('+bridge.toString()+')('+args+');</scr'+'ipt>';
frame.srcdoc=data.documents[name].replace(/<head>/i,()=>'<head>'+injected);
if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(new Blob([data.documents[name]],{{type:'text/html;charset=utf-8'}}));link.href=url;link.download=name+'-report.html';}}
window.addEventListener('message',event=>{{const value=event.data;if(event.source!==frame.contentWindow||!value||value.type!=='classification-workflow-state'||value.phase!==current||typeof value.fragment!=='string'||value.fragment&&value.fragment[0]!=='#')return;
const hash='#'+current+(value.fragment?'/'+encodeURIComponent(value.fragment.slice(1)):'');try{{history.replaceState(null,'',hash);}}catch(_){{/* Local URL restrictions do not change report evidence. */}}}});
select.addEventListener('change',()=>{{location.hash=select.value;}});window.addEventListener('hashchange',()=>show());show(true);
}})();</script></body></html>'''
