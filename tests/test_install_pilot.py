"""A3 installation runs only a validated local recipe and a frozen example."""
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

from modelmate import validate_plan


PILOT = Path(__file__).resolve().parents[1] / 'examples/routing-pilot.py'
RECIPE = ('mkdir -p "$HOME/.local/share/report demo"\n'
          'cp "$SOURCE/example.py" "$HOME/.local/share/report demo/example.py"\n'
          'python3 "$HOME/.local/share/report demo/example.py" --self-check')


class InstallPilotTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        result = subprocess.run([sys.executable, str(PILOT), 'prepare', '--case', 'install'],
            env=dict(os.environ, TMPDIR=directory.name), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.scratch = Path(result.stdout.strip())
        self.project = self.scratch / 'routed/project'
        self.document = self.project / 'INSTALL.md'
        self.helper = runpy.run_path(str(PILOT))

    def reference(self, recipe=RECIPE):
        self.document.write_text('# Report demo\n\nRequires a POSIX shell, Python 3, mkdir and cp. '
            'Set SOURCE to the absolute directory containing example.py and use your HOME directory. '
            'Paths may contain spaces.\n\n```sh\n' + recipe + '\n```\n\n'
            'Expect report-demo-ok. The installed file runs from any directory without the source copy.\n')

    def check(self):
        spec = json.loads((self.project / 'checks.json').read_text())['checks'][0]
        args = shlex.split(spec['command']); args[0] = sys.executable
        return subprocess.run(args, cwd=self.project, capture_output=True, text=True, timeout=10)

    def test_broken_guide_fails_and_reference_installs_in_fresh_paths_with_spaces(self):
        self.assertNotEqual(self.check().returncode, 0)
        self.reference()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(all(report['machineChecks'].values()))
        self.assertTrue(report['machineChecks']['independentRun'])
        self.assertTrue(report['trustedReviewRequired'])

    def test_unquoted_source_and_literal_variables_do_not_pass_real_install(self):
        for recipe in (RECIPE.replace('"$SOURCE/example.py"', '$SOURCE/example.py'),
                       RECIPE.replace('"', "'")):
            with self.subTest(recipe=recipe):
                self.reference(recipe)
                result = self.check()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(json.loads(result.stdout)['machineChecks']['installAndRun'])

    def test_arbitrary_shell_operators_substitutions_and_extra_blocks_never_execute(self):
        marker = self.project / 'must not exist'
        for recipe in (RECIPE + '\ntouch ' + shlex.quote(str(marker)),
                RECIPE.replace('mkdir', 'mkdir; touch ' + shlex.quote(str(marker)) + '; mkdir'),
                RECIPE.replace('cp ', '$(touch ' + shlex.quote(str(marker)) + ')cp '),
                RECIPE.replace('cp ', '`touch ' + shlex.quote(str(marker)) + '`cp '),
                RECIPE + '\n```\n```sh\ntouch ' + shlex.quote(str(marker)),
                RECIPE.replace('mkdir -p', 'mkdir -p > ' + shlex.quote(str(marker)))):
            with self.subTest(recipe=recipe):
                self.reference(recipe)
                self.assertEqual(self.check().returncode, 2)
                self.assertFalse(marker.exists())

    def test_changed_example_cannot_execute_and_replaced_checker_cannot_self_grade(self):
        self.reference()
        marker = self.project / 'candidate ran'
        (self.project / 'example.py').write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)['machineChecks']['exampleUnchanged'])
        self.assertFalse(marker.exists())
        (self.scratch / 'check-install.py').write_text('raise SystemExit(0)\n')
        result = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout), {'checkerIntegrity': False})

    def test_symlink_fifo_and_oversized_documents_cannot_block_or_pass(self):
        self.document.unlink()
        self.document.symlink_to(self.project / 'example.py')
        self.assertEqual(self.check().returncode, 2)
        self.document.unlink(); os.mkfifo(self.document)
        self.assertEqual(self.check().returncode, 2)
        self.document.unlink(); self.document.write_text('x' * 16385)
        self.assertEqual(self.check().returncode, 2)

    def test_machine_success_does_not_establish_prose_quality(self):
        self.reference()
        self.document.write_text('```sh\n' + RECIPE + '\n```\n')
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['trustedReviewRequired'])
        plan = validate_plan((self.project / 'plan.json').read_text())
        self.assertEqual([check['kind'] for check in plan['steps'][0]['checks']], ['test', 'rubric'])
        self.assertIn('trusted reviewer', plan['success_criteria'][1])

    def test_paired_preview_has_matching_inputs_and_no_state(self):
        plans = []
        for arm in ('routed', 'baseline'):
            project = self.scratch / arm / 'project'
            result = subprocess.run([sys.executable, str(PILOT), 'run', str(self.scratch), arm,
                '--standard', 'synthetic-standard', '--strong', 'synthetic-strong', '--economy', 'synthetic-economy'],
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((self.scratch / arm / 'state').exists())
            plan = validate_plan((project / 'plan.json').read_text()); plan['steps'][0].pop('role'); plans.append(plan)
            for name in ('example.py', 'INSTALL.md', 'checks.json'):
                self.assertEqual((project / name).read_bytes(), (self.project / name).read_bytes())
        self.assertEqual(*plans)

    def test_execution_requires_opt_in_frozen_files_and_fresh_state(self):
        run = self.helper['run']
        args = (self.scratch, 'routed', 'standard', 'strong')
        with patch('subprocess.run', return_value=Mock(returncode=0)) as launch, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'explicit --experimental-tool-approvals'):
                run(*args, True, 'economy')
            launch.assert_not_called()
            run(*args, True, 'economy', tool_approvals=True)
            self.assertIn('--experimental-tool-approvals', launch.call_args.args[0])
            self.assertIn('--execute-workflow', launch.call_args.args[0])
            launch.reset_mock()
            original = self.document.read_bytes(); self.reference()
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                run(*args, True, 'economy', tool_approvals=True)
            self.document.write_bytes(original)
            (self.scratch / 'routed/state').mkdir()
            with self.assertRaisesRegex(ValueError, 'already has state'):
                run(*args, True, 'economy', tool_approvals=True)
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
