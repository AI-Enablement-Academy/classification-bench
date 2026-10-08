"""Offline artifact verification around one-attempt ExecutionLedger records."""

import json
import os
import re
import stat
from dataclasses import asdict
from pathlib import Path

from .evidence import ArtifactRef, put_artifact, read_artifact
from .execution import ExecutionLedger


class VerifiedExecutionError(ValueError):
    pass


_RECEIPT_KEYS = {"schema_version", "request_id", "attempt_id", "manifest_digest",
                 "input_digest", "source_id", "response"}
_SHARD = re.compile(r"[0-9a-f]{2}\Z")
_OBJECT = re.compile(r"[0-9a-f]{64}\Z")


def _text(value, name):
    if not isinstance(value, str) or not value or value != value.strip():
        raise VerifiedExecutionError(f"{name} must be a nonempty trimmed string")


def _json_bytes(record):
    return json.dumps(record, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise VerifiedExecutionError("receipt JSON has duplicate keys")
        result[key] = value
    return result


class VerifiedExecution:
    """Verify immutable bytes before calling the lower-level execution API."""

    def __init__(self, database_path, artifact_root):
        self.execution = ExecutionLedger(database_path)
        self.artifact_root = Path(artifact_root)
        with self.execution.coordinator._transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS verified_response_receipts (
                request_id TEXT PRIMARY KEY REFERENCES requests(request_id),
                attempt_id TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                receipt_size INTEGER NOT NULL,
                receipt_media_type TEXT NOT NULL,
                receipt_path TEXT NOT NULL
            )""")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS verified_receipts_no_update
                BEFORE UPDATE ON verified_response_receipts BEGIN
                SELECT RAISE(ABORT, 'response receipt index is immutable'); END""")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS verified_receipts_no_delete
                BEFORE DELETE ON verified_response_receipts BEGIN
                SELECT RAISE(ABORT, 'response receipt index is immutable'); END""")

    def enqueue_bytes(self, request_id, scope, manifest_bytes, request_bytes,
                      *, request_media_type="application/json"):
        """Publish and verify exact bytes, then enroll their byte digests."""
        manifest = put_artifact(self.artifact_root, manifest_bytes, "application/json")
        request = put_artifact(self.artifact_root, request_bytes, request_media_type)
        read_artifact(self.artifact_root, manifest)
        read_artifact(self.artifact_root, request)
        enrolled = self.execution.enqueue(request_id, manifest.sha256, request.sha256, scope)
        return {"request": enrolled, "manifest_ref": manifest, "request_ref": request}

    def admit_verified(self, request_id, token, scope, reserve_amount, manifest_ref, request_ref,
                       *, bound_source=None, no_fee_evidence=None, admission_guard=None):
        """Re-read both artifacts and match the enrolled byte digests before admission."""
        state = self.execution.get(request_id)
        entry = state["execution"]
        if not isinstance(manifest_ref, ArtifactRef) or not isinstance(request_ref, ArtifactRef):
            raise VerifiedExecutionError("manifest and request must be ArtifactRef values")
        if manifest_ref.media_type != "application/json":
            raise VerifiedExecutionError("manifest artifact must be application/json")
        read_artifact(self.artifact_root, manifest_ref)
        read_artifact(self.artifact_root, request_ref)
        if (manifest_ref.sha256, request_ref.sha256) != (entry["manifest_digest"], entry["input_digest"]):
            raise VerifiedExecutionError("artifact bytes do not match enrolled digests")
        return self.execution.admit(request_id, token, manifest_ref.sha256, request_ref.sha256,
                                    scope, reserve_amount, bound_source=bound_source,
                                    no_fee_evidence=no_fee_evidence, admission_guard=admission_guard)

    def save_response(self, request_id, token, response_bytes, media_type, source_id):
        """Publish response bytes and a request-bound receipt, then index the receipt."""
        _text(source_id, "source_id")
        state = self.execution.get(request_id)
        row, entry = state["request"], state["execution"]
        if entry["admission_token"] != token or row["state"] not in (
                "dispatch_intent", "outcome_unknown"):
            raise VerifiedExecutionError("response is not bound to an admitted attempt")
        response = put_artifact(self.artifact_root, response_bytes, media_type)
        read_artifact(self.artifact_root, response)
        receipt_record = {
            "schema_version": 1, "request_id": request_id, "attempt_id": row["attempt_id"],
            "manifest_digest": entry["manifest_digest"],
            "input_digest": entry["input_digest"], "source_id": source_id,
            "response": asdict(response),
        }
        receipt = put_artifact(self.artifact_root, _json_bytes(receipt_record), "application/json")
        self._verify_receipt(request_id, token, receipt)
        self._index_receipt(request_id, receipt)
        return {"response_ref": response, "receipt_ref": receipt}

    def _verify_receipt(self, request_id, token, receipt_ref):
        if not isinstance(receipt_ref, ArtifactRef) or receipt_ref.media_type != "application/json":
            raise VerifiedExecutionError("receipt must be a JSON ArtifactRef")
        try:
            receipt = json.loads(read_artifact(self.artifact_root, receipt_ref))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise VerifiedExecutionError("receipt is not UTF-8 JSON") from exc
        if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_KEYS or (
                type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1):
            raise VerifiedExecutionError("invalid response receipt schema")
        state = self.execution.get(request_id)
        row, entry = state["request"], state["execution"]
        if entry["admission_token"] != token or (receipt["request_id"], receipt["attempt_id"],
                receipt["manifest_digest"], receipt["input_digest"]) != (
                request_id, row["attempt_id"], entry["manifest_digest"], entry["input_digest"]):
            raise VerifiedExecutionError("response receipt does not match admitted request and attempt")
        _text(receipt["source_id"], "receipt source_id")
        try:
            response = ArtifactRef(**receipt["response"])
        except (KeyError, TypeError) as exc:
            raise VerifiedExecutionError("invalid response artifact reference") from exc
        read_artifact(self.artifact_root, response)
        return response

    def _index_receipt(self, request_id, receipt_ref):
        """Make a verified receipt discoverable after a crash before terminal commit."""
        with self.execution.coordinator._transaction() as conn:
            row = self.execution.coordinator._row(conn, request_id)
            existing = conn.execute("SELECT * FROM verified_response_receipts WHERE request_id=?",
                                    (request_id,)).fetchone()
            if existing is not None:
                if (existing["attempt_id"], existing["receipt_sha256"], existing["receipt_size"],
                        existing["receipt_media_type"], existing["receipt_path"]) != (
                        row["attempt_id"], receipt_ref.sha256, receipt_ref.size,
                        receipt_ref.media_type, receipt_ref.path):
                    raise VerifiedExecutionError("conflicting response receipt for attempt")
                return
            if row["state"] not in ("dispatch_intent", "outcome_unknown"):
                raise VerifiedExecutionError("terminal request cannot accept a new receipt")
            conn.execute("""INSERT INTO verified_response_receipts
                (request_id,attempt_id,receipt_sha256,receipt_size,receipt_media_type,receipt_path)
                VALUES (?,?,?,?,?,?)""", (request_id, row["attempt_id"], receipt_ref.sha256,
                                          receipt_ref.size, receipt_ref.media_type, receipt_ref.path))

    def receipt_for(self, request_id):
        """Return the indexed receipt, if one was durably recorded."""
        with self.execution.coordinator._transaction() as conn:
            row = conn.execute("SELECT * FROM verified_response_receipts WHERE request_id=?",
                               (request_id,)).fetchone()
            if row is None:
                return None
            return ArtifactRef(1, row["receipt_sha256"], row["receipt_size"],
                               row["receipt_media_type"], row["receipt_path"])

    def discover_orphan_receipt(self, request_id, token, *, max_objects=10000):
        """Scan private published objects, then index one verified matching receipt."""
        _text(request_id, "request_id")
        _text(token, "token")
        if type(max_objects) is not int or max_objects < 1:
            raise VerifiedExecutionError("max_objects must be a positive integer")
        try:
            store_mode = self.artifact_root.lstat().st_mode
        except FileNotFoundError as exc:
            raise VerifiedExecutionError("artifact store directory is missing") from exc
        if not stat.S_ISDIR(store_mode):
            raise VerifiedExecutionError("artifact store must be a real directory")
        objects = self.artifact_root / "objects"
        try:
            root_mode = objects.lstat().st_mode
        except FileNotFoundError as exc:
            raise VerifiedExecutionError("artifact objects directory is missing") from exc
        if not stat.S_ISDIR(root_mode):
            raise VerifiedExecutionError("artifact objects directory is not a real directory")
        matches = []
        count = 0
        with os.scandir(objects) as shards:
            for shard in shards:
                if not _SHARD.fullmatch(shard.name) or not stat.S_ISDIR(shard.stat(follow_symlinks=False).st_mode):
                    raise VerifiedExecutionError("unexpected or symlinked artifact shard")
                with os.scandir(shard.path) as files:
                    for item in files:
                        if item.name.startswith(".artifact-"):
                            continue  # An unpublished temporary file is not evidence.
                        mode = item.stat(follow_symlinks=False).st_mode
                        if not _OBJECT.fullmatch(item.name) or not item.name.startswith(shard.name) or not stat.S_ISREG(mode):
                            raise VerifiedExecutionError("unexpected or symlinked artifact object")
                        count += 1
                        if count > max_objects:
                            raise VerifiedExecutionError("artifact discovery object cap exceeded")
                        ref = ArtifactRef(1, item.name, item.stat(follow_symlinks=False).st_size,
                                          "application/json", f"objects/{shard.name}/{item.name}")
                        data = read_artifact(self.artifact_root, ref)
                        try:
                            record = json.loads(data)
                        except (UnicodeError, json.JSONDecodeError):
                            continue  # Raw binary or non-JSON provider output has no receipt marker.
                        if not isinstance(record, dict):
                            continue
                        signals = len(set(record) & {"attempt_id", "manifest_digest", "input_digest", "source_id"})
                        receipt_like = set(record) == _RECEIPT_KEYS or (
                            record.get("request_id") == request_id and signals >= 2) or (
                            record.get("request_id") == request_id and
                            record.get("artifact_kind") == "verified_response_receipt")
                        if not receipt_like:
                            continue
                        if set(record) != _RECEIPT_KEYS or type(record.get("schema_version")) is not int or record["schema_version"] != 1:
                            raise VerifiedExecutionError("malformed or unsupported receipt-like artifact")
                        try:
                            json.loads(data, object_pairs_hook=_unique_pairs)
                        except (UnicodeError, json.JSONDecodeError) as exc:
                            raise VerifiedExecutionError("malformed receipt JSON") from exc
                        if record["request_id"] == request_id:
                            self._verify_receipt(request_id, token, ref)
                            matches.append(ref)
        indexed = self.receipt_for(request_id)
        if len(matches) > 1:
            raise VerifiedExecutionError("multiple conflicting attributable receipts; no receipt indexed")
        if indexed is not None and (not matches or matches[0] != indexed):
            raise VerifiedExecutionError("indexed receipt is missing or conflicts with discovered evidence")
        if not matches:
            return None
        if indexed is None:
            self._index_receipt(request_id, matches[0])
        return matches[0]

    def recover_discovered_response(self, request_id, token, *, max_objects=10000,
                                    billing_reason=None, settlement_id=None, charge=None,
                                    zero_charge_evidence=None):
        """Discover one attributable receipt and finish recovery without a model call."""
        receipt = self.discover_orphan_receipt(request_id, token, max_objects=max_objects)
        if receipt is None:
            raise VerifiedExecutionError("no attributable receipt found")
        return self.recover_response(request_id, token, receipt_ref=receipt,
                                     billing_reason=billing_reason,
                                     settlement_id=settlement_id, charge=charge,
                                     zero_charge_evidence=zero_charge_evidence)

    def record_unknown(self, request_id, token, evidence_id, billing_reason):
        """Record caller-observed uncertainty and retain the reservation as a hold."""
        return self.execution.complete(request_id, token, "outcome_unknown", evidence_id,
                                       billing_reason=billing_reason)

    def recover_response(self, request_id, token, *, receipt_ref=None,
                         billing_reason=None, settlement_id=None, charge=None,
                         zero_charge_evidence=None):
        """Verify attribution and bytes, then record response without any provider call."""
        indexed = self.receipt_for(request_id)
        if receipt_ref is None:
            if indexed is None:
                raise VerifiedExecutionError("no indexed receipt; an explicit receipt reference is required")
            receipt_ref = indexed
        elif indexed is not None and receipt_ref != indexed:
            raise VerifiedExecutionError("receipt conflicts with indexed attempt receipt")
        response = self._verify_receipt(request_id, token, receipt_ref)
        if indexed is None:
            self._index_receipt(request_id, receipt_ref)
        state = self.execution.get(request_id)
        request_state = state["request"]["state"]
        if request_state == "dispatch_intent":
            return self.execution.complete(
                request_id, token, "response_saved", receipt_ref.sha256,
                response_digest=response.sha256, billing_reason=billing_reason,
                settlement_id=settlement_id, charge=charge,
                zero_charge_evidence=zero_charge_evidence)
        if request_state == "outcome_unknown":
            if any(value is not None for value in (billing_reason, settlement_id, charge,
                                                    zero_charge_evidence)):
                raise VerifiedExecutionError("reconciliation does not settle cost; use settle_charge explicitly")
            return self.execution.reconcile(request_id, receipt_ref.sha256, "response_saved",
                                            response_digest=response.sha256)
        if request_state == "response_saved":
            if (state["request"]["evidence_id"], state["request"]["response_digest"]) != (
                    receipt_ref.sha256, response.sha256):
                raise VerifiedExecutionError("recorded response conflicts with verified receipt")
            return self.execution.complete(
                request_id, token, "response_saved", receipt_ref.sha256,
                response_digest=response.sha256, billing_reason=billing_reason,
                settlement_id=settlement_id, charge=charge,
                zero_charge_evidence=zero_charge_evidence)
        if request_state == "reconciled" and state["request"]["reconciliation_outcome"] == "response_saved":
            if any(value is not None for value in (billing_reason, settlement_id, charge,
                                                    zero_charge_evidence)):
                raise VerifiedExecutionError("reconciliation does not settle cost; use settle_charge explicitly")
            if (state["request"]["reconciliation_id"],
                    state["request"]["reconciliation_response_digest"]) != (
                    receipt_ref.sha256, response.sha256):
                raise VerifiedExecutionError("recorded reconciliation conflicts with verified receipt")
            return state
        raise VerifiedExecutionError("request state cannot accept a saved response")
