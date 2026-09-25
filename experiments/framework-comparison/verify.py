"""Fail closed unless both offline frameworks produced the expected evidence."""
import argparse
import json
from collections import Counter
from pathlib import Path

CORE = {'paired_P1', 'paired_P2', 'rate_limit', 'invalid', 'specialist'}
ALL = CORE | {'crash'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(out):
    requests = json.loads((out / 'requests.json').read_text())
    responses = json.loads((out / 'responses.json').read_text())
    require(set(requests) == ALL, 'missing or unexpected fixture requests')
    require(requests['paired_P1']['members'] == requests['paired_P2']['members'], 'paired membership or order drift')
    require(len(requests['paired_P1']['members']) == 10, 'paired batch is not ten records')
    require(requests['paired_P1']['identity_sha256'] != requests['paired_P2']['identity_sha256'], 'paired conditions have one identity')

    counts = {}
    for framework in ('inspect', 'promptfoo'):
        path = out / f'{framework}-attempts.jsonl'
        require(path.is_file(), f'missing {framework} attempt audit: {path}')
        attempts = [json.loads(row) for row in path.read_text().splitlines()]
        seen = Counter(row['case_id'] for row in attempts)
        require(set(seen) == ALL and all(seen[case] >= 1 for case in ALL), f'{framework} missing case attempts: {dict(seen)}')
        for row in attempts:
            case = row['case_id']
            require(bytes.fromhex(row['prompt_hex']).decode() == requests[case]['prompt'], f'{framework} prompt drift: {case}')
            require(row['request_identity'] == requests[case]['identity_sha256'], f'{framework} identity drift: {case}')
            require('reference' not in row and 'target' not in row, f'{framework} audit contains reference fields')
        counts[framework] = dict(seen)

    result_file = out / 'promptfoo-results.json'
    require(result_file.is_file(), f'missing promptfoo result export: {result_file}')
    results = json.loads(result_file.read_text())['results']['results']
    rows = {row['testCase']['vars']['case_id']: row for row in results}
    require(len(results) == 5 and set(rows) == CORE, 'promptfoo export does not cover five distinct non-crash cases')
    require(rows['paired_P1']['success'] and rows['paired_P2']['success'], 'paired prompt rows did not pass')
    for case in ('paired_P1', 'paired_P2'):
        require(rows[case].get('response', {}).get('output') == responses[case]['raw'], f'promptfoo saved response drift: {case}')
        require(rows[case].get('prompt', {}).get('raw') == requests[case]['prompt'], f'promptfoo exported prompt drift: {case}')
    require(not rows['rate_limit']['success'] and 'RateLimitExhaustedError' in rows['rate_limit'].get('error', ''), '429 row is not a transport error')
    require(not rows['invalid']['success'] and rows['invalid'].get('response', {}).get('output') == '{"label":"A",}', 'invalid JSON row was lost or repaired')
    require(rows['specialist']['success'] and rows['specialist'].get('response', {}).get('output') == {'choice': 'B', 'probabilities': {'A': 0.1, 'B': 0.7, 'C': 0.1, 'D': 0.1}}, 'specialist native object was not exported')

    try:
        from inspect_ai.log import read_eval_log
    except ImportError as ex:
        raise RuntimeError('Inspect log verification requires the pinned Inspect virtual environment') from ex
    log_dir = out / 'inspect-logs'
    require(log_dir.is_dir(), f'missing Inspect log directory: {log_dir}')
    observed = {}
    for path in log_dir.glob('*.eval'):
        log = read_eval_log(str(path))
        if log.samples:
            case = log.samples[0].id
            if case not in CORE:
                continue
            events = [event for event in log.samples[0].events if event.event == 'model']
            if log.status == 'success' and events:
                for event in events:
                    if event.call is not None:
                        content = event.call.request['messages'][-1]['content']
                        if content.startswith('attachment://'):
                            content = log.samples[0].attachments[content.removeprefix('attachment://')]
                        require(content == requests[case]['prompt'], f'Inspect raw call prompt drift: {case}')
                        require(event.call.request['controls'] == requests[case]['controls'], f'Inspect raw call controls drift: {case}')
                observed[case] = {'status': log.status, 'model_events': len(events), 'error_events': sum(event.error is not None for event in events), 'raw_calls': sum(event.call is not None for event in events), 'completion': log.samples[0].output.completion}
                if case == 'specialist':
                    observed[case]['native'] = next((event.call.response.get('native') for event in events if event.call), None)
        elif log.status == 'started':
            observed['crash'] = {'status': log.status, 'samples': 0}
    require(set(observed) == ALL, f'Inspect logs do not cover all cases: {sorted(observed)}')
    for case in CORE:
        require(observed[case]['raw_calls'] >= 1, f'Inspect missing raw call: {case}')
    require(observed['rate_limit']['model_events'] >= 2 and observed['rate_limit']['error_events'] >= 1, 'Inspect retry history missing')
    require(observed['invalid']['completion'] == '{"label":"A",}', 'Inspect invalid raw output missing')
    require(observed['specialist']['native'] == {'choice': 'B', 'probabilities': {'A': 0.1, 'B': 0.7, 'C': 0.1, 'D': 0.1}}, 'Inspect native call object missing')
    return {'matrix': 'paired identities distinct; membership/order equal', 'audit_prompt_bytes': 'exact', 'counts': counts, 'promptfoo_export_rows': len(rows), 'inspect_saved_logs': {case: {k: v for k, v in result.items() if k not in ('completion', 'native')} for case, result in sorted(observed.items())}}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('out', type=Path)
    args = p.parse_args()
    print(json.dumps(verify(args.out), indent=2))
