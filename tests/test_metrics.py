"""Metrics preserve observed counters and exclude incomparable quota windows."""
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import NativeWorkflowConnection, native_token_snapshot, quota_window_changes, quota_windows


class MetricsTests(unittest.TestCase):
    def test_token_usage_requires_valid_complete_core_counters(self):
        counters = {'inputTokens': 7, 'cachedInputTokens': 3, 'outputTokens': 2,
                    'reasoningOutputTokens': 1, 'totalTokens': 9}
        self.assertEqual(native_token_snapshot({'last': counters, 'total': counters})['last'], counters)
        invalid = dict(counters, totalTokens=True)
        self.assertIsNone(native_token_snapshot({'last': invalid, 'total': counters}))
        self.assertIsNone(native_token_snapshot({'last': counters}))

    def test_quota_compares_same_window_only(self):
        before = {('standard', 'primary'): (10, 300, 500)}
        for row in [(11, 300, 700), (11, 400, 500), (9, 300, 500)]:
            self.assertIsNone(quota_window_changes(before, {('standard', 'primary'): row}, 100))
        self.assertIsNone(quota_window_changes(before, before, 500))
        self.assertIsNone(quota_window_changes(before, {('other', 'primary'): (12, 300, 500)}, 100))
        change = quota_window_changes(before, {('standard', 'primary'): (12, 300, 500)}, 100)
        self.assertEqual(change[0]['deltaPercentagePoints'], 2)
        self.assertEqual(quota_window_changes(before, before, 100)[0]['deltaPercentagePoints'], 0)
        self.assertEqual(quota_windows({'rateLimits': {'primary': {'usedPercent': 3}}}), {})

    def test_timing_requires_one_matching_terminal_event_even_when_interrupted(self):
        backend = NativeWorkflowConnection.__new__(NativeWorkflowConnection)
        backend.thread_id = 'work'
        observed = {'terminalStatus': None, 'elapsedSeconds': None, 'lastReportedTokens': None}
        backend._measured_turn = {'id': 'current', 'started': 3.0, 'observation': observed}
        backend._work_turn_measurements = [observed]
        backend._latest_usage = backend._quota_first = None
        event = {'method': 'turn/completed', 'params': {
            'threadId': 'work', 'turn': {'id': 'current', 'status': 'interrupted'}}}
        with patch('modelmate.time.monotonic', return_value=5.0):
            backend._observe_measurement(dict(event, params=dict(event['params'], threadId='unrelated')))
            self.assertIsNone(backend.workflow_measurements()['turnElapsedSeconds'])
            backend._observe_measurement(event)
            backend._observe_measurement(event)
        result = backend.workflow_measurements()
        self.assertEqual(result['timedTurns'], 1)
        self.assertEqual(result['turnElapsedSeconds'], 2.0)
        self.assertEqual(result['workTurnMeasurements'], [{
            'terminalStatus': 'interrupted', 'elapsedSeconds': 2.0, 'lastReportedTokens': None}])
        self.assertIsNone(result['tokenUsage'])

    def test_final_quota_observation_checks_account_identity_and_uses_metadata_only(self):
        backend = NativeWorkflowConnection.__new__(NativeWorkflowConnection)
        backend.account_id = 'expected'
        backend._latest_usage = None
        backend._work_turn_measurements = []
        backend._quota_first = {('models', 'primary'): (4, 300, int(time.time()) + 600)}
        reset = backend._quota_first['models', 'primary'][2]

        for account, expected in [('foreign', None), ('expected', 2)]:
            backend.request = Mock(side_effect=[{'account': {'type': 'chatgpt'}}, {
                'accountId': account, 'rateLimitsByLimitId': {'models': {
                    'primary': {'usedPercent': 6, 'windowDurationMins': 300, 'resetsAt': reset}}}}])
            change = backend.workflow_measurements()['quotaWindowChanges']
            self.assertEqual(change[0]['deltaPercentagePoints'] if change else None, expected)
            self.assertEqual([call.args[0] for call in backend.request.call_args_list],
                             ['account/read', 'account/rateLimits/read'])
