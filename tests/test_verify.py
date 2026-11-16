import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from doctor import ProbeError
from verify import VerificationConnection, choose_models, ensure_quota, verify


GOOD_QUOTA = {'ordinaryUsageAllowed': True, 'rateLimits': {'primary': {'usedPercent': 30}}}


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
                        'params': {'threadId': 'thread', 'turnId': 'turn'}})
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
        c.request.assert_called_once_with('account/rateLimits/read')

    def test_synthetic_flow_and_no_nonce_in_second_prompt(self):
        c = Mock()
        c.request.return_value = {'thread': {'id': 'thread'}}
        c.run_turn.side_effect = [('ACK', set()), ('secret-code', set()), ('denied', {'command'}), ('denied', {'file'})]
        with tempfile.TemporaryDirectory() as tmp, patch('verify.secrets.token_hex', return_value='secret-code'):
            result = verify(c, [('one', 'low'), ('two', 'low')], Path(tmp))
        self.assertEqual(result['contextRecall'], 'passed')
        self.assertNotIn('secret-code', c.run_turn.call_args_list[1].args[0])
        self.assertEqual(c.run_turn.call_count, 4)

    def test_missing_approval_is_not_a_pass(self):
        c = Mock()
        c.request.return_value = {'thread': {'id': 'thread'}}
        c.run_turn.side_effect = [('ACK', set()), ('secret-code', set()), ('cannot write', set())]
        with tempfile.TemporaryDirectory() as tmp, patch('verify.secrets.token_hex', return_value='secret-code'):
            with self.assertRaisesRegex(ProbeError, 'INCONCLUSIVE'):
                verify(c, [('one', 'low'), ('two', 'low')], Path(tmp))

    def test_unapproved_write_is_a_failure(self):
        c = Mock()
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


if __name__ == '__main__':
    unittest.main()

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
