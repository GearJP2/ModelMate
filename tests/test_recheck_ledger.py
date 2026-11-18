"""Durable recheck state only: no native/model dispatch or permission certification."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from modelmate import (ProbeError, SessionStore, WorkflowController,
                       validate_workflow_checkpoint, workflow_statistics)
from test_routing import CATALOG, PLAN, POLICY, QUOTA


class RecheckLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / 'project'
        self.project.mkdir()
        self.store = SessionStore(self.project, root / 'state')
        self.addCleanup(self.store.close)
        record = self.store.create('recheck fixture', thread_id='work-thread',
            account_hash=hashlib.sha256(QUOTA['accountId'].encode()).hexdigest())
        self.sid = record['id']
        controller = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
        with self.attach(controller) as controller:
            aid = controller.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)['dispatch']['attempt_id']
            controller.finish_attempt(aid, 'completed')
            self.evidence = controller.record_check(aid, 0, origin='tool', exit_code=0,
                reference='synthetic observation', finding='observed success')
            controller.evaluate_attempt(aid)
            record = self.store.read(self.sid)
            record['turn_id'] = 'work-turn'
            self.store.save(record)
        self.original = self.store.read(self.sid)

    def attach(self, controller=None):
        return self.store.workflow(self.sid, QUOTA, time.monotonic(), CATALOG, POLICY, controller=controller)

    def reserve(self, controller, **kwargs):
        options = dict(evidence_id=self.evidence['id'], command='printf synthetic', cwd=str(self.project),
            selection={'model': 'synthetic-standard', 'effort': 'low'}, quota=QUOTA,
            checked_at=time.monotonic(), catalog=CATALOG, role_policy=POLICY)
        options.update(kwargs)
        return controller.reserve_recheck(**options)

    def bind(self, controller, operation):
        identity = operation['id']
        controller.advance_recheck(identity, 'thread', thread_id='recheck-' + identity)
        controller.advance_recheck(identity, 'turn_reserved')
        controller.advance_recheck(identity, 'turn', turn_id='turn-' + identity)

    def finish(self, controller, operation, code):
        self.bind(controller, operation)
        return controller.advance_recheck(operation['id'], 'finish', status='completed',
            exit_code=code, item_id='check-item')

    def test_reservation_is_durable_private_and_does_not_reset_or_rebind_work(self):
        with self.attach() as controller:
            operation = self.reserve(controller)
            record = self.store.read(self.sid)
            self.assertEqual(record['workflow']['version'], 2)
            self.assertEqual(record['workflow']['rechecks'][0]['id'], operation['id'])
            self.assertNotIn('printf synthetic', json.dumps(record['workflow']['rechecks']))
            self.assertNotIn(str(self.project), json.dumps(record['workflow']['rechecks']))
            self.assertEqual(record['turn_id'], 'work-turn')
            self.assertEqual(record['thread_id'], 'work-thread')
            self.assertEqual(record['workflow']['steps'], self.original['workflow']['steps'])
            self.assertEqual(record['workflow']['history'], self.original['workflow']['history'])
            self.assertEqual(record['workflow']['criterion_evidence'], self.original['workflow']['criterion_evidence'])
            with self.assertRaisesRegex(ProbeError, 'unresolved'):
                self.reserve(controller, command='different command')

    def test_phase_reservations_must_precede_bindings_and_terminal_results(self):
        with self.attach() as controller:
            operation = self.reserve(controller)
            before = controller.export_checkpoint()
            for kind, options in [('turn', {'turn_id': 'foreign'}),
                                  ('finish', {'status': 'completed', 'exit_code': 0, 'item_id': 'fake'})]:
                with self.subTest(kind=kind), self.assertRaises(ProbeError):
                    controller.advance_recheck(operation['id'], kind, **options)
                self.assertEqual(controller.export_checkpoint(), before)
            self.finish(controller, operation, 0)
            self.assertNotIn(self.evidence['id'], controller.snapshot()['stale_evidence'])
            with self.assertRaises(ProbeError):
                controller.advance_recheck(operation['id'], 'finish', status='completed', exit_code=0, item_id='again')

    def test_saved_completed_rechecks_are_not_current_after_another_restore(self):
        with self.attach() as controller:
            self.finish(controller, self.reserve(controller), 0)
        with self.attach() as controller:
            self.assertIn(self.evidence['id'], controller.snapshot()['stale_evidence'])
            self.assertEqual(controller.recheck_operations()[0]['status'], 'completed')
            self.assertEqual(controller.snapshot()['steps'][0]['attempts'], 1)

    def test_mismatches_keep_stale_and_budget_survives_model_and_command_changes(self):
        for number in range(1, 4):
            with self.attach() as controller:
                policy = dict(POLICY, standard='synthetic-economy') if number == 2 else POLICY
                operation = self.reserve(controller, command='printf attempt' + str(number),
                    role_policy=policy, selection={'model': policy['standard'], 'effort': 'low'})
                self.assertEqual(operation['number'], number)
                self.finish(controller, operation, 1)
                self.assertIn(self.evidence['id'], controller.snapshot()['stale_evidence'])
        with self.attach() as controller:
            with self.assertRaisesRegex(ProbeError, 'limit'):
                self.reserve(controller)
            controller.answer_recheck_limit(self.evidence['id'], 'pause')
            with self.assertRaisesRegex(ProbeError, 'limit'):
                self.reserve(controller)
            controller.answer_recheck_limit(self.evidence['id'], 'continue')
            operation = self.reserve(controller)
            self.assertEqual((operation['cycle'], operation['number']), (1, 1))
            self.assertEqual(controller.snapshot()['steps'][0]['attempts'], 1)

    def test_unknown_result_blocks_new_rechecks_and_work_across_reconnect(self):
        with self.attach() as controller:
            operation = self.reserve(controller)
            self.bind(controller, operation)
            controller.advance_recheck(operation['id'], 'finish', status='unknown', exit_code=None, item_id=None)
        with self.attach() as controller:
            with self.assertRaisesRegex(ProbeError, 'unresolved'):
                self.reserve(controller)
            with self.assertRaisesRegex(ProbeError, 'recheck'):
                controller.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)
            controller.advance_recheck(operation['id'], 'finish', status='completed', exit_code=0, item_id='historical')
            self.assertIn(self.evidence['id'], controller.snapshot()['stale_evidence'])

    def test_reconciling_unknown_in_same_process_does_not_make_old_observation_current(self):
        with self.attach() as controller:
            operation = self.reserve(controller)
            self.bind(controller, operation)
            controller.advance_recheck(operation['id'], 'finish', status='unknown', exit_code=None, item_id=None)
            controller.advance_recheck(operation['id'], 'finish', status='completed', exit_code=0, item_id='old-item')
            self.assertIn(self.evidence['id'], controller.snapshot()['stale_evidence'])

    def test_unresolved_recheck_cannot_be_hidden_by_manually_revalidating_old_evidence(self):
        with self.attach() as controller:
            self.reserve(controller)
            controller.revalidate_check(self.evidence['id'], origin='tool', exit_code=0,
                reference='synthetic other host', finding='synthetic explicit observation')
            with self.assertRaisesRegex(ProbeError, 'Unresolved'):
                controller.finish_task({0: [self.evidence['id']]})

    def test_save_failure_freezes_controller_and_persisted_reservation_cannot_replay(self):
        with self.attach() as controller:
            original_save = self.store.save
            def uncertain_save(record):
                original_save(record)
                raise OSError('synthetic failure after replacement')
            with patch.object(self.store, 'save', side_effect=uncertain_save):
                with self.assertRaises(OSError):
                    self.reserve(controller)
            with self.assertRaises(ProbeError):
                self.reserve(controller)
        with self.attach() as controller:
            self.assertEqual(len(controller.recheck_operations()), 1)
            with self.assertRaisesRegex(ProbeError, 'unresolved'):
                self.reserve(controller)

    def test_failed_save_before_replacement_requires_reopening_before_new_reservation(self):
        with self.attach() as controller:
            with patch.object(self.store, 'save', side_effect=OSError('before replacement')):
                with self.assertRaises(OSError):
                    self.reserve(controller)
            with self.assertRaises(ProbeError):
                self.reserve(controller)
            self.assertNotIn('rechecks', self.store.read(self.sid)['workflow'])
        with self.attach() as controller:
            self.assertEqual(self.reserve(controller)['number'], 1)

    def test_quota_selection_and_attachment_are_checked_before_reservation(self):
        with self.attach() as controller:
            for options in [dict(quota={}), dict(quota=dict(QUOTA, accountId='foreign')),
                            dict(selection={'model': 'synthetic-strong', 'effort': 'low'}),
                            dict(cwd='relative'), dict(evidence_id='0' * 32)]:
                with self.subTest(options=options), self.assertRaises(ProbeError):
                    self.reserve(controller, **options)
                self.assertEqual(controller.recheck_operations(), [])
            with self.assertRaises(ProbeError):
                controller.answer_recheck_limit(self.evidence['id'], 'continue')
        with self.assertRaises(ProbeError):
            self.reserve(controller)

    def test_store_rejects_ledger_rollback_and_valid_rewrite(self):
        with self.attach() as controller:
            operation = self.reserve(controller)
            events = copy.deepcopy(controller._rechecks)
            controller._rechecks = []
            with self.assertRaisesRegex(ProbeError, 'recheck ledger'):
                self.store.save_workflow(self.sid, controller)
            controller._rechecks = copy.deepcopy(events)
            controller._rechecks[0]['spec_digest'] = 'f' * 64
            with self.assertRaisesRegex(ProbeError, 'recheck ledger'):
                self.store.save_workflow(self.sid, controller)
            controller._rechecks = events

    def test_old_schema_stays_readable_and_malformed_new_ledger_is_rejected(self):
        old = self.original['workflow']
        self.assertEqual(validate_workflow_checkpoint(old)['version'], 1)
        with self.attach() as controller:
            self.reserve(controller)
            checkpoint = controller.export_checkpoint()
        for field, value in [('number', True), ('cycle', 1), ('spec_digest', 'bad'),
                             ('evidence_id', 'f' * 32), ('kind', []), ('extra', True)]:
            malformed = copy.deepcopy(checkpoint)
            malformed['rechecks'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ProbeError):
                validate_workflow_checkpoint(malformed)

    def test_metrics_distinguish_work_and_recheck_attempts(self):
        with self.attach() as controller:
            self.reserve(controller)
            stats = workflow_statistics(controller, 1, now=2)
            self.assertEqual(stats['attempts'], 1)
            self.assertEqual(stats['recheckAttempts'], 1)
            self.assertIsNone(stats['reportedModels'])
            self.assertIsNone(stats['tokenUsage'])


if __name__ == '__main__':
    unittest.main()
