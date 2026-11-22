import base64
import errno
import hashlib
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest

from modelmate import ProbeError
from recheck_transport import PrivateUnixEndpoint, UnixWebSocket, private_recheck_server


class PrivateWebSocketTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / 'server.sock'
        self.listener = self.listen(self.path)

    def listen(self, path):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        try:
            listener.bind(str(path))
        except PermissionError as exc:
            if exc.errno in (errno.EPERM, errno.EACCES):
                self.skipTest('Environment forbids binding a private Unix socket.')
            raise
        listener.listen()
        listener.settimeout(2)
        return listener

    def serve(self, handler, *, accept_key=True):
        errors = []

        def server():
            try:
                stream, _ = self.listener.accept()
                with stream, stream.makefile('rb') as reader:
                    stream.settimeout(2)
                    self.assertEqual(reader.readline(), b'GET / HTTP/1.1\r\n')
                    headers = {}
                    while (line := reader.readline()) != b'\r\n':
                        name, value = line.split(b':', 1)
                        headers[name.lower()] = value.strip()
                    key = headers[b'sec-websocket-key']
                    magic = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
                    accept = base64.b64encode(hashlib.sha1(key + magic).digest()) if accept_key else b'invalid'
                    stream.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                                   b'Connection: keep-alive, Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
                    handler(stream, reader)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=server, daemon=True)
        thread.start()

        def join():
            thread.join(3)
            self.assertFalse(thread.is_alive())
            if errors:
                raise errors[0]

        self.addCleanup(join)

    def connect(self, path=None):
        client = UnixWebSocket(PrivateUnixEndpoint(path or self.path, os.getpid()), 2)
        self.addCleanup(client.close)
        return client

    def read_client_frame(self, reader):
        opcode, size = reader.read(2)
        self.assertTrue(size & 0x80)
        size &= 0x7f
        if size == 126:
            size = struct.unpack('!H', reader.read(2))[0]
        mask = reader.read(4)
        payload = bytes(value ^ mask[i % 4] for i, value in enumerate(reader.read(size)))
        return opcode, payload

    def test_upgrade_fragmented_text_and_masked_ping_response(self):
        def handler(stream, reader):
            self.assertEqual(self.read_client_frame(reader), (0x81, b'x' * 140))
            stream.sendall(b'\x01\x02\xe2\x82\x89\x01!\x80\x01\xac')
            self.assertEqual(self.read_client_frame(reader), (0x8a, b'!'))

        self.serve(handler)
        alias = self.directory / 'alias.sock'
        alias.symlink_to(self.path)
        client = self.connect(alias)
        client.send_text('x' * 140, time.monotonic() + 2)
        self.assertEqual(client.receive_text(time.monotonic() + 2), '€')

    def test_invalid_handshake_closes_connection(self):
        self.serve(lambda stream, reader: self.assertEqual(reader.read(1), b''), accept_key=False)
        with self.assertRaisesRegex(ProbeError, 'Invalid .*upgrade'):
            self.connect()

    def test_wrong_peer_and_replaced_socket_are_rejected(self):
        with self.assertRaisesRegex(ProbeError, 'peer identity'):
            PrivateUnixEndpoint(self.path, os.getpid() + 1).connect(1)
        endpoint = PrivateUnixEndpoint(self.path, os.getpid())
        self.path.unlink()
        self.listen(self.path)
        with self.assertRaisesRegex(ProbeError, 'endpoint changed'):
            endpoint.connect(1)

    def test_public_parent_is_rejected(self):
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(ProbeError, 'not private'):
            PrivateUnixEndpoint(self.path, os.getpid())

    def test_masked_server_frame_fails_closed(self):
        self.serve(lambda stream, _: stream.sendall(b'\x81\x80'))
        client = self.connect()
        with self.assertRaisesRegex(ProbeError, 'Invalid .* frame'):
            client.receive_text(time.monotonic() + 2)
        self.assertEqual(client.stream.fileno(), -1)

    def test_message_limit_checked_before_payload_is_read(self):
        self.serve(lambda stream, _: stream.sendall(b'\x81\x7f' + struct.pack('!Q', UnixWebSocket.MAX_MESSAGE + 1)))
        client = self.connect()
        with self.assertRaisesRegex(ProbeError, 'message too large'):
            client.receive_text(time.monotonic() + 2)

    def test_close_frame_is_acknowledged_and_connection_closed(self):
        def handler(stream, reader):
            stream.sendall(b'\x88\x02\x03\xe8')
            self.assertEqual(self.read_client_frame(reader), (0x88, b'\x03\xe8'))

        self.serve(handler)
        client = self.connect()
        with self.assertRaises(EOFError):
            client.receive_text(time.monotonic() + 2)
        self.assertEqual(client.stream.fileno(), -1)

    def test_timeout_closes_connection(self):
        self.serve(lambda stream, reader: self.assertEqual(reader.read(1), b''))
        client = self.connect()
        with self.assertRaises(TimeoutError):
            client.receive_text(time.monotonic() + .05)
        self.assertEqual(client.stream.fileno(), -1)

    def test_owned_server_lifecycle_removes_only_its_socket_directory(self):
        executable = self.directory / 'fake-codex'
        executable.write_text('''#!/usr/bin/env python3
import socket
import sys
import time
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(sys.argv[3].removeprefix('unix://'))
server.listen()
time.sleep(30)
''')
        executable.chmod(0o700)
        with private_recheck_server(2, executable=str(executable)) as endpoint:
            with endpoint.connect(1):
                self.assertEqual(endpoint.peer_pid, endpoint.server.pid)
            directory = endpoint.path.parent
            self.assertTrue(directory.is_dir())
        self.assertFalse(directory.exists())
        self.assertTrue(self.path.is_socket())
        self.assertIsNotNone(endpoint.server.poll())

    def test_owned_server_startup_timeout_terminates_process(self):
        executable = self.directory / 'slow-codex'
        executable.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n')
        executable.chmod(0o700)
        started = time.monotonic()
        with self.assertRaisesRegex(ProbeError, 'startup timed out'):
            with private_recheck_server(.1, executable=str(executable)):
                self.fail('Server without a socket must not be yielded.')
        self.assertLess(time.monotonic() - started, 3)
