"""Native recheck transport against synthetic JSONL servers; no live inference."""
import hashlib
import errno
import json
from pathlib import Path
import sys
import socket
import tempfile
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

from modelmate import (NativeRecheckConnection, NativeWorkflowConnection, ProbeError, SessionStore, WorkflowController,
                       private_recheck_server, validate_workflow_checkpoint)
from test_routing import CATALOG, PLAN, POLICY, QUOTA


SERVER = r'''
import json,sys
from pathlib import Path
trace,checkpoint,project,mode=sys.argv[1:]
quota_reads=0
tid='recheck-thread';turn='recheck-turn'
def emit(value):print(json.dumps(value),flush=True)
def thread(identity):
 return {'id':identity,'cwd':project,'ephemeral':False,'modelProvider':'openai','status':{'type':'idle'}}
def events(command):
 text=command['command'];cwd=command['cwd']
 if mode=='wrapped':text="/bin/bash -lc '"+text+"'"
 if mode=='wrong_cwd':cwd='/foreign'
 if mode=='wrong_command':text='printf unrelated'
 params={'threadId':tid,'turnId':turn}
 if mode=='foreign':params['turnId']='foreign'
 if mode not in ('no_command','hang','approval','patch_approval','unknown_request'):
  for name in ('item/started','item/completed'):
   item={'type':'commandExecution','id':'check-item','command':text,'cwd':cwd}
   if name=='item/completed':item.update(status='completed',exitCode=1 if mode=='test_fail' else 0)
   emit({'method':name,'params':dict(params,item=item)})
  if mode=='repeat':emit({'method':'item/started','params':dict(params,item={'type':'commandExecution','id':'repeated','command':text,'cwd':cwd})})
 if mode in ('approval','patch_approval','unknown_request'):
  method={'approval':'item/commandExecution/requestApproval','patch_approval':'item/fileChange/requestApproval','unknown_request':'PRIVATE_UNKNOWN'}[mode]
  emit({'id':99,'method':method,'params':dict(params,itemId='pending')});return
 if mode=='hang':return
 emit({'method':'item/completed','params':dict(params,item={'type':'agentMessage','id':'answer','text':'Model claims passed'})})
 emit({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':turn,'status':'failed' if mode=='turn_fail' else 'completed'}}})
for line in sys.stdin:
 req=json.loads(line);method=req.get('method');params=req.get('params',{})
 saved=json.loads(Path(checkpoint).read_text())
 latest=(saved['workflow'].get('rechecks') or [{}])[-1]
 entry=dict(req,ledgerPhase=latest.get('kind'),clientMessageId=latest.get('client_message_id'),workTurn=saved['turn_id'])
 with open(trace,'a') as stream:stream.write(json.dumps(entry)+'\n')
 if method is None or 'id' not in req:continue
 if method=='initialize':result={}
 elif method=='account/read':result={'account':{'type':'apiKey' if mode=='api_key' else 'chatgpt'}}
 elif method=='model/list':
  effort='medium' if mode=='catalog_before_turn' and quota_reads>=3 else 'low'
  result={'data':[{'model':'synthetic-'+r,'defaultReasoningEffort':effort,'supportedReasoningEfforts':[{'reasoningEffort':effort}]} for r in ('economy','standard','strong')]}
 elif method=='account/rateLimits/read':
  quota_reads+=1
  result={'accountId':'foreign' if mode=='account' else 'synthetic','ordinaryUsageAllowed':True,
   'rateLimits':{'primary':{'usedPercent':100 if mode=='quota_before_turn' and quota_reads>=3 else 5}}}
 elif method=='thread/read':
  result={'thread':thread(params['threadId'])}
  if mode=='shared_observer' and params['threadId']==tid:
   stopped=any(json.loads(row).get('method')=='turn/interrupt' for row in Path(trace).read_text().splitlines())
   result['thread']['status']={'type':'idle' if stopped else 'active'}
  if mode=='work_project':result['thread']['cwd']='/foreign'
  if mode=='work_busy':result['thread']['status']={'type':'active'}
 elif method=='thread/turns/list':
  result={'data':[{'id':'work-turn','status':'completed'}]}
  if mode=='shared_observer' and params['threadId']==tid:
   stopped=any(json.loads(row).get('method')=='turn/interrupt' for row in Path(trace).read_text().splitlines())
   result={'data':[{'id':turn,'status':'interrupted' if stopped else 'inProgress'}]}
  if mode=='recover_lost_reply':
   accepted=[r['params'] for line in Path(trace).read_text().splitlines()
             if (r:=json.loads(line))['method']=='turn/start']
   assert len(accepted)==1 and params['threadId']==accepted[0]['threadId']==tid
   recovered={'id':turn,'status':'completed'}
   if params.get('itemsView')=='full':
    recovered.update(itemsView='full',items=[
     {'type':'userMessage','clientId':accepted[0]['clientUserMessageId']}])
   result={'data':[recovered]}
 elif method=='thread/resume':result={'thread':thread(params['threadId']),'approvalPolicy':'on-request','approvalsReviewer':'user','sandbox':{'type':'readOnly'}}
 elif method=='thread/start':
  if mode=='thread_error':emit({'id':req['id'],'error':{'code':-32000,'message':'PRIVATE_ERROR'}});continue
  result={'thread':thread('work-thread' if mode=='reused_work' else tid),'approvalPolicy':'on-request','approvalsReviewer':'user','sandbox':{'type':'readOnly'}}
  if mode=='permissions':result['sandbox']['type']='workspaceWrite'
  if mode=='ephemeral':result['thread']['ephemeral']=True
  if mode=='provider':result['thread']['modelProvider']='foreign'
 elif method=='turn/start':
  if mode=='lost_reply':break
  result={'turn':{} if mode=='unknown_turn' else {'id':turn}}
 elif method=='turn/interrupt':result={}
 else:raise RuntimeError(method)
 emit({'id':req['id'],'result':result})
 if method=='turn/start' and mode=='disconnect':break
 if method=='turn/start' and mode!='unknown_turn':events(json.loads(params['input'][0]['text'])['verification_commands'][0])
 if method=='turn/interrupt':emit({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':turn,'status':'interrupted'}}})
'''


class NativeRecheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / 'project';self.project.mkdir()
        self.trace = root / 'trace'
        self.store = SessionStore(self.project, root / 'state')
        self.addCleanup(self.store.close)
        record = self.store.create('synthetic parent', thread_id='work-thread',
            account_hash=hashlib.sha256(QUOTA['accountId'].encode()).hexdigest())
        self.sid = record['id']
        self.checkpoint = self.store.directory / (self.sid + '.json')
        controller = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
        with self.attach(controller) as c:
            aid = c.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)['dispatch']['attempt_id']
            c.finish_attempt(aid, 'completed')
            self.evidence = c.record_check(aid, 0, origin='tool', exit_code=0, reference='synthetic', finding='observed')
            c.evaluate_attempt(aid)
            record = self.store.read(self.sid);record['turn_id'] = 'work-turn';self.store.save(record)
        self.original = self.store.read(self.sid)

    def attach(self, controller=None):
        return self.store.workflow(self.sid, QUOTA, time.monotonic(), CATALOG, POLICY, controller=controller)

    def backend(self, mode='normal'):
        connection = NativeRecheckConnection([sys.executable, '-u', '-c', SERVER,
            str(self.trace), str(self.checkpoint), str(self.project), mode], .5)
        self.addCleanup(connection.close)
        return connection

    def start(self, connection, parent, **kwargs):
        args = dict(parent=parent, evidence_id=self.evidence['id'], command='printf synthetic',
            cwd=str(self.project), project=str(self.project), role_policy=POLICY,
            selection={'model':'synthetic-standard','effort':'low'}, work_thread_id='work-thread')
        args.update(kwargs)
        return connection.start_recheck(**args)

    def records(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def wait(self, connection):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            connection.drain()
            if connection.host._terminal is not None:return connection.operation()
            for key, _ in connection.selector.select(.02):connection.read_ready(key.fileobj)
        self.fail('synthetic native recheck did not terminate')

    def assert_revalidated(self, mode):
        with self.attach() as parent:
            connection = self.backend(mode)
            self.start(connection, parent)
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            result = self.wait(connection)
            self.assertEqual((result['status'], result['exit_code']), ('completed', 0))
            self.assertNotIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            record = self.store.read(self.sid)
            self.assertEqual(record['turn_id'], 'work-turn')
            self.assertEqual(record['thread_id'], 'work-thread')
            self.assertEqual(record['workflow']['history'], self.original['workflow']['history'])
            self.assertEqual(record['workflow']['steps'], self.original['workflow']['steps'])
            connection.close()

    def test_exact_result_revalidates_after_native_terminal(self): self.assert_revalidated('normal')
    def test_shell_wrapped_result_revalidates_after_native_terminal(self): self.assert_revalidated('wrapped')

    def test_reservations_are_on_disk_before_thread_and_turn_rpcs(self):
        with self.attach() as parent:
            connection = self.backend();self.start(connection, parent);self.wait(connection);connection.close()
        starts = [r for r in self.records() if r['method'] in ('thread/start','turn/start')]
        self.assertEqual([r['ledgerPhase'] for r in starts], ['reserve', 'turn_reserved'])
        self.assertTrue(all(r['workTurn'] == 'work-turn' for r in starts))
        thread = starts[0]['params']
        self.assertFalse(thread['ephemeral'])
        self.assertEqual(thread['sandbox'], 'read-only')
        self.assertEqual(thread['approvalPolicy'], 'on-request')
        self.assertEqual(starts[1]['params']['model'], 'synthetic-standard')
        self.assertEqual(starts[1]['params']['effort'], 'low')
        self.assertTrue(starts[1]['clientMessageId'])
        self.assertEqual(starts[1]['params']['clientUserMessageId'], starts[1]['clientMessageId'])
        self.assertFalse(any(r['method'] == 'command/exec' for r in self.records()))

    def test_child_observer_cannot_emit_authoritative_workflow_events_for_parent(self):
        events = []
        with self.attach() as parent:
            connection = self.backend();self.start(connection, parent, on_change=events.append)
            self.wait(connection)
            changes = [event for event in events if event['type'] == 'workflow_changed']
            self.assertEqual(changes, [{'type':'workflow_changed','task_id':parent.task_id}])
            self.assertTrue(any(event['type'] == 'text' for event in events))
            self.assertNotEqual(parent.state, 'DONE')
            connection.close()

    def assert_stale_result(self, mode):
        with self.attach() as parent:
            connection = self.backend(mode);self.start(connection, parent)
            self.wait(connection)
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            connection.close()

    def test_missing_command(self): self.assert_stale_result('no_command')
    def test_wrong_command(self): self.assert_stale_result('wrong_command')
    def test_wrong_cwd(self): self.assert_stale_result('wrong_cwd')
    def test_foreign_turn(self): self.assert_stale_result('foreign')
    def test_failed_check(self): self.assert_stale_result('test_fail')
    def test_failed_turn(self): self.assert_stale_result('turn_fail')

    def assert_no_turn(self, mode):
        with self.attach() as parent:
            connection = self.backend(mode)
            with self.assertRaises(ProbeError):self.start(connection, parent)
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            connection.close()
        self.assertFalse(any(r['method'] == 'turn/start' for r in self.records()))

    def test_api_key_auth(self): self.assert_no_turn('api_key')
    def test_wrong_account(self): self.assert_no_turn('account')
    def test_wrong_work_project(self): self.assert_no_turn('work_project')
    def test_busy_work_thread(self): self.assert_no_turn('work_busy')
    def test_expanded_permissions(self): self.assert_no_turn('permissions')
    def test_ephemeral_thread(self): self.assert_no_turn('ephemeral')
    def test_foreign_provider(self): self.assert_no_turn('provider')
    def test_reused_work_thread(self): self.assert_no_turn('reused_work')

    def test_thread_error_and_unknown_turn_are_reserved_and_never_replayed(self):
        with self.attach() as parent:
            connection = self.backend('unknown_turn')
            with self.assertRaises(ProbeError):self.start(connection, parent)
            self.assertEqual(connection.operation()['status'], 'unknown')
            with self.assertRaises(ProbeError):self.start(connection, parent)
            connection.close()
        with self.attach() as parent:
            other = self.backend()
            with self.assertRaisesRegex(ProbeError, 'unresolved'):self.start(other, parent)
            other.close()
        self.assertEqual(sum(r['method'] == 'turn/start' for r in self.records()), 1)
        self.assertEqual(sum(r['method'] == 'thread/start' for r in self.records()), 1)

    def test_thread_start_error_retains_reservation_without_starting_turn(self):
        with self.attach() as parent:
            connection = self.backend('thread_error')
            with self.assertRaises(ProbeError):self.start(connection, parent)
            self.assertEqual(connection.operation()['status'], 'unknown')
            connection.close()
        self.assertFalse(any(r['method'] == 'turn/start' for r in self.records()))

    def test_cancel_waits_for_terminal_and_cannot_accept_late_success(self):
        with self.attach() as parent:
            connection = self.backend('hang');self.start(connection, parent)
            connection.cancel()
            self.assertEqual(connection.operation()['status'], 'pending')
            self.assertEqual(self.wait(connection)['status'], 'interrupted')
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            connection.close()

    def test_cancel_racing_completed_turn_never_revalidates(self):
        with self.attach() as parent:
            connection = self.backend();self.start(connection, parent)
            connection.cancel()
            try:self.wait(connection)
            except ProbeError:pass
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            self.assertIsNone(connection.operation()['exit_code'])
            connection.close()

    def test_eof_leaves_unknown_without_replay(self):
        with self.attach() as parent:
            connection = self.backend('disconnect');self.start(connection, parent)
            with self.assertRaises(ProbeError):self.wait(connection)
            self.assertEqual(connection.operation()['status'], 'unknown')
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            connection.close()
        self.assertEqual(sum(r['method'] == 'turn/start' for r in self.records()), 1)

    def test_lost_start_reply_recovers_from_original_checkpoint_after_reconnect(self):
        from modelmate import RecheckRecoveryConnection

        with self.attach() as parent:
            connection = self.backend('lost_reply')
            with self.assertRaises(ProbeError):
                self.start(connection, parent)
            operation = connection.operation()
            self.assertEqual((operation['phase'], operation['status'], operation['turn_id']),
                             ('turn_pending', 'unknown', None))
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            connection.close()

        before = self.store.read(self.sid)
        recovery = RecheckRecoveryConnection([sys.executable, '-u', '-c', SERVER,
            str(self.trace), str(self.checkpoint), str(self.project), 'recover_lost_reply'], .5)
        self.addCleanup(recovery.close)
        with self.store._lock(self.sid):
            report = recovery.inspect_recheck(self.store, self.sid)
            self.assertEqual(report['state'], 'terminal')
            self.store.record_recheck_recovery(self.sid, report)
            self.assertEqual(recovery.inspect_recheck(self.store, self.sid), {'state': 'none'})
        after = self.store.read(self.sid)
        self.assertEqual(after['turn_id'], before['turn_id'])
        self.assertEqual(after['workflow']['steps'], before['workflow']['steps'])
        event = after['workflow']['rechecks'][-1]
        self.assertEqual((event['kind'], event['turn_id'], event['status']),
                         ('recover_turn', 'recheck-turn', 'completed'))
        methods = [r['method'] for r in self.records()]
        self.assertEqual(methods.count('turn/start'), 1)
        self.assertNotIn('turn/interrupt', methods)

    def test_shared_recovery_reconciles_attached_controller_and_disk(self):
        backend = NativeWorkflowConnection([sys.executable, '-c', 'import time; time.sleep(30)'], .5)
        self.addCleanup(backend.close)
        with self.attach() as parent:
            backend.store, backend.session_id = self.store, self.sid
            backend.controller, backend.host = parent, Mock(controller=parent)
            backend._attachment, backend._recheck_endpoint = MagicMock(), Mock()
            connection = self.backend('disconnect')
            self.start(connection, parent)
            with self.assertRaises(ProbeError):
                self.wait(connection)
            connection.close()
            operation = connection.operation()
            backend._shared_recheck_operation = operation['id']
            report = {'state': 'terminal', 'status': 'interrupted', 'operation_id': operation['id'],
                      'thread_id': operation['thread_id'], 'turn_id': operation['turn_id']}
            observer = Mock()
            observer.inspect_recheck.side_effect = [dict(report, turn_id='foreign'), report]
            with patch('modelmate.UnixWebSocket') as wire, \
                 patch('modelmate.RecheckRecoveryConnection', return_value=observer):
                with self.assertRaisesRegex(ProbeError, 'saved turn'):
                    backend.recover_shared_recheck()
                self.assertEqual(parent.recheck_operations()[0]['status'], 'unknown')
                self.assertEqual(backend.recover_shared_recheck(), report)
            wire.assert_called_with(backend._recheck_endpoint, .5)
            self.assertEqual(observer.close.call_count, 2)
            self.assertEqual(parent.recheck_operations()[0]['status'], 'interrupted')
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            self.assertEqual(self.store.read(self.sid)['workflow'], parent.export_checkpoint())

    def test_shared_recovery_connection_loss_preserves_unknown_checkpoint(self):
        backend = NativeWorkflowConnection([sys.executable, '-c', 'import time; time.sleep(30)'], .5)
        self.addCleanup(backend.close)
        with self.attach() as parent:
            backend.store, backend.session_id = self.store, self.sid
            backend.controller, backend.host = parent, Mock(controller=parent)
            backend._attachment, backend._recheck_endpoint = MagicMock(), Mock()
            connection = self.backend('disconnect')
            self.start(connection, parent)
            with self.assertRaises(ProbeError):
                self.wait(connection)
            connection.close()
            operation = connection.operation()
            backend._shared_recheck_operation = operation['id']
            before = self.store.read(self.sid)
            checkpoint = parent.export_checkpoint()
            observer = Mock()
            observer.inspect_recheck.side_effect = ProbeError('Recovery connection lost.')
            with patch('modelmate.UnixWebSocket'), \
                 patch('modelmate.RecheckRecoveryConnection', return_value=observer):
                with self.assertRaisesRegex(ProbeError, 'connection lost'):
                    backend.recover_shared_recheck()
                observer.close.assert_called_once_with()
                self.assertEqual(self.store.read(self.sid), before)
                self.assertEqual(parent.export_checkpoint(), checkpoint)
                self.assertEqual(parent.recheck_operations()[0]['status'], 'unknown')
                self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
                observer.inspect_recheck.side_effect = None
                observer.inspect_recheck.return_value = {'state': 'active',
                    'operation_id': operation['id'], 'thread_id': operation['thread_id'],
                    'turn_id': operation['turn_id']}
                self.assertEqual(backend.recover_shared_recheck()['state'], 'active')
                self.assertEqual(self.store.read(self.sid), before)
                observer.interrupt_recheck.assert_not_called()
            self.assertEqual(sum(r['method'] == 'turn/start' for r in self.records()), 1)

    def test_dead_owned_server_preserves_unknown_binding_across_resume(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as check:
            try:
                check.bind(str(self.project / 'capability.sock'))
            except PermissionError as exc:
                if exc.errno in (errno.EPERM, errno.EACCES):
                    self.skipTest('Environment forbids binding a private Unix socket.')
                raise
        executable = self.project / 'fake-codex'
        executable.write_text('''#!/usr/bin/env python3
import socket, sys, time
listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
listener.bind(sys.argv[3].removeprefix('unix://'))
listener.listen()
time.sleep(30)
''')
        executable.chmod(0o700)
        backend = NativeWorkflowConnection([sys.executable, '-c', 'import time; time.sleep(30)'], .5)
        self.addCleanup(backend.close)
        with self.attach() as parent:
            backend.store, backend.session_id = self.store, self.sid
            backend.controller, backend.host = parent, Mock(controller=parent)
            backend._attachment = MagicMock()
            connection = self.backend('disconnect')
            self.start(connection, parent)
            with self.assertRaises(ProbeError):
                self.wait(connection)
            connection.close()
            operation = connection.operation()
            backend._shared_recheck_operation = operation['id']
            before = self.store.read(self.sid)
            with private_recheck_server(2, executable=str(executable)) as endpoint:
                backend._recheck_endpoint = endpoint
                endpoint.server.terminate()
                endpoint.server.wait(timeout=2)
                self.assertTrue(endpoint.path.is_socket())
                with self.assertRaises(ConnectionRefusedError):
                    backend.recover_shared_recheck()
                self.assertEqual(self.store.read(self.sid), before)
                self.assertEqual(parent.export_checkpoint(), before['workflow'])
        with self.attach() as resumed:
            self.assertEqual(resumed.recheck_operations()[0], operation)
            self.assertIn(self.evidence['id'], resumed.snapshot()['stale_evidence'])
        self.assertEqual(sum(r['method'] == 'turn/start' for r in self.records()), 1)

    def test_approval_requests_decline_without_certifying_or_replaying(self):
        with self.attach() as parent:
            connection = self.backend('approval');self.start(connection, parent)
            with self.assertRaises(ProbeError):self.wait(connection)
            self.assertEqual(connection.operation()['status'], 'unknown')
            connection.close()
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
        replies = [r for r in self.records() if r.get('id') == 99 and 'result' in r]
        self.assertEqual([r['result'] for r in replies], [{'decision':'decline'}])

    def test_patch_approval_is_declined(self):
        with self.attach() as parent:
            connection = self.backend('patch_approval');self.start(connection, parent)
            with self.assertRaises(ProbeError):self.wait(connection)
            connection.close()
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
        self.assertEqual([r['result'] for r in self.records() if r.get('id') == 99 and 'result' in r],
                         [{'decision':'decline'}])

    def test_unsupported_server_request_is_not_accepted(self):
        with self.attach() as parent:
            connection = self.backend('unknown_request');self.start(connection, parent)
            with self.assertRaises(ProbeError):self.wait(connection)
            self.assertEqual(connection.operation()['status'], 'unknown')
            connection.close()
        self.assertFalse(any('result' in r and r.get('id') == 99 for r in self.records()))

    def test_repeated_command_makes_outcome_unknown(self):
        with self.attach() as parent:
            connection = self.backend('repeat');self.start(connection, parent)
            with self.assertRaises(ProbeError):self.wait(connection)
            self.assertEqual(connection.operation()['status'], 'unknown')
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            connection.close()

    def test_conflicting_late_terminal_revokes_validation_and_done(self):
        with self.attach() as parent:
            connection = self.backend();self.start(connection, parent);self.wait(connection)
            state = parent.snapshot()
            parent.answer_pause(state['pause_token'], 'continue')
            parent.finish_task({0: [self.evidence['id']]})
            self.assertEqual(parent.state, 'DONE')
            connection.request('turn/interrupt', {'threadId':connection.thread_id, 'turnId':'recheck-turn'})
            # The conflicting event can arrive after the RPC reply; the prior terminal is already present.
            with self.assertRaises(ProbeError):
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    connection.drain()
                    for key, _ in connection.selector.select(.02):
                        connection.read_ready(key.fileobj)
            self.assertEqual(parent.state, 'UNVERIFIED')
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            self.assertEqual(connection.operation()['status'], 'unknown')
            validate_workflow_checkpoint(self.store.read(self.sid)['workflow'])
            connection.close()

    def test_close_pending_turn_is_unknown_and_idempotent(self):
        with self.attach() as parent:
            connection = self.backend('hang');self.start(connection, parent)
            connection.close();connection.close()
            self.assertEqual(connection.operation()['status'], 'unknown')
        self.assertEqual(sum(r['method'] == 'turn/start' for r in self.records()), 1)

    def test_close_and_timeout_leave_unresolved_outcomes_without_new_turns(self):
        with self.attach() as parent:
            connection = self.backend('hang');self.start(connection, parent)
            connection.host._deadline = 0
            with self.assertRaises(ProbeError):connection.tick()
            self.assertEqual(connection.operation()['status'], 'unknown')
            connection.close()
        self.assertEqual(sum(r['method'] == 'turn/start' for r in self.records()), 1)

    def test_preflight_is_refreshed_after_thread_creation_before_turn(self):
        with self.attach() as parent:
            connection = self.backend('quota_before_turn')
            with self.assertRaises(ProbeError):self.start(connection, parent)
            self.assertEqual(connection.operation()['status'], 'unknown')
            connection.close()
        self.assertFalse(any(r['method'] == 'turn/start' for r in self.records()))

    def test_catalog_change_before_turn_cannot_change_selection(self):
        with self.attach() as parent:
            connection = self.backend('catalog_before_turn')
            with self.assertRaises(ProbeError):self.start(connection, parent)
            self.assertEqual(connection.operation()['status'], 'unknown')
            connection.close()
        self.assertFalse(any(r['method'] == 'turn/start' for r in self.records()))

    def test_changed_command_after_reservation_cannot_start_turn(self):
        with self.attach() as parent:
            connection = self.backend()
            original_preflight = connection.preflight
            def tampered_preflight():
                result = original_preflight()
                if connection.operation_id is not None:
                    connection._spec['command'] = 'printf changed'
                return result
            with patch.object(connection, 'preflight', side_effect=tampered_preflight):
                with self.assertRaises(ProbeError):self.start(connection, parent)
            self.assertEqual(connection.operation()['status'], 'unknown')
            connection.close()
        self.assertFalse(any(r['method'] == 'turn/start' for r in self.records()))

    def test_unconsented_selection_cannot_even_create_thread(self):
        with self.attach() as parent:
            connection = self.backend()
            with self.assertRaises(ProbeError):
                self.start(connection, parent, selection={'model':'synthetic-strong','effort':'low'})
            connection.close()
        self.assertFalse(any(r['method'] in ('thread/start','turn/start') for r in self.records()))

    def test_persist_failure_after_turn_response_never_rebinds_work_or_validates(self):
        with self.attach() as parent:
            connection = self.backend()
            original = parent.advance_recheck
            def save_failure(identity, kind, **values):
                if kind == 'turn':raise OSError('synthetic binding save failure')
                return original(identity, kind, **values)
            with patch.object(parent, 'advance_recheck', side_effect=save_failure):
                with self.assertRaises(OSError):self.start(connection, parent)
            self.assertIn(self.evidence['id'], parent.snapshot()['stale_evidence'])
            self.assertEqual(self.store.read(self.sid)['turn_id'], 'work-turn')
            connection.close()

    def test_reservation_save_failure_prevents_even_thread_start(self):
        with self.attach() as parent:
            connection = self.backend()
            with patch.object(self.store, 'save', side_effect=OSError('synthetic reservation failure')):
                with self.assertRaises(OSError):self.start(connection, parent)
            connection.close()
        self.assertFalse(any(r['method'] in ('thread/start','turn/start') for r in self.records()))

    def test_uncertain_thread_binding_write_prevents_turn_and_freezes_parent(self):
        with self.attach() as parent:
            connection = self.backend()
            original_save = self.store.save
            def fail_after_thread_write(record):
                original_save(record)
                if record['workflow']['rechecks'][-1]['kind'] == 'thread':
                    raise OSError('synthetic failure after thread binding replacement')
            with patch.object(self.store, 'save', side_effect=fail_after_thread_write):
                with self.assertRaises(OSError):self.start(connection, parent)
            self.assertTrue(parent._recheck_fault)
            self.assertEqual(connection.operation()['thread_id'], 'recheck-thread')
            with self.assertRaises(ProbeError):parent.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)
            connection.close()
        self.assertFalse(any(r['method'] == 'turn/start' for r in self.records()))

    def test_cancel_can_interrupt_even_when_parent_persistence_has_failed(self):
        with self.attach() as parent:
            connection = self.backend('hang');self.start(connection, parent)
            with patch.object(self.store, 'save', side_effect=OSError('synthetic ledger failure')):
                with self.assertRaises(OSError):
                    parent.advance_recheck(connection.operation_id, 'finish', status='unknown', exit_code=None, item_id=None)
            self.assertEqual(connection.operation()['status'], 'unknown')
            connection.cancel()
            self.assertTrue(any(r['method'] == 'turn/interrupt' for r in self.records()))
            connection.close()


if __name__ == '__main__':
    unittest.main()
