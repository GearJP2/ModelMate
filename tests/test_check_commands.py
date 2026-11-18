"""User check specifications feed native observations; no local shell or real model."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from modelmate import (ProbeError, load_check_commands, run_workflow_file,
                       NativeWorkflowConnection, SessionStore, main, ChatShell)
from test_routing import PLAN
from test_native_workflow import SERVER

COMMAND_SERVER = SERVER.replace("'command':'python3 -m unittest','cwd':'/synthetic'",
    "'command':json.loads(req['params']['input'][0]['text'])['verification_commands'][0]['command'],"
    "'cwd':json.loads(req['params']['input'][0]['text'])['verification_commands'][0]['cwd']")


class CheckCommandTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.plan=copy.deepcopy(PLAN)
        self.plan_path=self.root/'plan.json';self.plan_path.write_text(json.dumps(self.plan))
        self.config=self.root/'checks.json'
        self.binding={'step':1,'check':1,'command':'python3 -m unittest','cwd':'.'}
        self.write([self.binding])
        self.trace=self.root/'trace'

    def write(self, items):
        self.config.write_text(json.dumps({'version':1,'checks':items}))

    def load(self):return load_check_commands(self.config,self.plan,str(self.root))

    def test_valid_user_binding_is_canonical_and_loading_never_executes(self):
        with patch('modelmate.subprocess.Popen',side_effect=AssertionError('execution forbidden')):
            loaded=self.load()
        self.assertEqual(loaded,[dict(self.binding,cwd=str(self.root))])
        self.assertEqual(load_check_commands(None,self.plan,str(self.root)),[])

    def test_invalid_identity_schema_and_ambiguous_bindings_are_rejected(self):
        for field,value in (('step',True),('check',True),('step',0),('step',2),('check',99),
                            ('command',''),('cwd','absent'),('extra','x')):
            with self.subTest(field=field,value=value):
                self.write([dict(self.binding,**{field:value})])
                with self.assertRaises(ProbeError):self.load()
        self.write([self.binding,self.binding])
        with self.assertRaises(ProbeError):self.load()
        self.plan['steps'][0]['checks']*=2
        self.write([self.binding,dict(self.binding,check=2)])
        with self.assertRaises(ProbeError):self.load()

    def test_invalid_json_version_size_and_manual_targets_rejected(self):
        for payload in ('broken','x'*65537,'{"version":2,"checks":[]}',
                        '{"version":1,"version":1,"checks":[]}',
                        '{"version":1,"checks":[],"extra":true}'):
            self.config.write_text(payload)
            with self.assertRaises(ProbeError):self.load()
        self.plan['steps'][0]['checks'][0]['kind']='manual'
        self.write([self.binding])
        with self.assertRaises(ProbeError):self.load()

    def run_file(self, config=True, mode='normal', drive=None):
        output=io.StringIO()
        original=NativeWorkflowConnection.__init__
        def init(connection,command,timeout=15):
            self.assertIn('คำสั่งตรวจ 1.1', output.getvalue())
            self.assertIn('START',output.getvalue())
            original(connection,[sys.executable,'-u','-c',COMMAND_SERVER,str(self.trace),mode],1)
        with tempfile.TemporaryFile('w+') as source:
            source.write('START\n');source.seek(0)
            with patch('modelmate.NativeWorkflowConnection.__init__',init), \
                 patch('modelmate.os.getcwd',return_value=str(self.root)), \
                 patch.dict(os.environ,{'XDG_STATE_HOME':str(self.root/'state')}), \
                 patch('modelmate.run_chat',side_effect=drive):
                code=run_workflow_file(self.plan_path,['standard=synthetic-standard'],
                    'ask_to_escalate',True,source,output,self.config if config else None)
        return code,output.getvalue()

    def test_missing_bindings_stop_before_backend_creation(self):
        with patch('modelmate.NativeWorkflowConnection.__init__',side_effect=AssertionError('no backend')):
            with tempfile.TemporaryFile('w+') as source:
                with self.assertRaisesRegex(ProbeError,'Every test/lint'):
                    run_workflow_file(self.plan_path,['standard=synthetic-standard'],
                                      'ask_to_escalate',True,source,io.StringIO())

    def test_native_binding_carries_user_command_and_observed_exit_to_checkpoint(self):
        def drive(_input,_output,**kwargs):
            host=kwargs['workflow_action'];c=kwargs['workflow'];backend=kwargs['backend']
            host({'action':'next','task_id':c.task_id});backend.drain()
            self.assertEqual(c.snapshot()['active_attempt']['checks'],{})
            host({'action':'check','task_id':c.task_id})
            evidence=c.snapshot()['steps'][0]['evidence'][0]
            self.assertEqual((evidence['origin'],evidence['result'],evidence['exit_code']),('tool','pass',0))
            c.finish_task({0:[evidence['id']]})
            return 0
        code,_=self.run_file(drive=drive)
        self.assertEqual(code,0)
        with SessionStore(self.root,self.root/'state',read_only=True) as store:
            self.assertEqual(store.list_sessions()[0]['workflow']['state'],'DONE')
        turns=[json.loads(line) for line in self.trace.read_text().splitlines() if json.loads(line).get('method')=='turn/start']
        requested=json.loads(turns[0]['params']['input'][0]['text'])['verification_commands']
        self.assertEqual(requested,[{'check':1,'command':self.binding['command'],'cwd':str(self.root)}])

    def test_wrapped_native_command_is_accepted_only_with_same_inner_command(self):
        direct="'command':json.loads(req['params']['input'][0]['text'])['verification_commands'][0]['command']"
        wrapped=COMMAND_SERVER.replace(direct,
            "'command':'/bin/bash -lc '+__import__('shlex').quote(json.loads(req['params']['input'][0]['text'])['verification_commands'][0]['command'])")
        def drive(_input,_output,**kwargs):
            host=kwargs['workflow_action'];c=kwargs['workflow'];backend=kwargs['backend']
            shell=ChatShell(io.StringIO(),workflow=c,workflow_action=host)
            shell.line('/next');shell.line('/check');backend.drain()
            self.assertEqual(c.snapshot()['steps'][0]['evidence'][0]['exit_code'],0)
            shell.line('/finish 1=1.1')
            self.assertEqual(c.state,'DONE')
            return 0
        with patch(__name__+'.COMMAND_SERVER',wrapped):self.run_file(drive=drive)

    def test_native_failures_stop_after_initial_plus_two_corrections(self):
        def drive(_input,_output,**kwargs):
            host=kwargs['workflow_action'];c=kwargs['workflow'];backend=kwargs['backend']
            for number in range(1,4):
                host({'action':'next','task_id':c.task_id});backend.drain()
                host({'action':'check','task_id':c.task_id})
                self.assertEqual(c.snapshot()['steps'][0]['attempts'],number)
            self.assertEqual(c.reason,'correction_limit')
            with self.assertRaises(ProbeError):host({'action':'next','task_id':c.task_id})
            return 0
        self.run_file(mode='fail',drive=drive)
        self.assertEqual(sum(json.loads(line).get('method')=='turn/start' for line in self.trace.read_text().splitlines()),3)

    def test_successful_unregistered_command_cannot_pass_configured_check(self):
        wrong = COMMAND_SERVER.replace(
            "'command':json.loads(req['params']['input'][0]['text'])['verification_commands'][0]['command']",
            "'command':'true'")
        def drive(_input,_output,**kwargs):
            host=kwargs['workflow_action'];c=kwargs['workflow'];backend=kwargs['backend']
            host({'action':'next','task_id':c.task_id});backend.drain()
            host({'action':'check','task_id':c.task_id})
            self.assertEqual(c.state,'UNVERIFIED')
            self.assertEqual(c.snapshot()['steps'][0]['evidence'],[])
            return 0
        with patch(__name__+'.COMMAND_SERVER',wrong):
            self.run_file(drive=drive)

    def test_cli_passes_check_file_and_rejects_it_outside_workflow(self):
        with patch('sys.argv',['modelmate.py','--workflow',str(self.plan_path),
                              '--check-commands',str(self.config)]), \
             patch('modelmate.run_workflow_file',return_value=0) as run:
            self.assertEqual(main(),0)
            self.assertEqual(run.call_args.args[-1],str(self.config))
        with patch('sys.argv',['modelmate.py','--check-commands',str(self.config)]), \
             patch('sys.stderr',new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as exc:main()
            self.assertEqual(exc.exception.code,2)

    def test_early_check_is_deferred_until_real_terminal_without_new_turn(self):
        def drive(_input,_output,**kwargs):
            host=kwargs['workflow_action'];c=kwargs['workflow'];backend=kwargs['backend']
            shell=ChatShell(io.StringIO(),workflow=c,workflow_action=host)
            shell.line('/next')
            shell.line('/check');shell.line('/check')
            self.assertEqual(c.state,'RUNNING')
            self.assertEqual(c.snapshot()['active_attempt']['checks'],{})
            backend.drain()
            self.assertEqual(c.snapshot()['steps'][0]['state'],'DONE')
            shell.line('/finish 1=1.1')
            self.assertEqual(c.state,'DONE')
            return 0
        self.run_file(drive=drive)
        self.assertEqual(sum(json.loads(line).get('method')=='turn/start' for line in self.trace.read_text().splitlines()),1)

    def test_cancel_clears_queued_check_and_late_completion_cannot_accept_it(self):
        def drive(_input,_output,**kwargs):
            host=kwargs['workflow_action'];c=kwargs['workflow'];backend=kwargs['backend']
            shell=ChatShell(io.StringIO(),workflow=c,workflow_action=host)
            shell.line('/next');shell.line('/check');shell.line('/cancel')
            self.assertIsNone(shell._workflow_check_attempt)
            backend.drain()
            self.assertEqual(c.snapshot()['steps'][0]['evidence'],[])
            self.assertEqual(c.snapshot()['active_attempt']['checks'],{})
            return 0
        self.run_file(drive=drive)

    def test_deferred_check_does_not_accept_unrelated_successful_command(self):
        wrong=COMMAND_SERVER.replace(
            "'command':json.loads(req['params']['input'][0]['text'])['verification_commands'][0]['command']",
            "'command':'true'")
        def drive(_input,_output,**kwargs):
            host=kwargs['workflow_action'];c=kwargs['workflow'];backend=kwargs['backend']
            shell=ChatShell(io.StringIO(),workflow=c,workflow_action=host)
            shell.line('/next');shell.line('/check');backend.drain()
            self.assertEqual(c.state,'UNVERIFIED')
            self.assertEqual(c.snapshot()['steps'][0]['evidence'],[])
            return 0
        with patch(__name__+'.COMMAND_SERVER',wrong):self.run_file(drive=drive)

    def test_duplicate_commands_in_different_steps_are_unambiguous(self):
        self.plan['steps'].append(copy.deepcopy(self.plan['steps'][0]))
        self.write([self.binding,dict(self.binding,step=2)])
        self.assertEqual(len(self.load()),2)

    def test_future_step_binding_is_registered_before_first_attempt(self):
        self.plan['steps'].append(copy.deepcopy(self.plan['steps'][0]))
        self.plan['steps'][1]['checks'][0]['kind']='lint'
        self.plan_path.write_text(json.dumps(self.plan))
        self.write([self.binding,dict(self.binding,step=2,command='python3 -m compileall -q .')])
        def drive(_input,_output,**kwargs):
            host=kwargs['workflow_action'];c=kwargs['workflow'];backend=kwargs['backend']
            for number in (0,1):
                host({'action':'next','task_id':c.task_id});backend.drain()
                host({'action':'check','task_id':c.task_id})
                self.assertEqual(c.snapshot()['steps'][number]['state'],'DONE')
            return 0
        self.run_file(drive=drive)
