"""Metadata-only recovery probe uses a disposable copy, never original session writes."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from modelmate import SessionStore, WorkflowController, RecheckRecoveryConnection
from test_routing import PLAN, CATALOG, POLICY, QUOTA
from test_recheck_recovery import SERVER
from verify import probe_recheck_recovery, RECOVERY_PROBE_KEYS, main


class RecoveryProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.project=self.source/'project';self.project.mkdir()
        (self.project/'sentinel.txt').write_text('synthetic sentinel\n')
        self.store=SessionStore(self.project,self.source/'state');self.addCleanup(self.store.close)
        record=self.store.create('Synthetic durable tool recheck verification',thread_id='work-thread',
            account_hash=hashlib.sha256(QUOTA['accountId'].encode()).hexdigest())
        self.sid=record['id']
        plan=copy.deepcopy(PLAN);plan['goal']=record['goal']
        with self.store.workflow(self.sid,QUOTA,time.monotonic(),CATALOG,POLICY,
                controller=WorkflowController(json.dumps(plan),CATALOG,POLICY)) as c:
            aid=c.request_attempt(QUOTA,time.monotonic(),CATALOG,POLICY)['dispatch']['attempt_id']
            c.finish_attempt(aid,'completed')
            evidence=c.record_check(aid,0,origin='tool',exit_code=0,reference='synthetic',finding='observed')
            c.evaluate_attempt(aid);c.finish_task({0:[evidence['id']]})
        with self.store.workflow(self.sid,QUOTA,time.monotonic(),CATALOG,POLICY) as c:
            op=c.reserve_recheck(evidence['id'],'printf synthetic',str(self.project),
                {'model':'synthetic-standard','effort':'low'},QUOTA,time.monotonic(),CATALOG,POLICY)
            c.advance_recheck(op['id'],'thread',thread_id='check-thread')
            self.marker = str(uuid.UUID(hex=op['id']))
            c.advance_recheck(op['id'],'turn_reserved', client_message_id=self.marker)
            c.advance_recheck(op['id'],'turn',turn_id='check-turn')
            c.advance_recheck(op['id'],'finish',status='completed',exit_code=0,item_id='check-item')
            c.finish_task({0:[evidence['id']]})
        self.path=self.store.directory/(self.sid+'.json')
        self.original=self.path.read_bytes()
        self.copy=self.root/'copy';self.copy.mkdir()
        self.trace=self.root/'trace'

    def probe(self,mode='complete', *, lost_binding=False):
        def factory(command,timeout):
            return RecheckRecoveryConnection(
                [sys.executable,'-u','-c',SERVER,str(self.trace),str(self.project),mode,self.marker],timeout)
        with patch('verify.RecheckRecoveryConnection',new=factory), \
             patch('verify.tempfile.mkdtemp',return_value=str(self.copy)), \
             patch('sys.stderr',new_callable=io.StringIO):
            result=probe_recheck_recovery(self.source,1,lost_binding=lost_binding)
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertNotIn(str(self.source),json.dumps(result))
        self.assertNotIn('check-thread',json.dumps(result))
        self.assertNotIn('check-turn',json.dumps(result))
        return result

    def records(self):return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def test_completed_native_binding_recovers_only_copy_and_cleans_copy(self):
        result=self.probe()
        for key in RECOVERY_PROBE_KEYS:self.assertEqual(result[key],'passed',(key,result))
        self.assertEqual(result['modelTurnsRequested'],0)
        self.assertFalse(result['nativeThreadsDeleted'])
        self.assertFalse(result['copyRetained']);self.assertFalse(self.copy.exists())
        self.assertTrue(self.source.exists())
        self.assertEqual({r['method'] for r in self.records()},
                         {'initialize','initialized','account/read','account/rateLimits/read','thread/read','thread/turns/list'})

    def test_active_native_turn_is_never_interrupted_by_probe(self):
        result=self.probe('active')
        self.assertEqual(result['nativeTerminalObserved'],'unverified')
        self.assertEqual(result['nativeObservationReason'],'active')
        self.assertEqual(result['sourceUnchanged'],'passed')
        self.assertTrue(result['copyRetained']);self.assertTrue(self.copy.exists())
        self.assertFalse(any(r.get('method')=='turn/interrupt' for r in self.records()))

    def test_lost_binding_copy_recovers_through_full_history(self):
        result = self.probe(lost_binding=True)
        self.assertTrue(all(result[key] == 'passed' for key in RECOVERY_PROBE_KEYS), result)
        reads = [r['params']['itemsView'] for r in self.records() if r['method'] == 'thread/turns/list']
        self.assertEqual(reads, ['full', 'summary'])
        self.assertFalse(any(r['method'] in ('turn/start', 'turn/interrupt') for r in self.records()))

    def test_history_mismatch_does_not_reconcile_or_guess(self):
        result=self.probe('turn_id')
        self.assertNotEqual(result['metadataReconciled'],'passed')
        self.assertEqual(result['nativeObservationReason'],'native_history_mismatch')

    def test_exhausted_model_quota_does_not_require_new_inference(self):
        result=self.probe('exhausted')
        self.assertTrue(all(result[key]=='passed' for key in RECOVERY_PROBE_KEYS))
        self.assertFalse(any(r.get('method') in ('model/list','turn/start','thread/start') for r in self.records()))

    def test_incomplete_source_is_rejected_before_native_connection(self):
        with self.store.edit(self.sid) as record:
            record['state']=record['workflow']['state']='UNVERIFIED'
            record['workflow']['reason']='not_completed'
        with patch('verify.RecheckRecoveryConnection') as native:
            result=probe_recheck_recovery(self.source,1)
        self.assertNotEqual(result['nativeTerminalObserved'],'passed')
        self.assertEqual(result['phase'],'source_validation')
        native.assert_not_called()

    def test_cli_metadata_mode_runs_without_live_flag_and_rejects_live_flag(self):
        passed=dict.fromkeys(RECOVERY_PROBE_KEYS,'passed')
        with patch('sys.argv',['verify.py','--probe-recheck-recovery',str(self.source)]), \
             patch('sys.stdout',new_callable=io.StringIO),patch('verify.probe_recheck_recovery',return_value=passed) as probe:
            self.assertEqual(main(),0);probe.assert_called_once()
        with patch('sys.argv',['verify.py','--run-live','--probe-recheck-recovery',str(self.source)]), \
             patch('sys.stderr',new_callable=io.StringIO),patch('verify.probe_recheck_recovery') as probe:
            with self.assertRaises(SystemExit) as error:main()
            self.assertEqual(error.exception.code,2);probe.assert_not_called()


if __name__=='__main__':unittest.main()
