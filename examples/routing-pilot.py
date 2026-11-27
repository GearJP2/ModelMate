#!/usr/bin/env python3
"""Prepare, preview, and score paired synthetic routing evaluations."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import shlex
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

DEDUPE_CRITERION = 'Return the first occurrence of each distinct nonempty row in original order.'
DEDUPE_GOAL = 'Choose a stable de-duplication fix for the importer'
DEDUPE_CHOICES = {
    'A': lambda rows: sorted(set(rows)),
    'B': lambda rows: list(rows),
    'C': lambda rows: list(dict.fromkeys(reversed(rows)))[::-1],
    'D': lambda rows: list(dict.fromkeys(rows)),
}


def dedupe_plan(role):
    objective = (
        'Choose the correct expression and reply with exactly one letter A, B, C or D. '
        'Use only this prompt. Do not call tools or access files. An importer strips whitespace '
        'from each input string and drops empty strings before forming cleaned. '
        'Replace the return expression so the importer keeps the first occurrence of each '
        'distinct string in the original order. A: sorted(set(cleaned)). B: list(cleaned). '
        'C: list(dict.fromkeys(reversed(cleaned)))[::-1]. D: list(dict.fromkeys(cleaned)).'
    )
    return {'version': 1, 'goal': DEDUPE_GOAL, 'clarifications': [],
            'success_criteria': [DEDUPE_CRITERION], 'steps': [{
                'kind': 'implement', 'objective': objective, 'role': role, 'effort': 'low',
                'risk': 'normal', 'reason': 'A deterministic checker grades the choice after the turn.',
                'checks': [{'kind': 'rubric', 'criterion': DEDUPE_CRITERION}],
            }]}


def incident_plan(role):
    objective = (
        'Analyze the synthetic incident using only these records. Do not call tools or access files. '
        'All times are UTC on the same day. B: 09:10, elevated checkout errors first observed. '
        'D: 09:23, checkout errors return to normal. A: 09:04, configuration rollout started. '
        'C: 09:18, rollback started and upstream provider reported its own service recovery. '
        'No causal investigation was recorded. Respond with one JSON object containing exactly these keys: '
        'timeline (array of the four event IDs in chronological order), '
        'observed_impact_minutes (integer between first and last recorded customer impact observations, '
        'from first elevated errors until return to normal), '
        'root_cause (one of config_confirmed, upstream_confirmed, unconfirmed), '
        'competing_recovery_event (ID of the record containing both potential recovery explanations). '
        'Use no Markdown or commentary.'
    )
    criterion = 'Correctly order events, compute the observed duration and preserve causal uncertainty.'
    return {'version': 1, 'goal': 'Analyze the observed checkout incident timeline', 'clarifications': [],
            'success_criteria': [criterion], 'steps': [{
                'kind': 'implement', 'objective': objective, 'role': role, 'effort': 'low',
                'risk': 'normal', 'reason': 'The given records support independent grading.',
                'checks': [{'kind': 'rubric', 'criterion': criterion}],
            }]}


CLEANUP_SOURCE = ('def delete_session(project, session, token, expected_token):\n'
                  '    target = project / session["id"]\n'
                  '    if session["state"] == "RUNNING":\n'
                  '        return "blocked"\n'
                  '    if token:\n'
                  '        shutil.rmtree(target)\n'
                  '    if token != expected_token:\n'
                  '        return "denied"\n'
                  '    return "deleted"')


def cleanup_plan(role):
    criterion = 'Identify path escape and late confirmation with exact line evidence, without mislabeling the RUNNING guard.'
    objective = ('Review only the synthetic cleanup.py fixture reproduced below. Do not execute it, call tools or access files. '
        'Assume project is a pathlib.Path, shutil is imported, session id and token are untrusted strings, '
        'expected_token is a trusted nonempty string, and session state is controller-owned. '
        'Evaluate these three properties: scope_contained (the deletion stays inside project for every id), '
        'confirmation_before_delete (the token is compared with expected_token before any deletion), '
        'active_blocked (RUNNING sessions cannot reach deletion). '
        'Return exactly one JSON object with those three keys. Each value must contain exactly '
        'safe (boolean) and lines (ascending unique integer line numbers). For scope_contained cite the '
        'target construction and deletion; for confirmation_before_delete cite the token condition, '
        'deletion, comparison and denied return; for active_blocked cite the state condition, blocked '
        'return and deletion. Include no Markdown or extra findings.\n'
        + '\n'.join(str(i) + ': ' + line for i, line in enumerate(CLEANUP_SOURCE.splitlines(), 1)))
    return {'version': 1, 'goal': 'Review scope and confirmation safety of synthetic session cleanup',
        'clarifications': [], 'success_criteria': [criterion], 'steps': [{
            'kind': 'review', 'objective': objective, 'role': role, 'effort': 'low',
            'risk': 'normal', 'reason': 'A read-only bounded review graded against frozen facts and line evidence.',
            'checks': [{'kind': 'rubric', 'criterion': criterion}],
        }]}


def prepare(case):
    scratch = Path(tempfile.mkdtemp(prefix='modelmate-routing-pilot-'))
    runtime = scratch / 'modelmate.py'
    (scratch / 'case.txt').write_text(case + '\n', encoding='utf-8')
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'modelmate.py', runtime)
    checker = scratch / 'check-cli.py'
    if case == 'cli':
        shutil.copyfile(Path(__file__).with_name('cli-pilot-check.py'), checker)
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
        if case == 'economy':
            plan = prepare_economy(project, role)
        elif case == 'dedupe':
            plan = dedupe_plan(role)
        elif case == 'incident':
            plan = incident_plan(role)
        elif case == 'cleanup':
            (project / 'cleanup.py').write_text(CLEANUP_SOURCE + '\n', encoding='utf-8')
            plan = cleanup_plan(role)
        elif case == 'cli':
            plan = prepare_cli(project, role, checker)
        (project / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    print(scratch)


def prepare_economy(project, role):
    (project / 'search.py').write_text(
        'def first_index(values, target):\n'
        '    for index, value in enumerate(values):\n'
        '        if value == target:\n'
        '            return index\n'
        '    return -1\n', encoding='utf-8')
    (project / 'test_search.py').write_text(
        'import unittest\n'
        'from search import first_index\n\n'
        'class SearchTests(unittest.TestCase):\n'
        '    def test_empty(self):\n'
        '        self.assertEqual(first_index([], 4), -1)\n'
        '    def test_first(self):\n'
        '        self.assertEqual(first_index([4, 1], 4), 0)\n'
        '    def test_missing(self):\n'
        '        self.assertEqual(first_index([1, 2], 4), -1)\n', encoding='utf-8')
    step_one = 'The registered first_index regression suite exits successfully.'
    step_two = 'Give a valid new test with expected result that distinguishes the correct loop from one skipping the last element.'
    checks = {'version': 1, 'checks': [{'step': 1, 'check': 1, 'cwd': '.',
                                      'command': 'python3 -B -m unittest test_search'}]}
    (project / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    return {'version': 1, 'goal': 'Verify the first_index repair and identify a gap in the regression suite',
            'clarifications': [], 'success_criteria': [step_one, step_two], 'steps': [
                {'kind': 'implement', 'objective': 'Validate the supplied first_index implementation. '
                 'Run the registered test exactly as given and summarize the outcome. Read only search.py '
                 'and test_search.py if needed. Do not edit files or run other commands.',
                 'role': role, 'effort': 'low', 'risk': 'normal',
                 'reason': 'The repair is already staged and a local test checks the result.',
                 'checks': [{'kind': 'test', 'criterion': step_one}]},
                {'kind': 'review', 'objective': 'Review coverage of search.py in test_search.py. '
                 'Propose one missing test that would fail if the loop skipped the last element. '
                 'Give the concrete input, target, expected index and why the current tests miss it. '
                 'Read only those two files, and do not edit files or run tests.',
                 'role': 'strong', 'effort': 'low', 'risk': 'normal',
                 'reason': 'This step deliberately uses strong review to exercise escalation consent.',
                 'checks': [{'kind': 'rubric', 'criterion': step_two}]},
            ]}


def prepare_cli(project, role, checker):
    source_checker = Path(__file__).with_name('cli-pilot-check.py')
    fixture = runpy.run_path(str(source_checker))
    (project / fixture['INPUT_NAME']).write_text(fixture['INPUT'], encoding='utf-8')
    (project / 'rows.py').write_text(
        "import argparse\nimport sys\nfrom pathlib import Path\n\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser(description='Print input rows.')\n"
        "    parser.add_argument('path')\n"
        "    args = parser.parse_args()\n"
        "    try:\n"
        "        rows = Path(args.path).read_text(encoding='utf-8').splitlines()\n"
        "    except (OSError, UnicodeError):\n"
        "        parser.error('Cannot read input rows.')\n"
        "    sys.stdout.buffer.write(''.join(row + '\\n' for row in rows).encode('utf-8'))\n\n"
        "if __name__ == '__main__':\n    main()\n", encoding='utf-8')
    checker_code = source_checker.read_bytes()
    digest = hashlib.sha256(checker_code).hexdigest()
    bootstrap = ("import hashlib,pathlib,sys; p=" + repr(str(checker)) + "; "
        "source=open(p,'rb'); code=source.read(" + str(len(checker_code) + 1) + "); source.close(); "
        "valid=hashlib.sha256(code).hexdigest()==" + repr(digest) + "; "
        "print('{\"checkerIntegrity\":false}') if not valid else None; "
        "sys.exit(2) if not valid else None; "
        "exec(compile(code,p,'exec'),{'__name__':'__main__','__file__':p})")
    checks = {'version': 1, 'checks': [{'step': 1, 'check': 1, 'cwd': '.',
        'command': 'python3 -I -B -c ' + shlex.quote(bootstrap)}]}
    (project / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    criterion = 'Frozen CLI checks pass: default/blank rows, nonnegative limit, help and compatible error exits; input remains unchanged.'
    return {'version': 1, 'goal': 'Add --limit N to the row-printing CLI without changing existing behavior',
        'clarifications': [], 'success_criteria': [criterion], 'steps': [{
            'kind': 'implement', 'objective': 'Edit only rows.py to implement optional --limit N. '
            'N is a nonnegative integer; print at most the first N physical rows, including blank rows. '
            'Zero prints nothing; a limit beyond the input length prints all rows. Without --limit, '
            'preserve existing output. Keep the description, help, missing-file handling and argparse '
            'error exit code 2. Do not modify inputs, plans, commands or the frozen checker. '
            'Use native patch approval when needed; do not widen permissions. After implementation, '
            'run the registered check once and report the outcome. No network or unrelated commands.',
            'role': role, 'effort': 'low', 'risk': 'normal',
            'reason': 'A bounded single-file option with independent frozen CLI checks.',
            'checks': [{'kind': 'test', 'criterion': criterion}],
        }]}


def frozen_file_matches(path, expected):
    with path.open('rb') as source:
        return source.read(len(expected) + 1) == expected


def run(scratch, arm, standard, strong, execute, economy=None, measure_quota=False, metrics_jsonl=None,
        tool_approvals=False):
    if standard == strong or not standard.strip() or not strong.strip():
        raise ValueError('Choose two distinct model IDs that support low effort.')
    scratch = scratch.resolve(strict=True)
    project = scratch / arm / 'project'
    runtime = scratch / 'modelmate.py'
    if not frozen_file_matches(runtime, (Path(__file__).resolve().parents[1] / 'modelmate.py').read_bytes()):
        raise ValueError('Prepared runtime differs from this checkout; use its original revision or prepare a new pair.')
    state = scratch / arm / 'state'
    checks = project / 'checks.json'
    plan_path = project / 'plan.json'
    case_file = scratch / 'case.txt'
    case = case_file.read_text(encoding='utf-8').strip() if case_file.is_file() else 'c1'
    if tool_approvals and case != 'cli':
        raise ValueError('Experimental tool approvals are scoped to the CLI authoring pilot.')
    if execute and case == 'cli' and not tool_approvals:
        raise ValueError('Executing the CLI authoring pilot requires explicit --experimental-tool-approvals.')
    if case == 'cleanup':
        if state.exists():
            raise ValueError('Review arm already has state; inspect/resume it or prepare a new pair, never replay it.')
        expected = (json.dumps(cleanup_plan('standard' if arm == 'routed' else 'strong'), indent=2) + '\n').encode('utf-8')
        if ({path.name for path in project.iterdir()} != {'plan.json', 'cleanup.py'}
                or not frozen_file_matches(plan_path, expected)
                or not frozen_file_matches(project / 'cleanup.py', (CLEANUP_SOURCE + '\n').encode('utf-8'))):
            raise ValueError('Frozen cleanup review inputs changed; do not start this arm.')
    if case == 'cli':
        if state.exists():
            raise ValueError('CLI arm already has state; inspect/resume it or prepare a new pair, never replay it.')
        checker = scratch / 'check-cli.py'
        if not frozen_file_matches(checker, Path(__file__).with_name('cli-pilot-check.py').read_bytes()):
            raise ValueError('Frozen CLI checker changed; do not start this arm.')
        with tempfile.TemporaryDirectory(prefix='modelmate-cli-reference-') as directory:
            reference = Path(directory)
            expected = prepare_cli(reference, 'standard' if arm == 'routed' else 'strong', checker)
            (reference / 'plan.json').write_text(json.dumps(expected, indent=2) + '\n', encoding='utf-8')
            names = {path.name for path in reference.iterdir()}
            if ({path.name for path in project.iterdir()} != names or any(
                    not frozen_file_matches(project / name, (reference / name).read_bytes()) for name in names)):
                raise ValueError('Frozen CLI inputs changed; do not start this arm.')
    measured_pair = case_file.is_file() and case_file.read_text(encoding='utf-8').strip() in ('dedupe', 'incident', 'cleanup')
    mode = 'approve_plan'
    if checks.is_file():
        mode = 'ask_to_escalate'
    elif measured_pair:
        mode = 'auto'
    args = [sys.executable, str(runtime), '--workflow', str(plan_path),
            '--workflow-mode', mode, '--role-model', 'standard=' + standard,
            '--role-model', 'strong=' + strong]
    if checks.is_file():
        if not economy or economy in (standard, strong) or not economy.strip():
            raise ValueError('Command-check pilots require a third distinct model ID supporting low effort.')
        args.extend(['--check-commands', str(checks), '--role-model', 'economy=' + economy])
    if arm == 'routed':
        args.append('--suggest-models')
    if execute:
        args.append('--execute-workflow')
    if tool_approvals:
        args.append('--experimental-tool-approvals')
    if measure_quota or (execute and measured_pair):
        args.append('--measure-quota')
    if metrics_jsonl is not None:
        args.extend(['--metrics-jsonl', os.path.abspath(metrics_jsonl)])
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


def score_dedupe(answer):
    candidate = DEDUPE_CHOICES.get(answer.strip())
    if candidate is None:
        raise ValueError('The answer must be exactly one letter A, B, C or D.')
    cases = [
        ('empty', [], []),
        ('blanks', ['', ' ', '\t'], []),
        ('first occurrence order', ['z', 'a', 'z'], ['z', 'a']),
        ('duplicates after normalization', [' b', 'a', 'b ', '', 'a '], ['b', 'a']),
        ('distinct rows', ['z', 'b', 'a'], ['z', 'b', 'a']),
    ]
    results = {name: candidate([row for value in values if (row := value.strip())]) == expected
               for name, values, expected in cases}
    print(json.dumps(results, sort_keys=True))
    return 0 if all(results.values()) else 1


def unique_answer_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError('Duplicate answer key.')
        fields[key] = value
    return fields


def score_incident(answer):
    result = json.loads(answer, object_pairs_hook=unique_answer_fields)
    expected = {'timeline': ['A', 'B', 'C', 'D'], 'observed_impact_minutes': 13,
                'root_cause': 'unconfirmed', 'competing_recovery_event': 'C'}
    if not isinstance(result, dict) or result.keys() != expected.keys():
        raise ValueError('Expected the incident answer as one JSON object with the four requested keys.')
    checks = {key: type(result[key]) is type(value) and result[key] == value
              for key, value in expected.items()}
    print(json.dumps(checks))
    return 0 if all(checks.values()) else 1


def score_cleanup(answer):
    if len(answer.encode('utf-8')) > 16384:
        raise ValueError('Cleanup answer exceeds 16 KiB.')
    result = json.loads(answer, object_pairs_hook=unique_answer_fields)
    expected = {'scope_contained': {'safe': False, 'lines': [2, 6]},
                'confirmation_before_delete': {'safe': False, 'lines': [5, 6, 7, 8]},
                'active_blocked': {'safe': True, 'lines': [3, 4, 6]}}
    if not isinstance(result, dict) or result.keys() != expected.keys():
        raise ValueError('Expected exactly the three cleanup properties.')
    checks = {}
    for name, fact in expected.items():
        value = result[name]
        checks[name] = (isinstance(value, dict) and value.keys() == fact.keys()
            and type(value['safe']) is bool and value['safe'] == fact['safe']
            and isinstance(value['lines'], list) and all(type(line) is int for line in value['lines'])
            and value['lines'] == fact['lines'])
    print(json.dumps(checks, sort_keys=True))
    return 0 if all(checks.values()) else 1


def read_metrics_row(path, row_number):
    if row_number is not None and row_number < 1:
        raise ValueError('Metrics row numbers start at 1.')
    with path.open(encoding='utf-8') as source:
        if row_number is None:
            line = source.readline()
            if source.readline():
                raise ValueError('Choose an explicit row for ' + str(path) + '.')
        else:
            line = next((line for index, line in enumerate(source, 1) if index == row_number), '')
    if not line:
        raise ValueError('Metrics row not found in ' + str(path) + '.')
    row = json.loads(line)
    if not isinstance(row, dict) or type(row.get('schemaVersion')) is not int or row['schemaVersion'] != 1:
        raise ValueError('Unsupported metrics record in ' + str(path) + '.')
    return row


def comparison_metrics(report):
    def number(value):
        return value if type(value) in (float, int) and 0 <= value < 2 ** 63 and math.isfinite(value) else None

    attempts = report.get('attempts')
    timed = report.get('timedTurns')
    turns = report.get('workTurnMeasurements')
    complete = (type(attempts) is int and attempts > 0 and type(timed) is int
                and isinstance(turns, list) and len(turns) == timed == attempts
                and report.get('attemptsScope') == 'workflow_total'
                and all(isinstance(turn, dict) and turn.get('terminalStatus') == 'completed'
                        and number(turn.get('elapsedSeconds')) is not None for turn in turns))
    usage = report.get('tokenUsage')
    total = usage.get('total') if isinstance(usage, dict) else None
    last = usage.get('last') if isinstance(usage, dict) else None
    tokens_comparable = (complete and type(report.get('recheckAttempts')) is int
                         and report['recheckAttempts'] == 0
                         and report.get('tokenUsageScope') == 'last_observed_work_thread_update'
                         and isinstance(total, dict) and isinstance(last, dict)
                         and turns[-1].get('lastReportedTokens') == last)
    return {
        'state': report.get('state'), 'attempts': attempts, 'timedTurns': timed,
        'requestedSelections': report.get('requestedSelections'),
        'observedModelReroutes': [transition for turn in turns if isinstance(turn, dict)
                                 and isinstance(turn.get('modelReroutes'), list)
                                 for transition in turn['modelReroutes']] if isinstance(turns, list) else [],
        'allRecordedWorkTurnsCompletedHere': complete,
        'workTurnSeconds': number(report.get('turnElapsedSeconds')) if complete else None,
        'timeToAcceptanceSeconds': number(report.get('timeToAcceptanceSeconds'))
        if complete and report.get('state') == 'DONE' else None,
        'firstPassRate': report.get('firstPassRate'), 'firstPassSteps': report.get('firstPassSteps'),
        'cliWallSecondsIncludingUserWait': number(report.get('elapsedSeconds'))
        if report.get('elapsedScope') == 'current_cli_session' and report.get('includesUserWait') is True else None,
        'reportedWorkThreadTokens': number(total.get('totalTokens')) if tokens_comparable else None,
        'reportedCachedInputTokens': number(total.get('cachedInputTokens')) if tokens_comparable else None,
    }


def compare(baseline_path, routed_path, baseline_row, routed_row):
    baseline = comparison_metrics(read_metrics_row(baseline_path, baseline_row))
    routed = comparison_metrics(read_metrics_row(routed_path, routed_row))
    fields = ('workTurnSeconds', 'timeToAcceptanceSeconds', 'reportedWorkThreadTokens', 'reportedCachedInputTokens')
    deltas = {key: round(routed[key] - baseline[key], 3)
              if routed[key] is not None and baseline[key] is not None else None for key in fields}
    print(json.dumps({'baseline': baseline, 'routed': routed, 'routedMinusBaseline': deltas},
                     indent=2, ensure_ascii=True, allow_nan=False))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    setup = actions.add_parser('prepare', help='make a fresh pair and print its path')
    setup.add_argument('--case', choices=('c1', 'economy', 'dedupe', 'incident', 'cli', 'cleanup'), default='c1')
    launch = actions.add_parser('run', help='preview one arm, or opt in to a live workflow')
    launch.add_argument('scratch', type=Path)
    launch.add_argument('arm', choices=('routed', 'baseline'))
    launch.add_argument('--standard', required=True)
    launch.add_argument('--strong', required=True)
    launch.add_argument('--economy')
    launch.add_argument('--execute', action='store_true', help='enable START and turn approval, which can use quota')
    launch.add_argument('--measure-quota', action='store_true', help='include observed live quota-window changes')
    launch.add_argument('--metrics-jsonl', help='append a private metrics report without account quota data')
    launch.add_argument('--experimental-tool-approvals', action='store_true',
                        help='explicit native patch/command approval UI for the CLI authoring pilot')
    grade = actions.add_parser('score', help='score a turn answer with the case rubric')
    grade.add_argument('answer')
    grade.add_argument('--case', choices=('c1', 'dedupe', 'incident', 'cleanup'), default='c1')
    analysis = actions.add_parser('compare', help='compare two private metrics records offline')
    analysis.add_argument('baseline', type=Path)
    analysis.add_argument('routed', type=Path)
    analysis.add_argument('--baseline-row', type=int)
    analysis.add_argument('--routed-row', type=int)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            prepare(args.case)
            return 0
        if args.action == 'run':
            return run(args.scratch, args.arm, args.standard, args.strong, args.execute, args.economy,
                       args.measure_quota, args.metrics_jsonl, args.experimental_tool_approvals)
        if args.action == 'compare':
            return compare(args.baseline, args.routed, args.baseline_row, args.routed_row)
        scorers = {'c1': score, 'dedupe': score_dedupe, 'incident': score_incident, 'cleanup': score_cleanup}
        return scorers[args.case](args.answer)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    sys.exit(main())
