"""Metrics preserve observed counters and exclude incomparable quota windows."""
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import (NativeWorkflowConnection, ProbeError, append_workflow_metrics,
                       native_token_snapshot, quota_window_changes, quota_windows)


class MetricsTests(unittest.TestCase):
    def test_jsonl_appends_only_metrics_to_a_private_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'metrics.jsonl'
            for attempt in (1, 2):
                append_workflow_metrics(path, {'state': 'DONE', 'attempts': attempt,
                    'quotaWindowChanges': [{'beforePercent': 15}], 'prompt': 'private', 'session': 'private'})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row['attempts'] for row in rows], [1, 2])
            self.assertEqual(rows[0]['schemaVersion'], 1)
            self.assertNotIn('quotaWindowChanges', rows[0])
            self.assertNotIn('private', path.read_text())

    def test_jsonl_rejects_symlinks_and_nonprivate_files(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'existing'
            path.write_text('original')
            path.chmod(0o644)
            with self.assertRaises(ProbeError):
                append_workflow_metrics(path, {})
            link = Path(root) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError):
                append_workflow_metrics(link, {})
            self.assertEqual(path.read_text(), 'original')

    def test_jsonl_partial_append_failure_preserves_existing_record(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'metrics.jsonl'
            append_workflow_metrics(path, {'state': 'DONE'})
            original = path.read_bytes()
            write = os.write
            with patch('modelmate.os.write') as mocked:
                def partial(fd, payload):
                    if mocked.call_count == 1:
                        return write(fd, payload[:8])
                    raise OSError('injected write failure')
                mocked.side_effect = partial
                with self.assertRaises(OSError):
                    append_workflow_metrics(path, {'state': 'PAUSED'})
            self.assertEqual(path.read_bytes(), original)

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
        backend._measured_turns = {'current': backend._measured_turn}
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

    def test_late_events_update_their_own_turn_without_exposing_native_ids(self):
        backend = NativeWorkflowConnection.__new__(NativeWorkflowConnection)
        backend.thread_id = 'work'
        first, second = [dict(terminalStatus=None, elapsedSeconds=None,
                             lastReportedTokens=None, modelReroutes=[]) for _ in range(2)]
        backend._measured_turns = {
            'earlier-native-id': {'id': 'earlier-native-id', 'started': 1.0, 'observation': first},
            'later-native-id': {'id': 'later-native-id', 'started': 4.0, 'observation': second}}
        backend._measured_turn = backend._measured_turns['later-native-id']
        backend._work_turn_measurements = [first, second]
        backend._latest_usage = backend._quota_first = None
        counters = dict(inputTokens=7, cachedInputTokens=3, outputTokens=2,
                        reasoningOutputTokens=1, totalTokens=9)
        usage = {'method': 'thread/tokenUsage/updated', 'params': {
            'threadId': 'work', 'turnId': 'earlier-native-id',
            'tokenUsage': {'last': counters, 'total': counters}}}
        terminal = {'method': 'turn/completed', 'params': {'threadId': 'work',
            'turn': {'id': 'earlier-native-id', 'status': 'failed'}}}
        with patch('modelmate.time.monotonic', return_value=6.0):
            backend._observe_measurement(usage)
            backend._observe_measurement(terminal)
            backend._observe_measurement(terminal)
            backend._observe_measurement(dict(usage, params=dict(usage['params'], turnId='unknown')))
            backend._observe_measurement(dict(usage, params=dict(usage['params'], threadId='foreign')))
        result = backend.workflow_measurements()
        self.assertEqual(first['lastReportedTokens'], counters)
        self.assertEqual(first['terminalStatus'], 'failed')
        self.assertEqual(result['timedTurns'], 1)
        self.assertEqual(result['turnElapsedSeconds'], 5.0)
        self.assertIsNone(second['lastReportedTokens'])
        self.assertIsNone(second['terminalStatus'])
        self.assertNotIn('native-id', json.dumps(result))

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


class PlannedTimingTests(unittest.TestCase):
    def test_total_wall_includes_both_phases_without_usage_invention(self):
        from modelmate import report_planned_workflow_timing
        output=io.StringIO()
        report=report_planned_workflow_timing(output,10,14,22)
        self.assertEqual(report['planningWallSeconds'],4)
        self.assertEqual(report['workflowWallSeconds'],8)
        self.assertEqual(report['totalWallSeconds'],12)
        self.assertIs(report['includesUserWait'],True)
        self.assertNotIn('tokenUsage',report)
        self.assertNotIn('reportedModels',report)
        self.assertIn('Plan-workflow timing:',output.getvalue())

    def test_cancelled_planning_has_no_workflow_duration(self):
        from modelmate import report_planned_workflow_timing
        report=report_planned_workflow_timing(io.StringIO(),10,15)
        self.assertEqual(report['totalWallSeconds'],5)
        self.assertIsNone(report['workflowWallSeconds'])

    def test_bad_clocks_never_produce_a_report(self):
        from modelmate import report_planned_workflow_timing
        for clocks in ((True,2,3),(1,float('nan'),3),(3,2,4),(1,3,2),(1,2,float('inf'))):
            output=io.StringIO()
            with self.subTest(clocks=clocks),self.assertRaises(ProbeError):
                report_planned_workflow_timing(output,*clocks)
            self.assertEqual(output.getvalue(),'')

    def test_report_write_failure_does_not_replace_work_result(self):
        from modelmate import report_planned_workflow_timing
        output=Mock();output.write.side_effect=OSError('closed output')
        self.assertEqual(report_planned_workflow_timing(output,10,14,22)['totalWallSeconds'],12)
