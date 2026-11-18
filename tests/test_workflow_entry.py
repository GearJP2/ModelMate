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

from modelmate import ChatShell, ProbeError, WorkflowController, run_workflow_file, SessionStore, main, workflow_statistics, WorkflowHost, read_workflow_confirmation
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

    def test_confirmation_ignores_blank_paste_lines_without_approving_them(self):
        for payload in (b'\nSTART\n/next\n', b'\r\nSTART\r\n/next\n',
                        b'\x1b[200~START\x1b[201~\n/next\n'):
            with tempfile.TemporaryFile('w+b') as source:
                source.write(payload);source.seek(0)
                self.assertTrue(read_workflow_confirmation(source, lambda _: None))
                self.assertEqual(os.read(source.fileno(), 6), b'/next\n')

    def test_confirmation_on_a_real_pseudoterminal_preserves_next_command(self):
        import pty
        master, slave = pty.openpty()
        try:
            code = ("import sys,os;from modelmate import read_workflow_confirmation;"
                    "print(read_workflow_confirmation(sys.stdin,print));print(os.read(0,6))")
            process = subprocess.Popen([sys.executable, '-u', '-c', code], cwd=ROOT,
                                       stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                os.write(master, b'\nSTART\n/next\n')
                output, error = process.communicate(timeout=3)
                self.assertEqual(process.returncode, 0, error)
                self.assertIn(b'True\n', output)
                self.assertIn(b"b'/next\\n'", output)
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=3)
                process.stdout.close();process.stderr.close()
        finally:
            os.close(master);os.close(slave)

    def test_confirmation_eof_invalid_and_unclosed_paste_never_approve(self):
        for payload in (b'', b'\n\n', b'CANCEL\n', b'NO\nSTART\n',
                        b'\x1b[200~START\n', b'\x1bSTART\n', b'x'*257+b'START\n', b'START'+b' '*257+b'\n'):
            with tempfile.TemporaryFile('w+b') as source:
                source.write(payload);source.seek(0)
                self.assertFalse(read_workflow_confirmation(source, lambda _: None))

    def test_confirmation_diagnostics_do_not_echo_invalid_raw_input(self):
        messages=[]
        with tempfile.TemporaryFile('w+b') as source:
            source.write(b'PRIVATE_CONFIRM\x1b[201~\n');source.seek(0)
            self.assertFalse(read_workflow_confirmation(source,messages.append))
        text=' '.join(messages)
        self.assertIn('input diagnostics',text)
        self.assertIn('"paste_marker": true',text)
        self.assertNotIn('PRIVATE_CONFIRM',text)

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

    def test_short_evidence_refs_require_accepted_checks_and_explicit_coverage(self):
        c = WorkflowController(json.dumps(self.plan), CATALOG, POLICY)
        shell = ChatShell(io.StringIO(), workflow=c)
        aid = c.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)['dispatch']['attempt_id']
        c.finish_attempt(aid, 'completed')
        shell.line('/verify 1 pass')
        shell.line('/finish 1=1.1')
        self.assertNotEqual(c.state, 'DONE')
        c.evaluate_attempt(aid)
        for ref in ('EVIDENCE_ID', '0.1', '2.1', '1.0', '1.2', '1.1.1', 'a.b'):
            shell.line('/finish 1=' + ref)
            self.assertNotEqual(c.state, 'DONE')
        shell.line('/finish 1=1.1')
        self.assertEqual(c.state, 'DONE')
        self.assertIn('ref 1.1', shell.output.getvalue())

    def test_host_actions_render_once_and_completed_attempt_displays_checking(self):
        c = WorkflowController(json.dumps(self.plan), CATALOG, POLICY)
        host = WorkflowHost(c, lambda: dict(quota=QUOTA, checked_at=time.monotonic(), catalog=CATALOG,
                                           role_policy=POLICY),
                            lambda _: dict(thread_id='synthetic-thread', turn_id='synthetic-turn'), lambda _: None)
        output = io.StringIO()
        shell = ChatShell(output, workflow=c, workflow_action=host)
        shell.line('/next')
        self.assertEqual(output.getvalue().count('สถานะ: RUNNING'), 1)
        shell.line('/check')
        self.assertIsNone(shell._workflow_check_attempt)
        self.assertEqual(c.state, 'RUNNING')
        host.observe_native({'method':'turn/completed','params':{'threadId':'synthetic-thread',
            'turn':{'id':'synthetic-turn','status':'completed'}}})
        latest = output.getvalue().split('สถานะ: CHECKING')[-1]
        self.assertNotIn(' · RUNNING ·', latest)
        shell.line('/verify 1 pass')
        output.seek(0);output.truncate()
        shell.line('/check')
        self.assertEqual(output.getvalue().count('สถานะ: CHECKING'), 1)

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

    def test_statistics_count_attempts_without_inventing_usage_or_actual_models(self):
        c = WorkflowController(json.dumps(self.plan), CATALOG, POLICY)
        empty = workflow_statistics(c, 10, now=12)
        self.assertEqual(empty['attempts'], 0)
        self.assertEqual(empty['requestedSelections'], [])
        for _ in range(2):
            aid = c.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)['dispatch']['attempt_id']
            c.finish_attempt(aid, 'completed')
            c.record_check(aid, 0, origin='manual', result='fail', reference='user check', finding='failed')
            c.evaluate_attempt(aid)
        stats = workflow_statistics(c, 10, now=15.5)
        self.assertEqual(stats['attempts'], 2)
        self.assertEqual(stats['elapsedSeconds'], 5.5)
        self.assertEqual(len(stats['requestedSelections']), 1)
        self.assertTrue(stats['includesUserWait'])
        self.assertIsNone(stats['reportedModels'])
        self.assertIsNone(stats['tokenUsage'])
        for start, now in ((True, 12), (10, 9), (10, float('nan'))):
            with self.assertRaises(ProbeError):workflow_statistics(c, start, now=now)

    def test_full_cli_tty_accepts_typed_and_multiline_pasted_confirmation(self):
        import pty
        source = 'import sys;sys.path.insert(0,'+repr(str(ROOT))+');import modelmate\n'
        source += """
def stop_before_backend(self,*args,**kwargs):
 print('CONFIRMED_BACKEND',flush=True)
 raise modelmate.ProbeError('Offline test stopped before opening backend')
modelmate.NativeWorkflowConnection.__init__=stop_before_backend
sys.exit(modelmate.main())
"""
        for payload, confirmed in ((b'START\n', True),
                                   (b'\x1b[200~START\n\x1b[201~\n', True),
                                   (b'CANCEL\n', False)):
            with self.subTest(payload=payload):
                master, slave = pty.openpty()
                process = subprocess.Popen([sys.executable,'-u','-c',source,'--workflow',str(self.path),
                    '--role-model','standard=synthetic-standard','--execute-workflow'],
                    cwd=self.root,env=dict(os.environ,TERM='xterm-256color'),stdin=slave,stdout=slave,stderr=slave)
                buffer = b''
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(master,selectors.EVENT_READ)
                        def until(marker):
                            nonlocal buffer
                            deadline=time.monotonic()+4
                            while marker not in buffer and time.monotonic()<deadline:
                                if selector.select(max(0,deadline-time.monotonic())):
                                    try:chunk=os.read(master,65536)
                                    except OSError:break
                                    if not chunk:break
                                    buffer += chunk
                            self.assertIn(marker,buffer,repr(buffer))
                        until(b'START')
                        os.write(master,payload)
                        until(b'CONFIRMED_BACKEND' if confirmed else 'ยกเลิกแล้ว'.encode())
                    process.wait(timeout=3)
                    self.assertEqual(process.returncode,1 if confirmed else 0)
                    if not confirmed:self.assertNotIn(b'CONFIRMED_BACKEND',buffer)
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=3)
                    os.close(master);os.close(slave)

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
        send('/finish 1=1.1');until('สถานะ: DONE'.encode())
        send('/exit');p.wait(timeout=3)
        self.assertEqual(p.returncode,0,p.stderr.read())
        buffer += p.stdout.read()
        summary = next(line.split(': ', 1)[1] for line in buffer.decode().splitlines()
                       if line.startswith('สถิติ workflow: '))
        stats = json.loads(summary)
        self.assertEqual(stats['state'], 'DONE')
        self.assertEqual(stats['attempts'], 1)
        self.assertIsNone(stats['reportedModels'])
        with SessionStore(self.root,self.root/'state',read_only=True) as store:
            records=store.list_sessions()
            self.assertEqual(len(records),1)
            self.assertEqual(records[0]['workflow']['state'],'DONE')
        self.assertEqual(sum(json.loads(line).get('method')=='turn/start' for line in trace.read_text().splitlines()),1)
