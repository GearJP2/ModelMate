"""Offline P13 host capability probe; no model or network requests."""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


CHILD = r"""
import json, os, sys, ssl, http.client
from pathlib import Path
secret, marker, fd = sys.argv[1:]
def unreadable(path):
    try:
        Path(path).read_bytes()
    except (FileNotFoundError, PermissionError):
        return True
    return False
tls = ssl.create_default_context(cafile='/public-ca.pem')
public = Path('/public-query.json')
query = json.loads(sys.stdin.read())
checks = {
    'tlsTrustLoaded': tls.cert_store_stats()['x509_ca'] > 0 and tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED,
    'unmountedToolsHidden': all(not Path(path).exists() for path in ('/usr/bin/sh', '/usr/bin/env', '/usr/local', '/etc', '/run')),
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
KEYS = {'tlsTrustLoaded', 'unmountedToolsHidden', 'queryOnly', 'privateFileHidden', 'oldCwdHidden', 'homeHidden',
        'cwdIsolated', 'environmentCleared', 'privateFdClosed',
        'publicReadOnly', 'workerWriteSucceeded'}


# This diagnostic profile is deliberately host-specific; do not widen on failure.
MOUNTS = (
    ('/usr/bin/python3.11', '/usr/bin/python3'),
    ('/usr/lib/python3.11', '/usr/lib/python3.11'),
    ('/lib64/ld-linux-x86-64.so.2', '/lib64/ld-linux-x86-64.so.2'),
    *((f'/lib/x86_64-linux-gnu/{name}', f'/lib/x86_64-linux-gnu/{name}')
      for name in ('libc.so.6', 'libm.so.6', 'libz.so.1', 'libexpat.so.1',
                   'libssl.so.3', 'libcrypto.so.3')),
    ('/etc/ssl/certs/ca-certificates.crt', '/public-ca.pem'),
)


def probe(timeout=10):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be finite and positive')
    executable = shutil.which('bwrap')
    if not executable or not Path('/usr/bin/python3').is_file():
        return {'status': 'unverified', 'reason': 'missing_host_utility'}
    if any(not Path(source).exists() for source, _ in MOUNTS):
        return {'status': 'unverified', 'reason': 'unsupported_runtime_profile'}
    with tempfile.TemporaryDirectory(prefix='modelmate-isolation-') as directory:
        root = Path(directory)
        secret, public, marker = root / 'secret', root / 'query.json', root / 'worker-marker'
        private_bytes = os.urandom(32)
        secret.write_bytes(private_bytes)
        public_bytes = b'{"query": "synthetic public query"}'
        public.write_bytes(public_bytes)
        command = [executable, '--unshare-all', '--share-net', '--die-with-parent',
                   '--new-session', '--cap-drop', 'ALL']
        for source, destination in MOUNTS:
            command += ['--ro-bind', str(Path(source).resolve()), destination]
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
