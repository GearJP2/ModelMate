"""Offline tests of the routing pilot's metrics reader and comparison."""
import json
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
        self.write(self.routed, self.measured(90, 0, 1.7))
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['routedMinusBaseline'], {'workTurnSeconds': -0.6,
            'reportedWorkThreadTokens': -10, 'reportedCachedInputTokens': -20})
        self.assertEqual(report['routed']['cliWallSecondsIncludingUserWait'], 60)

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
