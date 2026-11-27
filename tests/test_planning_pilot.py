"""A2 arithmetic checks do not substitute for trusted review of plan quality."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from modelmate import validate_plan


PILOT = Path(__file__).resolve().parents[1] / 'examples' / 'routing-pilot.py'


class PlanningPilotTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        result = subprocess.run([sys.executable, str(PILOT), 'prepare', '--case', 'planning'],
            env=dict(os.environ, TMPDIR=directory.name), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.scratch = Path(result.stdout.strip())
        self.helper = runpy.run_path(str(PILOT))
        self.answer = {'assessments': {
            'manual': {'total_hours': 6, 'feasible': False, 'failed_constraints': ['weekly']},
            'script': {'total_hours': 6, 'feasible': True, 'failed_constraints': []},
            'hosted': {'total_hours': 3.4, 'feasible': False, 'failed_constraints': ['privacy']}},
            'selected': 'script',
            'plan': 'The maintainer will build a local script, test it against a manual report, then schedule daily runs by day 5.',
            'tradeoffs': 'Manual starts earlier but exceeds weekly maintenance; hosted needs least effort but violates privacy. Script meets constraints but can be 24 hours stale.',
            'rollback': 'If comparison fails, pause the scheduler and retain local inputs. Manual reporting is a temporary fallback requiring approval for its excess weekly maintenance.'}

    def score(self, raw):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = self.helper['score_planning'](raw)
        return status, json.loads(output.getvalue())

    def test_same_valid_plan_and_human_rubric_preview_both_arms_without_state(self):
        plans = []
        for arm, role in (('routed', 'standard'), ('baseline', 'strong')):
            path = self.scratch / arm / 'project/plan.json'
            plan = validate_plan(path.read_text())
            self.assertEqual(plan['steps'][0]['kind'], 'plan')
            self.assertEqual(len(plan['steps'][0]['checks']), 2)
            self.assertIn('trusted reviewer', plan['success_criteria'][1])
            result = subprocess.run([sys.executable, str(PILOT), 'run', str(self.scratch), arm,
                '--standard', 'synthetic-standard', '--strong', 'synthetic-strong'],
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('synthetic-' + role + '/low', result.stdout)
            self.assertFalse((self.scratch / arm / 'state').exists())
            plan['steps'][0].pop('role'); plans.append(plan)
        self.assertEqual(*plans)

    def test_reference_facts_pass_but_quality_always_requires_trusted_review(self):
        status, report = self.score(json.dumps(self.answer))
        self.assertEqual(status, 0)
        self.assertTrue(all(report['machineChecks'].values()))
        self.assertTrue(report['trustedReviewRequired'])
        # Deliberately vacuous prose demonstrates the machine check's boundary.
        self.answer.update(plan='x', tradeoffs='x', rollback='x')
        status, report = self.score(json.dumps(self.answer))
        self.assertEqual(status, 0)
        self.assertTrue(report['trustedReviewRequired'])
        self.assertNotIn('accepted', report)

    def test_infeasible_choice_arithmetic_missing_constraint_and_wrong_types_fail(self):
        for option, field, value in (('manual', 'total_hours', 2), ('hosted', 'feasible', True),
                ('manual', 'failed_constraints', []), ('script', 'feasible', 1),
                ('script', 'total_hours', '6'), ('script', 'total_hours', True),
                ('hosted', 'total_hours', float('nan'))):
            answer = json.loads(json.dumps(self.answer)); answer['assessments'][option][field] = value
            with self.subTest(option=option, field=field, value=value):
                status, report = self.score(json.dumps(answer))
                self.assertEqual(status, 1)
                self.assertFalse(report['machineChecks'][option])
        for field, value in (('selected', 'hosted'), ('plan', ''), ('rollback', []), ('tradeoffs', 'x' * 3001)):
            answer = dict(self.answer); answer[field] = value
            self.assertEqual(self.score(json.dumps(answer))[0], 1)

    def test_malformed_duplicate_extra_missing_and_oversized_answers_are_rejected(self):
        raw = json.dumps(self.answer)
        for invalid in ('[]', '{}', 'not JSON', '```' + raw + '```',
                raw[:-1] + ',"selected":"script"}',
                raw.replace('"feasible": true', '"feasible": true,"feasible": true'),
                json.dumps(dict(self.answer, approved=True)), raw + ' ' * 16385,
                '[' * 1500 + ']' * 1500):
            with self.subTest(raw=invalid[:40]), self.assertRaises(ValueError):
                self.score(invalid)
        result = subprocess.run([sys.executable, str(PILOT), 'score', '--case', 'planning', raw],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['trustedReviewRequired'])

    def test_execution_opt_in_frozen_inputs_and_existing_state_guards(self):
        run = self.helper['run']
        args = (self.scratch, 'routed', 'standard', 'strong')
        with patch('subprocess.run', return_value=Mock(returncode=0)) as launch, contextlib.redirect_stdout(io.StringIO()):
            run(*args, False)
            self.assertNotIn('--execute-workflow', launch.call_args.args[0])
            run(*args, True)
            self.assertIn('--execute-workflow', launch.call_args.args[0])
            self.assertIn('--measure-quota', launch.call_args.args[0])
            launch.reset_mock()
            with self.assertRaisesRegex(ValueError, 'scoped to the CLI'):
                run(*args, True, tool_approvals=True)
            path = self.scratch / 'routed/project/plan.json'
            original = path.read_bytes(); path.write_bytes(original + b'\n')
            with self.assertRaisesRegex(ValueError, 'Frozen planning'):
                run(*args, True)
            path.write_bytes(original)
            (self.scratch / 'routed/state').mkdir()
            with self.assertRaisesRegex(ValueError, 'never replay'):
                run(*args, True)
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
