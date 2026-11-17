"""Explicit workflow entry is offline until flag + confirmation; live tests use a fake server."""
import copy
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
from unittest.mock import patch

from modelmate import ChatShell, ProbeError, WorkflowController, run_workflow_file, SessionStore, main
from test_routing import PLAN, CATALOG, POLICY, QUOTA
from test_native_workflow import SERVER

ROOT = Path(__file__).resolve().parents[1]


class WorkflowEntryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.plan = copy.deepcopy(PLAN)
        self.plan['steps'][0]['checks'] = [{'kind':'manual','criterion':'User checks the answer'}]
        self.path = self.root / 'plan.json';self.path.write_text(json.dumps(self.plan))

    def run_file(self, execute=False, text='NO\n', bindings=None):
        with tempfile.TemporaryFile('w+') as source:
            source.write(text);source.seek(0)
            return run_workflow_file(self.path, bindings or ['standard=synthetic-standard'],
                                     'ask_to_escalate', execute, source, io.StringIO())

    def test_preview_and_declined_confirmation_never_start_process(self):
        with patch('modelmate.subprocess.Popen',side_effect=AssertionError('backend forbidden')):
            self.assertEqual(self.run_file(),0)
            self.assertEqual(self.run_file(True),0)
            self.assertEqual(self.run_file(True,text=''),0)

    def test_malformed_oversized_and_missing_bindings_never_connect(self):
        with patch('modelmate.NativeWorkflowConnection.__init__',side_effect=AssertionError('backend forbidden')):
            for bindings in (['standard=one','standard=two'], ['other=one'], ['standard='], ['bad'], ['economy=one']):
                with self.assertRaises((ProbeError,ValueError)):
                    self.run_file(bindings=bindings)
            for raw in ('invalid', 'x' * 65537):
                self.path.write_text(raw)
                with self.assertRaises(ProbeError):self.run_file()

    def test_unsupported_checks_and_clarification_cannot_execute(self):
        with patch('modelmate.NativeWorkflowConnection.__init__',side_effect=AssertionError('backend forbidden')):
            for kind in ('test','lint','source'):
                self.plan['steps'][0]['checks'][0]['kind']=kind
                self.path.write_text(json.dumps(self.plan))
                with self.assertRaises(ProbeError):self.run_file(True,text='START\n')
            self.plan['steps'][0]['checks'][0]['kind']='manual'
            self.plan['clarifications']=['Need an answer']
            self.path.write_text(json.dumps(self.plan))
            with self.assertRaises(ProbeError):self.run_file(True,text='START\n')

    def test_ui_manual_evidence_and_explicit_criterion_mapping(self):
        c=WorkflowController(json.dumps(self.plan),CATALOG,POLICY)
        shell=ChatShell(io.StringIO(),workflow=c)
        aid=c.request_attempt(QUOTA,time.monotonic(),CATALOG,POLICY)['dispatch']['attempt_id']
        shell.line('/verify 1 pass')
        self.assertEqual(c.snapshot()['active_attempt']['checks'],{})
        c.finish_attempt(aid,'completed')
        for command in ('/verify bad pass','/verify 0 pass','/verify 1 yes','/verify 99 pass'):
            shell.line(command)
            self.assertEqual(c.snapshot()['active_attempt']['checks'],{})
        shell.line('/verify 1 pass')
        evidence=c.snapshot()['active_attempt']['checks'][0]
        self.assertEqual(evidence['origin'],'manual')
        c.evaluate_attempt(aid)
        for command in ('/finish','/finish bad','/finish 1=missing','/finish 1='+evidence['id']+' 1='+evidence['id']):
            shell.line(command);self.assertNotEqual(c.state,'DONE')
        shell.line('/finish 1='+evidence['id'])
        self.assertEqual(c.state,'DONE')

    def test_ui_cannot_supply_manual_results_for_tool_checks(self):
        c=WorkflowController(json.dumps(PLAN),CATALOG,POLICY)
        shell=ChatShell(io.StringIO(),workflow=c)
        aid=c.request_attempt(QUOTA,time.monotonic(),CATALOG,POLICY)['dispatch']['attempt_id']
        c.finish_attempt(aid,'completed');shell.line('/verify 1 pass')
        self.assertEqual(c.snapshot()['active_attempt']['checks'],{})

    def test_workflow_option_conflicts_fail_before_backend(self):
        for args in (['--execute-workflow'],['--workflow',str(self.path),'prompt'],
                     ['--workflow',str(self.path),'--resume','a'],['--workflow',str(self.path),'--live']):
            with patch('sys.argv',['modelmate.py']+args),patch('sys.stderr',new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as exc:main()
                self.assertEqual(exc.exception.code,2)

    def test_real_cli_loop_preserves_confirmation_input_and_autosaves_done(self):
        trace=self.root/'trace'
        source='import sys;sys.path.insert(0,'+repr(str(ROOT))+');import modelmate\n'
        source+='import os\nSERVER='+repr(SERVER)+'\nTRACE='+repr(str(trace))+'\n'
        source+='''
original=modelmate.NativeWorkflowConnection.__init__
def init(self,command,timeout=15):
 original(self,[sys.executable,'-u','-c',SERVER,TRACE,'text'],timeout)
modelmate.NativeWorkflowConnection.__init__=init
sys.exit(modelmate.main())
'''
        env=dict(os.environ,XDG_STATE_HOME=str(self.root/'state'))
        p=subprocess.Popen([sys.executable,'-u','-c',source,'--workflow',str(self.path),
                            '--role-model','standard=synthetic-standard','--execute-workflow'],
                           cwd=self.root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        def cleanup():
            if p.poll() is None:p.kill()
            p.wait(timeout=3)
            for stream in (p.stdin,p.stdout,p.stderr):stream.close()
        self.addCleanup(cleanup)
        buffer=b''
        def until(marker):
            nonlocal buffer
            deadline=time.monotonic()+5
            with selectors.DefaultSelector() as selector:
                selector.register(p.stdout,selectors.EVENT_READ)
                while marker not in buffer and time.monotonic()<deadline:
                    if selector.select(max(0,deadline-time.monotonic())):
                        chunk=os.read(p.stdout.fileno(),65536)
                        if not chunk:break
                        buffer+=chunk
            self.assertIn(marker,buffer,buffer.decode(errors='replace'))
        def send(text):p.stdin.write((text+'\n').encode());p.stdin.flush()
        until(b'START');send('START\n/next')
        until('สถานะ: CHECKING'.encode());send('/verify 1 pass')
        until(b'evidence ')
        evidence=re.search(rb'evidence ([0-9a-f]{32})',buffer).group(1).decode()
        send('/check');until(b'task_criteria_pending')
        send('/finish 1='+evidence);until('สถานะ: DONE'.encode())
        send('/exit');p.wait(timeout=3)
        self.assertEqual(p.returncode,0,p.stderr.read())
        with SessionStore(self.root,self.root/'state',read_only=True) as store:
            records=store.list_sessions()
            self.assertEqual(len(records),1)
            self.assertEqual(records[0]['workflow']['state'],'DONE')
        self.assertEqual(sum(json.loads(line).get('method')=='turn/start' for line in trace.read_text().splitlines()),1)
