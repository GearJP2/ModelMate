"""C4 evaluation checks run developer-written references/mutants only, without Codex."""
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


class ParserPilotTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root = Path(directory.name) / 'parser pair with spaces';root.mkdir()
        output = subprocess.check_output([sys.executable, str(PILOT), 'prepare', '--case', 'parser'],
            env=dict(os.environ, TMPDIR=str(root)), text=True, timeout=5)
        self.scratch = Path(output.strip())
        self.project = self.scratch / 'routed' / 'project'
        self.original_records = (self.project / 'records.py').read_text()
        self.original_totals = (self.project / 'totals.py').read_text()

    def check(self):
        spec = json.loads((self.project / 'checks.json').read_text())['checks'][0]
        args = shlex.split(spec['command']);args[0] = sys.executable
        return subprocess.run(args, cwd=self.project, capture_output=True, text=True, timeout=15)

    def implement_reference(self):
        (self.project / 'record_fields.py').write_text(self.original_records.replace('def parse_record(', 'def parse_fields('))
        (self.project / 'records.py').write_text('from record_fields import parse_fields\n\n'
            'def parse_record(text):\n    return parse_fields(text)\n')
        (self.project / 'totals.py').write_text('from record_fields import parse_fields\n\n'
            'def sum_counts(rows):\n    result = {}\n    for text in rows:\n'
            '        name, count = parse_fields(text)\n'
            '        result[name] = result.get(name, 0) + count\n    return result\n')

    def test_checker_preserves_initial_api_and_requires_extracted_module(self):
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        checks = json.loads(result.stdout)
        self.assertTrue(checks['records_simple'])
        self.assertTrue(checks['totals_ordered_duplicates'])
        self.assertFalse(checks['extractedModule'])
        self.assertFalse(checks['record_fields_simple'])
        self.implement_reference()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)), 30)
        self.assertTrue(all(json.loads(result.stdout).values()))

    def test_mutants_cannot_change_types_order_aggregation_or_input(self):
        for name, change, check in (
                ('records.py', ('return parse_fields(text)', 'return list(parse_fields(text))'), 'records_simple'),
                ('record_fields.py', ('return name, count', 'return name, float(count)'), 'record_fields_simple'),
                ('totals.py', ('result.get(name, 0) + count', 'count'), 'totals_ordered_duplicates'),
                ('totals.py', ('return result', 'return dict(sorted(result.items()))'), 'totals_ordered_duplicates'),
                ('totals.py', ('for text in rows:', 'while rows:\n        text = rows.pop(0)'), 'totals_ordered_duplicates')):
            self.implement_reference()
            path = self.project / name;path.write_text(path.read_text().replace(*change))
            with self.subTest(name=name, change=change):
                result = self.check()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(json.loads(result.stdout)[check])

    def test_green_api_checks_still_require_independent_delegation_review(self):
        self.implement_reference()
        (self.project / 'totals.py').write_text(self.original_totals)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads((self.project / 'plan.json').read_text())
        self.assertEqual([check['kind'] for check in plan['steps'][0]['checks']], ['test', 'rubric'])
        self.assertEqual(len(plan['success_criteria']), 2)
        self.assertIn('both callers delegate', plan['success_criteria'][1])

    def test_same_initial_files_and_check_command_preview_both_arms_without_state(self):
        plans, commands = [], []
        for arm, model in (('routed', 'synthetic-standard'), ('baseline', 'synthetic-strong')):
            output = subprocess.check_output([sys.executable, str(PILOT), 'run', str(self.scratch), arm,
                '--standard', 'synthetic-standard', '--strong', 'synthetic-strong', '--economy', 'synthetic-economy'],
                text=True, timeout=5)
            self.assertIn(model + '/low', output)
            self.assertFalse((self.scratch / arm / 'state').exists())
            project = self.scratch / arm / 'project'
            self.assertEqual((project / 'records.py').read_text(), self.original_records)
            self.assertEqual((project / 'totals.py').read_text(), self.original_totals)
            plan = json.loads((project / 'plan.json').read_text());plan['steps'][0].pop('role');plans.append(plan)
            commands.append(json.loads((project / 'checks.json').read_text())['checks'][0]['command'])
        self.assertEqual(*plans)
        self.assertEqual(*commands)

    def test_modified_checker_cannot_replace_acceptance_with_self_report(self):
        (self.scratch / 'check-parser.py').write_text("from pathlib import Path\nPath('bypass').touch()\n")
        result = self.check()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'checkerIntegrity': False})
        self.assertFalse((self.project / 'bypass').exists())

    def test_frozen_inputs_extra_files_and_existing_arm_state_block_launch(self):
        run = runpy.run_path(str(PILOT))['run']
        paths = [self.scratch / 'modelmate.py', self.scratch / 'check-parser.py',
                 *(self.project / name for name in ('records.py', 'totals.py', 'checks.json', 'plan.json'))]
        with patch('subprocess.run') as launch:
            for path in paths:
                content = path.read_bytes();path.write_bytes(content + b'\nchanged')
                try:
                    with self.subTest(name=path.name),self.assertRaises(ValueError):
                        run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True)
                finally:path.write_bytes(content)
            extra = self.project / 'record_fields.py';extra.touch()
            with self.assertRaisesRegex(ValueError, 'Frozen authoring inputs'):
                run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True)
            extra.unlink()
            (self.scratch / 'routed' / 'state').mkdir()
            with self.assertRaisesRegex(ValueError, 'never replay'):
                run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True)
            launch.assert_not_called()

    def test_live_execution_needs_explicit_tool_approval_opt_in(self):
        run = runpy.run_path(str(PILOT))['run']
        with patch('subprocess.run', return_value=Mock(returncode=0)) as launch,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'explicit --experimental-tool-approvals'):
                run(self.scratch, 'routed', 'standard', 'strong', True, 'economy')
            launch.assert_not_called()
            self.assertEqual(run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True), 0)
            self.assertIn('--execute-workflow', launch.call_args.args[0])
            self.assertIn('--experimental-tool-approvals', launch.call_args.args[0])
            self.assertIn('--check-commands', launch.call_args.args[0])

    def test_timeout_or_failed_child_stops_and_stdout_cannot_supply_a_verdict(self):
        module = runpy.run_path(str(self.scratch / 'check-parser.py'))
        for observed in (None, (1, b'', b'private error')):
            observe = Mock(return_value=observed);output = io.StringIO()
            with self.subTest(observed=str(observed)[:30]),patch.dict(module['main'].__globals__, observe=observe), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(module['main'](), 2)
            observe.assert_called_once()
            self.assertEqual(json.loads(output.getvalue())['state'], 'unverified')
            self.assertNotIn('private error', output.getvalue())
        for stdout in (b'{"claimed_pass":true}', b'[' * 2000 + b']' * 2000):
            output = io.StringIO()
            with patch.dict(module['main'].__globals__, observe=Mock(return_value=(0, stdout, b''))), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(module['main'](), 1)
            self.assertNotIn('claimed_pass', output.getvalue())
            self.assertFalse(any(value for key, value in json.loads(output.getvalue()).items() if key != 'extractedModule'))
        (self.project / 'records.py').write_text('while True: pass\n')
        result = self.check()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)['reason'], 'candidate_timeout')

    def test_checker_respects_stronger_existing_output_limits(self):
        module = runpy.run_path(str(self.scratch / 'check-parser.py'));resource = module['resource']
        with patch('resource.getrlimit', return_value=(2048, 4096)),patch('resource.setrlimit') as limit:
            module['output_limit']()
        limit.assert_called_once_with(resource.RLIMIT_FSIZE, (2048, 2048))
