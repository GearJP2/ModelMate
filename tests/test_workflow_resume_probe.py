"""Two fake processes verify the opt-in resume harness without spending quota."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from modelmate import ChatShell, WorkflowController, NativeWorkflowConnection, ProbeError
from verify import (WorkflowVerificationConnection, WorkRecoveryVerificationConnection,
                    WORK_RECOVERY_KEYS, probe_workflow_resume, probe_work_recovery, main)
from test_native_resume import SERVER

PROBE_SERVER = SERVER.replace("data['remembered']=objective",
    "data['remembered']=objective.split('code: ')[1].split('.')[0] if 'code: ' in objective else objective")
PROBE_SERVER = PROBE_SERVER.replace("'ACK' if data['count']==1 else data['remembered']",
    "'ACK' if data['count']==1 else 'wrong' if mode=='recall' else data['remembered']")


class WorkflowResumeProbeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.scratch=self.root/'scratch';self.scratch.mkdir()
        self.trace=self.root/'trace'

    def probe(self,mode='normal'):
        original=WorkflowVerificationConnection
        def factory(command,timeout):
            self.assertIn('forced_login_method="chatgpt"',command)
            return original([sys.executable,'-u','-c',PROBE_SERVER,str(self.trace),mode],timeout)
        with patch('verify.WorkflowVerificationConnection',side_effect=factory), \
             patch('verify.tempfile.mkdtemp',return_value=str(self.scratch)), \
             patch('sys.stderr',new_callable=io.StringIO):
            return probe_workflow_resume('synthetic-standard',1)

    def records(self):return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def recover_work(self):
        original = WorkRecoveryVerificationConnection
        directory = self.root / 'recovery-copy';directory.mkdir()
        def factory(command, timeout):
            return original([sys.executable, '-u', '-c', PROBE_SERVER, str(self.trace), 'normal'], timeout)
        with patch('verify.WorkRecoveryVerificationConnection', side_effect=factory), \
             patch('verify.tempfile.mkdtemp', return_value=str(directory)), \
             patch('sys.stderr', new_callable=io.StringIO):
            return probe_work_recovery(self.scratch, 1)

    def test_missing_work_binding_probe_recovers_copy_without_new_turns_or_source_changes(self):
        self.assertEqual(self.probe()['finalCheckpoint'], 'passed')
        source_files = {p: p.read_bytes() for p in self.scratch.rglob('*.json')}
        result = self.recover_work()
        self.assertTrue(all(result[k] == 'passed' for k in WORK_RECOVERY_KEYS), result)
        self.assertEqual(result['modelTurnsRequested'], 0)
        self.assertFalse(result['copyRetained'])
        self.assertFalse((self.root / 'recovery-copy').exists())
        self.assertEqual({p: p.read_bytes() for p in self.scratch.rglob('*.json')}, source_files)
        records = self.records()
        self.assertEqual(sum(r.get('method') == 'turn/start' for r in records), 2)
        self.assertFalse(any(r.get('method') in ('turn/interrupt', 'thread/delete') for r in records))
        prompt = next(r['params']['input'][0]['text'] for r in records if r.get('method') == 'turn/start')
        nonce = json.loads(prompt)['step']['objective'].split('code: ')[1].split('.')[0]
        self.assertNotIn(nonce, json.dumps(result))
        self.assertNotIn(str(self.scratch), json.dumps(result))

    def test_missing_work_marker_cannot_pass_recovery_probe(self):
        self.assertEqual(self.probe()['finalCheckpoint'], 'passed')
        path = Path(str(self.trace) + '.state')
        native = json.loads(path.read_text())
        native['latest']['items'][0]['clientId'] = None
        path.write_text(json.dumps(native))
        result = self.recover_work()
        self.assertEqual(result['nativeBindingRecovered'], 'unverified')
        self.assertTrue(result['copyRetained'])
        self.assertEqual(result['sourceUnchanged'], 'passed')
        self.assertEqual(sum(r.get('method') == 'turn/start' for r in self.records()), 2)

    def test_work_recovery_probe_detects_invented_fresh_evidence(self):
        self.assertEqual(self.probe()['finalCheckpoint'], 'passed')
        resume = WorkRecoveryVerificationConnection.resume
        def invent(backend, *args, **kwargs):
            host = resume(backend, *args, **kwargs)
            active = host.controller.snapshot()['active_attempt']
            host.controller.record_check(active['id'], 0, origin='manual', result='pass',
                reference='Synthetic injected verifier fault', finding='This must not be inferred from metadata')
            return host
        with patch.object(WorkRecoveryVerificationConnection, 'resume', invent):
            result = self.recover_work()
        self.assertEqual(result['nativeBindingRecovered'], 'passed')
        self.assertNotEqual(result['noFreshEvidenceOrGrants'], 'passed')
        self.assertTrue(result['copyRetained'])
        self.assertEqual(result['sourceUnchanged'], 'passed')

    def test_work_recovery_send_tripwire_blocks_mutations_and_approval_replies(self):
        connection = object.__new__(WorkRecoveryVerificationConnection)
        connection.blocked_messages = 0
        messages = [{'id': 1, 'method': method} for method in
                    ('turn/start', 'thread/start', 'turn/interrupt', 'thread/delete')]
        messages += [{'id': 1, 'result': {'decision': 'accept'}}, {'id': 1, 'result': {'decision': 'decline'}}]
        with patch.object(NativeWorkflowConnection, 'send') as send:
            for message in messages:
                with self.subTest(message=message), self.assertRaises(ProbeError):connection.send(message)
            send.assert_not_called()
        self.assertEqual(connection.blocked_messages, len(messages))

    def test_work_recovery_rejects_an_incomplete_source_before_native_access(self):
        self.assertEqual(self.probe('recall')['contextRecallAfterReconnect'], 'failed')
        with patch('verify.WorkRecoveryVerificationConnection') as connection, \
             patch('sys.stderr', new_callable=io.StringIO):
            result = probe_work_recovery(self.scratch, 1)
        connection.assert_not_called()
        self.assertEqual(result['phase'], 'source_validation')
        self.assertNotEqual(result['nativeBindingRecovered'], 'passed')
        self.assertEqual(result['sourceUnchanged'], 'passed')

    def test_work_recovery_cli_is_zero_inference_and_requires_all_checks(self):
        args = ['verify.py', '--probe-work-recovery', str(self.scratch)]
        with patch('verify.probe_work_recovery') as probe, patch('sys.stdout', new_callable=io.StringIO):
            probe.return_value = dict.fromkeys(WORK_RECOVERY_KEYS, 'passed')
            with patch('sys.argv', args):self.assertEqual(main(), 0)
            probe.assert_called_once_with(str(self.scratch), 120)
            probe.return_value['noReplay'] = 'unverified'
            with patch('sys.argv', args):self.assertEqual(main(), 1)
            for options in (['--run-live'], ['--probe-recheck-recovery', str(self.scratch)],
                            ['--probe-workflow-resume', 'synthetic'], ['--timeout', 'nan']):
                with self.subTest(options=options), patch('sys.argv', args + options), \
                     patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)

    def test_two_turn_reconnect_done_and_redacted_retained_scratch(self):
        result=self.probe()
        for key in ('durableResume','contextRecallAfterReconnect','restoredEvidenceGate','finalCheckpoint','sentinelUnchanged'):
            self.assertEqual(result[key],'passed',(key,result))
        self.assertTrue(result['scratchRetained']);self.assertTrue(self.scratch.exists())
        records=self.records()
        self.assertEqual(sum(r.get('method')=='thread/start' for r in records),1)
        self.assertEqual(sum(r.get('method')=='thread/resume' for r in records),1)
        self.assertEqual(sum(r.get('method')=='turn/start' for r in records),2)
        turns=[r['params'] for r in records if r.get('method')=='turn/start']
        first=json.loads(turns[0]['input'][0]['text'])['step']['objective']
        nonce=first.split('code: ')[1].split('.')[0]
        self.assertNotIn(nonce,turns[1]['input'][0]['text'])
        report=json.dumps(result)
        self.assertNotIn(nonce,report)
        self.assertNotIn(str(self.scratch),report)
        self.assertIsNone(result['reportedModels'])

    def test_user_message_item_is_metadata_not_a_tool(self):
        server=PROBE_SERVER.replace(" if method=='turn/start':\n", " if method=='turn/start':\n  print(json.dumps({'method':'item/started','params':{'threadId':'thread','turnId':str(data['count']),'item':{'id':'input','type':'userMessage'}}}),flush=True)\n",1)
        with patch(__name__+'.PROBE_SERVER',server):result=self.probe()
        self.assertEqual(result['durableResume'],'passed',result)
        self.assertEqual(result['contextRecallAfterReconnect'],'passed',result)
        self.assertEqual(result['firstTurn']['toolEvents'],0)
        self.assertEqual(result['firstTurn']['startedItems']['userMessage'],1)

    def test_real_tool_or_unknown_item_stops_before_reconnect_with_safe_diagnostics(self):
        for kind,reason in (('commandExecution','tool_activity_observed'),('PRIVATE_UNKNOWN_TYPE','unknown_item_type')):
            with self.subTest(kind=kind):
                self.trace.unlink(missing_ok=True)
                Path(str(self.trace)+'.state').unlink(missing_ok=True)
                # Use fresh private state for each independent synthetic probe.
                import shutil
                shutil.rmtree(self.scratch);self.scratch.mkdir()
                event="  print(json.dumps({'method':'item/started','params':{'threadId':'thread','turnId':str(data['count']),'item':{'id':'tool-item','type':"+repr(kind)+",'command':'PRIVATE_COMMAND','cwd':'/private'}}}),flush=True)\n"
                server=PROBE_SERVER.replace(" if method=='turn/start':\n", " if method=='turn/start':\n"+event,1)
                with patch(__name__+'.PROBE_SERVER',server):result=self.probe()
                self.assertEqual(result['durableResume'],'unverified')
                self.assertEqual(result['failureReason'],reason)
                self.assertTrue(result['firstTurn']['exactExpectedAnswer'])
                self.assertEqual(result['sentinelUnchanged'],'passed')
                self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)
                report=json.dumps(result)
                self.assertNotIn('PRIVATE_UNKNOWN_TYPE',report)
                self.assertNotIn('PRIVATE_COMMAND',report)
                self.assertNotIn('/private',report)

    def test_failed_recall_is_not_retried(self):
        result=self.probe('recall')
        self.assertEqual(result['contextRecallAfterReconnect'],'failed')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),2)

    def test_dropped_ui_output_fails_before_reconnect(self):
        original=ChatShell.event
        def drop(shell,message):
            if message.get('type')!='text':return original(shell,message)
        with patch.object(ChatShell,'event',drop):result=self.probe()
        self.assertNotEqual(result['durableResume'],'passed')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_missing_stale_evidence_gate_is_detected(self):
        original=WorkflowController.finish_task
        def bypass(controller,coverage):
            controller._stale_evidence.clear()
            return original(controller,coverage)
        with patch.object(WorkflowController,'finish_task',bypass):result=self.probe()
        self.assertEqual(result['restoredEvidenceGate'],'failed')
        self.assertNotEqual(result['finalCheckpoint'],'passed')

    def test_ephemeral_thread_cannot_pass_resume(self):
        result=self.probe('ephemeral')
        self.assertNotEqual(result['durableResume'],'passed')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_live_flag_and_exit_status(self):
        with patch('sys.argv',['verify.py','--probe-workflow-resume','synthetic-standard']), \
             patch('verify.probe_workflow_resume') as probe,patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(),0);probe.assert_not_called()
        with patch('sys.argv',['verify.py','--run-live','--probe-workflow-resume','synthetic-standard']), \
             patch('verify.probe_workflow_resume',return_value={'durableResume':'unverified'}), \
             patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(),1)
