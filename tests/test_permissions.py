"""Durable controller tool decisions only; no executor or native permissions enabled."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import ChatShell, ProbeError, SessionStore, WorkflowController, WorkflowHost, run_chat, validate_workflow_checkpoint
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

    def host_ui(self, controller):
        response, interrupt = Mock(), Mock()
        host = WorkflowHost(controller, lambda: dict(quota=QUOTA, checked_at=time.monotonic(),
            catalog=CATALOG, role_policy=POLICY),
            lambda _: dict(thread_id='thread', turn_id='turn'), interrupt, tool_response=response)
        output = io.StringIO()
        shell = ChatShell(output, workflow=controller, workflow_action=host)
        shell.line('/next')
        return host, shell, output, response, interrupt

    def test_ui_displays_bound_preview_and_requires_a_separate_exact_tool_choice(self):
        with self.attach(WorkflowController(json.dumps(PLAN), CATALOG, POLICY)) as c:
            host, shell, output, response, _ = self.host_ui(c)
            preview = json.dumps({'command': 'printf synthetic', 'cwd': '/synthetic'}, ensure_ascii=True)
            request = host.offer_tool_approval(self.binding, preview)
            text = output.getvalue()
            self.assertLess(text.index(preview), text.index('/approve ' + request['token']))
            response.assert_not_called()
            shell.event({'type': 'text', 'text': '/approve ' + request['token']})
            shell.line('/approve wrong')
            shell.line('/approve ' + request['token'] + ' --next')
            response.assert_not_called()
            shell.line('/approve ' + request['token'])
            self.assertEqual(response.call_args.args[0]['decision'], 'accept')
            self.assertEqual(self.store.read(self.sid)['workflow']['tool_request']['status'], 'approved')
            shell.line('/approve ' + request['token'])
            self.assertEqual(response.call_count, 1)
            self.assertEqual(c.snapshot()['active_attempt']['checks'], {})

    def test_ui_cancel_pause_and_timeout_decline_then_interrupt_without_accept(self):
        for event in ('cancel', 'exit', 'pause', 'timeout', 'disconnect'):
            with self.subTest(event=event):
                c = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
                c._persist = lambda current: validate_workflow_checkpoint(current.export_checkpoint())
                host, shell, _, response, interrupt = self.host_ui(c)
                request = host.offer_tool_approval(self.binding, '{"command":"printf synthetic","cwd":"/synthetic"}')
                if event == 'timeout':
                    host._deadline = time.monotonic() - 1
                    with self.assertRaisesRegex(ProbeError, 'timed out'):host.tick()
                elif event == 'disconnect':host.disconnect()
                elif event == 'pause':shell.line('/pause ' + request['token'])
                else:shell.cancel(exit_after=event == 'exit')
                self.assertEqual(response.call_count, 1)
                self.assertEqual(response.call_args.args[0]['decision'], 'decline')
                interrupt.assert_called_once()
                self.assertEqual(c.state, 'PAUSED')
                with self.assertRaises(ProbeError):host.answer_tool_approval(request['token'], 'approve')

    def test_changed_preview_or_binding_cannot_use_a_visible_confirmation(self):
        for mutation in ('preview', 'binding'):
            with self.subTest(mutation=mutation):
                c = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
                c._persist = lambda current: validate_workflow_checkpoint(current.export_checkpoint())
                host, _, _, response, _ = self.host_ui(c)
                request = host.offer_tool_approval(self.binding, '{"command":"printf original","cwd":"/synthetic"}')
                if mutation == 'preview':host._tool_action['preview'] = 'changed'
                else:host._binding['turn_id'] = 'foreign'
                with self.assertRaises(ProbeError):host.answer_tool_approval(request['token'], 'approve')
                response.assert_not_called()
                self.assertEqual(c.export_checkpoint()['tool_request']['status'], 'expired')

    def test_failed_response_is_unknown_and_never_resent(self):
        with self.attach(WorkflowController(json.dumps(PLAN), CATALOG, POLICY)) as c:
            host, _, _, response, interrupt = self.host_ui(c)
            request = host.offer_tool_approval(self.binding, '{"command":"printf synthetic","cwd":"/synthetic"}')
            response.side_effect = OSError('synthetic send outcome unknown')
            with self.assertRaises(OSError):host.answer_tool_approval(request['token'], 'approve')
            self.assertEqual(c.reason, 'connection_lost')
            self.assertEqual(response.call_count, 1)
            interrupt.assert_called_once()
            with self.assertRaises(ProbeError):host.answer_tool_approval(request['token'], 'approve')
            self.assertEqual(response.call_count, 1)

    def test_unsupported_host_or_unsafe_preview_cannot_offer_an_approval(self):
        with self.attach(WorkflowController(json.dumps(PLAN), CATALOG, POLICY)) as c:
            host, _, _, response, _ = self.host_ui(c)
            for preview in ('', '\x1b[31mchanged', 'x' * 65537, 'unescaped Thai: ไทย'):
                with self.assertRaises(ProbeError):host.offer_tool_approval(self.binding, preview)
            with self.assertRaises(ProbeError):
                host.offer_tool_approval(dict(self.binding, turn_id='foreign'), 'safe')
            host._tool_response = None
            with self.assertRaises(ProbeError):host.offer_tool_approval(self.binding, 'safe')
            response.assert_not_called()
            self.assertEqual(c.state, 'RUNNING')

    def test_real_input_eof_declines_pending_tool_and_waits_for_interrupted_event(self):
        with self.attach(WorkflowController(json.dumps(PLAN), CATALOG, POLICY)) as c:
            responses = Mock()
            def interrupt(binding):
                host.observe_native({'method': 'turn/completed', 'params': {
                    'threadId': binding['thread_id'], 'turn': {'id': binding['turn_id'], 'status': 'interrupted'}}})
            host = WorkflowHost(c, lambda: dict(quota=QUOTA, checked_at=time.monotonic(),
                catalog=CATALOG, role_policy=POLICY),
                lambda _: dict(thread_id='thread', turn_id='turn'), interrupt, tool_response=responses)
            host({'action': 'next', 'task_id': c.task_id})
            host.offer_tool_approval(self.binding, '{"command":"printf synthetic","cwd":"/synthetic"}')
            output = io.StringIO()
            with tempfile.TemporaryFile() as stream:
                self.assertEqual(run_chat(stream, output, workflow=c, workflow_action=host), 0)
            responses.assert_called_once()
            self.assertEqual(responses.call_args.args[0]['decision'], 'decline')
            self.assertEqual(host._terminal, 'interrupted')
            self.assertIsNone(c.snapshot()['active_attempt'])
            self.assertNotEqual(c.state, 'DONE')

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
