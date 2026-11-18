#!/usr/bin/env python3
"""Prepare, preview, and score one paired synthetic routing evaluation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


CHOICES = {
    'A': lambda size: range(size - 1),
    'B': lambda size: range(size),
    'C': lambda size: range(size + 1),
    'D': lambda size: range(1, size),
}
CRITERION = 'The chosen loop expression returns the first matching index, including the last element, or -1.'


def prepare():
    scratch = Path(tempfile.mkdtemp(prefix='modelmate-routing-pilot-'))
    runtime = scratch / 'modelmate.py'
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'modelmate.py', runtime)
    objective = (
        'Choose the repair for this Python function and answer with exactly one letter A, B, C or D. '
        'Use only the code in this prompt. Do not call tools or read or modify files.\n'
        'def first_index(values, target):\n'
        '    for i in range(len(values) - 1):\n'
        '        if values[i] == target:\n'
        '            return i\n'
        '    return -1\n'
        'Replace only the expression after "in". A: range(len(values) - 1). '
        'B: range(len(values)). C: range(len(values) + 1). D: range(1, len(values)). '
        'The result must be the first matching index, or -1 if absent, including on empty input.'
    )
    for arm, role in [('routed', 'standard'), ('baseline', 'strong')]:
        project = scratch / arm / 'project'
        project.mkdir(parents=True)
        plan = {'version': 1, 'goal': 'Repair the boundary in first_index', 'clarifications': [],
                'success_criteria': [CRITERION], 'steps': [{
                    'kind': 'implement', 'objective': objective, 'role': role, 'effort': 'low',
                    'risk': 'normal', 'reason': 'A deterministic checker grades the choice after the turn.',
                    'checks': [{'kind': 'rubric', 'criterion': CRITERION}],
                }]}
        (project / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    print(scratch)


def run(scratch, arm, standard, strong, execute):
    if standard == strong or not standard.strip() or not strong.strip():
        raise ValueError('Choose two distinct model IDs that support low effort.')
    scratch = scratch.resolve(strict=True)
    project = scratch / arm / 'project'
    runtime = scratch / 'modelmate.py'
    state = scratch / arm / 'state'
    args = [sys.executable, str(runtime), '--workflow', str(project / 'plan.json'),
            '--workflow-mode', 'approve_plan', '--role-model', 'standard=' + standard,
            '--role-model', 'strong=' + strong]
    if arm == 'routed':
        args.append('--suggest-models')
    if execute:
        args.append('--execute-workflow')
    print('Runtime SHA-256 ' + hashlib.sha256(runtime.read_bytes()).hexdigest(), flush=True)
    return subprocess.run(args, cwd=project, env=dict(os.environ, XDG_STATE_HOME=str(state))).returncode


def score(answer):
    indices = CHOICES.get(answer.strip())
    if indices is None:
        raise ValueError('The answer must be exactly one letter A, B, C or D.')

    def first_index(values, target):
        for i in indices(len(values)):
            if values[i] == target:
                return i
        return -1

    cases = [('empty', [], 5, -1), ('singleton', [5], 5, 0),
             ('first duplicate', [5, 5, 2], 5, 0), ('last', [1, 2, 5], 5, 2),
             ('missing', [1, 2, 3], 5, -1)]
    results = {}
    for name, values, target, expected in cases:
        try:
            results[name] = first_index(values, target) == expected
        except IndexError:
            results[name] = False
    print(json.dumps(results, sort_keys=True))
    return 0 if all(results.values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('prepare', help='make a fresh pair and print its path')
    launch = actions.add_parser('run', help='preview one arm, or opt in to a live workflow')
    launch.add_argument('scratch', type=Path)
    launch.add_argument('arm', choices=('routed', 'baseline'))
    launch.add_argument('--standard', required=True)
    launch.add_argument('--strong', required=True)
    launch.add_argument('--execute', action='store_true', help='enable START and turn approval, which can use quota')
    grade = actions.add_parser('score', help='score the letter from the turn with trusted local cases')
    grade.add_argument('answer')
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            prepare()
            return 0
        if args.action == 'run':
            return run(args.scratch, args.arm, args.standard, args.strong, args.execute)
        return score(args.answer)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    sys.exit(main())
