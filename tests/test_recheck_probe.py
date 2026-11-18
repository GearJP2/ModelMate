"""Two synthetic tool turns across reconnect; never invoke installed Codex."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from modelmate import NativeWorkflowConnection, NativeRecheckConnection, ChatShell, ProbeError, WorkflowController
from verify import probe_rechecks, RECHECK_PROBE_KEYS, main


SERVER = r'''
import json,sys
from pathlib import Path
trace,mode=sys.argv[1:]
state=Path(trace+'.state')
data=json.loads(state.read_text()) if state.exists() else {'threads':{},'threadCount':0,'turnCount':0}
def emit(value):print(json.dumps(value),flush=True)
for line in sys.stdin:
 req=json.loads(line);method=req.get('method');params=req.get('params',{})
 with open(trace,'a') as stream:stream.write(json.dumps(req)+'\n')
 if method is None or 'id' not in req:continue
 if method=='initialize':result={}
 elif method=='account/read':result={'account':{'type':'chatgpt'}}
 elif method=='account/rateLimits/read':result={'accountId':'synthetic','ordinaryUsageAllowed':True,'rateLimits':{'primary':{'usedPercent':5}}}
 elif method=='model/list':result={'data':[{'model':'synthetic','defaultReasoningEffort':'low','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]}
 elif method=='thread/start':
  data['threadCount']+=1;tid='thread'+str(data['threadCount'])
  thread={'id':tid,'cwd':params['cwd'],'ephemeral':params['ephemeral'],'modelProvider':'openai','status':{'type':'idle'}}
  data['threads'][tid]={'thread':thread,'latest':None}
  result={'thread':thread,'approvalPolicy':'on-request','approvalsReviewer':'user','sandbox':{'type':'workspaceWrite' if mode=='permissions' and data['threadCount']==2 else 'readOnly'}}
 elif method in ('thread/read','thread/resume'):
  result={'thread':data['threads'][params['threadId']]['thread'],'approvalPolicy':'on-request','approvalsReviewer':'user','sandbox':{'type':'readOnly'}}
 elif method=='thread/turns/list':
  latest=data['threads'][params['threadId']]['latest'];result={'data':[] if latest is None else [latest]}
 elif method=='turn/start':
  data['turnCount']+=1;turn='turn'+str(data['turnCount']);tid=params['threadId']
  data['threads'][tid]['latest']={'id':turn,'status':'completed'}
  result={'turn':{'id':turn}}
 elif method=='turn/interrupt':result={}
 else:raise RuntimeError(method)
 state.write_text(json.dumps(data))
 emit({'id':req['id'],'result':result})
 if method=='turn/start':
  count=data['turnCount'];spec=json.loads(params['input'][0]['text'])['verification_commands'][0]
  event={'threadId':tid,'turnId':turn}
  if mode=='approval' and count==2:
   emit({'id':99,'method':'item/commandExecution/requestApproval','params':dict(event,itemId='approval')});continue
  if mode!='missing_first' or count!=1:
   for name in ('item/started','item/completed'):
    item={'type':'commandExecution','id':'cmd','command':spec['command'],'cwd':spec['cwd']}
    if mode=='wrong_recheck' and count==2:item['command']='PRIVATE_UNRELATED_COMMAND'
    if name=='item/completed':item.update(status='completed',exitCode=1 if (mode=='first_fail' and count==1) or (mode=='second_fail' and count==2) else 0)
    emit({'method':name,'params':dict(event,item=item)})
  emit({'method':'item/completed','params':dict(event,item={'type':'agentMessage','id':'answer','text':'PRIVATE_MODEL_CLAIMS_PASS'})})
  emit({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':turn,'status':'completed'}}})
 if method=='turn/interrupt':emit({'method':'turn/completed','params':{'threadId':params['threadId'],'turn':{'id':params['turnId'],'status':'interrupted'}}})
'''


class RecheckProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.scratch=self.root/'scratch';self.scratch.mkdir()
        self.trace=self.root/'trace'

    def probe(self,mode='normal'):
        def parent(command,timeout):
            self.assertIn('forced_login_method="chatgpt"',command)
            return NativeWorkflowConnection([sys.executable,'-u','-c',SERVER,str(self.trace),mode],timeout)
        def child(command,timeout):
            return NativeRecheckConnection([sys.executable,'-u','-c',SERVER,str(self.trace),mode],timeout)
        with patch('verify.NativeWorkflowConnection',new=parent), \
             patch('modelmate.NativeRecheckConnection',new=child), \
             patch('verify.tempfile.mkdtemp',return_value=str(self.scratch)), \
             patch('sys.stderr',new_callable=io.StringIO):
            return probe_rechecks('synthetic',1)

    def records(self):return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def test_two_turn_native_recheck_preserves_work_and_redacts_report(self):
        result=self.probe()
        for key in RECHECK_PROBE_KEYS:self.assertEqual(result[key],'passed',(key,result))
        records=self.records()
        self.assertEqual(sum(r.get('method')=='turn/start' for r in records),2)
        self.assertEqual(sum(r.get('method')=='thread/start' for r in records),2)
        self.assertEqual(sum(r.get('method')=='thread/resume' for r in records),1)
        turns=[r['params'] for r in records if r.get('method')=='turn/start']
        self.assertNotEqual(turns[0]['threadId'],turns[1]['threadId'])
        command=json.loads(turns[0]['input'][0]['text'])['verification_commands'][0]['command']
        report=json.dumps(result)
        self.assertNotIn(command,report)
        self.assertNotIn('PRIVATE_',report)
        self.assertNotIn(str(self.scratch),report)
        self.assertIsNone(result['reportedModels'])
        self.assertTrue(result['scratchRetained']);self.assertTrue(self.scratch.exists())

    def test_initial_failure_stops_before_second_turn(self):
        result=self.probe('first_fail')
        self.assertEqual(result['initialToolEvidence'],'failed')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_model_claim_without_initial_command_is_not_evidence(self):
        result=self.probe('missing_first')
        self.assertEqual(result['initialToolEvidence'],'failed')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_failed_recheck_remains_stale_without_retry(self):
        result=self.probe('second_fail')
        self.assertEqual(result['nativeRecheck'],'failed')
        self.assertNotEqual(result['finalCheckpoint'],'passed')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),2)

    def test_unrelated_recheck_command_cannot_validate_model_claim(self):
        result=self.probe('wrong_recheck')
        self.assertEqual(result['nativeRecheck'],'failed')
        self.assertNotIn('PRIVATE_',json.dumps(result))

    def test_expanded_permissions_stop_before_recheck_turn(self):
        result=self.probe('permissions')
        self.assertEqual(result['nativeRecheck'],'unverified')
        self.assertEqual(result['failureReason'],'recheck_start_unverified')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_preview_cannot_start_child_without_confirmation(self):
        original=ChatShell.recheck_command
        def refuse_confirmation(shell,cmd,values):
            if cmd=='/confirm-recheck':raise ProbeError('synthetic refused confirmation')
            return original(shell,cmd,values)
        with patch.object(ChatShell,'recheck_command',refuse_confirmation):result=self.probe()
        self.assertEqual(result['consentGate'],'passed')
        self.assertEqual(result['failureReason'],'recheck_start_unverified')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_unrelated_error_is_not_reported_as_a_passed_stale_gate(self):
        original=WorkflowController.finish_task
        def unrelated_error(controller,coverage):
            if controller.snapshot()['stale_evidence']:raise ProbeError('PRIVATE_UNRELATED_FAILURE')
            return original(controller,coverage)
        with patch.object(WorkflowController,'finish_task',unrelated_error):result=self.probe()
        self.assertNotEqual(result['restoredEvidenceGate'],'passed')
        self.assertEqual(result['failureReason'],'stale_gate_not_confirmed')
        self.assertNotIn('PRIVATE_',json.dumps(result))
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_approval_is_declined_and_probe_does_not_retry(self):
        result=self.probe('approval')
        self.assertNotEqual(result['nativeRecheck'],'passed')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),2)
        replies=[r for r in self.records() if r.get('id')==99 and 'result' in r]
        self.assertEqual([r['result'] for r in replies],[{'decision':'decline'}])

    def test_cli_requires_live_opt_in_and_never_passes_partial_result(self):
        with patch('sys.argv',['verify.py','--probe-rechecks','synthetic']), \
             patch('sys.stdout',new_callable=io.StringIO),patch('verify.probe_rechecks') as probe:
            self.assertEqual(main(),0);probe.assert_not_called()
        partial=dict.fromkeys(RECHECK_PROBE_KEYS,'passed');partial['nativeRecheck']='unverified'
        with patch('sys.argv',['verify.py','--run-live','--probe-rechecks','synthetic']), \
             patch('sys.stdout',new_callable=io.StringIO),patch('verify.probe_rechecks',return_value=partial):
            self.assertEqual(main(),1)


if __name__=='__main__':unittest.main()
