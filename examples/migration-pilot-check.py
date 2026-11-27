#!/usr/bin/env python3
"""Frozen C5 migration checks with publish and kernel file-write fault injection."""
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import tempfile


V1 = {'version': 1, 'items': [{'name': 'ไทย', 'count': 2}, {'name': ' a ', 'count': 0}, {'name': 'ไทย', 'count': 5}]}
V2 = {'version': 2, 'records': [{'name': row['name'], 'quantity': row['count']} for row in V1['items']]}
LEGACY_NAME = 'legacy sample.json'
LEGACY_BYTES = (json.dumps(V1, ensure_ascii=False, indent=2) + '\n').encode('utf-8')

DRIVER = '''import json,os,resource,signal,stat,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
operation,path,mode=sys.argv[1:]
path=Path(path)
report={'value':None,'error':None,'publishCalls':0,'snapshotValid':True}
try:
    import store
    original=store._publish
    def publish(snapshot,destination):
        snapshot,destination=Path(snapshot),Path(destination)
        report['publishCalls']+=1
        report['snapshotValid'] &= (snapshot.resolve() != path.resolve() and destination.resolve() == path.resolve()
            and snapshot.parent.resolve() == path.parent.resolve() and not snapshot.is_symlink() and snapshot.is_file()
            and stat.S_IMODE(snapshot.stat().st_mode)==0o600)
        if mode=='publish_failure':raise OSError('synthetic publication failure')
        return original(snapshot,destination)
    store._publish=publish
    previous=resource.getrlimit(resource.RLIMIT_FSIZE)
    old_signal=signal.getsignal(signal.SIGXFSZ)
    try:
        if mode=='write_failure':
            signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
            soft=1 if previous[0]==resource.RLIM_INFINITY else min(previous[0],1)
            resource.setrlimit(resource.RLIMIT_FSIZE,(soft,previous[1]))
        report['value']=getattr(store,operation)(path)
        if mode=='repeat':report['value']=[report['value'],store.migrate(path)]
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE,previous)
        signal.signal(signal.SIGXFSZ,old_signal)
except Exception as error:
    report['error']='OSError' if isinstance(error,OSError) else 'ValueError' if isinstance(error,ValueError) else type(error).__name__
print(json.dumps(report,sort_keys=True))
'''


def output_limit():
    limits = (*resource.getrlimit(resource.RLIMIT_FSIZE), 65536)
    cap = min(value for value in limits if value != resource.RLIM_INFINITY)
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))


def observe(operation, path, mode):
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        with subprocess.Popen([sys.executable, '-I', '-B', '-c', DRIVER, operation, str(path), mode],
                stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True,
                preexec_fn=output_limit) as process:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return None
            finally:
                try:os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait()
            out.seek(0);err.seek(0)
            return process.returncode, out.read(65537), err.read(65537)


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:raise ValueError('Duplicate JSON key.')
        result[key] = value
    return result


def input_unchanged():
    if Path(LEGACY_NAME).is_symlink() or not Path(LEGACY_NAME).is_file():return False
    with Path(LEGACY_NAME).open('rb') as source:
        return source.read(len(LEGACY_BYTES) + 1) == LEGACY_BYTES


def main():
    if not input_unchanged():
        print(json.dumps({'inputUnchanged': False}));return 1
    current = ('  ' + json.dumps(V2, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    cases = [
        ('load_legacy', 'load', LEGACY_BYTES, '', V2, None, 0, False),
        ('load_current', 'load', current, '', V2, None, 0, False),
        ('migrate_legacy', 'migrate', LEGACY_BYTES, '', V2, None, 1, True),
        ('migrate_empty', 'migrate', b'{"version":1,"items":[]}', '', {'version': 2, 'records': []}, None, 1, True),
        ('repeat', 'migrate', LEGACY_BYTES, 'repeat', [V2, V2], None, 1, True),
        ('current_noop', 'migrate', current, 'publish_failure', V2, None, 0, False),
        ('publish_failure', 'migrate', LEGACY_BYTES, 'publish_failure', None, 'OSError', 1, False),
        ('write_failure', 'migrate', LEGACY_BYTES, 'write_failure', None, 'OSError', 0, False),
    ]
    invalid = [b'not JSON', b'\xff', b'[]', b'{"version":true,"items":[]}', b'{"version":3,"items":[]}',
        b'{"version":1,"items":[],"extra":1}', b'{"version":1,"version":1,"items":[]}',
        b'{"version":1,"items":null}',
        b'{"version":1,"items":[{"name":"a","count":1,"count":2}]}',
        b'{"version":1,"items":[{"name":"a","count":1,"extra":0}]}',
        b'{"version":1,"items":[{"name":"a","count":true}]}',
        b'{"version":1,"items":[{"name":"a","count":-1}]}',
        b'{"version":2,"records":[{"name":"a","quantity":1.5}]}',
        b'{"version":2,"records":[{"name":" ","quantity":0}]}']
    for index, raw in enumerate(invalid):
        for operation in ('load', 'migrate'):
            cases.append((operation + '_invalid_' + str(index), operation, raw, '', None, 'ValueError', 0, False))
    checks = {'inputUnchanged': True}
    for name, operation, raw, mode, value, error, calls, changed in cases:
        with tempfile.TemporaryDirectory(prefix='.migration-check-', dir='.') as directory:
            path = Path(directory).resolve() / 'store.json'
            path.write_bytes(raw);path.chmod(0o600);os.utime(path, ns=(1000000000, 1000000000))
            before = path.stat()
            observed = observe(operation, path, mode)
            if observed is None:
                print(json.dumps({'state': 'unverified', 'reason': 'candidate_timeout', 'checks': checks}));return 2
            status, stdout, stderr = observed
            if status != 0 or stderr:
                print(json.dumps({'state': 'unverified', 'reason': 'candidate_failed', 'checks': checks}));return 2
            expected = {'value': value, 'error': error, 'publishCalls': calls, 'snapshotValid': True}
            files_ok = not path.is_symlink() and path.is_file() and {p.name for p in path.parent.iterdir()} == {'store.json'}
            if files_ok:
                with path.open('rb') as source:after = source.read(65537)
                metadata = path.stat()
                if changed:
                    try:
                        data = json.loads(after, object_pairs_hook=unique_fields)
                        expected_file = value[0] if mode == 'repeat' else value
                        files_ok = json.dumps(data, sort_keys=True) == json.dumps(expected_file, sort_keys=True)
                    except (ValueError, UnicodeError, RecursionError):files_ok = False
                else:
                    files_ok = after == raw and metadata.st_ino == before.st_ino and metadata.st_mtime_ns == before.st_mtime_ns
                files_ok = files_ok and stat.S_IMODE(metadata.st_mode) == 0o600
            checks[name] = files_ok and stdout == (json.dumps(expected, sort_keys=True) + '\n').encode('utf-8')
    checks['inputUnchanged'] = input_unchanged()
    print(json.dumps(checks, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    try:sys.exit(main())
    except (OSError, ValueError):
        print(json.dumps({'state': 'unverified', 'reason': 'checker_io_error'}));sys.exit(2)
