"""Offline DOM interaction check for the self-contained report.

This uses local jsdom when available. It does not render a browser or verify layout.
"""

import shutil
import subprocess
import unittest

from classification_bench.core import build_plan
from classification_bench.report import generate_report
import tests.test_report_ux as report_fixture


_CHECK = r"""
const fs = require('fs');
const assert = require('assert');
const { JSDOM } = require('jsdom');
const html = fs.readFileSync(0, 'utf8');
const plain = new JSDOM(html, {runScripts: 'dangerously', url: 'file:///offline/report.html'});
assert.equal(plain.window.document.querySelector('.jump-nav a[aria-current=location]').hash,
  '#comparison-heading');
let sectionObserver;
const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  url: 'file:///offline/report.html#provenance-heading',
  beforeParse(window) {
    window.IntersectionObserver = class {
      constructor(callback) { this.callback = callback; sectionObserver = this; }
      observe() {}
    };
  }
});
const document = dom.window.document;
const rows = [...document.querySelectorAll('.comparison-table tbody tr')];
assert.equal(rows.length, 4);
assert.equal(rows.filter(row => !row.hidden).length, 4);
rows[0].querySelector('.compare-select').click();
rows[1].querySelector('.compare-select').click();
assert.equal(document.querySelectorAll('.selection-card').length, 2);
assert(rows[2].querySelector('.compare-select').disabled);
const prompt = document.querySelector('[data-comparison-filter=prompt]');
prompt.value = 'careful';
prompt.dispatchEvent(new dom.window.Event('change'));
assert.equal(rows.filter(row => !row.hidden).length, 2);
assert(document.querySelector('.selection-outside'));
document.getElementById('clear-selection').click();
assert.equal(document.querySelectorAll('.selection-card').length, 0);
assert.equal(document.querySelectorAll('.compare-select:checked').length, 0);
assert(document.getElementById('selection-status').textContent.includes('Select up to two'));
assert.equal(prompt.value, 'careful');
assert.equal(rows.filter(row => !row.hidden).length, 2);
document.getElementById('reset-comparison').click();
assert.equal(rows.filter(row => !row.hidden).length, 4);
const passPrompt = document.querySelector('[data-filter=prompt]');
passPrompt.value = 'careful';
passPrompt.dispatchEvent(new dom.window.Event('change'));
assert.equal([...document.querySelectorAll('.pass')].filter(pass => !pass.hidden).length, 4);
assert.equal(rows.filter(row => !row.hidden).length, 4);
assert(document.getElementById('condition-0').hidden);
rows[0].querySelector('.row-actions a').click();
assert(!document.getElementById('condition-0').hidden);
assert.equal([...document.querySelectorAll('.pass')].filter(pass => !pass.hidden).length, 8);
const nav = [...document.querySelectorAll('.jump-nav a')];
assert.equal(nav.filter(link => link.getAttribute('aria-current') === 'location')[0].hash, '#provenance-heading');
nav[2].click();
assert.equal(nav.filter(link => link.getAttribute('aria-current') === 'location')[0].hash, '#detail-heading');
dom.reconfigure({url: 'file:///offline/report.html#summary-heading'});
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'));
assert.equal(nav.filter(link => link.getAttribute('aria-current') === 'location')[0].hash, '#summary-heading');
const summarySection = document.getElementById('summary-heading').closest('section');
sectionObserver.callback([{
  target: summarySection, isIntersecting: true, boundingClientRect: {top: 0}
}]);
assert.equal(nav.filter(link => link.getAttribute('aria-current') === 'location')[0].hash, '#summary-heading');
"""


