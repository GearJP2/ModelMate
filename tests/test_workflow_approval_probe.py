"""The opt-in native approval verifier uses fake processes, never installed Codex."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from modelmate import NativeWorkflowConnection, ProbeError, SessionStore
from test_native_permissions import SERVER
from test_routing import CATALOG
from verify import ApprovalVerificationConnection, WORKFLOW_APPROVAL_KEYS, main, probe_workflow_approvals


PROBE_SERVER = SERVER.replace('import json,sys', 'import json,sys,shlex')
PROBE_SERVER = PROBE_SERVER.replace("'command':'printf synthetic'", "'command':spec_command")
PROBE_SERVER = PROBE_SERVER.replace("Path(project,'effect').write_text('synthetic effect')",
    "Path(project,'approval-marker.txt').write_text(shlex.split(spec_command)[2]+'\\n')")
PROBE_SERVER = PROBE_SERVER.replace(" if method=='turn/start':\n",
    " if method=='turn/start':\n  spec_command=json.loads(p['input'][0]['text'])['verification_commands'][0]['command']\n")


class WorkflowApprovalProbeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.scratch = self.root / 'scratch';self.scratch.mkdir()
        self.count = 0

    def probe(self, source=PROBE_SERVER):
        original = ApprovalVerificationConnection
        def factory(command, timeout):
            choice = ('approve', 'decline')[self.count]
            self.count += 1
            project = self.scratch / choice
            with SessionStore(project, self.scratch / ('state-' + choice), read_only=True) as reader:
                state = reader.directory
            connection = original([sys.executable, '-u', '-c', source, str(self.root / (choice + '.trace')),
                str(project), str(state), 'command', json.dumps(CATALOG)], timeout)
            self.addCleanup(connection.close)
            return connection
        with patch('verify.ApprovalVerificationConnection', side_effect=factory), \
             patch('verify.tempfile.mkdtemp', return_value=str(self.scratch)), \
             patch('sys.stderr', new_callable=io.StringIO):
            return probe_workflow_approvals('synthetic-standard', 1)

    def records(self):
        return [json.loads(line) for trace in sorted(self.root.glob('*.trace'))
                for line in trace.read_text().splitlines()]

    def test_observed_accept_and_decline_are_durable_scoped_and_redacted(self):
        result = self.probe()
        self.assertTrue(all(result[key] == 'passed' for key in WORKFLOW_APPROVAL_KEYS), result)
        self.assertEqual(len(result['cases']), 2)
        self.assertEqual(sum(r.get('method') == 'turn/start' for r in self.records()), 2)
        self.assertEqual([r['result']['decision'] for r in self.records() if 'result' in r], ['accept', 'decline'])
        self.assertTrue((self.scratch / 'approve' / 'approval-marker.txt').is_file())
        self.assertFalse((self.scratch / 'decline' / 'approval-marker.txt').exists())
        self.assertNotIn(str(self.scratch), json.dumps(result))
        self.assertNotIn('MM-', json.dumps(result))
        self.assertNotIn('printf', json.dumps(result))
        self.assertIsNone(result['reportedModels'])

    def test_no_approval_event_cannot_pass_or_start_another_turn(self):
        source = PROBE_SERVER.replace('  emit(request)',
            "  emit({'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'1','status':'completed'}}})\n  continue")
        result = self.probe(source)
        self.assertEqual(result['failureReason'], 'approval_not_observed')
        self.assertEqual(result['safeRequestObserved'], 'unverified')
        self.assertEqual(sum(r.get('method') == 'turn/start' for r in self.records()), 1)

    def test_unexpected_command_is_never_approved_or_retried(self):
        result = self.probe(PROBE_SERVER.replace("'command':spec_command", "'command':spec_command+' && printf extra'"))
        self.assertEqual(result['failureReason'], 'unexpected_or_undisplayed_action')
        self.assertNotIn('accept', [r['result']['decision'] for r in self.records() if 'result' in r])
        self.assertEqual(sum(r.get('method') == 'turn/start' for r in self.records()), 1)

    def test_effect_before_consent_fails_without_sending_accept(self):
        source = PROBE_SERVER.replace('  emit(request)',
            "  Path(project,'approval-marker.txt').write_text(shlex.split(spec_command)[2]+'\\n')\n  emit(request)")
        result = self.probe(source)
        self.assertEqual(result['noEffectBeforeApproval'], 'failed')
        self.assertNotIn('accept', [r['result']['decision'] for r in self.records() if 'result' in r])

    def test_marker_without_native_command_completion_is_not_a_pass(self):
        result = self.probe(PROBE_SERVER.replace("if mode=='command':", 'if False:'))
        self.assertEqual(result['failureReason'], 'approved_command_evidence_missing')
        self.assertEqual(result['approvedEffect'], 'unverified')
        self.assertEqual(sum(r.get('method') == 'turn/start' for r in self.records()), 1)

    def test_early_command_completion_cannot_pass_even_if_marker_is_absent(self):
        source = PROBE_SERVER.replace('  emit(request)',
            "  item={'id':'tool','type':'commandExecution','command':spec_command,'cwd':project}\n"
            "  emit({'method':'item/started','params':{'threadId':'thread','turnId':'1','item':item}})\n"
            "  item.update(status='completed',exitCode=0)\n"
            "  emit({'method':'item/completed','params':{'threadId':'thread','turnId':'1','item':item}})\n"
            '  emit(request)')
        result = self.probe(source)
        self.assertEqual(result['noEffectBeforeApproval'], 'failed')
        self.assertFalse((self.scratch / 'approve' / 'approval-marker.txt').exists())
        self.assertNotIn('accept', [r['result']['decision'] for r in self.records() if 'result' in r])

    def test_accept_tripwire_blocks_unarmed_responses_before_transport(self):
        connection = object.__new__(ApprovalVerificationConnection)
        connection.armed = None
        connection.blocked_accepts = 0
        connection.controller = Mock()
        connection.controller.snapshot.return_value = {'tool_request': {'action_digest': 'a' * 64}}
        with patch.object(NativeWorkflowConnection, 'send') as send:
            with self.assertRaisesRegex(ProbeError, 'Unarmed'):connection.send({'id': 1, 'result': {'decision': 'accept'}})
            send.assert_not_called()
        self.assertEqual(connection.blocked_accepts, 1)

    def test_cli_requires_live_opt_in_and_all_checks_for_success(self):
        args = ['verify.py', '--probe-workflow-approvals', 'synthetic-standard']
        with patch('verify.probe_workflow_approvals') as probe, patch('sys.stdout', new_callable=io.StringIO):
            with patch('sys.argv', args):self.assertEqual(main(), 0)
            probe.assert_not_called()
            probe.return_value = dict.fromkeys(WORKFLOW_APPROVAL_KEYS, 'passed')
            with patch('sys.argv', args + ['--run-live']):
                self.assertEqual(main(), 0)
                probe.return_value['durableDecisions'] = 'unverified'
                self.assertEqual(main(), 1)
            with patch('sys.argv', args + ['--run-live', '--probe-workflow', 'synthetic-standard']), \
                 patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 2)
