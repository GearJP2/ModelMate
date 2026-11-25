"""Two synthetic tool turns across reconnect; never invoke installed Codex."""
import io
import json
from contextlib import contextmanager, nullcontext
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from modelmate import (NativeWorkflowConnection, NativeRecheckConnection, RecheckRecoveryConnection,
                       ChatShell, ProbeError, WorkflowController)
from verify import (probe_rechecks, RECHECK_PROBE_KEYS, RECHECK_STOP_KEYS, RECHECK_DISCONNECT_KEYS,
                    PendingApprovalOwner, PassiveApprovalObserver, probe_shared_approval,
                    SHARED_APPROVAL_KEYS, RUNTIME_RECHECK_KEYS, SERVER_LOSS_KEYS, main,
                    wait_for_recheck_owner)


SERVER = r'''
import json,sys
from pathlib import Path
trace,mode=sys.argv[1:]
state=Path(trace+'.state')
data=json.loads(state.read_text()) if state.exists() else {'threads':{},'threadCount':0,'turnCount':0}
recheck_reads=0
owner_reads=0
observer=False
def emit(value):print(json.dumps(value),flush=True)
for line in sys.stdin:
 req=json.loads(line);method=req.get('method');params=req.get('params',{})
 with open(trace,'a') as stream:stream.write(json.dumps(req)+'\n')
 if method is None or 'id' not in req:continue
 if mode.startswith('stop_') and state.exists():data=json.loads(state.read_text())
 if method=='initialize':
  observer=params['clientInfo']['name']=='modelmate_recheck_recovery'
  result={}
 elif method=='account/read':result={'account':{'type':'chatgpt'}}
 elif method=='account/rateLimits/read':result={'accountId':'synthetic','ordinaryUsageAllowed':True,'rateLimits':{'primary':{'usedPercent':5}}}
 elif method=='model/list':result={'data':[{'model':'synthetic','defaultReasoningEffort':'low','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]}
 elif method=='thread/start':
  data['threadCount']+=1;tid='thread'+str(data['threadCount'])
  thread={'id':tid,'cwd':params['cwd'],'ephemeral':params['ephemeral'],'modelProvider':'openai','status':{'type':'idle'}}
  data['threads'][tid]={'thread':thread,'latest':None}
  result={'thread':thread,'approvalPolicy':'on-request','approvalsReviewer':'user','sandbox':{'type':'workspaceWrite' if mode=='permissions' and data['threadCount']==2 else 'readOnly'}}
 elif method in ('thread/read','thread/resume'):
  if mode in ('stop_race','stop_disconnect_terminal') and observer and params['threadId']=='thread2':
   recheck_reads+=1
   if recheck_reads==2:
    data['threads']['thread2']['thread']['status']={'type':'idle'}
    data['threads']['thread2']['latest']['status']='interrupted'
  result={'thread':data['threads'][params['threadId']]['thread'],'approvalPolicy':'on-request','approvalsReviewer':'user','sandbox':{'type':'readOnly'}}
  if mode=='stop_observer_terminal' and observer and params['threadId']=='thread2':
   result['thread']=dict(result['thread'],status={'type':'notLoaded'})
  if mode in ('stop_owner_starting','stop_owner_never_active') and not observer and params['threadId']=='thread2':
   owner_reads+=1
   if owner_reads==1 or mode=='stop_owner_never_active':
    result['thread']=dict(result['thread'],status={'type':'idle'})
 elif method=='thread/turns/list':
  latest=data['threads'][params['threadId']]['latest'];result={'data':[] if latest is None else [latest]}
  if mode=='stop_observer_terminal' and observer and params['threadId']=='thread2':
   result['data']=[dict(latest,status='interrupted')]
 elif method=='turn/start':
  data['turnCount']+=1;turn='turn'+str(data['turnCount']);tid=params['threadId']
  data['threads'][tid]['latest']={'id':turn,'status':'completed'}
  if mode.startswith('stop_') and tid=='thread2':
   data['threads'][tid]['thread']['status']={'type':'active'}
   data['threads'][tid]['latest']['status']='inProgress'
  result={'turn':{'id':turn}}
 elif method=='turn/interrupt':
  if mode.startswith('stop_'):
   target=data['threads'][params['threadId']]
   assert target['latest']['id']==params['turnId']
   target['thread']['status']={'type':'idle'}
   target['latest']['status']='interrupted'
  result={}
 else:raise RuntimeError(method)
 state.write_text(json.dumps(data))
 emit({'id':req['id'],'result':result})
 if method=='turn/start':
  count=data['turnCount'];spec=json.loads(params['input'][0]['text'])['verification_commands'][0]
  if mode.startswith('stop_') and count==2:continue
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

    def test_passive_approval_observer_fails_closed_on_server_request(self):
        observer = object.__new__(PassiveApprovalObserver)
        observer.send = Mock()
        with self.assertRaises(ProbeError):
            observer.handle_event({'id': 4, 'method': 'item/fileChange/requestApproval'})
        observer.send.assert_not_called()
        self.assertNotIn('turn/interrupt', observer.allowed_methods)

    def test_owner_captures_only_one_matching_pending_approval_without_reply(self):
        owner = object.__new__(PendingApprovalOwner)
        owner.pending, owner.terminal_seen = None, False
        owner.timeout = 1
        owner.send = Mock()
        request = {'id': 4, 'method': 'item/fileChange/requestApproval',
                   'params': {'threadId': 'thread', 'turnId': 'turn', 'itemId': 'patch'}}
        owner.handle_event(request)
        owner.wait_for_approval('thread', 'turn')
        with self.assertRaises(ProbeError):
            owner.wait_for_approval('thread', 'foreign')
        with self.assertRaises(ProbeError):
            owner.handle_event(request)
        owner.send.assert_not_called()

    def test_shared_approval_probe_observes_terminal_only_after_closing_owner(self):
        self.check_shared_approval_probe(stop_orphan=False)

    def test_shared_approval_probe_can_stop_only_the_active_orphan(self):
        self.check_shared_approval_probe(stop_orphan=True)

    def check_shared_approval_probe(self, *, stop_orphan):
        owner, observer = Mock(), Mock()
        observer.allowed_methods = PassiveApprovalObserver.allowed_methods
        owner.request.side_effect = [
            {'thread': {'id': 'thread'}, 'sandbox': {'type': 'readOnly'},
             'approvalPolicy': 'on-request', 'approvalsReviewer': 'user'},
            {'turn': {'id': 'turn'}},
        ]

        def observe(project, thread_id, turn_id, *, single_turn):
            self.assertEqual((thread_id, turn_id, single_turn), ('thread', 'turn', True))
            if owner.close.called and (not stop_orphan or observer.request.called):
                return {'state': 'terminal', 'status': 'interrupted'}
            return {'state': 'active'}

        observer.inspect_bound_turn.side_effect = observe
        with patch('verify.PendingApprovalOwner', return_value=owner), \
             patch('verify.PassiveApprovalObserver', return_value=observer), \
             patch('verify.inspect', return_value={'models': []}), \
             patch('verify.select_model', return_value={'model': 'synthetic'}), \
             patch('verify.read_recovery_thread'), \
             patch('verify.refresh_quota', return_value={'state': 'allow', 'account_id': 'synthetic'}):
            report = probe_shared_approval('synthetic', 1, ['bridge'], stop_orphan=stop_orphan)
        self.assertTrue(all(report[key] == 'passed' for key in SHARED_APPROVAL_KEYS), report)
        self.assertEqual(report['observedTerminalStatus'], 'interrupted')
        self.assertEqual(report['modelTurnsRequested'], 1)
        self.assertEqual([call.args[0] for call in owner.request.call_args_list], ['thread/start', 'turn/start'])
        owner.send.assert_not_called()
        observer.send.assert_not_called()
        if stop_orphan:
            observer.request.assert_called_once_with('turn/interrupt', {'threadId': 'thread', 'turnId': 'turn'})
            self.assertEqual(report['observedAfterOwnerDisconnect'], 'active')
            self.assertTrue(report['orphanStopAcknowledged'])
        else:
            observer.request.assert_not_called()

    def test_shared_approval_cli_is_inert_without_live_opt_in(self):
        with patch('sys.argv', ['verify.py', '--probe-shared-approval', 'synthetic']), \
             patch('sys.stdout', new_callable=io.StringIO), patch('verify.private_app_server') as server:
            self.assertEqual(main(), 0)
            server.assert_not_called()

    def probe(self,mode='normal', *, stop=False, disconnect_owner=False, runtime_shared=False, server_loss=False):
        children = []
        self.server_exited = False
        endpoint = Mock()
        endpoint.server.poll.side_effect = lambda: 0 if self.server_exited else None
        @contextmanager
        def owned_server():
            try:
                yield endpoint
            finally:
                self.server_exited = True
                for backend in children:
                    if backend.process.poll() is None:
                        backend.process.terminate()
                        backend.process.wait(timeout=2)
        def parent(command,timeout):
            self.assertIn('forced_login_method="chatgpt"',command)
            return NativeWorkflowConnection([sys.executable,'-u','-c',SERVER,str(self.trace),mode],timeout)
        def child(command,timeout,*,websocket=None):
            backend = NativeRecheckConnection([sys.executable,'-u','-c',SERVER,str(self.trace),mode],timeout)
            children.append(backend)
            return backend
        def observer(command,timeout,*,websocket=None):
            return RecheckRecoveryConnection([sys.executable,'-u','-c',SERVER,str(self.trace),mode],timeout)
        with patch('verify.NativeWorkflowConnection',new=parent), \
             patch('modelmate.NativeRecheckConnection',new=child), \
             patch('modelmate.RecheckRecoveryConnection',new=observer), \
             patch('modelmate.private_recheck_server',side_effect=lambda _: owned_server() if server_loss else nullcontext(object())), \
             patch('modelmate.UnixWebSocket'), \
             patch('verify.RecheckRecoveryConnection',new=observer), \
             patch('verify.tempfile.mkdtemp',return_value=str(self.scratch)), \
             patch('sys.stderr',new_callable=io.StringIO):
            return probe_rechecks('synthetic',1,stop=stop,disconnect_owner=disconnect_owner,
                                  runtime_shared=runtime_shared,server_loss=server_loss)

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

    def test_retained_stop_requires_opt_in_and_observed_active_interruption(self):
        args = ['verify.py', '--probe-rechecks', 'synthetic', '--stop-retained-recheck']
        with patch('sys.argv', args), patch('sys.stderr', new_callable=io.StringIO), \
             patch('verify.probe_rechecks') as probe, self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 2)
        probe.assert_not_called()

        result = dict.fromkeys(RECHECK_STOP_KEYS, 'passed')
        result['activeRecheckObserved'] = 'unverified'
        with patch('sys.argv', args + ['--run-live']), \
             patch('sys.stdout', new_callable=io.StringIO), \
             patch('verify.probe_rechecks', return_value=result) as probe:
            self.assertEqual(main(), 1)
        probe.assert_called_once_with('synthetic', 120, stop=True)

    def test_stop_probe_prewarmed_observer_interrupts_only_the_active_recheck(self):
        result = self.probe('stop_active', stop=True)
        self.assertTrue(all(result[key] == 'passed' for key in RECHECK_STOP_KEYS), result)
        self.assertTrue(result['stopRpcAcknowledged'])
        records = self.records()
        interrupts = [r['params'] for r in records if r['method'] == 'turn/interrupt']
        self.assertEqual(interrupts, [{'threadId': 'thread2', 'turnId': 'turn2'}])
        starts = [i for i, r in enumerate(records) if r['method'] == 'turn/start']
        initializations = [i for i, r in enumerate(records) if r['method'] == 'initialize']
        self.assertEqual(len(starts), 2)
        self.assertLess(max(initializations), starts[1])

    def test_stop_probe_rejects_interrupted_when_no_interrupt_rpc_was_sent(self):
        result = self.probe('stop_race', stop=True)
        self.assertEqual(result['activeRecheckObserved'], 'passed')
        self.assertFalse(result['stopRpcAcknowledged'])
        self.assertEqual(result['observedAfterStop'], 'interrupted')
        self.assertNotEqual(result['nativeRecheckStopped'], 'passed')
        self.assertFalse(any(r['method'] == 'turn/interrupt' for r in self.records()))

    def test_stop_probe_reports_owner_active_when_observer_only_sees_interrupted(self):
        result = self.probe('stop_observer_terminal', stop=True)
        self.assertEqual(result['ownerStatusBeforeInspection'], 'active')
        self.assertEqual(result['observedBeforeStop'], 'interrupted')
        self.assertEqual(result['ownerStatusAfterInspection'], 'active')
        self.assertEqual(result['activeRecheckObserved'], 'unverified')
        self.assertEqual(result['nativeRecheckStopped'], 'unverified')
        self.assertNotIn('stopRpcAcknowledged', result)

    def test_stop_probe_waits_for_owner_to_become_active(self):
        result = self.probe('stop_owner_starting', stop=True)
        self.assertEqual(result['ownerInitialStatus'], 'idle')
        self.assertEqual(result['ownerStatusBeforeInspection'], 'active')
        self.assertTrue(all(result[key] == 'passed' for key in RECHECK_STOP_KEYS), result)

    def test_stop_probe_does_not_consult_observer_before_owner_is_active(self):
        result = self.probe('stop_owner_never_active', stop=True)
        self.assertEqual(result['stopObservationReason'], 'owner_active_not_observed')
        self.assertNotIn('observedBeforeStop', result)
        self.assertNotIn('stopRpcAcknowledged', result)

    def test_owner_observation_error_keeps_reason_and_restores_timeout(self):
        child = Mock(timeout=10, thread_id='synthetic')
        result = {}
        with patch('verify.read_recovery_thread', side_effect=ProbeError('Codex request timed out.')):
            with self.assertRaisesRegex(ProbeError, 'timed out'):
                wait_for_recheck_owner(child, self.root, 1, result)
        self.assertEqual(result['stopObservationReason'], 'owner_active_not_observed')
        self.assertEqual(child.timeout, 10)
        self.assertNotIn('observedBeforeStop', result)

    def test_shared_stop_requires_full_live_opt_in(self):
        args = ['verify.py', '--probe-rechecks', 'synthetic', '--shared-stop-server']
        with patch('verify.probe_shared_recheck_stop') as probe, patch('sys.stderr', new_callable=io.StringIO):
            for options in ([], ['--run-live'], ['--stop-retained-recheck']):
                with self.subTest(options=options), patch('sys.argv', args + options):
                    with self.assertRaises(SystemExit) as error:
                        main()
                    self.assertEqual(error.exception.code, 2)
            probe.assert_not_called()
            probe.return_value = dict.fromkeys(RECHECK_STOP_KEYS, 'passed')
            with patch('sys.argv', args + ['--run-live', '--stop-retained-recheck']), \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(), 0)
            probe.assert_called_once_with('synthetic', 120)

    def test_owner_disconnect_reconciles_terminal_without_sending_stop(self):
        result = self.probe('stop_disconnect_terminal', stop=True, disconnect_owner=True)
        self.assertTrue(all(result[key] == 'passed' for key in RECHECK_DISCONNECT_KEYS), result)
        self.assertEqual(result['observedAfterOwnerDisconnect'], 'interrupted')
        self.assertFalse(any(r['method'] == 'turn/interrupt' for r in self.records()))

    def test_owner_disconnect_stops_only_if_the_bound_turn_survives(self):
        result = self.probe('stop_active', stop=True, disconnect_owner=True)
        self.assertTrue(all(result[key] == 'passed' for key in RECHECK_DISCONNECT_KEYS), result)
        self.assertEqual(result['observedAfterOwnerDisconnect'], 'active')
        self.assertTrue(result['stopRpcAcknowledged'])
        starts = [r for r in self.records() if r['method'] == 'turn/start']
        stops = [r['params'] for r in self.records() if r['method'] == 'turn/interrupt']
        self.assertEqual(len(starts), 2)
        self.assertEqual(stops, [{'threadId': 'thread2', 'turnId': 'turn2'}])

    def test_runtime_shared_recovery_exercises_attached_controller_and_stop_confirmation(self):
        result = self.probe('stop_active', stop=True, runtime_shared=True)
        self.assertTrue(all(result[key] == 'passed' for key in RUNTIME_RECHECK_KEYS), result)
        self.assertEqual(result['transport'], 'runtime_private_unix_websocket')
        self.assertTrue(result['stopRpcAcknowledged'])
        self.assertEqual(result['observedAfterStop'], 'interrupted')
        starts = [r for r in self.records() if r['method'] == 'turn/start']
        stops = [r['params'] for r in self.records() if r['method'] == 'turn/interrupt']
        self.assertEqual(len(starts), 2)
        self.assertEqual(stops, [{'threadId': 'thread2', 'turnId': 'turn2'}])

    def test_runtime_shared_probe_requires_live_stop_and_reports_partial_result(self):
        args = ['verify.py', '--probe-rechecks', 'synthetic', '--runtime-shared-recheck']
        with patch('verify.probe_rechecks') as probe, patch('sys.stderr', new_callable=io.StringIO):
            with patch('sys.argv', args), self.assertRaises(SystemExit):
                main()
            probe.assert_not_called()
            probe.return_value = dict.fromkeys(RUNTIME_RECHECK_KEYS, 'passed')
            probe.return_value['stopConfirmationSingleUse'] = 'unverified'
            with patch('sys.argv', args + ['--run-live', '--stop-retained-recheck']), \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(), 1)
            probe.assert_called_once_with('synthetic', 120, stop=True, runtime_shared=True)

    def test_server_loss_probe_keeps_unknown_binding_and_blocks_replay(self):
        result = self.probe('stop_active', stop=True, runtime_shared=True, server_loss=True)
        self.assertTrue(all(result[key] == 'passed' for key in SERVER_LOSS_KEYS), result)
        self.assertTrue(self.server_exited)
        self.assertNotIn('stopRpcAcknowledged', result)
        self.assertNotIn('PRIVATE_', json.dumps(result))
        self.assertNotIn(str(self.scratch), json.dumps(result))
        requests = self.records()
        self.assertEqual(sum(r['method'] == 'turn/start' for r in requests), 2)
        self.assertFalse(any(r['method'] == 'turn/interrupt' for r in requests))

    def test_server_loss_probe_cannot_pass_without_observing_active_owner(self):
        result = self.probe('stop_owner_never_active', stop=True, runtime_shared=True, server_loss=True)
        self.assertEqual(result['activeRecheckObserved'], 'unverified')
        self.assertEqual(result['ownedServerExited'], 'unverified')
        self.assertEqual(result['finalCheckpoint'], 'unverified')

    def test_server_loss_cli_requires_full_opt_in_and_all_evidence(self):
        args = ['verify.py', '--probe-rechecks', 'synthetic', '--runtime-shared-recheck',
                '--stop-retained-recheck', '--terminate-recheck-server', '--run-live']
        with patch('verify.probe_rechecks') as probe, patch('sys.stderr', new_callable=io.StringIO):
            for missing in ('--run-live', '--runtime-shared-recheck', '--stop-retained-recheck'):
                with self.subTest(missing=missing), patch('sys.argv', [a for a in args if a != missing]):
                    with self.assertRaises(SystemExit) as error:
                        main()
                    self.assertEqual(error.exception.code, 2)
            probe.assert_not_called()
            probe.return_value = dict.fromkeys(SERVER_LOSS_KEYS, 'passed')
            with patch('sys.argv', args), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(), 0)
                probe.return_value['resumeBlocksReplay'] = 'unverified'
                self.assertEqual(main(), 1)
            probe.assert_called_with('synthetic', 120, stop=True, runtime_shared=True, server_loss=True)


if __name__=='__main__':unittest.main()