_CHECK_MODEL_TYPES = r"""
const fs = require('fs');
const assert = require('assert');
const { JSDOM } = require('jsdom');
const dom = new JSDOM(fs.readFileSync(0, 'utf8'), {
  runScripts: 'dangerously', url: 'file:///offline/report.html'
});
const document = dom.window.document;
const rows = [...document.querySelectorAll('.comparison-table tbody tr')];
const buttons = [...document.querySelectorAll('[data-model-type-choice]')];
const categoryButtons = [...document.querySelectorAll('[data-category-choice]')];
const visibleRows = () => rows.filter(row => !row.hidden);
const visiblePoints = () => [...document.querySelectorAll('.duration-point')].filter(point => !point.hasAttribute('hidden'));
const visibleLabels = () => [...document.querySelectorAll('.plot-key-row')].filter(item => !item.hidden);
const wholeExperiment = document.querySelector('.summary-section').textContent;
assert.equal(visibleRows().length, 4);
assert.equal(visiblePoints().length, 2);
assert.equal(visibleLabels().length, 2);
assert(document.getElementById('plot-status').textContent.includes('2 plotted of 4 visible conditions; 2 lack measured duration'));
buttons.find(button => button.dataset.modelTypeChoice === 'llm').click();
assert.equal(visibleRows().length, 2);
assert.equal(visiblePoints().length, 2);
assert(buttons.find(button => button.dataset.modelTypeChoice === 'llm').getAttribute('aria-pressed') === 'true');
rows[0].querySelector('.compare-select').click();
categoryButtons.find(button => button.dataset.categoryChoice === 'Native decisions').click();
assert.equal(visibleRows().length, 0);
assert.equal(visiblePoints().length, 0);
assert.equal(visibleLabels().length, 0);
assert(document.getElementById('plot-empty').hidden === false);
assert(document.getElementById('agreement-duration-chart').hasAttribute('hidden'));
assert(document.getElementById('comparison-empty').hidden === false);
assert(document.querySelector('.selection-card').textContent.includes('declared group: General LLM'));
assert(document.querySelector('.selection-outside'));
categoryButtons.find(button => button.dataset.categoryChoice === '').click();
assert.equal(visibleRows().length, 2);
buttons.find(button => button.dataset.modelTypeChoice === 'decision').click();
assert.equal(visibleRows().length, 2);
assert.equal(visiblePoints().length, 0);
assert.equal(visibleLabels().length, 0);
assert(document.getElementById('plot-empty').hidden === false);
assert(document.getElementById('plot-status').textContent.includes('2 lack measured duration'));
buttons.find(button => button.dataset.modelTypeChoice === 'llm').click();
assert.equal(visibleRows().length, 2);
const prompt = document.querySelector('[data-comparison-filter=prompt]');
prompt.value = 'careful';
prompt.dispatchEvent(new dom.window.Event('change'));
assert.equal(visibleRows().length, 1);
assert.equal(visiblePoints().length, 1);
assert.equal(visibleLabels().length, 1);
document.getElementById('reset-comparison').click();
assert.equal(visibleRows().length, 4);
assert.equal(visiblePoints().length, 2);
assert.equal(visibleLabels().length, 2);
assert(!document.getElementById('agreement-duration-chart').hasAttribute('hidden'));
assert.equal(prompt.value, '');
assert(buttons.find(button => button.dataset.modelTypeChoice === '').getAttribute('aria-pressed') === 'true');
assert.equal(document.querySelector('.summary-section').textContent, wholeExperiment);
const passPrompt = document.querySelector('[data-filter=prompt]');
passPrompt.value = 'careful';
passPrompt.dispatchEvent(new dom.window.Event('change'));
assert(document.getElementById('condition-0').hidden);
visiblePoints()[0].dispatchEvent(new dom.window.MouseEvent('click', {bubbles: true}));
assert(!document.getElementById('condition-0').hidden);
"""


class ReportDomTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the optional offline DOM check")
    def test_comparison_selection_filters_and_pass_scope(self):
        availability = subprocess.run(
            ["node", "-e", "require.resolve('jsdom')"], capture_output=True, text=True,
            check=False)
        if availability.returncode:
            self.skipTest("local jsdom is not installed")
        fixture = report_fixture.ReportUxTests()
        fixture.setUp()
        html = generate_report(fixture.task, fixture.plan, fixture.labels,
                               fixture.predictions, fixture.operations)
        result = subprocess.run(["node", "-e", _CHECK], input=html, text=True,
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the optional offline DOM check")
    def test_model_type_and_adapter_filters_compose_with_plot_and_selection(self):
        availability = subprocess.run(
            ["node", "-e", "require.resolve('jsdom')"], capture_output=True, text=True,
            check=False)
        if availability.returncode:
            self.skipTest("local jsdom is not installed")
        fixture = report_fixture.ReportUxTests()
        fixture.setUp()
        original_requests = fixture.plan["requests"]
        fixture.experiment["configs"][0]["model_type"] = "llm"
        fixture.experiment["configs"][0]["settings"]["adapter"] = "openrouter"
        fixture.experiment["configs"][1]["model_type"] = "decision"
        fixture.experiment["configs"][1]["settings"]["adapter"] = "clef_decide"
        fixture.plan = build_plan(fixture.task, fixture.experiment, fixture.inputs)
        replacements = {old["request_id"]: new["request_id"]
                        for old, new in zip(original_requests, fixture.plan["requests"])}
        for operation in fixture.operations:
            operation["request_id"] = replacements[operation["request_id"]]
        html = generate_report(fixture.task, fixture.plan, fixture.labels,
                               fixture.predictions, fixture.operations)
        result = subprocess.run(["node", "-e", _CHECK_MODEL_TYPES], input=html, text=True,
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
