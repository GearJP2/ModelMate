"""Regression coverage for multi-turn terminal input and preflight failures."""
import errno
import json
import os
from pathlib import Path
import pty
import selectors
import subprocess
import sys
import time
import tempfile
import unittest
from unittest.mock import patch

from modelmate import Connection, diagnostic_code
from test_live import FAKE


class ReadinessTests(unittest.TestCase):
    def test_consumed_ready_bytes_are_not_disconnect_or_fatal_read(self):
        c = Connection([sys.executable, '-c', 'import time;time.sleep(30)'], 1)
        try:
            self.assertFalse(os.get_blocking(c.process.stdout.fileno()))
            self.assertFalse(os.get_blocking(c.process.stderr.fileno()))
            with patch('modelmate.os.read', side_effect=BlockingIOError(errno.EAGAIN, 'private payload')):
                self.assertTrue(c.read_ready(c.process.stdout))
            self.assertFalse(c.stdout_closed)
            self.assertEqual(c.buffer, b'')
        finally:
            c.close()

    def test_diagnostic_codes_exclude_exception_payload(self):
        self.assertEqual(diagnostic_code(OSError(errno.EIO, 'private path and prompt')), 'OSError:errno=5')
        self.assertEqual(diagnostic_code(ValueError('private data')), 'ValueError')


class PtyConversationTests(unittest.TestCase):
    def test_thai_multi_turn_preflight_error_pauses_then_explicit_retry_succeeds(self):
        # Fail catalog refresh for the second prompt, after a successful first turn.
        fake = FAKE.replace('turn=0', 'turn=0\nmodel_reads=0')
        fake = fake.replace(" method=req.get('method')", """ method=req.get('method')
 if method=='model/list':
  model_reads+=1
  if model_reads==3:
   print(json.dumps({'id':req['id'],'error':{'code':-1,'message':'PRIVATE synthetic failure'}}),flush=True)
   continue""")
        start = fake.index("  print(json.dumps({'id':'tool-request'")
        end = fake.index(" if method=='turn/interrupt':", start)
        fake = fake[:start]+"""  print(json.dumps({'method':'item/completed','params':{'threadId':'thread','turnId':str(turn),
      'item':{'type':'agentMessage','id':'answer','text':'synthetic answer '+str(turn)}}}),flush=True)
  print(json.dumps({'method':'turn/completed','params':{'threadId':'thread',
      'turn':{'id':str(turn),'status':'completed'}}}),flush=True)
  print(json.dumps({'method':'thread/tokenUsage/updated','params':{'threadId':'thread','tokenUsage':{}}}),flush=True)
"""+fake[end:]
        source = '''import sys,modelmate
original=modelmate.LiveChatConnection
fake,trace=sys.argv[1:3]
modelmate.LiveChatConnection=lambda command: original([sys.executable,'-u','-c',fake,trace])
sys.argv=['modelmate.py','--live','--model','synthetic-model']
sys.exit(modelmate.main())
'''
        root = str(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as directory:
            trace = str(Path(directory) / 'trace')
            master, slave = pty.openpty()
            p = subprocess.Popen([sys.executable, '-u', '-c', source, fake, trace], cwd=root,
                                 env=dict(os.environ, XDG_STATE_HOME=str(Path(directory) / 'state')),
                                 stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            os.close(slave)
            received = b''
            buffer = b''
            def read_until(marker):
                nonlocal received, buffer
                end = time.monotonic()+4
                with selectors.DefaultSelector() as selector:
                    selector.register(p.stdout, selectors.EVENT_READ)
                    while marker not in buffer and time.monotonic()<end:
                        if selector.select(max(0,end-time.monotonic())):
                            chunk=os.read(p.stdout.fileno(),65536)
                            if not chunk:break
                            buffer+=chunk;received+=chunk
                self.assertIn(marker,buffer,buffer.decode(errors='replace'))
                cut=buffer.index(marker)+len(marker)
                buffer=buffer[cut:]
            try:
                read_until(b'auto routing')
                os.write(master,'ฟหก\n'.encode())
                read_until('จบ turn'.encode())
                os.write(master,'นายชื่ออะไร\n'.encode())
                read_until(b'[catalog_preflight]')
                self.assertIsNone(p.poll())
                os.write(master,'ลองอีกครั้ง\n'.encode())
                read_until('จบ turn'.encode())
                os.write(master,'ต่ออีกหนึ่งข้อความ\n'.encode())
                read_until('จบ turn'.encode())
                os.write(master,b'/exit\n')
                p.wait(timeout=3)
                self.assertEqual(p.returncode,0,p.stderr.read())
                self.assertNotIn(b'PRIVATE',received)
                messages=[json.loads(line) for line in Path(trace).read_text().splitlines()]
                starts=[m for m in messages if m.get('method')=='turn/start']
                self.assertEqual(len(starts),3)
                sent=[m['params']['input'][0]['text'] for m in starts]
                self.assertEqual(sent,['ฟหก','ลองอีกครั้ง','ต่ออีกหนึ่งข้อความ'])
                self.assertTrue(all(m['params']['threadId']=='thread' for m in starts))
            finally:
                if p.poll() is None:p.kill()
                p.wait(timeout=3)
                os.close(master)
                for stream in (p.stdout,p.stderr):stream.close()


if __name__ == '__main__':
    unittest.main()
