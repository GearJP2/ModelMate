"""Offline tests of the routing pilot's metrics reader and comparison."""
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PILOT = Path(__file__).resolve().parents[1] / 'examples' / 'routing-pilot.py'


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
        self.assertEqual(report['routedMinusBaseline'], {'workTurnSeconds': -0.6,
            'reportedWorkThreadTokens': -10, 'reportedCachedInputTokens': -20})
        self.assertEqual(report['routed']['cliWallSecondsIncludingUserWait'], 60)
        self.assertEqual(report['baseline']['observedModelReroutes'], [])
        self.assertEqual(report['routed']['observedModelReroutes'], [transition])

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
        self.assertIn('Duplicate incident answer key', score.stderr)
