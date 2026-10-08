"""Versioned provenance for deterministic categorical scoring and case analysis.

Source hashes identify the selected local implementation. They do not capture a
Python environment, authenticate references, or attest provider execution.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path


class EvaluationProvenanceError(ValueError):
    pass


_SCOPES = {
    "categorical_evaluation": {
        "algorithm": "categorical_reference_agreement",
        "algorithm_version": 1,
        "sources": ("core.py", "evaluation_provenance.py"),
    },
    "categorical_case_analysis": {
        "algorithm": "categorical_run_case_comparisons",
        "algorithm_version": 1,
        "sources": ("core.py", "evaluation_provenance.py", "model_metadata.py", "report_analysis.py"),
    },
}
_SOURCE_KEYS = {"task", "plan", "labels", "predictions"}


def _digest(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvaluationProvenanceError("evaluation provenance must be finite JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _hash(value, where):
    if (not isinstance(value, str) or len(value) != 64 or
            any(char not in "0123456789abcdef" for char in value)):
        raise EvaluationProvenanceError(f"{where}: expected lowercase SHA-256")


def current_provenance(*, scope="categorical_evaluation"):
    """Hash the installed source files in the declared scoring scope."""
    if not isinstance(scope, str) or scope not in _SCOPES:
        raise EvaluationProvenanceError("evaluation provenance: unsupported scope")
    definition = _SCOPES[scope]
    directory = Path(__file__).resolve().parent
    sources = {}
    for name in definition["sources"]:
        try:
            sources["classification_bench/" + name] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        except OSError as exc:
            raise EvaluationProvenanceError(f"evaluation provenance: cannot read scoring source {name}") from exc
    value = {"schema_version": 1, "scope": scope, "algorithm": definition["algorithm"],
             "algorithm_version": definition["algorithm_version"], "source_sha256": sources,
             "implementation_sha256": _digest(sources)}
    value["provenance_sha256"] = _digest(value)
    return value


def validate_provenance(value, *, scope=None, require_current=False):
    """Validate frozen provenance without reinterpreting it as the current build.

    Historical records may name a different algorithm version or source hashes.
    Current matching is an explicit scoring prerequisite, not a read prerequisite.
    """
    keys = {"schema_version", "scope", "algorithm", "algorithm_version", "source_sha256",
            "implementation_sha256", "provenance_sha256"}
    if not isinstance(value, dict) or set(value) != keys:
        raise EvaluationProvenanceError("evaluation provenance: missing or unknown fields")
    if type(require_current) is not bool:
        raise EvaluationProvenanceError("require_current: expected boolean")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise EvaluationProvenanceError("evaluation provenance: expected schema_version 1")
    selected = value["scope"]
    if not isinstance(selected, str) or selected not in _SCOPES or (scope is not None and selected != scope):
        raise EvaluationProvenanceError("evaluation provenance: unexpected scope")
    definition = _SCOPES[selected]
    if value["algorithm"] != definition["algorithm"]:
        raise EvaluationProvenanceError("evaluation provenance: unexpected algorithm")
    if type(value["algorithm_version"]) is not int or value["algorithm_version"] < 1:
        raise EvaluationProvenanceError("evaluation provenance: expected positive algorithm version")
    sources = value["source_sha256"]
    if (not isinstance(sources, dict) or
            set(sources) != {"classification_bench/" + name for name in definition["sources"]}):
        raise EvaluationProvenanceError("evaluation provenance: source scope mismatch")
    for name, source_hash in sources.items():
        _hash(source_hash, name)
    for name in ("implementation_sha256", "provenance_sha256"):
        _hash(value[name], name)
    if value["implementation_sha256"] != _digest(sources):
        raise EvaluationProvenanceError("evaluation provenance: implementation hash mismatch")
    body = {key: item for key, item in value.items() if key != "provenance_sha256"}
    if value["provenance_sha256"] != _digest(body):
        raise EvaluationProvenanceError("evaluation provenance: provenance hash mismatch")
    if require_current and value != current_provenance(scope=selected):
        raise EvaluationProvenanceError(
            "frozen evaluator differs from the current scoring implementation; "
            "use standalone evaluate for a new current-version evaluation or prepare a new report workflow")
    return deepcopy(value)


def evaluation_identity(source_hashes, provenance):
    """Bind scoring identity to four logical inputs and the evaluator provenance."""
    value = validate_provenance(provenance, scope="categorical_evaluation")
    if not isinstance(source_hashes, dict) or set(source_hashes) != _SOURCE_KEYS:
        raise EvaluationProvenanceError("evaluation sources: expected task, plan, labels and predictions")
    for name, source_hash in source_hashes.items():
        if source_hash is None and name == "labels":
            continue
        _hash(source_hash, "evaluation source " + name)
    return _digest({"schema_version": 1, "source_hashes": source_hashes,
                    "evaluation_provenance_sha256": value["provenance_sha256"]})
