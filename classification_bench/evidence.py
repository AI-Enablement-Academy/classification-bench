"""Small offline artifact and parser-evidence primitives (schema version 1).

This module stores bytes and validates bindings. It does not execute parsers,
select attempts, dispatch requests, or enforce an event ledger.
"""

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path


class EvidenceError(ValueError):
    """An artifact or parsed-attempt binding is invalid."""


_HEX = re.compile(r"[0-9a-f]{64}\Z")
_MEDIA = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]*\Z")


@dataclass(frozen=True)
class ArtifactRef:
    schema_version: int
    sha256: str
    size: int
    media_type: str
    path: str


def _check_ref(ref):
    if not isinstance(ref, ArtifactRef) or type(ref.schema_version) is not int or ref.schema_version != 1:
        raise EvidenceError("expected artifact reference version 1")
    if not isinstance(ref.sha256, str) or not _HEX.fullmatch(ref.sha256):
        raise EvidenceError("invalid artifact SHA-256")
    if type(ref.size) is not int or ref.size < 0:
        raise EvidenceError("invalid artifact size")
    if not isinstance(ref.media_type, str) or not _MEDIA.fullmatch(ref.media_type):
        raise EvidenceError("invalid artifact media type")
    if ref.path != f"objects/{ref.sha256[:2]}/{ref.sha256}":
        raise EvidenceError("artifact path must be the relative content address")


def _sync_dir(path):
    handle = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def _check_directory(path):
    try:
        mode = Path(path).lstat().st_mode
    except FileNotFoundError as exc:
        raise EvidenceError("artifact store directory is missing") from exc
    if not stat.S_ISDIR(mode):
        raise EvidenceError("artifact store directory must not be a symlink or file")


def _ensure_directory(path):
    path = Path(path)
    try:
        path.mkdir(mode=0o700)
    except FileNotFoundError:
        _ensure_directory(path.parent)
        return _ensure_directory(path)
    except FileExistsError:
        pass
    _check_directory(path)
    # Sync even after a concurrent creator wins: publication must not rely on
    # that other writer reaching its own fsync before this writer returns.
    _sync_dir(path.parent)


def _object_dir(root, digest):
    root = Path(root)
    objects = root / "objects"
    shard = objects / digest[:2]
    for directory in (root, objects, shard):
        _ensure_directory(directory)
    return shard


def read_artifact(root, ref):
    """Read one content-addressed object, rejecting missing or altered bytes."""
    _check_ref(ref)
    path = Path(root) / ref.path
    _check_directory(Path(root))
    _check_directory(path.parent.parent)
    _check_directory(path.parent)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        handle = os.open(path, flags)
    except FileNotFoundError as exc:
        raise EvidenceError("artifact is missing") from exc
    except OSError as exc:
        raise EvidenceError(f"cannot open artifact: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(handle).st_mode):
            raise EvidenceError("artifact is not a regular file")
        with os.fdopen(handle, "rb") as source:
            handle = -1
            content = source.read()
    finally:
        if handle >= 0:
            os.close(handle)
    if len(content) != ref.size or hashlib.sha256(content).hexdigest() != ref.sha256:
        raise EvidenceError("artifact size or SHA-256 mismatch")
    return content


def put_artifact(root, content, media_type):
    """Durably publish bytes without replacing an existing content address.

    Concurrent identical writes deduplicate. Existing content is checked before
    reuse. A conflicting existing object fails without modifying that object.
    """
    if not isinstance(content, bytes):
        raise EvidenceError("artifact content must be bytes")
    digest = hashlib.sha256(content).hexdigest()
    ref = ArtifactRef(1, digest, len(content), media_type, f"objects/{digest[:2]}/{digest}")
    _check_ref(ref)
    shard = _object_dir(root, digest)
    destination = shard / digest
    handle, temporary = tempfile.mkstemp(prefix=".artifact-", dir=shard)
    try:
        with os.fdopen(handle, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            read_artifact(root, ref)
        else:
            _sync_dir(shard)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
            _sync_dir(shard)
    return ref


def _identity(value, name):
    if not isinstance(value, str) or not value or value != value.strip():
        raise EvidenceError(f"{name} must be a nonempty trimmed string")


def _validate_binding(record):
    required = {"schema_version", "request_id", "attempt_id", "parser_sha256",
                "response", "status", "prediction", "reason"}
    if not isinstance(record, dict) or set(record) != required or type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise EvidenceError("invalid parsed-attempt record schema")
    _identity(record["request_id"], "request_id")
    _identity(record["attempt_id"], "attempt_id")
    if not isinstance(record["parser_sha256"], str) or not _HEX.fullmatch(record["parser_sha256"]):
        raise EvidenceError("invalid parser SHA-256")
    try:
        response = ArtifactRef(**record["response"])
    except (TypeError, KeyError) as exc:
        raise EvidenceError("invalid response reference") from exc
    _check_ref(response)
    if record["status"] not in ("valid", "invalid", "unavailable"):
        raise EvidenceError("invalid parse status")
    prediction, reason = record["prediction"], record["reason"]
    if record["status"] == "valid":
        if not isinstance(prediction, dict) or not prediction or any(
                not isinstance(key, str) or not key or not isinstance(value, str)
                for key, value in prediction.items()):
            raise EvidenceError("valid projection requires a nonempty string-label map")
        if reason is not None:
            raise EvidenceError("valid projection cannot have an error reason")
    else:
        if prediction is not None:
            raise EvidenceError("invalid or unavailable projection cannot carry a prediction")
        if not isinstance(reason, dict) or set(reason) != {"code", "detail"} or not (
                isinstance(reason["code"], str) and _CODE.fullmatch(reason["code"])) or not (
                isinstance(reason["detail"], str) and reason["detail"]):
            raise EvidenceError("invalid or unavailable projection needs a structured reason")
    return response


def bind_parsed_attempt(root, response, request_id, attempt_id, parser_sha256,
                        status, prediction=None, reason=None):
    """Store an immutable parser result bound to verified original response bytes.

    ``valid`` means the caller's parser accepted the projection; this module
    checks its shape, not a task-specific vocabulary or the parser's judgment.
    """
    if not isinstance(response, ArtifactRef):
        raise EvidenceError("response must be an ArtifactRef")
    record = {"schema_version": 1, "request_id": request_id, "attempt_id": attempt_id,
              "parser_sha256": parser_sha256, "response": vars(response),
              "status": status, "prediction": prediction, "reason": reason}
    _validate_binding(record)
    read_artifact(root, response)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    return put_artifact(root, encoded, "application/json")


def load_parsed_attempt(root, binding, request_id, attempt_id, parser_sha256):
    """Verify both immutable files and the caller's expected source identities."""
    _check_ref(binding)
    if binding.media_type != "application/json":
        raise EvidenceError("parsed-attempt artifact must be application/json")
    try:
        record = json.loads(read_artifact(root, binding))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("parsed-attempt artifact is not UTF-8 JSON") from exc
    response = _validate_binding(record)
    if (record["request_id"], record["attempt_id"], record["parser_sha256"]) != (
            request_id, attempt_id, parser_sha256):
        raise EvidenceError("parsed-attempt source binding mismatch")
    read_artifact(root, response)
    return record
