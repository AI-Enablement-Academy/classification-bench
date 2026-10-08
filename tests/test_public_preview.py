"""Publication checks inspect nested documents and compressed downloads offline."""

import base64
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_public_preview as preview


class PublicPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="public-preview-tests-")
        cls.root = Path(cls.temporary.name)
        cls.bundle = cls.root / "first"
        original_open = Path.open

        def guard_open(path, mode="r", *args, **kwargs):
            if ("examples" in path.parts or "private-data" in path.parts or path.name.startswith(".env")):
                raise AssertionError("preview attempted to read pre-existing fixture/private data")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", guard_open), \
                patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-PUBLIC_PREVIEW_ENV_CANARY_1234567890"}), \
                patch("classification_bench.benchmark.run", side_effect=AssertionError("adapter execution forbidden")):
            cls.result = preview.build(cls.bundle)
        cls.manifest = json.loads((cls.bundle / "manifest.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def copy_bundle(self):
        destination = Path(tempfile.mkdtemp(prefix="mutation-", dir=self.root)) / "site"
        shutil.copytree(self.bundle, destination)
        return destination

    def resign(self, root, filename):
        """Content checks must reject leakage even with matching outer hashes."""
        path = root / "manifest.json"
        manifest = json.loads(path.read_text())
        payload = (root / filename).read_bytes()
        row = next(item for item in manifest["files"] if item["file"] == filename)
        row.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        path.write_text(preview._json(manifest))

    def test_exact_allowlist_nested_documents_and_downloads(self):
        self.assertEqual({path.name for path in self.bundle.iterdir()}, preview.PUBLISH_FILES)
        self.assertEqual(self.result["files"], 19)
        self.assertEqual(self.result["html_documents"], 21)  # 17 top-level plus four workflow phases
        self.assertEqual(self.result["embedded_downloads"], 36)
        self.assertTrue(self.result["synthetic"])
        self.assertEqual(self.result["live_dispatches"], 0)
        self.assertEqual(self.result["rendered_acceptance"], "pending")
        self.assertGreater(self.result["json_blocks"], 50)

    def test_counts_preserve_invalid_missing_and_unlabeled_outcomes(self):
        reports = {row["file"]: row for row in self.manifest["reports"]}
        for kind in ("product", "candidate"):
            for state in preview.STATES[:-1]:
                row = reports[f"{kind}-{state}.html"]
                self.assertEqual(row["planned"], 36)
                self.assertEqual(row["planned"], row["valid"] + row["invalid"] + row["missing"])
            self.assertEqual(reports[f"{kind}-complete.html"]["valid"], 36)
            for state in ("invalid", "partial", "unlabeled", "sensitivity"):
                self.assertEqual(reports[f"{kind}-{state}.html"]["invalid"], 1)
            for state in ("all-missing", "failed"):
                self.assertEqual(reports[f"{kind}-{state}.html"]["missing"], 36)
            phases = reports[f"{kind}-workflow.html"]["phases"]
            self.assertEqual(phases["smoke"], {"planned": 4, "invalid": 1, "missing": 0})
            self.assertEqual(phases["full"], {"planned": 36, "invalid": 1, "missing": 0})
            html = (self.bundle / f"{kind}-unlabeled.html").read_text()
            self.assertIn("Full-denominator exact agreement is unavailable.", html)
            self.assertIn("presentation-start", html)

    def test_all_downloads_are_fictional_and_keep_exact_hashes(self):
        html = (self.bundle / "product-complete.html").read_text()
        blocks = dict(preview._HTMLData(html).blocks)
        packed = json.loads(blocks["analysis-export-data"])
        self.assertEqual(set(packed), {"sanitized", "fictional"})
        for mode, entry in packed.items():
            raw = gzip.decompress(base64.b64decode(entry["base64"]))
            data = json.loads(raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["json_sha256"])
            self.assertTrue(data["preview_projection"]["synthetic"])
            self.assertTrue('"source_sha256":' not in raw.decode(), "source path map remains in preview download")
            self.assertNotIn("PUBLIC_PREVIEW_ENV_CANARY", raw.decode())
            self.assertIn("evaluation_id", data["evaluation"])
            self.assertIn("implementation_sha256", data["evaluation"]["evaluation_provenance"])
            if mode == "fictional":
                self.assertEqual(data["visibility"], "fictional")
                self.assertEqual(data["runs"][0]["cases"][0]["case_id"], "demo-product-1")
                self.assertIn("invented", data["runs"][0]["cases"][0]["input"]["text"])
            else:
                self.assertNotIn("input", data["runs"][0]["cases"][0])
        self.assertIn("value='fictional'", html)
        self.assertIn("mode.value==='fictional'", html)
        self.assertNotIn("value='private'", html)

    def test_rebuilding_is_byte_identical_and_existing_destination_is_rejected(self):
        second = self.root / "second"
        result = preview.build(second)
        self.assertEqual(result, self.result)
        for name in preview.PUBLISH_FILES:
            self.assertEqual((self.bundle / name).read_bytes(), (second / name).read_bytes(), name)
        with self.assertRaises(FileExistsError):
            preview.build(self.bundle)
        self.assertEqual(preview.audit(self.bundle), self.result)

    def test_public_download_controls_emit_both_exact_projected_payloads(self):
        if not shutil.which("node"):
            self.skipTest("local Node.js is unavailable for source execution checks")
        html = (self.bundle / "product-complete.html").read_text()
        blocks = dict(preview._HTMLData(html).blocks)
        packed = json.loads(blocks["analysis-export-data"])
        scripts = [body for start, body, end in preview._SCRIPT.findall(html)
                   if "application/json" not in start]
        download = next(body for body in scripts if "const values=JSON.parse(document.getElementById('analysis-export-data')" in body)
        script = r"""
const fs=require('fs'), vm=require('vm'), assert=require('assert'), crypto=require('crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8')), saved=[], blobs=[];
const mode={value:'sanitized',addEventListener(type,fn){this.change=fn;}}, notice={textContent:''};
const button={addEventListener(type,fn){this.click=fn;}};
const nodes={'analysis-export-data':{textContent:JSON.stringify(input.packed)},'analysis-export-mode':mode,
  'analysis-export-notice':notice,'analysis-export-download':button};
const document={getElementById:id=>nodes[id],body:{append(){}},createElement(){return {
  click(){saved.push({name:this.download,blob:blobs.at(-1)});},remove(){}};}};
vm.runInNewContext(input.script,{document,atob:value=>Buffer.from(value,'base64').toString('binary'),
  Uint8Array,Blob:class{constructor(parts){this.bytes=Buffer.from(parts[0]);}},
  URL:{createObjectURL(blob){blobs.push(blob);return 'blob:source-test';},revokeObjectURL(){}},setTimeout(){}});
for(const key of ['sanitized','fictional']){
  mode.value=key;mode.change();button.click();
  const result=saved.at(-1),expected=input.packed[key];
  assert.equal(result.name,expected.filename);
  assert.equal(crypto.createHash('sha256').update(result.blob.bytes).digest('hex'),expected.sha256);
  assert(notice.textContent.includes('Downloaded '+key));
  assert(!notice.textContent.includes('Keep it private'));
}
assert.equal(saved.length,2);
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps({"script": download, "packed": packed}),
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_transformed_inline_javascript_parses_without_a_browser(self):
        if not shutil.which("node"):
            self.skipTest("local Node.js is unavailable for syntax checks")
        scripts = []

        def collect(html):
            scripts.extend(body for start, body, end in preview._SCRIPT.findall(html)
                           if "application/json" not in start)
            for block_id, body in preview._HTMLData(html).blocks:
                if block_id == "workflow-data":
                    for document in json.loads(body)["documents"].values():
                        collect(document)

        for name in preview.REPORT_FILES:
            collect((self.bundle / name).read_text())
        script = "const vm=require('vm'),fs=require('fs');for(const value of JSON.parse(fs.readFileSync(0,'utf8')))new vm.Script(value);"
        result = subprocess.run(["node", "-e", script], input=json.dumps(scripts), text=True,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_generation_blocks_network_and_subprocess_calls(self):
        from scripts.build_public_preview import generate_report

        for action in (lambda: socket.create_connection(("example.invalid", 443)),
                       lambda: subprocess.Popen(["true"])):
            def attempt(*args, **kwargs):
                action()
                return generate_report(*args, **kwargs)

            with patch.object(preview, "generate_report", attempt), self.assertRaisesRegex(AssertionError, "remain offline"):
                preview.build(self.root / ("blocked-" + str(id(action))))

    def test_unexpected_file_and_symlink_are_rejected(self):
        root = self.copy_bundle()
        (root / "saved-receipt.json").write_text("fictional")
        with self.assertRaisesRegex(preview.PreviewAuditError, "exact allowlist"):
            preview.audit(root)
        (root / "saved-receipt.json").unlink()
        target = root / ".nojekyll"
        target.unlink()
        target.symlink_to(self.bundle / ".nojekyll")
        with self.assertRaisesRegex(preview.PreviewAuditError, "single-link"):
            preview.audit(root)

    def test_changed_report_bytes_are_rejected(self):
        root = self.copy_bundle()
        with (root / "product-complete.html").open("a") as handle:
            handle.write("<!-- changed -->")
        with self.assertRaisesRegex(preview.PreviewAuditError, "digest mismatch"):
            preview.audit(root)

    def test_encoded_private_path_in_workflow_document_is_rejected(self):
        root = self.copy_bundle()
        path = root / "product-workflow.html"
        html = path.read_text()
        blocks = dict(preview._HTMLData(html).blocks)
        data = json.loads(blocks["workflow-data"])
        data["documents"]["full"] += "<!-- /Users/private-operator/saved-data -->"
        html = html.replace(blocks["workflow-data"], json.dumps(data).replace("/", "\\u002f"))
        path.write_text(html)
        self.resign(root, path.name)
        with self.assertRaisesRegex(preview.PreviewAuditError, "path or credential"):
            preview.audit(root)

    def test_secret_in_compressed_download_is_rejected_after_resigning(self):
        root = self.copy_bundle()
        path = root / "candidate-complete.html"
        html = path.read_text()
        blocks = dict(preview._HTMLData(html).blocks)
        packed = json.loads(blocks["analysis-export-data"])
        entry = packed["fictional"]
        value = json.loads(gzip.decompress(base64.b64decode(entry["base64"])))
        value["leaked"] = "ghp_" + "Z" * 36
        raw = preview._json(value).encode()
        compressed = gzip.compress(raw, mtime=0)
        entry.update(base64=base64.b64encode(compressed).decode(), bytes=len(compressed),
                     sha256=hashlib.sha256(compressed).hexdigest(), json_bytes=len(raw),
                     json_sha256=hashlib.sha256(raw).hexdigest())
        path.write_text(html.replace(blocks["analysis-export-data"], preview._safe_script_json(packed)))
        self.resign(root, path.name)
        with self.assertRaisesRegex(preview.PreviewAuditError, "path or credential"):
            preview.audit(root)

    def test_external_script_and_unknown_navigation_are_rejected(self):
        for extra in ("<script src='https://example.invalid/code.js'></script>",
                      "<a href='https://example.invalid/private-data'>Bad link</a>"):
            root = self.copy_bundle()
            path = root / "index.html"
            path.write_text(path.read_text() + extra)
            self.resign(root, path.name)
            with self.assertRaises(preview.PreviewAuditError):
                preview.audit(root)

    def test_path_detection_accepts_escaped_follow_up_and_rejects_drive_paths(self):
        preview._audit_text(r"Suggested follow-up:\u003c/strong\u003e")
        with self.assertRaises(preview.PreviewAuditError):
            preview._audit_text(r"C:\private\saved-file.json")


if __name__ == "__main__":
    unittest.main()
