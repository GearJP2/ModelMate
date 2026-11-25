"""Offline P13 host capability probe; no model or network requests."""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


CHILD = r"""
import json, os, sys
from pathlib import Path
secret, marker, fd = sys.argv[1:]
def unreadable(path):
    try:
        Path(path).read_bytes()
    except (FileNotFoundError, PermissionError):
        return True
    return False
public = Path('/public-query.json')
query = json.loads(sys.stdin.read())
checks = {
    'queryOnly': query == {'query': 'synthetic public query'} and json.loads(public.read_text()) == query,
    'privateFileHidden': unreadable(secret),
    'oldCwdHidden': unreadable('secret'),
    'homeHidden': not Path('/home').exists(),
    'cwdIsolated': os.getcwd() == '/tmp',
    'environmentCleared': dict(os.environ) == {'PATH': '/usr/bin', 'LC_CTYPE': 'C.UTF-8', 'PWD': '/tmp'},
}
try:
    os.fstat(int(fd))
    checks['privateFdClosed'] = False
except OSError:
    checks['privateFdClosed'] = True
try:
    public.write_text('modified')
    checks['publicReadOnly'] = False
except (PermissionError, OSError):
    checks['publicReadOnly'] = True
path = Path(marker)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text('worker marker')
checks['workerWriteSucceeded'] = path.read_text() == 'worker marker'
print(json.dumps(checks))
"""
KEYS = {'queryOnly', 'privateFileHidden', 'oldCwdHidden', 'homeHidden',
        'cwdIsolated', 'environmentCleared', 'privateFdClosed',
        'publicReadOnly', 'workerWriteSucceeded'}


def probe(timeout=10):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be finite and positive')
    executable = shutil.which('bwrap')
    if not executable or not Path('/usr/bin/python3').is_file():
        return {'status': 'unverified', 'reason': 'missing_host_utility'}
    with tempfile.TemporaryDirectory(prefix='modelmate-isolation-') as directory:
        root = Path(directory)
        secret, public, marker = root / 'secret', root / 'query.json', root / 'worker-marker'
        private_bytes = os.urandom(32)
        secret.write_bytes(private_bytes)
        public_bytes = b'{"query": "synthetic public query"}'
        public.write_bytes(public_bytes)
        command = [executable, '--unshare-all', '--share-net', '--die-with-parent',
                   '--new-session', '--cap-drop', 'ALL']
        # shortcut: broad system mounts test capability only; review a minimal runtime allowlist before G3.
        for system in ('/usr', '/lib', '/lib64'):
            if Path(system).exists():
                command += ['--ro-bind', system, system]
        command += ['--dev', '/dev', '--proc', '/proc', '--tmpfs', '/tmp',
                    '--ro-bind', str(public), '/public-query.json', '--chdir', '/tmp',
                    '--clearenv', '--setenv', 'PATH', '/usr/bin',
                    '--setenv', 'LC_CTYPE', 'C.UTF-8']
        with secret.open('rb') as private_fd:
            os.set_inheritable(private_fd.fileno(), True)
            command += ['--', '/usr/bin/python3', '-I', '-S', '-c', CHILD,
                        str(secret), str(marker), str(private_fd.fileno())]
            try:
                result = subprocess.run(command, input=public_bytes, capture_output=True,
                                        timeout=timeout, close_fds=True, cwd=root,
                                        env={'PATH': os.defpath})
            except subprocess.TimeoutExpired:
                return {'status': 'unverified', 'reason': 'timeout'}
            except OSError:
                return {'status': 'unverified', 'reason': 'launch_failed'}
        if result.returncode:
            return {'status': 'unverified', 'reason': 'namespace_or_worker_failed'}
        try:
            checks = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            checks = None
        if (not isinstance(checks, dict) or set(checks) != KEYS
                or any(type(value) is not bool for value in checks.values())):
            return {'status': 'unverified', 'reason': 'invalid_worker_report'}
        checks['hostWriteContained'] = not marker.exists()
        checks['hostInputsUnchanged'] = (secret.read_bytes() == private_bytes
                                        and public.read_bytes() == public_bytes)
        return {'status': 'capability_verified' if all(checks.values()) else 'unverified',
                'checks': checks, 'scope': 'synthetic_local_probe_only', 'g3Passed': False}


if __name__ == '__main__':
    report = probe()
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report['status'] == 'capability_verified' else 1)
