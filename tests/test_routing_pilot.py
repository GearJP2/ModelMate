"""Offline tests of the routing pilot's metrics reader and comparison."""
import json
import contextlib
import io
import runpy
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


PILOT = Path(__file__).resolve().parents[1] / 'examples' / 'routing-pilot.py'


class CleanupPilotTests(unittest.TestCase):
    answer = {'scope_contained': {'safe': False, 'lines': [2, 6]},
              'confirmation_before_delete': {'safe': False, 'lines': [5, 6, 7, 8]},
              'active_blocked': {'safe': True, 'lines': [3, 4, 6]}}

    def prepare(self):
        output = subprocess.check_output([sys.executable, str(PILOT), 'prepare', '--case', 'cleanup'],
                                         text=True, timeout=5)
        scratch = Path(output.strip())
        self.addCleanup(shutil.rmtree, scratch)
        return scratch

    def score(self, answer):
        return subprocess.run([sys.executable, str(PILOT), 'score', '--case', 'cleanup', answer],
                              capture_output=True, text=True, timeout=5)

    def test_same_numbered_review_fixture_previews_without_codex_or_state(self):
        scratch = self.prepare()
        plans = []
        for arm, model in (('routed', 'synthetic-standard'), ('baseline', 'synthetic-strong')):
            output = subprocess.check_output([sys.executable, str(PILOT), 'run', str(scratch), arm,
                '--standard', 'synthetic-standard', '--strong', 'synthetic-strong'], text=True, timeout=5)
            self.assertIn(model + '/low', output)
            self.assertIn('6:         shutil.rmtree(target)', output)
            project = scratch / arm / 'project'
            self.assertEqual({p.name for p in project.iterdir()}, {'plan.json', 'cleanup.py'})
            self.assertEqual((project / 'cleanup.py').read_bytes(),
                             (scratch / 'routed' / 'project' / 'cleanup.py').read_bytes())
            self.assertFalse((scratch / arm / 'state').exists())
            plan = json.loads((project / 'plan.json').read_text())
            self.assertEqual(plan['steps'][0]['kind'], 'review')
            plan['steps'][0].pop('role');plans.append(plan)
        self.assertEqual(*plans)

    def test_scorer_requires_both_bugs_correct_guard_and_exact_evidence(self):
        result = self.score(json.dumps(self.answer))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(json.loads(result.stdout).values()))
        for property, field, value in (('scope_contained', 'safe', True),
                ('confirmation_before_delete', 'safe', True), ('active_blocked', 'safe', False),
                ('scope_contained', 'lines', [2]), ('active_blocked', 'lines', [6, 3, 4]),
                ('scope_contained', 'safe', 0), ('scope_contained', 'lines', [2.0, 6])):
            answer = json.loads(json.dumps(self.answer));answer[property][field] = value
            with self.subTest(property=property, field=field, value=value):
                result = self.score(json.dumps(answer))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(json.loads(result.stdout)[property])

    def test_malformed_duplicate_extra_and_oversized_answers_cannot_pass(self):
        valid = json.dumps(self.answer)
        invalid = ['not JSON', '```json\n' + valid + '\n```', '[]', '{}',
                   valid[:-1] + ',"active_blocked":{}}',
                   json.dumps(dict(self.answer, approved=True)), valid + ' ' * 16385]
        for answer in invalid:
            with self.subTest(answer=answer[:30]):
                self.assertEqual(self.score(answer).returncode, 2)

    def test_execute_is_explicit_and_tool_approval_scope_is_not_expanded(self):
        scratch = self.prepare()
        run = runpy.run_path(str(PILOT))['run']
        with patch('subprocess.run', return_value=Mock(returncode=0)) as launch, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(scratch, 'routed', 'standard', 'strong', False), 0)
            self.assertNotIn('--execute-workflow', launch.call_args.args[0])
            self.assertEqual(run(scratch, 'routed', 'standard', 'strong', True), 0)
            self.assertIn('--execute-workflow', launch.call_args.args[0])
            self.assertIn('--measure-quota', launch.call_args.args[0])
            self.assertNotIn('--experimental-tool-approvals', launch.call_args.args[0])
            launch.reset_mock()
            with self.assertRaisesRegex(ValueError, 'scoped to the CLI'):
                run(scratch, 'routed', 'standard', 'strong', True, tool_approvals=True)
            launch.assert_not_called()

    def test_changed_review_inputs_or_existing_state_prevents_launch(self):
        scratch = self.prepare()
        run = runpy.run_path(str(PILOT))['run']
        plan = scratch / 'routed' / 'project' / 'plan.json'
        with patch('subprocess.run') as launch:
            for path in (plan, plan.with_name('cleanup.py')):
                content = path.read_bytes();path.write_bytes(content + b'\n')
                with self.subTest(file=path.name),self.assertRaisesRegex(ValueError, 'Frozen cleanup review inputs changed'):
                    run(scratch, 'routed', 'standard', 'strong', True)
                path.write_bytes(content)
            (scratch / 'routed' / 'state').mkdir()
            with self.assertRaisesRegex(ValueError, 'never replay'):
                run(scratch, 'routed', 'standard', 'strong', True)
            launch.assert_not_called()


class PilotComparisonTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.baseline = Path(temp.name) / 'baseline.jsonl'
        self.routed = Path(temp.name) / 'routed.jsonl'

    def measured(self, tokens, cached, seconds):
        last = {'totalTokens': tokens, 'cachedInputTokens': cached}
        return {'schemaVersion': 1, 'state': 'PAUSED', 'attempts': 1,
                'attemptsScope': 'workflow_total', 'elapsedSeconds': 60,
                'elapsedScope': 'current_cli_session', 'includesUserWait': True,
                'recheckAttempts': 0, 'timedTurns': 1, 'turnElapsedSeconds': seconds,
                'tokenUsageScope': 'last_observed_work_thread_update',
                'tokenUsage': {'last': last, 'total': last},
                'workTurnMeasurements': [{'elapsedSeconds': seconds,
                   'terminalStatus': 'completed', 'lastReportedTokens': last}]}

    def write(self, file, *records):
        file.write_text(''.join(json.dumps(record) + '\n' for record in records), encoding='utf-8')

    def cli(self, *options):
        return subprocess.run([sys.executable, str(PILOT), 'compare',
            str(self.baseline), str(self.routed), *options], capture_output=True, text=True, timeout=5)

    def test_completed_pair_compares_seconds_total_tokens_and_cached_subset(self):
        self.write(self.baseline, self.measured(100, 20, 2.3))
        routed = self.measured(90, 0, 1.7)
        transition = {'fromModel': 'synthetic-standard', 'toModel': 'synthetic-fallback'}
        routed['workTurnMeasurements'][0]['modelReroutes'] = [transition]
        self.write(self.routed, routed)
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['routedMinusBaseline'], {'workTurnSeconds': -0.6, 'timeToAcceptanceSeconds': None,
            'reportedWorkThreadTokens': -10, 'reportedCachedInputTokens': -20})
        self.assertEqual(report['routed']['cliWallSecondsIncludingUserWait'], 60)
        self.assertEqual(report['baseline']['observedModelReroutes'], [])
        self.assertEqual(report['routed']['observedModelReroutes'], [transition])

    def test_acceptance_comparison_requires_both_completed_workflows(self):
        baseline = dict(self.measured(100, 20, 2.3), state='DONE', timeToAcceptanceSeconds=30)
        routed = dict(self.measured(90, 0, 1.7), state='DONE', timeToAcceptanceSeconds=27)
        self.write(self.baseline, baseline)
        self.write(self.routed, routed)
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['routedMinusBaseline']['timeToAcceptanceSeconds'], -3)
        self.write(self.routed, dict(routed, state='PAUSED'))
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(json.loads(result.stdout)['routedMinusBaseline']['timeToAcceptanceSeconds'])

    def test_ambiguous_selection_requires_row_and_resumed_partial_metrics_stay_unknown(self):
        complete = self.measured(100, 20, 2.3)
        self.write(self.baseline, complete, complete)
        self.write(self.routed, dict(self.measured(90, 0, 1.7), attempts=2))
        self.assertIn('Choose an explicit row', self.cli().stderr)
        result = self.cli('--baseline-row', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['routed']['allRecordedWorkTurnsCompletedHere'])
        self.assertTrue(all(delta is None for delta in report['routedMinusBaseline'].values()))

    def test_missing_latest_token_update_does_not_turn_an_older_snapshot_into_zero(self):
        complete = self.measured(100, 20, 2.3)
        partial = self.measured(90, 0, 1.7)
        partial['workTurnMeasurements'][0]['lastReportedTokens'] = None
        self.write(self.baseline, complete)
        self.write(self.routed, partial)
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        deltas = json.loads(result.stdout)['routedMinusBaseline']
        self.assertEqual(deltas['workTurnSeconds'], -0.6)
        self.assertIsNone(deltas['reportedWorkThreadTokens'])

    def test_incident_plan_freezes_same_questions_and_previews_without_dispatch(self):
        prepared = subprocess.check_output([sys.executable, str(PILOT), 'prepare', '--case', 'incident'],
                                           text=True, timeout=5)
        scratch = Path(prepared.strip())
        self.addCleanup(shutil.rmtree, scratch)
        plans = []
        for arm, model in [('baseline', 'synthetic-strong'), ('routed', 'synthetic-standard')]:
            result = subprocess.check_output([sys.executable, str(PILOT), 'run', str(scratch), arm,
                '--standard', 'synthetic-standard', '--strong', 'synthetic-strong'], text=True, timeout=5)
            self.assertIn(model + '/low', result)
            self.assertIn('observed_impact_minutes', result)
            self.assertFalse((scratch / arm / 'state').exists())
            plan = json.loads((scratch / arm / 'project' / 'plan.json').read_text())
            plan['steps'][0].pop('role')
            plans.append(plan)
        self.assertEqual(*plans)

    def test_incident_scorer_detects_overstated_cause_and_duplicate_fields(self):
        result = {'timeline': ['A', 'B', 'C', 'D'], 'observed_impact_minutes': 13,
                  'root_cause': 'unconfirmed', 'competing_recovery_event': 'C'}
        command = [sys.executable, str(PILOT), 'score', '--case', 'incident']
        score = subprocess.run(command + [json.dumps(result)], capture_output=True, text=True, timeout=5)
        self.assertEqual(score.returncode, 0, score.stderr)
        result['root_cause'] = 'config_confirmed'
        score = subprocess.run(command + [json.dumps(result)], capture_output=True, text=True, timeout=5)
        self.assertEqual(score.returncode, 1)
        self.assertFalse(json.loads(score.stdout)['root_cause'])
        duplicate = json.dumps(result)[:-1] + ', "root_cause": "unconfirmed"}'
        score = subprocess.run(command + [duplicate], capture_output=True, text=True, timeout=5)
        self.assertEqual(score.returncode, 2)
        self.assertIn('Duplicate answer key', score.stderr)
