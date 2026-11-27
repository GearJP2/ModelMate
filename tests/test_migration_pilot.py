"""C5 migration evaluation uses developer-written candidates and real local write faults."""
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
REFERENCE = '''import json,os,tempfile
from pathlib import Path

def _publish(snapshot,destination):
    os.replace(snapshot,destination)

def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate key')
        result[key]=value
    return result

def _read(path):
    data=json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=_unique)
    if not isinstance(data,dict) or type(data.get('version')) is not int or data['version'] not in (1,2):
        raise ValueError('version')
    version=data['version'];field='items' if version==1 else 'records';count='count' if version==1 else 'quantity'
    if set(data)!={'version',field} or not isinstance(data[field],list):raise ValueError('schema')
    records=[]
    for row in data[field]:
        if (not isinstance(row,dict) or set(row)!={'name',count} or not isinstance(row['name'],str)
                or not row['name'].strip() or type(row[count]) is not int or row[count]<0):
            raise ValueError('record')
        records.append({'name':row['name'],'quantity':row[count]})
    return version,{'version':2,'records':records}

def load(path):
    return _read(Path(path))[1]

def migrate(path):
    path=Path(path)
    version,value=_read(path)
    if version==2:return value
    fd,name=tempfile.mkstemp(prefix='.snapshot-',dir=path.parent)
    snapshot=Path(name)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False)
            stream.write('\\n');stream.flush();os.fsync(stream.fileno())
        _publish(snapshot,path)
        return value
    finally:
        try:snapshot.unlink()
        except FileNotFoundError:pass
'''


class MigrationPilotTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root = Path(directory.name) / 'migration pair with spaces';root.mkdir()
        output = subprocess.check_output([sys.executable, str(PILOT), 'prepare', '--case', 'migration'],
            env=dict(os.environ, TMPDIR=str(root)), text=True, timeout=5)
        self.scratch = Path(output.strip())
        self.project = self.scratch / 'routed' / 'project'

    def check(self, source=None):
        if source is not None:(self.project / 'store.py').write_text(source)
        spec = json.loads((self.project / 'checks.json').read_text())['checks'][0]
        args = shlex.split(spec['command']);args[0] = sys.executable
        return subprocess.run(args, cwd=self.project, capture_output=True, text=True, timeout=20)

    def test_baseline_fails_and_reference_preserves_data_under_real_faults(self):
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)['migrate_legacy'])
        result = self.check(REFERENCE)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(len(report), 37)
        self.assertTrue(all(report.values()))
        self.assertTrue(report['write_failure'])
        self.assertTrue(report['publish_failure'])
        self.assertTrue(report['current_noop'])
        self.assertEqual({p.name for p in self.project.iterdir()},
                         {'store.py', 'legacy sample.json', 'plan.json', 'checks.json'})
        relative = REFERENCE.replace('_publish(snapshot,path)',
            '_publish(snapshot,Path(os.path.relpath(path,Path.cwd())))')
        result = self.check(relative)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_destructive_rewrite_and_retry_mutants_cannot_pass(self):
        for name, source, failed in (
                ('truncate_first', REFERENCE.replace('    fd,name=tempfile.mkstemp',
                    "    path.write_text('truncated')\n    fd,name=tempfile.mkstemp"), 'publish_failure'),
                ('ignore_publish_error', REFERENCE.replace('        _publish(snapshot,path)',
                    '        try:_publish(snapshot,path)\n        except OSError:pass'), 'publish_failure'),
                ('retry_publish', REFERENCE.replace('        _publish(snapshot,path)',
                    '        try:_publish(snapshot,path)\n        except OSError:_publish(snapshot,path)'), 'publish_failure'),
                ('rewrite_v2', REFERENCE.replace('    if version==2:return value',
                    "    if version==2:\n        path.write_text(json.dumps(value))\n        return value"), 'current_noop'),
                ('leak_snapshot', REFERENCE.replace('try:snapshot.unlink()', 'try:pass'), 'publish_failure')):
            with self.subTest(name=name):
                result = self.check(source)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(json.loads(result.stdout)[failed])

    def test_green_fault_checks_still_need_strong_and_trusted_source_review(self):
        result = self.check(REFERENCE.replace('stream.flush();os.fsync(stream.fileno())', 'stream.flush()'))
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads((self.project / 'plan.json').read_text())
        self.assertEqual(plan['steps'][0]['risk'], 'high')
        self.assertEqual(plan['steps'][1]['role'], 'strong')
        self.assertEqual(plan['steps'][1]['kind'], 'review')
        self.assertEqual(plan['steps'][1]['checks'][0]['kind'], 'rubric')
        self.assertIn('fsync', plan['success_criteria'][1])

    def test_paired_frozen_sources_preview_without_authentication_or_state(self):
        plans, commands = [], []
        for arm in ('routed', 'baseline'):
            output = subprocess.check_output([sys.executable, str(PILOT), 'run', str(self.scratch), arm,
                '--standard', 'synthetic-standard', '--strong', 'synthetic-strong', '--economy', 'synthetic-economy'],
                text=True, timeout=5)
            self.assertIn('synthetic-strong/low', output)
            self.assertFalse((self.scratch / arm / 'state').exists())
            project = self.scratch / arm / 'project'
            for name in ('store.py', 'legacy sample.json'):
                self.assertEqual((project / name).read_bytes(), (self.project / name).read_bytes())
            plan = json.loads((project / 'plan.json').read_text());plan['steps'][0].pop('role');plans.append(plan)
            commands.append(json.loads((project / 'checks.json').read_text())['checks'][0]['command'])
        self.assertEqual(*plans)
        self.assertEqual(*commands)

    def test_checker_or_legacy_input_changes_cannot_supply_a_pass(self):
        (self.project / 'legacy sample.json').write_text('changed')
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout), {'inputUnchanged': False})
        legacy = self.project / 'legacy sample.json'
        module = runpy.run_path(str(self.scratch / 'check-migration.py'))
        backing = self.project / 'alternate.json';backing.write_bytes(module['LEGACY_BYTES'])
        legacy.unlink();legacy.symlink_to(backing)
        result = self.check()
        self.assertEqual(json.loads(result.stdout), {'inputUnchanged': False})
        legacy.unlink();os.mkfifo(legacy,0o600)
        result = self.check()
        self.assertEqual(json.loads(result.stdout), {'inputUnchanged': False})
        (self.scratch / 'check-migration.py').write_text("from pathlib import Path\nPath('bypass').touch()\n")
        result = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout), {'checkerIntegrity': False})
        self.assertFalse((self.project / 'bypass').exists())

    def test_modified_sources_specs_or_existing_state_block_launch(self):
        run = runpy.run_path(str(PILOT))['run']
        paths = [self.scratch / 'modelmate.py', self.scratch / 'check-migration.py',
                 *(self.project / name for name in ('store.py', 'legacy sample.json', 'checks.json', 'plan.json'))]
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

    def test_native_execution_remains_explicitly_opted_in(self):
        run = runpy.run_path(str(PILOT))['run']
        with patch('subprocess.run', return_value=Mock(returncode=0)) as launch,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'explicit --experimental-tool-approvals'):
                run(self.scratch, 'routed', 'standard', 'strong', True, 'economy')
            launch.assert_not_called()
            self.assertEqual(run(self.scratch, 'routed', 'standard', 'strong', True, 'economy', tool_approvals=True), 0)
            self.assertIn('--execute-workflow', launch.call_args.args[0])
            self.assertIn('--experimental-tool-approvals', launch.call_args.args[0])

    def test_timeout_and_failed_child_stop_without_exposing_output(self):
        module = runpy.run_path(str(self.scratch / 'check-migration.py'))
        for observed in (None, (1, b'', b'PRIVATE-ERROR')):
            observe = Mock(return_value=observed);output = io.StringIO()
            with contextlib.chdir(self.project),patch.dict(module['main'].__globals__, observe=observe),contextlib.redirect_stdout(output):
                self.assertEqual(module['main'](), 2)
            observe.assert_called_once()
            self.assertEqual(json.loads(output.getvalue())['state'], 'unverified')
            self.assertNotIn('PRIVATE-ERROR', output.getvalue())
        result = self.check('while True: pass\n')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['reason'], 'candidate_timeout')

    def test_checker_does_not_increase_stronger_host_file_limits(self):
        module = runpy.run_path(str(self.scratch / 'check-migration.py'));resource = module['resource']
        with patch('resource.getrlimit', return_value=(2048, 4096)),patch('resource.setrlimit') as limit:
            module['output_limit']()
        limit.assert_called_once_with(resource.RLIMIT_FSIZE, (2048, 2048))

    def test_nonregular_published_files_cannot_block_parent_observation(self):
        source = REFERENCE.replace('    os.replace(snapshot,destination)',
            '    os.unlink(snapshot)\n    os.mkfifo(snapshot,0o600)\n    os.replace(snapshot,destination)')
        result = self.check(source)
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['checks']['migrate_legacy'])
        self.assertEqual(report['reason'], 'candidate_timeout')
