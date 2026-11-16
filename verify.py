#!/usr/bin/env python3
"""Opt-in live Codex checks: context handoff and denial of scratch-file writes."""
import argparse
import json
import math
import secrets
import shutil
import sys
import tempfile
import time
from pathlib import Path

from modelmate import Connection, ProbeError, inspect


APPROVALS = {
    'item/commandExecution/requestApproval': 'command',
    'item/fileChange/requestApproval': 'file',
}


class VerificationConnection(Connection):
    allowed_methods = Connection.allowed_methods | {'thread/start', 'turn/start', 'turn/interrupt'}

    def __init__(self, command, timeout):
        super().__init__(command, timeout)
        self.events = []
        self.denials = []
        self.thread_id = None
        self.turn_id = None
        self.start_pending = False
        self.account_id = None

    def handle_event(self, message):
        method = message.get('method')
        if not isinstance(message.get('params'), dict):
            raise ProbeError('Malformed server event; no action approved.')
        if 'id' in message:
            if method not in APPROVALS:
                raise ProbeError('Unexpected permission/tool request; nothing approved.')
            params = message.get('params', {})
            if (not isinstance(params, dict) or params.get('threadId') != self.thread_id
                    or not params.get('turnId') or not params.get('itemId')
                    or not isinstance(params.get('turnId'), str)
                    or (self.turn_id is not None and params['turnId'] != self.turn_id)):
                raise ProbeError('Approval belongs to a different thread; nothing approved.')
            self.denials.append((APPROVALS[method], params.get('turnId')))
            self.send({'id': message['id'], 'result': {'decision': 'decline'}})
        else:
            if method == 'turn/started' and message.get('params', {}).get('threadId') == self.thread_id:
                turn_id = message['params'].get('turn', {}).get('id')
                if not isinstance(turn_id, str) or not turn_id:
                    raise ProbeError('Invalid turn ID.')
                if self.turn_id is not None and self.turn_id != turn_id:
                    raise ProbeError('Conflicting active turn ID.')
                self.turn_id = turn_id
            self.events.append(message)
            if len(self.events) > 10000:
                raise ProbeError('Too many events; stopping verification.')

    def run_turn(self, prompt, model, effort):
        if self.start_pending or self.turn_id:
            raise ProbeError('Previous turn outcome unknown; no new turn started.')
        quota = self.request('account/rateLimits/read')
        ensure_quota(quota)
        account_id = quota.get('accountId')
        if not isinstance(account_id, str) or not account_id:
            raise ProbeError('Account identity unavailable; no new turn started.')
        if self.account_id is not None and account_id != self.account_id:
            raise ProbeError('Account changed; no new turn started.')
        self.account_id = account_id
        self.events.clear()
        self.denials.clear()
        deadline = time.monotonic() + self.timeout
        self.start_pending = True
        result = self.request('turn/start', {
            'threadId': self.thread_id, 'model': model, 'effort': effort,
            'input': [{'type': 'text', 'text': prompt}],
        })
        turn_id = result.get('turn', {}).get('id')
        if not isinstance(turn_id, str) or not turn_id or (self.turn_id and self.turn_id != turn_id):
            raise ProbeError('Invalid or conflicting turn ID; outcome unknown.')
        self.turn_id = turn_id
        self.start_pending = False
        messages = []
        while True:
            events, self.events = self.events, []
            for event in events:
                params = event.get('params', {})
                if params.get('threadId') != self.thread_id:
                    continue
                if event.get('method') == 'item/completed' and params.get('turnId') == self.turn_id:
                    item = params.get('item', {})
                    if item.get('type') == 'agentMessage':
                        messages.append(item.get('text', ''))
                if event.get('method') == 'turn/completed' and params.get('turn', {}).get('id') == self.turn_id:
                    turn = params['turn']
                    completed_id = self.turn_id
                    self.turn_id = None
                    if turn.get('status') != 'completed':
                        raise ProbeError('Verification turn did not complete successfully.')
                    return '\n'.join(messages), {kind for kind, tid in self.denials if tid == completed_id}
            self.handle_event(self.receive(deadline))

    def interrupt(self):
        if self.start_pending and not self.turn_id:
            raise ProbeError('Turn start outcome unknown; no automatic retry is safe.')
        if not self.turn_id:
            return
        target = self.turn_id
        self.request('turn/interrupt', {'threadId': self.thread_id, 'turnId': target})
        deadline = time.monotonic() + self.timeout
        while True:
            events, self.events = self.events, []
            for event in events:
                params = event.get('params', {})
                if (event.get('method') == 'turn/completed' and params.get('threadId') == self.thread_id
                        and params.get('turn', {}).get('id') == target
                        and params['turn'].get('status') in {'completed', 'failed', 'interrupted'}):
                    self.turn_id = None
                    self.start_pending = False
                    return
            self.handle_event(self.receive(deadline))


