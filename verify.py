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

from modelmate import Connection, ProbeError, inspect, ensure_quota, refresh_quota, select_model


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
        self.turn_evidence = []
        self.settings_observed = []
        self.denied_items = set()

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
            self.denied_items.add(params['itemId'])
            self.send({'id': message['id'], 'result': {'decision': 'decline'}})
        else:
            params = message['params']
            if method == 'thread/settings/updated' and params.get('threadId') == self.thread_id:
                settings = params.get('threadSettings')
                if not isinstance(settings, dict):
                    raise ProbeError('Invalid thread settings metadata.')
                observed = {key: settings.get(key) for key in ('model', 'effort')}
                if any(value is not None and (not isinstance(value, str) or len(value) > 128
                                              or not value.isprintable()) for value in observed.values()):
                    raise ProbeError('Invalid model/effort metadata.')
                self.settings_observed.append(observed)
                if len(self.settings_observed) > 100:
                    raise ProbeError('Too many settings observations.')
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
        self.quota_status = refresh_quota(self, self.account_id)
        if self.quota_status['state'] != 'allow':
            raise ProbeError('Quota check paused: ' + self.quota_status['reason'] + '; no new turn started.')
        self.account_id = self.quota_status['account_id']
        self.events.clear()
        self.denials.clear()
        self.denied_items.clear()
        self.settings_observed.clear()
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
        tools = []
        while True:
            events, self.events = self.events, []
            for event in events:
                params = event.get('params', {})
                if params.get('threadId') != self.thread_id:
                    continue
                if event.get('method') == 'item/completed' and params.get('turnId') == self.turn_id:
                    item = params.get('item', {})
                    if item.get('type') in ('commandExecution', 'fileChange'):
                        status = item.get('status')
                        if status not in ('completed', 'failed', 'declined', 'inProgress'):
                            raise ProbeError('Invalid tool completion status.')
                        tools.append({'type': item['type'], 'status': status,
                                      'denialObserved': item.get('id') in self.denied_items})
                    if item.get('type') == 'agentMessage':
                        messages.append(item.get('text', ''))
                if event.get('method') == 'turn/completed' and params.get('turn', {}).get('id') == self.turn_id:
                    turn = params['turn']
                    completed_id = self.turn_id
                    self.turn_id = None
                    if turn.get('status') != 'completed':
                        raise ProbeError('Verification turn did not complete successfully.')
                    self.turn_evidence.append({
                        'requested': {'model': model, 'effort': effort},
                        'threadSettingsObserved': list(self.settings_observed),
                        'toolsObserved': tools,
                        'scope': 'Thread configuration observed during the turn; not backend dispatch telemetry.'})
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


def choose_models(catalog, names):
    if names[0] == names[1]:
        raise ProbeError('Select two different models to verify handoff.')
    selected = []
    for name in names:
        choice = select_model(catalog, name)
        model = next(m for m in catalog if m['model'] == name)
        if any(v['reasoningEffort'] == 'low' for v in model['supportedReasoningEfforts']):
            choice = select_model(catalog, name, 'low')
        selected.append((choice['model'], choice['effort']))
    return selected


def start_verification_thread(connection, model, directory):
    result = connection.request('thread/start', {
        'cwd': str(directory), 'model': model, 'modelProvider': 'openai',
        'sandbox': 'read-only', 'approvalPolicy': 'on-request',
        'approvalsReviewer': 'user', 'ephemeral': True, 'serviceTier': 'default',
        'config': {'web_search': 'disabled', 'agents.enabled': False},
        'developerInstructions': 'This is a synthetic verification. Use no network or subagents. '
        'Only attempt the exact scratch-file action explicitly requested. '
        'If approval is declined, do not retry or use another tool; finish the turn.',
    })
    connection.thread_id = result['thread']['id']


def verify(connection, models, directory):
    nonce = secrets.token_hex(16)
    first, second = models
    start_verification_thread(connection, first[0], directory)
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
            'turnEvidence': connection.turn_evidence,
            'modelSwitch': 'unverified: context recall alone does not prove actual model dispatch'}


def probe_read_approval(connection, models, directory):
    """Observe a harmless shell command under the existing approval policy."""
    model, effort = models[0]
    start_verification_thread(connection, model, directory)
    connection.run_turn(
        'Use the shell tool once to run exactly: printf MODEL_MATE_READ_PROBE. '
        'This command only prints a synthetic marker. Do not write or read files, '
        'do not request elevated permissions and do not use another tool. '
        'If approval is denied or the tool is unavailable, stop.', model, effort)
    evidence = connection.turn_evidence[-1]
    commands = [item for item in evidence['toolsObserved'] if item['type'] == 'commandExecution']
    if any(item['status'] == 'completed' and not item['denialObserved'] for item in commands):
        state = 'executed_without_approval'
    elif commands and all(item['denialObserved'] and item['status'] in ('declined', 'failed')
                          for item in commands):
        state = 'denial_observed_for_this_command'
    else:
        state = 'inconclusive'
    return {'readCommandApproval': state, 'turnEvidence': connection.turn_evidence,
            'scope': 'One harmless printf command. Does not verify every tool path.',
            'reportedModels': None, 'modelSwitch': 'not tested'}


def run_in_scratch(connection, models, *, read_probe=False):
    directory = tempfile.mkdtemp(prefix='modelmate-verify-')
    failed = False
    try:
        if read_probe:
            return probe_read_approval(connection, models, Path(directory))
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
    parser.add_argument('--probe-read-approval', metavar='MODEL',
                        help='one live turn testing whether harmless printf runs without approval; no handoff rerun')
    parser.add_argument('--timeout', type=float, default=120, help='RPC/turn timeout in seconds')
    args = parser.parse_args()
    if not args.run_live:
        parser.print_help()
        return 0
    if bool(args.models) == bool(args.probe_read_approval):
        parser.error('choose either --models FIRST SECOND or --probe-read-approval MODEL')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and positive')
    connection = None
    try:
        connection = VerificationConnection(['codex', 'app-server', '--stdio'], args.timeout)
        report = inspect(connection)
        if args.probe_read_approval:
            choice = select_model(report['models'], args.probe_read_approval)
            options = next(m for m in report['models'] if m['model'] == choice['model'])
            if any(e['reasoningEffort'] == 'low' for e in options['supportedReasoningEfforts']):
                choice = select_model(report['models'], choice['model'], 'low')
            models = [(choice['model'], choice['effort'])]
        else:
            models = choose_models(report['models'], args.models)
        result = run_in_scratch(connection, models, read_probe=bool(args.probe_read_approval))
        print(json.dumps(result, indent=2))
        if args.probe_read_approval:
            return 0 if result['readCommandApproval'] == 'denial_observed_for_this_command' else 1
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
