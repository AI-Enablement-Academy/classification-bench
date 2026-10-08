"""Request capacity is not monetary billing for account-backed execution."""
import json
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from classification_bench.adapter_runtime import registry
from classification_bench.adapters import TransportResult
from classification_bench.benchmark import preview, run, report_snapshot, recover
from tests import test_adapter_runtime as runtime_fixtures
from tests.test_adapter_runtime import OtherAdapter, AuthorizedOfflineFixtureRuntime


class RequestAdapter(OtherAdapter):
    def parse(self, *args, **kwargs):
        return replace(super().parse(*args, **kwargs), observed_cost_microusd=None)


class RequestRuntime(AuthorizedOfflineFixtureRuntime):
    accounting_currency = 'REQ'


class RequestAccountingTests(unittest.TestCase):
    setUp = runtime_fixtures.RuntimeTests.setUp

    def prepare(self, count=3, cap=2):
        registry.unregister('other-runtime')
        registry.register('other-runtime', RequestRuntime(RequestAdapter))
        Path(self.config['inputs']).write_text(json.dumps({'records': [
            {'id': str(i), 'input': {'text': 'example'}} for i in range(count)]}))
        self.config.update(scope='fixture:requests', currency='REQ', scale=1, cap=cap,
                           authorization_file=str(self.config_path.parent / 'auth.json'))
        self.config_path.write_text(json.dumps(self.config))
        planned = preview(self.config_path)
        Path(self.config['authorization_file']).write_text(json.dumps({
            'schema_version': 1, 'run_sha256': planned['run_sha256'],
            'plan_sha256': planned['plan_sha256'], 'request_count': count,
            'scope': self.config['scope'], 'cap': cap}))
        return planned

    def test_consumed_requests_exhaust_cap_without_inventing_usd(self):
        self.prepare()
        with patch.object(RequestAdapter, 'dispatch', autospec=True,
                          side_effect=OtherAdapter.dispatch) as dispatch:
            result = run(self.config_path)
            self.assertEqual(dispatch.call_count, 2)
            run(self.config_path)
            recover(self.config_path)
            self.assertEqual(dispatch.call_count, 2)
        self.assertEqual(result['states'].get('response_saved'), 2)
        operations = report_snapshot(self.config_path)['operations']
        self.assertEqual(sum(x['consumed_requests'] or 0 for x in operations), 2)
        for item in operations:
            self.assertIsNone(item['observed_cost_micro_usd'])
            self.assertIsNone(item['active_reserve_micro_usd'])
            self.assertEqual(item['subscription_cost_status'], 'unavailable')

    def test_ambiguous_dispatch_keeps_request_capacity_and_is_not_replayed(self):
        self.prepare(count=1, cap=1)
        with patch.object(RequestAdapter, 'dispatch', return_value=TransportResult(
                b'', None, 12, 'connection lost')) as dispatch:
            run(self.config_path)
            run(self.config_path)
            recover(self.config_path)
            self.assertEqual(dispatch.call_count, 1)
        operation = report_snapshot(self.config_path)['operations'][0]
        self.assertEqual(operation['unresolved_request_hold'], 1)
        self.assertIsNone(operation['consumed_requests'])
        self.assertIsNone(operation['unresolved_hold_micro_usd'])

    def test_subscription_scope_rejects_dollar_accounting(self):
        self.prepare(count=1, cap=1)
        self.config.update(currency='USD', scale=1_000_000)
        self.config_path.write_text(json.dumps(self.config))
        with self.assertRaisesRegex(ValueError, 'REQ'):
            preview(self.config_path)

    def test_saved_receipt_recovery_settles_capacity_without_another_dispatch(self):
        self.prepare(count=1, cap=1)
        with patch.object(RequestAdapter, 'dispatch', autospec=True,
                          side_effect=OtherAdapter.dispatch) as dispatch:
            with patch('classification_bench.benchmark._save_observation',
                       side_effect=OSError('interrupted after receipt')):
                with self.assertRaisesRegex(OSError, 'interrupted after receipt'):
                    run(self.config_path)
            recover(self.config_path)
            run(self.config_path)
            self.assertEqual(dispatch.call_count, 1)
        operation = report_snapshot(self.config_path)['operations'][0]
        self.assertEqual(operation['consumed_requests'], 1)
        self.assertIsNone(operation['observed_cost_micro_usd'])
        self.assertIsNone(operation['unresolved_request_hold'])

    def test_request_scope_cannot_bypass_paid_runtime_bounds(self):
        self.prepare(count=1, cap=1)
        registry.unregister('other-runtime')
        registry.register('other-runtime', AuthorizedOfflineFixtureRuntime(OtherAdapter))
        with self.assertRaisesRegex(ValueError, 'USD'):
            preview(self.config_path)


if __name__ == '__main__':
    unittest.main()
