"""Standalone transport spike for the private recheck App Server."""

import base64
import hashlib
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import tempfile
import time
from contextlib import contextmanager

from modelmate import ProbeError


class PrivateUnixEndpoint:
    """Pin both the socket inode and the peer of an already-owned server."""

    def __init__(self, path, peer_pid=None, *, server=None):
        self.path = Path(path)
        self.peer_pid = peer_pid
        self.server = server
        self.target, self.identity = self._inspect()

    def _inspect(self):
        target = self.path.resolve(strict=True)
        uid = os.getuid()
        for directory in {self.path.parent, target.parent}:
            info = directory.stat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
                raise ProbeError('App Server socket directory is not private.')
        info = target.stat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid:
            raise ProbeError('App Server endpoint is not an owned socket.')
        return target, (info.st_dev, info.st_ino)

    def connect(self, timeout):
        if self._inspect() != (self.target, self.identity):
            raise ProbeError('App Server endpoint changed.')
        stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            stream.settimeout(timeout)
            stream.connect(str(self.target))
            credentials = stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
            pid, uid, _ = struct.unpack('3i', credentials)
            if (uid != os.getuid() or self._inspect() != (self.target, self.identity)
                    or (self.peer_pid is not None and pid != self.peer_pid)):
                raise ProbeError('App Server peer identity changed.')
            if self.server is not None:
                if self.server.poll() is not None or os.getpgid(pid) != self.server.pid:
                    raise ProbeError('App Server peer does not belong to the owned process group.')
            elif self.peer_pid is None:
                raise ProbeError('App Server peer ownership is unknown.')
            self.peer_pid = pid
            return stream
        except BaseException:
            stream.close()
            raise


