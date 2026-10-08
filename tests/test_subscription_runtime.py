"""Both CLI routes use generic planning/accounting without invoking a CLI."""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from classification_bench.adapter_runtime import registry
from classification_bench.adapters import TransportResult
from classification_bench.benchmark import (preview, preflight, run, report_snapshot, recover,
                                            status, export_predictions, BenchmarkError)
from classification_bench.manifest import canonical_bytes, digest
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
                   'preflight': adapter._preflight or self.preflight(adapter)}
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

    def configure_paid(self, *, kind='claude_code', state=False, approved=True, paid_cap=3, repeats=3):
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        approval = {'approved': True, 'request_cap': paid_cap, 'approved_at': now,
                    'source': 'explicit human paid credit permission; offline fixture'} if approved else None
        evidence = canonical_bytes({'fixture': True, 'extra_usage_disabled': state, 'approval': approval})
        evidence_path = self.config_path.parent / 'account-check.json'
        evidence_path.write_bytes(evidence)
        evidence_path.chmod(0o600)
        experiment = json.loads(Path(self.config['experiment']).read_text())
        experiment['repeats'] = repeats
        experiment['configs'] = [{'id': 'own-account', 'model': 'claude-fixture' if kind == 'claude_code' else 'gpt-fixture',
            'settings': {'adapter': kind, 'executable': '/usr/bin/true', 'cli_version': 'offline-fixture',
                'effort': 'medium', 'account_assertion': {'schema_version': 2, 'extra_usage_disabled': state,
                    'verified_at': now, 'source': 'enabled' if state is False else 'disabled' if state is True else 'billing setting unverified',
                    'paid_credit_authorization': approval, 'account_check_sha256': digest(evidence),
                    'account_check_file': str(evidence_path)}}}]
        Path(self.config['experiment']).write_text(json.dumps(experiment))
        self.config.update(currency='REQ', scale=1, cap=repeats, scope='fixture:subscription',
            authorization_file=str(self.config_path.parent / 'auth.json'),
            provider_limits={'claude_subscription': 1, 'chatgpt_subscription': 1})
        self.config_path.write_text(json.dumps(self.config))
        plan = preview(self.config_path)
        Path(self.config['authorization_file']).write_text(json.dumps({
            'schema_version': 1, 'run_sha256': plan['run_sha256'], 'plan_sha256': plan['plan_sha256'],
            'request_count': repeats, 'scope': self.config['scope'], 'cap': repeats}))
        return experiment['configs'][0], plan

    def test_authorized_paid_overage_is_telemetry_and_req_cost_remains_unknown(self):
        self.configure_paid()
        worker = FakeCLIWorker('overage')
        self.assertTrue(preflight(self.config_path, worker=worker)['ready'])
        self.assertFalse(Path(self.config['database']).exists())
        result = run(self.config_path, worker=worker)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(worker.calls, 3)
        operations = report_snapshot(self.config_path)['operations']
        for operation in operations:
            self.assertIsNone(operation['observed_cost_micro_usd'])
            self.assertEqual(operation['consumed_requests'], 1)
            evidence = operation['usage']['subscription']
            self.assertTrue(evidence['overage_observed'])
            self.assertTrue(evidence['paid_credit_authorized'])
            self.assertIsNone(evidence['actual_billed_usd'])
            self.assertIs(evidence['extra_usage_guard']['disabled'], False)
        recover(self.config_path)
        run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, 3)

    def test_unknown_billing_setting_can_use_explicit_paid_approval(self):
        self.configure_paid(kind='codex', state=None, repeats=1)
        worker = FakeCLIWorker()
        self.assertEqual(run(self.config_path, worker=worker)['status'], 'completed')
        evidence = report_snapshot(self.config_path)['operations'][0]['usage']['subscription']
        self.assertIsNone(evidence['extra_usage_guard']['disabled'])
        self.assertTrue(evidence['paid_credit_authorized'])
        self.assertIsNone(evidence['actual_billed_usd'])

    def test_enabled_without_paid_approval_cannot_dispatch(self):
        self.configure_paid(approved=False)
        worker = FakeCLIWorker('overage')
        self.assertFalse(preflight(self.config_path, worker=worker)['ready'])
        run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, 0)

    def test_paid_request_cap_cannot_be_smaller_than_the_scope(self):
        from classification_bench.subscription_assertions import SubscriptionAssertionError
        self.configure_paid(paid_cap=2)
        worker = FakeCLIWorker()
        with self.assertRaisesRegex(SubscriptionAssertionError, 'request cap exceeds'):
            run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, 0)

    def test_forged_receipt_approval_blocks_remaining_requests_and_restart(self):
        self.configure_paid()
        class ForgedWorker(FakeCLIWorker):
            def dispatch(self, adapter, prepared):
                result = super().dispatch(adapter, prepared)
                receipt = json.loads(result.raw_bytes)
                receipt['preflight']['extra_usage_guard']['paid_credit_authorization']['request_cap'] += 1
                return TransportResult(canonical_bytes(receipt), result.http_status, result.duration_ms)
        worker = ForgedWorker()
        result = run(self.config_path, worker=worker)
        self.assertEqual(result['status'], 'blocked_safety', result)
        self.assertEqual(worker.calls, 1)
        self.assertIn('billing policy receipt mismatch', result['admission_block']['reason'])
        recover(self.config_path)
        self.assertEqual(run(self.config_path, worker=worker)['status'], 'blocked_safety')
        self.assertEqual(worker.calls, 1)

    def test_paid_ambiguous_dispatch_is_never_automatically_replayed(self):
        self.configure_paid(kind='codex', state=None, repeats=1)
        class InterruptedWorker(FakeCLIWorker):
            def dispatch(self, adapter, prepared):
                self.calls += 1
                raise TimeoutError('offline interruption with uncertain acceptance')
        worker = InterruptedWorker()
        run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, 1)
        self.assertEqual(status(self.config_path)['states'], {'outcome_unknown': 1})
        recover(self.config_path)
        run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, 1)

    def test_paid_scope_still_blocks_isolation_failure(self):
        self.configure_paid()
        worker = FakeCLIWorker('tools')
        result = run(self.config_path, worker=worker)
        self.assertEqual(result['status'], 'blocked_safety')
        self.assertEqual(worker.calls, 1)
        self.assertIn('isolation violation', result['admission_block']['reason'])

    def test_paid_scope_still_blocks_quota_exhaustion(self):
        self.configure_paid(kind='codex', state=None)
        worker = FakeCLIWorker('quota')
        self.assertEqual(run(self.config_path, worker=worker)['status'], 'blocked_safety')
        self.assertEqual(worker.calls, 1)

    def test_paid_scope_still_blocks_model_mismatch(self):
        self.configure_paid()
        class MismatchWorker(FakeCLIWorker):
            def dispatch(self, adapter, prepared):
                result = super().dispatch(adapter, prepared)
                receipt = json.loads(result.raw_bytes)
                events = [json.loads(line) for line in receipt['stdout'].splitlines()]
                events[0]['model'] = 'claude-other-model'
                receipt['stdout'] = '\n'.join(json.dumps(event) for event in events)
                return TransportResult(canonical_bytes(receipt), 200, 1)
        worker = MismatchWorker()
        result = run(self.config_path, worker=worker)
        self.assertEqual(result['status'], 'blocked_safety')
        self.assertIn('model mismatch', result['admission_block']['reason'])
        self.assertEqual(worker.calls, 1)

    def test_mixed_subscription_scope_binds_one_frozen_request_per_configuration(self):
        import copy
        self.configure_paid(repeats=1, paid_cap=2)
        experiment = json.loads(Path(self.config['experiment']).read_text())
        second = copy.deepcopy(experiment['configs'][0])
        second.update(id='codex-account', model='gpt-fixture')
        second['settings']['adapter'] = 'codex'
        second['settings']['account_assertion']['extra_usage_disabled'] = None
        second_evidence = canonical_bytes({'fixture': True, 'extra_usage_disabled': None,
            'approval': second['settings']['account_assertion']['paid_credit_authorization']})
        second_path = self.config_path.parent / 'codex-account-check.json'
        second_path.write_bytes(second_evidence)
        second_path.chmod(0o600)
        second['settings']['account_assertion'].update(account_check_file=str(second_path),
            account_check_sha256=digest(second_evidence), source='Codex billing setting unverified; offline fixture')
        experiment['configs'].append(second)
        Path(self.config['experiment']).write_text(json.dumps(experiment))
        self.config['cap'] = 2
        self.config_path.write_text(json.dumps(self.config))
        plan = preview(self.config_path)
        self.assertEqual(plan['request_count'], 2)
        Path(self.config['authorization_file']).write_text(json.dumps({
            'schema_version': 1, 'run_sha256': plan['run_sha256'], 'plan_sha256': plan['plan_sha256'],
            'request_count': 2, 'scope': self.config['scope'], 'cap': 2}))
        class CountingWorker(FakeCLIWorker):
            def __init__(self):
                super().__init__()
                self.routes = []
            def dispatch(self, adapter, prepared):
                self.routes.append(adapter.kind)
                return super().dispatch(adapter, prepared)
        worker = CountingWorker()
        self.assertEqual(run(self.config_path, worker=worker)['status'], 'completed')
        self.assertEqual(sorted(worker.routes), ['claude_code', 'codex'])
        operations = report_snapshot(self.config_path)['operations']
        self.assertEqual(sorted(row['config_id'] for row in operations), ['codex-account', 'own-account'])
        guards = [row['usage']['subscription']['admitted_extra_usage_guard'] for row in operations]
        self.assertEqual({guard['run_sha256'] for guard in guards}, {plan['run_sha256']})
        self.assertEqual({guard['config_id'] for guard in guards}, {'codex-account', 'own-account'})
        self.assertEqual(len({guard['configuration_sha256'] for guard in guards}), 2)
        self.assertEqual({guard['paid_credit_authorization']['request_cap'] for guard in guards}, {2})
        run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, 2)
        # Adding another repeat changes the frozen plan and invalidates the grant.
        experiment['repeats'] = 2
        Path(self.config['experiment']).write_text(json.dumps(experiment))
        with self.assertRaisesRegex(BenchmarkError, 'authorization does not match'):
            run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, 2)

    def test_orphan_paid_receipt_recovers_under_admitted_policy_after_later_deny(self):
        from classification_bench.benchmark import _load, _initialize
        from classification_bench.subscription_assertions import SubscriptionAssertionLedger
        cfg, plan = self.configure_paid(repeats=1)
        worker = FakeCLIWorker('overage')
        with patch('classification_bench.benchmark._save_observation', side_effect=RuntimeError('offline saved-receipt interruption')):
            with self.assertRaisesRegex(RuntimeError, 'saved-receipt interruption'):
                run(self.config_path, worker=worker)
        self.assertEqual(worker.calls, 1)
        self.assertEqual(status(self.config_path)['states'], {'dispatch_intent': 1})
        config, _, binding, materials, _ = _load(self.config_path)
        verified = _initialize(config, binding, materials)
        ledger = SubscriptionAssertionLedger(verified.execution, verified.artifact_root)
        current = ledger.current(config['scope'], binding, cfg['id'])
        evidence = canonical_bytes({'fixture': True, 'extra_usage_disabled': True, 'paid_approval': None})
        ledger.renew({'schema_version': 2, 'renewal_id': 'later-deny', 'scope': config['scope'],
            'run_sha256': binding, 'config_id': cfg['id'], 'configuration_sha256': digest(canonical_bytes(cfg)),
            'adapter': 'claude_code', 'expected_revision': 0, 'extra_usage_disabled': True,
            'verified_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'source': 'later fixture disables paid usage', 'account_check_sha256': digest(evidence),
            'paid_credit_authorization': None}, evidence)
        recover(self.config_path)
        row = report_snapshot(self.config_path)['operations'][0]
        self.assertEqual(row['parsed_status'], 'valid')
        self.assertTrue(row['usage']['subscription']['paid_credit_authorized'])
        self.assertEqual(row['usage']['subscription']['admitted_extra_usage_guard']['assertion_id'], current['assertion_id'])
        self.assertEqual(run(self.config_path, worker=worker)['status'], 'completed')
        self.assertEqual(worker.calls, 1)
