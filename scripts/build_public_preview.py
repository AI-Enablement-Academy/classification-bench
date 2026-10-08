"""Build and audit an allowlisted, entirely fictional static preview.

No existing benchmark data, examples, environment values or provider adapters
are read. The Python network/subprocess guards are not process isolation.
"""

import argparse
import base64
import copy
import gzip
import hashlib
from html import escape
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
from unittest.mock import patch

from classification_bench.core import _digest, build_plan, evaluate
from classification_bench.report import generate_report
from classification_bench.workflow_report import generate_workflow_report


STATES = ("complete", "invalid", "partial", "unlabeled", "all-missing", "failed", "sensitivity", "workflow")
REPORT_FILES = tuple(f"{kind}-{state}.html" for kind in ("product", "candidate") for state in STATES)
PUBLISH_FILES = frozenset((".nojekyll", "index.html", "manifest.json", *REPORT_FILES))
DEMO_NOTE = "Public synthetic demo: every input, label and observation is invented. No provider calls occurred."
_SCRIPT = re.compile(r"(<script\b[^>]*>)(.*?)(</script>)", re.I | re.S)
_SOURCE_PATH = re.compile(r"(?:file://|/Users/|/home/|/private/|/tmp/|(?<![A-Za-z0-9_-])[A-Za-z]:\\(?!u[0-9a-f]{4})|private-data/|classification_bench/[A-Za-z_]+\.py)")
_SECRET = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
_DENIED_KEYS = frozenset(("api_key", "access_token", "refresh_token", "authorization", "credentials", "account_id", "source_sha256", "receipt_path", "source_path"))
_PUBLIC_LINKS = frozenset((
    "https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages",
    "https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion",
    "https://openrouter.ai/docs/guides/best-practices/prompt-caching",
))
_MAX_JSON_BYTES = 16 * 1024 * 1024


