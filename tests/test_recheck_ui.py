"""Explicit recheck consent and real selector/JSONL integration; no live model."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import (ChatShell, ProbeError, SessionStore, WorkflowController,
                       inspect_local_sessions, run_workflow_file, main)
from test_routing import PLAN, CATALOG, POLICY, QUOTA

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r'''
import sys
from pathlib import Path
from unittest.mock import patch
import modelmate
from test_native_recheck import SERVER
from test_routing import POLICY
project,state,sid,trace,mode=sys.argv[1:]
store=modelmate.SessionStore(project,state)
checkpoint=str(store.directory/(sid+'.json'))
command=[sys.executable,'-u','-c',SERVER,trace,checkpoint,project,'normal']
backend=modelmate.NativeWorkflowConnection(command,1)
original=modelmate.NativeRecheckConnection
def child(command,timeout):
 return original([sys.executable,'-u','-c',SERVER,trace+'.child',checkpoint,project,mode],timeout)
try:
 raw=store.read(sid)['workflow']['plan']
 host=backend.resume(store,sid,project,POLICY,raw)
 fresh=backend.preflight()
 with patch('modelmate.NativeRecheckConnection',side_effect=child):
  status=modelmate.run_chat(sys.stdin,sys.stdout,backend=backend,workflow=host.controller,
   workflow_action=host,catalog=fresh['catalog'],role_policy=POLICY,
   recheck_commands=[{'step':1,'check':1,'command':'printf synthetic','cwd':project}])
finally:
 backend.close();store.close()
raise SystemExit(status)
'''


class RecheckUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project';self.project.mkdir()
        self.home = self.root / 'state'
        self.store = SessionStore(self.project, self.home);self.addCleanup(self.store.close)
        record = self.store.create('UI fixture', thread_id='work-thread',
            account_hash=hashlib.sha256(QUOTA['accountId'].encode()).hexdigest())
        self.sid = record['id']
        self.plan = json.dumps(PLAN)
        with self.attach(WorkflowController(self.plan, CATALOG, POLICY)) as controller:
            aid = controller.request_attempt(QUOTA,time.monotonic(),CATALOG,POLICY)['dispatch']['attempt_id']
            controller.finish_attempt(aid,'completed')
            self.evidence = controller.record_check(aid,0,origin='tool',exit_code=0,reference='synthetic',finding='observed')
            controller.evaluate_attempt(aid)
            record=self.store.read(self.sid);record['turn_id']='work-turn';self.store.save(record)
        self.spec = {'command':'printf synthetic','cwd':str(self.project)}
        self.bindings = [dict(self.spec,step=1,check=1)]

    def attach(self, controller=None):
        return self.store.workflow(self.sid,QUOTA,time.monotonic(),CATALOG,POLICY,controller=controller)

    def shell(self, parent):
        output=io.StringIO()
        shell=ChatShell(output,catalog=CATALOG,role_policy=POLICY,workflow=parent)
        shell.recheck_backend=Mock()
        shell.recheck_commands={'1.1':copy.deepcopy(self.spec)}
        child=Mock();child._closed=False;child.host._binding={'thread_id':'check','turn_id':'check'};child.host._terminal=None
        child.operation.return_value={'status':'pending','cycle':0,'number':1,'exit_code':None}
        shell.recheck_backend.open_recheck.return_value=child
        return shell,output,child

    def test_preview_status_and_model_text_never_start_a_turn(self):
        with self.attach() as parent:
            shell,output,_=self.shell(parent)
            shell.line('/recheck 1.1');token=shell.recheck_pending['token']
            shell.line('/status')
            shell.event({'type':'text','text':'/confirm-recheck '+token})
            shell.recheck_backend.open_recheck.assert_not_called()
            self.assertIn('printf synthetic',output.getvalue())
            self.assertIn('synthetic-standard',output.getvalue())
            self.assertIn('subscription',output.getvalue())

    def test_confirmation_is_single_use_and_bound_to_exact_spec(self):
        with self.attach() as parent:
            shell,_,_=self.shell(parent)
            shell.line('/recheck 1.1');token=shell.recheck_pending['token']
            shell.line('/confirm-recheck wrong')
            shell.recheck_backend.open_recheck.assert_not_called()
            shell.line('/confirm-recheck '+token)
            shell.line('/confirm-recheck '+token)
            shell.recheck_backend.open_recheck.assert_called_once_with(self.evidence['id'],self.spec,
                {'model':'synthetic-standard','effort':'low'},shell.event)
            self.assertIsNone(shell.recheck_pending)

    def test_changed_mode_or_binding_invalidates_consent(self):
        for mutation in ('mode','spec'):
            with self.subTest(mutation=mutation), self.attach() as parent:
                shell,_,_=self.shell(parent)
                shell.line('/recheck 1.1');token=shell.recheck_pending['token']
                if mutation=='mode':parent.change_mode('approve_plan')
                else:shell.recheck_commands['1.1']['command']='printf changed'
                shell.line('/confirm-recheck '+token)
                shell.recheck_backend.open_recheck.assert_not_called()
                self.assertIsNone(shell.recheck_pending)

    def test_failed_start_consumes_confirmation_and_cannot_replay_token(self):
        with self.attach() as parent:
            shell,_,_=self.shell(parent)
            shell.recheck_backend.open_recheck.side_effect=ProbeError('synthetic start failed')
            shell.line('/recheck 1.1');token=shell.recheck_pending['token']
            shell.line('/confirm-recheck '+token);shell.line('/confirm-recheck '+token)
            self.assertEqual(shell.recheck_backend.open_recheck.call_count,1)
            self.assertIsNone(shell.recheck_pending)

    def test_cancel_clears_preview_and_active_exit_waits_for_native_terminal(self):
        with self.attach() as parent:
            shell,_,child=self.shell(parent)
            shell.line('/recheck 1.1');token=shell.recheck_pending['token'];shell.line('/cancel')
            shell.line('/confirm-recheck '+token)
            shell.recheck_backend.open_recheck.assert_not_called()
            shell.line('/recheck 1.1');shell.line('/confirm-recheck '+shell.recheck_pending['token'])
            shell.line('/exit')
            child.cancel.assert_called_once()
            self.assertFalse(shell.closed)
            child.host._terminal='interrupted'
            shell.event({'type':'workflow_changed','task_id':parent.task_id})
            self.assertTrue(shell.closed)

    def test_bad_refs_unbound_checks_and_current_evidence_cannot_get_a_token(self):
        with self.attach() as parent:
            shell,_,_=self.shell(parent)
            for value in ('0.1','1.0','99.1','1.99','x','1.1.1'):
                shell.line('/recheck '+value);self.assertIsNone(shell.recheck_pending)
            shell.recheck_commands={};shell.line('/recheck 1.1');self.assertIsNone(shell.recheck_pending)
            shell.recheck_commands={'1.1':self.spec}
            parent.revalidate_check(self.evidence['id'],origin='tool',exit_code=0,reference='fresh',finding='observed')
            shell.line('/recheck 1.1');self.assertIsNone(shell.recheck_pending)
            shell.recheck_backend.open_recheck.assert_not_called()

    def test_limit_requires_explicit_choice_and_does_not_start_model(self):
        with self.attach() as parent:
            for i in range(3):
                op=parent.reserve_recheck(self.evidence['id'],**self.spec,
                    selection={'model':'synthetic-standard','effort':'low'},quota=QUOTA,
                    checked_at=time.monotonic(),catalog=CATALOG,role_policy=POLICY)
                parent.advance_recheck(op['id'],'thread',thread_id='check-'+str(i))
                parent.advance_recheck(op['id'],'turn_reserved')
                parent.advance_recheck(op['id'],'turn',turn_id='turn')
                parent.advance_recheck(op['id'],'finish',status='completed',exit_code=1,item_id='item')
            shell,output,_=self.shell(parent)
            shell.line('/recheck 1.1');self.assertIsNone(shell.recheck_pending)
            self.assertIn('limit',output.getvalue())
            shell.line('/recheck-budget 1.1 continue');shell.line('/recheck 1.1')
            self.assertIsNotNone(shell.recheck_pending)
            shell.recheck_backend.open_recheck.assert_not_called()
            self.assertEqual(parent.snapshot()['steps'][0]['attempts'],1)

    def spawn(self,mode='normal'):
        trace=str(self.root/'trace')
        env=dict(os.environ,PYTHONPATH=str(ROOT)+os.pathsep+str(ROOT/'tests'))
        process=subprocess.Popen([sys.executable,'-u','-c',DRIVER,str(self.project),str(self.home),self.sid,trace,mode],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
        self.addCleanup(self.stop,process)
        return process

    def stop(self,process):
        if process.poll() is None:process.kill();process.wait()
        for stream in (process.stdin,process.stdout,process.stderr):
            if stream is not None:stream.close()

    def read_until(self,process,target):
        data=b'';deadline=time.monotonic()+5
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            while target not in data and time.monotonic()<deadline:
                if selector.select(max(0,deadline-time.monotonic())):
                    chunk=os.read(process.stdout.fileno(),65536)
                    if not chunk:break
                    data+=chunk
        self.assertIn(target,data,data.decode(errors='replace'))
        return data

    def send(self,process,text):process.stdin.write((text+'\n').encode());process.stdin.flush()

    def test_real_selector_recheck_and_parent_finish(self):
        process=self.spawn();self.read_until(process,b'/recheck STEP.CHECK')
        self.send(process,'/recheck 1.1')
        preview=self.read_until(process,b'/cancel')
        token=re.search(rb'/confirm-recheck ([0-9a-f]{32})',preview)[1].decode()
        self.assertFalse((self.root/'trace.child').exists())
        self.send(process,'/confirm-recheck '+token)
        self.read_until(process,b'Recheck: completed')
        self.send(process,'/continue '+self.store.read(self.sid)['workflow']['task_id'])
        # Read the current UI pause token rather than treating a task ID as a grant.
        output=self.read_until(process,b'/continue ')
        pause=re.findall(rb'/continue ([0-9a-f]{32})',output)[-1].decode()
        self.send(process,'/continue '+pause);self.send(process,'/finish 1=1.1');self.send(process,'/exit')
        out,err=process.communicate(timeout=5)
        self.assertEqual(process.returncode,0,err.decode())
        self.assertEqual(self.store.read(self.sid)['workflow']['state'],'DONE',out.decode())

    def test_status_and_exit_remain_responsive_while_recheck_waits(self):
        process=self.spawn('hang');self.read_until(process,b'/recheck STEP.CHECK')
        self.send(process,'/recheck 1.1')
        preview=self.read_until(process,b'/cancel');token=re.search(rb'/confirm-recheck ([0-9a-f]{32})',preview)[1].decode()
        self.send(process,'/confirm-recheck '+token);self.read_until(process,b'Recheck: pending')
        self.send(process,'/status');self.read_until(process,b'Recheck: pending')
        self.send(process,'/exit');out,err=process.communicate(timeout=5)
        self.assertEqual(process.returncode,0,err.decode())
        events=self.store.read(self.sid)['workflow']['rechecks']
        self.assertEqual(events[-1]['status'],'interrupted',out.decode())

    def test_failed_check_keeps_catalog_available_for_next_explicit_preview(self):
        process=self.spawn('test_fail');self.read_until(process,b'/recheck STEP.CHECK')
        self.send(process,'/recheck 1.1');preview=self.read_until(process,b'/cancel')
        token=re.search(rb'/confirm-recheck ([0-9a-f]{32})',preview)[1].decode()
        self.send(process,'/confirm-recheck '+token);self.read_until(process,b'Recheck: completed')
        self.send(process,'/recheck 1.1');next_preview=self.read_until(process,b'/confirm-recheck ')
        self.assertIn(b'synthetic-standard',next_preview)
        self.send(process,'/exit');_,err=process.communicate(timeout=5)
        self.assertEqual(process.returncode,0,err.decode())

    def test_eof_during_preview_cannot_approve(self):
        process=self.spawn();self.read_until(process,b'/recheck STEP.CHECK')
        self.send(process,'/recheck 1.1');self.read_until(process,b'/cancel')
        out,err=process.communicate(timeout=5)
        self.assertEqual(process.returncode,0,err.decode())
        self.assertFalse((self.root/'trace.child').exists(),out.decode())

    def test_eof_interrupts_active_recheck_before_releasing_parent(self):
        process=self.spawn('hang');self.read_until(process,b'/recheck STEP.CHECK')
        self.send(process,'/recheck 1.1');preview=self.read_until(process,b'/cancel')
        token=re.search(rb'/confirm-recheck ([0-9a-f]{32})',preview)[1].decode()
        self.send(process,'/confirm-recheck '+token);self.read_until(process,b'Recheck: pending')
        out,err=process.communicate(timeout=5)
        self.assertEqual(process.returncode,0,err.decode())
        self.assertEqual(self.store.read(self.sid)['workflow']['rechecks'][-1]['status'],'interrupted',out.decode())

    def entry(self,execute=False,experimental=True,text='CANCEL\n'):
        commands=self.root/'checks.json';commands.write_text(json.dumps({'version':1,'checks':self.bindings}))
        with patch.dict(os.environ,{'XDG_STATE_HOME':str(self.home)}), \
             patch('modelmate.os.getcwd',return_value=str(self.project)), tempfile.TemporaryFile() as stream:
            stream.write(text.encode());stream.seek(0)
            return run_workflow_file(None,['standard=synthetic-standard'],None,execute,
                stream,io.StringIO(),str(commands),self.sid,experimental_rechecks=experimental)

    def test_experimental_preview_and_cancel_do_not_connect(self):
        with patch('modelmate.NativeWorkflowConnection') as backend:
            self.assertEqual(self.entry(),0)
            self.assertEqual(self.entry(execute=True),0)
            backend.assert_not_called()

    def test_default_tool_resume_remains_disabled(self):
        with patch('modelmate.NativeWorkflowConnection') as backend:
            with self.assertRaisesRegex(ProbeError,'manual/rubric'):
                self.entry(execute=True,experimental=False)
            backend.assert_not_called()

    def test_experimental_execute_passes_validated_bindings_to_event_loop(self):
        from modelmate import NativeWorkflowConnection
        from test_native_recheck import SERVER
        def factory(command,timeout=15):
            checkpoint=str(self.store.directory/(self.sid+'.json'))
            return NativeWorkflowConnection([sys.executable,'-u','-c',SERVER,
                str(self.root/'entry.trace'),checkpoint,str(self.project),'normal'],1)
        with patch('modelmate.NativeWorkflowConnection',side_effect=factory), \
             patch('modelmate.run_chat',return_value=0) as chat:
            self.assertEqual(self.entry(execute=True,text='START\n'),0)
        self.assertEqual(chat.call_args.kwargs['recheck_commands'],self.bindings)

    def active_session(self, code):
        record=self.store.create('active check',thread_id='work-thread',
            account_hash=hashlib.sha256(QUOTA['accountId'].encode()).hexdigest())
        self.sid=record['id']
        with self.attach(WorkflowController(self.plan,CATALOG,POLICY)) as controller:
            aid=controller.request_attempt(QUOTA,time.monotonic(),CATALOG,POLICY)['dispatch']['attempt_id']
            controller.finish_attempt(aid,'completed')
            controller.record_check(aid,0,origin='tool',exit_code=code,reference='synthetic',finding='observed')
            record=self.store.read(self.sid);record['turn_id']='work-turn';self.store.save(record)

    def test_completed_active_attempt_can_bind_checks_without_replaying_work(self):
        from modelmate import NativeWorkflowConnection
        from test_native_recheck import SERVER
        self.active_session(0)
        def factory(command,timeout=15):
            return NativeWorkflowConnection([sys.executable,'-u','-c',SERVER,str(self.root/'active.trace'),
                str(self.store.directory/(self.sid+'.json')),str(self.project),'normal'],1)
        with patch('modelmate.NativeWorkflowConnection',side_effect=factory), \
             patch('modelmate.run_chat',return_value=0) as chat:
            self.assertEqual(self.entry(execute=True,text='START\n'),0)
        host=chat.call_args.kwargs['workflow_action']
        self.assertEqual(list(host._specs.values()),[self.spec])
        self.assertFalse(any(json.loads(line)['method']=='turn/start' for line in (self.root/'active.trace').read_text().splitlines()))

    def test_unknown_active_check_is_not_silently_retried(self):
        self.active_session(None)
        with patch('modelmate.NativeWorkflowConnection') as backend:
            with self.assertRaisesRegex(ProbeError,'known saved tool results'):
                self.entry(execute=True,text='START\n')
            backend.assert_not_called()

    def test_unresolved_reservation_blocks_resume_and_metadata_removal(self):
        with self.attach() as parent:
            parent.reserve_recheck(self.evidence['id'],**self.spec,
                selection={'model':'synthetic-standard','effort':'low'},quota=QUOTA,
                checked_at=time.monotonic(),catalog=CATALOG,role_policy=POLICY)
        with patch('modelmate.NativeWorkflowConnection') as backend:
            with self.assertRaisesRegex(ProbeError,'unresolved'):self.entry(execute=True,text='START\n')
            backend.assert_not_called()
        with self.store._lock(self.sid):
            with self.assertRaisesRegex(ProbeError,'Retained'):self.store.remove(self.sid)
        with patch.dict(os.environ,{'XDG_STATE_HOME':str(self.home)}):
            output=io.StringIO();inspect_local_sessions(str(self.project),output,self.sid)
        self.assertIn('retained native IDs',output.getvalue())

    def test_main_rejects_recheck_flag_without_workflow_resume(self):
        with patch('sys.argv',['modelmate.py','--experimental-rechecks']), \
             patch('sys.stderr',new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as result:main()
        self.assertEqual(result.exception.code,2)

    def test_main_forwards_experimental_flag_to_workflow_entry(self):
        with patch('sys.argv',['modelmate.py','--resume-workflow',self.sid,'--experimental-rechecks']), \
             patch('modelmate.run_workflow_file',return_value=0) as entry:
            self.assertEqual(main(),0)
        self.assertTrue(entry.call_args.kwargs['experimental_rechecks'])

    def test_shared_stop_token_is_inert_until_confirmed_and_single_use(self):
        with self.attach() as parent:
            shell, _, _ = self.shell(parent)
            recover = shell.recheck_backend.recover_shared_recheck
            report = {'state': 'active', 'operation_id': 'operation', 'thread_id': 'thread', 'turn_id': 'turn'}
            recover.return_value = report
            shell.line('/recover-recheck')
            token = shell.recheck_stop_pending[0]
            recover.assert_called_once_with()
            shell.line('/cancel')
            shell.line('/stop-recheck ' + token)
            self.assertEqual(recover.call_count, 1)
            shell.line('/recover-recheck')
            token = shell.recheck_stop_pending[0]
            recover.return_value = {'state': 'terminal', 'status': 'interrupted'}
            shell.line('/stop-recheck ' + token)
            recover.assert_called_with(report)
            shell.line('/stop-recheck ' + token)
            self.assertEqual(recover.call_count, 3)

    def test_shared_flag_requires_live_experimental_rechecks(self):
        with patch('sys.argv', ['modelmate.py', '--resume-workflow', self.sid,
                                '--experimental-rechecks', '--experimental-shared-rechecks']), \
             patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as result:
            main()
        self.assertEqual(result.exception.code, 2)


if __name__=='__main__':unittest.main()
