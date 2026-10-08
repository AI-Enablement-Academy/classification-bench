"""An offline case explorer for the deterministic report-analysis schema.

The panel uses the report's existing colour variables. Its JSON is inert and all
evidence reaches the DOM through textContent, including invalid raw predictions.
"""

import json


def _panel_data(analysis):
    """Keep all selectable evidence while avoiding unused pair metadata copies."""
    run_keys = ("run_id", "config_id", "prompt_id", "repeat", "model", "case_ids",
                "counts", "cases", "source_hashes")
    transitions = ("gained_ids", "lost_ids", "stable_correct_ids", "stable_error_ids",
                   "reference_unknown_ids", "unusable_to_valid_ids", "valid_to_unusable_ids",
                   "unusable_both_ids", "net_gain")
    prompt_keys = ("run_a", "run_b", "config_id", "repeat", "prompt_a", "prompt_b", *transitions)
    agreement_keys = ("run_a", "run_b", "planned", "accepted_correct", "accepted_error",
                      "accepted_reference_unknown", "deferred", "accepted_correct_ids",
                      "accepted_error_ids", "accepted_reference_unknown_ids", "deferred_ids")
    take = lambda value, keys: {key: value[key] for key in keys if key in value}
    prompts = []
    for pair in analysis.get("prompt_comparisons", []):
        item = take(pair, prompt_keys)
        item["fields"] = {field: take(values, transitions) for field, values in pair.get("fields", {}).items()}
        prompts.append(item)
    agreements = []
    has_usd_evidence = False
    for pair in analysis.get("agreement_pairs", []):
        item = take(pair, agreement_keys)
        # Monetary values may use 64-bit ledger units. Keep their decimal bytes
        # instead of letting the browser round integers beyond its safe range.
        item["cost"] = {key: str(value) if type(value) is int else value
                        for key, value in pair.get("cost", {}).items()}
        has_usd_evidence = has_usd_evidence or any(pair.get("cost", {}).get(key) is not None
            for key in ("observed_cost_micro_usd", "partial_observed_cost_micro_usd", "unresolved_hold_micro_usd"))
        agreements.append(item)
    return {"schema_version": 1, "analysis_id": analysis.get("analysis_id"),
            "source_hashes": analysis.get("source_hashes"), "task": {"fields": analysis["task"]["fields"]},
            "usd_micro_unit": "micro USD" if has_usd_evidence else None,
            "runs": [take(run, run_keys) for run in analysis.get("runs", [])],
            "prompt_comparisons": prompts,
            "agreement_pairs": agreements}


