"""Native runtime admission, evidence, billing holds and restart without network."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from classification_bench.adapter_runtime import DecisionRuntime
from classification_bench.adapters import TransportResult
from classification_bench.benchmark import preview, run, recover, report_snapshot
from classification_bench.decision_adapters import CONTRACTS, DecisionAdapter
from classification_bench.isolation import IsolationUnavailable
from classification_bench.manifest import canonical_bytes


class DecisionRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        task = {'name': 'fictional-routing', 'input_keys': ['text'],
                'fields': [{'name': 'kind', 'labels': ['a', 'b']}]}
        configs = []
        for kind, contract in CONTRACTS.items():
            if contract['provider'] == 'cloudflare':
                continue
            settings = {'adapter': kind, 'billing_snapshot': {
                'source_url': contract['billing_url'], 'response_sha256': 'a' * 64,
                'observed_at': '2026-09-30T00:00:00Z',
                'valid_until': '2026-10-01T00:00:00Z',
                'max_input_tokens': contract['context'] or 65536,
                'input_usd_per_token': '0', 'output_usd_per_token': '0',
                'request_usd': '0', 'basis': 'free'}}
            if kind == 'qwen_decision':
                settings.update(workspace_id='123456', region='cn-beijing')
            configs.append({'id': kind, 'model': contract['model'], 'settings': settings})
        experiment = {'configs': configs, 'prompts': [{'id': 'p', 'text': 'Classify.'}],
                      'repeats': 1, 'batch_size': 1}
        inputs = {'records': [{'id': 'i', 'input': {'text': 'fictional example'}}]}
        self.config = dict(schema_version=1, task=str(self.root/'task.json'),
                           experiment=str(self.root/'experiment.json'),
                           inputs=str(self.root/'inputs.json'),
                           database=str(self.root/'run.sqlite'), artifacts=str(self.root/'artifacts'),
                           scope='native:offline-fixture', cap=3, currency='USD', scale=1000000,
                           max_concurrency=1, provider_limits={c['provider']: 1 for c in CONTRACTS.values()},
                           authorization_file=str(self.root/'authorization.json'),
                           on_budget_exhausted='pause')
        self.path = self.root/'config.json'
        for name, value in [('task', task), ('experiment', experiment), ('inputs', inputs)]:
            (self.root/f'{name}.json').write_text(json.dumps(value))
        self.authorize_fixture()
        # This test grant only reaches a patched deterministic transport. It is
        # not a provider authorization or a genuine billing snapshot.
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {c['credential']: 'fixture-only' for c in CONTRACTS.values()}, clear=True).start()
        patch.object(DecisionAdapter, 'verify_live_snapshot', return_value={
            'billing_response_sha256': 'a' * 64}).start()
        self.calls = []
        self.dispatch = patch('classification_bench.decision_network.isolated_decision_dispatch',
                              side_effect=self.response).start()
        self.worker = Mock()

    def authorize_fixture(self):
        self.path.write_text(json.dumps(self.config))
        proposal = preview(self.path)
        Path(self.config['authorization_file']).write_text(json.dumps({
            'schema_version': 1, 'run_sha256': proposal['run_sha256'],
            'plan_sha256': proposal['plan_sha256'], 'request_count': proposal['request_count'],
            'scope': self.config['scope'], 'cap': self.config['cap']}))

    def response(self, adapter, prepared, api_key, *, worker):
        self.calls.append(prepared.request_id)
        self.assertEqual(api_key, 'fixture-only')
        body = json.loads(prepared.body)
        answers = {name: {'type': 'choice', 'choice': 'a',
                          'probabilities': {'a': 0.75, 'b': 0.25}, 'confidence': 0.6}
                   for name in body['questions']}
        return TransportResult(canonical_bytes({'model': adapter.model, 'answers': answers,
                               'request_id': 'provider-' + prepared.request_id,
                               'usage': {'input_tokens': 17, 'output_tokens': 0}}), 200, 5)

    def test_all_native_routes_preserve_usage_cost_holds_and_no_replay(self):
        result = run(self.path, worker=self.worker)
        self.assertEqual(result['states'], {'response_saved': 3})
        self.assertEqual(result['parsed_statuses'], {'valid': 3})
        self.assertEqual(result['budget']['known_charges'], 0)
        self.assertEqual(result['budget']['unknown_holds'], 3)
        snapshot = report_snapshot(self.path)
        self.assertEqual(len(snapshot['predictions']['records']), 3)
        self.assertEqual(len(self.calls), 3)
        for operation in snapshot['operations']:
            self.assertEqual((operation['input_tokens'], operation['output_tokens']), (17, 0))
            self.assertIsNone(operation['observed_cost_micro_usd'])
            self.assertEqual(operation['unresolved_hold_micro_usd'], 1)
            self.assertEqual(operation['usage']['decision_answers']['kind']['confidence'], 0.6)
            self.assertEqual(operation['provider_identity_status'], 'model-echoed;provider-unverified')
        run(self.path, worker=self.worker)
        self.assertEqual(len(self.calls), 3)

    def test_receipt_recovery_reconstructs_choice_binding_without_dispatch(self):
        with patch('classification_bench.benchmark._save_observation', side_effect=RuntimeError('fixture crash')):
            with self.assertRaisesRegex(RuntimeError, 'fixture crash'):
                run(self.path, worker=self.worker)
        self.assertEqual(len(self.calls), 1)
        first = self.calls[0]
        self.assertEqual(recover(self.path)['unresolved'], [])
        self.assertEqual(len(report_snapshot(self.path)['predictions']['records']), 1)
        run(self.path, worker=self.worker)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.calls.count(first), 1)

    def test_budget_pause_does_not_release_native_unknown_charges(self):
        self.config['cap'] = 1
        self.authorize_fixture()
        result = run(self.path, worker=self.worker)
        self.assertEqual(result['status'], 'paused_budget')
        self.assertEqual(result['budget']['unknown_holds'], 1)
        self.assertEqual(len(self.calls), 1)
        run(self.path, worker=self.worker)
        self.assertEqual(len(self.calls), 1)

    def test_budget_stop_preserves_holds_and_stays_stopped(self):
        self.config.update(cap=1, on_budget_exhausted='stop')
        self.authorize_fixture()
        result = run(self.path, worker=self.worker)
        self.assertEqual(result['status'], 'stopped_budget')
        self.assertEqual(result['budget']['unknown_holds'], 1)
        self.assertEqual(run(self.path, worker=self.worker)['status'], 'stopped_budget')
        self.assertEqual(len(self.calls), 1)

    def test_preflight_failure_never_dispatches_or_reserves(self):
        self.worker.probe_endpoint.side_effect = IsolationUnavailable('fixture denial')
        result = run(self.path, worker=self.worker)
        self.dispatch.assert_not_called()
        self.assertEqual(result['preflight_failed_requests'], 3)
        self.assertEqual(result['budget']['unknown_holds'], 0)
        self.assertEqual(result['budget']['active_reservations'], 0)
        self.assertEqual(self.worker.probe_endpoint.call_count, 3)

    def test_uncertain_transport_retains_holds_and_never_replays(self):
        def uncertain(adapter, prepared, api_key, *, worker):
            self.calls.append(prepared.request_id)
            return TransportResult(b'', None, 5, 'TimeoutError')
        self.dispatch.side_effect = uncertain
        result = run(self.path, worker=self.worker)
        self.assertEqual(result['states'], {'outcome_unknown': 3})
        self.assertEqual(result['budget']['unknown_holds'], 3)
        run(self.path, worker=self.worker)
        self.assertEqual(len(self.calls), 3)

    def test_native_credentials_cannot_reuse_generic_key(self):
        for kind, contract in CONTRACTS.items():
            runtime = DecisionRuntime(kind)
            with self.assertRaises(ValueError):
                runtime.credential('wrong-provider-fixture')
            with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'wrong-provider-fixture'}, clear=True):
                with self.assertRaisesRegex(ValueError, contract['credential']):
                    runtime.credential(None)

    def test_clef_routes_run_from_successful_rest_envelopes(self):
        configs = []
        for kind in ('clef_decide', 'clef_flash_decide'):
            contract = CONTRACTS[kind]
            configs.append({'id': kind, 'model': contract['model'], 'settings': {
                'adapter': kind, 'account_id': 'a' * 32,
                'billing_snapshot': {
                    'source_url': contract['billing_url'], 'response_sha256': 'a' * 64,
                    'observed_at': '2026-09-30T00:00:00Z',
                    'valid_until': '2026-10-01T00:00:00Z',
                    'max_input_tokens': 65536,
                    'input_usd_per_token': str(contract['input_rate']),
                    'output_usd_per_token': '0', 'request_usd': '0',
                    'basis': 'metered'}}})
        experiment = json.loads((self.root/'experiment.json').read_text())
        experiment['configs'] = configs
        (self.root/'experiment.json').write_text(json.dumps(experiment))
        self.config['cap'] = 30000
        self.authorize_fixture()
        def cloudflare_response(adapter, prepared, api_key, *, worker):
            self.calls.append(prepared.request_id)
            self.assertEqual(api_key, 'clef-fixture-only')
            answers = {'kind': {'type': 'choice', 'choice': 'a',
                                'probabilities': {'a': 0.75, 'b': 0.25},
                                'confidence': 0.6}}
            return TransportResult(canonical_bytes({
                'success': True, 'errors': [], 'messages': [],
                'result': {'model': adapter.model, 'answers': answers,
                           'usage': {'input_tokens': 17, 'output_tokens': 0}}}), 200, 5)
        self.dispatch.side_effect = cloudflare_response
        with patch.dict(os.environ, {'CLOUDFLARE_CLEF_API_TOKEN': 'clef-fixture-only'}):
            result = run(self.path, worker=self.worker)
        self.assertEqual(result['states'], {'response_saved': 2})
        self.assertEqual(result['parsed_statuses'], {'valid': 2})
        self.assertEqual(result['budget']['unknown_holds'], 21628)
        operations = report_snapshot(self.path)['operations']
        self.assertEqual(sorted(op['unresolved_hold_micro_usd'] for op in operations),
                         [5899, 15729])
        self.assertEqual(len(self.calls), 2)
