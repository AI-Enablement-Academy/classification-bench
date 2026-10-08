"""Allowlisted operator model declarations, separate from experimental results."""

from copy import deepcopy
from html import escape

from .core import MODEL_METADATA_AXES, _digest, validate_model_metadata


AXIS_LABELS = {"family": "Model family", "declared_purpose": "Declared purpose",
               "training_lineage": "Training lineage"}
STATUS_LABELS = {"unknown": "Unknown", "operator_declared": "Operator declaration",
                 "operator_verified": "Operator verified declaration"}
VERIFICATION_NOTE = "Operator-supplied declarations; the harness has not independently verified their sources or claims."


def project_model_metadata(config):
    """Return exact sourced claims and explicit unknowns without model-name inference."""
    supplied = "model_metadata" in config
    metadata = validate_model_metadata(config["model_metadata"]) if supplied else {"schema_version": 1}
    result = {"schema_version": 1, "supplied": supplied,
              "metadata_sha256": _digest(metadata) if supplied else None,
              "verification_note": VERIFICATION_NOTE}
    for axis in MODEL_METADATA_AXES:
        claim = metadata.get(axis, {"status": "unknown"})
        result[axis] = {key: deepcopy(claim.get(key)) for key in
                       ("status", "value", "provenance", "reviewed_at")}
        result[axis]["source_urls"] = list(claim.get("source_urls", []))
    return result


def export_model_metadata(config, *, private):
    """Private claims are allowlisted; sanitized output contains hashes/statuses only."""
    value = project_model_metadata(config)
    if private:
        return value
    return {"schema_version": 1, "supplied": value["supplied"],
            "metadata_sha256": value["metadata_sha256"],
            "verification_note": VERIFICATION_NOTE,
            **{axis: {"status": value[axis]["status"]} for axis in MODEL_METADATA_AXES}}


def render_model_metadata(config, *, heading="Model declarations"):
    """Semantic, no-JS-readable context with escaped text and validated citations."""
    value = project_model_metadata(config)
    h = lambda item: escape(str(item), quote=True)
    rows = []
    for axis in MODEL_METADATA_AXES:
        claim = value[axis]
        detail = "Unknown; no sourced declaration supplied."
        if claim["status"] != "unknown":
            detail = (f"<span>{h(claim['value'])}</span> <span>({h(STATUS_LABELS[claim['status']])})</span>"
                      f"<p>Provenance: {h(claim['provenance'])}</p>")
            if claim["reviewed_at"]:
                detail += f"<p>Operator review: <time datetime='{h(claim['reviewed_at'])}'>{h(claim['reviewed_at'])}</time></p>"
            if claim["source_urls"]:
                detail += "<ul>" + "".join(f"<li><a href='{h(url)}' rel='noopener noreferrer'>{h(url)}</a></li>"
                                           for url in claim["source_urls"]) + "</ul>"
        rows.append(f"<dt>{h(AXIS_LABELS[axis])}</dt><dd>{detail}</dd>")
    identity = f"<p>Metadata SHA-256: <code>{h(value['metadata_sha256'])}</code></p>" if value["supplied"] else "<p>Model metadata was not supplied.</p>"
    return ("<details class='model-declarations'><summary>" + h(heading) + "</summary>"
            "<dl>" + "".join(rows) + "</dl>" + identity + f"<p>{h(VERIFICATION_NOTE)}</p>"
            "<p>Reporting group, execution route and output interface remain separate. These declarations do not establish causes of observed performance.</p></details>")
