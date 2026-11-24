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

from modelmate import ChatShell, LiveChatConnection, ProbeError, main

CATALOG = [{'model': 'synthetic-model', 'defaultReasoningEffort': 'low',
            'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}]
QUOTA = {'accountId': 'synthetic', 'ordinaryUsageAllowed': True,
         'rateLimits': {'primary': {'usedPercent': 5}}}

FAKE = r'''
import sys,json
turn=0
trace=sys.argv[1]
for line in sys.stdin:
 req=json.loads(line)
 with open(trace,'a') as f: f.write(json.dumps(req)+'\n')
 method=req.get('method')
 if 'method' not in req:
  print(json.dumps({'method':'item/completed','params':{'threadId':'thread','turnId':str(turn),
    'item':{'id':'answer','type':'agentMessage','text':'tool '+req['result']['decision']}}}),flush=True)
  print(json.dumps({'method':'turn/completed','params':{'threadId':'thread',
    'turn':{'id':str(turn),'status':'completed'}}}),flush=True)
  continue
 if 'id' not in req: continue
 if method=='initialize': result={}
 elif method=='account/read': result={'account':{'type':'chatgpt','planType':'plus'}}
 elif method=='model/list': result={'data':[{'model':'synthetic-model','defaultReasoningEffort':'low',
       'supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]}
 elif method=='account/rateLimits/read': result={'accountId':'synthetic','ordinaryUsageAllowed':True,
       'rateLimits':{'primary':{'usedPercent':5}}}
 elif method=='thread/start': result={'thread':{'id':'thread'}}
 elif method=='turn/start':
  turn+=1;result={'turn':{'id':str(turn)}}
 elif method in ('turn/steer','turn/interrupt'): result={}
 else: raise RuntimeError(method)
 print(json.dumps({'id':req['id'],'result':result}),flush=True)
 if method=='turn/start':
  print(json.dumps({'method':'turn/started','params':{'threadId':'thread','turn':{'id':str(turn)}}}),flush=True)
  print(json.dumps({'id':'tool-request','method':'item/commandExecution/requestApproval','params':{
       'threadId':'thread','turnId':str(turn),'itemId':'tool','command':'printf synthetic','cwd':'/synthetic'}}),flush=True)
 if method=='turn/interrupt':
  print(json.dumps({'method':'turn/completed','params':{'threadId':'thread',
       'turn':{'id':str(turn),'status':'interrupted'}}}),flush=True)
'''


class LiveBackendTests(unittest.TestCase):
    def backend(self):
        c = LiveChatConnection([sys.executable, '-c', 'import time;time.sleep(30)'], 1)
        self.addCleanup(c.close)
        c.thread_id = 'thread'
        c.catalog = CATALOG
        c.selection = {'model': 'synthetic-model', 'effort': 'low'}
        c.shell = ChatShell(io.StringIO(), c.action, CATALOG)
        c.shell.live = True
        c.send = Mock()
        return c

    def test_connect_uses_native_policy_without_expanding_permissions(self):
        c = self.backend()
        c.shell = None
        c.request = Mock(return_value={'thread': {'id': 'thread'}})
        with patch('modelmate.inspect', return_value={'models': CATALOG}):
            c.connect('synthetic-model', 'low', '/tmp')
        params = c.request.call_args.args[1]
        self.assertEqual(params['sandbox'], 'read-only')
        self.assertEqual(params['approvalPolicy'], 'on-request')
        self.assertEqual(params['approvalsReviewer'], 'user')
        self.assertEqual(params['config']['web_search'], 'disabled')
        self.assertTrue(params['ephemeral'])

    def test_quota_failure_never_sends_inference(self):
        c = self.backend()
        with patch('modelmate.read_models', return_value=CATALOG), \
             patch('modelmate.refresh_quota', return_value={
                 'state': 'pause', 'reason': 'quota_unknown', 'checked_at': 100, 'account_id': None}):
            c.shell.line('task')
        c.send.assert_not_called()
        self.assertFalse(c.shell.active)
        self.assertIn('quota_unknown', c.shell.output.getvalue())

    def test_approval_requires_exact_token_and_is_one_time(self):
        c = self.backend()
        c.turn_id = 'turn'
        c.shell.active = True
        c.handle_event({'id': 'request', 'method': 'item/commandExecution/requestApproval', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'itemId': 'item',
            'command': 'printf "\u202e"', 'cwd': '/tmp'}})
        c.send.assert_not_called()
        token = c.shell.pending['token']
        self.assertIn('\\u202e', c.shell.output.getvalue())
        c.shell.line('/approve wrong')
        c.send.assert_not_called()
        c.shell.line('/approve ' + token)
        self.assertEqual(c.send.call_args.args[0], {'id': 'request', 'result': {'decision': 'accept'}})
        with self.assertRaises(ProbeError):
            c._answer_tool(token, 'approve')

    def test_patch_without_preview_is_declined(self):
        c = self.backend();c.turn_id = 'turn'
        c.handle_event({'id': 12, 'method': 'item/fileChange/requestApproval', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'itemId': 'item'}})
        self.assertEqual(c.send.call_args.args[0]['result']['decision'], 'decline')
        self.assertIsNone(c.shell.pending)

    def test_unknown_or_stale_request_never_accepts(self):
        c = self.backend();c.turn_id = 'current'
        for method, turn in [('unknown', 'current'), ('item/commandExecution/requestApproval', 'old')]:
            with self.assertRaises(ProbeError):
                c.handle_event({'id': 2, 'method': method, 'params': {
                    'threadId': 'thread', 'turnId': turn, 'itemId': 'tool'}})
        c.send.assert_not_called()

    def test_interrupt_ack_does_not_claim_stopped(self):
        c = self.backend();c.turn_id = 'turn';c.shell.active = True
        c.shell.cancel()
        req = c.send.call_args.args[0]
        c.buffer = (json.dumps({'id': req['id'], 'result': {}})+'\n').encode()
        c.drain()
        self.assertTrue(c.shell.active)
        self.assertTrue(c.shell.stopping)
        c.handle_event({'method': 'turn/completed', 'params': {
            'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'interrupted'}}})
        self.assertFalse(c.shell.active)

    def test_completion_before_start_response_does_not_revive_turn(self):
        c = self.backend();c.start_pending = True
        c._async('turn/start', {'threadId': 'thread'})
        req = c.send.call_args.args[0]
        events = [{'method': 'turn/started', 'params': {'threadId': 'thread', 'turn': {'id': 'turn'}}},
                  {'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}},
                  {'id': req['id'], 'result': {'turn': {'id': 'turn'}}}]
        c.buffer = ''.join(json.dumps(e)+'\n' for e in events).encode()
        c.drain()
        self.assertIsNone(c.turn_id)
        self.assertFalse(c.start_pending)

    def test_streamed_text_does_not_duplicate_final_message(self):
        c = self.backend();c.turn_id = 'turn'
        c.handle_event({'method': 'item/agentMessage/delta', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'itemId': 'a', 'delta': 'ไทย\x1b'}})
        c.handle_event({'method': 'item/completed', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'item': {'type': 'agentMessage','id': 'a','text': 'ไทย'}}})
        self.assertEqual(c.shell.output.getvalue(), 'ไทย')

    def test_patch_preview_is_required_and_shown_before_accept(self):
        c = self.backend();c.turn_id = 'turn';c.shell.active = True
        c.handle_event({'method': 'item/started', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'item': {
                'type': 'fileChange', 'id': 'patch',
                'changes': [{'path': '/tmp/synthetic', 'diff': '+synthetic'}]}}})
        c.handle_event({'id': 'patch-request', 'method': 'item/fileChange/requestApproval', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'itemId': 'patch'}})
        c.send.assert_not_called()
        self.assertIn('+synthetic', c.shell.output.getvalue())
        c.shell.line('/approve '+c.shell.pending['token'])
        self.assertEqual(c.send.call_args.args[0]['result']['decision'], 'accept')

    def test_cancel_during_start_waits_for_id_then_interrupts(self):
        c = self.backend();c.start_pending = True;c.shell.active = True
        c.shell.cancel()
        self.assertTrue(c.cancel_after_start)
        c.send.assert_not_called()
        c.handle_event({'method': 'turn/started', 'params': {
            'threadId': 'thread', 'turn': {'id': 'new'}}})
        self.assertEqual(c.send.call_args.args[0]['method'], 'turn/interrupt')
        self.assertTrue(c.shell.stopping)

    def test_native_patch_update_expires_token_and_requires_a_new_preview(self):
        c = self.backend();c.turn_id = 'turn';c.shell.active = True
        params = {'threadId': 'thread', 'turnId': 'turn', 'itemId': 'patch',
                  'changes': [{'path': '/tmp/synthetic', 'kind': {'type': 'add'}, 'diff': '+original'}]}
        c.handle_event({'method': 'item/fileChange/patchUpdated', 'params': params})
        request = {'id': 'first', 'method': 'item/fileChange/requestApproval', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'itemId': 'patch', 'startedAtMs': 1}}
        c.handle_event(request)
        old = c.shell.pending['token']
        params['changes'][0]['diff'] = '+changed'
        c.handle_event({'method': 'item/fileChange/patchUpdated', 'params': params})
        self.assertIsNone(c.shell.pending)
        c.shell.line('/approve ' + old)
        c.send.assert_called_once_with({'id': 'first', 'result': {'decision': 'decline'}})
        request['id'] = 'second'
        c.handle_event(request)
        new = c.shell.pending['token']
        self.assertNotEqual(old, new)
        self.assertIn('+changed', c.shell.output.getvalue())
        c.shell.line('/approve ' + new)
        self.assertEqual(c.send.call_args.args[0], {'id': 'second', 'result': {'decision': 'accept'}})

    def test_native_patch_update_ignores_foreign_turn_and_invalidates_malformed_changes(self):
        c = self.backend();c.turn_id = 'turn';c.shell.active = True
        update = {'method': 'item/fileChange/patchUpdated', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'itemId': 'patch',
            'changes': [{'path': '/tmp/synthetic', 'kind': {'type': 'add'}, 'diff': '+original'}]}}
        c.handle_event(update)
        c.handle_event({'id': 'request', 'method': 'item/fileChange/requestApproval', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'itemId': 'patch'}})
        token = c.shell.pending['token']
        update['params'].update(turnId='foreign', changes=None)
        c.handle_event(update)
        self.assertEqual(c.shell.pending['token'], token)
        c.send.assert_not_called()
        update['params']['turnId'] = 'turn'
        c.handle_event(update)
        self.assertIsNone(c.shell.pending)
        c.send.assert_called_once_with({'id': 'request', 'result': {'decision': 'decline'}})

    def test_unrepresented_native_approval_scopes_never_get_an_accept_token(self):
        for field, value in [('kind', 'writeStdin'), ('kind', 'humanCommand'),
                             ('approvalId', 'callback'), ('environmentId', 'remote'),
                             ('networkApprovalContext', {'host': 'example.org'}), ('grantRoot', '/tmp')]:
            with self.subTest(field=field):
                c = self.backend();c.turn_id = 'turn';c.shell.active = True
                params = {'threadId': 'thread', 'turnId': 'turn', 'itemId': 'item',
                          'command': 'printf synthetic', 'cwd': '/tmp', field: value}
                c.handle_event({'id': 'request', 'method': 'item/fileChange/requestApproval' if field == 'grantRoot'
                    else 'item/commandExecution/requestApproval', 'params': params})
                self.assertIsNone(c.shell.pending)
                self.assertFalse(c._approvals)
                c.send.assert_called_once_with({'id': 'request', 'result': {'decision': 'decline'}})

    def test_duplicate_request_id_declines_once_and_expires_old_token(self):
        c = self.backend();c.turn_id = 'turn';c.shell.active = True
        request = {'id': 'duplicate', 'method': 'item/commandExecution/requestApproval', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'itemId': 'item', 'command': 'printf original', 'cwd': '/tmp'}}
        c.handle_event(request)
        token = c.shell.pending['token']
        request['params']['command'] = 'printf changed'
        c.handle_event(request)
        self.assertIsNone(c.shell.pending)
        c.shell.line('/approve ' + token)
        c.send.assert_called_once_with({'id': 'duplicate', 'result': {'decision': 'decline'}})
        with self.assertRaises(ProbeError):c._answer_tool(token, 'approve')

    def test_patch_approval_cannot_accept_a_changed_invalid_or_completed_preview(self):
        for mutation in ('changed', 'invalid', 'missing_diff', 'changed_type', 'completed', 'unchanged'):
            with self.subTest(mutation=mutation):
                c = self.backend();c.turn_id = 'turn';c.shell.active = True
                item = {'type': 'fileChange', 'id': 'patch',
                        'changes': [{'path': '/tmp/synthetic', 'diff': '+original'}]}
                params = {'threadId': 'thread', 'turnId': 'turn', 'item': item}
                c.handle_event({'method': 'item/started', 'params': params})
                c.handle_event({'id': 'patch-request', 'method': 'item/fileChange/requestApproval',
                    'params': {'threadId': 'thread', 'turnId': 'turn', 'itemId': 'patch'}})
                token = c.shell.pending['token']
                self.assertIn('+original', c.shell.output.getvalue())
                if mutation == 'changed':
                    item['changes'] = [{'path': '/tmp/synthetic', 'diff': '+changed'}]
                elif mutation == 'invalid':
                    item['changes'] = None
                elif mutation == 'missing_diff':
                    item['changes'] = [{'path': '/tmp/synthetic'}]
                elif mutation == 'changed_type':
                    item['type'] = 'commandExecution'
                c.handle_event({'method': 'item/completed' if mutation == 'completed' else 'item/started',
                                'params': params})
                if mutation == 'unchanged':
                    c.send.assert_not_called()
                else:
                    self.assertIsNone(c.shell.pending)
                    # Returning to the original diff cannot revive an expired token.
                    item['type'] = 'fileChange'
                    item['changes'] = [{'path': '/tmp/synthetic', 'diff': '+original'}]
                    c.handle_event({'method': 'item/started', 'params': params})
                c.shell.line('/approve ' + token)
                decision = 'accept' if mutation == 'unchanged' else 'decline'
                self.assertEqual(c.send.call_args.args[0], {'id': 'patch-request', 'result': {'decision': decision}})
                self.assertEqual(c.send.call_count, 1)
                with self.assertRaises(ProbeError):c._answer_tool(token, 'approve')
                if mutation != 'unchanged':
                    self.assertIsNone(c.shell.pending)
                    self.assertIn('fresh preview', c.shell.output.getvalue())

    def test_pending_tool_is_declined_on_cancel_and_token_expires(self):
        c = self.backend();c.turn_id = 'turn';c.shell.active = True
        c.handle_event({'id': 13, 'method': 'item/commandExecution/requestApproval', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'itemId': 'tool', 'command': 'printf x', 'cwd': '/tmp'}})
        token = c.shell.pending['token']
        c.shell.cancel()
        calls = [call.args[0] for call in c.send.call_args_list]
        self.assertEqual(calls[0], {'id': 13, 'result': {'decision': 'decline'}})
        self.assertEqual(calls[1]['method'], 'turn/interrupt')
        with self.assertRaises(ProbeError):c._answer_tool(token, 'approve')


