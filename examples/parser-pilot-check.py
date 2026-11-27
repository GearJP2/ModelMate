#!/usr/bin/env python3
"""Frozen C4 API checks; independent human review still checks the refactor itself."""
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile


DRIVER = '''import importlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
args=json.loads(sys.argv[3])
if sys.argv[4]=='iterator':args[0]=iter(args[0])
try:
    value=getattr(importlib.import_module(sys.argv[1]),sys.argv[2])(*args)
    report={'type':type(value).__name__,'value':value}
    if isinstance(value,dict):report['keys']=list(value)
except Exception as error:
    report={'error':type(error).__name__}
if sys.argv[1]=='totals' and sys.argv[4]!='iterator':report['input']=args[0]
print(json.dumps(report,sort_keys=True))
'''


def output_limit():
    limits = (*resource.getrlimit(resource.RLIMIT_FSIZE), 65536)
    cap = min(value for value in limits if value != resource.RLIM_INFINITY)
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))


def observe(module, function, arguments, mode=''):
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        with subprocess.Popen([sys.executable, '-I', '-B', '-c', DRIVER, module, function,
                json.dumps(arguments), mode], stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                start_new_session=True, preexec_fn=output_limit) as process:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return None
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            out.seek(0);err.seek(0)
            return process.returncode, out.read(65537), err.read(65537)


def main():
    cases = []
    for module, function in (('records', 'parse_record'), ('record_fields', 'parse_fields')):
        for name, text, expected in (
                ('simple', 'alpha:2', ['alpha', 2]), ('unicode_spaces', '  ไทย : 02 ', ['ไทย', 2]),
                ('zero', 'a:0', ['a', 0]), ('plus', 'a:+3', ['a', 3])):
            cases.append((module + '_' + name, module, function, [text], '',
                          {'type': 'tuple', 'value': expected}))
        for name, text, error in (
                ('empty', '', 'ValueError'), ('missing_colon', 'alpha', 'ValueError'),
                ('extra_colon', 'a:1:2', 'ValueError'), ('empty_name', ' :1', 'ValueError'),
                ('negative', 'a:-1', 'ValueError'), ('fraction', 'a:1.5', 'ValueError'),
                ('non_integer', 'a:no', 'ValueError'), ('wrong_type', True, 'TypeError')):
            cases.append((module + '_' + name, module, function, [text], '', {'error': error}))
    for name, rows, expected, mode in (
            ('empty', [], {}, ''), ('ordered_duplicates', ['b:1', 'a:2', 'b:3'], {'b': 4, 'a': 2}, ''),
            ('iterator', ['b:1', 'a:0', 'b:3'], {'b': 4, 'a': 0}, 'iterator')):
        report = {'type': 'dict', 'value': expected, 'keys': list(expected)}
        if not mode:report['input'] = rows
        cases.append(('totals_' + name, 'totals', 'sum_counts', [rows], mode, report))
    for name, rows, error in (('bad_row', ['a:1', 'bad'], 'ValueError'),
                              ('non_iterable', None, 'TypeError')):
        cases.append(('totals_' + name, 'totals', 'sum_counts', [rows], '', {'error': error, 'input': rows}))
    checks = {'extractedModule': Path('record_fields.py').is_file()}
    for name, module, function, arguments, mode, expected in cases:
        observed = observe(module, function, arguments, mode)
        if observed is None:
            print(json.dumps({'state': 'unverified', 'reason': 'candidate_timeout', 'checks': checks}))
            return 2
        status, stdout, stderr = observed
        if status != 0 or stderr:
            print(json.dumps({'state': 'unverified', 'reason': 'candidate_failed', 'checks': checks}))
            return 2
        checks[name] = stdout == (json.dumps(expected, sort_keys=True) + '\n').encode('utf-8')
    print(json.dumps(checks, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError):
        print(json.dumps({'state': 'unverified', 'reason': 'checker_io_error'}))
        sys.exit(2)
