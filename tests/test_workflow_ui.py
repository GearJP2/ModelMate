"""Trusted host callbacks exercise UI/controller wiring without model or tool execution."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import ChatShell, ProbeError, SessionStore, WorkflowController, run_chat
from test_routing import CATALOG, PLAN, POLICY, QUOTA


class WorkflowUITests(unittest.TestCase):
    def controller(self, role='standard'):
        plan = copy.deepcopy(PLAN);plan['steps'][0]['role'] = role
        return WorkflowController(json.dumps(plan), CATALOG, POLICY)

    def shell(self, c=None, connected=True, auto_stop=False):
        c = c or self.controller()
        actions = []
        def host(action):
            actions.append(action)
            self.assertEqual(action['task_id'], c.task_id)
            if action['action'] == 'next':
                return c.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)
            if auto_stop:
                c.finish_attempt(c.snapshot()['active_attempt']['id'], 'interrupted')
        out = io.StringIO()
        shell = ChatShell(out, catalog=CATALOG, role_policy=POLICY, workflow=c,
                          workflow_action=host if connected else None)
        shell.start()
        return shell, c, out, actions

    def finish(self, shell, c, code):
        aid = c.snapshot()['active_attempt']['id']
        c.finish_attempt(aid, 'completed')
        evidence = c.record_check(aid, 0, origin='tool', exit_code=code, reference='synthetic host check', finding='observed result')
        c.evaluate_attempt(aid)
        shell.event({'type': 'workflow_changed', 'task_id': c.task_id})
        return evidence

    def test_plan_status_and_model_preview_do_not_start_work(self):
        shell, c, out, actions = self.shell()
        shell.line('/workflow');shell.line('/status')
        self.assertIn(PLAN['goal'], out.getvalue())
        self.assertIn(POLICY['standard'], out.getvalue())
        self.assertIn('attempt 0/3', out.getvalue())
        self.assertEqual(actions, [])
        self.assertEqual(c.snapshot()['steps'][0]['attempts'], 0)

    def test_status_summarizes_chat_time_and_counts_without_rendering_full_plan(self):
        shell, controller, output, actions = self.shell()
        output.seek(0)
        output.truncate()
        shell.line('/status')
        summary = output.getvalue()
        self.assertIn('READY · ask_to_escalate · เสร็จ 0/1 ขั้น', summary)
        self.assertIn('วินาทีรวมเวลารอ · 0 attempts · 0 rechecks', summary)
        self.assertIn('/next', summary)
        self.assertNotIn(PLAN['success_criteria'][0], summary)
        self.assertEqual(actions, [])
        self.assertEqual(controller.snapshot()['steps'][0]['attempts'], 0)

    def test_missing_host_blocks_next_without_consuming_budget(self):
        shell, c, out, _ = self.shell(connected=False)
        shell.line('/next')
        self.assertIn('unavailable', out.getvalue())
        self.assertEqual(c.state, 'READY')
        self.assertEqual(c.snapshot()['steps'][0]['attempts'], 0)

    def test_callback_return_value_cannot_declare_done_without_controller_evidence(self):
        c = self.controller()
        host = Mock(return_value={'state': 'DONE', 'tests': 'passed'})
        shell = ChatShell(io.StringIO(), workflow=c, workflow_action=host)
        shell.line('/next')
        self.assertEqual(c.state, 'READY')
        self.assertEqual(c.snapshot()['steps'][0]['attempts'], 0)

    def test_cancel_reaches_host_even_if_persisting_pause_fails(self):
        shell, c, _, actions = self.shell()
        shell.line('/next')
        with patch.object(c, 'pause', side_effect=OSError('synthetic storage failure')):
            with self.assertRaises(OSError):shell.line('/cancel')
        self.assertEqual(actions[-1]['action'], 'cancel')
        self.assertEqual(c.snapshot()['active_attempt']['status'], 'running')

    def test_model_approval_is_explicit_and_does_not_automatically_dispatch(self):
        shell, c, out, actions = self.shell(self.controller('strong'))
        shell.line('/next');token = shell.pending['token']
        self.assertEqual(shell.pending['kind'], 'workflow_model')
        shell.line('yes');shell.line('/approve stale')
        self.assertEqual(len(actions), 1)
        self.assertEqual(c.state, 'AWAITING_MODEL_APPROVAL')
        shell.line('/approve ' + token)
        self.assertEqual(c.state, 'READY')
        self.assertEqual(len(actions), 1)
        self.assertEqual(c.snapshot()['steps'][0]['attempts'], 0)
        shell.line('/next')
        self.assertEqual(len(actions), 2)
        self.assertTrue(shell.active)
        self.assertEqual(c.snapshot()['steps'][0]['attempts'], 1)

    def test_mode_change_expires_old_grants_and_tokens_and_preserves_budget(self):
        shell, c, _, actions = self.shell(self.controller('strong'))
        shell.line('/next');old = shell.pending['token']
        shell.line('/mode approve_plan')
        self.assertEqual(c.mode, 'approve_plan')
        shell.line('/approve ' + old)
        self.assertEqual(c.state, 'READY')
        shell.line('/next');fresh = shell.pending['token']
        self.assertNotEqual(fresh, old)
        shell.line('/approve ' + fresh);shell.line('/next')
        shell.line('/mode auto')
        self.assertEqual(c.mode, 'approve_plan')
        self.assertEqual(c.snapshot()['steps'][0]['attempts'], 1)

    def test_correction_limit_choices_preserve_ledger_and_require_explicit_next(self):
        shell, c, _, actions = self.shell()
        for _ in range(3):
            shell.line('/next');self.finish(shell, c, 1)
        self.assertEqual(c.reason, 'correction_limit')
        shell.line('/cancel')
        self.assertEqual(c.reason, 'correction_limit')
        token = shell.pending['token']
        shell.line('/next')
        self.assertEqual(len(actions), 3)
        shell.line('/continue ' + token)
        self.assertEqual(len(actions), 3)
        self.assertEqual(c.snapshot()['steps'][0]['cycle'], 1)
        shell.line('/next')
        self.assertEqual(c.snapshot()['active_attempt']['number'], 1)
        self.assertTrue(any(e.get('kind') == 'budget_extension' for e in c.snapshot()['history']))

    def test_revise_and_pause_do_not_reset_counters_or_start_a_new_attempt(self):
        shell, c, _, actions = self.shell()
        shell.line('/next');self.finish(shell, c, 1)
        shell.line('/cancel');token = shell.pending['token']
        shell.line('/revise ' + token)
        self.assertEqual(c.reason, 'revise_scope')
        shell.line('/pause ' + shell.pending['token'])
        self.assertEqual(c.snapshot()['steps'][0]['attempts'], 1)
        self.assertEqual(len(actions), 1)

    def test_exit_waits_for_terminal_event_and_does_not_treat_ack_as_stop(self):
        shell, c, out, actions = self.shell()
        shell.line('/next');shell.line('/exit')
        self.assertFalse(shell.closed)
        self.assertTrue(shell.stopping)
        self.assertTrue(shell.active)
        self.assertEqual(actions[-1]['action'], 'cancel')
        shell.line('/next')
        self.assertEqual(len(actions), 2)
        c.finish_attempt(c.snapshot()['active_attempt']['id'], 'interrupted')
        shell.event({'type': 'workflow_changed', 'task_id': c.task_id})
        self.assertTrue(shell.closed)
        self.assertFalse(shell.active)
        self.assertEqual(c.reason, 'outcome_unknown')

    def test_unconfirmed_exit_times_out_and_keeps_unknown_attempt(self):
        shell, c, out, _ = self.shell()
        shell.line('/next')
        with patch('modelmate.time.monotonic', return_value=100):shell.line('/exit')
        with patch('modelmate.time.monotonic', return_value=106):shell.tick()
        self.assertEqual(shell.exit_code, 130)
        self.assertTrue(shell.closed)
        self.assertEqual(c.state, 'PAUSED')
        self.assertEqual(c.snapshot()['active_attempt']['status'], 'running')
        self.assertIn('ผล', out.getvalue())

    def test_sync_host_confirmation_can_close_exit_without_false_completion(self):
        shell, c, _, actions = self.shell(auto_stop=True)
        shell.line('/next');shell.line('/exit')
        self.assertTrue(shell.closed)
        self.assertEqual(c.state, 'PAUSED')
        self.assertEqual(c.reason, 'outcome_unknown')
        self.assertEqual(actions[-1]['action'], 'cancel')

    def test_model_claims_and_foreign_or_forged_events_cannot_mutate_workflow(self):
        shell, c, _, actions = self.shell()
        for message in ({'type': 'completed'}, {'type': 'stopped'},
                        {'type': 'workflow_changed', 'task_id': 'different'},
                        {'type': 'workflow_changed', 'task_id': c.task_id, 'state': 'DONE'},
                        {'type': 'plan', 'raw': json.dumps(PLAN)},
                        {'type': 'tool_approval', 'token': 'fake', 'preview': 'approve command'}):
            with self.assertRaises(ProbeError):shell.event(message)
        shell.line('DONE tests passed')
        shell.line('/approve fake')
        self.assertEqual(c.state, 'READY')
        self.assertEqual(actions, [])

    def test_read_only_permissions_and_manual_executor_cannot_be_bypassed(self):
        shell, c, _, actions = self.shell()
        shell.line('/permissions workspace')
        shell.line('/model synthetic-strong low');shell.line('/sessions other')
        self.assertEqual(shell.permissions, 'read_only')
        self.assertEqual(actions, [])
        with self.assertRaises(ProbeError):ChatShell(io.StringIO(), send=Mock(), workflow=c)
        with self.assertRaises(ProbeError):run_chat(io.StringIO(), io.StringIO(), workflow=c, backend=Mock())

    def test_rendering_filters_terminal_controls_and_does_not_claim_backend_completion_is_done(self):
        plan = copy.deepcopy(PLAN);plan['goal'] = 'ไทย\x1b[2J\u202e'
        c = WorkflowController(json.dumps(plan), CATALOG, POLICY)
        shell, c, out, _ = self.shell(c)
        self.assertNotIn('\x1b', out.getvalue());self.assertNotIn('\u202e', out.getvalue())
        shell.line('/next');evidence = self.finish(shell, c, 0)
        self.assertEqual(c.state, 'CHECKING')
        self.assertIn('[pass] test', out.getvalue())
        c.finish_task({0: [evidence['id']]})
        shell.event({'type': 'workflow_changed', 'task_id': c.task_id})
        self.assertIn('สถานะ: DONE', out.getvalue())
        self.assertIn('หลักฐานที่บันทึก 1', out.getvalue())

    def test_bound_workflow_ui_persists_user_choices_and_mode_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project';project.mkdir()
            with SessionStore(project, Path(directory) / 'state') as store:
                fingerprint = hashlib.sha256(QUOTA['accountId'].encode()).hexdigest()
                sid = store.create('workflow', account_hash=fingerprint)['id']
                with store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY, controller=self.controller()) as c:
                    shell, c, _, _ = self.shell(c)
                    shell.line('/mode approve_plan');shell.line('/next')
                    shell.line('/approve ' + shell.pending['token'])
                    shell.line('/cancel')
                    self.assertEqual(store.read(sid)['mode'], 'approve_plan')
                with store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY) as restored:
                    self.assertEqual(restored.mode, 'approve_plan')
                    self.assertEqual(restored.snapshot()['steps'][0]['attempts'], 0)


FAKE_UI = r'''
import json,os,sys,time
from modelmate import WorkflowController,run_chat
from test_routing import PLAN,CATALOG,POLICY,QUOTA
c=WorkflowController(json.dumps(PLAN),CATALOG,POLICY)
r,w=os.pipe()
def host(action):
 if action['action']=='next':
  c.request_attempt(QUOTA,time.monotonic(),CATALOG,POLICY)
  os.write(w,(json.dumps({'type':'workflow_changed','task_id':c.task_id})+'\n').encode())
 elif action['action']=='cancel':
  c.finish_attempt(c.snapshot()['active_attempt']['id'],'interrupted')
  os.write(w,(json.dumps({'type':'workflow_changed','task_id':c.task_id})+'\n').encode())
try:
 sys.exit(run_chat(sys.stdin,sys.stdout,event_stream=os.fdopen(r,'rb',buffering=0),
  workflow=c,workflow_action=host,catalog=CATALOG,role_policy=POLICY))
finally:os.close(w)
'''


class WorkflowUIProcessTests(unittest.TestCase):
    def test_eof_during_active_workflow_requests_host_stop_and_exits_after_confirmation(self):
        root = Path(__file__).resolve().parents[1]
        source = 'import sys;sys.path.insert(0,' + repr(str(root / 'tests')) + ');' + FAKE_UI
        result = subprocess.run([sys.executable, '-u', '-c', source], cwd=root,
                                input=b'/next\n', capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('outcome_unknown'.encode(), result.stdout)

    def test_selector_processes_host_change_signal_while_input_stays_open(self):
        root = Path(__file__).resolve().parents[1]
        source = 'import sys;sys.path.insert(0,' + repr(str(root / 'tests')) + ');' + FAKE_UI
        p = subprocess.Popen([sys.executable, '-u', '-c', source], cwd=root,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            p.stdin.write(b'/next\n');p.stdin.flush()
            marker = 'สถานะ: RUNNING'.encode();buffer = b'';deadline = time.monotonic() + 4
            with selectors.DefaultSelector() as selector:
                selector.register(p.stdout, selectors.EVENT_READ)
                while buffer.count(marker) < 2 and time.monotonic() < deadline:
                    if selector.select(max(0, deadline - time.monotonic())):
                        chunk = os.read(p.stdout.fileno(), 65536)
                        if not chunk:break
                        buffer += chunk
            self.assertGreaterEqual(buffer.count(marker), 2, buffer.decode(errors='replace'))
            p.stdin.write(b'/exit\n');p.stdin.flush();p.wait(timeout=3)
            self.assertEqual(p.returncode, 0, p.stderr.read())
        finally:
            if p.poll() is None:p.kill()
            p.wait(timeout=3)
            for stream in (p.stdin, p.stdout, p.stderr):stream.close()


if __name__ == '__main__':
    unittest.main()
