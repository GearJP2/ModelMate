"""Two fake processes verify the opt-in resume harness without spending quota."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from modelmate import ChatShell, WorkflowController
from verify import WorkflowVerificationConnection, probe_workflow_resume, main
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