def ensure_quota(quota):
    if not isinstance(quota, dict) or quota.get('ordinaryUsageAllowed') is not True:
        raise ProbeError('Included usage is unavailable or unknown; no new turn started.')
    buckets = quota.get('rateLimitsByLimitId')
    if buckets is None:
        buckets = {'default': quota.get('rateLimits')}
    if not isinstance(buckets, dict) or not buckets:
        raise ProbeError('Quota buckets unavailable; no new turn started.')
    for bucket in buckets.values():
        if not isinstance(bucket, dict):
            raise ProbeError('Invalid quota snapshot.')
        if bucket.get('spendControlReached') or bucket.get('rateLimitReachedType'):
            raise ProbeError('A quota limit is reached; no new turn started.')
        if not any(isinstance(bucket.get(k), dict) for k in ('primary', 'secondary')):
            raise ProbeError('Quota windows unavailable; no new turn started.')
        for name in ('primary', 'secondary'):
            window = bucket.get(name)
            if window is not None:
                if not isinstance(window, dict):
                    raise ProbeError('Invalid quota window.')
                used = window.get('usedPercent')
                if type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used < 100:
                    raise ProbeError('Quota window exhausted or invalid; no new turn started.')
        credits = bucket.get('credits')
        if credits is None:
            credits = {}
        if not isinstance(credits, dict):
            raise ProbeError('Invalid credit snapshot.')
        if credits.get('hasCredits') or credits.get('unlimited'):
            raise ProbeError('Extra credit access detected; this subscription-only verification will not run.')


def choose_models(catalog, names):
    if names[0] == names[1]:
        raise ProbeError('Select two different models to verify handoff.')
    selected = []
    for name in names:
        model = next((m for m in catalog if m.get('model') == name), None)
        if model is None:
            raise ProbeError('A selected model is not in the account catalog. Run doctor.py first.')
        efforts = [v['reasoningEffort'] for v in model.get('supportedReasoningEfforts') or []]
        effort = 'low' if 'low' in efforts else model.get('defaultReasoningEffort')
        if effort not in efforts:
            raise ProbeError('Cannot verify a supported reasoning effort for the selected model.')
        selected.append((name, effort))
    return selected


def verify(connection, models, directory):
    nonce = secrets.token_hex(16)
    first, second = models
    result = connection.request('thread/start', {
        'cwd': str(directory), 'model': first[0], 'modelProvider': 'openai',
        'sandbox': 'read-only', 'approvalPolicy': 'on-request',
        'approvalsReviewer': 'user', 'ephemeral': True, 'serviceTier': 'default',
        'config': {'web_search': 'disabled', 'agents.enabled': False},
        'developerInstructions': 'This is a synthetic verification. Use no network or subagents. '
        'Only attempt the exact scratch-file action explicitly requested. '
        'If approval is declined, do not retry or use another tool; finish the turn.',
    })
    connection.thread_id = result['thread']['id']
    print('Checking context handoff (two model turns)...', file=sys.stderr)
    connection.run_turn('Remember this synthetic code for the next message: ' + nonce +
                        '. Do not use tools or write files. Reply only ACK.', *first)
    answer, _ = connection.run_turn('Reply only with the synthetic code from my previous message. '
                                    'Do not use tools.', *second)
    if answer.strip() != nonce:
        raise ProbeError('Context recall check failed; handoff is not verified.')
    print('Context recall passed. Checking command and patch denials...', file=sys.stderr)
    for kind, filename in [('command', 'command-marker.txt'), ('file', 'patch-marker.txt')]:
        marker = directory / filename
        if kind == 'command':
            prompt = f'Use the shell tool once to run: printf test > {filename}. Request approval if needed.'
        else:
            prompt = f'Use apply_patch once to add {filename} containing test. Request approval if needed.'
        _, denied = connection.run_turn(prompt + ' If denied, stop; do not try an alternative.', *first)
        if marker.exists():
            raise ProbeError('A marker was written; approval protection check FAILED.')
        if kind not in denied:
            raise ProbeError('No matching approval request observed; this check is INCONCLUSIVE, not passed.')
    return {'contextRecall': 'passed', 'commandDenial': 'passed', 'patchDenial': 'passed',
            'scope': 'Only these synthetic actions; not proof that every tool path requires approval.',
            'requestedModels': [m[0] for m in models], 'reportedModels': None,
            'modelSwitch': 'unverified: context recall alone does not prove actual model dispatch'}


def run_in_scratch(connection, models):
    directory = tempfile.mkdtemp(prefix='modelmate-verify-')
    failed = False
    try:
        return verify(connection, models, Path(directory))
    except BaseException:
        failed = True
        raise
    finally:
        try:
            connection.interrupt()
        except (ProbeError, OSError):
            print('Interruption unconfirmed; scratch directory retained: ' + directory, file=sys.stderr)
            if not failed:
                raise ProbeError('Turn outcome unknown; check Codex before retrying.')
        else:
            try:
                shutil.rmtree(directory)
            except OSError:
                print('Could not remove scratch directory: ' + directory, file=sys.stderr)
                if not failed:
                    raise ProbeError('Scratch cleanup failed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true', help='explicitly run inference using subscription quota')
    parser.add_argument('--models', nargs=2, metavar=('FIRST', 'SECOND'), help='two model IDs from doctor.py')
    parser.add_argument('--timeout', type=float, default=120, help='RPC/turn timeout in seconds')
    args = parser.parse_args()
    if not args.run_live:
        parser.print_help()
        return 0
    if not args.models:
        parser.error('--models FIRST SECOND is required for live verification')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and positive')
    connection = None
    try:
        connection = VerificationConnection(['codex', 'app-server', '--stdio'], args.timeout)
        report = inspect(connection)
        models = choose_models(report['models'], args.models)
        result = run_in_scratch(connection, models)
        print(json.dumps(result, indent=2))
        return 0
    except KeyboardInterrupt:
        print('Verification cancelled.', file=sys.stderr)
        return 130
    except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        message = str(exc) if isinstance(exc, ProbeError) else 'Verification failed; inspect installation/protocol compatibility.'
        print(message, file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.interrupt()
            except (ProbeError, OSError):
                print('Could not confirm turn interruption. Check Codex before retrying.', file=sys.stderr)
            finally:
                connection.close()


if __name__ == '__main__':
    sys.exit(main())
