import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modelmate import ProbeError
from verify import VerificationConnection, choose_models, verify
from modelmate import ensure_quota


GOOD_QUOTA = {'ordinaryUsageAllowed': True, 'accountId': 'synthetic-account', 'rateLimits': {'primary': {'usedPercent': 30}}}


class VerificationTests(unittest.TestCase):
    def test_quota_fails_closed(self):
        for quota in [{}, {'ordinaryUsageAllowed': False}, {'ordinaryUsageAllowed': True},
                      {'ordinaryUsageAllowed': True, 'rateLimits': {'primary': {'usedPercent': 100}}},
                      {'ordinaryUsageAllowed': True, 'rateLimits': {'credits': {'hasCredits': True}}},
                      {'ordinaryUsageAllowed': True, 'rateLimits': {'primary': {'usedPercent': float('nan')}}}]:
            with self.subTest(quota=quota), self.assertRaises(ProbeError):
                ensure_quota(quota)
        ensure_quota(GOOD_QUOTA)

    def test_catalog_controls_model_and_effort(self):
        catalog = [{'model': name, 'defaultReasoningEffort': 'medium',
                    'supportedReasoningEfforts': [{'reasoningEffort': 'low'}, {'reasoningEffort': 'medium'}]}
                   for name in ['one', 'two']]
        self.assertEqual(choose_models(catalog, ['one', 'two']), [('one', 'low'), ('two', 'low')])
        for names in [['one', 'missing'], ['one', 'one']]:
            with self.assertRaises(ProbeError):
                choose_models(catalog, names)

    def connection(self):
        c = VerificationConnection([sys.executable, '-c', 'import time; time.sleep(30)'], 1)
        self.addCleanup(c.close)
        c.thread_id = 'thread'
        c.send = Mock()
        return c

    def test_approval_is_declined_never_accepted(self):
        c = self.connection()
        c.handle_event({'id': 99, 'method': 'item/fileChange/requestApproval',
                        'params': {'threadId': 'thread', 'turnId': 'turn', 'itemId': 'item'}})
        self.assertEqual(c.send.call_args.args[0], {'id': 99, 'result': {'decision': 'decline'}})
        self.assertEqual(c.denials, [('file', 'turn')])
        for message in [{'id': 100, 'method': 'unknown'},
                        {'id': 101, 'method': 'item/fileChange/requestApproval',
                         'params': {'threadId': 'other'}}]:
            with self.assertRaises(ProbeError):
                c.handle_event(message)
        self.assertEqual(c.send.call_count, 1)

    def test_events_before_rpc_response_are_retained(self):
        c = self.connection()
        def request(method, params=None):
            if method == 'account/read':
                return {'account': {'type': 'chatgpt'}}
            if method == 'account/rateLimits/read':
                return GOOD_QUOTA
            c.handle_event({'method': 'item/completed', 'params': {
                'threadId': 'thread', 'turnId': 'turn', 'item': {'type': 'agentMessage', 'text': 'answer'}}})
            c.handle_event({'method': 'turn/completed', 'params': {
                'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}})
            return {'turn': {'id': 'turn'}}
        c.request = Mock(side_effect=request)
        self.assertEqual(c.run_turn('prompt', 'one', 'low'), ('answer', set()))
        self.assertIsNone(c.turn_id)

    def test_unknown_quota_prevents_turn_start(self):
        c = self.connection()
        c.request = Mock(return_value={})
        with self.assertRaises(ProbeError):
            c.run_turn('prompt', 'one', 'low')
        c.request.assert_called_once_with('account/read', {'refreshToken': False})

    def test_synthetic_flow_and_no_nonce_in_second_prompt(self):
        c = Mock()
        c.turn_evidence = []
        c.request.return_value = {'thread': {'id': 'thread'}}
        c.run_turn.side_effect = [('ACK', set()), ('secret-code', set()), ('denied', {'command'}), ('denied', {'file'})]
        with tempfile.TemporaryDirectory() as tmp, patch('verify.secrets.token_hex', return_value='secret-code'):
            result = verify(c, [('one', 'low'), ('two', 'low')], Path(tmp))
        self.assertEqual(result['contextRecall'], 'passed')
        self.assertNotIn('secret-code', c.run_turn.call_args_list[1].args[0])
        self.assertEqual(c.run_turn.call_count, 4)

    def test_missing_approval_is_not_a_pass(self):
        c = Mock()
        c.turn_evidence = []
        c.request.return_value = {'thread': {'id': 'thread'}}
        c.run_turn.side_effect = [('ACK', set()), ('secret-code', set()), ('cannot write', set())]
        with tempfile.TemporaryDirectory() as tmp, patch('verify.secrets.token_hex', return_value='secret-code'):
            with self.assertRaisesRegex(ProbeError, 'INCONCLUSIVE'):
                verify(c, [('one', 'low'), ('two', 'low')], Path(tmp))

    def test_unapproved_write_is_a_failure(self):
        c = Mock()
        c.turn_evidence = []
        c.request.return_value = {'thread': {'id': 'thread'}}
        with tempfile.TemporaryDirectory() as tmp, patch('verify.secrets.token_hex', return_value='secret-code'):
            def turn(prompt, *args):
                if 'printf' in prompt:
                    (Path(tmp) / 'command-marker.txt').write_text('test')
                    return 'done', {'command'}
                return 'secret-code', set()
            c.run_turn.side_effect = turn
            with self.assertRaisesRegex(ProbeError, 'FAILED'):
                verify(c, [('one', 'low'), ('two', 'low')], Path(tmp))

class HarnessRegressions(unittest.TestCase):
    def test_empty_or_malformed_windows_fail_closed(self):
        for windows in [{}, {'primary': []}, {'primary': {'usedPercent': True}},
                        {'primary': {'usedPercent': 5}, 'secondary': []}]:
            with self.subTest(windows=windows), self.assertRaises(ProbeError):
                ensure_quota({'ordinaryUsageAllowed': True, 'rateLimits': windows})

    def test_stale_approval_is_never_answered(self):
        c = VerificationConnection([sys.executable, '-c', 'import time; time.sleep(30)'], 1)
        try:
            c.thread_id, c.turn_id = 'thread', 'current'
            c.send = Mock()
            for params in [None, {'threadId': 'thread'},
                           {'threadId': 'thread', 'turnId': 'old'}]:
                with self.assertRaises(ProbeError):
                    c.handle_event({'id': 5, 'method': 'item/fileChange/requestApproval', 'params': params})
            c.send.assert_not_called()
        finally:
            c.close()

class LifecycleRegressions(unittest.TestCase):
    connection = VerificationTests.connection

    def test_failed_start_without_id_cannot_be_retried_or_cleaned(self):
        c = self.connection()
        c.request = Mock(side_effect=[{'account': {'type': 'chatgpt'}}, GOOD_QUOTA, ProbeError('timed out')])
        with self.assertRaises(ProbeError):
            c.run_turn('prompt', 'one', 'low')
        self.assertTrue(c.start_pending)
        with self.assertRaisesRegex(ProbeError, 'unknown'):
            c.interrupt()
        with self.assertRaisesRegex(ProbeError, 'unknown'):
            c.run_turn('again', 'one', 'low')
        self.assertEqual(c.request.call_count, 3)

    def test_interrupt_ack_alone_does_not_confirm_stop(self):
        c = self.connection()
        c.turn_id = 'turn'
        c.request = Mock(return_value={})
        c.receive = Mock(side_effect=ProbeError('timed out'))
        with self.assertRaises(ProbeError):
            c.interrupt()
        self.assertEqual(c.turn_id, 'turn')

    def test_interrupt_waits_for_matching_terminal_event(self):
        c = self.connection()
        c.turn_id = 'turn'
        c.request = Mock(return_value={})
        c.receive = Mock(side_effect=[
            {'method': 'turn/completed', 'params': {'threadId': 'other', 'turn': {'id': 'turn', 'status': 'interrupted'}}},
            {'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'interrupted'}}},
        ])
        c.interrupt()
        self.assertIsNone(c.turn_id)
        self.assertEqual(c.receive.call_count, 2)

    def test_identity_change_or_missing_identity_blocks_start(self):
        c = self.connection()
        c.account_id = 'original'
        for identity in [None, 'different']:
            quota = dict(GOOD_QUOTA, accountId=identity)
            c.request = Mock(side_effect=[{'account': {'type': 'chatgpt'}}, quota])
            with self.assertRaisesRegex(ProbeError, 'account_unknown|account_changed'):
                c.run_turn('prompt', 'one', 'low')
            self.assertEqual(c.request.call_count, 2)

    def test_multiple_buckets_and_bad_credits_fail_closed(self):
        for buckets in [
            {'a': GOOD_QUOTA['rateLimits'], 'b': {'primary': {'usedPercent': 100}}},
            {'a': {'primary': {'usedPercent': 1}, 'credits': []}},
        ]:
            with self.assertRaises(ProbeError):
                ensure_quota({'ordinaryUsageAllowed': True, 'rateLimitsByLimitId': buckets})

    def test_original_error_survives_interrupt_failure_and_scratch_is_retained(self):
        from verify import run_in_scratch
        import shutil
        c = Mock()
        c.turn_evidence = []
        c.interrupt.side_effect = ProbeError('interrupt failed')
        with tempfile.TemporaryDirectory() as parent:
            directory = Path(parent) / 'scratch'
            directory.mkdir()
            with patch('verify.tempfile.mkdtemp', return_value=str(directory)), \
                 patch('verify.verify', side_effect=ProbeError('original error')):
                with self.assertRaisesRegex(ProbeError, 'original error'):
                    run_in_scratch(c, [])
            self.assertTrue(directory.exists())
            shutil.rmtree(directory)

    def test_success_is_not_reported_if_interrupt_is_unconfirmed(self):
        from verify import run_in_scratch
        c = Mock()
        c.turn_evidence = []
        c.interrupt.side_effect = ProbeError('not stopped')
        with tempfile.TemporaryDirectory() as directory, \
             patch('verify.tempfile.mkdtemp', return_value=directory), \
             patch('verify.verify', return_value={'passed': True}):
            with self.assertRaisesRegex(ProbeError, 'unknown'):
                run_in_scratch(c, [])
            self.assertTrue(Path(directory).exists())

    def test_cleanup_error_does_not_mask_original_failure(self):
        from verify import run_in_scratch
        c = Mock()
        c.turn_evidence = []
        with tempfile.TemporaryDirectory() as directory, \
             patch('verify.tempfile.mkdtemp', return_value=directory), \
             patch('verify.verify', side_effect=ProbeError('original')), \
             patch('verify.shutil.rmtree', side_effect=OSError('cleanup')):
            with self.assertRaisesRegex(ProbeError, 'original'):
                run_in_scratch(c, [])

    def test_turn_deadline_includes_start_rpc_wait(self):
        c = self.connection()
        c.request = Mock(side_effect=[{'account': {'type': 'chatgpt'}}, GOOD_QUOTA, {'turn': {'id': 'turn'}}])
        c.receive = Mock(side_effect=ProbeError('timed out'))
        with patch('verify.time.monotonic', return_value=100):
            with self.assertRaises(ProbeError):
                c.run_turn('prompt', 'one', 'low')
        c.receive.assert_called_once_with(101)

    def test_unknown_request_and_malformed_event_are_rejected(self):
        c = self.connection()
        for event in [
            {'id': 1, 'method': 'unknown', 'params': {}},
            {'method': 'turn/started', 'params': None},
            {'method': 'turn/started', 'params': {'threadId': 'thread', 'turn': {}}},
        ]:
            with self.subTest(event=event), self.assertRaises(ProbeError):
                c.handle_event(event)
        c.send.assert_not_called()

    def test_started_event_allows_interrupt_after_missing_rpc_response(self):
        c = self.connection()
        def request(method, params=None):
            if method == 'account/read':
                return {'account': {'type': 'chatgpt'}}
            if method == 'account/rateLimits/read':
                return GOOD_QUOTA
            if method == 'turn/start':
                c.handle_event({'method': 'turn/started', 'params': {
                    'threadId': 'thread', 'turn': {'id': 'turn'}}})
                raise ProbeError('response lost')
            c.handle_event({'method': 'turn/completed', 'params': {
                'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'interrupted'}}})
            return {}
        c.request = Mock(side_effect=request)
        with self.assertRaises(ProbeError):
            c.run_turn('prompt', 'one', 'low')
        c.interrupt()
        self.assertIsNone(c.turn_id)
        self.assertFalse(c.start_pending)


if __name__ == "__main__":
    unittest.main()
