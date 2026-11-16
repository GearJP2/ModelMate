import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from modelmate import ProbeError
from verify import VerificationConnection, probe_read_approval
from test_quota import FAKE_SERVER, GOOD


class MetadataTests(unittest.TestCase):
    def test_settings_before_start_response_are_observed_without_claiming_dispatch(self):
        source = FAKE_SERVER.replace("result={'turn':{'id':str(turn)}}", """result={'turn':{'id':str(turn)}}
        print(json.dumps({'method':'thread/settings/updated','params':{
            'threadId':'thread','threadSettings':{'model':'synthetic-model','effort':'low',
                                               'cwd':'PRIVATE','secret':'PRIVATE'}}}),flush=True)""")
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'trace.jsonl'
            c = VerificationConnection([sys.executable, '-u', '-c', source,
                                        json.dumps([GOOD]), str(trace), json.dumps({'type': 'chatgpt'})], 2)
            c.thread_id = 'thread'
            try:
                c.run_turn('synthetic task', 'synthetic-model', 'low')
                evidence = c.turn_evidence[0]
                self.assertEqual(evidence['threadSettingsObserved'], [{'model': 'synthetic-model', 'effort': 'low'}])
                self.assertNotIn('PRIVATE', json.dumps(evidence))
                self.assertIn('not backend dispatch telemetry', evidence['scope'])
            finally:
                c.close()

    def test_unrelated_settings_are_ignored_and_malformed_settings_fail(self):
        c = VerificationConnection([sys.executable, '-c', 'import time;time.sleep(30)'], 1)
        try:
            c.thread_id = 'thread'
            c.handle_event({'method': 'thread/settings/updated', 'params': {
                'threadId': 'other', 'threadSettings': {'model': 'wrong', 'effort': 'high'}}})
            self.assertEqual(c.settings_observed, [])
            for settings in [None, {'model': []}, {'effort': '\x1b[2J'}]:
                with self.subTest(settings=settings), self.assertRaises(ProbeError):
                    c.handle_event({'method': 'thread/settings/updated', 'params': {
                        'threadId': 'thread', 'threadSettings': settings}})
        finally:
            c.close()

    def test_missing_settings_are_unknown_not_echoed_from_request(self):
        with tempfile.TemporaryDirectory() as directory:
            c = VerificationConnection([sys.executable, '-u', '-c', FAKE_SERVER,
                                        json.dumps([GOOD]), str(Path(directory) / 'trace'),
                                        json.dumps({'type': 'chatgpt'})], 2)
            try:
                c.thread_id = 'thread'
                c.run_turn('task', 'requested', 'low')
                self.assertEqual(c.turn_evidence[0]['threadSettingsObserved'], [])
                self.assertEqual(c.turn_evidence[0]['requested']['model'], 'requested')
            finally:
                c.close()

    def test_command_observation_is_taken_from_tool_item_not_assistant_text(self):
        source = FAKE_SERVER.replace("'item':{'type':'agentMessage','text':'ok'}",
                                     "'item':{'type':'commandExecution','id':'synthetic-tool','status':'completed',"
                                     "'command':'PRIVATE','aggregatedOutput':'PRIVATE'}")
        with tempfile.TemporaryDirectory() as directory:
            c = VerificationConnection([sys.executable, '-u', '-c', source,
                                        json.dumps([GOOD]), str(Path(directory) / 'trace'),
                                        json.dumps({'type': 'chatgpt'})], 2)
            try:
                c.thread_id = 'thread'
                answer, _ = c.run_turn('task', 'requested', 'low')
                self.assertEqual(answer, '')
                self.assertEqual(c.turn_evidence[0]['toolsObserved'], [
                    {'type': 'commandExecution', 'status': 'completed', 'denialObserved': False}])
                self.assertNotIn('PRIVATE', json.dumps(c.turn_evidence))
            finally:
                c.close()


class ReadApprovalProbeTests(unittest.TestCase):
    def result(self, tools):
        c = Mock()
        c.request.return_value = {'thread': {'id': 'synthetic'}}
        c.turn_evidence = [{'threadSettingsObserved': [], 'toolsObserved': tools}]
        c.run_turn.return_value = ('synthetic answer', set())
        with tempfile.TemporaryDirectory() as directory:
            result = probe_read_approval(c, [('synthetic-model', 'low')], Path(directory))
        c.run_turn.assert_called_once()
        prompt = c.run_turn.call_args.args[0]
        self.assertIn('printf MODEL_MATE_READ_PROBE', prompt)
        self.assertIn('do not request elevated permissions', prompt)
        self.assertNotIn('>', prompt)
        self.assertIsNone(result['reportedModels'])
        return result['readCommandApproval']

    def test_completed_without_denial_is_a_bypass_observation(self):
        self.assertEqual(self.result([{'type': 'commandExecution', 'status': 'completed', 'denialObserved': False}]),
                         'executed_without_approval')

    def test_denied_command_is_only_a_scoped_success(self):
        self.assertEqual(self.result([{'type': 'commandExecution', 'status': 'declined', 'denialObserved': True}]),
                         'denial_observed_for_this_command')

    def test_no_tool_or_unexplained_failure_is_inconclusive(self):
        for items in [[], [{'type': 'commandExecution', 'status': 'failed', 'denialObserved': False}],
                      [{'type': 'fileChange', 'status': 'completed', 'denialObserved': False}]]:
            self.assertEqual(self.result(items), 'inconclusive')

    def test_successfully_executed_tool_does_not_get_pass_even_with_denial(self):
        self.assertEqual(self.result([{'type': 'commandExecution', 'status': 'completed', 'denialObserved': True}]),
                         'inconclusive')


if __name__ == '__main__':
    unittest.main()
