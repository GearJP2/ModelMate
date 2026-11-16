#!/usr/bin/env python3
"""Opt-in live Codex checks: context handoff and denial of scratch-file writes."""
import argparse
import json
import math
import secrets
import sys
import tempfile
import time
from pathlib import Path

from doctor import Connection, ProbeError, inspect


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

    def handle_event(self, message):
        method = message.get('method')
        if 'id' in message:
            if method not in APPROVALS:
                raise ProbeError('Unexpected permission/tool request; nothing approved.')
            params = message.get('params', {})
            if params.get('threadId') != self.thread_id:
                raise ProbeError('Approval belongs to a different thread; nothing approved.')
            self.denials.append((APPROVALS[method], params.get('turnId')))
            self.send({'id': message['id'], 'result': {'decision': 'decline'}})
        else:
            if method == 'turn/started' and message.get('params', {}).get('threadId') == self.thread_id:
                self.turn_id = message['params']['turn']['id']
            self.events.append(message)
            if len(self.events) > 10000:
                raise ProbeError('Too many events; stopping verification.')

    def run_turn(self, prompt, model, effort):
        ensure_quota(self.request('account/rateLimits/read'))
        self.events.clear()
        self.denials.clear()
        result = self.request('turn/start', {
            'threadId': self.thread_id, 'model': model, 'effort': effort,
            'input': [{'type': 'text', 'text': prompt}],
        })
        self.turn_id = result['turn']['id']
        deadline = time.monotonic() + self.timeout
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
        if self.thread_id and self.turn_id:
            self.request('turn/interrupt', {'threadId': self.thread_id, 'turnId': self.turn_id})
            self.turn_id = None


def ensure_quota(quota):
    if quota.get('ordinaryUsageAllowed') is not True:
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
        for name in ('primary', 'secondary'):
            window = bucket.get(name)
            if window is not None:
                used = window.get('usedPercent')
                if type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used < 100:
                    raise ProbeError('Quota window exhausted or invalid; no new turn started.')
        credits = bucket.get('credits') or {}
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
            'models': [m[0] for m in models]}


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
        with tempfile.TemporaryDirectory(prefix='modelmate-verify-') as directory:
            try:
                result = verify(connection, models, Path(directory))
            finally:
                connection.interrupt()
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
