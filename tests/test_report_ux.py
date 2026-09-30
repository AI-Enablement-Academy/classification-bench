"""Static regression checks for the offline report's summary and evidence UI.

These tests parse generated HTML. They do not render or interact with a browser.
"""

from html.parser import HTMLParser
import unittest

from classification_bench.core import _digest, build_plan
from classification_bench.report import generate_report


class Element:
    def __init__(self, tag, attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    def descendants(self, tag=None):
        for child in self.children:
            if isinstance(child, Element):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.descendants(tag)

    def text(self):
        return "".join(child.text() if isinstance(child, Element) else child
                       for child in self.children)


class Tree(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Element("root")
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Element(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def normalized(node):
    return " ".join(node.text().split())


def table_rows(table):
    rows = []
    for row in table.descendants("tr"):
        cells = [normalized(cell) for cell in row.children
                 if isinstance(cell, Element) and cell.tag in ("th", "td")]
        rows.append(cells)
    return rows


def comparison_rows(table):
    headers = table_rows(table)[0]
    return headers, {(row.attrs["data-config-id"], row.attrs["data-prompt-id"]):
                     dict(zip(headers, [normalized(cell) for cell in row.children
                                        if isinstance(cell, Element) and cell.tag in ("th", "td")]))
                     for row in table.descendants("tr") if "data-config-id" in row.attrs}


class ReportUxTests(unittest.TestCase):
    def setUp(self):
        self.task = {"name": "fictional", "input_keys": ["text"],
                     "fields": [{"name": "class", "labels": ["yes", "no"]}]}
        self.experiment = {
            "configs": [
                {"id": "alpha", "model": "fixture-a", "settings": {"provider": "local", "route": "first"}},
                {"id": "beta", "model": "fixture-b", "settings": {"provider": "local", "route": "second"}},
            ],
            "prompts": [{"id": "plain", "text": "Classify."},
                        {"id": "careful", "text": "Classify carefully."}],
            "repeats": 2, "batch_size": 2,
        }
        self.inputs = {"records": [{"id": "a", "input": {"text": "first input"}},
                                   {"id": "b", "input": {"text": "second input"}}]}
        self.labels = {"records": [{"id": "a", "labels": {"class": "yes"}},
                                   {"id": "b", "labels": {"class": "no"}}]}
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        records = []
        for config in self.experiment["configs"]:
            for prompt in self.experiment["prompts"]:
                for repeat in (1, 2):
                    for record in self.labels["records"]:
                        cid, pid, rid = config["id"], prompt["id"], record["id"]
                        if (cid, pid, repeat, rid) == ("alpha", "careful", 1, "b"):
                            continue
                        value = record["labels"]["class"]
                        if (cid, pid, repeat, rid) == ("alpha", "plain", 2, "a"):
                            value = "no"
                        if cid == "beta" and pid == "careful":
                            value = "no" if value == "yes" else "yes"
                        if (cid, pid, repeat, rid) == ("alpha", "careful", 2, "a"):
                            value = "invalid"
                        records.append({"config_id": cid, "prompt_id": pid, "repeat": repeat,
                                        "id": rid, "prediction": {"class": value}})
        self.predictions = {"records": records}
        requests = {(r["config_id"], r["prompt_id"], r["repeat"]): r
                    for r in self.plan["requests"]}
        self.operations = [
            {"request_id": requests[("alpha", "plain", 1)]["request_id"],
             "duration_seconds": 2.0, "observed_cost_micro_usd": 5,
             "receipt_sha256": "receipt-alpha-plain-1"},
            {"request_id": requests[("alpha", "plain", 2)]["request_id"],
             "duration_seconds": None, "observed_cost_micro_usd": None},
            {"request_id": requests[("alpha", "careful", 1)]["request_id"],
             "duration_seconds": 4.0, "observed_cost_micro_usd": 7},
        ]

    def render(self):
        return Tree(generate_report(self.task, self.plan, self.labels,
                                    self.predictions, self.operations)).root

    def test_comparison_uses_native_requested_provider_from_operations(self):
        self.experiment["configs"][0]["settings"].pop("provider")
        old_requests = self.plan["requests"]
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        ids = {old["request_id"]: new["request_id"]
               for old, new in zip(old_requests, self.plan["requests"])}
        for operation in self.operations:
            operation["request_id"] = ids[operation["request_id"]]
            operation["provider"] = "liquid"
            operation["returned_provider"] = None
        page = self.render()
        table = next(table for table in page.descendants("table")
                     if table.attrs.get("class") == "comparison-table")
        self.assertIn("requested provider: liquid", normalized(table))

    def test_comparison_uses_full_denominator_and_keeps_missing_invalid_separate(self):
        page = self.render()
        tables = [table for table in page.descendants("table")
                  if "comparison-table" in table.attrs.get("class", "").split()]
        self.assertEqual(len(tables), 1)
        self.assertEqual(normalized(next(tables[0].descendants("caption"))),
                         "Configuration and prompt comparison (unfiltered)")
        header, rows = comparison_rows(tables[0])
        self.assertEqual(header[:6], ["Configuration", "Prompt", "Exact agreement",
                                      "Repeat range", "Invalid selected projections",
                                      "No selected prediction"])
        self.assertEqual(len(rows), 4)
        self.assertEqual(set(rows), {("alpha", "plain"), ("alpha", "careful"),
                                     ("beta", "plain"), ("beta", "careful")})
        for key, expected in {
            ("alpha", "plain"): ("3/4 (75.0%)", "50.0% to 100.0%", "0", "0"),
            ("alpha", "careful"): ("2/4 (50.0%)", "50.0% to 50.0%", "1", "1"),
            ("beta", "plain"): ("4/4 (100.0%)", "100.0% to 100.0%", "0", "0"),
            ("beta", "careful"): ("0/4 (0.0%)", "0.0% to 0.0%", "0", "0"),
        }.items():
            row = rows[key]
            for column, value in zip(("Exact agreement", "Repeat range",
                                      "Invalid selected projections", "No selected prediction"), expected):
                self.assertEqual(row[column], value, (key, column))
        self.assertEqual(sum(int(row["Invalid selected projections"]) for row in rows.values()), 1)
        self.assertEqual(sum(int(row["No selected prediction"]) for row in rows.values()), 1)

    def test_comparison_distinguishes_partial_measurements_and_unavailable_cost(self):
        page = self.render()
        table = next(table for table in page.descendants("table")
                     if "comparison-table" in table.attrs.get("class", "").split())
        header, rows = comparison_rows(table)
        plain = rows[("alpha", "plain")]
        self.assertIn("2.000 s", plain["Mean client request duration"])
        self.assertIn("1/2", plain["Mean client request duration"])
        self.assertIn("5 micro USD", plain["Observed cost"])
        self.assertIn("1/2", plain["Cost coverage"])
        careful = rows[("alpha", "careful")]
        self.assertIn("4.000 s", careful["Mean client request duration"])
        self.assertIn("1/2", careful["Mean client request duration"])
        self.assertIn("7 micro USD", careful["Observed cost"])
        self.assertIn("1/2", careful["Cost coverage"])
        for key in (("beta", "plain"), ("beta", "careful")):
            row = rows[key]
            self.assertIn("unavailable", row["Mean client request duration"])
            self.assertIn("unavailable", row["Observed cost"])
            self.assertIn("0/2", row["Cost coverage"])

    def test_mixed_usd_and_synthetic_passes_keep_cost_units_separate(self):
        self.experiment["configs"][0] = {
            "id": "alpha", "model": "vendor/model",
            "settings": {"adapter": "openrouter", "provider": "vendor", "route": "regular",
                         "endpoint_snapshot": {
                             "model_id": "vendor/model", "provider_tag": "vendor",
                             "pricing": {"prompt": "0.000001", "completion": "0.000002",
                                         "input_cache_read": "0", "request": "0"}}},
        }
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        requests = {(r["config_id"], r["prompt_id"], r["repeat"]): r
                    for r in self.plan["requests"]}
        self.operations = [
            {"request_id": requests[("alpha", "plain", 1)]["request_id"],
             "cost_currency": "USD", "route": "regular", "returned_model": "vendor/model",
             "observed_cost_micro_usd": 5, "unresolved_hold_micro_usd": 2,
             "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                       "prompt_tokens_details": {"cache_write_tokens": 0}}},
            {"request_id": requests[("alpha", "plain", 2)]["request_id"],
             "cost_currency": "SYN", "route": "synthetic:offline",
             "observed_cost_micro_usd": 7, "unresolved_hold_micro_usd": 3},
        ]
        page = self.render()
        comparison = next(table for table in page.descendants("table")
                          if "comparison-table" in table.attrs.get("class", "").split())
        header, rows = comparison_rows(comparison)
        row = rows[("alpha", "plain")]
        self.assertIn("5 micro USD", row["Observed cost"])
        self.assertIn("7 SYN units", row["Observed cost"])
        self.assertIn("2/2", row["Cost coverage"])

        article = next(node for node in page.descendants("article")
                       if node.attrs.get("id") == "condition-0")
        passes = {node.attrs["data-repeat"]: node for node in article.descendants("section")
                  if "pass" in node.attrs.get("class", "").split()}
        self.assertEqual(set(passes), {"1", "2"})
        summary1 = next(table for table in passes["1"].descendants("table")
                        if any(normalized(caption) == "Request measurement summary"
                               for caption in table.descendants("caption")))
        summary2 = next(table for table in passes["2"].descendants("table")
                        if any(normalized(caption) == "Request measurement summary"
                               for caption in table.descendants("caption")))
        self.assertIn(["Observed provider charges", "5 micro USD across 1 request(s)"], table_rows(summary1))
        self.assertIn(["Pricing estimates", "3 micro USD across 1 request(s)"], table_rows(summary1))
        self.assertIn(["Unresolved budget holds", "2 micro USD across 1 request(s)"], table_rows(summary1))
        self.assertIn(["Observed synthetic accounting", "7 SYN units across 1 request(s)"], table_rows(summary2))
        self.assertIn(["Unresolved budget holds", "3 SYN units across 1 request(s)"], table_rows(summary2))
        for repeat, unit in (("1", "micro USD"), ("2", "SYN units")):
            telemetry = next(table for table in passes[repeat].descendants("table")
                             if any(normalized(caption) == "Request token and cost telemetry"
                                    for caption in table.descendants("caption")))
            self.assertIn(f"Observed charge ({unit})", table_rows(telemetry)[0])
        self.assertFalse(any(normalized(title) == "Agreement and observed cost"
                             for title in article.descendants("title")))
        self.assertIn("Observed costs use more than one currency", normalized(article))

    def test_unsafe_identifiers_are_escaped_and_internal_links_have_unique_targets(self):
        attack = "alpha'><img src=x onerror=alert(1)>"
        malicious_label = "yes<script>alert(2)</script>"
        self.experiment["configs"][0]["id"] = attack
        self.experiment["prompts"][0]["id"] = "p<&\"'"
        self.task["fields"][0]["labels"][0] = malicious_label
        self.labels["records"][0]["labels"]["class"] = malicious_label
        self.plan = build_plan(self.task, self.experiment, self.inputs)
        for record in self.predictions["records"]:
            if record["config_id"] == "alpha":
                record["config_id"] = attack
            if record["prompt_id"] == "plain":
                record["prompt_id"] = "p<&\"'"
            if record["prediction"]["class"] == "yes":
                record["prediction"]["class"] = malicious_label
        self.operations = []
        html = generate_report(self.task, self.plan, self.labels, self.predictions)
        page = Tree(html).root
        self.assertNotIn("<img", html)
        self.assertFalse(list(page.descendants("img")))
        self.assertNotIn("<script>alert(2)</script>", html)
        ids = [node.attrs["id"] for node in page.descendants() if "id" in node.attrs]
        self.assertEqual(len(ids), len(set(ids)))
        targets = [node.attrs["href"][1:] for node in page.descendants("a")
                   if node.attrs.get("href", "").startswith("#")]
        self.assertTrue(targets)
        self.assertTrue(set(targets).issubset(set(ids)))
        self.assertIn(attack, normalized(page))
        self.assertIn(malicious_label, normalized(page))

    def test_request_disclosure_preserves_identity_receipt_and_case_evidence(self):
        page = self.render()
        disclosures = [node for node in page.descendants("details")
                       if "request-evidence" in node.attrs.get("class", "").split()]
        self.assertGreaterEqual(len(disclosures), len(self.operations))
        self.assertTrue(all("Full request identity and telemetry evidence" in normalized(node)
                            for node in disclosures))
        evidence_text = " ".join(normalized(node) for node in disclosures)
        for operation in self.operations:
            self.assertIn(operation["request_id"], evidence_text)
        receipt = [node for node in disclosures if "receipt-alpha-plain-1" in normalized(node)]
        self.assertEqual(len(receipt), 1)
        request_id = self.operations[0]["request_id"]
        self.assertIn(request_id, normalized(receipt[0]))
        self.assertIn(_digest(self.operations), normalized(page))
        supporting = [node for node in page.descendants("details")
                      if "Supporting cases" in normalized(next(node.descendants("summary")))]
        self.assertEqual(len(supporting), 8)
        self.assertTrue(any("first input" in normalized(node) for node in supporting))

    def test_filter_controls_and_initial_state_match_pass_sections(self):
        page = self.render()
        passes = [node for node in page.descendants("section")
                  if "pass" in node.attrs.get("class", "").split()]
        self.assertEqual(len(passes), 8)
        selectors = [node for node in page.descendants("select") if "data-filter" in node.attrs]
        self.assertEqual({node.attrs["data-filter"] for node in selectors},
                         {"task", "model", "provider", "effort", "prompt", "repeat", "route"})
        for selector in selectors:
            key = selector.attrs["data-filter"]
            options = {option.attrs.get("value", "") for option in selector.descendants("option")}
            self.assertIn("", options)
            for section in passes:
                self.assertIn("data-" + key, section.attrs)
                self.assertIn(section.attrs["data-" + key], options)
        statuses = [node for node in page.descendants() if node.attrs.get("id") == "filter-status"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("Showing 8 of 8 pass sections", normalized(statuses[0]))
        resets = [node for node in page.descendants("button")
                  if node.attrs.get("id") == "reset-filters"]
        self.assertEqual(len(resets), 1)
        self.assertEqual(resets[0].attrs.get("type"), "button")
        empty = [node for node in page.descendants() if node.attrs.get("id") == "filter-empty"]
        self.assertEqual(len(empty), 1)
        self.assertIn("hidden", empty[0].attrs)
        self.assertIn("No pass sections match", normalized(empty[0]))

    def test_comparison_leads_and_uses_explicit_sort_values(self):
        page = self.render()
        main = next(page.descendants("main"))
        first_section = next(child for child in main.children if isinstance(child, Element))
        self.assertEqual(first_section.attrs.get("class"), "comparison-section")
        table = next(table for table in first_section.descendants("table")
                     if table.attrs.get("class") == "comparison-table")
        rows = {(row.attrs["data-config-id"], row.attrs["data-prompt-id"]): row
                for row in table.descendants("tr") if "data-config-id" in row.attrs}
        self.assertEqual(set(rows), {("alpha", "plain"), ("alpha", "careful"),
                                     ("beta", "plain"), ("beta", "careful")})
        plain = rows[("alpha", "plain")]
        cells = [cell for cell in plain.children if isinstance(cell, Element)]
        self.assertIn("fixture-a", normalized(cells[0]))
        self.assertIn("alpha · requested provider: local", normalized(cells[0]))
        self.assertEqual(cells[2].attrs["data-sort-value"], "0.75")
        self.assertEqual(cells[4].attrs["data-sort-value"], "0")
        self.assertEqual(cells[6].attrs["data-sort-value"], "2.0")
        beta_cells = [cell for cell in rows[("beta", "plain")].children if isinstance(cell, Element)]
        self.assertEqual(beta_cells[6].attrs["data-sort-value"], "")
        self.assertIn("selected prediction gap(s)", normalized(rows[("alpha", "careful")]))
        self.assertTrue(any("has-gaps" in span.attrs.get("class", "").split()
                            for span in rows[("alpha", "careful")].descendants("span")))
        sort_keys = {button.attrs["data-sort"] for button in table.descendants("button")
                     if "data-sort" in button.attrs}
        self.assertIn("exact", sort_keys)
        self.assertNotIn("cost", sort_keys)
        self.assertEqual(len([node for node in page.descendants("input")
                              if node.attrs.get("id") == "comparison-search"]), 1)

    def test_saved_raw_usage_is_collapsed_and_escaped_per_request(self):
        self.operations[0]["usage"] = {
            "choice_probabilities": [{"id": "a", "yes": 0.73}],
            "note": "<script>alert(1)</script>",
        }
        html = generate_report(self.task, self.plan, self.labels,
                               self.predictions, self.operations)
        page = Tree(html).root
        disclosures = [node for node in page.descendants("details")
                       if "raw-usage" in node.attrs.get("class", "").split()]
        self.assertEqual(len(disclosures), len(self.operations))
        self.assertFalse(any("open" in node.attrs for node in disclosures))
        first = next(node for node in disclosures
                     if self.operations[0]["request_id"] in normalized(node))
        self.assertIn('"yes": 0.73', normalized(first))
        self.assertIn("<script>alert(1)</script>", normalized(first))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertTrue(any("unavailable" in normalized(node) for node in disclosures))


if __name__ == "__main__":
    unittest.main()
