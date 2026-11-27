#!/usr/bin/env python3
"""A3 checks execute only a validated three-command local installation recipe."""
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile


EXAMPLE = ("import argparse\n\nparser = argparse.ArgumentParser(description='Local report demo.')\n"
           "parser.add_argument('--self-check', action='store_true', required=True)\n"
           "parser.parse_args()\nprint('report-demo-ok')\n")
DESTINATION = '$HOME/.local/share/report demo'
COMMANDS = [['mkdir', '-p', DESTINATION],
            ['cp', '$SOURCE/example.py', DESTINATION + '/example.py'],
            ['python3', DESTINATION + '/example.py', '--self-check']]


def read_regular(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('Expected a regular fixture file.')
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Fixture exceeds its size limit.')
    return data


def recipe(document):
    blocks = re.findall(r'```sh\n(.*?)\n```', document, re.DOTALL)
    if len(blocks) != 1 or document.count('```') != 2:
        raise ValueError('Expected exactly one sh fenced block.')
    lines = [line.strip() for line in blocks[0].splitlines() if line.strip() and not line.lstrip().startswith('#')]
    # Token allowlisting precedes shell execution; arbitrary documentation is never a shell program.
    if [shlex.split(line) for line in lines] != COMMANDS:
        raise ValueError('Recipe must use the three declared local commands in order.')
    return '\n'.join(lines)


def main():
    if read_regular(Path('example.py'), len(EXAMPLE.encode())) != EXAMPLE.encode():
        print(json.dumps({'machineChecks': {'exampleUnchanged': False}, 'trustedReviewRequired': True}))
        return 1
    commands = recipe(read_regular(Path('INSTALL.md'), 16384).decode('utf-8'))
    with tempfile.TemporaryDirectory(prefix='modelmate install pilot ') as directory:
        base = Path(directory)
        source, home, working, later = [base / name for name in
                                      ('source with spaces', 'home with spaces', 'fresh working directory', 'another directory')]
        for path in (source, home, working, later):
            path.mkdir()
        (source / 'example.py').write_text(EXAMPLE, encoding='utf-8')
        env = {'SOURCE': str(source), 'HOME': str(home), 'PATH': os.defpath, 'LC_ALL': 'C.UTF-8'}
        result = subprocess.run(['/bin/sh', '-eu', '-c', commands], cwd=working, env=env,
                                capture_output=True, timeout=3)
        installed = home / '.local/share/report demo/example.py'
        checks = {'exampleUnchanged': True, 'recipeShape': True,
                  'installAndRun': result.returncode == 0 and result.stdout == b'report-demo-ok\n' and not result.stderr}
        checks['installedBytes'] = installed.is_file() and read_regular(installed, len(EXAMPLE.encode())) == EXAMPLE.encode()
        (source / 'example.py').unlink()
        if checks['installedBytes']:
            result = subprocess.run([sys.executable, '-I', '-B', str(installed), '--self-check'],
                cwd=later, env=env, capture_output=True, timeout=3)
            checks['independentRun'] = result.returncode == 0 and result.stdout == b'report-demo-ok\n' and not result.stderr
        else:
            checks['independentRun'] = False
    print(json.dumps({'machineChecks': checks, 'trustedReviewRequired': True}, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print(json.dumps({'state': 'unverified', 'reason': 'invalid_recipe_or_check_failed', 'trustedReviewRequired': True}))
        sys.exit(2)
