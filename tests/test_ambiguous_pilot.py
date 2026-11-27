"""C8 uses synthetic host evidence; no model or account is contacted."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import ProbeError, SessionStore, WorkflowController
from test_routing import CATALOG, POLICY, QUOTA


PILOT = Path(__file__).resolve().parents[1] / 'examples' / 'routing-pilot.py'


class AmbiguousPilotTests(unittest.TestCase):
    def setUp(self):
        self.prepare_pair()

    def prepare_pair(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        result = subprocess.run([sys.executable, str(PILOT), 'prepare', '--case', 'ambiguous'],
            env=dict(os.environ, TMPDIR=directory.name), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.scratch = Path(result.stdout.strip())
        self.project = self.scratch / 'routed' / 'project'
        self.home = self.scratch / 'routed' / 'question-state'
        self.helper = runpy.run_path(str(PILOT))
        self.question = json.loads((self.project / 'question-plan.json').read_text())

    def run_arm(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.helper['run'](self.scratch, 'routed', 'standard', 'strong',
                                      kwargs.pop('execute', False), 'economy', **kwargs)

    def receipt(self, *, done=True, bound=True, change=None):
        plan = json.loads(json.dumps(self.question))
        if change:
            change(plan)
        controller = WorkflowController(json.dumps(plan), CATALOG, POLICY, 'auto')
        with SessionStore(self.project, self.home) as store:
            record = store.create(plan['goal'], thread_id='synthetic-thread',
                account_hash=hashlib.sha256(QUOTA['accountId'].encode()).hexdigest())
            sid = record['id']
            with store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY,
                                controller=controller) as flow:
                aid = flow.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)['dispatch']['attempt_id']
                if done:
                    flow.finish_attempt(aid, 'completed')
                    evidence = flow.record_check(aid, 0, origin='manual', result='pass',
                        reference='Synthetic trusted review', finding='Necessary question observed before edits')
                    flow.evaluate_attempt(aid)
                    flow.finish_task({0: [evidence['id']]})
            with store.edit(sid) as record:
                record['turn_id'] = 'synthetic-turn' if bound else None
            return sid

    def test_question_task_does_not_supply_missing_policy_and_arms_match(self):
        self.assertNotIn(self.helper['ROW_QUESTION'], json.dumps(self.question))
        self.assertNotIn(self.helper['ROW_ANSWER'], json.dumps(self.question))
        baseline = json.loads((self.scratch / 'baseline/project/question-plan.json').read_text())
        baseline['steps'][0]['role'] = 'standard'
        self.assertEqual(baseline, self.question)
        work = json.loads((self.project / 'plan.json').read_text())
        self.assertEqual(work['clarifications'], [self.helper['ROW_QUESTION']])

    def test_both_previews_are_offline_and_use_separate_states(self):
        for answered in (False, True):
            with self.subTest(answered=answered):
                result = subprocess.run([sys.executable, str(PILOT), 'run', str(self.scratch), 'routed',
                    '--standard', 'synthetic-standard', '--strong', 'synthetic-strong',
                    '--economy', 'synthetic-economy'] + (['--use-frozen-clarification'] if answered else []),
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(self.home.exists())
                self.assertFalse((self.scratch / 'routed/state').exists())
        with patch('subprocess.run', return_value=Mock(returncode=0)) as launch:
            self.run_arm()
            self.assertNotIn('--check-commands', launch.call_args.args[0])
            self.assertTrue(launch.call_args.kwargs['env']['XDG_STATE_HOME'].endswith('question-state'))
            self.run_arm(use_frozen_clarification=True)
            args = launch.call_args.args[0]
            self.assertIn('1=' + self.helper['ROW_ANSWER'], args)
            self.assertNotIn('--execute-workflow', args)

    def test_live_implementation_requires_accepted_receipt_before_launch(self):
        with patch('subprocess.run') as launch:
            with self.assertRaisesRegex(ValueError, 'missing, invalid'):
                self.run_arm(execute=True, tool_approvals=True, use_frozen_clarification=True)
            launch.assert_not_called()
        self.assertFalse(self.home.exists())

    def test_accepted_receipt_is_locked_during_launch_without_resume_or_grants(self):
        sid = self.receipt()
        def launch(args, **kwargs):
            self.assertIn('--execute-workflow', args)
            self.assertIn('1=' + self.helper['ROW_ANSWER'], args)
            self.assertNotIn('--resume', args)
            self.assertTrue(kwargs['env']['XDG_STATE_HOME'].endswith('/state'))
            with SessionStore(self.project, self.home) as other:
                with self.assertRaises(ProbeError):
                    with other._lock(sid):
                        self.fail('Receipt lock must remain held')
            return Mock(returncode=0)
        with patch('subprocess.run', side_effect=launch):
            self.assertEqual(self.run_arm(execute=True, tool_approvals=True,
                                         use_frozen_clarification=True), 0)

    def test_incomplete_unbound_and_changed_task_receipts_cannot_launch(self):
        for options in ({'done': False}, {'bound': False},
                        {'change': lambda plan: plan['steps'][0].update(objective='Different task')}):
            with self.subTest(options=options):
                # Each invalid receipt belongs to its own freshly prepared pair.
                self.prepare_pair()
                self.receipt(**options)
                with patch('subprocess.run') as launch:
                    with self.assertRaises(ValueError):
                        self.run_arm(execute=True, tool_approvals=True, use_frozen_clarification=True)
                    launch.assert_not_called()

    def test_multiple_or_busy_receipts_cannot_launch(self):
        sid = self.receipt()
        with SessionStore(self.project, self.home) as store:
            with store._lock(sid), patch('subprocess.run') as launch:
                with self.assertRaisesRegex(ValueError, 'still in use'):
                    self.run_arm(execute=True, tool_approvals=True, use_frozen_clarification=True)
                launch.assert_not_called()
        self.receipt()
        with patch('subprocess.run') as launch:
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                self.run_arm(execute=True, tool_approvals=True, use_frozen_clarification=True)
            launch.assert_not_called()

    def test_forged_done_without_check_evidence_is_rejected(self):
        sid = self.receipt(done=False)
        with SessionStore(self.project, self.home, read_only=True) as store:
            path = store.directory / (sid + '.json')
        record = json.loads(path.read_text())
        record['state'] = record['workflow']['state'] = 'DONE'
        path.write_text(json.dumps(record))
        with patch('subprocess.run') as launch:
            with self.assertRaisesRegex(ValueError, 'missing, invalid'):
                self.run_arm(execute=True, tool_approvals=True, use_frozen_clarification=True)
            launch.assert_not_called()

    def test_frozen_checker_counts_blank_rows_as_clarified(self):
        path = self.project / 'rows.py'
        code = path.read_text().replace('    args = parser.parse_args()',
            "    parser.add_argument('--limit', type=int)\n    args = parser.parse_args()\n"
            "    if args.limit is not None and args.limit < 0:\n        parser.error('limit must be non-negative')")
        code = code.replace('    sys.stdout.buffer.write(',
            '    if args.limit is not None:\n        rows = rows[:args.limit]\n    sys.stdout.buffer.write(')
        spec = json.loads((self.project / 'checks.json').read_text())['checks'][0]
        args = shlex.split(spec['command']); args[0] = sys.executable
        for reference, expected in ((code, 0),
                (code.replace('rows[:args.limit]', '[row for row in rows if row][:args.limit]'), 1)):
            path.write_text(reference)
            result = subprocess.run(args, cwd=self.project, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, expected, result.stderr)

    def test_question_phase_disallows_tool_opt_in_replay_and_changed_inputs(self):
        with patch('subprocess.run') as launch:
            with self.assertRaisesRegex(ValueError, 'cannot enable'):
                self.run_arm(tool_approvals=True)
            (self.scratch / 'routed/state').mkdir()
            with self.assertRaisesRegex(ValueError, 'do not replay'):
                self.run_arm()
            (self.scratch / 'routed/state').rmdir()
            self.home.mkdir()
            with self.assertRaisesRegex(ValueError, 'already has state'):
                self.run_arm()
            self.home.rmdir()
            (self.project / 'question-plan.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                self.run_arm()
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
