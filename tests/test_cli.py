import copy
import io
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

from modelmate import ChatShell, ProbeError, terminal_text
from test_routing import CATALOG, PLAN, POLICY

ROOT = Path(__file__).resolve().parents[1]


class ShellPolicyTests(unittest.TestCase):
    def shell(self):
        output, send = io.StringIO(), Mock()
        return ChatShell(output, send, CATALOG, POLICY), output, send

    def strong_plan(self):
        plan = copy.deepcopy(PLAN)
        plan['steps'][0]['role'] = 'strong'
        return {'type': 'plan', 'raw': json.dumps(plan), 'step_id': 'one'}

    def test_commands_blank_unicode_and_unknown_slash(self):
        shell, out, send = self.shell()
        shell.line('')
        shell.line('/unknown แก้ไฟล์')
        shell.line('/mode auto')
        shell.line('/permissions workspace')
        shell.line('/sessions')
        shell.line('/delete')
        send.assert_not_called()
        self.assertEqual(shell.mode, 'auto')
        self.assertEqual(shell.permissions, 'ask')
        shell.line('ช่วยเขียนเอกสาร')
        self.assertEqual(send.call_args.args[0]['text'], 'ช่วยเขียนเอกสาร')
        shell.line('เพิ่มตัวอย่างด้วย')
        self.assertEqual(send.call_args.args[0]['action'], 'steer')
        self.assertIn('ไม่รู้จักคำสั่ง', out.getvalue())

    def test_model_selection_validates_and_cannot_change_active_work(self):
        shell, out, send = self.shell()
        shell.line('/model synthetic-standard medium')
        self.assertEqual(shell.selection['effort'], 'medium')
        shell.line('/model missing low')
        self.assertEqual(shell.selection['model'], 'synthetic-standard')
        shell.line('task')
        shell.line('/model synthetic-strong low')
        self.assertEqual(shell.selection['model'], 'synthetic-standard')

    def test_only_explicit_token_approval_records_a_model_grant(self):
        shell, out, send = self.shell()
        shell.event(self.strong_plan())
        token = shell.pending['token']
        shell.line('yes')
        shell.line('/approve stale')
        self.assertIsNotNone(shell.pending)
        shell.line('/approve ' + token)
        self.assertIsNone(shell.pending)
        self.assertIn('allow_model', out.getvalue())
        send.assert_not_called()

    def test_mode_change_and_changed_plan_invalidate_pending_token(self):
        shell, out, send = self.shell()
        shell.event(self.strong_plan())
        old = shell.pending['token']
        shell.line('/mode approve_plan')
        self.assertNotEqual(shell.pending['token'], old)
        shell.line('/approve ' + old)
        self.assertIsNotNone(shell.pending)
        shell.line('/decline ' + shell.pending['token'])
        self.assertIsNone(shell.pending)
        self.assertIn('model_selection_declined', out.getvalue())
        send.assert_not_called()

    def test_clarification_cannot_revive_old_grants(self):
        shell, out, send = self.shell()
        event = self.strong_plan()
        shell.event(event)
        shell.line('/approve ' + shell.pending['token'])
        unclear = copy.deepcopy(PLAN)
        unclear['clarifications'] = ['Which file?']
        shell.event(dict(event, raw=json.dumps(unclear)))
        self.assertIsNone(shell.route)
        shell.event(event)
        self.assertIsNotNone(shell.pending)

    def test_cancel_waits_for_confirmation_or_reports_unknown(self):
        shell, out, send = self.shell()
        shell.line('task')
        shell.event(self.strong_plan())
        shell.cancel(exit_after=True)
        self.assertIsNone(shell.pending)
        self.assertFalse(shell.closed)
        self.assertTrue(shell.active)
        self.assertEqual(send.call_args.args[0], {'action': 'cancel'})
        shell.event({'type': 'stopped'})
        self.assertTrue(shell.closed)
        self.assertFalse(shell.active)
        other, out, send = self.shell()
        other.line('task')
        with patch('modelmate.time.monotonic', return_value=100):
            other.cancel(exit_after=True)
        with patch('modelmate.time.monotonic', return_value=106):
            other.tick()
        self.assertEqual(other.exit_code, 130)
        self.assertTrue(other.active)

    def test_untrusted_text_cannot_emit_terminal_controls(self):
        shell, out, send = self.shell()
        shell.event({'type': 'text', 'text': '\x1b[2J\x1b]52;c;secret\x07\r\u202eไทย\x9b'})
        result = out.getvalue()
        for char in ['\x1b', '\x07', '\r', '\u202e', '\x9b']:
            self.assertNotIn(char, result)
        self.assertIn('ไทย', result)
        self.assertEqual(terminal_text('a\nb\tc'), 'a\nb\tc')

    def test_unknown_tool_event_is_never_approved(self):
        shell, out, send = self.shell()
        with self.assertRaises(ProbeError):
            shell.event({'type': 'tool_approval', 'command': 'rm -rf /'})
        send.assert_not_called()


