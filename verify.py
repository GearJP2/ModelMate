#!/usr/bin/env python3
"""Opt-in live Codex checks: handoff, scratch permissions and session lifecycle."""
import argparse
import hashlib
import io
import json
import math
import secrets
import shutil
import sys
import tempfile
import time
from pathlib import Path

from modelmate import (Connection, ProbeError, inspect, ensure_quota, refresh_quota,
                       select_model, LiveChatConnection, ChatShell, SessionStore, THREAD_SOURCE_KINDS, NativeWorkflowConnection, WorkflowController, diagnostic_code)


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


class SessionVerificationConnection(LiveChatConnection):
    """Observe synthetic turns using the actual runtime lifecycle implementation."""

    def __init__(self, command, timeout):
        super().__init__(command, timeout)
        self.answer = ''
        self.completed_status = None
        self.tool_observed = False

    def handle_event(self, message):
        params = message.get('params', {})
        matching = self.shell is not None and params.get('threadId') == self.thread_id
        method = message.get('method')
        if matching:
            item = params.get('item', {})
            if 'id' in message or (method in ('item/started', 'item/completed')
                    and item.get('type') not in ('userMessage', 'agentMessage', 'reasoning',
                                                 'plan', 'contextCompaction')):
                self.tool_observed = True
            if method == 'item/completed' and params.get('turnId') == self.turn_id and item.get('type') == 'agentMessage':
                text = item.get('text')
                if not isinstance(text, str) or len(self.answer) + len(text) > 4096:
                    raise ProbeError('Session probe returned oversized or invalid text.')
                self.answer += text
            if method == 'turn/completed' and params.get('turn', {}).get('id') == self.turn_id:
                self.completed_status = params['turn'].get('status')
        super().handle_event(message)

    def wait_idle(self, timeout, *, cancelling=False):
        deadline = time.monotonic() + timeout
        while True:
            self.drain()
            self.tick()
            if self.tool_observed and not cancelling:
                raise ProbeError('Unexpected tool observed; session probe did not pass.')
            if not self.shell.active and not self._rpcs:
                return
            if time.monotonic() >= deadline:
                raise ProbeError('Session probe timed out; outcome unknown; no automatic replay.')
            for key, _ in self.selector.select(min(.1, max(0, deadline - time.monotonic()))):
                self.read_ready(key.fileobj)

    def run_text(self, prompt):
        self.shell = ChatShell(io.StringIO(), self.action, self.catalog)
        self.shell.selection = self.selection
        self.answer, self.completed_status = '', None
        self.shell.line(prompt)
        self.wait_idle(self.timeout)
        if self.completed_status != 'completed' or self.record['state'] != 'UNVERIFIED':
            raise ProbeError('Synthetic turn did not complete [' + self.phase + ']; session probe did not pass.')
        return self.answer.strip()


def check_session_sentinel(project, sentinel):
    if (sentinel.is_symlink() or sentinel.read_text() != 'synthetic sentinel\n'
            or set(project.iterdir()) != {sentinel}):
        raise ProbeError('Scratch work files changed; sentinel check failed.')


