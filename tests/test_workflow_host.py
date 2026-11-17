"""Executor observations are synthetic; no native Codex dispatch or external command runner."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import ChatShell, ProbeError, SessionStore, WorkflowController, WorkflowHost
from test_routing import CATALOG, PLAN, POLICY, QUOTA


class WorkflowHostTests(unittest.TestCase):
    def setUp(self):
        self.c = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
        self.quota = copy.deepcopy(QUOTA)
        self.preflight = Mock(side_effect=lambda: {'quota': self.quota, 'checked_at': time.monotonic(),
                                                  'catalog': CATALOG, 'role_policy': POLICY})
        self.binding = None
        def dispatch(descriptor):
            self.binding = {'thread_id': 'synthetic-thread', 'turn_id': 'turn-' + str(self.dispatch.call_count)}
            return dict(self.binding)
        self.dispatch = Mock(side_effect=dispatch)
        self.interrupt = Mock()
        self.host = WorkflowHost(self.c, self.preflight, self.dispatch, self.interrupt)
        self.host.configure_check(0, command='python3 -m unittest', cwd='/synthetic')

    def action(self, name='next'):
        self.host({'action': name, 'task_id': self.c.task_id})

    def item(self, method, code=None, status='completed', item_id='check-item', command='python3 -m unittest', cwd='/synthetic', **params):
        event = {'method': method, 'params': {'threadId': self.binding['thread_id'], 'turnId': self.binding['turn_id'],
            'item': {'id': item_id, 'type': 'commandExecution', 'command': command, 'cwd': cwd,
                     'status': status, 'exitCode': code, 'aggregatedOutput': 'PRIVATE stdout is not evidence'}}}
        event['params'].update(params)
        return self.host.observe_native(event)

    def terminal(self, status='completed', **changes):
        params = {'threadId': self.binding['thread_id'], 'turn': {'id': self.binding['turn_id'], 'status': status}}
        params.update(changes)
        return self.host.observe_native({'method': 'turn/completed', 'params': params})

    def check_pass(self, code=0):
        self.item('item/started', status='inProgress')
        self.item('item/completed', code)
        self.terminal()
        self.action('check')

    def test_exact_observation_records_evidence_but_not_task_success_or_raw_stdout(self):
        self.action()
        self.check_pass()
        state = self.c.snapshot()
        self.assertEqual(state['state'], 'CHECKING')
        self.assertEqual(state['reason'], 'task_criteria_pending')
        evidence = state['steps'][0]['evidence'][0]
        self.assertEqual(evidence['result'], 'pass')
        self.assertNotIn('PRIVATE', json.dumps(self.c.export_checkpoint()))
        self.c.finish_task({0: [evidence['id']]})
        self.assertEqual(self.c.state, 'DONE')

    def test_unrelated_successful_command_cannot_satisfy_test(self):
        self.action()
        self.assertFalse(self.item('item/started', command='true'))
        self.assertFalse(self.item('item/completed', 0, command='true'))
        self.terminal();self.action('check')
        self.assertEqual(self.c.state, 'UNVERIFIED')

    def test_foreign_thread_or_turn_is_ignored_without_recording_or_finishing(self):
        self.action()
        self.assertFalse(self.item('item/completed', 0, threadId='foreign'))
        self.assertFalse(self.item('item/completed', 0, turnId='foreign'))
        self.assertFalse(self.terminal(threadId='foreign'))
        self.assertEqual(self.c.state, 'RUNNING')
        self.interrupt.assert_not_called()

    def test_missing_observed_start_or_changed_command_cannot_pass(self):
        self.action()
        with self.assertRaisesRegex(ProbeError, 'start'):self.item('item/completed', 0)
        self.assertEqual(self.c.state, 'PAUSED')
        self.assertEqual(self.interrupt.call_count, 1)

    def test_changed_bound_metadata_discards_prior_successful_observation(self):
        self.action();self.item('item/started');self.item('item/completed', 0)
        with self.assertRaisesRegex(ProbeError, 'changed'):self.item('item/completed', 0, cwd='/other')
        self.terminal()
        self.action('check')
        self.assertEqual(self.c.state, 'UNVERIFIED')

    def test_duplicate_observation_is_idempotent_and_conflict_pauses(self):
        self.action();self.item('item/started');self.item('item/completed', 0)
        self.item('item/completed', 0)
        with self.assertRaisesRegex(ProbeError, 'Conflicting'):self.item('item/completed', 1)
        self.assertEqual(self.c.state, 'PAUSED')
        self.assertEqual(self.c.snapshot()['steps'][0]['attempts'], 1)

    def test_repeated_check_item_within_one_model_attempt_is_not_hidden_retry(self):
        self.action();self.item('item/started')
        with self.assertRaisesRegex(ProbeError, 'repeated'):self.item('item/started', item_id='second-item')
        self.assertEqual(self.dispatch.call_count, 1)
        self.assertEqual(self.c.state, 'PAUSED')

    def test_declined_or_missing_exit_code_is_unverified_and_boolean_is_rejected(self):
        self.action();self.item('item/started');self.item('item/completed', 0, status='declined')
        self.terminal();self.action('check')
        self.assertEqual(self.c.state, 'UNVERIFIED')
        self.setUp()
        self.action();self.item('item/started')
        with self.assertRaises(ProbeError):self.item('item/completed', True)

    def test_known_failures_exhaust_controller_budget_and_do_not_autodispatch(self):
        for i in range(3):
            self.action();self.check_pass(1)
            self.assertEqual(self.dispatch.call_count, i + 1)
        self.assertEqual(self.c.reason, 'correction_limit')
        with self.assertRaises(ProbeError):self.action()
        self.assertEqual(self.dispatch.call_count, 3)

    def test_model_approval_still_requires_explicit_user_and_separate_next(self):
        plan = copy.deepcopy(PLAN);plan['steps'][0]['role'] = 'strong'
        self.c.revise_step(json.dumps(plan))
        shell = ChatShell(io.StringIO(), workflow=self.c, workflow_action=self.host)
        shell.line('/next')
        self.dispatch.assert_not_called()
        shell.line('/approve ' + shell.pending['token'])
        self.dispatch.assert_not_called()
        shell.line('/next')
        self.dispatch.assert_called_once()

    def test_quota_or_preflight_failure_never_consumes_slot_or_dispatches(self):
        self.quota.clear();self.action()
        self.dispatch.assert_not_called()
        self.assertEqual(self.c.state, 'PAUSED')
        self.assertEqual(self.c.snapshot()['steps'][0]['attempts'], 0)
        self.setUp();self.preflight.side_effect = OSError('PRIVATE network error')
        with self.assertRaises(OSError):self.action()
        self.assertEqual(self.c.reason, 'quota_unknown')
        self.dispatch.assert_not_called()

    def test_unknown_start_outcome_keeps_slot_and_requires_explicit_reconciliation(self):
        self.dispatch.side_effect = TimeoutError('synthetic timeout')
        with self.assertRaises(TimeoutError):self.action()
        self.assertEqual(self.c.snapshot()['steps'][0]['attempts'], 1)
        with self.assertRaises(ProbeError):self.c.answer_pause(self.c.snapshot()['pause_token'], 'continue')
        self.host.reconcile({'thread_id': 'inspected-thread', 'turn_id': 'inspected-turn'}, 'interrupted')
        self.assertEqual(self.c.reason, 'outcome_unknown')
        self.assertEqual(self.dispatch.call_count, 1)

    def test_cancel_ack_is_not_terminal_and_interrupt_is_not_replayed(self):
        self.action();self.action('cancel');self.action('cancel')
        self.assertEqual(self.interrupt.call_count, 1)
        self.assertEqual(self.c.snapshot()['active_attempt']['status'], 'running')
        self.terminal('interrupted')
        self.assertIsNone(self.c.snapshot()['active_attempt'])
        self.assertEqual(self.c.state, 'PAUSED')

    def test_timeout_and_disconnect_block_further_dispatch_without_replay(self):
        with patch('modelmate.time.monotonic', return_value=100):self.action()
        with patch('modelmate.time.monotonic', return_value=221):
            with self.assertRaisesRegex(ProbeError, 'timed out'):self.host.tick()
        self.assertEqual(self.dispatch.call_count, 1)
        self.host.disconnect()
        with self.assertRaises(ProbeError):self.action()
        self.assertEqual(self.interrupt.call_count, 1)

    def test_approval_requests_never_become_tool_acceptance(self):
        self.action()
        with self.assertRaisesRegex(ProbeError, 'nothing approved'):
            self.host.observe_native({'id': 'server-request', 'method': 'item/commandExecution/requestApproval',
                                      'params': {'threadId': self.binding['thread_id'], 'turnId': self.binding['turn_id']}})
        self.assertEqual(self.c.reason, 'unsupported_capability')
        self.interrupt.assert_called_once()

    def test_model_claims_do_not_fill_checks_and_duplicate_terminal_does_not_advance(self):
        self.action()
        self.assertFalse(self.host.observe_native({'method': 'item/completed', 'params': {
            'threadId': self.binding['thread_id'], 'turnId': self.binding['turn_id'],
            'item': {'id': 'message', 'type': 'agentMessage', 'text': 'DONE all tests passed'}}}))
        self.terminal();self.assertFalse(self.terminal())
        self.action('check')
        self.assertEqual(self.c.state, 'UNVERIFIED')

    def test_old_turn_identity_is_rejected_and_old_checks_do_not_leak_into_recovery(self):
        self.action();self.check_pass(1)
        old_binding = dict(self.binding)
        self.dispatch.side_effect = lambda _: old_binding
        with self.assertRaisesRegex(ProbeError, 'reused'):self.action()
        self.assertEqual(self.c.snapshot()['steps'][0]['attempts'], 2)
        self.host.reconcile({'thread_id': 'recovery', 'turn_id': 'new-turn'}, 'completed')
        self.action('check')
        self.assertEqual(self.c.state, 'UNVERIFIED')

    def test_reentrant_events_before_binding_return_fail_closed(self):
        self.dispatch.side_effect = lambda _: self.host.observe_native({'method': 'turn/completed', 'params': {}})
        with self.assertRaisesRegex(ProbeError, 'Queue'):self.action()
        self.assertEqual(self.c.state, 'PAUSED')
        self.assertEqual(self.c.snapshot()['steps'][0]['attempts'], 1)

    def test_configuration_and_action_identities_are_checked(self):
        for index, cwd in ((True, '/synthetic'), (99, '/synthetic'), (0, 'relative')):
            with self.assertRaises(ProbeError):self.host.configure_check(index, command='test', cwd=cwd)
        with self.assertRaises(ProbeError):self.host({'action': 'next', 'task_id': 'foreign'})
        self.action()
        with self.assertRaises(ProbeError):self.host.configure_check(0, command='changed', cwd='/synthetic')
        ChatShell(io.StringIO(), workflow=self.c, workflow_action=self.host)
        with self.assertRaises(ProbeError):ChatShell(io.StringIO(), workflow=self.c, workflow_action=self.host)
        other = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
        with self.assertRaises(ProbeError):ChatShell(io.StringIO(), workflow=other, workflow_action=self.host)

    def test_automatic_delegation_effort_is_not_dispatched_or_counted(self):
        catalog = copy.deepcopy(CATALOG)
        catalog[1]['supportedReasoningEfforts'].append({'reasoningEffort': 'ultra'})
        plan = copy.deepcopy(PLAN);plan['steps'][0]['effort'] = 'ultra'
        c = WorkflowController(json.dumps(plan), catalog, POLICY)
        host = WorkflowHost(c, lambda: {'quota': QUOTA, 'checked_at': time.monotonic(),
                                       'catalog': catalog, 'role_policy': POLICY}, self.dispatch, self.interrupt)
        host({'action': 'next', 'task_id': c.task_id})
        self.dispatch.assert_not_called()
        self.assertEqual(c.reason, 'unsupported_capability')
        self.assertEqual(c.snapshot()['steps'][0]['attempts'], 0)

    def test_durable_attempt_precedes_dispatch_and_observed_check_is_persisted(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project';project.mkdir()
            with SessionStore(project, Path(directory) / 'state') as store:
                sid = store.create('workflow host', account_hash=hashlib.sha256(QUOTA['accountId'].encode()).hexdigest())['id']
                with store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY, controller=self.c):
                    original = self.dispatch.side_effect
                    def assert_durable(descriptor):
                        saved = store.read(sid)['workflow']['active_attempt']
                        self.assertEqual(saved['id'], descriptor['attempt_id'])
                        return original(descriptor)
                    self.dispatch.side_effect = assert_durable
                    self.action();self.check_pass()
                    saved = store.read(sid)['workflow']
                    self.assertEqual(saved['steps'][0]['evidence'][0]['result'], 'pass')
                    self.assertNotIn('PRIVATE', json.dumps(saved))

    def test_restored_completed_attempt_can_finish_checks_without_another_model_turn(self):
        self.action()
        self.terminal()
        active = self.c.snapshot()['active_attempt']
        self.c.record_check(active['id'], 0, origin='tool', exit_code=0, reference='prior observed item', finding='host revalidated observation')
        restored = WorkflowController.restore_checkpoint(self.c.export_checkpoint(), QUOTA, time.monotonic(), CATALOG, POLICY)
        dispatch = Mock()
        host = WorkflowHost(restored, self.preflight, dispatch, self.interrupt)
        host.reconcile(dict(self.binding), 'completed')
        self.assertEqual(restored.state, 'PAUSED')
        restored.answer_pause(restored.snapshot()['pause_token'], 'continue')
        host({'action': 'check', 'task_id': restored.task_id})
        self.assertEqual(restored.snapshot()['steps'][0]['state'], 'DONE')
        self.assertEqual(restored.snapshot()['steps'][0]['attempts'], 1)
        dispatch.assert_not_called()

    def test_malformed_event_or_changed_item_type_never_supplies_check_evidence(self):
        self.action()
        with self.assertRaises(ProbeError):self.host.observe_native({'params': {}})
        self.item('item/started');self.item('item/completed', 0)
        with self.assertRaisesRegex(ProbeError, 'type'):
            self.host.observe_native({'method': 'item/completed', 'params': {
                'threadId': self.binding['thread_id'], 'turnId': self.binding['turn_id'],
                'item': {'type': 'agentMessage', 'id': 'check-item', 'text': 'all passed'}}})
        self.assertEqual(self.c.state, 'PAUSED')


FAKE_HOST_UI = r'''
import json,os,sys,time
from modelmate import WorkflowController,WorkflowHost,run_chat
from test_routing import PLAN,CATALOG,POLICY,QUOTA
c=WorkflowController(json.dumps(PLAN),CATALOG,POLICY)
r,w=os.pipe();closed=False;sent=0;interrupted=0
def dispatch(descriptor):
 global closed,sent
 sent+=1
 if sys.argv[1]=='disconnect':
  os.close(w);closed=True
 elif sys.argv[1]=='broken':
  os.write(w,b'PRIVATE invalid protocol\n')
 else:
  item={'id':'check-item','type':'commandExecution','command':'python3 -m unittest','cwd':'/synthetic',
        'status':'completed','exitCode':0,'aggregatedOutput':'PRIVATE-STDOUT'}
  for method in ('item/started','item/completed'):
   os.write(w,(json.dumps({'method':method,'params':{'threadId':'thread','turnId':'turn','item':item}})+'\n').encode())
  os.write(w,(json.dumps({'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'turn','status':'completed'}}})+'\n').encode())
 return {'thread_id':'thread','turn_id':'turn'}
def interrupt(binding):
 global interrupted
 interrupted+=1
host=WorkflowHost(c,lambda:{'quota':QUOTA,'checked_at':time.monotonic(),'catalog':CATALOG,'role_policy':POLICY},dispatch,interrupt)
host.configure_check(0,command='python3 -m unittest',cwd='/synthetic')
try:
 result=run_chat(sys.stdin,sys.stdout,workflow=c,workflow_action=host,executor_stream=os.fdopen(r,'rb',buffering=0),
                 catalog=CATALOG,role_policy=POLICY)
 print('SYNTHETIC '+json.dumps({'sent':sent,'interrupts':interrupted,'state':c.state,'attempts':c.snapshot()['steps'][0]['attempts']}),flush=True)
 sys.exit(result)
finally:
 if not closed:os.close(w)
'''


class WorkflowHostProcessTests(unittest.TestCase):
    def spawn(self, mode):
        root = Path(__file__).resolve().parents[1]
        source = 'import sys;sys.path.insert(0,' + repr(str(root / 'tests')) + ');' + FAKE_HOST_UI
        p = subprocess.Popen([sys.executable, '-u', '-c', source, mode], cwd=root,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if p.poll() is None:p.kill()
            p.wait(timeout=3)
            for stream in (p.stdin,p.stdout,p.stderr):stream.close()
        self.addCleanup(cleanup)
        return p

    def test_executor_pipe_carries_observed_checks_without_printing_raw_output(self):
        import selectors
        p = self.spawn('complete')
        p.stdin.write(b'/next\n');p.stdin.flush()
        buffer = b''
        def until(marker):
            nonlocal buffer
            deadline = time.monotonic() + 4
            with selectors.DefaultSelector() as selector:
                selector.register(p.stdout, selectors.EVENT_READ)
                while marker not in buffer and time.monotonic() < deadline:
                    if selector.select(max(0, deadline - time.monotonic())):
                        chunk=os.read(p.stdout.fileno(),65536)
                        if not chunk:break
                        buffer += chunk
            self.assertIn(marker, buffer, buffer.decode(errors='replace'))
        until('สถานะ: CHECKING'.encode())
        p.stdin.write(b'/check\n');p.stdin.flush()
        until('[pass] test'.encode())
        p.stdin.write(b'/exit\n');p.stdin.flush();p.wait(timeout=3)
        remaining = p.stdout.read();buffer += remaining
        self.assertEqual(p.returncode, 0, p.stderr.read())
        self.assertNotIn(b'PRIVATE-STDOUT', buffer)
        self.assertIn(b'"sent": 1', buffer)
        self.assertNotIn('สถานะ: DONE'.encode(), buffer)

    def test_executor_eof_stops_session_and_does_not_replay(self):
        for mode in ('disconnect', 'broken'):
            with self.subTest(mode=mode):
                p = self.spawn(mode)
                stdout, stderr = p.communicate(b'/next\n', timeout=5)
                self.assertEqual(p.returncode, 1, stderr)
                self.assertIn(b'"sent": 1', stdout)
                self.assertIn(b'"interrupts": 1', stdout)
                self.assertIn(b'"state": "PAUSED"', stdout)
                self.assertNotIn(b'PRIVATE', stdout)


if __name__ == '__main__':
    unittest.main()
