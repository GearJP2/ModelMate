"""Local inspection must not create state, restore permissions or start Codex."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from modelmate import ProbeError, SessionStore, WorkflowController, inspect_local_sessions
from test_routing import PLAN, CATALOG, POLICY, QUOTA


class LocalInspectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.project = self.base / 'โปรเจกต์'; self.project.mkdir()
        self.home = self.base / 'state'
        self.env = patch.dict(os.environ, {'XDG_STATE_HOME': str(self.home)})
        self.env.start(); self.addCleanup(self.env.stop)

    def create(self):
        store = SessionStore(self.project)
        self.addCleanup(store.close)
        record = store.create('task', thread_id='private-thread', account_hash=hashlib.sha256(
            QUOTA['accountId'].encode()).hexdigest())
        return store, record['id']

    def inspect(self, sid=None):
        output = io.StringIO()
        with patch('modelmate.subprocess.Popen', side_effect=AssertionError('backend forbidden')):
            inspect_local_sessions(self.project, output, sid)
        return output.getvalue()

    def snapshot(self):
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.home.rglob('*') if p.is_file()}

    def test_missing_store_is_not_created(self):
        self.assertIn('ไม่มี session', self.inspect())
        self.assertFalse(self.home.exists())
        with self.assertRaises(ProbeError):
            self.inspect('a' * 32)
        self.assertFalse(self.home.exists())

    def test_listing_and_readonly_mutation_guards_preserve_files(self):
        store, sid = self.create()
        before = self.snapshot()
        self.assertIn(sid, self.inspect())
        self.assertNotIn('private-thread', self.inspect())
        with SessionStore(self.project, read_only=True) as reader:
            for action in (lambda: reader.create('new'), lambda: reader.save(store.read(sid)),
                           lambda: reader.remove(sid)):
                with self.assertRaisesRegex(ProbeError, 'read-only'):
                    action()
            with self.assertRaisesRegex(ProbeError, 'read-only'):
                with reader.edit(sid):
                    self.fail('read-only edit entered')
        self.assertEqual(before, self.snapshot())

    def test_checkpoint_view_is_historical_and_has_no_authority(self):
        store, sid = self.create()
        controller = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
        with store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY, controller=controller):
            controller.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)
        before = self.snapshot()
        text = self.inspect(sid)
        self.assertIn(PLAN['goal'], text)
        self.assertIn('ผลปัจจุบันยังไม่ทราบ', text)
        self.assertIn('[pending]', text)
        for forbidden in ('private-thread', 'account_hash', '/approve', '/continue'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(before, self.snapshot())

    def test_saved_done_is_only_historical_evidence(self):
        store, sid = self.create()
        controller = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
        with store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY, controller=controller):
            aid = controller.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)['dispatch']['attempt_id']
            controller.finish_attempt(aid, 'completed')
            evidence = controller.record_check(aid, 0, origin='tool', exit_code=0,
                                               reference='synthetic check', finding='observed status')
            controller.evaluate_attempt(aid)
            controller.finish_task({0: [evidence['id']]})
        before = self.snapshot()
        text = self.inspect(sid)
        self.assertIn('สถานะที่บันทึก: DONE', text)
        self.assertIn('ยังไม่ได้ตรวจ backend หรือไฟล์งานใหม่', text)
        self.assertIn('[pass]', text)
        self.assertEqual(before, self.snapshot())

    def test_legacy_session_and_corruption_fail_without_writes(self):
        store, sid = self.create()
        with self.assertRaisesRegex(ProbeError, 'no workflow'):
            self.inspect(sid)
        path = store.directory / (sid + '.json')
        for data in (b'broken JSON', json.dumps(dict(store.read(sid), version=99)).encode()):
            path.write_bytes(data)
            before = self.snapshot()
            with self.assertRaises(ProbeError):
                self.inspect()
            self.assertEqual(before, self.snapshot())

    def test_other_project_does_not_create_state_and_symlink_is_rejected(self):
        store, sid = self.create()
        other = self.base / 'other'; other.mkdir()
        before = self.snapshot()
        inspect_local_sessions(other, io.StringIO())
        self.assertEqual(before, self.snapshot())
        path = store.directory / (sid + '.json')
        target = self.base / 'target'; path.rename(target); path.symlink_to(target)
        with self.assertRaises(OSError):
            self.inspect(sid)
        self.assertTrue(path.is_symlink())

    def test_cli_offline_and_invalid_combinations(self):
        script = str(Path(__file__).resolve().parents[1] / 'modelmate.py')
        env = dict(os.environ, PATH='')
        result = subprocess.run([sys.executable, script, '--sessions'], cwd=self.project,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.home.exists())
        for args in (['--sessions', '--live'], ['--sessions', 'prompt'],
                     ['--show-workflow', 'a' * 32, '--model', 'anything']):
            result = subprocess.run([sys.executable, script] + args, cwd=self.project,
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.home.exists())
