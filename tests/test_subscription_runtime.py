"""Both CLI routes use generic planning/accounting without invoking a CLI."""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from classification_bench.adapter_runtime import registry
from classification_bench.adapters import TransportResult
from classification_bench.benchmark import (preview, preflight, run, report_snapshot, recover,
                                            status, export_predictions)
from classification_bench.manifest import canonical_bytes
from classification_bench.report import generate_report
from classification_bench.subscription_adapters import SubscriptionAdapter
from tests import test_adapter_runtime as fixtures


class FakeCLIWorker:
    def __init__(self, guard=None):
        self.calls = 0
        self.guard = guard

    def preflight(self, adapter):
        return {'authentication': 'fixture-account', 'identity_status': 'unavailable',
                'cli_version': adapter.cli_version, 'isolation': 'fixture-only'}

    def dispatch(self, adapter, prepared):
        self.calls += 1
        output = {'request_id': prepared.request_id, 'predictions': [
            {'id': rid, 'prediction': {'kind': 'b'}} for rid in prepared.expected_ids]}
        if adapter.kind == 'codex':
            events = [{'type': 'thread.started', 'thread_id': 'fixture-thread'},
                      {'type': 'turn.completed', 'usage': {'input_tokens': 12, 'output_tokens': 6}}]
        else:
            events = [{'type': 'system', 'subtype': 'init', 'model': adapter.model,
                       'tools': [], 'apiKeySource': 'none'},
                      {'type': 'result', 'subtype': 'success', 'is_error': False,
                       'session_id': 'fixture-session', 'structured_output': output,
                       'usage': {'input_tokens': 12, 'output_tokens': 6}}]
        if self.guard == 'quota':
            events = [{'type': 'turn.failed', 'error': {'message': 'usage limit reached'}}]
        elif self.guard == 'overage':
            events.append({'type': 'rate_limit_event', 'rate_limit_info': {'isUsingOverage': True}})
        elif self.guard == 'tools':
            events[0]['tools'] = ['Bash']
        receipt = {'schema_version': 1, 'adapter': adapter.kind,
                   'requested_model': adapter.model, 'requested_effort': adapter.effort,
                   'cli_version': adapter.cli_version, 'returncode': 0,
                   'stdout': '\n'.join(json.dumps(event) for event in events),
                   'stderr': '', 'final_text': json.dumps(output),
                   'preflight': self.preflight(adapter)}
        return TransportResult(canonical_bytes(receipt), 200, 5)


