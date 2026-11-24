"""Durable controller tool decisions only; no executor or native permissions enabled."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from modelmate import ProbeError, SessionStore, WorkflowController, validate_workflow_checkpoint
from test_routing import CATALOG, PLAN, POLICY, QUOTA


class WorkflowToolDecisionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.store = SessionStore(root, root / 'state')
        self.addCleanup(self.store.close)
        self.sid = self.store.create('synthetic tool decision',
            account_hash=hashlib.sha256(QUOTA['accountId'].encode()).hexdigest())['id']
        self.binding = dict(thread_id='thread', turn_id='turn', item_id='item', request_id=7, kind='command')
        self.digest = hashlib.sha256(b'printf synthetic').hexdigest()

    def attach(self, controller=None):
        return self.store.workflow(self.sid, QUOTA, time.monotonic(), CATALOG, POLICY, controller=controller)

    def begin(self, c):
        return c.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)['dispatch']['attempt_id']

    def test_exact_tool_decision_is_durable_single_use_and_not_model_approval(self):
        with self.attach(WorkflowController(json.dumps(PLAN), CATALOG, POLICY)) as c:
            aid = self.begin(c)
            request = c.request_tool_approval(aid, self.binding, self.digest)
            self.assertEqual(c.state, 'AWAITING_TOOL_APPROVAL')
            saved = self.store.read(self.sid)['workflow']
            self.assertEqual(saved['version'], 3)
            self.assertNotIn(request['token'], json.dumps(saved))
            self.assertNotIn('printf synthetic', json.dumps(saved))
            with self.assertRaises(ProbeError):c.answer_model(request['token'], 'approve')
            response = c.answer_tool_approval(request['token'], 'approve', self.binding, self.digest)
            self.assertEqual(response, dict(binding=self.binding, action_digest=self.digest, decision='accept'))
            self.assertEqual(self.store.read(self.sid)['workflow'], c.export_checkpoint())
            self.assertEqual(c.snapshot()['steps'][0]['attempts'], 1)
            self.assertEqual(c.snapshot()['active_attempt']['checks'], {})
            with self.assertRaises(ProbeError):
                c.answer_tool_approval(request['token'], 'approve', self.binding, self.digest)

    def test_changed_binding_or_digest_expires_confirmation_without_reviving(self):
        for field in (*self.binding, 'digest'):
            with self.subTest(field=field):
                c = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
                c._persist = lambda current: validate_workflow_checkpoint(current.export_checkpoint())
                aid = self.begin(c)
                request = c.request_tool_approval(aid, self.binding, self.digest)
                binding = dict(self.binding)
                digest = self.digest
                if field == 'digest':digest = 'b' * 64
                else:binding[field] = 'changed'
                with self.assertRaisesRegex(ProbeError, 'action changed'):
                    c.answer_tool_approval(request['token'], 'approve', binding, digest)
                with self.assertRaises(ProbeError):
                    c.answer_tool_approval(request['token'], 'approve', self.binding, self.digest)
                self.assertEqual(c.export_checkpoint()['tool_request']['status'], 'expired')

    def test_restore_expires_pending_tool_and_requires_native_reconciliation(self):
        with self.attach(WorkflowController(json.dumps(PLAN), CATALOG, POLICY)) as c:
            aid = self.begin(c)
            request = c.request_tool_approval(aid, self.binding, self.digest)
        with self.attach() as restored:
            self.assertEqual((restored.state, restored.reason), ('PAUSED', 'outcome_unknown'))
            self.assertEqual(restored.export_checkpoint()['tool_request']['status'], 'expired')
            self.assertEqual(restored.export_checkpoint()['tool_request']['binding'], self.binding)
            with self.assertRaises(ProbeError):
                restored.answer_tool_approval(request['token'], 'approve', self.binding, self.digest)
            with self.assertRaisesRegex(ProbeError, 'unknown'):
                restored.answer_pause(restored.snapshot()['pause_token'], 'continue')

    def test_pause_and_terminal_events_expire_tokens_and_never_make_checks_pass(self):
        for event in ('pause', 'completed', 'interrupted'):
            with self.subTest(event=event):
                c = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
                c._persist = lambda current: validate_workflow_checkpoint(current.export_checkpoint())
                aid = self.begin(c)
                request = c.request_tool_approval(aid, self.binding, self.digest)
                if event == 'pause':c.pause()
                else:c.finish_attempt(aid, event)
                with self.assertRaises(ProbeError):
                    c.answer_tool_approval(request['token'], 'approve', self.binding, self.digest)
                self.assertNotEqual(c.state, 'DONE')
                self.assertEqual(c.export_checkpoint()['tool_request']['status'], 'expired')

    def test_invalid_external_state_is_rejected_before_any_pending_grant(self):
        with self.attach(WorkflowController(json.dumps(PLAN), CATALOG, POLICY)) as c:
            aid = self.begin(c)
            for binding, digest in [(dict(self.binding, request_id=True), self.digest),
                                    (dict(self.binding, item_id=''), self.digest), (self.binding, 'not-a-digest')]:
                with self.assertRaises(ProbeError):c.request_tool_approval(aid, binding, digest)
                self.assertEqual(c.state, 'RUNNING')
            request = c.request_tool_approval(aid, self.binding, self.digest)
            before = c.export_checkpoint()
            for field, value in [('attempt_id', 'a' * 32), ('status', 'approved')]:
                invalid = copy.deepcopy(before)
                invalid['tool_request'][field] = value
                with self.assertRaises(ProbeError):validate_workflow_checkpoint(invalid)
            with self.assertRaises(ProbeError):
                c.answer_tool_approval(request['token'], 'yes', self.binding, self.digest)
            self.assertEqual(c.export_checkpoint(), before)

    def test_persistence_failure_never_returns_an_accept_and_freezes_further_work(self):
        with self.attach(WorkflowController(json.dumps(PLAN), CATALOG, POLICY)) as c:
            aid = self.begin(c)
            request = c.request_tool_approval(aid, self.binding, self.digest)
            with patch.object(self.store, 'save', side_effect=OSError('synthetic write failure')):
                with self.assertRaises(OSError):
                    c.answer_tool_approval(request['token'], 'approve', self.binding, self.digest)
            with self.assertRaises(ProbeError):
                c.answer_tool_approval(request['token'], 'approve', self.binding, self.digest)
            with self.assertRaises(ProbeError):c.request_tool_approval(aid, self.binding, self.digest)
        with self.attach() as restored:
            self.assertEqual(restored.export_checkpoint()['tool_request']['status'], 'expired')

    def test_decline_and_pause_persist_before_returning_a_decline_descriptor(self):
        for choice in ('decline', 'pause'):
            with self.subTest(choice=choice):
                saved = []
                c = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
                c._persist = lambda current: saved.append(validate_workflow_checkpoint(current.export_checkpoint()))
                aid = self.begin(c)
                request = c.request_tool_approval(aid, self.binding, self.digest)
                response = c.answer_tool_approval(request['token'], choice, self.binding, self.digest)
                self.assertEqual(response['decision'], 'decline')
                self.assertEqual(saved[-1]['tool_request']['status'], 'declined')
                self.assertEqual(saved[-1]['state'], 'PAUSED' if choice == 'pause' else 'RUNNING')
                self.assertEqual(saved[-1]['active_attempt']['checks'], [])

    def test_tool_schema_preserves_source_attempt_and_recheck_ledger(self):
        with self.attach(WorkflowController(json.dumps(PLAN), CATALOG, POLICY)) as c:
            aid = self.begin(c)
            request = c.request_tool_approval(aid, self.binding, self.digest)
            c.answer_tool_approval(request['token'], 'approve', self.binding, self.digest)
            c.finish_attempt(aid, 'completed')
            evidence = c.record_check(aid, 0, origin='tool', exit_code=0,
                reference='synthetic native observation', finding='observed exit')
            c.evaluate_attempt(aid)
        with self.attach() as restored:
            with self.assertRaises(ProbeError):
                restored.answer_tool_approval(request['token'], 'approve', self.binding, self.digest)
            restored.reserve_recheck(evidence['id'], 'printf synthetic', str(self.store.project),
                {'model': POLICY['standard'], 'effort': 'low'}, QUOTA, time.monotonic(), CATALOG, POLICY)
            saved = self.store.read(self.sid)['workflow']
            self.assertEqual(saved['version'], 3)
            self.assertEqual(saved['tool_request']['status'], 'approved')
            self.assertEqual(saved['tool_request']['attempt_id'], aid)
            self.assertEqual(len(saved['rechecks']), 1)

    def test_uncertain_request_write_exposes_no_token_and_retains_unknown_attempt(self):
        with self.attach(WorkflowController(json.dumps(PLAN), CATALOG, POLICY)) as c:
            aid = self.begin(c)
            save = self.store.save
            def uncertain(record):
                save(record)
                raise OSError('synthetic failure after replacement')
            with patch.object(self.store, 'save', side_effect=uncertain):
                with self.assertRaises(OSError):c.request_tool_approval(aid, self.binding, self.digest)
            self.assertIsNone(c._tool_token)
            with self.assertRaises(ProbeError):c.request_tool_approval(aid, self.binding, self.digest)
        with self.attach() as restored:
            self.assertEqual(restored.reason, 'outcome_unknown')
            self.assertEqual(restored.export_checkpoint()['tool_request']['status'], 'expired')
