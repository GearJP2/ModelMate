"""C2 fixtures/checks use only developer-written candidate code in offline tests."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


PILOT = Path(__file__).resolve().parents[1] / 'examples' / 'routing-pilot.py'


class CliPilotTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / 'scratch with spaces';self.root.mkdir()
        result = subprocess.run([sys.executable, str(PILOT), 'prepare', '--case', 'cli'],
            env=dict(os.environ, TMPDIR=str(self.root)), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.scratch = Path(result.stdout.strip())
        self.project = self.scratch / 'routed' / 'project'

    def check(self):
        spec = json.loads((self.project / 'checks.json').read_text())['checks'][0]
        args = shlex.split(spec['command']);args[0] = sys.executable
        return subprocess.run(args, cwd=self.project, capture_output=True, text=True, timeout=25)

    def implement_reference(self):
        path = self.project / 'rows.py'
        code = path.read_text()
        code = code.replace("    parser.add_argument('path')",
            "    parser.add_argument('path')\n    parser.add_argument('--limit', type=int)")
        code = code.replace('    args = parser.parse_args()',
            "    args = parser.parse_args()\n    if args.limit is not None and args.limit < 0:\n        parser.error('limit must be non-negative')")
        code = code.replace('    sys.stdout.buffer.write(',
            '    if args.limit is not None:\n        rows = rows[:args.limit]\n    sys.stdout.buffer.write(')
        path.write_text(code)

    def test_frozen_checker_rejects_original_and_accepts_audited_reference(self):
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['default'])
        self.assertFalse(report['zero'])
        self.assertFalse(report['help'])
        self.implement_reference()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(len(report), 11)
        self.assertTrue(all(report.values()))
        path = self.project / 'rows.py'
        path.write_text(path.read_text().replace('rows[:args.limit]', 'rows[:args.limit + 1]'))
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['zero'])
        (self.project / 'rows with spaces.txt').write_text('changed input')
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout), {'inputUnchanged': False})

    def test_checker_hash_prevents_replacing_acceptance_with_self_report(self):
        (self.scratch / 'check-cli.py').write_text(
            "from pathlib import Path\nPath('grader-bypass').write_text('bad')\nraise SystemExit(0)\n")
        result = self.check()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'checkerIntegrity': False})
        self.assertFalse((self.project / 'grader-bypass').exists())

    def test_matching_fixtures_preview_both_arms_without_codex_or_state(self):
        plans, commands = [], []
        for arm, model in (('routed', 'synthetic-economy'), ('baseline', 'synthetic-strong')):
            result = subprocess.run([sys.executable, str(PILOT), 'run', str(self.scratch), arm,
                '--standard', 'synthetic-standard', '--strong', 'synthetic-strong', '--economy', 'synthetic-economy'],
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(model + '/low', result.stdout)
            self.assertFalse((self.scratch / arm / 'state').exists())
            project = self.scratch / arm / 'project'
            plan = json.loads((project / 'plan.json').read_text());plan['steps'][0].pop('role')
            plans.append(plan)
            commands.append(json.loads((project / 'checks.json').read_text())['checks'][0]['command'])
            self.assertEqual((project / 'rows.py').read_bytes(), (self.project / 'rows.py').read_bytes())
        self.assertEqual(*plans)
        self.assertEqual(*commands)

    def test_execution_requires_explicit_native_approval_flag_and_forwards_it(self):
        run = runpy.run_path(str(PILOT))['run']
        with patch('subprocess.run', return_value=Mock(returncode=0)) as execute, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'explicit --experimental-tool-approvals'):
                run(self.scratch, 'routed', 'standard', 'strong', True, 'economy')
            execute.assert_not_called()
            self.assertEqual(run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True), 0)
            args = execute.call_args.args[0]
            self.assertIn('--experimental-tool-approvals', args)
            self.assertIn('--execute-workflow', args)
            self.assertIn('--check-commands', args)
        self.assertFalse((self.scratch / 'routed' / 'state').exists())

    def test_checker_respects_stronger_existing_file_limits(self):
        module = runpy.run_path(str(self.scratch / 'check-cli.py'))
        resource = module['resource']
        for limits, expected in (((2048, 4096), 2048),
                                 ((resource.RLIM_INFINITY, resource.RLIM_INFINITY), 65536)):
            with self.subTest(limits=limits), patch('resource.getrlimit', return_value=limits), \
                 patch('resource.setrlimit') as set_limit:
                module['output_limit']()
            set_limit.assert_called_once_with(resource.RLIMIT_FSIZE, (expected, expected))

    def test_changed_inputs_or_existing_arm_state_cannot_launch_runtime(self):
        run = runpy.run_path(str(PILOT))['run']
        paths = [self.scratch / 'modelmate.py', self.scratch / 'check-cli.py',
                 self.project / 'rows.py', self.project / 'rows with spaces.txt',
                 self.project / 'plan.json', self.project / 'checks.json']
        with patch('subprocess.run') as launch, contextlib.redirect_stdout(io.StringIO()):
            for path in paths:
                original = path.read_bytes()
                path.write_bytes(original + b'\nchanged')
                try:
                    with self.subTest(path=path.name), self.assertRaises(ValueError):
                        run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True)
                finally:
                    path.write_bytes(original)
            (self.scratch / 'routed' / 'state').mkdir()
            with self.assertRaisesRegex(ValueError, 'never replay'):
                run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True)
            launch.assert_not_called()

    def test_checker_timeout_stops_without_running_later_cases(self):
        module = runpy.run_path(str(self.scratch / 'check-cli.py'))
        main = module['main']
        observe = Mock(return_value=None)
        output = io.StringIO()
        with patch.dict(main.__globals__, observe=observe, input_unchanged=lambda _: True), \
             contextlib.redirect_stdout(output):
            self.assertEqual(main(), 2)
        observe.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())['reason'], 'candidate_timeout')


if __name__ == '__main__':
    unittest.main()
