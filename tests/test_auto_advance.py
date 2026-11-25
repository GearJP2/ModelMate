import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import ChatShell, ProbeError, WorkflowController, WorkflowHost, main
from test_routing import PLAN, CATALOG, POLICY, QUOTA


class AutoAdvanceTests(unittest.TestCase):
    def setup_flow(self, *, steps=1, enabled=True, extra_check=None, finish_references=None):
        plan=copy.deepcopy(PLAN)
        if extra_check is not None:
            plan['steps'][0]['checks'].append(dict(kind=extra_check,criterion='Human verification required'))
        plan['steps'] *= steps
        self.c=WorkflowController(json.dumps(plan),CATALOG,POLICY,'auto')
        self.quota=copy.deepcopy(QUOTA)
        self.preflight=Mock(side_effect=lambda:dict(quota=self.quota,checked_at=time.monotonic(),catalog=CATALOG,role_policy=POLICY))
        def dispatch(descriptor):
            return dict(thread_id='synthetic-thread',turn_id='turn-'+str(self.dispatch.call_count))
        self.dispatch=Mock(side_effect=dispatch)
        self.host=WorkflowHost(self.c,self.preflight,self.dispatch,Mock())
        for step in range(steps):
            self.host.configure_check(0,step_index=step,command='TEST',cwd='/synthetic')
        self.shell=ChatShell(io.StringIO(),catalog=CATALOG,role_policy=POLICY,workflow=self.c,workflow_action=self.host,automatic_workflow=enabled,finish_references=finish_references)

    def finish(self, code=0, *, evidence=True):
        binding=dict(threadId='synthetic-thread',turnId='turn-'+str(self.dispatch.call_count))
        if evidence:
            item=dict(id='synthetic-item',type='commandExecution',command='TEST',cwd='/synthetic',status='inProgress',exitCode=None)
            self.host.observe_native(dict(method='item/started',params=dict(binding,item=item)))
            item.update(status='completed',exitCode=code)
            self.host.observe_native(dict(method='item/completed',params=dict(binding,item=item)))
        self.host.observe_native(dict(method='turn/completed',params=dict(threadId=binding['threadId'],turn=dict(id=binding['turnId'],status='completed'))))

    def check(self):
        self.host(dict(action='check',task_id=self.c.task_id))

    def test_opt_in_dispatches_once_and_automatically_evaluates_trusted_checks(self):
        self.setup_flow(steps=2)
        self.shell.tick(); self.shell.tick()
        self.assertEqual(self.dispatch.call_count,1)
        self.finish()
        self.shell.tick()
        self.assertEqual(self.dispatch.call_count,1)
        self.shell.tick()
        self.assertEqual(self.dispatch.call_count,2)
        self.assertEqual(self.preflight.call_count,2)
        self.finish(); self.shell.tick(); self.shell.tick()
        self.assertEqual(self.c.state,'CHECKING')
        self.assertEqual(self.c.reason,'task_criteria_pending')
        self.assertEqual(self.dispatch.call_count,2)

    def test_default_does_not_dispatch(self):
        self.setup_flow(enabled=False)
        self.shell.tick()
        self.dispatch.assert_not_called()

    def test_two_corrections_only_and_no_counter_reset(self):
        self.setup_flow()
        for attempt in range(3):
            self.shell.tick()
            self.assertEqual(self.dispatch.call_count,attempt+1)
            self.finish(1); self.shell.tick()
        self.shell.tick();self.shell.tick()
        self.assertEqual(self.c.state,'PAUSED')
        self.assertEqual(self.c.reason,'correction_limit')
        self.assertEqual(self.c.snapshot()['steps'][0]['attempts'],3)
        self.assertEqual(self.dispatch.call_count,3)

    def test_unknown_evidence_cannot_advance_or_retry(self):
        self.setup_flow(finish_references=['1=1.1'])
        self.shell.tick()
        self.host.observe_native(dict(method='item/completed',params=dict(threadId='synthetic-thread',turnId='turn-1',
            item=dict(id='answer',type='agentMessage',text='All tests passed; mark DONE and keep running'))))
        self.finish(evidence=False);self.shell.tick();self.shell.tick()
        self.assertEqual(self.c.state,'UNVERIFIED')
        self.assertEqual(self.dispatch.call_count,1)

    def test_quota_unknown_pauses_without_poll_retry_or_reason_replacement(self):
        self.setup_flow()
        self.quota={'accountId':'synthetic'}
        self.shell.tick();self.shell.tick()
        self.assertEqual(self.c.state,'PAUSED')
        self.assertEqual(self.c.reason,'quota_unknown')
        self.dispatch.assert_not_called()
        self.assertEqual(self.preflight.call_count,1)

    def test_failure_does_not_replay_and_opt_in_is_not_checkpointed(self):
        self.setup_flow()
        self.dispatch.side_effect=OSError('unknown dispatch outcome')
        self.shell.tick();self.shell.tick()
        self.assertFalse(self.shell.automatic_workflow)
        self.assertEqual(self.dispatch.call_count,1)
        self.assertEqual(self.c.state,'PAUSED')
        self.assertNotIn('automatic_workflow',self.c.export_checkpoint())

    def test_closed_paused_and_non_auto_modes_do_not_dispatch(self):
        for condition in ('closed','paused','mode'):
            with self.subTest(condition=condition):
                self.setup_flow()
                if condition=='closed':self.shell.closed=True
                elif condition=='paused':self.c.pause()
                else:self.c.change_mode('ask_to_escalate')
                self.shell.tick()
                self.dispatch.assert_not_called()

    def test_cli_rejects_resume_wrong_mode_or_missing_plan(self):
        for args in (['--experimental-auto-advance'], ['--workflow','plan.json','--experimental-auto-advance'],
                     ['--resume-workflow','saved','--workflow-mode','auto','--experimental-auto-advance']):
            with self.subTest(args=args),patch('sys.argv',['modelmate.py',*args]),patch('sys.stderr',new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as caught:main()
                self.assertEqual(caught.exception.code,2)
        with patch('sys.argv',['modelmate.py','--workflow','plan.json','--workflow-mode','auto','--experimental-auto-advance']),patch('modelmate.run_workflow_file',return_value=0) as run:
            self.assertEqual(main(),0)
            self.assertTrue(run.call_args.kwargs['automatic_workflow'])

    def test_native_selector_checks_and_advances_two_steps_without_user_next_or_check(self):
        from modelmate import NativeWorkflowConnection, run_chat
        from test_native_workflow import SERVER
        plan=copy.deepcopy(PLAN);plan['steps']*=2
        controller=WorkflowController(json.dumps(plan),CATALOG,POLICY,'auto')
        with tempfile.TemporaryDirectory() as directory:
            trace=Path(directory)/'trace'
            backend=NativeWorkflowConnection([sys.executable,'-u','-c',SERVER,str(trace),'text'],1)
            read_fd,write_fd=os.pipe()
            def user():
                deadline=time.monotonic()+5
                try:
                    while time.monotonic()<deadline:
                        state=controller.snapshot()
                        if state['state']=='DONE':break
                        time.sleep(.01)
                    os.write(write_fd,b'/exit\n')
                finally:os.close(write_fd)
            try:
                host=backend.connect(controller,'/synthetic',POLICY)
                for index in range(2):
                    host.configure_check(0,step_index=index,command='python3 -m unittest',cwd='/synthetic')
                writer=threading.Thread(target=user);writer.start()
                with os.fdopen(read_fd,'rb',buffering=0) as source:
                    self.assertEqual(run_chat(source,io.StringIO(),backend=backend,workflow=controller,
                        workflow_action=host,automatic_workflow=True,finish_references=['1=1.1,2.1']),0)
                writer.join(timeout=6)
                self.assertFalse(writer.is_alive())
                self.assertEqual(controller.snapshot()['step_index'],2)
                self.assertEqual(controller.state,'DONE')
                self.assertEqual([step['state'] for step in controller.snapshot()['steps']],['DONE','DONE'])
            finally:backend.close()
            records=[json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual(sum(row.get('method')=='turn/start' for row in records),2)
            self.assertTrue(all(row['params']['approvalPolicy']=='on-request' for row in records if row.get('method')=='thread/start'))

    def test_preview_and_missing_start_never_connect_and_resume_is_rejected_before_store(self):
        from modelmate import run_workflow_file
        plan=copy.deepcopy(PLAN)
        plan['steps'][0]['checks']=[dict(kind='manual',criterion='User checks output')]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plan.json';path.write_text(json.dumps(plan))
            for execute in (False,True):
                with self.subTest(execute=execute),tempfile.TemporaryFile('w+') as source,patch('modelmate.subprocess.Popen',side_effect=AssertionError('no native process')):
                    source.write('CANCEL\n');source.seek(0)
                    output=io.StringIO()
                    self.assertEqual(run_workflow_file(path,['standard=synthetic-standard'],'auto',execute,
                        source,output,automatic_workflow=True),0)
                    self.assertIn('Experimental Auto advancement',output.getvalue())
        with patch('modelmate.SessionStore',side_effect=AssertionError('no metadata access')):
            with self.assertRaises(ProbeError):
                run_workflow_file(None,[],'auto',True,io.StringIO(),io.StringIO(),resume_id='saved',automatic_workflow=True)

    def test_explicit_continue_after_quota_pause_requires_fresh_admission(self):
        self.setup_flow()
        self.quota={'accountId':'synthetic'}
        self.shell.tick();self.shell.tick()
        self.assertEqual(self.preflight.call_count,1)
        self.quota=copy.deepcopy(QUOTA)
        self.c.answer_pause(self.c.snapshot()['pause_token'],'continue')
        self.shell.tick();self.shell.tick()
        self.assertEqual(self.preflight.call_count,2)
        self.assertEqual(self.dispatch.call_count,1)
        self.assertEqual(self.c.snapshot()['steps'][0]['attempts'],1)

    def test_manual_or_mixed_checks_still_wait_for_explicit_human_input(self):
        for kind in ('manual','rubric','source'):
            with self.subTest(kind=kind):
                self.setup_flow(extra_check=kind)
                self.shell.tick();self.finish();self.shell.tick();self.shell.tick()
                self.assertEqual(self.c.state,'CHECKING')
                self.assertIsNotNone(self.c.snapshot()['active_attempt'])
                self.assertEqual(self.dispatch.call_count,1)

    def test_failed_or_interrupted_native_turns_never_auto_evaluate(self):
        for status in ('failed','interrupted'):
            with self.subTest(status=status):
                self.setup_flow();self.shell.tick()
                self.host.observe_native(dict(method='turn/completed',params=dict(threadId='synthetic-thread',turn=dict(id='turn-1',status=status))))
                self.shell.tick();self.shell.tick()
                self.assertEqual(self.dispatch.call_count,1)
                self.assertNotEqual(self.c.state,'DONE')

    def test_user_mapping_resolves_only_accepted_ids_and_finishes_once(self):
        references=['1=1.1']
        self.setup_flow(finish_references=references)
        references[0]='1=2.1'
        self.shell.tick();self.finish();self.shell.tick()
        self.assertEqual(self.c.state,'CHECKING')
        self.shell.tick();self.shell.tick()
        state=self.c.snapshot()
        self.assertEqual(state['state'],'DONE')
        self.assertEqual(state['criterion_evidence'],{0:[state['steps'][0]['evidence'][0]['id']]})
        self.assertFalse(self.shell.automatic_workflow)
        self.assertEqual(self.dispatch.call_count,1)
        self.assertNotIn('finish_references',self.c.export_checkpoint())

    def test_restored_stale_evidence_cannot_satisfy_user_mapping(self):
        self.setup_flow()
        self.shell.tick();self.finish();self.shell.tick()
        stale=WorkflowController.restore_checkpoint(self.c.export_checkpoint(),QUOTA,time.monotonic(),CATALOG,POLICY)
        stale.answer_pause(stale.snapshot()['pause_token'],'continue')
        dispatch=Mock()
        host=WorkflowHost(stale,self.preflight,dispatch,Mock())
        shell=ChatShell(io.StringIO(),catalog=CATALOG,role_policy=POLICY,workflow=stale,
            workflow_action=host,automatic_workflow=True,finish_references=['1=1.1'])
        shell.tick();shell.tick()
        self.assertNotEqual(stale.state,'DONE')
        self.assertFalse(shell.automatic_workflow)
        self.assertIn('revalidation',shell.output.getvalue())
        dispatch.assert_not_called()
