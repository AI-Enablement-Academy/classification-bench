"""Shared filters preserve report scope and exact evidence navigation."""

import shutil
import subprocess
import unittest

from classification_bench.report import generate_report
import tests.test_report_ux as report_fixture


class SharedReportWorkflowTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required for offline DOM behavior")
    def test_shared_filters_aliases_scope_url_and_case_evidence(self):
        if subprocess.run(["node", "-e", "require.resolve('jsdom')"], capture_output=True).returncode:
            self.skipTest("jsdom unavailable")
        fixture = report_fixture.ReportUxTests()
        fixture.setUp()
        html = generate_report(fixture.task, fixture.plan, fixture.labels,
                               fixture.predictions, fixture.operations)
        script = r"""
const assert = require('assert');
const {JSDOM, VirtualConsole} = require('jsdom');
(async()=>{
const errors = []; const vc = new VirtualConsole(); vc.on('jsdomError', error => errors.push(error.message));
const dom = new JSDOM(require('fs').readFileSync(0,'utf8'), {runScripts:'dangerously', url:'file:///report.html#comparison-heading?keep=yes', virtualConsole:vc});
const w=dom.window, d=w.document, f=w.reportFilters;
const visible = selector => [...d.querySelectorAll(selector)].filter(node => !node.hidden);
const totals = d.querySelector('.summary-section').textContent;
const full=f.getState(); assert.equal(full.eligibleRunIds.length,8);
f.setValue('prompt','careful');
assert.equal(visible('.pass').length,4); assert.equal(visible('.comparison-table tbody tr').length,2);
for(const select of d.querySelectorAll('[data-report-filter=prompt]')) assert.equal(select.selectedOptions[0].textContent,'careful');
f.setValue('repeat','1');
assert.equal(visible('.pass').length,2); assert.equal(visible('.comparison-table tbody tr').length,2);
assert(visible('.comparison-table tbody tr').every(row => row.querySelector('.condition-filter-scope').textContent.includes('1/2')));
assert.equal(d.querySelector('.summary-section').textContent,totals);
assert(w.location.hash.includes('keep=yes')); assert(w.location.hash.includes('rf_prompt='));
const id = d.getElementById('explorer-run').value;
w.dispatchEvent(new w.CustomEvent('report-explorer-select',{detail:{run:id,case:d.getElementById('explorer-case').value}}));
assert.equal(d.getElementById('explorer-run').value,id);
assert.equal(f.getState().eligibleRunIds.length,2);
d.querySelector('.jump-nav a[href="#case-explorer-heading"]').click();
await new Promise(resolve=>setTimeout(resolve,50));
assert.equal(f.getState().eligibleRunIds.length,2);
assert.equal(d.getElementById('explorer-run').value,id);
assert(w.location.hash.includes('keep=yes'));
const beforeLink = new w.URLSearchParams(w.location.hash.split('?')[1]); beforeLink.set('compareRun',full.eligibleRunIds[7]);
w.location.hash='#case-explorer-heading?'+beforeLink.toString();
await new Promise(resolve=>setTimeout(resolve,50));
const evidence=[...d.querySelectorAll('.finding:not([hidden]) a[href^="#case-explorer-heading?"]')].find(link=>!link.getAttribute('href').includes('compareRun='));
assert(evidence); evidence.click();
await new Promise(resolve=>setTimeout(resolve,50));
assert.equal(f.getState().eligibleRunIds.length,2);
assert.equal(new w.URLSearchParams(w.location.hash.split('?')[1]).get('compareRun'),'');
const selectedAfterEvidence=d.getElementById('explorer-run').value;
const reload = new JSDOM(dom.serialize(), {runScripts:'dangerously', url:w.location.href, virtualConsole:vc});
assert.equal(reload.window.reportFilters.getState().eligibleRunIds.length,2);
assert.equal(reload.window.document.getElementById('explorer-run').value,selectedAfterEvidence);
d.getElementById('reset-filters').click();
assert.equal(visible('.pass').length,8); assert.equal(visible('.comparison-table tbody tr').length,4);
assert.equal(d.querySelector('.summary-section').textContent,totals);
assert(w.location.hash.includes('keep=yes')); assert.equal(new w.URLSearchParams(w.location.hash.split('?')[1]).get('rf_prompt'),'');
const pdata=JSON.parse(d.getElementById('presentation-data').textContent);
const controlled=pdata.findings.find(item=>item.kind==='controlled_configuration_overview');
assert(controlled && controlled.supporting_links.length===2);
const findingSelect=d.getElementById('presentation-finding-select');
findingSelect.value=controlled.finding_id; findingSelect.dispatchEvent(new w.Event('change'));
const links=[...d.querySelectorAll('.presentation-supporting-links a')];
assert.equal(links.length,2);
for(let i=0;i<2;i++) { const params=new w.URLSearchParams(new w.URL(links[i].href).hash.split('?')[1]);
  assert.equal(params.get('run'),controlled.supporting_links[i].run_a);
  assert.equal(params.get('compareRun'),controlled.supporting_links[i].run_b); }
assert.deepEqual(errors,[]); reload.window.close(); w.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(["node", "-e", script], input=html, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr[-5000:])


if __name__ == "__main__":
    unittest.main()