class LiveSubprocessTests(unittest.TestCase):
    def test_two_live_controller_turns_with_explicit_approval_and_decline(self):
        root = str(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as directory:
            trace = str(Path(directory) / 'trace')
            source = '''import sys,modelmate
original=modelmate.LiveChatConnection
fake_source,trace=sys.argv[1:3]
modelmate.LiveChatConnection=lambda command: original([sys.executable,'-u','-c',fake_source,trace])
sys.argv=['modelmate.py','--live','--model','synthetic-model']
sys.exit(modelmate.main())
'''
            p = subprocess.Popen([sys.executable,'-u','-c',source,FAKE,trace],cwd=root,
                                 env=dict(os.environ, XDG_STATE_HOME=str(Path(directory) / 'state')),
                                 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            buffer = b''
            def read_until(target):
                nonlocal buffer
                deadline = time.monotonic()+4
                with selectors.DefaultSelector() as selector:
                    selector.register(p.stdout,selectors.EVENT_READ)
                    while target not in buffer and time.monotonic()<deadline:
                        if selector.select(max(0,deadline-time.monotonic())):
                            data=os.read(p.stdout.fileno(),65536)
                            if not data: break
                            buffer+=data
                self.assertIn(target,buffer,buffer.decode(errors='replace'))
                data,buffer=buffer,b''
                return data
            try:
                read_until(b'auto routing')
                for choice in ('approve','decline'):
                    p.stdin.write('ช่วยตอบข้อความ\n'.encode());p.stdin.flush()
                    data=read_until(b'/decline ')
                    token=data.decode().split('/approve ')[-1].split()[0]
                    p.stdin.write(('/'+choice+' '+token+'\n').encode());p.stdin.flush()
                    read_until('จบ turn'.encode())
                p.stdin.write(b'/exit\n');p.stdin.flush()
                p.wait(timeout=3)
                self.assertEqual(p.returncode,0,p.stderr.read())
                requests=[json.loads(line) for line in Path(trace).read_text().splitlines()]
                starts=[r for r in requests if r.get('method')=='turn/start']
                self.assertEqual(len(starts),2)
                self.assertTrue(all(r['params']['threadId']=='thread' for r in starts))
                decisions=[r['result']['decision'] for r in requests if 'method' not in r]
                self.assertEqual(decisions,['accept','decline'])
                self.assertGreaterEqual(sum(r.get('method')=='account/rateLimits/read' for r in requests),3)
            finally:
                if p.poll() is None:p.kill()
                p.wait(timeout=3)
                for stream in (p.stdin,p.stdout,p.stderr):stream.close()

    def test_live_requires_explicit_model_and_rejects_doctor_combination(self):
        for args in [['--live'], ['--live','--doctor','--model','x']]:
            with patch('sys.argv',['modelmate.py']+args), patch('modelmate.LiveChatConnection') as ctor, \
                 patch('sys.stderr',new_callable=io.StringIO):
                with self.assertRaises(SystemExit):main()
                ctor.assert_not_called()


if __name__ == '__main__':
    unittest.main()