def probe_sessions(model, timeout):
    """Opt-in creation/deletion only inside this harness's private scratch project."""
    directory = Path(tempfile.mkdtemp(prefix='modelmate-session-verify-'))
    project = directory / 'project'
    sentinel = project / 'sentinel.txt'
    nonce = secrets.token_hex(16)
    connection = None
    passed = False
    phase = 'prepare'
    command = ['codex', 'app-server', '--stdio', '-c', 'forced_login_method="chatgpt"',
               '-c', 'model_provider="openai"', '-c', 'web_search="disabled"',
               '-c', 'approvals_reviewer="user"']
    store = None
    try:
        project.mkdir(mode=0o700)
        sentinel.write_text('synthetic sentinel\n')
        phase = 'start'
        store = SessionStore(project, directory / 'state')
        connection = SessionVerificationConnection(command, timeout)
        connection.connect(model, 'low', project, store=store)
        session_id = connection.record['id']
        thread_id = connection.thread_id
        phase = 'first_turn'
        connection.run_text('Remember this synthetic code for the next message: ' + nonce
                            + '. Reply only ACK. Do not use tools, network or write files.')
        connection.close()
        connection = None
        phase = 'resume'
        connection = SessionVerificationConnection(command, timeout)
        connection.connect(model, 'low', project, store=store, session_id=session_id)
        if connection.thread_id != thread_id or connection.recovery_token is not None:
            raise ProbeError('Resume did not restore the expected settled thread.')
        phase = 'recall'
        answer = connection.run_text('Reply only with the synthetic code from my previous message. '
                                     'Do not use tools or network, and do not read or write files.')
        if answer != nonce:
            raise ProbeError('Context recall after reconnect failed.')
        check_session_sentinel(project, sentinel)
        phase = 'delete_preview'
        connection.session_command('/delete', [])
        proposal = connection.delete_proposal
        if (proposal is None or proposal['record']['id'] != session_id
                or proposal['tree'] != [{'thread_id': thread_id, 'project': str(project)}]):
            raise ProbeError('Deletion scope is not exactly the harness-created scratch thread.')
        phase = 'delete'
        connection.session_command('/confirm-delete', [proposal['token']])
        if connection.record is not None or not connection.shell.closed or store.list_sessions():
            raise ProbeError('Confirmed deletion did not remove local metadata.')
        phase = 'list_after_delete'
        for archived in (False, True):
            cursor, seen = None, set()
            for _ in range(100):
                page = connection.request('thread/list', {'cwd': str(project), 'archived': archived,
                    'limit': 100, 'cursor': cursor, 'sourceKinds': THREAD_SOURCE_KINDS})
                rows = page.get('data')
                if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('id'), str) for r in rows):
                    raise ProbeError('Invalid post-delete listing; deletion not verified.')
                if any(row['id'] == thread_id for row in rows):
                    raise ProbeError('Deleted thread remains in a history listing.')
                cursor = page.get('nextCursor')
                if cursor is None:
                    break
                if not isinstance(cursor, str) or not cursor or cursor in seen:
                    raise ProbeError('Invalid post-delete pagination.')
                seen.add(cursor)
            else:
                raise ProbeError('Post-delete listing exceeded verification limit.')
        phase = 'sentinel'
        check_session_sentinel(project, sentinel)
        result = {'sessionResume': 'passed', 'contextRecallAfterReconnect': 'passed',
                'confirmedDeletion': 'passed', 'localMetadataDeleted': 'passed',
                'threadAbsentFromListings': 'passed', 'sentinelUnchanged': 'passed',
                'requested': {'model': model, 'effort': 'low'}, 'reportedModels': None,
                'runtimeSha256': hashlib.sha256(Path(sys.modules[LiveChatConnection.__module__].__file__).read_bytes()).hexdigest(),
                'verifierSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'scope': 'Two synthetic turns and one scratch thread; not crash recovery, all tool paths, '
                         'backend dispatch telemetry or complete service-side data erasure.'}
        passed = True
        return result
    finally:
        if connection is not None:
            try:
                if connection.shell is not None and connection.shell.active:
                    connection.shell.cancel()
                    connection.wait_idle(5, cancelling=True)
            except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError):
                print('Interruption unconfirmed; inspect Codex before retrying.', file=sys.stderr)
            finally:
                connection.close()
        if store is not None:
            store.close()
        if passed:
            shutil.rmtree(directory)
        else:
            print('Session probe stopped at ' + phase + '; scratch retained: ' + str(directory), file=sys.stderr)


class WorkflowVerificationConnection(NativeWorkflowConnection):
    """Observe only bound denial replies; never retain native traces or assistant text in reports."""
    def __init__(self, command, timeout):
        super().__init__(command, timeout)
        self._requests = {}
        self.declined = 0

    def handle_event(self, message):
        super().handle_event(message)
        if 'id' in message and message.get('method') in APPROVALS:
            if len(self._requests) >= 100:
                raise ProbeError('Too many workflow approval requests.')
            self._requests[message['id']] = message['params']

    def send(self, message):
        super().send(message)
        if message.get('result') == {'decision': 'decline'}:
            params = self._requests.pop(message.get('id'), {})
            binding = self.host._binding if self.host is not None else None
            if (binding is not None and params.get('threadId') == binding['thread_id']
                    and params.get('turnId') == binding['turn_id']):
                self.declined += 1


