"""No live inference: the verifier runs against a synthetic native App Server."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verify import WorkflowVerificationConnection, main, probe_workflow
from modelmate import ChatShell

SERVER = r'''
import sys,json,re
from pathlib import Path
trace,mode=sys.argv[1:]
turn=0;cwd=None;nonce=None;cancel=False
for line in sys.stdin:
 req=json.loads(line)
 with open(trace,'a') as f:f.write(json.dumps(req)+'\n')
 method=req.get('method');p=req.get('params',{})
 if method is None or 'id' not in req:continue
 if method=='initialize':result={}
 elif method=='account/read':result={'account':{'type':'apiKey' if mode=='auth' else 'chatgpt'}}
 elif method=='account/rateLimits/read':result={'accountId':'PRIVATE_ACCOUNT','ordinaryUsageAllowed':True,
  'rateLimits':{'primary':{'usedPercent':5}}}
 elif method=='model/list':result={'data':[{'model':'synthetic','defaultReasoningEffort':'low',
  'supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]}
 elif method=='thread/start':
  cwd=p['cwd'];result={'thread':{'id':'PRIVATE_THREAD','cwd':cwd,'ephemeral':True,'modelProvider':'openai'},
   'approvalPolicy':'on-request','approvalsReviewer':'user','sandbox':{'type':'readOnly'}}
 elif method=='turn/start':
  turn+=1
  objective=json.loads(p['input'][0]['text'])['step']['objective']
  cancel='10000' in objective
  if 'Remember this synthetic code:' in objective:nonce=re.search(r'code: ([0-9a-f]+)',objective).group(1)
  result={'turn':{'id':str(turn)}}
 elif method=='turn/interrupt':result={}
 else:raise RuntimeError(method)
 print(json.dumps({'id':req['id'],'result':result}),flush=True)
 if method=='turn/start':
  if mode=='hang' or (cancel and mode!='cancel_race'):continue
  if turn==3:
   if mode=='changed':Path(cwd,'sentinel.txt').write_text('changed')
   if mode not in ('no_approval','changed'):
    print(json.dumps({'id':'tool','method':'item/commandExecution/requestApproval','params':{
     'threadId':'PRIVATE_THREAD','turnId':str(turn),'itemId':'command','command':'synthetic write','cwd':cwd}}),flush=True)
    continue
  text='ACK' if turn==1 else 'wrong' if mode=='recall' else nonce or 'finished'
  print(json.dumps({'method':'item/completed','params':{'threadId':'PRIVATE_THREAD','turnId':str(turn),
   'item':{'id':'answer','type':'agentMessage','text':text}}}),flush=True)
  print(json.dumps({'method':'turn/completed','params':{'threadId':'PRIVATE_THREAD','turn':{
   'id':str(turn),'status':'failed' if mode=='failed' else 'completed'}}}),flush=True)
 if method=='turn/interrupt' and not (cancel and mode=='cancel_race'):
  print(json.dumps({'method':'turn/completed','params':{'threadId':'PRIVATE_THREAD','turn':{
   'id':str(turn),'status':'interrupted'}}}),flush=True)
'''


class WorkflowProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scratch = self.root / 'scratch';self.scratch.mkdir()
        self.trace = self.root / 'trace'

    def probe(self, mode='success', timeout=1):
        original = WorkflowVerificationConnection
        def factory(command, timeout):
            self.assertIn('forced_login_method="chatgpt"', command)
            return original([sys.executable,'-u','-c',SERVER,str(self.trace),mode], timeout)
        with patch('verify.WorkflowVerificationConnection',side_effect=factory), \
             patch('verify.tempfile.mkdtemp',return_value=str(self.scratch)), \
             patch('sys.stderr',new_callable=io.StringIO):
            return probe_workflow('synthetic', timeout)

    def records(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def test_four_turns_display_recall_denial_cancel_and_disconnect_guard(self):
        result = self.probe()
        for key in ('answerDisplay','contextRecall','approvalDenial','sentinelUnchanged','cancel','disconnectGuard'):
            self.assertEqual(result[key],'passed',(key,result))
        self.assertFalse(self.scratch.exists())
        records = self.records()
        turns = [r for r in records if r.get('method')=='turn/start']
        self.assertEqual(len(turns),4)
        first = json.loads(turns[0]['params']['input'][0]['text'])['step']['objective']
        nonce = first.split('code: ')[1].split('.')[0]
        self.assertNotIn(nonce, turns[1]['params']['input'][0]['text'])
        report = json.dumps(result)
        for private in ('PRIVATE_ACCOUNT','PRIVATE_THREAD',str(self.scratch),nonce):
            self.assertNotIn(private, report)
        self.assertEqual([r['result']['decision'] for r in records if 'result' in r],['decline'])
        self.assertIsNone(result['reportedModels'])
        self.assertEqual(len(result['runtimeSha256']),64)

    def test_no_approval_is_unverified_and_retains_scratch(self):
        result = self.probe('no_approval')
        self.assertEqual(result['approvalDenial'],'unverified')
        self.assertTrue(self.scratch.exists())

    def test_changed_sentinel_fails_and_skips_cancel_turn(self):
        result = self.probe('changed')
        self.assertEqual(result['sentinelUnchanged'],'failed')
        self.assertEqual(result['approvalDenial'],'failed')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),3)
        self.assertTrue(self.scratch.exists())

    def test_wrong_recall_is_not_passed_or_retried(self):
        result = self.probe('recall')
        self.assertEqual(result['contextRecall'],'failed')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),2)
        self.assertTrue(self.scratch.exists())

    def test_cancel_race_is_unverified(self):
        result = self.probe('cancel_race')
        self.assertEqual(result['cancel'],'unverified')
        self.assertTrue(self.scratch.exists())

    def test_timeout_and_failed_turn_do_not_replay(self):
        for mode in ('hang','failed'):
            with self.subTest(mode=mode):
                self.trace.unlink(missing_ok=True)
                result = self.probe(mode,timeout=.2)
                self.assertNotEqual(result['answerDisplay'],'passed')
                self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_auth_failure_starts_no_turn(self):
        result = self.probe('auth')
        self.assertEqual(result['answerDisplay'],'unverified')
        self.assertFalse(any(r.get('method')=='turn/start' for r in self.records()))

    def test_noop_disconnect_does_not_pass_or_start_a_fifth_turn(self):
        with patch('modelmate.WorkflowHost.disconnect', lambda self: None):
            result = self.probe()
        self.assertEqual(result['disconnectGuard'], 'failed')
        self.assertEqual(sum(r.get('method') == 'turn/start' for r in self.records()), 4)
        self.assertTrue(self.scratch.exists())

    def test_dropped_display_text_does_not_pass_from_event_payload(self):
        original = ChatShell.event
        def drop_text(shell, message):
            if message.get('type') != 'text':
                return original(shell, message)
        with patch.object(ChatShell, 'event', drop_text):
            result = self.probe()
        self.assertEqual(result['answerDisplay'], 'failed')
        self.assertEqual(sum(r.get('method') == 'turn/start' for r in self.records()), 1)
        self.assertTrue(self.scratch.exists())

    def test_cli_requires_optin_and_maps_incomplete_to_exit_one(self):
        with patch('sys.argv',['verify.py','--probe-workflow','synthetic']), \
             patch('verify.probe_workflow') as probe, patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(),0);probe.assert_not_called()
        with patch('sys.argv',['verify.py','--run-live','--probe-workflow','synthetic']), \
             patch('verify.probe_workflow',return_value={'cancel':'unverified'}), \
             patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(),1)
