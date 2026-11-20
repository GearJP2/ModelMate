"""Recovery inspects native metadata; no command/model execution or current evidence."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import Mock, patch

from modelmate import (Connection, LiveChatConnection, RecheckRecoveryConnection, ProbeError, SessionStore,
                       WorkflowController, run_recheck_recovery, run_session_cleanup, run_work_turn_inspection, validate_workflow_checkpoint, main)
from test_routing import PLAN, CATALOG, POLICY, QUOTA


SERVER = r'''
import json,sys
trace,project,mode,marker=sys.argv[1:]
interrupted=False;reads=0;quotas=0
for line in sys.stdin:
 req=json.loads(line);method=req.get('method');p=req.get('params',{})
 with open(trace,'a') as f:f.write(json.dumps(req)+'\n')
 if 'id' not in req:continue
 if method=='initialize':result={}
 elif method=='account/read':result={'account':{'type':'apiKey' if mode=='api_key' else 'chatgpt'}}
 elif method=='account/rateLimits/read':
  quotas+=1
  result={'accountId':'foreign' if mode=='account' or (mode=='account_change' and quotas>1) else 'synthetic',
   'ordinaryUsageAllowed':True,'rateLimits':{'primary':{'usedPercent':100 if mode=='exhausted' else 5}}}
  if mode=='quota_unknown':result={}
 elif method=='thread/read':
  reads+=1
  active=mode in ('active','ack_only','changed','account_change','finished_before_stop') and not interrupted
  if mode=='finished_before_stop' and reads>1:active=False
  result={'thread':{'id':p['threadId'],'cwd':project,'modelProvider':'openai','ephemeral':False,
   'status':{'type':'active' if active else 'idle'}}}
  if mode=='project':result['thread']['cwd']='/PRIVATE_PATH'
  if mode=='provider':result['thread']['modelProvider']='foreign'
  if mode=='ephemeral':result['thread']['ephemeral']=True
  if mode=='thread_id':result['thread']['id']='foreign'
 elif method=='thread/turns/list':
  active=mode in ('active','ack_only','changed','account_change','finished_before_stop') and not interrupted
  if mode=='finished_before_stop' and reads>1:active=False
  status='inProgress' if active else 'interrupted' if interrupted or mode=='interrupted' else 'failed' if mode=='failed' else 'completed'
  result={'data':[{'id':'work-turn' if p['threadId']=='work-thread' else 'check-turn','status':status}],'nextCursor':None}
  if p.get('itemsView')=='full':
   result['data'][0].update(itemsView='full',items=[
    {'type':'userMessage','clientId':None if mode=='missing_marker' else marker}])
   if mode=='duplicate_marker':result['data'][0]['items']*=2
  if mode=='turn_id' or (mode=='changed' and reads>1):result['data'][0]['id']='foreign'
  if mode=='empty':result['data']=[]
  if mode=='older':result['nextCursor']='older'
 elif method=='turn/interrupt':
  if mode!='ack_only':interrupted=True
  result={}
 else:raise RuntimeError(method)
 print(json.dumps({'id':req['id'],'result':result}),flush=True)
'''


class RecheckRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.project=self.root/'project';self.project.mkdir()
        self.home=self.root/'state';self.trace=self.root/'trace'
        self.store=SessionStore(self.project,self.home);self.addCleanup(self.store.close)
        self.make_pending()

    def make_pending(self,phase='turn_bound', *, correlated=False):
        record=self.store.create('recovery fixture',thread_id='work-thread',
            account_hash=hashlib.sha256(QUOTA['accountId'].encode()).hexdigest())
        self.sid=record['id'];self.plan=json.dumps(PLAN)
        with self.store.workflow(self.sid,QUOTA,time.monotonic(),CATALOG,POLICY,
                controller=WorkflowController(self.plan,CATALOG,POLICY)) as c:
            aid=c.request_attempt(QUOTA,time.monotonic(),CATALOG,POLICY)['dispatch']['attempt_id']
            c.finish_attempt(aid,'completed')
            self.evidence=c.record_check(aid,0,origin='tool',exit_code=0,reference='synthetic',finding='observed')
            c.evaluate_attempt(aid);c.finish_task({0:[self.evidence['id']]})
            record=self.store.read(self.sid);record['turn_id']='work-turn';self.store.save(record)
        with self.store.workflow(self.sid,QUOTA,time.monotonic(),CATALOG,POLICY) as c:
            self.op=c.reserve_recheck(self.evidence['id'],'printf synthetic',str(self.project),
                {'model':'synthetic-standard','effort':'low'},QUOTA,time.monotonic(),CATALOG,POLICY)
            if phase!='reserved':c.advance_recheck(self.op['id'],'thread',thread_id='check-thread')
            if phase in ('turn_pending','turn_bound'):
                fields = {'client_message_id': str(uuid.UUID(hex=self.op['id']))} if correlated else {}
                c.advance_recheck(self.op['id'],'turn_reserved', **fields)
            if phase=='turn_bound':c.advance_recheck(self.op['id'],'turn',turn_id='check-turn')
            c.advance_recheck(self.op['id'],'finish',status='unknown',exit_code=None,item_id=None)
        self.before=self.store.read(self.sid)

    def backend(self,mode='complete'):
        marker = str(uuid.UUID(hex=self.op['id']))
        backend=RecheckRecoveryConnection([sys.executable,'-u','-c',SERVER,str(self.trace),str(self.project),mode,marker],.5)
        self.addCleanup(backend.close);return backend

    def records(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def cleanup_backend(self):
        backend = LiveChatConnection([sys.executable, '-c', 'import time;time.sleep(30)'], .5)
        self.addCleanup(backend.close)
        backend.store, backend.cwd = self.store, str(self.project)
        backend.account_id = QUOTA['accountId']
        backend._fresh_account = Mock()
        threads = {
            tid: {'id': tid, 'cwd': str(self.project), 'modelProvider': 'openai',
                  'ephemeral': False, 'status': {'type': 'idle'}}
            for tid in ('work-thread', 'check-thread', 'check-child', 'unrelated')
        }
        threads['check-child']['parentThreadId'] = 'check-thread'

        def reply(method, params):
            if method == 'thread/list':
                return {'data': [row for tid, row in threads.items()
                                 if (tid == 'check-child') == params['archived']]}
            if method == 'thread/read':
                return {'thread': threads.get(params['threadId'])}
            if method == 'thread/turns/list':
                return {'data': [{'status': 'completed'}]}
            if method == 'thread/delete':
                del threads[params['threadId']]
                if params['threadId'] == 'check-thread':
                    del threads['check-child']
                return {}
            raise AssertionError(method)

        backend.request = Mock(side_effect=reply)
        return backend, threads

    def test_scoped_cleanup_includes_independent_recheck_and_its_archived_child(self):
        backend, threads = self.cleanup_backend()
        with self.store._lock(self.sid):
            record = self.store.read(self.sid)
            tree = backend._deletion_tree(record)
            self.assertEqual({row['thread_id']: row['delete_root'] for row in tree}, {
                'check-thread': 'check-thread', 'check-child': 'check-thread', 'work-thread': 'work-thread'})
            self.assertEqual(self.store.read(self.sid), self.before)
            with patch.object(self.store, 'remove', side_effect=OSError):
                with self.assertRaises(OSError):
                    backend._confirm_session_deletion(record, tree)
            saved = self.store.read(self.sid)
            self.assertEqual(saved['recheck_cleanup'], {'deleted': ['check-thread', 'work-thread'], 'pending': None})
            self.assertEqual(saved['deletion_state'], 'remote_deleted')
            backend._confirm_session_deletion(saved, backend._deletion_tree(saved))
        self.assertEqual(list(threads), ['unrelated'])
        self.assertEqual(self.store.list_sessions(), [])
        self.assertEqual([call.args[1]['threadId'] for call in backend.request.call_args_list
                          if call.args[0] == 'thread/delete'], ['check-thread', 'work-thread'])

    def test_cleanup_resumes_older_work_root_receipt(self):
        backend, threads = self.cleanup_backend()
        del threads['work-thread']
        with self.store._lock(self.sid):
            record = self.store.read(self.sid)
            record.update(deletion_state='remote_deleted', state='PAUSED', pause_reason='deletion_pending')
            self.store.save(record)
            tree = backend._deletion_tree(record)
            self.assertEqual({row['delete_root'] for row in tree}, {'check-thread'})
            backend._confirm_session_deletion(record, tree)
        self.assertEqual(set(threads), {'unrelated'})
        self.assertEqual(self.store.list_sessions(), [])

    def test_cleanup_cli_requires_exact_confirmation_with_enter(self):
        import uuid

        backend, threads = self.cleanup_backend()
        reply = backend.request.side_effect
        backend.request.side_effect = lambda method, params: (
            {} if method == 'initialize' else reply(method, params))
        token = uuid.UUID(int=10)
        for ending, expected in [(b'', 2), (b'\n', 0)]:
            read_fd, write_fd = os.pipe()
            with os.fdopen(write_fd, 'wb') as writer:
                writer.write(('DELETE ' + token.hex).encode() + ending)
            output = io.StringIO()
            with (os.fdopen(read_fd) as reader,
                  patch('modelmate.os.getcwd', return_value=str(self.project)),
                  patch.dict(os.environ, {'XDG_STATE_HOME': str(self.home)}),
                  patch('modelmate.LiveChatConnection', return_value=backend),
                  patch.object(backend, 'send'), patch.object(backend, 'close'),
                  patch('uuid.uuid4', return_value=token)):
                self.assertEqual(run_session_cleanup(self.sid, reader, output), expected)
            self.assertIn('check-child', output.getvalue())
            if expected == 2:
                self.assertEqual(self.store.read(self.sid), self.before)
                self.assertFalse(any(call.args[0] == 'thread/delete' for call in backend.request.call_args_list))
        self.assertEqual(set(threads), {'unrelated'})
        self.assertFalse(any(call.args[0] in ('turn/start', 'thread/start', 'thread/resume', 'turn/interrupt')
                             for call in backend.request.call_args_list))

    def test_partial_cleanup_keeps_receipt_and_never_replays_uncertain_root(self):
        backend, threads = self.cleanup_backend()
        reply = backend.request.side_effect

        def disconnected(method, params):
            if method == 'thread/delete' and params['threadId'] == 'work-thread':
                raise ProbeError('Synthetic disconnect.')
            return reply(method, params)

        backend.request.side_effect = disconnected
        with self.store._lock(self.sid):
            record = self.store.read(self.sid)
            tree = backend._deletion_tree(record)
            with self.assertRaisesRegex(ProbeError, 'disconnect'):
                backend._confirm_session_deletion(record, tree)
            saved = self.store.read(self.sid)
            self.assertEqual(saved['recheck_cleanup'], {'deleted': ['check-thread'], 'pending': 'work-thread'})
            with self.assertRaisesRegex(ProbeError, 'unconfirmed'):
                backend._deletion_tree(saved)
        self.assertEqual(set(threads), {'work-thread', 'unrelated'})

    def test_cleanup_refuses_active_foreign_or_separately_bound_threads(self):
        backend, threads = self.cleanup_backend()
        with self.store._lock(self.sid):
            record = self.store.read(self.sid)
            for key, value in [('status', {'type': 'active'}), ('cwd', '/other-project')]:
                with patch.dict(threads['check-child'], {key: value}):
                    with self.assertRaises(ProbeError):
                        backend._deletion_tree(record)
            self.store.create('Other saved binding', thread_id='check-thread')
            with self.assertRaisesRegex(ProbeError, 'another ModelMate session'):
                backend._deletion_tree(record)
        self.assertFalse(any(call.args[0] == 'thread/delete' for call in backend.request.call_args_list))

    def test_cleanup_refuses_lost_recheck_thread_binding(self):
        self.make_pending('reserved')
        backend, _ = self.cleanup_backend()
        with self.store._lock(self.sid), self.assertRaisesRegex(ProbeError, 'incomplete'):
            backend._deletion_tree(self.store.read(self.sid))
        backend.request.assert_not_called()

    def test_work_turn_inspection_reads_latest_bound_turn_without_revalidation(self):
        for mode, status, code in [('older', 'terminal', 0), ('failed', 'unverified', 2),
                                   ('turn_id', 'unverified', 2)]:
            with self.subTest(mode=mode):
                output = io.StringIO()
                with (patch('modelmate.os.getcwd', return_value=str(self.project)),
                      patch.dict(os.environ, {'XDG_STATE_HOME': str(self.home)}),
                      patch('modelmate.RecheckRecoveryConnection', return_value=self.backend(mode))):
                    self.assertEqual(run_work_turn_inspection(self.sid, output), code)
                report = json.loads(output.getvalue())
                self.assertEqual(report['state'], status)
                self.assertEqual(report['historicalChecks'], {'pass': 1, 'fail': 0, 'unknown': 0})
                self.assertEqual(self.store.read(self.sid), self.before)
        self.assertLessEqual({row['method'] for row in self.records()}, {
            'initialize', 'initialized', 'account/read', 'account/rateLimits/read',
            'thread/read', 'thread/turns/list'})

    def test_work_turn_inspection_does_not_infer_binding_for_running_attempt(self):
        raw = json.dumps(PLAN)
        record = self.store.create('unbound work attempt', thread_id='work-thread',
            account_hash=self.before['account_hash'])
        with self.store.workflow(record['id'], QUOTA, time.monotonic(), CATALOG, POLICY,
                controller=WorkflowController(raw, CATALOG, POLICY)) as controller:
            controller.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)
            # An older turn ID on disk is not enough to bind the current running attempt.
            saved = self.store.read(record['id'])
            saved['turn_id'] = 'work-turn'
            self.store.save(saved)
        output = io.StringIO()
        with (patch('modelmate.os.getcwd', return_value=str(self.project)),
              patch.dict(os.environ, {'XDG_STATE_HOME': str(self.home)}),
              patch('modelmate.RecheckRecoveryConnection') as connection):
            self.assertEqual(run_work_turn_inspection(record['id'], output), 2)
            connection.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['reason'], 'unconfirmed_attempt_binding')

    def test_terminal_recovery_preserves_evidence_counters_and_bindings(self):
        backend=self.backend()
        with self.store._lock(self.sid):
            report=backend.inspect_recheck(self.store,self.sid)
            self.assertEqual((report['state'],report['status']),('terminal','completed'))
            self.store.record_recheck_recovery(self.sid,report)
            self.assertEqual(backend.inspect_recheck(self.store,self.sid),{'state':'none'})
        after=self.store.read(self.sid)
        for field in ('steps','history','criterion_evidence','baseline'):
            self.assertEqual(after['workflow'][field],self.before['workflow'][field])
        self.assertEqual(after['workflow']['rechecks'][:-1],self.before['workflow']['rechecks'])
        self.assertEqual(after['workflow']['rechecks'][-1]['kind'],'reconcile')
        self.assertEqual((after['thread_id'],after['turn_id']),('work-thread','work-turn'))
        with self.store.workflow(self.sid,QUOTA,time.monotonic(),CATALOG,POLICY) as c:
            self.assertIn(self.evidence['id'],c.snapshot()['stale_evidence'])
            self.assertEqual(c.recheck_operations()[0]['exit_code'],None)
            with self.assertRaises(ProbeError):c.finish_task({0:[self.evidence['id']]})
            new=c.reserve_recheck(self.evidence['id'],'printf synthetic',str(self.project),
                {'model':'synthetic-standard','effort':'low'},QUOTA,time.monotonic(),CATALOG,POLICY)
            self.assertEqual((new['cycle'],new['number']),(0,2))
        self.assertFalse(any(r.get('method') in ('turn/start','thread/start','thread/resume','command/exec','model/list') for r in self.records()))

    def test_failed_and_interrupted_are_known_terminal_states_without_exit_codes(self):
        for mode in ('failed','interrupted'):
            with self.subTest(mode=mode),self.store._lock(self.sid):
                backend=self.backend(mode);report=backend.inspect_recheck(self.store,self.sid)
                self.assertEqual((report['state'],report['status']),('terminal',mode))
                backend.close()

    def test_active_turn_is_not_stopped_by_inspection(self):
        backend=self.backend('active')
        with self.store._lock(self.sid):
            self.assertEqual(backend.inspect_recheck(self.store,self.sid)['state'],'active')
        self.assertFalse(any(r.get('method')=='turn/interrupt' for r in self.records()))
        self.assertEqual(self.store.read(self.sid),self.before)

    def test_interrupt_rechecks_target_and_observes_terminal_not_ack(self):
        backend=self.backend('active')
        with self.store._lock(self.sid):
            initial=backend.inspect_recheck(self.store,self.sid)
            report=backend.interrupt_recheck(self.store,self.sid,initial,timeout=.2)
            self.assertEqual((report['state'],report['status']),('terminal','interrupted'))
            self.store.record_recheck_recovery(self.sid,report)
        interrupts=[r for r in self.records() if r.get('method')=='turn/interrupt']
        self.assertEqual([r['params'] for r in interrupts],[{'threadId':'check-thread','turnId':'check-turn'}])

    def test_ack_alone_stays_unverified_and_does_not_change_metadata(self):
        backend=self.backend('ack_only')
        with self.store._lock(self.sid):
            initial=backend.inspect_recheck(self.store,self.sid)
            report=backend.interrupt_recheck(self.store,self.sid,initial,timeout=.05)
            self.assertEqual(report['state'],'unverified')
        self.assertEqual(self.store.read(self.sid),self.before)
        self.assertEqual(sum(r.get('method')=='turn/interrupt' for r in self.records()),1)

    def test_changed_target_is_not_interrupted(self):
        backend=self.backend('changed')
        with self.store._lock(self.sid):
            initial=backend.inspect_recheck(self.store,self.sid)
            self.assertEqual(backend.interrupt_recheck(self.store,self.sid,initial)['state'],'unverified')
        self.assertFalse(any(r.get('method')=='turn/interrupt' for r in self.records()))

    def test_finished_while_user_decides_does_not_get_interrupted(self):
        backend=self.backend('finished_before_stop')
        with self.store._lock(self.sid):
            initial=backend.inspect_recheck(self.store,self.sid)
            report=backend.interrupt_recheck(self.store,self.sid,initial)
            self.assertEqual(report['state'],'terminal')
        self.assertFalse(any(r.get('method')=='turn/interrupt' for r in self.records()))

    def test_identity_and_auth_mismatches_never_mutate(self):
        for mode in ('api_key','account','project','provider','ephemeral','thread_id','quota_unknown'):
            with self.subTest(mode=mode),self.store._lock(self.sid):
                backend=self.backend(mode)
                with self.assertRaises(ProbeError):backend.inspect_recheck(self.store,self.sid)
                backend.close()
        self.assertEqual(self.store.read(self.sid),self.before)
        self.assertFalse(any(r.get('method')=='turn/interrupt' for r in self.records()))

    def test_unknown_or_extra_native_history_is_not_guessed(self):
        for mode in ('turn_id','empty','older'):
            with self.subTest(mode=mode),self.store._lock(self.sid):
                backend=self.backend(mode)
                self.assertEqual(backend.inspect_recheck(self.store,self.sid)['state'],'unverified')
                backend.close()

    def test_missing_bindings_do_not_query_or_guess_native_threads(self):
        for phase in ('reserved','thread_bound','turn_pending'):
            self.make_pending(phase)
            with self.subTest(phase=phase),self.store._lock(self.sid):
                backend=self.backend()
                self.assertEqual(backend.inspect_recheck(self.store,self.sid)['reason'],'missing_native_binding')
                backend.close()
        self.assertEqual(self.records(),[])

    def test_known_exhausted_quota_does_not_block_metadata_recovery(self):
        with self.store._lock(self.sid):
            self.assertEqual(self.backend('exhausted').inspect_recheck(self.store,self.sid)['state'],'terminal')

    def test_account_change_before_stop_prevents_interruption(self):
        backend=self.backend('account_change')
        with self.store._lock(self.sid):
            initial=backend.inspect_recheck(self.store,self.sid)
            with self.assertRaises(ProbeError):backend.interrupt_recheck(self.store,self.sid,initial)
        self.assertFalse(any(r.get('method')=='turn/interrupt' for r in self.records()))

    def test_writer_lock_and_terminal_binding_are_required(self):
        backend=self.backend()
        with self.assertRaises(ProbeError):backend.inspect_recheck(self.store,self.sid)
        self.assertEqual(self.records(),[])
        with self.store._lock(self.sid):
            report=backend.inspect_recheck(self.store,self.sid)
            for key in ('thread_id','turn_id','operation_id','state'):
                bad=dict(report);bad[key]='foreign'
                with self.assertRaises(ProbeError):self.store.record_recheck_recovery(self.sid,bad)
        self.assertEqual(self.store.read(self.sid),self.before)

    def test_unknown_recovery_status_cannot_be_persisted(self):
        with self.store._lock(self.sid):
            report=self.backend().inspect_recheck(self.store,self.sid)
            report['status']='inProgress'
            with self.assertRaises(ProbeError):self.store.record_recheck_recovery(self.sid,report)
        self.assertEqual(self.store.read(self.sid),self.before)

    def test_write_failure_is_idempotent_and_does_not_certify_evidence(self):
        with self.store._lock(self.sid):
            backend=self.backend();report=backend.inspect_recheck(self.store,self.sid)
            original=self.store.save
            def uncertain(record):original(record);raise OSError('synthetic after replacement')
            with patch.object(self.store,'save',side_effect=uncertain):
                with self.assertRaises(OSError):self.store.record_recheck_recovery(self.sid,report)
            self.assertEqual(backend.inspect_recheck(self.store,self.sid)['state'],'none')
        validate_workflow_checkpoint(self.store.read(self.sid)['workflow'])

    def run_cli(self,text,mode='active'):
        def factory(command,timeout=15):return self.backend(mode)
        with patch.dict(os.environ,{'XDG_STATE_HOME':str(self.home)}), \
             patch('modelmate.os.getcwd',return_value=str(self.project)), \
             patch('modelmate.RecheckRecoveryConnection',side_effect=factory), tempfile.TemporaryFile() as stream:
            stream.write(text);stream.seek(0)
            output=io.StringIO();code=run_recheck_recovery(self.sid,stream,output)
        return code,output.getvalue()

    def test_cli_pause_eof_and_invalid_input_do_not_interrupt(self):
        for text in (b'PAUSE\n',b'',b'YES\n',b'START\n'):
            with self.subTest(text=text):self.assertEqual(self.run_cli(text)[0],2)
        self.assertEqual(self.store.read(self.sid),self.before)
        self.assertFalse(any(r.get('method')=='turn/interrupt' for r in self.records()))

    def test_cli_stop_recovers_without_replaying_model_or_command(self):
        code,text=self.run_cli(b'\x1b[200~STOP\x1b[201~\n')
        self.assertEqual(code,0,text)
        self.assertEqual(self.store.read(self.sid)['workflow']['rechecks'][-1]['kind'],'reconcile')
        self.assertFalse(any(r.get('method') in ('thread/start','turn/start','command/exec') for r in self.records()))

    def test_cli_recovers_correlated_terminal_turn_without_replay(self):
        self.make_pending('turn_pending', correlated=True)
        code, output = self.run_cli(b'', mode='complete')
        self.assertEqual(code, 0, output)
        flow = self.store.read(self.sid)['workflow']
        self.assertEqual(flow['rechecks'][-1]['kind'], 'recover_turn')
        self.assertEqual(flow['rechecks'][-1]['turn_id'], 'check-turn')
        self.assertEqual(flow['steps'], self.before['workflow']['steps'])
        self.assertEqual(flow['rechecks'][:-1], self.before['workflow']['rechecks'])
        self.assertFalse(any(r.get('method') in ('turn/interrupt','thread/start','turn/start','command/exec')
                             for r in self.records()))
        self.assertEqual(self.run_cli(b'')[0], 0)

    def test_cli_leaves_missing_duplicate_or_unsettled_correlation_unchanged(self):
        self.make_pending('turn_pending', correlated=True)
        for mode in ('missing_marker', 'duplicate_marker', 'older', 'active'):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_cli(b'STOP\n', mode=mode)[0], 2)
                self.assertEqual(self.store.read(self.sid), self.before)
        self.assertFalse(any(r.get('method') == 'turn/interrupt' for r in self.records()))

    def test_cli_stop_reconciles_a_turn_that_finished_during_confirmation(self):
        code, output = self.run_cli(b'STOP\n', mode='finished_before_stop')
        self.assertEqual(code, 0, output)
        flow = self.store.read(self.sid)['workflow']
        self.assertEqual(flow['rechecks'][-1]['kind'], 'reconcile')
        self.assertEqual(flow['rechecks'][-1]['status'], 'completed')
        self.assertEqual(flow['steps'], self.before['workflow']['steps'])
        self.assertFalse(any(row['method'] in ('turn/interrupt', 'thread/start', 'turn/start')
                             for row in self.records()))

    def test_recovery_transport_cannot_start_or_resume_inference(self):
        backend=object.__new__(RecheckRecoveryConnection);backend.send=Mock()
        for method in ('thread/start','turn/start','thread/resume','model/list','command/exec'):
            with self.subTest(method=method),self.assertRaises(ProbeError):backend.request(method,{})
        backend.send.assert_not_called()

    def test_cli_without_pending_work_does_not_start_native_process(self):
        backend=self.backend()
        with self.store._lock(self.sid):
            self.store.record_recheck_recovery(self.sid,backend.inspect_recheck(self.store,self.sid))
        with patch.dict(os.environ,{'XDG_STATE_HOME':str(self.home)}), \
             patch('modelmate.os.getcwd',return_value=str(self.project)), \
             patch('modelmate.RecheckRecoveryConnection') as native:
            self.assertEqual(run_recheck_recovery(self.sid,io.StringIO(),io.StringIO()),0)
            native.assert_not_called()

    def test_main_dispatches_only_recovery_and_rejects_model_overrides(self):
        with patch('sys.argv',['modelmate.py','--recover-recheck',self.sid]), \
             patch('modelmate.run_recheck_recovery',return_value=2) as recovery:
            self.assertEqual(main(),2);recovery.assert_called_once()
        with patch('sys.argv',['modelmate.py','--recover-recheck',self.sid,'--model','synthetic']), \
             patch('sys.stderr',new_callable=io.StringIO),patch('modelmate.run_recheck_recovery') as recovery:
            with self.assertRaises(SystemExit) as error:main()
            self.assertEqual(error.exception.code,2);recovery.assert_not_called()

    def test_cli_reports_missing_binding_phase_without_starting_native_process(self):
        for phase in ('reserved', 'thread_bound', 'turn_pending'):
            self.make_pending(phase)
            before = self.store.read(self.sid)
            output = io.StringIO()
            with self.subTest(phase=phase), patch.dict(os.environ, {'XDG_STATE_HOME': str(self.home)}), \
                 patch('modelmate.os.getcwd', return_value=str(self.project)), \
                 patch('modelmate.RecheckRecoveryConnection') as native:
                self.assertEqual(run_recheck_recovery(self.sid, io.StringIO('STOP\n'), output), 2)
                self.assertIn(f'({phase})', output.getvalue())
                native.assert_not_called()
                self.assertEqual(self.store.read(self.sid), before)


if __name__=='__main__':unittest.main()
