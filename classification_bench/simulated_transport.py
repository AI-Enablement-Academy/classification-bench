"""Pure offline fake response for a sandboxed child; no provider interface."""

import hashlib
from pathlib import Path


# This source runs with Python -I -S and can read only its request capsule.
WORKER_SOURCE = r'''
import json, sys
with open(sys.argv[1], 'rb') as source:
    request = json.load(source)
payload = json.loads(request['messages'][1]['content'])
mode = request['controls']['synthetic_response_mode']
predictions = []
if mode != 'missing':
    for item in payload['items']:
        values = {field['name']: field['labels'][0] for field in payload['fields']}
        if mode == 'invalid':
            values[payload['fields'][0]['name']] = '__invalid_synthetic_label__'
        predictions.append({'id': item['id'], 'prediction': values})
print(json.dumps({'schema_version': 1, 'request_id': request['request_id'],
                  'predictions': predictions}, sort_keys=True, separators=(',', ':')))
'''


def build_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def parse_response(response_bytes, request_id, expected_ids):
    """Check fake response identity and shape, preserving invalid label values."""
    import json

    try:
        response = json.loads(response_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("synthetic response is not UTF-8 JSON") from exc
    if (not isinstance(response, dict) or set(response) != {"schema_version", "request_id", "predictions"}
            or response["schema_version"] != 1 or response["request_id"] != request_id
            or not isinstance(response["predictions"], list)):
        raise ValueError("synthetic response identity or schema mismatch")
    seen = set()
    for item in response["predictions"]:
        if (not isinstance(item, dict) or set(item) != {"id", "prediction"}
                or item["id"] not in expected_ids or item["id"] in seen
                or not isinstance(item["prediction"], dict)):
            raise ValueError("synthetic response position mismatch")
        seen.add(item["id"])
    return response
