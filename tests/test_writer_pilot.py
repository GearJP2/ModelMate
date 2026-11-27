"""C6 fixtures run developer-written counter writers and owned local crash tests only."""
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
BODY = '''def increment(path):
    path=Path(path)
    descriptor=os.open(str(path)+'.lock',os.O_RDWR|os.O_CREAT|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'a+') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX)
        _before_read()
        value=load(path)
        value['count']+=1
        descriptor,name=tempfile.mkstemp(prefix='.snapshot-',dir=path.parent)
        snapshot=Path(name)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
            _publish(snapshot,path)
            return value
        finally:
            try:snapshot.unlink()
            except FileNotFoundError:pass
'''


class WriterPilotTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root = Path(directory.name) / 'writer pair with spaces';root.mkdir()
        output = subprocess.check_output([sys.executable, str(PILOT), 'prepare', '--case', 'writer'],
            env=dict(os.environ, TMPDIR=str(root)), text=True, timeout=5)
        self.scratch = Path(output.strip())
        self.project = self.scratch / 'routed' / 'project'
        self.original = (self.project / 'writer.py').read_text()
        self.reference = 'import fcntl,tempfile\n' + self.original.split('def increment(', 1)[0] + BODY

    def check(self, source=None):
        if source is not None:(self.project / 'writer.py').write_text(source)
        spec = json.loads((self.project / 'checks.json').read_text())['checks'][0]
        args = shlex.split(spec['command']);args[0] = sys.executable
        return subprocess.run(args, cwd=self.project, capture_output=True, text=True, timeout=20)

    def test_initial_writer_fails_and_reference_survives_real_contention_and_crashes(self):
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)['contention'])
        result = self.check(self.reference)
        self.assertEqual(result.returncode, 0, result.stderr)
        checks = json.loads(result.stdout)
        self.assertEqual(len(checks), 6)
        self.assertTrue(all(checks.values()))
        self.assertEqual({p.name for p in self.project.iterdir()},
                         {'writer.py', 'checkpoint sample.json', 'plan.json', 'checks.json'})

    def test_missing_shared_or_data_inode_locks_cannot_pass(self):
        for name, source, failed in (
                ('none', self.reference.replace('fcntl.flock(guard,fcntl.LOCK_EX)', 'pass'), 'contention'),
                ('shared', self.reference.replace('fcntl.LOCK_EX', 'fcntl.LOCK_SH'), 'contention'),
                ('early_unlock', self.reference.replace('            _publish(snapshot,path)',
                    '            fcntl.flock(guard,fcntl.LOCK_UN)\n            _publish(snapshot,path)'), 'crash_before_publish'),
                ('data_inode', self.reference.replace("str(path)+'.lock'", 'str(path)'), 'contention')):
            with self.subTest(name=name):
                result = self.check(source)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(json.loads(result.stdout)[failed])

    def test_unlinking_sidecar_or_publishing_twice_cannot_pass(self):
        for source in (
                self.reference.replace('            return value',
                    "            Path(str(path)+'.lock').unlink()\n            return value"),
                self.reference.replace('            _publish(snapshot,path)',
                    '            _publish(snapshot,path)\n            _publish(snapshot,path)')):
            result = self.check(source)
            self.assertNotEqual(result.returncode, 0)

    def test_in_place_publication_does_not_satisfy_atomic_commit_observation(self):
        source = self.reference.replace('    os.replace(snapshot, destination)',
            "    Path(destination).write_bytes(Path(snapshot).read_bytes())\n    Path(snapshot).unlink()")
        result = self.check(source)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)['crash_after_publish'])

    def test_orphan_adoption_or_wildcard_cleanup_cannot_pass(self):
        for name, injected in (
                ('adopt', "        for other in path.parent.glob('.snapshot-*'):\n            value=load(other)\n"),
                ('delete', "        for other in path.parent.glob('.snapshot-*'):\n            other.unlink()\n")):
            source = self.reference.replace("        value['count']+=1", injected + "        value['count']+=1")
            with self.subTest(name=name):
                result = self.check(source)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(json.loads(result.stdout)['crash_before_publish'])

    def test_machine_crash_checks_do_not_replace_strong_human_fsync_review(self):
        result = self.check(self.reference.replace('os.fsync(stream.fileno())', 'None'))
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads((self.project / 'plan.json').read_text())
        self.assertEqual(plan['steps'][0]['risk'], 'high')
        self.assertEqual(plan['steps'][1]['role'], 'strong')
        self.assertEqual(plan['steps'][1]['checks'][0]['kind'], 'rubric')
        self.assertIn('fsync', plan['success_criteria'][1])

    def test_same_frozen_plans_preview_without_codex_or_state(self):
        plans, commands = [], []
        for arm in ('routed', 'baseline'):
            output = subprocess.check_output([sys.executable, str(PILOT), 'run', str(self.scratch), arm,
                '--standard', 'synthetic-standard', '--strong', 'synthetic-strong', '--economy', 'synthetic-economy'],
                text=True, timeout=5)
            self.assertIn('synthetic-strong/low', output)
            self.assertFalse((self.scratch / arm / 'state').exists())
            project = self.scratch / arm / 'project'
            for name in ('writer.py', 'checkpoint sample.json'):
                self.assertEqual((project / name).read_bytes(), (self.project / name).read_bytes())
            plan = json.loads((project / 'plan.json').read_text());plan['steps'][0].pop('role');plans.append(plan)
            commands.append(json.loads((project / 'checks.json').read_text())['checks'][0]['command'])
        self.assertEqual(*plans)
        self.assertEqual(*commands)

    def test_changed_inputs_checker_or_started_state_prevent_fresh_launch(self):
        run = runpy.run_path(str(PILOT))['run']
        paths = [self.scratch / 'modelmate.py', self.scratch / 'check-writer.py',
                 *(self.project / name for name in ('writer.py', 'checkpoint sample.json', 'checks.json', 'plan.json'))]
        with patch('subprocess.run') as launch:
            for path in paths:
                content = path.read_bytes();path.write_bytes(content + b'\nchanged')
                try:
                    with self.subTest(name=path.name),self.assertRaises(ValueError):
                        run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True)
                finally:path.write_bytes(content)
            (self.scratch / 'routed' / 'state').mkdir()
            with self.assertRaisesRegex(ValueError, 'never replay'):
                run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True)
            launch.assert_not_called()
        (self.scratch / 'check-writer.py').write_text("from pathlib import Path\nPath('bypass').touch()\n")
        result = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout), {'checkerIntegrity': False})
        self.assertFalse((self.project / 'bypass').exists())

    def test_live_execution_still_needs_explicit_native_tool_opt_in(self):
        run = runpy.run_path(str(PILOT))['run']
        with patch('subprocess.run', return_value=Mock(returncode=0)) as launch,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'explicit --experimental-tool-approvals'):
                run(self.scratch, 'routed', 'standard', 'strong', True, 'economy')
            launch.assert_not_called()
            self.assertEqual(run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True), 0)
            self.assertIn('--execute-workflow', launch.call_args.args[0])
            self.assertIn('--experimental-tool-approvals', launch.call_args.args[0])

    def test_stale_marker_does_not_prove_worker_is_alive(self):
        module = runpy.run_path(str(self.scratch / 'check-writer.py'))
        control = self.project / 'control';control.mkdir();(control / 'read').write_bytes(b'1')
        owner = {'process': Mock(poll=Mock(return_value=0)), 'control': control}
        self.assertFalse(module['await_marker'](owner, 'read'))

    def test_timeouts_private_errors_and_stronger_limits_remain_fail_closed(self):
        result = self.check('while True: pass\n')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['reason'], 'candidate_timeout')
        result = self.check("raise RuntimeError('PRIVATE-ERROR')\n")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('PRIVATE-ERROR', result.stdout)
        module = runpy.run_path(str(self.scratch / 'check-writer.py'));resource = module['resource']
        with patch('resource.getrlimit', return_value=(2048, 4096)),patch('resource.setrlimit') as limit:
            module['output_limit']()
        limit.assert_called_once_with(resource.RLIMIT_FSIZE, (2048, 2048))