def wait_workflow(connection, seconds, *, allow_denial=False):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            connection.drain()
        except ProbeError as exc:
            if not (allow_denial and connection.declined
                    and str(exc) == 'Workflow tool approvals are not enabled; nothing approved.'
                    and connection.host.controller.reason == 'unsupported_capability'):
                raise
        if connection.host._terminal is not None:
            return connection.host._terminal
        for key, _ in connection.selector.select(min(.1, max(0, deadline - time.monotonic()))):
            connection.read_ready(key.fileobj)
    raise ProbeError('Workflow probe timed out; outcome unknown; no replay.')


def probe_workflow(model, timeout):
    """Up to four synthetic turns; no retries, durable sessions or user-project changes."""
    directory = Path(tempfile.mkdtemp(prefix='modelmate-workflow-verify-'))
    sentinel = directory / 'sentinel.txt'
    sentinel.write_text('synthetic sentinel\n')
    connection = None
    safe_cleanup = True
    result = {key: 'unverified' for key in ('answerDisplay', 'contextRecall', 'approvalDenial',
              'sentinelUnchanged', 'cancel', 'disconnectGuard')}
    result.update(requested={'model': model, 'effort': 'low'}, reportedModels=None,
        runtimeSha256=hashlib.sha256(Path(sys.modules[NativeWorkflowConnection.__module__].__file__).read_bytes()).hexdigest(),
        verifierSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope='At most four synthetic turns in ephemeral threads. Disconnect guard is local only; '
              'not network-drop recovery, all tool paths, backend dispatch telemetry or service-side erasure.')
    command = ['codex', 'app-server', '--stdio', '-c', 'forced_login_method="chatgpt"',
               '-c', 'model_provider="openai"', '-c', 'web_search="disabled"',
               '-c', 'approvals_reviewer="user"']
    # This is an explicit requested selection; connect/preflight validates the real catalog before inference.
    catalog = [{'model': model, 'defaultReasoningEffort': 'low',
                'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}]
    policy = {role: model for role in ('economy', 'standard', 'strong')}

    def make_controller(prompts):
        return WorkflowController(json.dumps({'version': 1, 'goal': 'Synthetic workflow verification',
            'clarifications': [], 'success_criteria': ['Harness observed synthetic outcomes'],
            'steps': [{'kind': 'implement', 'objective': prompt, 'role': 'standard', 'effort': 'low',
                       'risk': 'normal', 'reason': 'Explicit opt-in synthetic probe',
                       'checks': [{'kind': 'manual', 'criterion': 'Harness verifies the synthetic answer'}]}
                      for prompt in prompts]}), catalog, policy)

    def close_connection():
        nonlocal connection, safe_cleanup
        if connection is None:
            return
        try:
            host = connection.host
            if host is not None and host.controller.snapshot()['active_attempt'] is not None and host._terminal is None:
                previously_safe = safe_cleanup
                safe_cleanup = False
                host({'action': 'cancel', 'task_id': host.controller.task_id})
                wait_workflow(connection, 5, allow_denial=True)
                safe_cleanup = previously_safe
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError):
            safe_cleanup = False
        finally:
            connection.close()
            connection = None

    try:
        nonce = secrets.token_hex(16)
        prompts = ['Remember this synthetic code: ' + nonce + '. Reply only ACK. Do not use tools or network.',
                   'Reply only with the synthetic code from the preceding step. Do not use tools or network.',
                   'Use a command tool to replace sentinel.txt in the current working directory with PROBE_CHANGED. '
                   'Request permission if the sandbox requires it. Do not touch any other file or use network.']
        result['phase'] = 'context_connect'
        controller = make_controller(prompts)
        connection = WorkflowVerificationConnection(command, timeout)
        host = connection.connect(controller, directory, policy)
        host.timeout = timeout
        output = io.StringIO()
        shell = ChatShell(output, workflow=controller, workflow_action=host)
        answers = []
        def observe(message):
            shell.event(message)
            if message.get('type') == 'text':
                answers.append(message['text'].strip())
        host.on_change = observe
        for index in (0, 1):
            result['phase'] = 'answer_display' if index == 0 else 'context_recall'
            output.seek(0); output.truncate()
            host({'action': 'next', 'task_id': controller.task_id})
            status = wait_workflow(connection, timeout)
            expected = 'ACK' if index == 0 else nonce
            # Only text events are answers; UI status/plan output is deliberately excluded.
            if status != 'completed' or answers != [expected]:
                result['answerDisplay' if index == 0 else 'contextRecall'] = 'failed'
                return result
            result['answerDisplay' if index == 0 else 'contextRecall'] = 'passed'
            active = controller.snapshot()['active_attempt']
            controller.record_check(active['id'], 0, origin='manual', result='pass',
                                    reference='synthetic harness comparison', finding='Exact expected answer observed')
            host({'action': 'check', 'task_id': controller.task_id})
            answers.clear()
        result['phase'] = 'approval_denial'
        host({'action': 'next', 'task_id': controller.task_id})
        wait_workflow(connection, timeout, allow_denial=True)
        if connection.declined:
            result['approvalDenial'] = 'passed'
        try:
            check_session_sentinel(directory, sentinel)
        except (ProbeError, OSError, UnicodeError):
            result['approvalDenial'] = result['sentinelUnchanged'] = 'failed'
            return result
        result['sentinelUnchanged'] = 'passed'
        close_connection()
        if not safe_cleanup:
            return result
        result['phase'] = 'cancel_connect'
        controller = make_controller(['Do not use tools or network. Write the integers 1 through 10000, one per line.'])
        connection = WorkflowVerificationConnection(command, timeout)
        host = connection.connect(controller, directory, policy)
        host.timeout = timeout
        result['phase'] = 'cancel'
        host({'action': 'next', 'task_id': controller.task_id})
        host({'action': 'cancel', 'task_id': controller.task_id})
        status = wait_workflow(connection, timeout)
        result['cancel'] = 'passed' if status == 'interrupted' else 'unverified'
        result['phase'] = 'disconnect_guard'
        sent = len(connection._sent_attempts)
        host.disconnect()
        try:
            host({'action': 'next', 'task_id': controller.task_id})
        except ProbeError:
            result['disconnectGuard'] = 'passed' if len(connection._sent_attempts) == sent else 'failed'
        result['phase'] = 'finished'
        return result
    except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result['diagnostic'] = diagnostic_code(exc)
        return result
    finally:
        close_connection()
        try:
            check_session_sentinel(directory, sentinel)
            result['sentinelUnchanged'] = 'passed'
        except (ProbeError, OSError, UnicodeError):
            result['sentinelUnchanged'] = 'failed'
        if safe_cleanup and all(result.get(key) == 'passed' for key in (
                'answerDisplay', 'contextRecall', 'approvalDenial', 'sentinelUnchanged', 'cancel', 'disconnectGuard')):
            shutil.rmtree(directory)
        else:
            print('Workflow probe incomplete; inspect Codex before retrying. Scratch retained: ' + str(directory), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true', help='explicitly run inference using subscription quota')
    parser.add_argument('--models', nargs=2, metavar=('FIRST', 'SECOND'), help='two model IDs from doctor.py')
    parser.add_argument('--probe-read-approval', metavar='MODEL',
                        help='one live turn testing whether harmless printf runs without approval; no handoff rerun')
    parser.add_argument('--probe-sessions', metavar='MODEL',
                        help='two live turns across reconnect; delete only the harness-created scratch thread')
    parser.add_argument('--probe-workflow', metavar='MODEL',
                        help='up to four synthetic native workflow turns: answers, denial and cancel; local disconnect guard')
    parser.add_argument('--timeout', type=float, default=120, help='RPC/turn timeout in seconds')
    args = parser.parse_args()
    if not args.run_live:
        parser.print_help()
        return 0
    if sum(bool(value) for value in (args.models, args.probe_read_approval, args.probe_sessions, args.probe_workflow)) != 1:
        parser.error('choose one of --models FIRST SECOND, --probe-read-approval MODEL, --probe-sessions MODEL, --probe-workflow MODEL')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and positive')
    connection = None
    try:
        if args.probe_workflow:
            result = probe_workflow(args.probe_workflow, args.timeout)
            print(json.dumps(result, indent=2))
            return 0 if all(result.get(key) == 'passed' for key in (
                'answerDisplay', 'contextRecall', 'approvalDenial', 'sentinelUnchanged', 'cancel', 'disconnectGuard')) else 1
        if args.probe_sessions:
            result = probe_sessions(args.probe_sessions, args.timeout)
            print(json.dumps(result, indent=2))
            return 0
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
