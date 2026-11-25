import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from modelmate import ProbeError, run_search_process


class SearchProcessTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def run_child(self, code, **kwargs):
        return run_search_process([sys.executable, '-I', '-S', '-c', code],
            b'public query', cwd=self.root, timeout=kwargs.pop('timeout', 3), **kwargs)

    def test_collects_public_input_and_discards_large_stderr(self):
        result = self.run_child("import os,sys; os.write(2,b'x'*100000); sys.stdout.buffer.write(sys.stdin.buffer.read())")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'public query', b''))

    def test_limits_output_during_collection(self):
        with self.assertRaisesRegex(ProbeError, 'size limit'):
            self.run_child("import os,time; os.write(1,b'x'*100000); time.sleep(30)", output_limit=1024)

    def test_accepts_exact_output_limit_and_records_nonzero_exit(self):
        result = self.run_child("import os; os.write(1,b'x'*1024); raise SystemExit(7)", output_limit=1024)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, b'x' * 1024)

    def test_timeout_covers_open_stdout_and_closed_stdout(self):
        for code in ('import time; time.sleep(30)', 'import os,time; os.close(1); time.sleep(30)'):
            with self.subTest(code=code), self.assertRaises(subprocess.TimeoutExpired):
                self.run_child(code, timeout=.2)

    def test_timeout_kills_descendant_holding_output_pipe(self):
        child_file = self.root / 'child.pid'
        code = ("import subprocess,sys; from pathlib import Path; "
                "child=subprocess.Popen([sys.executable,'-I','-S','-c','import time; time.sleep(30)']); "
                "Path('child.pid').write_text(str(child.pid))")
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_child(code, timeout=.5)
        pid = int(child_file.read_text())
        deadline = time.monotonic() + 2
        while True:
            try:
                state = Path('/proc', str(pid), 'stat').read_text().split(') ')[1][0]
            except FileNotFoundError:
                state = None
            if state in (None, 'Z') or time.monotonic() >= deadline:
                break
            time.sleep(.01)
        self.assertIn(state, (None, 'Z'))

    def test_invalid_limits_never_launch(self):
        for kwargs in ({'timeout': 0}, {'timeout': float('nan')}, {'output_limit': True},
                       {'output_limit': 0}, {'output_limit': 65537}):
            with self.subTest(kwargs=kwargs), patch('modelmate.subprocess.Popen') as launch:
                with self.assertRaises(ProbeError):
                    self.run_child('pass', **kwargs)
                launch.assert_not_called()

    def test_launch_clears_environment_and_inherited_private_fd(self):
        private = self.root / 'private'
        private.write_bytes(b'synthetic secret')
        with private.open('rb') as stream:
            os.set_inheritable(stream.fileno(), True)
            code = ("import os; "
                    "assert not os.environ.get('MODELMATE_SYNTHETIC_SECRET'); "
                    f"assert not os.path.exists('/proc/self/fd/{stream.fileno()}'); "
                    "print('clean')")
            with patch.dict(os.environ, {'MODELMATE_SYNTHETIC_SECRET': 'synthetic private value'}):
                result = self.run_child(code)
        self.assertEqual((result.returncode, result.stdout), (0, b'clean\n'))
