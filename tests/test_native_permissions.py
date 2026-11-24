"""Synthetic native approval handshake with observable, test-owned file effects."""
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from modelmate import ChatShell, NativeWorkflowConnection, ProbeError, SessionStore, WorkflowController, run_chat
from test_routing import CATALOG, PLAN, POLICY, QUOTA


SERVER = r'''
import json,sys
from pathlib import Path
trace,project,directory,mode,catalog=sys.argv[1:]
def emit(value):print(json.dumps(value),flush=True)
for line in sys.stdin:
 req=json.loads(line)
 with open(trace,'a') as stream:stream.write(json.dumps(req)+'\n')
 method=req.get('method');p=req.get('params',{})
 if method is None:
  record=json.loads(next(Path(directory).glob('*.json')).read_text())
  pending=record['workflow'].get('tool_request')
  decision=req['result']['decision']
  if decision=='accept':
   assert pending['status']=='approved' and pending['binding']['request_id']==req['id']
   Path(project,'effect').write_text('synthetic effect')
   item={'id':'tool','type':'commandExecution','command':'printf synthetic','cwd':project}
   if mode=='command':
    emit({'method':'item/started','params':{'threadId':'thread','turnId':'1','item':item}})
    item.update(status='completed',exitCode=0)
    emit({'method':'item/completed','params':{'threadId':'thread','turnId':'1','item':item}})
  elif pending is not None:assert pending['status']=='declined'
  if mode not in ('scope','no_preview','duplicate') and not mode.startswith('hold_'):
   emit({'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'1','status':'completed'}}})
  continue
 if 'id' not in req:continue
 if method=='initialize':result={}
 elif method=='account/read':result={'account':{'type':'chatgpt'}}
 elif method=='account/rateLimits/read':result={'accountId':'synthetic','ordinaryUsageAllowed':True,'rateLimits':{'primary':{'usedPercent':5}}}
 elif method=='model/list':result={'data':json.loads(catalog)}
 elif method=='thread/start':result={'thread':{'id':'thread','cwd':project,'ephemeral':False,'modelProvider':'openai'},
  'approvalPolicy':'on-request','approvalsReviewer':'user','sandbox':{'type':'readOnly'}}
 elif method=='turn/start':result={'turn':{'id':'1'}}
 elif method=='turn/interrupt':result={}
 else:raise RuntimeError(method)
 emit({'id':req['id'],'result':result})
 if method=='turn/start':
  changes=[{'path':str(Path(project,'effect')),'kind':{'type':'add'},'diff':'+synthetic effect'}]
  if mode in ('patch','patch_update'):
   emit({'method':'item/fileChange/patchUpdated','params':{'threadId':'thread','turnId':'1','itemId':'tool','changes':changes}})
  params={'threadId':'foreign' if mode=='foreign' else 'thread','turnId':'1','itemId':'tool',
   'command':'printf synthetic','cwd':project}
  if mode=='scope':params['kind']='writeStdin'
  request={'id':'approval','method':'item/fileChange/requestApproval' if mode in ('patch','patch_update','no_preview')
   else 'item/commandExecution/requestApproval','params':params}
  emit(request)
  if mode=='duplicate':
   request['params']['command']='printf changed';emit(request)
  if mode=='patch_update':
   changes[0]['diff']='+changed effect'
   emit({'method':'item/fileChange/patchUpdated','params':{'threadId':'thread','turnId':'1','itemId':'tool','changes':changes}})
 if method=='turn/interrupt':
  emit({'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'1','status':'interrupted'}}})
'''


class NativePermissionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def start(self, mode='command', enabled=True):
        project = self.root / mode
        project.mkdir()
        store = SessionStore(project, self.root / ('state-' + mode))
        self.addCleanup(store.close)
        trace = self.root / (mode + '.trace')
        backend = NativeWorkflowConnection([sys.executable, '-u', '-c', SERVER, str(trace), str(project),
            str(store.directory), mode, json.dumps(CATALOG)], 1)
        self.addCleanup(backend.close)
        backend.experimental_tool_approvals = enabled
        controller = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
        host = backend.connect(controller, project, POLICY, store=store)
        host.configure_check(0, command='printf synthetic', cwd=str(project))
        shell = ChatShell(io.StringIO(), workflow=controller, workflow_action=host)
        shell.line('/next')
        return backend, controller, shell, store, project, trace

    def pump(self, backend, predicate):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            backend.drain()
            if predicate():return
            for key, _ in backend.selector.select(.02):backend.read_ready(key.fileobj)
        self.fail('Synthetic native approval did not reach its expected state.')

    def records(self, trace):
        return [json.loads(line) for line in trace.read_text().splitlines()]

    def test_explicit_accept_is_durable_once_and_separate_from_check_evidence(self):
        for mode in ('command', 'patch'):
            with self.subTest(mode=mode):
                backend, c, shell, store, project, trace = self.start(mode)
                self.pump(backend, lambda: c.state == 'AWAITING_TOOL_APPROVAL')
                self.assertFalse((project / 'effect').exists())
                token = shell.pending['token']
                shell.line('/approve wrong');shell.line('/approve ' + token + ' --next')
                self.assertFalse((project / 'effect').exists())
                shell.line('/approve ' + token)
                self.pump(backend, lambda: c.state == 'CHECKING')
                self.assertTrue((project / 'effect').exists())
                shell.line('/approve ' + token)
                backend.request('account/read')
                self.assertEqual([r['result']['decision'] for r in self.records(trace) if 'result' in r], ['accept'])
                self.assertEqual(store.read(backend.session_id)['workflow']['tool_request']['status'], 'approved')
                self.assertNotEqual(c.state, 'DONE')
                checks = c.snapshot()['active_attempt']['checks']
                if mode == 'command':self.assertEqual(checks[0]['result'], 'pass')
                else:self.assertEqual(checks, {})
                backend.close()

    def test_explicit_decline_and_close_do_not_perform_the_effect(self):
        for mode in ('command', 'patch'):
            with self.subTest(mode=mode):
                backend, c, shell, _, project, trace = self.start(mode)
                self.pump(backend, lambda: c.state == 'AWAITING_TOOL_APPROVAL')
                token = shell.pending['token']
                if mode == 'command':
                    shell.line('/decline ' + token)
                    self.pump(backend, lambda: c.state == 'CHECKING')
                backend.close()
                self.assertFalse((project / 'effect').exists())
                self.assertEqual([r['result']['decision'] for r in self.records(trace) if 'result' in r], ['decline'])

    def test_patch_update_declines_old_token_without_performing_the_effect(self):
        backend, c, shell, _, project, trace = self.start('patch_update')
        self.pump(backend, lambda: c.state == 'CHECKING')
        self.assertIsNone(shell.pending)
        self.assertFalse((project / 'effect').exists())
        self.assertEqual([r['result']['decision'] for r in self.records(trace) if 'result' in r], ['decline'])

    def test_unsupported_duplicate_or_foreign_requests_never_accept(self):
        for mode in ('scope', 'no_preview', 'duplicate', 'foreign'):
            with self.subTest(mode=mode):
                backend, c, _, _, project, trace = self.start(mode)
                if mode in ('scope', 'no_preview', 'foreign'):
                    with self.assertRaises(ProbeError):self.pump(backend, lambda: c.state == 'PAUSED')
                else:self.pump(backend, lambda: c.state == 'PAUSED')
                backend.close()
                self.assertFalse((project / 'effect').exists())
                self.assertNotIn('accept', [r['result']['decision'] for r in self.records(trace) if 'result' in r])

    def test_default_adapter_still_declines_without_opt_in(self):
        backend, _, _, _, project, trace = self.start(enabled=False)
        with self.assertRaises(ProbeError):self.pump(backend, lambda: False)
        backend.close()
        self.assertFalse((project / 'effect').exists())
        self.assertEqual([r['result']['decision'] for r in self.records(trace) if 'result' in r], ['decline'])

    def test_native_cancel_exit_timeout_and_disconnect_decline_then_observe_interruption(self):
        for event in ('cancel', 'exit', 'timeout', 'disconnect'):
            with self.subTest(event=event):
                backend, c, shell, _, project, trace = self.start('hold_' + event)
                self.pump(backend, lambda: c.state == 'AWAITING_TOOL_APPROVAL')
                token = shell.pending['token']
                if event == 'timeout':
                    backend.host._deadline = time.monotonic() - 1
                    with self.assertRaisesRegex(ProbeError, 'timed out'):backend.tick()
                elif event == 'disconnect':backend.host.disconnect()
                else:shell.cancel(exit_after=event == 'exit')
                self.pump(backend, lambda: backend.host._terminal is not None)
                self.assertEqual(backend.host._terminal, 'interrupted')
                self.assertFalse((project / 'effect').exists())
                with self.assertRaises(ProbeError):backend.host.answer_tool_approval(token, 'approve')
                backend.close()
                records = self.records(trace)
                self.assertEqual([r['result']['decision'] for r in records if 'result' in r], ['decline'])
                self.assertEqual(sum(r.get('method') == 'turn/interrupt' for r in records), 1)
                self.assertEqual(sum(r.get('method') == 'turn/start' for r in records), 1)
                self.assertNotEqual(c.state, 'DONE')

    def test_native_eof_declines_before_exit_and_waits_for_terminal_confirmation(self):
        backend, c, _, _, project, trace = self.start('hold_eof')
        self.pump(backend, lambda: c.state == 'AWAITING_TOOL_APPROVAL')
        backend.host.on_change = None
        with tempfile.TemporaryFile() as source:
            self.assertEqual(run_chat(source, io.StringIO(), backend=backend,
                workflow=c, workflow_action=backend.host), 0)
        self.assertEqual(backend.host._terminal, 'interrupted')
        self.assertFalse((project / 'effect').exists())
        self.assertEqual([r['result']['decision'] for r in self.records(trace) if 'result' in r], ['decline'])

    def test_native_process_loss_keeps_unresolved_attempt_and_never_restores_permission(self):
        backend, c, shell, store, project, trace = self.start('hold_lost')
        self.pump(backend, lambda: c.state == 'AWAITING_TOOL_APPROVAL')
        token, sid = shell.pending['token'], backend.session_id
        backend.process.kill();backend.process.wait(timeout=2)
        backend.read_ready(backend.process.stdout)
        with self.assertRaisesRegex(ProbeError, 'disconnected'):backend.drain()
        backend.close()
        self.assertTrue(all(stream.closed for stream in
                            (backend.process.stdin, backend.process.stdout, backend.process.stderr)))
        self.assertIsNone(backend.host._terminal)
        self.assertFalse((project / 'effect').exists())
        with store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY) as restored:
            self.assertEqual((restored.state, restored.reason), ('PAUSED', 'outcome_unknown'))
            self.assertEqual(restored.snapshot()['active_attempt']['status'], 'running')
            self.assertEqual(restored.snapshot()['steps'][0]['attempts'], 1)
            request = restored.export_checkpoint()['tool_request']
            with self.assertRaises(ProbeError):
                restored.answer_tool_approval(token, 'approve', request['binding'], request['action_digest'])
        self.assertNotIn('accept', [r['result']['decision'] for r in self.records(trace) if 'result' in r])
        self.assertEqual(sum(r.get('method') == 'turn/start' for r in self.records(trace)), 1)

    def test_lost_accept_send_result_is_not_replayed_and_does_not_imply_rollback(self):
        backend, c, shell, _, project, trace = self.start('hold_send')
        self.pump(backend, lambda: c.state == 'AWAITING_TOOL_APPROVAL')
        token = shell.pending['token']
        send = backend.send
        def lost_result(message):
            send(message)
            if message.get('result', {}).get('decision') == 'accept':
                raise OSError('synthetic failure after writing acceptance')
        with patch.object(backend, 'send', side_effect=lost_result):
            with self.assertRaises(OSError):backend.host.answer_tool_approval(token, 'approve')
        self.assertEqual(c.reason, 'connection_lost')
        with self.assertRaises(ProbeError):backend.host.answer_tool_approval(token, 'approve')
        backend.request('account/read')
        self.assertTrue((project / 'effect').exists())
        self.assertNotEqual(c.state, 'DONE')
        self.assertEqual([r['result']['decision'] for r in self.records(trace) if 'result' in r], ['accept'])
        self.assertEqual(sum(r.get('method') == 'turn/start' for r in self.records(trace)), 1)
