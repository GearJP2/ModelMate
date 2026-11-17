"""No real Codex or inference: two fake server processes share synthetic state."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modelmate import ProbeError
from verify import SessionVerificationConnection, main, probe_sessions


SERVER = r'''
import json,sys
from pathlib import Path
trace,mode=sys.argv[1:3]
state=Path(trace+'.state')
data=json.loads(state.read_text()) if state.exists() else {'count':0,'deleted':False}
for line in sys.stdin:
 req=json.loads(line)
 with open(trace,'a') as f:f.write(json.dumps(req)+'\n')
 method=req.get('method');p=req.get('params',{})
 if 'id' not in req or method is None:continue
 if method=='initialize':result={}
 elif method=='account/read':result={'account':{'type':'chatgpt'}}
 elif method=='account/rateLimits/read':result={'accountId':'private-synthetic-account','ordinaryUsageAllowed':True,
  'rateLimits':{'primary':{'usedPercent':5}}}
 elif method=='model/list':result={'data':[{'model':'synthetic-model','defaultReasoningEffort':'low',
  'supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]}
 elif method=='thread/start':
  data['thread']={'id':'private-thread-id','cwd':p['cwd'],'ephemeral':False,'modelProvider':'openai',
   'status':{'type':'idle'},'parentThreadId':None,'source':'exec'}
  result={'thread':data['thread']}
 elif method in ('thread/read','thread/resume'):
  result={'thread':data['thread'],'approvalPolicy':'on-request','approvalsReviewer':'user','sandbox':{'type':'readOnly'}}
 elif method=='thread/turns/list':result={'data':[{'id':'old-turn','status':'completed','items':[]}]}
 elif method=='thread/list':
  rows=[] if data['deleted'] and mode!='lingering' else [data['thread']]
  if 'exec' not in p.get('sourceKinds',['exec']):rows=[]
  if mode=='extra_scope':rows.append(dict(data['thread'],id='child',parentThreadId=data['thread']['id']))
  result={'data':rows,'nextCursor':None}
 elif method=='thread/delete':
  if mode=='delete_failure':
   print(json.dumps({'id':req['id'],'error':{'code':-1,'message':'PRIVATE diagnostic'}}),flush=True);continue
  data['deleted']=True;result={}
 elif method=='turn/start':
  data['count']+=1
  if data['count']==1:data['nonce']=p['input'][0]['text'].split(': ',1)[1].split('.')[0]
  if mode=='sentinel_changed' and data['count']==2:
   Path(data['thread']['cwd'],'sentinel.txt').write_text('changed')
  result={'turn':{'id':'turn-'+str(data['count'])}}
 elif method=='turn/interrupt':result={}
 else:raise RuntimeError(method)
 state.write_text(json.dumps(data))
 print(json.dumps({'id':req['id'],'result':result}),flush=True)
 if method=='turn/start':
  tid='turn-'+str(data['count']);thread=data['thread']['id']
  print(json.dumps({'method':'turn/started','params':{'threadId':thread,'turn':{'id':tid}}}),flush=True)
  if mode=='hang':continue
  if mode=='tool':
   print(json.dumps({'id':'approval','method':'item/commandExecution/requestApproval','params':{
    'threadId':thread,'turnId':tid,'itemId':'tool','command':'printf synthetic','cwd':data['thread']['cwd']}}),flush=True)
   continue
  text='ACK' if data['count']==1 else 'wrong' if mode=='recall_failure' else data['nonce']
  print(json.dumps({'method':'item/completed','params':{'threadId':thread,'turnId':tid,
   'item':{'id':'answer','type':'agentMessage','text':text}}}),flush=True)
  print(json.dumps({'method':'turn/completed','params':{'threadId':thread,'turn':{'id':tid,
   'status':'failed' if mode=='failed_turn' else 'completed'}}}),flush=True)
 if method=='turn/interrupt':
  print(json.dumps({'method':'turn/completed','params':{'threadId':data['thread']['id'],
   'turn':{'id':'turn-'+str(data['count']),'status':'interrupted'}}}),flush=True)
'''


class SessionProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir(mode=0o700)
        self.trace = self.root / 'trace'

    def run_probe(self, mode='success'):
        original = SessionVerificationConnection
        def factory(command, timeout):
            self.assertIn('forced_login_method="chatgpt"', command)
            return original([sys.executable, '-u', '-c', SERVER, str(self.trace), mode], timeout)
        with patch('verify.SessionVerificationConnection', side_effect=factory), \
             patch('verify.tempfile.mkdtemp', return_value=str(self.scratch)), \
             patch('verify.secrets.token_hex', return_value='private-synthetic-marker'):
            return probe_sessions('synthetic-model', 2)

    def messages(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def test_two_connections_recall_and_confirmed_scratch_deletion_with_redacted_report(self):
        result = self.run_probe()
        self.assertEqual(result['contextRecallAfterReconnect'], 'passed')
        self.assertEqual(result['confirmedDeletion'], 'passed')
        self.assertFalse(self.scratch.exists())
        messages = self.messages()
        methods = [m.get('method') for m in messages]
        self.assertEqual(methods.count('initialize'), 2)
        self.assertEqual(methods.count('thread/start'), 1)
        self.assertEqual(methods.count('thread/resume'), 1)
        self.assertEqual(methods.count('turn/start'), 2)
        self.assertEqual(methods.count('thread/delete'), 1)
        turns = [m for m in messages if m.get('method') == 'turn/start']
        self.assertNotIn('private-synthetic-marker', turns[1]['params']['input'][0]['text'])
        report = json.dumps(result)
        for private in ('private-synthetic-marker', 'private-synthetic-account', 'private-thread-id', str(self.scratch)):
            self.assertNotIn(private, report)
        self.assertIsNone(result['reportedModels'])
        self.assertRegex(result['runtimeSha256'], '^[0-9a-f]{64}$')
        self.assertRegex(result['verifierSha256'], '^[0-9a-f]{64}$')

    def test_recall_failure_retains_scratch_and_never_attempts_remote_deletion(self):
        with patch('sys.stderr', new_callable=io.StringIO) as err:
            with self.assertRaisesRegex(ProbeError, 'recall'):self.run_probe('recall_failure')
        self.assertIn('stopped at recall', err.getvalue())
        self.assertTrue((self.scratch / 'project' / 'sentinel.txt').exists())
        self.assertNotIn('thread/delete', [m.get('method') for m in self.messages()])

    def test_descendant_scope_is_never_confirmed_automatically(self):
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(ProbeError, 'scope'):self.run_probe('extra_scope')
        self.assertTrue(self.scratch.exists())
        self.assertNotIn('thread/delete', [m.get('method') for m in self.messages()])

    def test_delete_failure_retains_retry_metadata_and_hides_raw_server_error(self):
        with patch('sys.stderr', new_callable=io.StringIO) as err:
            with self.assertRaisesRegex(ProbeError, 'deletion'):self.run_probe('delete_failure')
        records = list((self.scratch / 'state').rglob('*.json'))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())['deletion_state'], 'requested')
        self.assertNotIn('PRIVATE', err.getvalue())

    def test_lingering_thread_cannot_report_success_even_with_non_appserver_source(self):
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(ProbeError, 'listing'):self.run_probe('lingering')
        self.assertTrue(self.scratch.exists())

    def test_changed_sentinel_cannot_report_success_and_is_preserved(self):
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(ProbeError, 'sentinel'):self.run_probe('sentinel_changed')
        self.assertEqual((self.scratch / 'project' / 'sentinel.txt').read_text(), 'changed')
        self.assertNotIn('thread/delete', [m.get('method') for m in self.messages()])

    def test_unexpected_tool_is_declined_then_interrupted_without_success(self):
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(ProbeError, 'tool'):self.run_probe('tool')
        messages = self.messages()
        decisions = [m['result']['decision'] for m in messages if 'result' in m]
        self.assertEqual(decisions, ['decline'])
        self.assertIn('turn/interrupt', [m.get('method') for m in messages])
        self.assertNotIn('thread/delete', [m.get('method') for m in messages])
        self.assertTrue(self.scratch.exists())

    def test_failed_turn_is_not_a_successful_probe(self):
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(ProbeError, 'complete'):self.run_probe('failed_turn')
        self.assertNotIn('thread/delete', [m.get('method') for m in self.messages()])

    def test_timeout_requests_interrupt_and_preserves_scratch_without_replay(self):
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(ProbeError, 'timed out'):self.run_probe('hang')
        methods = [m.get('method') for m in self.messages()]
        self.assertEqual(methods.count('turn/start'), 1)
        self.assertIn('turn/interrupt', methods)
        self.assertNotIn('thread/delete', methods)
        self.assertTrue(self.scratch.exists())

    def test_live_opt_in_and_exclusive_modes_are_required_before_connecting(self):
        with patch('sys.argv', ['verify.py', '--probe-sessions', 'synthetic-model']), \
             patch('verify.SessionVerificationConnection') as connection, patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(main(), 0)
            connection.assert_not_called()
        for flags in (['--models', 'one', 'two'], ['--timeout', 'nan']):
            with patch('sys.argv', ['verify.py', '--run-live', '--probe-sessions', 'synthetic-model'] + flags), \
                 patch('verify.SessionVerificationConnection') as connection, patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit):main()
                connection.assert_not_called()


if __name__ == '__main__':
    unittest.main()