class PreviewAuditError(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _safe_script_json(value):
    return _json(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def fictional_fixture(kind):
    """Invent preview data here; never load examples or saved project data."""
    if kind == "product":
        fields = [{"name": "use", "labels": ["shared", "individual"]},
                  {"name": "timing", "labels": ["soon", "later"]}]
        messages = ["An invented shared paper map for next week's treasure game.",
                    "An invented notebook for a lone cloud sketcher next winter.",
                    "An invented group calendar for a future moon picnic."]
        vectors = [("shared", "soon"), ("individual", "later"), ("shared", "later")]
    elif kind == "candidate":
        fields = [{"name": "experience", "labels": ["positive", "negative"]},
                  {"name": "follow_up", "labels": ["requested", "none"]}]
        messages = ["Fictional feedback: the imaginary interview was clear; please send the next date.",
                    "Fictional feedback: the imaginary schedule was confusing; please explain it.",
                    "Fictional feedback: the imaginary host explained the steps clearly. Thank you."]
        vectors = [("positive", "requested"), ("negative", "requested"), ("positive", "none")]
    else:
        raise ValueError("unsupported fictional preview kind")
    task = {"name": f"Fictional {kind} demo", "input_keys": ["text"], "fields": fields}
    inputs = {"records": [{"id": f"demo-{kind}-{i + 1}", "input": {"text": text}}
                          for i, text in enumerate(messages)]}
    labels = {"records": [{"id": row["id"], "labels": dict(zip((f["name"] for f in fields), vector))}
                          for row, vector in zip(inputs["records"], vectors)]}
    experiment = {"configs": [
        {"id": "fictional-a", "model": "synthetic-demo-a", "settings": {"adapter": "synthetic"}},
        {"id": "fictional-b", "model": "synthetic-demo-b", "model_type": "decision",
         "settings": {"adapter": "synthetic"}}],
        "prompts": [{"id": "baseline", "text": "Classify these invented records using the fictional task labels."},
                    {"id": "explicit", "text": "Check every fictional field before selecting its invented label."}],
        "repeats": 3, "batch_size": 2}
    return task, experiment, inputs, labels


def _predictions(task, plan, labels):
    references = {row["id"]: row["labels"] for row in labels["records"]}
    rows = []
    for request in plan["requests"]:
        for item in request["items"]:
            value = copy.deepcopy(references[item["id"]])
            # Different invented decisions exercise disagreement/error views.
            if request["config_id"] == "fictional-b" and request["prompt_id"] == "baseline":
                field = task["fields"][0]
                value[field["name"]] = next(label for label in field["labels"] if label != value[field["name"]])
            rows.append({"config_id": request["config_id"], "prompt_id": request["prompt_id"],
                         "repeat": request["repeat"], "id": item["id"], "prediction": value})
    return {"records": rows}


def _invalid(task, predictions):
    value = copy.deepcopy(predictions)
    value["records"][0]["prediction"][task["fields"][0]["name"]] = "fictional-invalid-label"
    return value


def _project(value):
    """Preview projection retains digests but omits implementation source paths."""
    if isinstance(value, list):
        return [_project(item) for item in value]
    if isinstance(value, dict):
        return {key: _project(item) for key, item in value.items() if key != "source_sha256"}
    return value


def _public_exports(packed):
    result = {}
    for mode, entry in packed.items():
        public_mode = "fictional" if mode == "private" else mode
        value = _project(json.loads(gzip.decompress(base64.b64decode(entry["base64"], validate=True))))
        value["preview_projection"] = {"schema_version": 1, "synthetic": True,
                                       "provenance": "Digest-only preview; source path maps omitted."}
        if public_mode == "fictional":
            value["visibility"] = "fictional"
            value["privacy_note"] = "Contains only invented inputs, labels and findings from this public synthetic demo."
        payload = _json(value).encode("utf-8")
        compressed = gzip.compress(payload, mtime=0)
        result[public_mode] = {"filename": entry["filename"].replace("-private.json.gz", "-fictional.json.gz"),
                               "base64": base64.b64encode(compressed).decode("ascii"),
                               "sha256": hashlib.sha256(compressed).hexdigest(), "bytes": len(compressed),
                               "json_sha256": hashlib.sha256(payload).hexdigest(), "json_bytes": len(payload)}
    return result


def _public_html(html):
    exports = []

    def replace_script(match):
        start, body, end = match.groups()
        if not re.search(r"\btype=['\"]application/json['\"]", start, re.I):
            return match.group(0)
        value = json.loads(body)
        if re.search(r"\bid=['\"]analysis-export-data['\"]", start):
            value = _public_exports(value)
            exports.append(value)
        elif re.search(r"\bid=['\"]workflow-data['\"]", start):
            value["documents"] = {name: _public_html(document) for name, document in value["documents"].items()}
        else:
            value = _project(value)
        return start + _safe_script_json(value) + end

    html = _SCRIPT.sub(replace_script, html)
    if exports:
        rows = "".join(f"<li>{escape(mode)}: {entry['bytes']} compressed bytes; download SHA-256 <code>{entry['sha256']}</code>; "
                       f"{entry['json_bytes']} uncompressed UTF-8 bytes; JSON SHA-256 <code>{entry['json_sha256']}</code></li>"
                       for mode, entry in exports[0].items())
        html, count = re.subn(r"(<summary>Exact download byte hashes</summary><ul>).*?(</ul>)",
                             lambda match: match[1] + rows + match[2], html, flags=re.S)
        if count != 1:
            raise PreviewAuditError("preview download disclosure was not found exactly once")
    replacements = {
        "Private local classification report": "Public synthetic classification demo",
        "Private local classification workflow": "Public synthetic classification workflow",
        "This file includes private inputs and reference labels. Keep it local.": DEMO_NOTE,
        "value='private'": "value='fictional'",
        "mode.value==='private'": "mode.value==='fictional'",
        "Private inputs, labels and findings": "Fictional inputs, labels and findings",
        "Private export includes inputs and reference labels. Keep it private.": "Fictional export includes only invented inputs and reference labels.",
        "Compression keeps large pair analyses out of the page DOM; it does not encrypt private data.": "Compression keeps large pair analyses out of the page DOM. Both download choices contain only fictional demo data.",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    banner = ("<aside aria-label='Public demo scope' style='padding:12px 24px;background:#e9efe9;border-bottom:1px solid #c8d2c9'>"
              f"<strong>{DEMO_NOTE}</strong> Rendered acceptance is pending.</aside>")
    return html.replace("<body>", "<body>" + banner, 1)


class _HTMLData(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.blocks, self.resources, self.links = [], [], []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/json":
            self.current = [attrs.get("id"), ""]
        if tag in ("script", "img", "iframe", "link", "video", "audio", "source", "object", "embed"):
            self.resources.extend(attrs[name] for name in ("src", "href", "data", "srcdoc") if attrs.get(name))
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] += data

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.blocks.append(self.current)
            self.current = None


def _audit_text(text):
    if _SOURCE_PATH.search(text) or _SECRET.search(text):
        raise PreviewAuditError("public preview contains a path or credential pattern")


def _audit_value(value, stats):
    if isinstance(value, dict):
        if _DENIED_KEYS.intersection(value):
            raise PreviewAuditError("public preview contains a prohibited metadata key")
        if "base64" in value:
            required = {"filename", "base64", "sha256", "bytes", "json_sha256", "json_bytes"}
            if set(value) != required or not re.fullmatch(r"benchmark-[0-9a-f]{12}-(?:sanitized|fictional)\.json\.gz", value["filename"]):
                raise PreviewAuditError("unexpected embedded download shape")
            compressed = base64.b64decode(value["base64"], validate=True)
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
                raw = handle.read(_MAX_JSON_BYTES + 1)
            if len(raw) > _MAX_JSON_BYTES:
                raise PreviewAuditError("embedded download exceeds preview audit limit")
            if (len(compressed) != value["bytes"] or hashlib.sha256(compressed).hexdigest() != value["sha256"]
                    or len(raw) != value["json_bytes"] or hashlib.sha256(raw).hexdigest() != value["json_sha256"]):
                raise PreviewAuditError("embedded download digest mismatch")
            decoded = raw.decode("utf-8")
            _audit_text(decoded)
            data = json.loads(decoded)
            if data.get("preview_projection", {}).get("synthetic") is not True:
                raise PreviewAuditError("embedded download lacks fictional provenance")
            stats["embedded_downloads"] += 1
            _audit_value(data, stats)
            return
        for key, item in value.items():
            _audit_text(key)
            if key == "documents":
                if set(item) != {"smoke", "full"}:
                    raise PreviewAuditError("unexpected workflow phase documents")
                for document in item.values():
                    _audit_html(document, stats)
            else:
                _audit_value(item, stats)
    elif isinstance(value, list):
        for item in value:
            _audit_value(item, stats)
    elif isinstance(value, str):
        _audit_text(value)


def _audit_html(html, stats):
    _audit_text(html)
    if DEMO_NOTE not in html or "Rendered acceptance is pending." not in html:
        raise PreviewAuditError("report lacks its public fictional scope notice")
    parsed = _HTMLData(html)
    if parsed.resources:
        raise PreviewAuditError("public preview must have no external or embedded resource loads")
    for link in parsed.links:
        if not (link.startswith("#") or link in PUBLISH_FILES or link in _PUBLIC_LINKS):
            raise PreviewAuditError("public preview contains a non-allowlisted navigation link")
    for block_id, body in parsed.blocks:
        value = json.loads(body)
        if block_id == "analysis-export-data" and set(value) != {"sanitized", "fictional"}:
            raise PreviewAuditError("unexpected public download modes")
        _audit_value(value, stats)
        stats["json_blocks"] += 1
    stats["html_documents"] += 1


def audit(directory):
    """Fail closed on any unexpected file, changed bytes or embedded disclosure."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise PreviewAuditError("publish root must be a real directory")
    entries = list(root.iterdir())
    if {path.name for path in entries} != PUBLISH_FILES:
        raise PreviewAuditError("publish files do not match the exact allowlist")
    for path in entries:
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise PreviewAuditError("publish files must be ordinary single-link files")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    expected_keys = {"schema_version", "purpose", "synthetic", "live_dispatches", "rendered_acceptance", "build_guard",
                     "generator_sha256", "report_engine_sha256", "fixture_definition_sha256", "reports", "files"}
    if (set(manifest) != expected_keys or manifest["schema_version"] != 1 or manifest["synthetic"] is not True
            or manifest["live_dispatches"] != 0 or manifest["rendered_acceptance"] != "pending"):
        raise PreviewAuditError("unexpected public preview manifest")
    expected_files = PUBLISH_FILES - {"manifest.json"}
    declared = manifest["files"]
    if len(declared) != len(expected_files) or {item["file"] for item in declared} != expected_files:
        raise PreviewAuditError("manifest file list mismatch")
    stats = {"files": len(entries), "html_documents": 0, "json_blocks": 0, "embedded_downloads": 0}
    _audit_value(manifest, stats)
    for item in declared:
        if set(item) != {"file", "sha256", "bytes"}:
            raise PreviewAuditError("unexpected manifest file entry")
        payload = (root / item["file"]).read_bytes()
        if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise PreviewAuditError("publish file digest mismatch")
        if item["file"].endswith(".html"):
            _audit_html(payload.decode("utf-8"), stats)
        elif payload:
            raise PreviewAuditError(".nojekyll must be empty")
    if len(manifest["reports"]) != len(REPORT_FILES) or {item["file"] for item in manifest["reports"]} != set(REPORT_FILES):
        raise PreviewAuditError("manifest report list mismatch")
    return {**stats, "synthetic": True, "live_dispatches": 0, "rendered_acceptance": "pending",
            "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()}


def _index():
    sections = []
    for kind in ("product", "candidate"):
        rows = "".join(f"<li><a href='{kind}-{state}.html'>{escape(state.replace('-', ' '))}</a></li>" for state in STATES)
        sections.append(f"<section><h2>Fictional {kind} reports</h2><ul>{rows}</ul></section>")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Classification report demo</title><style>body{max-width:860px;margin:48px auto;padding:0 24px;background:#f8f7f4;color:#222823;font:17px/1.6 system-ui,sans-serif}"
            "h1,h2{font-family:Georgia,serif}a{color:#245b4b}a:focus-visible{outline:3px solid #245b4b;outline-offset:4px}ul{display:flex;gap:8px 28px;flex-wrap:wrap;padding-left:24px}"
            "section{border-top:1px solid #dcded8;margin-top:28px}</style></head><body>"
            f"<h1>Classification report demo</h1><p><strong>{DEMO_NOTE}</strong></p>"
            "<p>Inspect the report layout, filters, case comparisons and presentation controls. Each data-state report has 36 planned outputs from three fictional cases, two configurations, two prompts and three repeats. Repeats are scheduled outputs, not independent cases.</p>"
            "<p>The workflow reports keep smoke and full phases separate. Missing cost, token and timing measurements remain unavailable. These examples provide no evidence about real model quality, cost or speed.</p>"
            + "".join(sections) +
            "<section><h2>Inspection record</h2><p>Rendered acceptance is pending. Record the report file, its SHA-256 from <a href='manifest.json'>the manifest</a>, browser version, viewport, reduced-motion setting and observed results. Source checks and this publication do not establish visual or native-download acceptance.</p>"
            "<p>Both embedded download choices contain only fictional demo data. Their preview projections retain provenance digests and omit source path maps.</p>"
            "<p>This site uses <a href='https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages'>GitHub Pages</a>.</p></section></body></html>")


def build(directory):
    target = Path(directory).absolute()
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    files, reports, definitions = [], [], []

    def save(name, value):
        if name not in PUBLISH_FILES:
            raise PreviewAuditError("attempt to stage an unallowlisted file")
        payload = value.encode("utf-8")
        fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        files.append({"file": name, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})

    def deny_external(*args, **kwargs):
        raise AssertionError("Public preview generation must remain offline and use no subprocesses")

    with patch.object(socket.socket, "connect", deny_external), patch.object(socket, "create_connection", deny_external), \
            patch.object(subprocess, "Popen", deny_external), tempfile.TemporaryDirectory(prefix="fictional-preview-") as temporary:
        for kind in ("product", "candidate"):
            task, experiment, inputs, labels = fictional_fixture(kind)
            definitions.append({"task": task, "experiment": experiment, "inputs": inputs, "labels": labels})
            plan = build_plan(task, experiment, inputs)
            complete = _predictions(task, plan, labels)
            invalid = _invalid(task, complete)
            partial = {"records": labels["records"][:1]}
            failures = [{"request_id": req["request_id"], "state": "failed", "route": "synthetic:public-demo",
                         "cost_currency": "SYN", "reason": "Invented failed-request fixture; no request was dispatched."}
                        for req in plan["requests"]]
            first = labels["records"][0]
            field = task["fields"][0]
            scenarios = [{"id": "fictional-alternate-reference", "title": "Fictional alternate reference",
                          "provenance": "Illustrative invented scenario; the baseline is unchanged.",
                          "changes": [{"id": first["id"], "labels": {field["name"]: next(
                              value for value in field["labels"] if value != first["labels"][field["name"]])}}]}]
            for state, references, outputs, allow_partial, operations in (
                    ("complete", labels, complete, False, []), ("invalid", labels, invalid, False, []),
                    ("partial", partial, invalid, True, []), ("unlabeled", None, invalid, False, []),
                    ("all-missing", labels, {"records": []}, False, []),
                    ("failed", labels, {"records": []}, False, failures),
                    ("sensitivity", labels, invalid, False, [])):
                name = f"{kind}-{state}.html"
                result = evaluate(task, plan, references, outputs, allow_partial_references=allow_partial)
                html = generate_report(task, plan, references, outputs, operations, allow_partial_references=allow_partial,
                                       scenarios=scenarios if state == "sensitivity" else None)
                save(name, _public_html(html))
                reports.append({"file": name, "state": state, "planned": result["positions"],
                                "invalid": len(result["invalid"]), "missing": result["missing"],
                                "valid": result["positions"] - len(result["invalid"]) - result["missing"],
                                "input_sha256": _digest(inputs), "reference_sha256": _digest(references),
                                "plan_sha256": _digest(plan), "prediction_sha256": _digest(outputs),
                                "operation_sha256": _digest(operations)})
            source = Path(temporary) / (kind + ".json")
            source.write_text(_json(inputs), encoding="utf-8")
            phases, manifest_phases, counts = {}, {}, {}
            for phase, rows, repeats in (("smoke", inputs["records"][:1], 1), ("full", inputs["records"], 3)):
                phase_plan = build_plan(task, {**experiment, "repeats": repeats}, {"records": rows})
                phase_outputs = _invalid(task, _predictions(task, phase_plan, labels))
                phases[phase] = {"task": task, "plan": phase_plan, "predictions": phase_outputs, "operations": []}
                manifest_phases[phase] = {"ids": [row["id"] for row in rows], "plan_sha256": _digest(phase_plan)}
                projected = {"records": [row for row in labels["records"] if row["id"] in manifest_phases[phase]["ids"]]}
                scored = evaluate(task, phase_plan, projected, phase_outputs)
                counts[phase] = {"planned": scored["positions"], "invalid": len(scored["invalid"]), "missing": scored["missing"]}
            snapshot = {"manifest": {"name": f"Fictional {kind} demo workflow", "workflow_sha256": _digest(manifest_phases),
                                      "sources": {"inputs": {"path": str(source)}}, "phases": manifest_phases}, "phases": phases}
            name = f"{kind}-workflow.html"
            save(name, _public_html(generate_workflow_report(snapshot, labels)))
            reports.append({"file": name, "state": "workflow", "phases": counts,
                            "input_sha256": _digest(inputs), "reference_sha256": _digest(labels)})
        save("index.html", _index())
        save(".nojekyll", "")
        package = Path(__file__).resolve().parents[1] / "classification_bench"
        engine_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(package.glob("*.py"))]
        manifest = {"schema_version": 1, "purpose": "Public fictional report inspection; no provider-performance evidence",
                    "synthetic": True, "live_dispatches": 0, "rendered_acceptance": "pending",
                    "build_guard": "Python socket and subprocess calls denied during generation; not process isolation",
                    "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "report_engine_sha256": _digest(engine_hashes), "fixture_definition_sha256": _digest(definitions),
                    "reports": reports, "files": sorted(files, key=lambda item: item["file"])}
        save("manifest.json", _json(manifest))
    return audit(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--directory", help="New output directory; existing destinations are rejected")
    group.add_argument("--audit", help="Audit an existing exact publish tree without modifying it")
    args = parser.parse_args()
    print(_json(audit(args.audit) if args.audit else build(args.directory)), end="")


if __name__ == "__main__":
    main()