@contextmanager
def private_recheck_server(timeout, *, executable='codex'):
    """Own one local listener for the lifetime of the enclosing workflow."""
    import signal

    with tempfile.TemporaryDirectory(prefix='modelmate-recheck-socket-') as scratch:
        path = Path(scratch) / 'server.sock'
        command = [executable, 'app-server', '--listen', f'unix://{path}',
                   '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"',
                   '-c', 'web_search="disabled"', '-c', 'approvals_reviewer="user"']
        with subprocess.Popen(command, cwd=scratch, start_new_session=True, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as server:
            try:
                deadline = time.monotonic() + timeout
                while server.poll() is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        endpoint = PrivateUnixEndpoint(path, server=server)
                    except FileNotFoundError:
                        time.sleep(min(.05, remaining))
                        continue
                    break
                else:
                    raise ProbeError('Private App Server exited before publishing its socket.')
                if remaining <= 0:
                    raise ProbeError('Private App Server socket startup timed out.')
                yield endpoint
            finally:
                if server.poll() is None:
                    try:
                        os.killpg(server.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        server.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(server.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass


class UnixWebSocket:
    """Bounded WebSocket text records over an owned Linux Unix socket."""

    MAX_MESSAGE = 4 * 1024 * 1024
    MAX_HEADERS = 16 * 1024
    MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

    def __init__(self, endpoint, timeout):
        deadline = time.monotonic() + timeout
        self.stream = endpoint.connect(timeout)
        self.buffer = bytearray()
        self.fragments = None
        try:
            self._upgrade(deadline)
        except BaseException:
            self.close()
            raise

    def close(self):
        self.stream.close()

    def _set_deadline(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('App Server WebSocket deadline exceeded.')
        self.stream.settimeout(remaining)

    def _fill(self, deadline):
        self._set_deadline(deadline)
        data = self.stream.recv(65536)
        if not data:
            raise EOFError('App Server WebSocket disconnected.')
        self.buffer.extend(data)

    def _take(self, size, deadline):
        while len(self.buffer) < size:
            self._fill(deadline)
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def _upgrade(self, deadline):
        key = base64.b64encode(os.urandom(16)).decode('ascii')
        request = (f'GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
                   f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n')
        self._set_deadline(deadline)
        self.stream.sendall(request.encode('ascii'))
        while (end := self.buffer.find(b'\r\n\r\n')) < 0:
            if len(self.buffer) >= self.MAX_HEADERS:
                raise ProbeError('App Server WebSocket headers too large.')
            self._fill(deadline)
        if end + 4 > self.MAX_HEADERS:
            raise ProbeError('App Server WebSocket headers too large.')
        status, *lines = self._take(end + 4, deadline)[:-4].decode('ascii').split('\r\n')
        headers = {}
        for line in lines:
            name, separator, value = line.partition(':')
            if not separator or not name or name.lower() in headers:
                raise ProbeError('Invalid App Server WebSocket headers.')
            headers[name.lower()] = value.strip()
        accept = base64.b64encode(hashlib.sha1((key + self.MAGIC).encode('ascii')).digest()).decode('ascii')
        if (status.split()[:2] != ['HTTP/1.1', '101']
                or headers.get('upgrade', '').lower() != 'websocket'
                or 'upgrade' not in {part.strip().lower() for part in headers.get('connection', '').split(',')}
                or headers.get('sec-websocket-accept') != accept
                or {'sec-websocket-extensions', 'sec-websocket-protocol'} & headers.keys()):
            raise ProbeError('Invalid App Server WebSocket upgrade.')

    def _send_frame(self, opcode, payload, deadline):
        size = len(payload)
        if size < 126:
            length = bytes([0x80 | size])
        elif size <= 65535:
            length = b'\xfe' + struct.pack('!H', size)
        else:
            length = b'\xff' + struct.pack('!Q', size)
        mask = os.urandom(4)
        body = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self._set_deadline(deadline)
        self.stream.sendall(bytes([0x80 | opcode]) + length + mask + body)

    def send_text(self, text, deadline):
        try:
            payload = text.encode('utf-8')
            if len(payload) > self.MAX_MESSAGE:
                raise ProbeError('App Server WebSocket message too large.')
            self._send_frame(1, payload, deadline)
        except BaseException:
            self.close()
            raise

    def receive_text(self, deadline):
        try:
            return self._receive_text(deadline)
        except BaseException:
            self.close()
            raise

    def _receive_text(self, deadline):
        while (message := self.pop_text(deadline)) is None:
            self._fill(deadline)
        return message

    def read_ready(self):
        self.stream.setblocking(False)
        try:
            chunk = self.stream.recv(65536)
        except BlockingIOError:
            return True
        if not chunk:
            return False
        self.buffer.extend(chunk)
        return True

    def pop_text(self, deadline):
        """Consume complete frames already read, retaining partial frames for the selector."""
        try:
            return self._pop_text(deadline)
        except BaseException:
            self.close()
            raise

    def _pop_text(self, deadline):
        while len(self.buffer) >= 2:
            first, size = self.buffer[:2]
            final, opcode = bool(first & 0x80), first & 0x0f
            if first & 0x70 or size & 0x80 or opcode not in (0, 1, 8, 9, 10):
                raise ProbeError('Invalid App Server WebSocket frame.')
            if opcode >= 8 and (not final or size > 125):
                raise ProbeError('Invalid App Server WebSocket control frame.')
            header_size = 2
            if size in (126, 127):
                header_size = 4 if size == 126 else 10
                if len(self.buffer) < header_size:
                    return None
                length = int.from_bytes(self.buffer[2:header_size], 'big')
                if length < (126 if size == 126 else 65536):
                    raise ProbeError('Invalid App Server WebSocket frame length.')
                size = length
            if size > self.MAX_MESSAGE or (opcode == 0 and self.fragments is not None
                                           and len(self.fragments) + size > self.MAX_MESSAGE):
                raise ProbeError('App Server WebSocket message too large.')
            end = header_size + size
            if len(self.buffer) < end:
                return None
            payload = bytes(self.buffer[header_size:end])
            del self.buffer[:end]
            if opcode == 8:
                if size == 1:
                    raise ProbeError('Invalid App Server WebSocket close frame.')
                self._send_frame(8, payload, deadline)
                raise EOFError('App Server WebSocket closed.')
            if opcode == 9:
                self._send_frame(10, payload, deadline)
            elif opcode in (0, 1):
                if (opcode == 0) != (self.fragments is not None):
                    raise ProbeError('Unexpected App Server WebSocket fragmentation.')
                if self.fragments is None:
                    self.fragments = bytearray()
                self.fragments.extend(payload)
                if final:
                    message = self.fragments.decode('utf-8')
                    self.fragments = None
                    return message
        return None