class SubscriptionRuntimeTests(unittest.TestCase):
    setUp = fixtures.RuntimeTests.setUp

    def exercise(self, kind, model, guard=None, *, effort='medium', cli_version='offline-fixture'):
        experiment = json.loads(Path(self.config['experiment']).read_text())
        repeats = 3 if guard else 1
        experiment['repeats'] = repeats
        experiment['configs'] = [{'id': 'own-account', 'model': model, 'model_type': 'llm',
                                 'settings': {'adapter': kind, 'executable': '/usr/bin/true',
                                    'cli_version': cli_version, 'effort': effort,
                                    'extra_usage_disabled': True,
                                    'extra_usage_verified_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                                    'extra_usage_source': 'offline test only'}}]
        Path(self.config['experiment']).write_text(json.dumps(experiment))
        self.config.update(currency='REQ', scale=1, cap=repeats, scope='fixture:subscription',
                           authorization_file=str(self.config_path.parent / 'auth.json'),
                           provider_limits={'claude_subscription': 1, 'chatgpt_subscription': 1})
        self.config_path.write_text(json.dumps(self.config))
        plan = preview(self.config_path)
        probe = FakeCLIWorker()
        self.assertTrue(preflight(self.config_path, worker=probe)['ready'])
        self.assertEqual(probe.calls, 0)
        self.assertFalse(Path(self.config['database']).exists())
        self.assertFalse(Path(self.config['artifacts']).exists())
        Path(self.config['authorization_file']).write_text(json.dumps({
            'schema_version': 1, 'run_sha256': plan['run_sha256'], 'plan_sha256': plan['plan_sha256'],
            'request_count': repeats, 'scope': self.config['scope'], 'cap': repeats}))
        worker = FakeCLIWorker(guard)
        result = run(self.config_path, worker=worker)
        if guard:
            self.assertEqual(result['status'], 'blocked_safety')
            self.assertIsNotNone(result['admission_block'])
            recover(self.config_path)
            restarted = run(self.config_path, worker=worker)
            self.assertEqual(restarted['status'], 'blocked_safety')
            self.assertEqual(worker.calls, 1)
            self.assertEqual(result['completed_requests'], 1)
            self.assertEqual(result['planned_requests'], 3)
            return
        self.assertEqual(result['states'], {'response_saved': 1})
        self.assertEqual(worker.calls, 1)
        snapshot = report_snapshot(self.config_path)
        self.assertEqual(snapshot['predictions']['records'][0]['prediction'], {'kind': 'b'})
        operation = snapshot['operations'][0]
        self.assertEqual(operation['effort'], effort)
        self.assertEqual(operation['returned_provider'],
                         'claude_subscription' if kind == 'claude_code' else 'chatgpt_subscription')
        self.assertEqual(operation['consumed_requests'], 1)
        self.assertIsNone(operation['observed_cost_micro_usd'])
        self.assertEqual(operation['input_tokens'], 12)
        self.assertEqual(operation['output_tokens'], 6)
        recover(self.config_path)
        run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, 1)
        if kind == 'codex':
            self.assertIn('unavailable', operation['provider_identity_status'])

    def test_codex_route_through_matrix(self):
        self.exercise('codex', 'gpt-fixture')

    def test_claude_route_through_matrix(self):
        self.exercise('claude_code', 'claude-fixture')

    def _historical_no_effort_evidence(self, model):
        def legacy_adapter(value):
            # Create saved fake receipts using the previously accepted controls.
            # Only the fixture bypasses new live validation; no CLI is invoked.
            adapter = SubscriptionAdapter({**value, 'model': 'claude-fixture'})
            adapter.model = value['model']
            adapter.config = json.loads(canonical_bytes(value))
            adapter._validate_live_controls = lambda: None
            return adapter

        with patch.object(registry.get('claude_code'), 'create_adapter', side_effect=legacy_adapter):
            self.exercise('claude_code', model, effort='not_applicable',
                          cli_version='2.1.293 (Claude Code)')
            original_plan = preview(self.config_path)
            original_snapshot = report_snapshot(self.config_path)
            original_html = generate_report(**original_snapshot)

        self.assertEqual(preview(self.config_path), original_plan)
        self.assertEqual(status(self.config_path)['states'], {'response_saved': 1})
        self.assertEqual(export_predictions(self.config_path), original_snapshot['predictions'])
        snapshot = report_snapshot(self.config_path)
        self.assertEqual(snapshot, original_snapshot)
        self.assertEqual(snapshot['operations'][0]['consumed_requests'], 1)
        self.assertEqual(snapshot['operations'][0]['effort'], 'not_applicable')
        self.assertEqual(generate_report(**snapshot), original_html)
        self.assertIn(model, original_html)
        worker = FakeCLIWorker()
        recover(self.config_path)
        self.assertEqual(run(self.config_path, worker=worker)['status'], 'completed')
        self.assertEqual(worker.calls, 0)

    def test_historical_haiku55_no_effort_status_export_report_and_recovery(self):
        self._historical_no_effort_evidence('claude-haiku-5-5')

    def test_historical_unknown_haiku_status_export_report_and_recovery(self):
        self._historical_no_effort_evidence('claude-haiku-3-5-20241022')

    def test_quota_exhaustion_blocks_remaining_work_and_restart(self):
        self.exercise('codex', 'gpt-fixture', 'quota')

    def test_observed_overage_blocks_remaining_work_and_restart(self):
        self.exercise('claude_code', 'claude-fixture', 'overage')

    def test_tool_isolation_failure_blocks_remaining_work_and_restart(self):
        self.exercise('claude_code', 'claude-fixture', 'tools')
