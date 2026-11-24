"""Offline transport checks against small JSONL subprocesses."""
import subprocess
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock

from modelmate import Connection, NativeWorkflowConnection, NativeRecheckConnection, RecheckRecoveryConnection, ProbeError


class ProtocolTests(unittest.TestCase):
    def test_close_discards_buffered_input_instead_of_flushing_to_a_surviving_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            captured = Path(directory) / 'captured'
            source = '''import json,os,sys,time
from pathlib import Path
pid=os.fork()
if pid==0:
 data=sys.stdin.buffer.read()
 Path(sys.argv[1]).write_bytes(data)
 os._exit(0)
print(json.dumps({'method':'synthetic/ready','params':{'pid':pid}}),flush=True)
time.sleep(30)
'''
            c = Connection([sys.executable, '-u', '-c', source, str(captured)], 1)
            self.addCleanup(c.close)
            pid = c.receive(time.monotonic() + 2)['params']['pid']
            def cleanup_reader():
                try:os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:pass
            try:
                c.process.stdin.write(b'UNSENT_ACTION\n')
                c.close()
                deadline = time.monotonic() + 2
                while not captured.exists() and time.monotonic() < deadline:time.sleep(.01)
                self.assertTrue(captured.exists(), 'Reader did not receive EOF.')
                self.assertEqual(captured.read_bytes(), b'')
                self.assertTrue(all(stream.closed for stream in
                                    (c.process.stdin, c.process.stdout, c.process.stderr)))
            finally:
                cleanup_reader()

    def test_standalone_commands_cannot_bypass_workflow_permission_gate(self):
        # No server is needed: unsupported requests must fail before any RPC send.
        for connection_type in (Connection, NativeWorkflowConnection, NativeRecheckConnection, RecheckRecoveryConnection):
            connection = object.__new__(connection_type)
            connection.send = Mock()
            for method in ('command/exec', 'command/exec/write',
                           'command/exec/terminate'):
                with self.subTest(connection=connection_type.__name__, method=method):
                    with self.assertRaisesRegex(ProbeError, 'does not permit'):
                        connection.request(method, {'command': ['printf', 'synthetic']})
            connection.send.assert_not_called()

    def connection(self, source):
        c = Connection([sys.executable, '-u', '-c', source], .5)
        self.addCleanup(c.close)
        return c

    def test_missing_server_cwd_is_not_reported_as_missing_codex(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / 'absent')
            with self.assertRaises(FileNotFoundError) as raised:
                Connection(['codex', 'app-server', '--stdio'], .5, cwd=missing)
            self.assertEqual(raised.exception.filename, missing)

    def test_standalone_runtime_import_does_not_launch_process_or_network(self):
        import tempfile
        import shutil
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'modelmate.py',
                            Path(directory) / 'modelmate.py')
            source = '''import subprocess,socket,selectors
from unittest.mock import patch
with patch.object(subprocess,'Popen',side_effect=AssertionError('process')), \\
     patch.object(socket,'socket',side_effect=AssertionError('network')), \\
     patch.object(selectors,'DefaultSelector',side_effect=AssertionError('selector')):
 import modelmate
assert modelmate.Connection.allowed_methods == {'initialize','account/read','model/list','account/rateLimits/read'}
'''
            result = subprocess.run([sys.executable, '-I', '-c',
                                     'import sys;sys.path.insert(0,sys.argv[1]);' + source, directory],
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stdout, b'')

    def test_unknown_server_request_never_gets_approval(self):
        c = self.connection('''import sys,json
sys.stdin.readline()
print(json.dumps({'id':9,'method':'unknown','params':{}}),flush=True)
''')
        with self.assertRaisesRegex(ProbeError, 'no action was approved'):
            c.request('account/read')

    def test_malformed_protocol_envelopes_fail(self):
        for message in ['[]', '{"id":true,"result":{}}', '{"id":1}',
                        '{"id":1,"result":{},"error":{}}',
                        '{"method":3}', '{"method":"event","params":[]}']:
            with self.subTest(message=message):
                c = self.connection('import sys;sys.stdin.readline();print(' + repr(message) + ',flush=True)')
                with self.assertRaises(ProbeError):
                    c.request('account/read')

    def test_oversized_unterminated_message_is_rejected(self):
        c = self.connection('import os;os.write(1,b"x"*(4*1024*1024+1))')
        with self.assertRaisesRegex(ProbeError, 'size limit'):
            c.receive(time.monotonic() + 5)

    def test_notification_flood_does_not_extend_rpc_deadline(self):
        c = self.connection('''import sys,time
sys.stdin.readline()
while True:
 print('{"method":"notice","params":{}}',flush=True)
 time.sleep(.01)
''')
        started = time.monotonic()
        with self.assertRaisesRegex(ProbeError, 'timed out'):
            c.request('account/read')
        self.assertLess(time.monotonic() - started, 2)

    def test_base_and_verification_use_one_protocol_class(self):
        import doctor
        import verify
        self.assertIs(doctor.Connection, Connection)
        self.assertIs(verify.Connection, Connection)
        self.assertIs(verify.VerificationConnection.__bases__[0], Connection)


if __name__ == '__main__':
    unittest.main()
