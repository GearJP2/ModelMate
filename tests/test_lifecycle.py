"""Offline lifecycle checks. Synthetic protocol replies do not prove live resume."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import selectors
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import ChatShell, LiveChatConnection, ProbeError, SessionStore
from test_live import CATALOG, FAKE


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'งาน มีช่องว่าง'
        self.project.mkdir()
        self.store = SessionStore(self.project, Path(self.temp.name) / 'state')
        self.addCleanup(self.store.close)
        self.quota = {'state': 'allow', 'reason': 'included_usage_available',
                      'account_id': 'synthetic-account', 'checked_at': 100}
        for name, value in [('inspect', {'models': CATALOG}), ('read_models', CATALOG),
                            ('refresh_quota', self.quota)]:
            mock = patch('modelmate.' + name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.thread = {'id': 'synthetic-thread', 'cwd': str(self.project), 'ephemeral': False,
                       'modelProvider': 'openai', 'status': {'type': 'idle'}, 'parentThreadId': None}
        self.history = []
        self.extra_threads = []

    def reply(self, method, params):
        if method in ('thread/start', 'thread/read'):
            return {'thread': dict(self.thread)}
        if method == 'thread/resume':
            return {'thread': dict(self.thread), 'approvalPolicy': 'on-request',
                    'approvalsReviewer': 'user', 'sandbox': {'type': 'readOnly'}}
        if method == 'thread/turns/list':
            return {'data': self.history}
        if method == 'thread/list':
            return {'data': [dict(self.thread)] + self.extra_threads, 'nextCursor': None}
        if method == 'thread/delete':
            return {}
        raise AssertionError(method)

    def backend(self, session_id=None):
        c = LiveChatConnection([sys.executable, '-c', 'import time;time.sleep(30)'], 1)
        self.addCleanup(c.close)
        c.request = Mock(side_effect=self.reply)
        c.send = Mock()
        c.connect('synthetic-model', 'low', self.project, store=self.store, session_id=session_id)
        c.shell = ChatShell(io.StringIO(), c.action, CATALOG)
        c.shell.selection = c.selection
        c.shell.sessions = c.session_command
        c.shell.live = True
        return c

    def finish(self, c, status='completed'):
        c.handle_event({'method': 'turn/started', 'params': {
            'threadId': c.thread_id, 'turn': {'id': 'synthetic-turn'}}})
        c.handle_event({'method': 'turn/completed', 'params': {
            'threadId': c.thread_id, 'turn': {'id': 'synthetic-turn', 'status': status}}})

    def test_persistent_thread_and_pre_dispatch_checkpoint_with_full_lifetime_lock(self):
        c = self.backend()
        self.assertFalse(c.request.call_args.args[1]['ephemeral'])
        sid = c.record['id']
        def inspect_send(message):
            if message.get('method') == 'turn/start':
                saved = self.store.read(sid)
                self.assertEqual(saved['state'], 'RUNNING')
                self.assertEqual(saved['goal'], 'synthetic goal')
                self.assertEqual(saved['thread_id'], c.thread_id)
        c.send.side_effect = inspect_send
        c.shell.line('synthetic goal')
        with self.assertRaisesRegex(ProbeError, 'another writer'):
            with self.store.edit(sid):
                self.fail('Open live chat must retain exclusive ownership')
        self.finish(c)
        self.assertEqual(self.store.read(sid)['state'], 'UNVERIFIED')
        c.close()
        with self.store.edit(sid) as record:
            self.assertEqual(record['turn_id'], 'synthetic-turn')

    def test_fresh_resume_never_starts_or_replays_a_turn_and_preserves_counters(self):
        c = self.backend()
        sid = c.record['id']
        c.checkpoint(step_id='step', correction_count=2, state='UNVERIFIED')
        c.close()
        resumed = self.backend(sid)
        resumed.send.assert_not_called()
        self.assertNotIn('turn/start', [x.args[0] for x in resumed.request.call_args_list])
        self.assertEqual(resumed.record['correction_count'], 2)
        self.assertIsNone(resumed.shell.pending)
        self.assertEqual(resumed.record['permission_profile'], 'read_only')
        options = next(x.args[1] for x in resumed.request.call_args_list if x.args[0] == 'thread/resume')
        self.assertEqual(options['sandbox'], 'read-only')
        self.assertEqual(options['config']['web_search'], 'disabled')

    def test_crash_before_or_after_tool_result_requires_explicit_recovery_ack(self):
        for received_result in (False, True):
            c = self.backend()
            sid = c.record['id']
            c.shell.line('synthetic tool task')
            c.handle_event({'method': 'turn/started', 'params': {
                'threadId': c.thread_id, 'turn': {'id': 'synthetic-turn'}}})
            c.handle_event({'id': 'tool', 'method': 'item/commandExecution/requestApproval', 'params': {
                'threadId': c.thread_id, 'turnId': c.turn_id, 'itemId': 'command',
                'command': 'printf synthetic', 'cwd': str(self.project)}})
            if received_result:
                c.shell.line('/approve ' + c.shell.pending['token'])
                c.handle_event({'method': 'item/completed', 'params': {
                    'threadId': c.thread_id, 'turnId': c.turn_id,
                    'item': {'id': 'command', 'type': 'commandExecution', 'status': 'completed', 'exitCode': 0}}})
            c.close()
            self.history = [{'id': 'synthetic-turn', 'status': 'completed', 'items': []}]
            resumed = self.backend(sid)
            resumed.shell.line('must not replay')
            resumed.send.assert_not_called()
            resumed.shell.line('/acknowledge stale')
            self.assertIsNotNone(resumed.recovery_token)
            resumed.shell.line('/acknowledge ' + resumed.recovery_token)
            self.assertIsNone(resumed.recovery_token)
            resumed.send.assert_not_called()
            self.assertEqual(self.store.read(sid)['state'], 'UNVERIFIED')
            resumed.shell.line('explicit new instruction')
            self.assertEqual(resumed.send.call_args.args[0]['method'], 'turn/start')
            resumed.close()

    def test_account_mismatch_legacy_or_missing_thread_never_resumes(self):
        c = self.backend();sid = c.record['id'];c.close()
        for change in ({'account_hash': '0' * 64}, {'thread_id': None}):
            with self.store.edit(sid) as record:
                original = dict(record);record.update(change)
            with self.assertRaises(ProbeError):
                self.backend(sid)
            with self.store.edit(sid) as record:
                record.update(original)
        legacy = self.store.create('legacy task', thread_id='synthetic-thread')
        with self.assertRaisesRegex(ProbeError, 'legacy'):
            self.backend(legacy['id'])
        original_reply = self.reply
        def missing(method, params):
            if method == 'thread/read':
                raise ProbeError('thread/read failed')
            return original_reply(method, params)
        with patch.object(self, 'reply', side_effect=missing):
            with self.assertRaises(ProbeError):
                self.backend(sid)
        self.assertEqual(self.store.read(sid)['thread_id'], 'synthetic-thread')

    def test_active_wrong_project_or_weaker_permissions_refuses_resume(self):
        c = self.backend();sid = c.record['id'];c.close()
        for field, value in [('status', {'type': 'active'}), ('cwd', '/other')]:
            old = self.thread[field];self.thread[field] = value
            with self.assertRaises(ProbeError):self.backend(sid)
            self.thread[field] = old
        reply = self.reply
        def weaker(method, params):
            result = reply(method, params)
            if method == 'thread/resume':result['sandbox'] = {'type': 'workspaceWrite'}
            return result
        with patch.object(self, 'reply', side_effect=weaker):
            with self.assertRaisesRegex(ProbeError, 'permissions'):self.backend(sid)

    def test_disconnect_before_response_retains_unknown_state(self):
        c = self.backend()
        c.send.side_effect = BrokenPipeError('synthetic disconnect')
        with self.assertRaises(BrokenPipeError):c.shell.line('synthetic task')
        sid = c.record['id'];c.close()
        self.assertEqual(self.store.read(sid)['state'], 'RUNNING')
        resumed = self.backend(sid)
        self.assertIsNotNone(resumed.recovery_token)
        resumed.send.assert_not_called()

    def test_confirmed_interrupt_is_saved_but_interrupt_ack_alone_is_not_stopped(self):
        c = self.backend()
        c.shell.line('task')
        c.turn_id = 'synthetic-turn'
        c.shell.cancel(exit_after=True)
        self.assertEqual(self.store.read(c.record['id'])['state'], 'RUNNING')
        self.assertFalse(c.shell.closed)
        self.finish(c, 'interrupted')
        self.assertTrue(c.shell.closed)
        self.assertEqual(self.store.read(c.record['id'])['pause_reason'], 'user_pause')

    def test_delete_needs_fresh_exact_confirmation_and_never_deletes_work_files(self):
        c = self.backend();sid = c.record['id']
        work = self.project / 'work.txt';work.write_text('keep')
        c.shell.line('/delete')
        token = c.delete_proposal['token']
        self.assertNotIn('thread/delete', [x.args[0] for x in c.request.call_args_list])
        c.shell.line('/confirm-delete stale')
        self.assertTrue((c.store.directory / (sid + '.json')).exists())
        c.shell.line('/delete')
        self.assertNotEqual(c.delete_proposal['token'], token)
        c.shell.line('/confirm-delete ' + c.delete_proposal['token'])
        self.assertFalse((c.store.directory / (sid + '.json')).exists())
        self.assertEqual(work.read_text(), 'keep')
        self.assertTrue(c.shell.closed)
        self.assertEqual(sum(x.args[0] == 'thread/delete' for x in c.request.call_args_list), 1)

    def test_remote_delete_failure_preserves_metadata_and_blocks_new_work(self):
        c = self.backend();sid = c.record['id']
        reply = self.reply
        def failing(method, params):
            if method == 'thread/delete':raise ProbeError('remote deletion failed')
            return reply(method, params)
        c.request.side_effect = failing
        c.shell.line('/delete')
        c.shell.line('/confirm-delete ' + c.delete_proposal['token'])
        self.assertEqual(self.store.read(sid)['deletion_state'], 'requested')
        c.shell.line('must not start a turn')
        c.send.assert_not_called()
        self.assertFalse(c.shell.closed)

    def test_remote_success_local_cleanup_failure_can_retry_without_remote_redelete(self):
        c = self.backend();sid = c.record['id']
        c.shell.line('/delete')
        with patch.object(self.store, 'remove', side_effect=OSError('synthetic failure')):
            c.shell.line('/confirm-delete ' + c.delete_proposal['token'])
        self.assertEqual(self.store.read(sid)['deletion_state'], 'remote_deleted')
        c.shell.line('/delete')
        c.shell.line('/confirm-delete ' + c.delete_proposal['token'])
        self.assertEqual(sum(x.args[0] == 'thread/delete' for x in c.request.call_args_list), 1)
        self.assertFalse((self.store.directory / (sid + '.json')).exists())

    def test_scope_change_and_active_descendant_invalidate_delete(self):
        c = self.backend()
        c.shell.line('/delete')
        token = c.delete_proposal['token']
        child = dict(self.thread, id='child', parentThreadId=c.thread_id)
        self.extra_threads = [child]
        c.shell.line('/confirm-delete ' + token)
        self.assertNotIn('thread/delete', [x.args[0] for x in c.request.call_args_list])
        c.shell.line('/delete')
        self.assertEqual(len(c.delete_proposal['tree']), 2)
        child['status'] = {'type': 'active'}
        c.shell.line('/confirm-delete ' + c.delete_proposal['token'])
        self.assertNotIn('thread/delete', [x.args[0] for x in c.request.call_args_list])

    def test_spawn_source_ancestry_is_used_but_unrelated_review_does_not_block_delete(self):
        c = self.backend()
        self.extra_threads = [dict(self.thread, id='review', source={'subAgent': 'review'}),
            dict(self.thread, id='child', source={'subAgent': {
                'thread_spawn': {'parent_thread_id': c.thread_id, 'depth': 1}}})]
        c.shell.line('/delete')
        self.assertEqual({row['thread_id'] for row in c.delete_proposal['tree']}, {c.thread_id, 'child'})
        self.extra_threads[1]['source']['subAgent']['thread_spawn']['parent_thread_id'] = None
        c.shell.line('/confirm-delete ' + c.delete_proposal['token'])
        self.assertNotIn('thread/delete', [x.args[0] for x in c.request.call_args_list])

    def test_delete_still_available_when_included_quota_exhausted(self):
        self.quota.update(state='pause', reason='quota_exhausted')
        c = self.backend()
        c.shell.line('/delete')
        c.shell.line('/confirm-delete ' + c.delete_proposal['token'])
        self.assertTrue(c.shell.closed)

    def test_schema_v2_rejects_invalid_account_or_deletion_receipt_without_overwrite(self):
        c = self.backend();sid = c.record['id']
        path = self.store.directory / (sid + '.json')
        before = path.read_bytes()
        for update in [{'account_hash': 'raw-account'}, {'deletion_state': 'done'}, {'turn_id': []}]:
            with self.assertRaises(ProbeError):
                self.store.save(dict(c.record, **update))
            self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(ProbeError, 'lock'):
            self.store.remove('0' * 32)

    def test_remote_success_lost_receipt_keeps_checkpoint_and_never_assumes_missing_means_deleted(self):
        c = self.backend();sid = c.record['id']
        c.shell.line('/delete')
        save = self.store.save
        def fail_receipt(record):
            if record['deletion_state'] == 'remote_deleted':raise OSError('lost receipt')
            save(record)
        with patch.object(self.store, 'save', side_effect=fail_receipt):
            c.shell.line('/confirm-delete ' + c.delete_proposal['token'])
        self.assertEqual(self.store.read(sid)['deletion_state'], 'requested')
        c.close()
        other = self.backend()
        reply = self.reply
        def missing(method, params):
            if method == 'thread/read':raise ProbeError('thread/read failed')
            return reply(method, params)
        other.request.side_effect = missing
        other.shell.line('/delete ' + sid)
        self.assertIsNone(other.delete_proposal)
        self.assertEqual(self.store.read(sid)['deletion_state'], 'requested')

    def test_cancel_or_new_work_invalidates_deletion_confirmation(self):
        c = self.backend()
        c.shell.line('/delete');token = c.delete_proposal['token']
        c.shell.line('/cancel')
        c.shell.line('/confirm-delete ' + token)
        self.assertNotIn('thread/delete', [x.args[0] for x in c.request.call_args_list])
        c.shell.line('/delete')
        c.shell.line('new work')
        self.assertIsNone(c.delete_proposal)

    def test_actual_process_death_releases_lock_and_saved_running_requires_recovery(self):
        c = self.backend();sid = c.record['id'];c.close()
        source = '''import os,sys
from modelmate import SessionStore
with SessionStore(sys.argv[1],sys.argv[2]) as store:
 with store.edit(sys.argv[3]) as record:
  record['state']='RUNNING'
  store.save(record)
  os._exit(23)
'''
        result = subprocess.run([sys.executable, '-c', source, str(self.project),
                                 str(self.store.directory.parent.parent), sid], timeout=5)
        self.assertEqual(result.returncode, 23)
        resumed = self.backend(sid)
        self.assertIsNotNone(resumed.recovery_token)
        resumed.send.assert_not_called()


class RestartedCliTests(unittest.TestCase):
    def test_chat_exit_restart_resume_and_delete_with_synthetic_backend(self):
        fake = FAKE.replace("elif method=='thread/start': result={'thread':{'id':'thread'}}", """elif method=='thread/start':
  thread={'id':'thread','cwd':req['params']['cwd'],'ephemeral':False,
          'modelProvider':'openai','status':{'type':'idle'},'parentThreadId':None}
  with open(trace+'.thread','w') as f:json.dump(thread,f)
  result={'thread':thread}
 elif method in ('thread/read','thread/resume'):
  with open(trace+'.thread') as f:thread=json.load(f)
  result={'thread':thread,'approvalPolicy':'on-request','approvalsReviewer':'user',
          'sandbox':{'type':'readOnly'}}
 elif method=='thread/turns/list':result={'data':[]}
 elif method=='thread/list':
  with open(trace+'.thread') as f:thread=json.load(f)
  result={'data':[thread],'nextCursor':None}
 elif method=='thread/delete':result={} """)
        source = '''import sys,modelmate
original=modelmate.LiveChatConnection
fake,trace=sys.argv[1:3]
modelmate.LiveChatConnection=lambda command:original([sys.executable,'-u','-c',fake,trace])
sys.argv=['modelmate.py','--live','--model','synthetic-model']+sys.argv[3:]
sys.exit(modelmate.main())
'''
        root = str(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, XDG_STATE_HOME=str(Path(directory) / 'state'))
            trace = str(Path(directory) / 'trace')
            def start(extra):
                p = subprocess.Popen([sys.executable, '-u', '-c', source, fake, trace] + extra,
                    cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                def cleanup():
                    if p.poll() is None:p.kill()
                    p.wait(timeout=3)
                    for stream in (p.stdin, p.stdout, p.stderr):stream.close()
                self.addCleanup(cleanup)
                return p
            def read_until(p, target):
                buffer = b'';deadline = time.monotonic() + 4
                with selectors.DefaultSelector() as selector:
                    selector.register(p.stdout, selectors.EVENT_READ)
                    while target not in buffer and time.monotonic() < deadline:
                        if selector.select(max(0, deadline - time.monotonic())):
                            chunk = os.read(p.stdout.fileno(), 65536)
                            if not chunk:break
                            buffer += chunk
                self.assertIn(target, buffer, buffer.decode(errors='replace'))
                return buffer.decode()
            def line(p, text):
                p.stdin.write((text + '\n').encode());p.stdin.flush()
            first = start([])
            read_until(first, 'โมเดลที่ร้องขอ'.encode())
            line(first, 'synthetic first turn')
            token = read_until(first, b'/decline ').split('/approve ')[-1].split()[0]
            line(first, '/decline ' + token)
            read_until(first, 'จบ turn'.encode())
            line(first, '/exit');first.wait(timeout=3)
            self.assertEqual(first.returncode, 0, first.stderr.read())
            with SessionStore(root, env['XDG_STATE_HOME']) as store:
                record, = store.list_sessions()
                self.assertEqual(record['state'], 'UNVERIFIED')
            second = start(['--resume', record['id']])
            read_until(second, 'โมเดลที่ร้องขอ'.encode())
            line(second, '/sessions')
            read_until(second, record['id'].encode())
            line(second, '/delete')
            token = read_until(second, b'/confirm-delete ').split('/confirm-delete ')[-1].split()[0]
            line(second, '/confirm-delete ' + token);second.wait(timeout=3)
            self.assertEqual(second.returncode, 0, second.stderr.read())
            with SessionStore(root, env['XDG_STATE_HOME']) as store:
                self.assertEqual(store.list_sessions(), [])
            requests = [json.loads(row) for row in Path(trace).read_text().splitlines()]
            methods = [row.get('method') for row in requests]
            self.assertEqual(methods.count('thread/start'), 1)
            self.assertEqual(methods.count('thread/resume'), 1)
            self.assertEqual(methods.count('turn/start'), 1)
            self.assertEqual(methods.count('thread/delete'), 1)


if __name__ == '__main__':
    unittest.main()