FAKE_CHAT = r'''
import json,os,sys
from modelmate import run_chat
from test_routing import CATALOG,POLICY,PLAN
r,w=os.pipe()
def send(action):
 print('ACTION '+json.dumps(action),flush=True)
 if action['action']=='submit':
  plan=json.loads(json.dumps(PLAN));plan['steps'][0]['role']='strong'
  for event in [{'type':'progress','text':'working'}, {'type':'text','text':'partial text'},
                {'type':'plan','raw':json.dumps(plan),'step_id':'one'}]:
   os.write(w,(json.dumps(event)+'\n').encode())
 elif action['action']=='cancel':
  os.write(w,b'{"type":"stopped"}\n')
try:
 sys.exit(run_chat(sys.stdin,sys.stdout,event_stream=os.fdopen(r,'rb',buffering=0),send=send,
                   catalog=CATALOG,role_policy=POLICY))
finally:
 os.close(w)
'''


class SubprocessShellTests(unittest.TestCase):
    def spawn(self, fake=False):
        source = ('import sys;sys.path.insert(0,' + repr(str(ROOT / 'tests')) + ');' + FAKE_CHAT)
        command = [sys.executable, '-u', '-c', source] if fake else [sys.executable, '-u', str(ROOT / 'modelmate.py')]
        p = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=ROOT)
        def cleanup():
            if p.poll() is None:
                p.kill()
            p.wait(timeout=3)
            for stream in (p.stdin, p.stdout, p.stderr):
                if not stream.closed:
                    stream.close()
        self.addCleanup(cleanup)
        return p

    def read_until(self, p, target):
        data = b''
        end = time.monotonic() + 4
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ)
            while target not in data and time.monotonic() < end:
                if selector.select(max(0, end-time.monotonic())):
                    chunk = os.read(p.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    data += chunk
        self.assertIn(target, data, data.decode(errors='replace'))
        return data

    def test_help_and_default_prompt_never_launch_codex(self):
        result = subprocess.run([sys.executable, str(ROOT / 'modelmate.py'), '--help'],
                                capture_output=True, timeout=3, env=dict(os.environ, PATH='/nonexistent'))
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'live execution is unavailable', result.stdout)
        result = subprocess.run([sys.executable, str(ROOT / 'modelmate.py'), 'ช่วยวางแผน'],
                                input=b'/status\n/exit\n', capture_output=True, timeout=3,
                                env=dict(os.environ, PATH='/nonexistent'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ไม่เริ่ม inference'.encode(), result.stdout)

    def test_pipe_input_blank_commands_and_eof(self):
        p = self.spawn()
        stdout, stderr = p.communicate('\n/status\n/mode auto\n/nope\n'.encode(), timeout=3)
        self.assertEqual(p.returncode, 0, stderr)
        self.assertIn(b'ask_to_escalate', stdout)
        self.assertIn('ไม่รู้จักคำสั่ง'.encode(), stdout)

    def test_input_remains_responsive_during_stream_and_approval(self):
        p = self.spawn(fake=True)
        self.read_until(p, b'/help')
        p.stdin.write('ช่วยทำงาน\n'.encode()); p.stdin.flush()
        self.read_until(p, b'"state": "ask"')
        p.stdin.write(b'/status\n'); p.stdin.flush()
        self.read_until(p, b'"active": true')
        p.stdin.write(b'/exit\n'); p.stdin.flush()
        p.stdin.close()
        p.wait(timeout=3)
        self.assertEqual(p.returncode, 0, p.stderr.read())
        self.assertIn('หยุดงานแล้ว'.encode(), p.stdout.read())

    def test_sigint_while_waiting_approval_requests_cancel(self):
        p = self.spawn(fake=True)
        self.read_until(p, b'/help')
        p.stdin.write(b'task\n'); p.stdin.flush()
        self.read_until(p, b'"state": "ask"')
        p.send_signal(signal.SIGINT)
        self.read_until(p, 'หยุดงานแล้ว'.encode())
        p.stdin.write(b'/exit\n'); p.stdin.flush()
        p.wait(timeout=3)
        self.assertEqual(p.returncode, 0, p.stderr.read())

    def test_eof_during_approval_cancels_without_accepting(self):
        p = self.spawn(fake=True)
        self.read_until(p, b'/help')
        p.stdin.write(b'task\n'); p.stdin.flush()
        self.read_until(p, b'"state": "ask"')
        p.stdin.close()
        p.wait(timeout=3)
        output = p.stdout.read()
        self.assertEqual(p.returncode, 0, p.stderr.read())
        self.assertIn(b'"action": "cancel"', output)
        self.assertNotIn(b'allow_model', output)


if __name__ == '__main__':
    unittest.main()
