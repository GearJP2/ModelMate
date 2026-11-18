"""The installed artifact is one executable Python file, independent of the repo."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class StandaloneTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.bin=self.root/'ติดตั้ง มีช่องว่าง'/'bin';self.bin.mkdir(parents=True)
        self.binary=self.bin/'sr'
        shutil.copyfile(ROOT/'modelmate.py',self.binary);self.binary.chmod(0o755)
        python_bin=self.root/'python-only';python_bin.mkdir()
        (python_bin/'python3').symlink_to(sys.executable)
        self.project=self.root/'โปรเจกต์ มีช่องว่าง';self.project.mkdir()
        self.state=self.root/'state'
        self.env=dict(os.environ,PATH=str(python_bin),PYTHONPATH='',PYTHONNOUSERSITE='1',
                      XDG_STATE_HOME=str(self.state))

    def run_artifact(self,args,text=None):
        return subprocess.run([str(self.binary)]+args,cwd=self.project,env=self.env,input=text,
                              text=True,capture_output=True,timeout=5)

    def test_help_without_codex_auth_dependencies_or_state(self):
        result=self.run_artifact(['--help'])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--resume-workflow',result.stdout)
        self.assertFalse(self.state.exists())
        self.assertEqual(list(self.bin.iterdir()),[self.binary])

    def test_single_file_offline_preview_without_repo_imports(self):
        result=self.run_artifact(['--workflow',str(ROOT/'examples/explain-lists.json'),
                                  '--role-model','standard=synthetic-model'])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Preview เท่านั้น',result.stdout)
        self.assertNotIn('Session:',result.stdout)
        self.assertFalse(self.state.exists())

    def test_missing_codex_has_actionable_error_in_all_entry_points(self):
        cases=[(['--doctor'],None),(['--live','--model','synthetic-model'],None),
               (['--workflow',str(ROOT/'examples/explain-lists.json'),'--role-model',
                 'standard=synthetic-model','--execute-workflow'],'START\n')]
        for args,text in cases:
            with self.subTest(args=args):
                result=self.run_artifact(args,text)
                self.assertEqual(result.returncode,1,result.stdout)
                self.assertIn('Codex CLI',result.stderr)
                self.assertIn('PATH',result.stderr)
                self.assertIn('command -v codex',result.stderr)
                self.assertNotIn('Traceback',result.stderr)

    def test_quoted_bash_alias_preserves_executable_path_and_arguments(self):
        script='shopt -s expand_aliases\nalias sr=\'"$MODELMATE_TEST_BINARY"\'\neval "sr --help"\n'
        result=subprocess.run(['/bin/bash','--noprofile','--norc','-c',script],cwd=self.project,
            env=dict(self.env,MODELMATE_TEST_BINARY=str(self.binary)),capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--workflow',result.stdout)
        self.assertFalse(self.state.exists())
