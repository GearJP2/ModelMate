#!/usr/bin/env python3
"""Frozen C2 checks; run model-authored candidates only through approved native execution."""
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile


INPUT = 'alpha\n\nไทย\nomega\n'
INPUT_NAME = 'rows with spaces.txt'


def input_unchanged(expected):
    with Path(INPUT_NAME).open('rb') as source:
        return source.read(len(expected) + 1) == expected


def output_limit():
    limits = (*resource.getrlimit(resource.RLIMIT_FSIZE), 65536)
    cap = min(value for value in limits if value != resource.RLIM_INFINITY)
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))


def observe(arguments):
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        with subprocess.Popen([sys.executable, '-I', '-B', 'rows.py', *arguments],
                stdout=out, stderr=err, preexec_fn=output_limit) as process:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()
                return None
            out.seek(0);err.seek(0)
            return process.returncode, out.read(65537), err.read(65537)


def main():
    expected = INPUT.encode('utf-8')
    if not input_unchanged(expected):
        print(json.dumps({'inputUnchanged': False}))
        return 1
    cases = [
        ('default', [INPUT_NAME], 0, expected),
        ('zero', [INPUT_NAME, '--limit', '0'], 0, b''),
        ('before_path', ['--limit', '1', INPUT_NAME], 0, b'alpha\n'),
        ('blank_counts_as_row', [INPUT_NAME, '--limit', '2'], 0, b'alpha\n\n'),
        ('above_length', [INPUT_NAME, '--limit', '10'], 0, expected),
        ('negative', [INPUT_NAME, '--limit', '-1'], 2, b''),
        ('not_integer', [INPUT_NAME, '--limit', 'bad'], 2, b''),
        ('unknown_option', [INPUT_NAME, '--unknown'], 2, b''),
        ('missing_file', ['missing-input.txt'], 2, b''),
        ('help', ['--help'], 0, None),
    ]
    checks = {'inputUnchanged': True}
    for name, arguments, code, output in cases:
        observed = observe(arguments)
        if observed is None:
            print(json.dumps({'state': 'unverified', 'reason': 'candidate_timeout', 'checks': checks}))
            return 2
        status, stdout, stderr = observed
        if name == 'help':
            passed = status == 0 and not stderr and b'--limit' in stdout and b'Print input rows.' in stdout
        else:
            passed = status == code and stdout == output and bool(stderr) == (code != 0)
        checks[name] = passed
    checks['inputUnchanged'] = input_unchanged(expected)
    print(json.dumps(checks, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError):
        print(json.dumps({'state': 'unverified', 'reason': 'checker_io_error'}))
        sys.exit(2)
