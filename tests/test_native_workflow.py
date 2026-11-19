"""Native protocol integration against a synthetic subprocess, never a live model."""
import io
import json
import os
import selectors
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest

from modelmate import NativeWorkflowConnection, WorkflowController, ProbeError, run_chat, ChatShell
from test_routing import CATALOG, PLAN, POLICY

SERVER = r'''
import json,sys,time
trace,mode=sys.argv[1:]
quota_reset=int(time.time())+3600
turn=0
quota_reads=0
catalog=[{'model':'synthetic-'+r,'defaultReasoningEffort':'low',
 'supportedReasoningEfforts':[{'reasoningEffort':'low'}]} for r in ('economy','standard','strong')]
def emit(value):print(json.dumps(value),flush=True)
for line in sys.stdin:
 req=json.loads(line)
 with open(trace,'a') as f:f.write(json.dumps(req)+'\n')
 method=req.get('method')
 if method is None or 'id' not in req:continue
 if method=='initialize':result={}
 elif method=='account/read':result={'account':{'type':'apiKey' if mode=='api' else 'chatgpt'}}
 elif method=='model/list':
  result={'data':None if mode=='catalog-after-connect' and quota_reads>=3 else catalog}
 elif method=='account/rateLimits/read':
  quota_reads+=1
  result={'accountId':'different' if mode=='account-after-connect' and quota_reads>=3 else 'synthetic',
   'ordinaryUsageAllowed':mode!='quota' and not (mode=='quota-after-connect' and quota_reads>=3),
   'rateLimits':{'primary':{'usedPercent':10}}}
  if mode=='unknown-after-connect' and quota_reads>=3:result.pop('ordinaryUsageAllowed')
  if mode=='metrics':result['rateLimits']['primary'].update(
   usedPercent=10+turn,windowDurationMins=300,resetsAt=quota_reset)
 elif method=='thread/start':result={'thread':{'id':'thread','cwd':req['params']['cwd'],
  'ephemeral':req['params'].get('ephemeral',True),'modelProvider':'openai'},'approvalPolicy':'on-request','approvalsReviewer':'user',
  'sandbox':{'type':'workspaceWrite' if mode=='permissions' else 'readOnly'}}
 elif method=='turn/start':
  turn+=1
  if mode=='disconnect':sys.exit(0)
  item={'id':'check','type':'commandExecution','command':'python3 -m unittest','cwd':'/synthetic',
   'status':'completed','exitCode':1 if mode=='fail' else 0}
  for event in ('item/started','item/completed'):
   emit({'method':event,'params':{'threadId':'thread','turnId':str(turn),'item':item}})
  if mode in ('text','text-only'):
   emit({'method':'item/agentMessage/delta','params':{'threadId':'thread','turnId':str(turn),
    'itemId':'answer','delta':'SYNTHETIC_ANSWER'}})
   for thread_id,turn_id in (('foreign',str(turn)),('thread','foreign'),('thread',str(turn)),('thread',str(turn))):
    emit({'method':'item/completed','params':{'threadId':thread_id,'turnId':turn_id,
     'item':{'id':'answer','type':'agentMessage','text':'SYNTHETIC_ANSWER all tests passed DONE' if (thread_id,turn_id)==('thread',str(turn)) else 'FOREIGN_ANSWER'}}})
  if mode=='metrics':
   total={'inputTokens':9,'cachedInputTokens':3,'outputTokens':2,'reasoningOutputTokens':1,'totalTokens':11}
   for thread_id, turn_id, value in [('thread',str(turn),total),('other',str(turn),dict(total,totalTokens=99)),
                                     ('thread','old',dict(total,totalTokens=99))]:
    emit({'method':'thread/tokenUsage/updated','params':{'threadId':thread_id,'turnId':turn_id,
     'tokenUsage':{'last':value,'total':value}}})
  if mode=='approval':emit({'id':'approval','method':'item/commandExecution/requestApproval',
   'params':{'threadId':'thread','turnId':str(turn),'itemId':'tool','command':'write','cwd':'/synthetic'}})
  elif mode!='text-only':emit({'method':'turn/completed','params':{'threadId':'thread','turn':{'id':str(turn),'status':'completed'}}})
  result={'turn':{} if mode=='missing-id' else {'id':str(turn)}}
 elif method=='turn/interrupt':result={}
 else:raise RuntimeError(method)
 emit({'id':req['id'],'result':result})
'''


class NativeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.trace = Path(temp.name) / 'trace'
        self.controller = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)

    def backend(self, mode='normal'):
        c = NativeWorkflowConnection([sys.executable, '-u', '-c', SERVER, str(self.trace), mode], 1)
        self.addCleanup(c.close)
        return c

    def records(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def start(self, c):
        host = c.connect(self.controller, '/synthetic', POLICY)
        host.configure_check(0, command='python3 -m unittest', cwd='/synthetic')
        host({'action':'next', 'task_id':self.controller.task_id})
        return host

    def test_events_before_start_reply_are_queued_until_exact_binding_exists(self):
        c = self.backend(); host = self.start(c)
        self.assertEqual(self.controller.state, 'RUNNING')
        self.assertGreater(len(c._events), 0)
        c.drain()
        self.assertEqual(self.controller.state, 'CHECKING')
        host({'action':'check','task_id':self.controller.task_id})
        self.assertEqual(self.controller.snapshot()['steps'][0]['evidence'][0]['result'], 'pass')
        self.assertNotEqual(self.controller.state, 'DONE')
        start = next(r['params'] for r in self.records() if r.get('method')=='thread/start')
        self.assertEqual(start['sandbox'], 'read-only')
        self.assertEqual(start['approvalPolicy'], 'on-request')
        self.assertTrue(start['ephemeral'])
        self.assertEqual(start['config']['web_search'], 'disabled')

    def test_summary_uses_only_matching_native_token_events(self):
        backend = self.backend('metrics')
        backend.measure_quota = True
        self.start(backend)
        backend.drain()
        summary = backend.workflow_measurements()
        self.assertEqual(summary['timedTurns'], 1)
        self.assertGreaterEqual(summary['turnElapsedSeconds'], 0)
        self.assertEqual(summary['tokenUsage']['total']['totalTokens'], 11)
        self.assertEqual(summary['tokenUsage']['last']['cachedInputTokens'], 3)
        self.assertEqual(summary['tokenUsage']['last']['reasoningOutputTokens'], 1)
        self.assertEqual(summary['quotaWindowChanges'][0]['deltaPercentagePoints'], 1)
        self.assertEqual(sum(row.get('method') == 'turn/start' for row in self.records()), 1)

    def test_auth_quota_and_permission_mismatch_start_no_turn(self):
        for mode in ('api','quota','permissions'):
            with self.subTest(mode=mode):
                self.trace.unlink(missing_ok=True)
                c = self.backend(mode)
                with self.assertRaises(ProbeError):c.connect(self.controller, '/synthetic', POLICY)
                self.assertFalse(any(r.get('method')=='turn/start' for r in self.records()))
                c.close()

    def test_mid_workflow_preflight_preserves_pause_reason_without_consuming_attempt(self):
        for mode, reason in (
            ('quota-after-connect', 'quota_exhausted'),
            ('unknown-after-connect', 'quota_unknown'),
            ('account-after-connect', 'account_changed'),
            ('catalog-after-connect', 'catalog_unavailable'),
        ):
            with self.subTest(mode=mode):
                self.trace.unlink(missing_ok=True)
                controller = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
                backend = self.backend(mode)
                try:
                    host = backend.connect(controller, '/synthetic', POLICY)
                    with self.assertRaisesRegex(ProbeError, reason):
                        host({'action': 'next', 'task_id': controller.task_id})
                    state = controller.snapshot()
                    self.assertEqual((state['state'], state['reason']), ('PAUSED', reason))
                    self.assertEqual(state['steps'][0]['attempts'], 0)
                    self.assertFalse(any(row.get('method') == 'turn/start' for row in self.records()))
                finally:
                    backend.close()

    def test_declines_tool_request_and_pauses_without_accept(self):
        c = self.backend('approval'); self.start(c)
        with self.assertRaisesRegex(ProbeError, 'nothing approved'):c.drain()
        self.assertEqual(self.controller.state, 'PAUSED')
        # Interrupt RPC also synchronizes the fake server's trace after the decline.
        decisions = [r['result']['decision'] for r in self.records() if 'result' in r]
        self.assertEqual(decisions, ['decline'])
        self.assertEqual(sum(r.get('method')=='turn/interrupt' for r in self.records()), 1)

    def test_unknown_start_keeps_slot_and_never_replays(self):
        for mode in ('missing-id','disconnect'):
            with self.subTest(mode=mode):
                self.trace.unlink(missing_ok=True)
                self.controller = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
                c = self.backend(mode)
                with self.assertRaises(ProbeError):self.start(c)
                self.assertEqual(self.controller.state, 'PAUSED')
                self.assertEqual(self.controller.snapshot()['steps'][0]['attempts'], 1)
                with self.assertRaises(ProbeError):
                    c.host({'action':'next','task_id':self.controller.task_id})
                self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()), 1)
                c.close()

    def test_direct_dispatch_requires_reservation_and_cannot_repeat_attempt(self):
        c = self.backend(); host = c.connect(self.controller, '/synthetic', POLICY)
        with self.assertRaises(ProbeError):c.dispatch({'attempt_id':'invented'})
        descriptor = self.controller.request_attempt(host.preflight()['quota'], time.monotonic(), CATALOG, POLICY)['dispatch']
        c.dispatch(descriptor)
        with self.assertRaisesRegex(ProbeError, 'replay'):c.dispatch(descriptor)
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()), 1)

    def test_selector_connects_only_matching_controller_and_host(self):
        c = self.backend(); host = c.connect(self.controller, '/synthetic', POLICY)
        r, w = os.pipe()
        os.write(w, b'/exit\n'); os.close(w)
        with os.fdopen(r, 'rb', buffering=0) as source:
            self.assertEqual(run_chat(source, io.StringIO(), backend=c,
                                      workflow=self.controller, workflow_action=host), 0)
        with self.assertRaises(ProbeError):run_chat(io.StringIO(),io.StringIO(),backend=c)

    def test_corrections_reuse_thread_and_use_requested_model_effort(self):
        c = self.backend('fail'); host = self.start(c)
        for number in range(2):
            c.drain()
            host({'action':'check','task_id':self.controller.task_id})
            if number == 0:
                host({'action':'next','task_id':self.controller.task_id})
        turns = [r['params'] for r in self.records() if r.get('method')=='turn/start']
        self.assertEqual(len(turns), 2)
        self.assertEqual({t['threadId'] for t in turns}, {'thread'})
        self.assertEqual({t['model'] for t in turns}, {'synthetic-standard'})
        self.assertEqual({t['effort'] for t in turns}, {'low'})
        self.assertEqual(self.controller.snapshot()['steps'][0]['attempts'], 2)

    def test_active_checkpoint_requires_recovery_instead_of_new_thread(self):
        self.controller.request_attempt({'accountId':'synthetic','ordinaryUsageAllowed':True,
            'rateLimits':{'primary':{'usedPercent':10}}}, time.monotonic(), CATALOG, POLICY)
        c = self.backend()
        with self.assertRaisesRegex(ProbeError, 'recovery'):
            c.connect(self.controller, '/synthetic', POLICY)
        self.assertFalse(self.trace.exists())

    def test_terminal_loop_drains_native_stream_and_evaluates_checks(self):
        root = Path(__file__).resolve().parents[1]
        code = "import sys;sys.path.insert(0," + repr(str(root / 'tests')) + ");" + """
import json
from modelmate import NativeWorkflowConnection,WorkflowController,run_chat
from test_routing import PLAN,CATALOG,POLICY
c=WorkflowController(json.dumps(PLAN),CATALOG,POLICY)
backend=NativeWorkflowConnection([sys.executable,'-u','-c',SERVER,TRACE,'text'],1)
try:
 host=backend.connect(c,'/synthetic',POLICY)
 host.configure_check(0,command='python3 -m unittest',cwd='/synthetic')
 result=run_chat(sys.stdin,sys.stdout,workflow=c,workflow_action=host,backend=backend)
 sys.exit(result)
finally:backend.close()
"""
        code = 'SERVER=' + repr(SERVER) + ';TRACE=' + repr(str(self.trace)) + ';' + code
        process = subprocess.Popen([sys.executable,'-u','-c',code],cwd=root,
                                   stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        def cleanup():
            if process.poll() is None:process.kill()
            process.wait(timeout=3)
            for stream in (process.stdin,process.stdout,process.stderr):stream.close()
        self.addCleanup(cleanup)
        buffer = b''
        def until(marker):
            nonlocal buffer
            deadline = time.monotonic() + 4
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout,selectors.EVENT_READ)
                while marker not in buffer and time.monotonic() < deadline:
                    if selector.select(max(0,deadline-time.monotonic())):
                        chunk = os.read(process.stdout.fileno(),65536)
                        if not chunk:break
                        buffer += chunk
            self.assertIn(marker,buffer,buffer.decode(errors='replace'))
        process.stdin.write(b'/next\n');process.stdin.flush()
        until('สถานะ: CHECKING'.encode())
        self.assertEqual(buffer.count(b'SYNTHETIC_ANSWER'), 1)
        self.assertNotIn(b'FOREIGN_ANSWER', buffer)
        process.stdin.write(b'/check\n');process.stdin.flush()
        until(b'[pass] test')
        process.stdin.write(b'/exit\n');process.stdin.flush()
        process.wait(timeout=3)
        self.assertEqual(process.returncode,0,process.stderr.read())
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_completed_answer_is_visible_once_and_foreign_messages_are_ignored(self):
        c = self.backend('text')
        host = c.connect(self.controller, '/synthetic', POLICY)
        output = io.StringIO()
        ChatShell(output, workflow=self.controller, workflow_action=host)
        host({'action':'next','task_id':self.controller.task_id})
        c.drain()
        self.assertEqual(output.getvalue().count('SYNTHETIC_ANSWER'), 1)
        self.assertNotIn('FOREIGN_ANSWER', output.getvalue())
        self.assertEqual(self.controller.state, 'CHECKING')
        self.assertEqual(self.controller.snapshot()['active_attempt']['checks'], {})
        self.assertNotIn('SYNTHETIC_ANSWER', json.dumps(self.controller.export_checkpoint()))

    def test_model_text_cannot_finish_turn_or_pass_checks(self):
        c = self.backend('text-only')
        host = c.connect(self.controller, '/synthetic', POLICY)
        output = io.StringIO()
        ChatShell(output, workflow=self.controller, workflow_action=host)
        host({'action':'next','task_id':self.controller.task_id})
        c.drain()
        self.assertIn('SYNTHETIC_ANSWER all tests passed DONE', output.getvalue())
        self.assertEqual(self.controller.state, 'RUNNING')
        self.assertEqual(self.controller.snapshot()['active_attempt']['checks'], {})

    def test_answer_controls_are_sanitized_and_post_terminal_text_is_ignored(self):
        c = self.backend('text-only')
        host = c.connect(self.controller, '/synthetic', POLICY)
        output = io.StringIO()
        ChatShell(output, workflow=self.controller, workflow_action=host)
        host({'action':'next','task_id':self.controller.task_id})
        c.drain()
        def answer(item_id, text):
            c.handle_event({'method':'item/completed','params':{'threadId':'thread','turnId':'1',
                'item':{'id':item_id,'type':'agentMessage','text':text}}})
            c.drain()
        answer('controls', 'safe\x1b[31m\u202ehidden')
        self.assertNotIn('\x1b', output.getvalue())
        self.assertNotIn('\u202e', output.getvalue())
        c.handle_event({'method':'turn/completed','params':{
            'threadId':'thread','turn':{'id':'1','status':'completed'}}})
        c.drain()
        answer('late', 'LATE_ANSWER')
        self.assertNotIn('LATE_ANSWER', output.getvalue())

    def test_reused_message_id_displays_again_in_next_turn(self):
        c = self.backend('text-only')
        host = c.connect(self.controller, '/synthetic', POLICY)
        host.configure_check(0, command='python3 -m unittest', cwd='/synthetic')
        output = io.StringIO()
        ChatShell(output, workflow=self.controller, workflow_action=host)
        for number in (1, 2):
            host({'action':'next','task_id':self.controller.task_id})
            c.drain()
            c.handle_event({'method':'turn/completed','params':{
                'threadId':'thread','turn':{'id':str(number),'status':'completed'}}})
            c.drain()
            self.assertEqual(output.getvalue().count('SYNTHETIC_ANSWER'), number)
            if number == 1:
                active = self.controller.snapshot()['active_attempt']
                self.controller.record_check(active['id'], 0, origin='tool', exit_code=1,
                                             reference='synthetic failure', finding='observed failed result')
                host({'action':'check','task_id':self.controller.task_id})

    def test_queue_is_bounded(self):
        c = self.backend()
        with self.assertRaisesRegex(ProbeError, 'queue'):
            c.handle_event({'method':'text','params':{'text':'x' * (4 * 1024 * 1024)}})
