"""Generate label-free, entirely synthetic offline framework fixtures."""
import hashlib
import json
import sys
from pathlib import Path

out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=True)
records = [{"id": f"s{i:02d}", "text": f"Synthetic feedback note {i:02d}."} for i in range(1, 11)]
responses = {
    "paired_P1": {"raw": json.dumps({"decisions": [{"id": r["id"], "label": "A"} for r in records]}, separators=(",", ":")), "reported_model": "fixture-model-v1"},
    "paired_P2": {"raw": json.dumps({"decisions": [{"id": r["id"], "label": "B"} for r in records]}, separators=(",", ":")), "reported_model": "fixture-model-v1"},
    "rate_limit": {"raw": '{"label":"A"}', "reported_model": "fixture-model-v1", "first_error": "429"},
    "invalid": {"raw": '{"label":"A",}', "reported_model": "fixture-model-v1"},
    "specialist": {"native": {"choice": "B", "probabilities": {"A": 0.1, "B": 0.7, "C": 0.1, "D": 0.1}}, "reported_model": "fixture-choice-v1"},
    "crash": {"raw": '{"label":"C"}', "reported_model": "fixture-model-v1"},
}
requests = {}
for condition in ("P1", "P2"):
    case = f"paired_{condition}"
    prompt = f"CONDITION={condition}\nReturn decisions as JSON.\n" + "\n".join(f'{r["id"]}: {r["text"]}' for r in records)
    requests[case] = {"case": case, "condition": condition, "members": [r["id"] for r in records], "prompt": prompt, "controls": {"temperature": 0, "max_tokens": 256, "model": "fixture-model-v1", "route": "offline-fixture"}}
for case in ("rate_limit", "invalid", "specialist", "crash"):
    requests[case] = {"case": case, "condition": "P1", "members": [records[0]["id"]], "prompt": f"CASE={case}\nReturn one synthetic decision as JSON.\n{records[0]['id']}: {records[0]['text']}", "controls": {"temperature": 0, "max_tokens": 256, "model": responses[case]["reported_model"], "route": "offline-fixture"}}
for request in requests.values():
    binding = {k: request[k] for k in ("condition", "members", "prompt", "controls")}
    request["identity_sha256"] = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
(out / "requests.json").write_text(json.dumps(requests, indent=2) + "\n")
(out / "responses.json").write_text(json.dumps(responses, indent=2) + "\n")
config = {
    "description": "Synthetic offline framework comparison; no references or model calls",
    "prompts": ["{{payload}}"],
    "providers": [{"id": f"file://{Path(__file__).with_name('provider.cjs').resolve()}", "label": "saved-fixture", "config": {"maxRetries": 0}}],
    "tests": [{"vars": {"payload": item["prompt"], "case_id": case}, "assert": [{"type": "is-json"}]} for case, item in requests.items() if case != "crash"],
    "evaluateOptions": {"cache": False, "maxConcurrency": 1},
}
(out / "promptfooconfig.json").write_text(json.dumps(config, indent=2) + "\n")
crash_config = dict(config)
crash_config["tests"] = [{"vars": {"payload": requests["crash"]["prompt"], "case_id": "crash"}, "assert": [{"type": "is-json"}]}]
(out / "promptfoo-crash-config.json").write_text(json.dumps(crash_config, indent=2) + "\n")
print("fixtures", len(requests), "paired_members_equal", requests["paired_P1"]["members"] == requests["paired_P2"]["members"])
