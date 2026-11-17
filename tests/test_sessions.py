import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

from modelmate import ProbeError, SessionStore


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'งาน มีช่องว่าง'
        self.project.mkdir()
        self.state = self.base / 'state'
        self.store = SessionStore(self.project, self.state)
        self.addCleanup(self.store.close)

    def path(self, record):
        return self.store.directory / (record['id'] + '.json')

    def test_create_edit_read_and_list_keep_only_metadata(self):
        first = self.store.create('เพิ่มการค้นหา', thread_id='synthetic-thread')
        second = self.store.create('เขียนเอกสาร')
        with self.store.edit(first['id']) as record:
            record.update(criteria=['ทดสอบผ่าน'], step_id='synthetic-step', correction_count=1,
                          state='PAUSED', pause_reason='quota_unknown', summary='ยังไม่ได้ลงมือ')
        stored = self.store.read(first['id'])
        self.assertEqual(stored['project'], str(self.project.resolve()))
        self.assertEqual(stored['correction_count'], 1)
        self.assertEqual(stored['pause_reason'], 'quota_unknown')
        self.assertEqual(stored['thread_id'], 'synthetic-thread')
        self.assertEqual({r['id'] for r in self.store.list_sessions()}, {first['id'], second['id']})
        self.assertNotIn('transcript', stored)
        self.assertNotIn('grants', stored)

    def test_directories_and_files_are_private(self):
        record = self.store.create('task')
        for path, mode in [(self.state / 'modelmate', 0o700), (self.store.directory, 0o700),
                           (self.path(record), 0o600),
                           (self.store.directory / (record['id'] + '.json.lock'), 0o600)]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)

    def test_project_alias_uses_same_identity_other_projects_are_separate(self):
        alias = self.base / 'alias'
        alias.symlink_to(self.project, target_is_directory=True)
        other_project = self.base / 'other';other_project.mkdir()
        record = self.store.create('task')
        with SessionStore(alias, self.state) as alias_store, SessionStore(other_project, self.state) as other:
            self.assertEqual(alias_store.directory, self.store.directory)
            self.assertEqual(alias_store.read(record['id'])['id'], record['id'])
            self.assertNotEqual(other.directory, self.store.directory)
            self.assertEqual(other.list_sessions(), [])

    def test_corrupt_and_future_version_files_are_not_overwritten(self):
        record = self.store.create('task')
        path = self.path(record)
        for payload in [b'broken JSON', json.dumps(dict(record, version=3)).encode()]:
            path.write_bytes(payload)
            with self.assertRaises(ProbeError):
                with self.store.edit(record['id']):
                    self.fail('Invalid metadata must not reach edit body')
            self.assertEqual(path.read_bytes(), payload)

    def test_unknown_fields_and_changed_identity_are_rejected_before_replace(self):
        record = self.store.create('task')
        path = self.path(record);before = path.read_bytes()
        for field, value in [('credentials', 'secret'), ('grants', ['allow']), ('id', 'different'),
                             ('project', '/other'), ('correction_count', True),
                             ('correction_count', 3), ('state', 'UNKNOWN')]:
            with self.subTest(field=field), self.assertRaises(ProbeError):
                with self.store.edit(record['id']) as changed:
                    changed[field] = value
            self.assertEqual(path.read_bytes(), before)

    def test_failed_replace_preserves_old_file_and_removes_temporary(self):
        record = self.store.create('task')
        before = self.path(record).read_bytes()
        with patch('modelmate.os.replace', side_effect=OSError('synthetic failed replace')):
            with self.assertRaises(OSError):
                with self.store.edit(record['id']) as changed:
                    changed['summary'] = 'new summary'
        self.assertEqual(self.path(record).read_bytes(), before)
        self.assertEqual(list(self.store.directory.glob('*.tmp')), [])
        with self.store.edit(record['id']) as changed:
            changed['summary'] = 'retry explicitly'
        self.assertEqual(self.store.read(record['id'])['summary'], 'retry explicitly')

    def test_exception_in_edit_body_does_not_save_partial_changes(self):
        record = self.store.create('task')
        before = self.path(record).read_bytes()
        with self.assertRaises(RuntimeError):
            with self.store.edit(record['id']) as changed:
                changed['goal'] = 'should not save'
                raise RuntimeError('synthetic failure')
        self.assertEqual(self.path(record).read_bytes(), before)

    def test_concurrent_process_writer_is_rejected_then_lock_releases(self):
        record = self.store.create('task')
        code = '''import sys
from modelmate import SessionStore,ProbeError
with SessionStore(sys.argv[1],sys.argv[2]) as store:
 try:
  with store.edit(sys.argv[3]): pass
 except ProbeError as e:
  if 'another writer' not in str(e): raise
  print('busy')
 else: sys.exit(2)
'''
        with self.store.edit(record['id']):
            result = subprocess.run([sys.executable, '-c', code, str(self.project), str(self.state), record['id']],
                                    capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'busy')
        with self.store.edit(record['id']) as changed:
            changed['summary'] = 'lock released'
        self.assertEqual(self.store.read(record['id'])['summary'], 'lock released')

    def test_crash_before_replace_keeps_valid_checkpoint_and_releases_lock(self):
        record = self.store.create('task')
        before = self.path(record).read_bytes()
        code = '''import sys,os,modelmate
with modelmate.SessionStore(sys.argv[1],sys.argv[2]) as store:
 modelmate.os.replace=lambda *a,**kw:os._exit(23)
 with store.edit(sys.argv[3]) as record:record['summary']='not committed'
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.project), str(self.state), record['id']],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 23)
        self.assertEqual(self.path(record).read_bytes(), before)
        self.assertEqual(len(self.store.list_sessions()), 1)
        with self.store.edit(record['id']) as changed:
            changed['summary'] = 'after crash'
        self.assertEqual(self.store.read(record['id'])['summary'], 'after crash')

    def test_session_and_lock_symlinks_cannot_escape_state_directory(self):
        record = self.store.create('task')
        external = self.base / 'external';external.write_text('do not change');external.chmod(0o600)
        path = self.path(record);path.unlink();path.symlink_to(external)
        with self.assertRaises((OSError, ProbeError)):
            self.store.read(record['id'])
        lock = self.store.directory / (record['id'] + '.json.lock')
        lock.unlink();lock.symlink_to(external)
        with self.assertRaises((OSError, ProbeError)):
            with self.store.edit(record['id']):pass
        self.assertEqual(external.read_text(), 'do not change')

    def test_modelmate_root_symlink_is_rejected(self):
        state = self.base / 'symlink-state';state.mkdir()
        target = self.base / 'target';target.mkdir(mode=0o700)
        (state / 'modelmate').symlink_to(target, target_is_directory=True)
        with self.assertRaises((OSError, ProbeError)):
            SessionStore(self.project, state)
        self.assertEqual(list(target.iterdir()), [])

    def test_open_directory_fd_prevents_retargeting_project_state(self):
        record = self.store.create('task')
        directory = self.store.directory
        moved = directory.with_name(directory.name + '-moved')
        directory.rename(moved)
        outside = self.base / 'outside';outside.mkdir()
        directory.symlink_to(outside, target_is_directory=True)
        with self.store.edit(record['id']) as changed:changed['summary'] = 'old directory only'
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(json.loads((moved / (record['id'] + '.json')).read_text())['summary'], 'old directory only')

    def test_invalid_id_and_closed_store_are_rejected(self):
        for value in ['../secret', '/absolute', 'bad', None, 'A' * 32]:
            with self.subTest(value=value), self.assertRaises(ProbeError):
                self.store.read(value)
        self.store.close()
        with self.assertRaises(ProbeError):self.store.list_sessions()

    def test_insecure_file_or_directory_is_not_silently_used(self):
        record = self.store.create('task')
        self.path(record).chmod(0o644)
        with self.assertRaises(ProbeError):self.store.read(record['id'])
        self.store.directory.chmod(0o755)
        with self.assertRaises(ProbeError):SessionStore(self.project, self.state)

    def test_xdg_state_home_is_respected_and_relative_home_rejected(self):
        home = self.base / 'xdg'
        with patch.dict(os.environ, {'XDG_STATE_HOME': str(home)}):
            with SessionStore(self.project) as store:
                self.assertEqual(store.directory.parent, home / 'modelmate')
        with self.assertRaises(ProbeError):SessionStore(self.project, 'relative')

    def test_id_collision_does_not_overwrite_existing_session(self):
        record = self.store.create('first')
        before = self.path(record).read_bytes()
        with patch('uuid.uuid4', return_value=Mock(hex=record['id'])):
            with self.assertRaisesRegex(ProbeError, 'collision'):
                self.store.create('second')
        self.assertEqual(self.path(record).read_bytes(), before)

    def test_checkpoint_requires_lock_and_survives_later_edit_failure(self):
        record = self.store.create('task')
        with self.assertRaisesRegex(ProbeError, 'edit lock'):
            self.store.save(record)
        with self.assertRaises(RuntimeError):
            with self.store.edit(record['id']) as changed:
                changed['summary'] = 'checkpoint'
                self.store.save(changed)
                self.assertEqual(self.store.read(record['id'])['summary'], 'checkpoint')
                changed['summary'] = 'not checkpointed'
                raise RuntimeError('later failure')
        self.assertEqual(self.store.read(record['id'])['summary'], 'checkpoint')

    def test_pause_and_correction_metadata_require_context(self):
        record = self.store.create('task')
        for update in [{'state': 'PAUSED'}, {'correction_count': 1}]:
            with self.assertRaises(ProbeError):
                with self.store.edit(record['id']) as changed:
                    changed.update(update)

    def test_failed_nested_writer_does_not_revoke_outer_lock(self):
        record = self.store.create('task')
        with self.store.edit(record['id']) as changed:
            with self.assertRaisesRegex(ProbeError, 'another writer'):
                with self.store.edit(record['id']):pass
            changed['summary'] = 'outer writer still owns lock'
            self.store.save(changed)
        self.assertEqual(self.store.read(record['id'])['summary'], 'outer writer still owns lock')


if __name__ == '__main__':
    unittest.main()
