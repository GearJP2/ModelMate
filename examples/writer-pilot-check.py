#!/usr/bin/env python3
"""Frozen C6 checks using owned processes, kernel locks and controlled crash barriers."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import tempfile
import time


INPUT_NAME = 'checkpoint sample.json'
INPUT_BYTES = b'{"count": 0, "version": 1}\n'
KEEP = b'other writer data; do not delete\n'
DRIVER = '''import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
operation,path,pause,control=sys.argv[1:]
path,control=Path(path),Path(control)
report={'value':None,'error':None,'publishCalls':0,'snapshotValid':True}
try:
    import writer
    original=writer._publish
    def gate(stage):
        (control/stage).write_bytes(b'1')
        if pause==stage or (pause=='both' and stage in ('read','publish')):
            while not (control/('release-'+stage)).exists():time.sleep(.01)
    def before_read():gate('read')
    def publish(snapshot,destination):
        snapshot,destination=Path(snapshot),Path(destination)
        report['publishCalls']+=1
        report['snapshotValid'] &= (snapshot.resolve()!=path.resolve() and destination.resolve()==path.resolve()
            and snapshot.parent.resolve()==path.parent.resolve() and not snapshot.is_symlink()
            and snapshot.is_file() and snapshot.stat().st_mode & 0o777==0o600)
        (control/'snapshot').write_text(snapshot.name,encoding='utf-8')
        gate('publish')
        original(snapshot,destination)
        gate('after')
    writer._before_read=before_read;writer._publish=publish
    (control/'entered').write_bytes(b'1')
    report['value']=getattr(writer,operation)(path)
except Exception as error:
    report['error']='ValueError' if isinstance(error,ValueError) else type(error).__name__
print(json.dumps(report,sort_keys=True))
'''


def output_limit():
    limits = (*resource.getrlimit(resource.RLIMIT_FSIZE), 65536)
    cap = min(value for value in limits if value != resource.RLIM_INFINITY)
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))


@contextmanager
def worker(path, operation='increment', pause='none'):
    with tempfile.TemporaryDirectory(prefix='.control-', dir=path.parent.parent) as directory, \
            tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        control = Path(directory).resolve()
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', DRIVER,
            operation, str(path), pause, str(control)], stdin=subprocess.DEVNULL, stdout=out,
            stderr=err, start_new_session=True, preexec_fn=output_limit)
        try:
            yield {'process': process, 'control': control, 'out': out, 'err': err}
        finally:
            try:os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait(timeout=2)


def read_bytes(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):raise ValueError('Nonregular observation.')
        value = os.read(descriptor, 65537)
        if len(value) > 65536:raise ValueError('Oversized observation.')
        return value
    finally:os.close(descriptor)


def count(path):
    data = json.loads(read_bytes(path))
    if (not isinstance(data, dict) or set(data) != {'version', 'count'}
            or type(data['version']) is not int or data['version'] != 1
            or type(data['count']) is not int or data['count'] < 0):
        raise ValueError('Invalid checkpoint observation.')
    return data['count']


def private(path):
    return not path.is_symlink() and path.is_file() and stat.S_IMODE(path.stat().st_mode) == 0o600


def await_marker(owner, name):
    deadline = time.monotonic() + 2
    marker = owner['control'] / name
    while time.monotonic() < deadline:
        if marker.exists():return read_bytes(marker) == b'1' and owner['process'].poll() is None
        if owner['process'].poll() is not None:return False
        time.sleep(.01)
    raise TimeoutError('Candidate barrier timed out.')


def release(owner, name):
    (owner['control'] / ('release-' + name)).write_bytes(b'1')


def finished(owner, expected, *, error=None, publishes=1):
    owner['process'].wait(timeout=2)
    owner['out'].seek(0);owner['err'].seek(0)
    report = {'value': expected, 'error': error, 'publishCalls': publishes, 'snapshotValid': True}
    return (owner['process'].returncode == 0 and not owner['err'].read(65537)
            and owner['out'].read(65537) == (json.dumps(report, sort_keys=True) + '\n').encode('utf-8'))


def lock_path(path):return Path(str(path) + '.lock')


def exclusive(path):
    lock = lock_path(path)
    if not private(lock):return False
    descriptor = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        try:fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:os.close(descriptor)


def identity(path):
    value = path.stat()
    return value.st_dev, value.st_ino


def snapshot(owner, path):
    name = read_bytes(owner['control'] / 'snapshot').decode('utf-8')
    if (not name or len(name) > 255 or Path(name).name != name
            or name in ('.', '..', path.name, lock_path(path).name, 'keep.txt')):
        raise ValueError('Snapshot outside owned case.')
    return path.parent / name


def seed(directory, value):
    data = directory / 'data';data.mkdir()
    path = data / 'checkpoint.json'
    path.write_text(json.dumps({'version': 1, 'count': value}) + '\n', encoding='utf-8')
    path.chmod(0o600);os.utime(path, ns=(1000000000, 1000000000))
    (data / 'keep.txt').write_bytes(KEEP)
    return path


def clean_scope(path, extra=()):
    return ({p.name for p in path.parent.iterdir()} == {path.name, lock_path(path).name, 'keep.txt', *extra}
            and private(path) and private(lock_path(path)) and read_bytes(path.parent / 'keep.txt') == KEEP)


def sequential(directory):
    path = seed(directory, 0);before = path.stat();raw = read_bytes(path)
    with worker(path, 'load') as owner:
        if not finished(owner, {'version': 1, 'count': 0}, publishes=0):return False
    if read_bytes(path) != raw or identity(path) != (before.st_dev, before.st_ino) or path.stat().st_mtime_ns != before.st_mtime_ns:return False
    for value in (1, 2):
        with worker(path) as owner:
            if not finished(owner, {'version': 1, 'count': value}):return False
        if count(path) != value or exclusive(path):return False
    return clean_scope(path)


def contention(directory):
    path = seed(directory, 0);raw = read_bytes(path)
    with worker(path, pause='both') as first:
        if not await_marker(first, 'read') or not exclusive(path) or read_bytes(path) != raw:return False
        lock = identity(lock_path(path))
        with worker(path, pause='read') as second:
            if not await_marker(second, 'entered'):return False
            release(first, 'read')
            if not await_marker(first, 'publish'):return False
            if not exclusive(path) or count(path) != 0 or (second['control'] / 'read').exists():return False
            release(first, 'publish')
            if not finished(first, {'version': 1, 'count': 1}) or not await_marker(second, 'read'):return False
            if count(path) != 1 or not exclusive(path) or identity(lock_path(path)) != lock:return False
            release(second, 'read')
            if not finished(second, {'version': 1, 'count': 2}):return False
    return count(path) == 2 and identity(lock_path(path)) == lock and not exclusive(path) and clean_scope(path)


def crash(directory, stage):
    path = seed(directory, 7);raw = read_bytes(path);before = path.stat()
    committed = 7 if stage == 'publish' else 8
    with worker(path, pause=stage) as owner:
        if not await_marker(owner, stage) or not exclusive(path):return False
        lock = identity(lock_path(path));orphan = snapshot(owner, path)
        if count(path) != committed:return False
        if stage == 'publish':
            if (read_bytes(path) != raw or identity(path) != (before.st_dev, before.st_ino)
                    or path.stat().st_mtime_ns != before.st_mtime_ns or not private(orphan) or count(orphan) != 8):return False
        elif orphan.exists() or identity(path) == (before.st_dev, before.st_ino):return False
        if owner['process'].poll() is not None:return False
        os.killpg(owner['process'].pid, signal.SIGKILL);owner['process'].wait(timeout=2)
        if owner['process'].returncode != -signal.SIGKILL:return False
    if count(path) != committed or exclusive(path) or identity(lock_path(path)) != lock:return False
    if stage == 'publish' and (read_bytes(path) != raw or path.stat().st_mtime_ns != before.st_mtime_ns):return False
    poison = b'{"version":1,"count":9999}\n'
    if stage == 'after':
        descriptor = os.open(orphan, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600);os.close(descriptor)
    orphan.write_bytes(poison)
    with worker(path) as next_owner:
        if not finished(next_owner, {'version': 1, 'count': committed + 1}):return False
    return (count(path) == committed + 1 and private(orphan) and read_bytes(orphan) == poison
            and identity(lock_path(path)) == lock and not exclusive(path) and clean_scope(path, (orphan.name,)))


def invalid(directory):
    path = seed(directory, 0)
    for raw in (b'not JSON', b'{"version":1,"count":true}', b'{"version":1,"count":-1}'):
        path.write_bytes(raw);before = path.stat()
        with worker(path) as owner:
            if not finished(owner, None, error='ValueError', publishes=0):return False
        if (read_bytes(path) != raw or identity(path) != (before.st_dev, before.st_ino)
                or path.stat().st_mtime_ns != before.st_mtime_ns):return False
    return not exclusive(path) and clean_scope(path)


def main():
    checks = {'inputUnchanged': read_bytes(Path(INPUT_NAME)) == INPUT_BYTES}
    if not checks['inputUnchanged']:print(json.dumps(checks));return 1
    cases = {'sequential': sequential, 'contention': contention,
             'crash_before_publish': lambda root: crash(root, 'publish'),
             'crash_after_publish': lambda root: crash(root, 'after'), 'invalid_unchanged': invalid}
    for name, run_case in cases.items():
        with tempfile.TemporaryDirectory(prefix='.writer-check-', dir='.') as directory:
            try:checks[name] = run_case(Path(directory).resolve())
            except ValueError:checks[name] = False
    checks['inputUnchanged'] = read_bytes(Path(INPUT_NAME)) == INPUT_BYTES
    print(json.dumps(checks, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    try:sys.exit(main())
    except (TimeoutError, subprocess.TimeoutExpired):
        print(json.dumps({'state': 'unverified', 'reason': 'candidate_timeout'}));sys.exit(2)
    except (OSError, ValueError):
        print(json.dumps({'state': 'unverified', 'reason': 'checker_io_error'}));sys.exit(2)