def render_report_explorer(analysis):
    """Return a self-contained panel for ``report_analysis.build_analysis``.

    Fragment parameters ``run``, ``compareRun`` and ``case`` identify the selection;
    inbound search parameters also work. Other parameters and the heading part of
    the document fragment survive changes, including when opened as local HTML. Hosts
    can select evidence with a ``report-explorer-select`` window event and observe
    a ``report-explorer-change`` event; both use those three parameter names.
    ``caseSearch`` filters case IDs and structured input text without changing
    selected evidence or denominators. ``report-filter-change`` events supply
    ``eligibleRunIds``; exact selected runs/pairs outside that scope are retained.
    """
    if not isinstance(analysis, dict) or analysis.get("schema_version") != 1:
        raise ValueError("report explorer requires analysis schema version 1")
    encoded = json.dumps(_panel_data(analysis), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    encoded = (encoded.replace("&", "\\u0026").replace("<", "\\u003c")
               .replace(">", "\\u003e").replace("\u2028", "\\u2028")
               .replace("\u2029", "\\u2029"))
    return _HTML + "<script type='application/json' id='report-explorer-data'>" + encoded + "</script>" + _SCRIPT


_HTML = """
<style>
.case-explorer{padding:2.4rem 0 3rem;border-top:1px solid var(--line,#dcded8);scroll-margin-top:5rem;color:var(--ink,#222823);font-variant-numeric:tabular-nums}
.case-explorer p{max-width:70ch}.explorer-intro,.explorer-note{color:var(--muted,#59635d)}
.explorer-controls{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;margin:1.4rem 0 .8rem;align-items:end}
.explorer-controls label{display:block;font-size:.8rem;font-weight:650;color:var(--muted,#59635d)}
.explorer-controls select{display:block;width:100%;margin-top:.35rem;padding:.6rem .75rem;border:1px solid #aeb9af;border-radius:3px;background:var(--surface,#fff);color:var(--ink,#222823);font:inherit;min-width:0}
.explorer-actions{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;font-size:.85rem;margin-bottom:1rem}
.explorer-actions button{padding:.5rem .75rem;border:1px solid var(--accent,#245b4b);background:transparent;color:var(--accent,#245b4b);font:inherit;cursor:pointer}
.case-explorer a{color:var(--accent,#245b4b);text-underline-offset:.18em;overflow-wrap:anywhere}.explorer-actions button:hover{background:var(--soft,#e9efe9)}
.explorer-actions button:active{transform:translateY(1px)}.explorer-actions button,.case-explorer a{transition:background-color .18s,color .18s}
.case-explorer :is(a,button,select,input,summary,.explorer-scroll):focus-visible{outline:3px solid var(--accent,#245b4b);outline-offset:3px}
.explorer-actions :is(select,input){margin-left:.4rem;padding:.4rem;border:1px solid #aeb9af;border-radius:3px;background:var(--surface,#fff);color:var(--ink,#222823);font:inherit}.explorer-actions input{width:5rem}.explorer-actions button:disabled{opacity:.5;cursor:default}
.explorer-case-search{display:flex;gap:.75rem;align-items:end;flex-wrap:wrap;margin:1.2rem 0 .5rem}.explorer-case-search label{display:grid;gap:.35rem;font-size:.8rem;font-weight:650;color:var(--muted,#59635d);flex:1;max-width:36rem;min-width:12rem}.explorer-case-search input{width:100%;margin-left:0;min-height:2.7rem;padding:.6rem .75rem;border:1px solid #aeb9af;border-radius:3px;background:var(--surface,#fff);color:var(--ink,#222823);font:inherit}.explorer-case-search button{min-height:2.7rem;margin-bottom:0}.explorer-filter-scope{border-left:3px solid var(--accent,#245b4b);padding-left:.75rem}
.case-explorer [hidden]{display:none!important}.explorer-selection{font-size:.86rem;overflow-wrap:anywhere}.explorer-notice{border-left:3px solid var(--accent,#245b4b);padding-left:.75rem}
.explorer-scroll{overflow-x:auto;max-width:100%;background:var(--surface,#fff);border-top:2px solid var(--ink,#222823);border-bottom:1px solid var(--line,#dcded8);margin:1rem 0 1.5rem}
.explorer-table{border-collapse:collapse;width:100%;min-width:650px;font-size:.85rem}.explorer-table caption{text-align:left;padding:.75rem;font-weight:650;color:var(--muted,#59635d)}
.explorer-table :is(th,td){text-align:left;padding:.65rem .75rem;vertical-align:top;border-bottom:1px solid var(--line,#dcded8);white-space:pre-wrap;overflow-wrap:anywhere}
.explorer-table thead th{font-size:.75rem;font-weight:600;background:#f1f2ed;color:var(--muted,#59635d)}.explorer-table tbody tr:last-child>*{border-bottom:0}
#explorer-agreement-table{min-width:980px}#explorer-prompt-table{min-width:1100px}
.explorer-table tr[aria-current=true]{background:var(--soft,#e9efe9)}.explorer-table .explorer-number{text-align:right;white-space:nowrap}.explorer-table small{display:block;color:var(--muted,#59635d);margin-top:.25rem}
.explorer-detail{border-top:1px solid var(--line,#dcded8);padding-top:1.5rem}.explorer-detail h3{margin:0 0 .7rem}.explorer-evidence{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1.5rem;min-width:0}
.explorer-evidence>div{min-width:0}.case-explorer pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:24rem;overflow:auto;padding:1rem;border:1px solid var(--line,#dcded8);background:#f1f2ed;font-size:.78rem}
.explorer-transitions{margin-top:2rem}.explorer-transitions h3{margin-bottom:.7rem}.explorer-id-list{display:flex;flex-wrap:wrap;gap:.3rem .75rem;margin:.35rem 0;font-size:.8rem}
.explorer-id-list>span{color:var(--muted,#59635d)}.explorer-evidence summary{cursor:pointer;color:var(--accent,#245b4b);font-weight:650}.explorer-note{font-size:.82rem}
@media(max-width:760px){.explorer-controls{grid-template-columns:1fr}.explorer-evidence{grid-template-columns:1fr}.explorer-table{min-width:570px}}
@media(prefers-reduced-motion:reduce){.case-explorer *{transition:none!important;animation:none!important;scroll-behavior:auto}}
</style>
<section class='case-explorer' id='case-explorer' aria-labelledby='case-explorer-heading'>
  <h2 id='case-explorer-heading'>Case explorer</h2>
  <p class='explorer-intro'>Select an exact run and case. Add run B to compare fields, statuses and evidence. Every planned case stays in the denominator.</p>
  <div class='explorer-controls'>
    <label for='explorer-run'>Run A<select id='explorer-run'></select></label>
    <label for='explorer-compare'>Run B<select id='explorer-compare'></select></label>
    <label for='explorer-case'>Case<select id='explorer-case'></select></label>
  </div>
  <div class='explorer-actions'><button type='button' id='explorer-reset'>Reset case selection</button><a id='explorer-permalink' href='#case-explorer-heading'>Link to this selection</a></div>
  <p id='explorer-selection' class='explorer-selection' role='status' aria-live='polite' aria-atomic='true'></p>
  <p id='explorer-notice' class='explorer-note explorer-notice' hidden></p>
  <p id='explorer-filter-scope' class='explorer-note explorer-filter-scope' role='status' aria-live='polite' aria-atomic='true' hidden></p>
  <p id='explorer-empty' class='explorer-notice' hidden>No planned runs are available for this report.</p>
  <div id='explorer-content'>
    <p id='explorer-counts' class='explorer-note'></p>
    <div class='explorer-case-search explorer-actions'><label for='explorer-case-search'>Search case ID or input text<input id='explorer-case-search' type='search' autocomplete='off' aria-describedby='explorer-case-search-help explorer-case-search-count'></label><button id='explorer-case-search-reset' type='button'>Clear case search</button></div>
    <p id='explorer-case-search-help' class='explorer-note'>Search case IDs and structured input keys or values. Predictions and references are excluded. The case chooser retains every planned case.</p>
    <p id='explorer-case-search-count' class='explorer-note' role='status' aria-live='polite' aria-atomic='true'></p>
    <p id='explorer-case-search-empty' class='explorer-note explorer-notice' hidden>No cases match this search. Clear the case search to restore all planned rows. The selected case remains available below.</p>
    <div class='explorer-scroll' tabindex='0' role='region' aria-label='Case search results' aria-labelledby='explorer-case-caption'><table class='explorer-table' id='explorer-case-table'><caption id='explorer-case-caption'>All planned cases in the selected runs</caption><thead><tr><th scope='col'>Case</th><th scope='col'>Run A</th><th scope='col'>Run B</th><th scope='col'>Reference coverage</th><th scope='col'>A/B difference</th></tr></thead><tbody></tbody></table></div>
    <div class='explorer-detail' id='explorer-detail'>
      <h3 id='explorer-case-heading'></h3>
      <p id='explorer-case-status' class='explorer-note'></p>
      <div class='explorer-scroll' tabindex='0' role='region' aria-label='Selected case field comparison'><table class='explorer-table' id='explorer-field-table'><caption>Fields for the selected case</caption><thead><tr><th scope='col'>Field</th><th scope='col'>Reference</th><th scope='col'>Run A</th><th scope='col'>Run B</th><th scope='col'>A/B difference</th><th scope='col'>Reference check</th></tr></thead><tbody></tbody></table></div>
      <div class='explorer-evidence'><div><h4>Input</h4><pre id='explorer-input'></pre></div><div><details><summary>Raw predictions and evidence</summary><pre id='explorer-raw'></pre></details></div></div>
    </div>
    <div class='explorer-transitions'><h3>Prompt gains and losses</h3><p class='explorer-note'>These pairs keep the configuration and repeat fixed. Exact gains and losses require full references. Field rows use the known reference for that field. Missing and invalid results earn no credit; output recovery is counted separately.</p>
      <div class='explorer-actions' role='group' aria-label='Prompt comparison pages'><button type='button' id='explorer-prompt-previous'>Previous prompt page</button><label for='explorer-prompt-page'>Page<input id='explorer-prompt-page' type='number' min='1' value='1'></label><button type='button' id='explorer-prompt-next'>Next prompt page</button><span id='explorer-prompt-page-status' role='status'></span></div><div id='explorer-prompts'></div></div>
    <div class='explorer-transitions'><h3>Agreement and deferral</h3><p class='explorer-note'>Accept when both runs return the same valid fields; defer every other planned case. Accepted cases with an unknown reference remain separate from correct and error counts.</p>
      <div class='explorer-actions'><label for='explorer-agreement-scope'>Pair scope<select id='explorer-agreement-scope'><option value='selection'>Selected A/B, or pairs with run A</option><option value='all'>All eligible pairs</option></select></label></div>
      <div class='explorer-actions' role='group' aria-label='Agreement pair pages'><button type='button' id='explorer-agreement-previous'>Previous pair page</button><label for='explorer-agreement-page'>Page<input id='explorer-agreement-page' type='number' min='1' value='1'></label><button type='button' id='explorer-agreement-next'>Next pair page</button><span id='explorer-agreement-page-status' role='status'></span></div><div id='explorer-agreement'></div></div>
  </div>
  <noscript><p class='explorer-notice'>Enable JavaScript to select cases. The report's static results remain available.</p></noscript>
</section>
"""


_SCRIPT = r"""
<script>
(() => {
  'use strict';
  const source = document.getElementById('report-explorer-data');
  const panel = document.getElementById('case-explorer');
  const data = JSON.parse(source.textContent);
  const runs = data.runs || [];
  const byRun = new Map(runs.map(run => [run.run_id, run]));
  const fields = (data.task.fields || []).map(field => field.name);
  const get = id => document.getElementById(id);
  const runSelect = get('explorer-run');
  const compareSelect = get('explorer-compare');
  const caseSelect = get('explorer-case');
  const caseSearchInput = get('explorer-case-search');
  const notice = get('explorer-notice');
  const element = (tag, value, className) => {
    const node = document.createElement(tag);
    if (value !== undefined && value !== null) node.textContent = String(value);
    if (className) node.className = className;
    return node;
  };
  const label = run => `${run.model || run.config_id} · ${run.config_id} · ${run.prompt_id} · repeat ${run.repeat}`;
  const option = (select, value, name) => {
    const node = element('option', name); node.value = value; select.append(node);
  };
  runs.forEach(run => option(runSelect, run.run_id, label(run)));
  option(compareSelect, '', 'No comparison');
  runs.forEach(run => option(compareSelect, run.run_id, label(run)));
  let state = {run: '', compareRun: '', case: ''};
  let stateNotice = '';
  let caseSearch = '', caseSearchTokens = new Map(), eligibleRunIds = null;
  const internalHashChanges = new Set();
  const pageSize = 12;
  let promptPage = 0, agreementPage = 0, agreementScope = 'selection';
  let promptRendered = false, promptSelectionKey = null, agreementKey = null;
  const casesOf = run => new Map((run && run.cases || []).map(item => [item.case_id, item]));
  const caseIDs = (a, b) => [...new Set([...(a && a.case_ids || []), ...(b && b.case_ids || [])])];
  const normalizeSearch = value => String(value).normalize('NFC').toLowerCase();
  function inputTokens(value) {
    if (value === null) return ['null'];
    if (Array.isArray(value)) return value.flatMap(inputTokens);
    if (typeof value === 'object') return Object.entries(value).flatMap(([key, item]) => [key, ...inputTokens(item)]);
    return value === undefined ? [] : [String(value)];
  }
  const exactSelectedPair = pair => Boolean(state.compareRun &&
    (pair.run_a === state.run && pair.run_b === state.compareRun || pair.run_b === state.run && pair.run_a === state.compareRun));
  function filteredPairs(items) {
    if (eligibleRunIds === null) return {items, eligible:items.length, preserved:0};
    const eligible = items.filter(pair => eligibleRunIds.has(pair.run_a) && eligibleRunIds.has(pair.run_b));
    const preserved = items.filter(pair => exactSelectedPair(pair) && !(eligibleRunIds.has(pair.run_a) && eligibleRunIds.has(pair.run_b)));
    return {items:[...preserved, ...eligible], eligible:eligible.length, preserved:preserved.length};
  }
  function pairFilterNote(projection, total) {
    return eligibleRunIds === null ? '' : ` ${projection.eligible}/${total} pairs satisfy both-run report filters; ${projection.preserved} exact selected pair(s) retained outside scope for evidence inspection.`;
  }
  const agreementScopeKey = () => agreementScope === 'all' ?
    (eligibleRunIds === null ? 'all' : `all|${state.run}|${state.compareRun}`) : `${state.run}|${state.compareRun}`;
  function updateRunScope() {
    const selected = new Set([state.run, state.compareRun]);
    [...runSelect.options].forEach(option => {const excluded = eligibleRunIds !== null && !eligibleRunIds.has(option.value) && !selected.has(option.value); option.hidden = excluded; option.disabled = excluded;});
    [...compareSelect.options].forEach(option => {const excluded = Boolean(option.value && eligibleRunIds !== null && !eligibleRunIds.has(option.value) && !selected.has(option.value)); option.hidden = excluded; option.disabled = excluded || Boolean(option.value && option.value === state.run);});
    const notice = get('explorer-filter-scope'); notice.hidden = eligibleRunIds === null;
    if (eligibleRunIds !== null) {
      const outside = [];
      if (state.run && !eligibleRunIds.has(state.run)) outside.push('run A');
      if (state.compareRun && !eligibleRunIds.has(state.compareRun)) outside.push('run B');
      notice.textContent = `Report filters include ${eligibleRunIds.size}/${runs.length} planned runs. ` +
        (outside.length ? `Selected ${outside.join(' and ')} lies outside this scope and is preserved for exact evidence inspection. ` : '') +
        'Whole experiment totals and planned case denominators remain unchanged.';
    } else notice.textContent = '';
  }
  function applyCaseSearch() {
    const query = normalizeSearch(caseSearch.trim());
    const rows = [...get('explorer-case-table').querySelectorAll('tbody tr')];
    let shown = 0, selectedShown = false;
    rows.forEach(row => {const match = !query || (caseSearchTokens.get(row.dataset.caseId) || []).some(text => text.includes(query)); row.hidden = !match; shown += Number(match); if (row.dataset.caseId === state.case) selectedShown = match;});
    get('explorer-case-search-count').textContent = `${shown}/${rows.length} planned cases shown in the selected run${state.compareRun ? 's' : ''}. ` +
      (query && state.case && !selectedShown ? `Selected case ${state.case} is outside the search; its detail and the full case chooser remain available. ` : '') +
      'Search changes visible rows only; metrics and planned denominators are unchanged.';
    get('explorer-case-search-empty').hidden = !rows.length || shown > 0;
    get('explorer-case-search-reset').disabled = !caseSearch;
    get('explorer-case-caption').textContent = query ? `Matching cases in selected runs (${shown}/${rows.length} planned cases)` : 'All planned cases in the selected runs';
    get('explorer-permalink').href = selectionURL(state).href;
  }
  const has = (object, key) => object !== null && typeof object === 'object' && Object.prototype.hasOwnProperty.call(object, key);
  const valueText = value => typeof value === 'string' ? value : JSON.stringify(value);
  const predictionValue = (item, field) => item && item.prediction_status === 'valid' && has(item.prediction, field) ? valueText(item.prediction[field]) : 'Unavailable';
  const referenceValue = (item, field) => item && has(item.reference, field) ? valueText(item.reference[field]) : 'Unknown';
  const referenceStatus = item => !item || item.reference_status === 'missing' ? 'Unknown' : item.reference_status === 'partial' ? 'Partial' : 'Full';
  const predictionStatus = item => item ? item.prediction_status : 'Outside run';
  const statusText = item => {
    if (!item) return 'Outside run';
    const parts = [item.prediction_status, `lifecycle: ${item.lifecycle_state || 'unknown'}`, `parse: ${item.parsed_status || 'unknown'}`];
    if (item.reason) parts.push(`reason: ${item.reason}`);
    return parts.join('; ');
  };
  const fieldDifference = (a, b, field) => {
    if (!b) return 'No comparison';
    if (!a || a.prediction_status !== 'valid' || b.prediction_status !== 'valid') return 'Not comparable';
    return has(a.prediction, field) && has(b.prediction, field) ? (a.prediction[field] === b.prediction[field] ? 'Same' : 'Changed') : 'Not comparable';
  };
  const caseDifference = (a, b) => {
    if (!state.compareRun) return 'No comparison';
    if (!a || !b) return 'Outside one run';
    if (a.prediction_status !== b.prediction_status) return `${a.prediction_status} → ${b.prediction_status}`;
    if (a.prediction_status !== 'valid') return 'Not comparable';
    const changed = fields.filter(field => fieldDifference(a, b, field) === 'Changed');
    return changed.length ? changed.join(', ') : 'Same valid fields';
  };
  const checkText = (item, field) => {
    if (!item || !has(item.reference, field)) return 'Reference unknown';
    if (item.prediction_status !== 'valid') return 'Prediction unavailable';
    const match = item.field_matches && item.field_matches[field];
    return match === true ? 'Match' : match === false ? 'Mismatch' : 'Unknown';
  };
  function selectionURL(next, clear = false, heading = null) {
    const url = new URL(window.location.href);
    const fragment = url.hash.slice(1).split('?');
    const params = new URLSearchParams(fragment.slice(1).join('?'));
    ['run', 'compareRun', 'case'].forEach(key => {
      // Explicit empty values override old inbound search parameters on reset.
      params.set(key, clear ? '' : next[key] || '');
    });
    params.set('caseSearch', caseSearch);
    url.hash = `${heading || fragment[0] || 'case-explorer-heading'}?${params.toString()}`;
    return url;
  }
  function evidenceLink(id, a = state.run, b = state.compareRun) {
    const next = {run: a, compareRun: b, case: id};
    const url = selectionURL(next, false, 'case-explorer-heading');
    const link = element('a', id); link.href = url.href;
    link.addEventListener('click', event => {
      if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); select(next, true, false, 'case-explorer-heading'); revealCase();
    });
    return link;
  }
  function revealCase() {
    if (!state.case || get('explorer-detail').hidden) return;
    const heading = get('explorer-case-heading');
    heading.focus({preventScroll: true});
    const reducedMotion = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (typeof heading.scrollIntoView === 'function') heading.scrollIntoView({behavior: reducedMotion ? 'auto' : 'smooth', block: 'start'});
  }
  function caseList(ids, a, b) {
    const list = element('div', undefined, 'explorer-id-list');
    if (!ids || !ids.length) list.append(element('span', 'None'));
    else ids.forEach(id => list.append(evidenceLink(id, a, b)));
    return list;
  }
  function countText(run, prefix) {
    const counts = run.counts || {};
    let text = `${prefix}: ${counts.planned || 0} planned; ${counts.valid || 0} valid; ${counts.invalid || 0} invalid; ${counts.missing || 0} missing. References: ${counts.full_reference || 0} full, ${counts.partial_reference || 0} partial, ${counts.no_reference || 0} unknown.`;
    if (counts.full_reference > 0 && typeof counts.exact_correct === 'number') text += ` Exact matches: ${counts.exact_correct} of ${counts.full_reference} fully referenced cases.`;
    else text += ' Exact match quality is unavailable without full references.';
    return text;
  }
  function cell(row, value, header = false) {
    const node = element(header ? 'th' : 'td', value);
    if (header) node.scope = 'row'; row.append(node); return node;
  }
  function makeTable(caption, headers, id) {
    const wrap = element('div', undefined, 'explorer-scroll');
    wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', caption);
    const table = element('table', undefined, 'explorer-table'); table.id = id;
    table.append(element('caption', caption));
    const head = element('thead'), row = element('tr');
    headers.forEach(name => { const th = element('th', name); th.scope = 'col'; row.append(th); });
    head.append(row); table.append(head); const body = element('tbody'); table.append(body); wrap.append(table);
    return {wrap, body};
  }
  function pageSlice(items, requested, prefix, scope) {
    const pages = Math.max(1, Math.ceil(items.length / pageSize));
    const page = Math.max(0, Math.min(Number.isFinite(requested) ? Math.trunc(requested) : 0, pages - 1));
    get(`explorer-${prefix}-previous`).disabled = page === 0;
    get(`explorer-${prefix}-next`).disabled = page === pages - 1;
    const input = get(`explorer-${prefix}-page`); input.value = page + 1; input.max = pages; input.disabled = !items.length;
    const start = page * pageSize, end = Math.min(start + pageSize, items.length);
    get(`explorer-${prefix}-page-status`).textContent = `Page ${page + 1} of ${pages}; showing ${items.length ? start + 1 : 0}–${end} of ${items.length}. ${scope}`;
    return {page, items: items.slice(start, end)};
  }
  function renderPromptPairs() {
    const promptPanel = get('explorer-prompts'); promptPanel.replaceChildren();
    const allComparisons = data.prompt_comparisons || [], projection = filteredPairs(allComparisons), comparisons = projection.items;
    const page = pageSlice(comparisons, promptPage, 'prompt', `${allComparisons.length} paired prompt conditions available in the full report; all planned cases remain in each pair.` + pairFilterNote(projection, allComparisons.length));
    promptPage = page.page;
    if (!comparisons.length) promptPanel.append(element('p', allComparisons.length ? 'No paired prompt conditions match both-run report filters. Clear the report filters to restore the full comparison scope.' : 'No paired prompt conditions are available.', 'explorer-note'));
    else {
      const {wrap, body} = makeTable(eligibleRunIds === null ? 'All paired prompt conditions' : 'Report-filtered prompt conditions; exact selected A/B evidence is retained outside scope', ['Runs', 'Gains', 'Losses', 'Net gain on known references', 'Reference unknown', 'Output recovery', 'Stable credit', 'Unusable in both'], 'explorer-prompt-table');
      page.items.forEach(pair => {
        const row = element('tr');
        const outside = eligibleRunIds !== null && !(eligibleRunIds.has(pair.run_a) && eligibleRunIds.has(pair.run_b));
        cell(row, `${pair.config_id} · repeat ${pair.repeat}\n${pair.prompt_a} → ${pair.prompt_b}` + (outside ? '\nExact selected pair outside report filters; retained as evidence.' : ''), true);
        [['gained_ids', 'Gained'], ['lost_ids', 'Lost']].forEach(([key, name]) => {
          const td = cell(row, `${(pair[key] || []).length} ${name.toLowerCase()}`); td.append(caseList(pair[key], pair.run_a, pair.run_b));
        });
        cell(row, pair.net_gain === null || pair.net_gain === undefined ? 'Unknown' : pair.net_gain);
        const unknown = cell(row, `${(pair.reference_unknown_ids || []).length}`); unknown.append(caseList(pair.reference_unknown_ids, pair.run_a, pair.run_b));
        const recovery = cell(row, `${(pair.unusable_to_valid_ids || []).length} unusable → valid; ${(pair.valid_to_unusable_ids || []).length} valid → unusable`);
        recovery.append(caseList(pair.unusable_to_valid_ids, pair.run_a, pair.run_b), caseList(pair.valid_to_unusable_ids, pair.run_a, pair.run_b));
        const stable = cell(row, `${(pair.stable_correct_ids || []).length} correct; ${(pair.stable_error_ids || []).length} zero credit`);
        stable.append(caseList(pair.stable_correct_ids, pair.run_a, pair.run_b), caseList(pair.stable_error_ids, pair.run_a, pair.run_b));
        const unusable = cell(row, `${(pair.unusable_both_ids || []).length}`); unusable.append(caseList(pair.unusable_both_ids, pair.run_a, pair.run_b));
        body.append(row);
        Object.entries(pair.fields || {}).forEach(([field, values]) => {
          const detail = element('tr'); cell(detail, `Field: ${field}`, true);
          ['gained_ids', 'lost_ids'].forEach(key => { const td = cell(detail, `${(values[key] || []).length}`); td.append(caseList(values[key], pair.run_a, pair.run_b)); });
          cell(detail, values.net_gain === null || values.net_gain === undefined ? 'Unknown' : values.net_gain); const td = cell(detail, `${(values.reference_unknown_ids || []).length}`); td.append(caseList(values.reference_unknown_ids, pair.run_a, pair.run_b));
          cell(detail, `${(values.unusable_to_valid_ids || []).length} unusable → valid; ${(values.valid_to_unusable_ids || []).length} valid → unusable`);
          const stable = cell(detail, `${(values.stable_correct_ids || []).length} correct; ${(values.stable_error_ids || []).length} zero credit`);
          stable.append(caseList(values.stable_correct_ids, pair.run_a, pair.run_b), caseList(values.stable_error_ids, pair.run_a, pair.run_b));
          const unusable = cell(detail, `${(values.unusable_both_ids || []).length}`); unusable.append(caseList(values.unusable_both_ids, pair.run_a, pair.run_b)); body.append(detail);
        });
      });
      promptPanel.append(wrap);
    }
  }
  function renderAgreementPairs() {
    const agreementPanel = get('explorer-agreement'); agreementPanel.replaceChildren();
    const allPairs = data.agreement_pairs || [];
    const projection = filteredPairs(allPairs);
    const pairs = agreementScope === 'all' ? projection.items : projection.items.filter(pair => state.compareRun ?
      (pair.run_a === state.run && pair.run_b === state.compareRun || pair.run_b === state.run && pair.run_a === state.compareRun) :
      pair.run_a === state.run || pair.run_b === state.run);
    const scope = agreementScope === 'all' ? 'All eligible pairs.' : state.compareRun ? 'Selected A/B pair.' : 'Pairs containing run A.';
    const page = pageSlice(pairs, agreementPage, 'agreement', `${scope} ${allPairs.length} eligible pairs available in this report; all planned cases remain in each pair.` + pairFilterNote(projection, allPairs.length));
    agreementPage = page.page;
    if (!pairs.length) agreementPanel.append(element('p', allPairs.length ? 'No eligible agreement pair matches this selection and report filter scope. Select all eligible pairs or clear report filters to inspect other runs.' : 'No eligible agreement pairs are available.', 'explorer-note'));
    else {
      const {wrap, body} = makeTable('Eligible agreement pairs in the stated scope and page', ['Runs', 'Planned', 'Accepted correct', 'Accepted error', 'Accepted reference unknown', 'Deferred', 'Cost and source scope'], 'explorer-agreement-table');
      page.items.forEach(pair => {
        const row = element('tr');
        const a = byRun.get(pair.run_a), b = byRun.get(pair.run_b);
        const outside = eligibleRunIds !== null && !(eligibleRunIds.has(pair.run_a) && eligibleRunIds.has(pair.run_b));
        cell(row, `${a ? label(a) : pair.run_a}\n${b ? label(b) : pair.run_b}` + (outside ? '\nExact selected pair outside report filters; retained as evidence.' : ''), true); cell(row, pair.planned);
        ['accepted_correct', 'accepted_error', 'accepted_reference_unknown', 'deferred'].forEach(key => {
          const td = cell(row, pair[key]); td.append(caseList(pair[`${key}_ids`], pair.run_a, pair.run_b));
        });
        cell(row, undefined).append(costDisclosure(pair, a, b));
        body.append(row);
      });
      agreementPanel.append(wrap);
    }
  }
  function usdText(value) {
    if (value === null || value === undefined || !/^\d+$/.test(String(value))) return 'Unavailable';
    const digits = String(value).padStart(7, '0');
    return `${digits.slice(0, -6)}.${digits.slice(-6)} USD (${value} ${data.usd_micro_unit || 'ledger units'})`;
  }
  function knownText(value) { return value === null || value === undefined ? 'Unavailable' : String(value); }
  function costDisclosure(pair, a, b) {
    const cost = pair.cost || {}, details = element('details');
    details.append(element('summary', `USD coverage: ${knownText(cost.observed_cost_requests)}/${knownText(cost.planned_requests)} requests`));
    const total = cost.complete === true ? usdText(cost.observed_cost_micro_usd) : 'Unavailable: incomplete USD coverage';
    details.append(element('p', `Two-run USD total: ${total}. Partial observed USD: ${usdText(cost.partial_observed_cost_micro_usd)}. Unresolved USD holds: ${usdText(cost.unresolved_hold_micro_usd)}.`, 'explorer-note'));
    details.append(element('p', `Subscription invocations: ${knownText(cost.subscription_invocations)}. Unresolved subscription invocations: ${knownText(cost.unresolved_subscription_invocations)}. Synthetic requests excluded from USD: ${knownText(cost.synthetic_excluded_requests)}. Subscription usage does not establish dollar charges.`, 'explorer-note'));
    details.append(element('p', `Scope: ${cost.scope || 'These two selected runs only; other runs and human review are excluded.'} ${cost.limitation || 'Retrospective agreement counts do not establish deployment gains.'}`, 'explorer-note'));
    details.append(element('pre', JSON.stringify({run_a: pair.run_a, run_b: pair.run_b,
      source_hashes_a: a && a.source_hashes, source_hashes_b: b && b.source_hashes,
      verification: 'Supplied source metadata; not independently verified by the panel.'}, null, 2)));
    return details;
  }
  function render() {
    const a = byRun.get(state.run), b = byRun.get(state.compareRun);
    runSelect.value = state.run; compareSelect.value = state.compareRun;
    [...compareSelect.options].forEach(option => { option.disabled = Boolean(option.value && option.value === state.run); });
    caseSelect.replaceChildren(); caseIDs(a, b).forEach(id => option(caseSelect, id, id)); caseSelect.value = state.case;
    const empty = !a; get('explorer-empty').hidden = !empty; get('explorer-content').hidden = empty;
    [runSelect, compareSelect, caseSelect].forEach(select => { select.disabled = empty || !select.options.length; });
    caseSearchInput.disabled = empty;
    updateRunScope();
    get('explorer-reset').disabled = empty;
    get('explorer-selection').textContent = empty ? 'No run selected.' : `Run A: ${label(a)}${b ? `; run B: ${label(b)}` : ''}; case: ${state.case || 'none planned'}.`;
    notice.textContent = stateNotice; notice.hidden = !stateNotice;
    get('explorer-permalink').href = selectionURL(state).href;
    if (!a) {caseSearchTokens = new Map(); applyCaseSearch(); return;}
    get('explorer-counts').textContent = countText(a, 'Run A') + (b ? '\n' + countText(b, 'Run B') : '');
    const aCases = casesOf(a), bCases = casesOf(b), body = get('explorer-case-table').querySelector('tbody'); body.replaceChildren();
    caseSearchTokens = new Map();
    caseIDs(a, b).forEach(id => {
      const ca = aCases.get(id), cb = bCases.get(id), row = element('tr');
      caseSearchTokens.set(id, [id, ...inputTokens(ca && ca.input), ...inputTokens(cb && cb.input)].map(normalizeSearch));
      row.dataset.caseId = id; row.setAttribute('aria-current', String(id === state.case));
      cell(row, undefined, true).append(evidenceLink(id)); cell(row, statusText(ca)); cell(row, b ? statusText(cb) : 'No comparison');
      cell(row, referenceStatus(ca || cb)); cell(row, caseDifference(ca, cb)); body.append(row);
    });
    applyCaseSearch();
    const ca = aCases.get(state.case), cb = bCases.get(state.case);
    get('explorer-detail').hidden = !state.case;
    get('explorer-case-heading').textContent = `Case ${state.case}`; get('explorer-case-heading').tabIndex = -1;
    get('explorer-case-status').textContent = `Run A: ${statusText(ca)}${b ? `\nRun B: ${statusText(cb)}` : ''}\nReference: ${referenceStatus(ca || cb)}.`;
    const fieldBody = get('explorer-field-table').querySelector('tbody'); fieldBody.replaceChildren();
    fields.forEach(field => {
      const row = element('tr'); row.dataset.field = field; cell(row, field, true);
      cell(row, referenceValue(ca || cb, field)); cell(row, predictionValue(ca, field)); cell(row, b ? predictionValue(cb, field) : 'No comparison');
      cell(row, fieldDifference(ca, cb, field)); cell(row, `A: ${checkText(ca, field)}${b ? `; B: ${checkText(cb, field)}` : ''}`); fieldBody.append(row);
    });
    get('explorer-input').textContent = JSON.stringify((ca || cb || {}).input || {}, null, 2);
    get('explorer-raw').textContent = JSON.stringify({
      run_a: ca ? {run_id: a.run_id, source_hashes: a.source_hashes, request_id: ca.request_id, prediction: ca.prediction, raw_prediction: ca.raw_prediction, evidence: ca.evidence} : null,
      run_b: cb ? {run_id: b.run_id, source_hashes: b.source_hashes, request_id: cb.request_id, prediction: cb.prediction, raw_prediction: cb.raw_prediction, evidence: cb.evidence} : null
    }, null, 2);
    const selectionKey = eligibleRunIds === null ? 'all' : `${state.run}|${state.compareRun}`;
    if (!promptRendered || selectionKey !== promptSelectionKey) {promptPage = 0; renderPromptPairs(); promptRendered = true; promptSelectionKey = selectionKey;}
    const key = agreementScopeKey();
    if (key !== agreementKey) { agreementPage = 0; renderAgreementPairs(); agreementKey = key; }
    window.dispatchEvent(new CustomEvent('report-explorer-change', {detail: {...state}}));
  }
  function select(requested, writeURL, clear = false, heading = null) {
    stateNotice = '';
    const fallback = runs[0] && runs[0].run_id || '';
    const run = byRun.has(requested.run) ? requested.run : fallback;
    if (requested.run && !byRun.has(requested.run)) stateNotice = 'The linked run is unavailable. Showing the first planned run.';
    let compareRun = byRun.has(requested.compareRun) ? requested.compareRun : '';
    if (requested.compareRun && !compareRun) stateNotice += ' The linked comparison run is unavailable.';
    if (compareRun && compareRun === run) { compareRun = ''; stateNotice += ' Run B must differ from run A.'; }
    const ids = caseIDs(byRun.get(run), byRun.get(compareRun));
    const caseID = ids.includes(requested.case) ? requested.case : ids[0] || '';
    if (requested.case && !ids.includes(requested.case)) stateNotice += ' The linked case is unavailable. Showing the first planned case.';
    state = {run, compareRun, case: caseID};
    if (writeURL) {
      const url = selectionURL(state, clear, heading);
      writeSelectionURL(url);
    }
    render();
  }
  function fromURL() {
    const url = new URL(window.location.href);
    const params = new URLSearchParams(url.hash.slice(1).split('?').slice(1).join('?'));
    const fragmentSelection = ['run', 'compareRun', 'case'].some(key => params.has(key));
    const value = key => fragmentSelection ? params.get(key) : url.searchParams.get(key);
    caseSearch = (params.has('caseSearch') ? params.get('caseSearch') : url.searchParams.get('caseSearch')) || '';
    if (caseSearchInput.value !== caseSearch) caseSearchInput.value = caseSearch;
    select({run: value('run'), compareRun: value('compareRun'), case: value('case')}, false);
  }
  function writeSelectionURL(url) {
    try {window.history.replaceState(null, '', url.href);}
    catch (_) {if (window.location.hash !== url.hash) internalHashChanges.add(url.href); window.location.hash = url.hash;}
  }
  caseSearchInput.addEventListener('input', () => {caseSearch = caseSearchInput.value; applyCaseSearch(); writeSelectionURL(selectionURL(state));});
  get('explorer-case-search-reset').addEventListener('click', () => {caseSearch = ''; caseSearchInput.value = ''; applyCaseSearch(); writeSelectionURL(selectionURL(state)); caseSearchInput.focus();});
  runSelect.addEventListener('change', () => select({...state, run: runSelect.value}, true));
  compareSelect.addEventListener('change', () => select({...state, compareRun: compareSelect.value}, true));
  caseSelect.addEventListener('change', () => select({...state, case: caseSelect.value}, true));
  get('explorer-reset').addEventListener('click', () => select({}, true, true));
  function listenPages(prefix, update) {
    get(`explorer-${prefix}-previous`).addEventListener('click', () => update(-1));
    get(`explorer-${prefix}-next`).addEventListener('click', () => update(1));
    get(`explorer-${prefix}-page`).addEventListener('change', () => update(null, Number(get(`explorer-${prefix}-page`).value) - 1));
  }
  listenPages('prompt', (delta, page) => { promptPage = delta === null ? page : promptPage + delta; renderPromptPairs(); });
  listenPages('agreement', (delta, page) => { agreementPage = delta === null ? page : agreementPage + delta; renderAgreementPairs(); });
  get('explorer-agreement-scope').addEventListener('change', () => {
    agreementScope = get('explorer-agreement-scope').value; agreementPage = 0;
    agreementKey = agreementScopeKey();
    renderAgreementPairs();
  });
  window.addEventListener('popstate', fromURL);
  window.addEventListener('hashchange', event => {
    const internal = internalHashChanges.delete(event.newURL || window.location.href);
    fromURL();
    const url = new URL(window.location.href);
    const fragment = url.hash.slice(1).split('?');
    if (!internal && fragment[0] === 'case-explorer-heading' && new URLSearchParams(fragment.slice(1).join('?')).has('case')) revealCase();
  });
  window.addEventListener('report-explorer-select', event => select(event.detail || {}, true));
  function applyReportFilters(detail) {
    const requested = detail && detail.eligibleRunIds;
    if (!Array.isArray(requested) || requested.some(id => typeof id !== 'string')) return;
    let next = new Set(requested.filter(id => byRun.has(id)));
    if (next.size === runs.length) next = null;
    if (next === null && eligibleRunIds === null || next !== null && eligibleRunIds !== null && next.size === eligibleRunIds.size && [...next].every(id => eligibleRunIds.has(id))) return;
    eligibleRunIds = next; promptPage = 0; agreementPage = 0;
    updateRunScope(); renderPromptPairs(); promptRendered = true;
    promptSelectionKey = eligibleRunIds === null ? 'all' : `${state.run}|${state.compareRun}`;
    renderAgreementPairs(); agreementKey = agreementScopeKey();
  }
  window.addEventListener('report-filter-change', event => applyReportFilters(event.detail));
  fromURL();
  if (window.reportFilters && typeof window.reportFilters.getState === 'function') applyReportFilters(window.reportFilters.getState());
  else window.dispatchEvent(new CustomEvent('report-filter-request'));
})();
</script>
"""
