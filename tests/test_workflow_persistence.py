"""Durable offline workflow state; these tests do not call a real model or tool adapter."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import (ProbeError, SessionStore, WorkflowController, validate_workflow_checkpoint,
                       LiveChatConnection, ChatShell)
from test_routing import CATALOG, PLAN, POLICY, QUOTA


class WorkflowPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'งาน มีช่องว่าง';self.project.mkdir()
        self.home = self.base / 'state'
        self.store = SessionStore(self.project, self.home);self.addCleanup(self.store.close)
        self.account_hash = hashlib.sha256(QUOTA['accountId'].encode()).hexdigest()
        self.record = self.store.create('workflow', thread_id='synthetic-thread', account_hash=self.account_hash)
        self.sid = self.record['id']
        self.path = self.store.directory / (self.sid + '.json')

    def new(self, plan=None, mode='ask_to_escalate'):
        return WorkflowController(json.dumps(plan or PLAN), CATALOG, POLICY, mode)

    def attached(self, controller=None, quota=None):
        return self.store.workflow(self.sid, QUOTA if quota is None else quota, time.monotonic(),
                                   CATALOG, POLICY, controller=controller)

    def begin(self, c):
        return c.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)

    def check(self, c, code=0):
        aid = self.begin(c)['dispatch']['attempt_id']
        c.finish_attempt(aid, 'completed')
        evidence = c.record_check(aid, 0, origin='tool', exit_code=code,
                                  reference='synthetic host check', finding='observed exit status')
        return c.evaluate_attempt(aid), evidence

    def continue_paused(self, c):
        state = c.snapshot()
        return c.answer_pause(state['pause_token'], 'continue')

    def test_every_transition_is_saved_and_corrections_resume_without_reset(self):
        c = self.new()
        with self.attached(c):
            self.check(c, 1)
            saved = self.store.read(self.sid)
            self.assertEqual(saved['version'], 3)
            self.assertEqual(saved['correction_count'], 0)
            self.assertEqual(saved['workflow']['steps'][0]['attempts'], 1)
            self.check(c, 1)
        with self.attached() as resumed:
            state = resumed.snapshot()
            self.assertEqual(state['state'], 'PAUSED')
            self.assertEqual(state['steps'][0]['attempts'], 2)
            self.assertEqual(state['steps'][0]['id'], c.snapshot()['steps'][0]['id'])
            self.assertNotIn('dispatch', self.begin(resumed))
            self.continue_paused(resumed)
            paused, _ = self.check(resumed, 1)
            self.assertEqual(paused['reason'], 'correction_limit')
            self.assertEqual(self.store.read(self.sid)['correction_count'], 2)
        with self.attached() as again:
            self.assertEqual(again.snapshot()['reason'], 'correction_limit')
            self.assertEqual(len(again.snapshot()['history']), len(paused['history']))
            self.assertNotIn('dispatch', self.begin(again))

    def test_saved_budget_extensions_and_user_choices_round_trip(self):
        with self.attached(self.new()) as c:
            for _ in range(3):self.check(c, 1)
            self.continue_paused(c)
            self.check(c, 1)
        with self.attached() as restored:
            step = restored.snapshot()['steps'][0]
            self.assertEqual((step['cycle'], step['attempts']), (1, 1))
            self.assertTrue(any(e.get('kind') == 'budget_extension' for e in restored.snapshot()['history']))
            self.assertTrue(any(e.get('kind') == 'user_choice' for e in restored.snapshot()['history']))

    def test_running_crash_checkpoint_blocks_replay_until_terminal_event(self):
        with self.attached(self.new()) as c:
            aid = self.begin(c)['dispatch']['attempt_id']
            checkpoint = self.store.read(self.sid)['workflow']
            self.assertEqual(checkpoint['active_attempt']['id'], aid)
        with self.attached() as restored:
            self.assertEqual(restored.snapshot()['reason'], 'outcome_unknown')
            self.assertEqual(restored.snapshot()['active_attempt']['id'], aid)
            with self.assertRaisesRegex(ProbeError, 'unknown'):self.continue_paused(restored)
            self.assertNotIn('dispatch', self.begin(restored))
            stopped = restored.finish_attempt(aid, 'interrupted')
            self.assertEqual(stopped['steps'][0]['attempts'], 1)
            self.continue_paused(restored)
            self.assertEqual(self.begin(restored)['active_attempt']['number'], 2)

    def test_partial_checks_survive_without_reexecuting_completed_model_turn(self):
        plan = copy.deepcopy(PLAN);plan['steps'][0]['checks'] *= 2
        with self.attached(self.new(plan)) as c:
            aid = self.begin(c)['dispatch']['attempt_id'];c.finish_attempt(aid, 'completed')
            original = c.record_check(aid, 1, origin='tool', exit_code=0, reference='check', finding='passed')
        with self.attached() as restored:
            self.continue_paused(restored)
            self.assertEqual(restored.snapshot()['state'], 'CHECKING')
            self.assertEqual(restored.snapshot()['active_attempt']['checks'][1]['id'], original['id'])
            self.assertNotIn('dispatch', self.begin(restored))
            restored.record_check(aid, 0, origin='tool', exit_code=0, reference='check', finding='passed')
            restored.evaluate_attempt(aid)
        with self.attached() as last:
            self.assertEqual(last.snapshot()['step_index'], 1)
            self.assertEqual(len(last.snapshot()['steps'][0]['evidence']), 2)

    def test_done_restores_as_unverified_and_retains_coverage_and_evidence(self):
        with self.attached(self.new()) as c:
            _, evidence = self.check(c)
            c.finish_task({0: [evidence['id']]})
        with self.attached() as restored:
            state = restored.snapshot()
            self.assertEqual(state['state'], 'UNVERIFIED')
            self.assertEqual(state['reason'], 'restored_result_unverified')
            self.assertEqual(state['criterion_evidence'], {0: [evidence['id']]})
            self.assertEqual(state['history'][0]['checks'][0]['id'], evidence['id'])

    def test_model_grants_tokens_and_raw_account_id_never_persist(self):
        plan = copy.deepcopy(PLAN);plan['steps'][0]['role'] = 'strong'
        with self.attached(self.new(plan, 'approve_plan')) as c:
            request = self.begin(c)
            old = request['model_request']['token']
            c.answer_model(old, 'approve')
        payload = self.path.read_text()
        self.assertNotIn(old, payload)
        self.assertNotIn('pause_token', payload)
        self.assertNotIn('model_request', payload)
        self.assertNotIn('grants', payload)
        self.assertNotIn(json.dumps(QUOTA['accountId']), payload)
        with self.attached() as restored:
            with self.assertRaises(ProbeError):restored.answer_model(old, 'approve')
            self.continue_paused(restored)
            fresh = self.begin(restored)
            self.assertEqual(fresh['state'], 'AWAITING_MODEL_APPROVAL')
            self.assertNotEqual(fresh['model_request']['token'], old)

    def test_unknown_quota_or_wrong_account_leaves_checkpoint_untouched(self):
        with self.attached(self.new()):pass
        before = self.path.read_bytes()
        for quota in ({}, dict(QUOTA, accountId='different'), dict(QUOTA, ordinaryUsageAllowed=False)):
            with self.assertRaises(ProbeError):
                with self.attached(quota=quota):self.fail('must not restore')
            self.assertEqual(self.path.read_bytes(), before)

    def test_corrupt_unknown_version_or_inconsistent_counters_are_not_overwritten(self):
        with self.attached(self.new()) as c:self.check(c, 1)
        good = json.loads(self.path.read_text())
        cases = [b'broken JSON']
        for change in ('version', 'attempts', 'id', 'evidence', 'grant'):
            record = copy.deepcopy(good)
            if change == 'version':record['workflow']['version'] = 2
            elif change == 'attempts':record['workflow']['steps'][0]['attempts'] = 0
            elif change == 'id':record['workflow']['history'][0]['step_id'] = '0' * 32
            elif change == 'evidence':record['workflow']['history'][0]['checks'][0]['result'] = 'pass'
            else:record['workflow']['grants'] = ['approve']
            cases.append(json.dumps(record).encode())
        for payload in cases:
            self.path.write_bytes(payload)
            with self.assertRaises(ProbeError):
                with self.attached():self.fail('corruption must not reach controller')
            self.assertEqual(self.path.read_bytes(), payload)

    def test_disk_failure_before_dispatch_returns_no_descriptor_and_keeps_old_checkpoint(self):
        with self.attached(self.new()) as c:
            before = self.path.read_bytes()
            with patch('modelmate.os.replace', side_effect=OSError('synthetic full disk')):
                with self.assertRaises(OSError):self.begin(c)
            self.assertEqual(self.path.read_bytes(), before)
        with self.attached() as restored:
            self.assertEqual(restored.snapshot()['steps'][0]['attempts'], 0)

    def test_second_writer_is_rejected_and_closed_attachment_cannot_dispatch(self):
        c = self.new()
        with self.attached(c):
            with self.assertRaisesRegex(ProbeError, 'another writer'):
                with self.attached():self.fail('second writer')
        with self.assertRaisesRegex(ProbeError, 'closed'):self.begin(c)

    def test_task_replacement_and_older_active_checkpoint_cannot_reset_budget(self):
        with self.attached(self.new()) as c:
            old = c.export_checkpoint()
            self.begin(c)
            with self.assertRaisesRegex(ProbeError, 'replace'):
                self.store.save_workflow(self.sid, self.new())
            stale = WorkflowController.restore_checkpoint(old, QUOTA, time.monotonic(), CATALOG, POLICY)
            with self.assertRaisesRegex(ProbeError, 'discard'):
                self.store.save_workflow(self.sid, stale)

    def test_real_process_death_before_and_after_check_keeps_counter_and_releases_lock(self):
        fixture = self.base / 'fixture.json';fixture.write_text(json.dumps({'plan': PLAN, 'catalog': CATALOG, 'policy': POLICY, 'quota': QUOTA}))
        source = '''import json,os,sys,time
from modelmate import SessionStore,WorkflowController
x=json.load(open(sys.argv[4]))
with SessionStore(sys.argv[1],sys.argv[2]) as store:
 c=WorkflowController(json.dumps(x['plan']),x['catalog'],x['policy'])
 with store.workflow(sys.argv[3],x['quota'],time.monotonic(),x['catalog'],x['policy'],controller=c):
  aid=c.request_attempt(x['quota'],time.monotonic(),x['catalog'],x['policy'])['dispatch']['attempt_id']
  if sys.argv[5]=='after_check':
   c.finish_attempt(aid,'completed')
   c.record_check(aid,0,origin='tool',exit_code=0,reference='synthetic check',finding='observed result')
  os._exit(23)
'''
        for phase in ('reserved', 'after_check'):
            with self.subTest(phase=phase):
                sid = self.store.create('crash checkpoint', account_hash=self.account_hash)['id']
                result = subprocess.run([sys.executable, '-c', source, str(self.project), str(self.home), sid, str(fixture), phase], timeout=5)
                self.assertEqual(result.returncode, 23)
                with self.store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY) as restored:
                    state = restored.snapshot()
                    self.assertEqual(state['steps'][0]['attempts'], 1)
                    self.assertEqual(state['reason'], 'outcome_unknown' if phase == 'reserved' else 'user_pause')
                    self.assertEqual(len(state['active_attempt']['checks']), 0 if phase == 'reserved' else 1)
                    self.assertNotIn('dispatch', self.begin(restored))

    def test_future_schema_and_manual_v1_v2_records_remain_supported_without_migration(self):
        legacy = self.store.create('legacy')
        before = self.path.read_bytes()
        self.assertEqual(self.store.read(legacy['id'])['version'], 1)
        self.assertEqual(self.store.read(self.sid)['version'], 2)
        self.assertEqual(self.path.read_bytes(), before)
        invalid = dict(self.record, version=4);self.path.write_text(json.dumps(invalid))
        with self.assertRaises(ProbeError):self.store.read(self.sid)

    def test_export_is_json_round_trip_and_limits_fail_closed(self):
        c = self.new();self.check(c, 1)
        exported = json.loads(json.dumps(c.export_checkpoint()))
        self.assertEqual(validate_workflow_checkpoint(exported), exported)
        oversized = copy.deepcopy(exported);oversized['history'] = exported['history'] * 5000
        with self.assertRaises(ProbeError):validate_workflow_checkpoint(oversized)

    def test_failed_extension_save_cannot_reset_budget_on_disk(self):
        with self.attached(self.new()) as c:
            for _ in range(3):self.check(c, 1)
            before = self.path.read_bytes()
            with patch('modelmate.os.replace', side_effect=OSError('synthetic full disk')):
                with self.assertRaises(OSError):self.continue_paused(c)
            self.assertEqual(self.path.read_bytes(), before)
        with self.attached() as restored:
            self.assertEqual(restored.snapshot()['reason'], 'correction_limit')
            self.assertEqual(restored.snapshot()['steps'][0]['attempts'], 3)
            self.assertEqual(restored.snapshot()['steps'][0]['cycle'], 0)

    def test_saved_baseline_is_preserved_and_missing_baseline_cannot_restore(self):
        with self.attached(self.new()) as c:baseline = c.export_checkpoint()['baseline']
        with self.attached() as restored:self.assertEqual(restored.export_checkpoint()['baseline'], baseline)
        before = self.path.read_bytes()
        with self.assertRaises(ProbeError):
            with self.store.workflow(self.sid, QUOTA, time.monotonic(), [], POLICY):self.fail('missing baseline')
        self.assertEqual(self.path.read_bytes(), before)

    def test_session_mirror_and_budget_extension_tampering_are_rejected(self):
        with self.attached(self.new()) as c:
            for _ in range(3):self.check(c, 1)
            self.continue_paused(c)
        good = json.loads(self.path.read_text())
        variants = []
        record = copy.deepcopy(good);record['correction_count'] = 2;variants.append(record)
        record = copy.deepcopy(good);record['workflow']['history'][-2]['choice'] = 'pause';variants.append(record)
        record = copy.deepcopy(good);record['workflow']['history'][-1]['cycle'] = True;variants.append(record)
        for record in variants:
            payload = json.dumps(record).encode();self.path.write_bytes(payload)
            with self.assertRaises(ProbeError):self.store.read(self.sid)
            self.assertEqual(self.path.read_bytes(), payload)

    def live_backend(self):
        c = LiveChatConnection([sys.executable, '-c', 'import time;time.sleep(30)'], 1)
        self.addCleanup(c.close)
        c.store = self.store;c.cwd = str(self.project)
        c.selection = {'model': POLICY['standard'], 'effort': 'low'}
        c.shell = ChatShell(io.StringIO(), c.action, CATALOG)
        c.shell.sessions = c.session_command
        c.request = Mock()
        return c

    def test_manual_chat_cannot_resume_workflow_checkpoint_or_reset_its_state(self):
        with self.attached(self.new()) as c:self.check(c, 1)
        before = self.path.read_bytes()
        backend = self.live_backend()
        quota = {'state': 'allow', 'reason': 'included_usage_available', 'checked_at': time.monotonic(),
                 'account_id': QUOTA['accountId']}
        with patch('modelmate.refresh_quota', return_value=quota), patch('modelmate.read_models', return_value=CATALOG):
            with self.assertRaisesRegex(ProbeError, 'controller'):backend.open_session(self.sid)
        backend.request.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_workflow_metadata_still_supports_explicit_confirmed_deletion(self):
        with self.attached(self.new()):pass
        backend = self.live_backend()
        thread = {'id': 'synthetic-thread', 'cwd': str(self.project), 'ephemeral': False,
                  'modelProvider': 'openai', 'status': {'type': 'idle'}, 'parentThreadId': None}
        def reply(method, params):
            if method == 'thread/read':return {'thread': thread}
            if method == 'thread/list':return {'data': [thread], 'nextCursor': None}
            if method == 'thread/delete':return {}
            raise AssertionError(method)
        backend.request.side_effect = reply
        quota = {'state': 'allow', 'reason': 'included_usage_available', 'checked_at': time.monotonic(),
                 'account_id': QUOTA['accountId']}
        with patch('modelmate.refresh_quota', return_value=quota):
            backend.shell.line('/delete ' + self.sid)
            backend.shell.line('/confirm-delete ' + backend.delete_proposal['token'])
        self.assertFalse(self.path.exists())
        self.assertEqual(sum(call.args[0] == 'thread/delete' for call in backend.request.call_args_list), 1)

    def test_history_truncation_and_stale_evidence_rollback_are_rejected(self):
        with self.attached(self.new()) as c:
            first = c.export_checkpoint()
            self.check(c, 1)
            stale = WorkflowController.restore_checkpoint(first, QUOTA, time.monotonic(), CATALOG, POLICY)
            with self.assertRaisesRegex(ProbeError, 'ledger'):self.store.save_workflow(self.sid, stale)
            aid = self.begin(c)['dispatch']['attempt_id'];c.finish_attempt(aid, 'completed')
            before_check = c.export_checkpoint()
            c.record_check(aid, 0, origin='tool', exit_code=0, reference='check', finding='passed')
            stale = WorkflowController.restore_checkpoint(before_check, QUOTA, time.monotonic(), CATALOG, POLICY)
            with self.assertRaisesRegex(ProbeError, 'evidence'):self.store.save_workflow(self.sid, stale)

    def test_pending_model_and_pause_tokens_are_fresh_after_restart(self):
        plan = copy.deepcopy(PLAN);plan['steps'][0]['role'] = 'strong'
        with self.attached(self.new(plan)) as c:
            old = self.begin(c)['model_request']['token']
        with self.attached() as restored:
            with self.assertRaises(ProbeError):restored.answer_model(old, 'approve')
            pause_token = restored.snapshot()['pause_token']
        with self.attached() as restored:
            self.assertNotEqual(restored.snapshot()['pause_token'], pause_token)
            with self.assertRaises(ProbeError):restored.answer_pause(pause_token, 'continue')
            self.continue_paused(restored)
            fresh = self.begin(restored)
            self.assertEqual(fresh['state'], 'AWAITING_MODEL_APPROVAL')
            self.assertNotEqual(fresh['model_request']['token'], old)

    def test_existing_task_cannot_be_rewritten_with_new_criteria_ids_or_baseline(self):
        with self.attached(self.new()) as c:
            data = c.export_checkpoint()
            before = self.path.read_bytes()
            for field in ('plan', 'steps', 'baseline'):
                changed = copy.deepcopy(data)
                if field == 'plan':
                    plan = json.loads(changed['plan']);plan['success_criteria'] = ['easier criterion']
                    changed['plan'] = json.dumps(plan)
                elif field == 'steps':changed['steps'][0]['id'] = '0' * 32
                else:changed['baseline']['model'] = POLICY['economy']
                stale = WorkflowController.restore_checkpoint(changed, QUOTA, time.monotonic(), CATALOG, POLICY)
                with self.assertRaises(ProbeError):self.store.save_workflow(self.sid, stale)
                self.assertEqual(self.path.read_bytes(), before)

    def test_multiple_steps_sources_and_terminal_phases_validate_after_json_roundtrip(self):
        plan = copy.deepcopy(PLAN)
        plan['steps'] = [dict(copy.deepcopy(PLAN['steps'][0]), kind=kind) for kind in ('plan', 'implement', 'review')]
        plan['steps'][-1]['checks'] = [{'kind': 'source', 'criterion': 'source supports claim'}]
        with self.attached(self.new(plan)) as c:
            self.check(c);self.check(c)
            aid = self.begin(c)['dispatch']['attempt_id'];c.finish_attempt(aid, 'completed')
            evidence = c.record_check(aid, 0, origin='source', result='pass', reference='https://example.org', finding='host verified claim')
            c.evaluate_attempt(aid);c.finish_task({0: [evidence['id']]})
        with self.attached() as restored:
            self.assertEqual(restored.snapshot()['step_index'], 3)
            self.assertTrue(all(s['state'] == 'DONE' for s in restored.snapshot()['steps']))
        for state in ('CLARIFYING', 'FAILED'):
            current_plan = copy.deepcopy(PLAN)
            if state == 'CLARIFYING':current_plan['clarifications'] = ['Which scope?']
            sid = self.store.create('terminal phase', account_hash=self.account_hash)['id']
            with self.store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY, controller=self.new(current_plan)) as c:
                if state == 'FAILED':c.finish_attempt(self.begin(c)['dispatch']['attempt_id'], 'failed')
            with self.store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY) as restored:
                self.assertEqual(restored.snapshot()['state'], state)

    def test_new_workflow_cannot_overwrite_unknown_manual_session_outcome(self):
        with self.store.edit(self.sid) as record:record['state'] = 'RUNNING'
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ProbeError, 'Reconcile'):
            with self.attached(self.new()):self.fail('unknown existing native turn')
        self.assertEqual(self.path.read_bytes(), before)

    def test_completed_attempt_cannot_be_rolled_back_to_running(self):
        with self.attached(self.new()) as c:
            aid = self.begin(c)['dispatch']['attempt_id']
            running = c.export_checkpoint()
            c.finish_attempt(aid, 'completed')
            before = self.path.read_bytes()
            old = WorkflowController.restore_checkpoint(running, QUOTA, time.monotonic(), CATALOG, POLICY)
            with self.assertRaisesRegex(ProbeError, 'active attempt'):self.store.save_workflow(self.sid, old)
            self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
