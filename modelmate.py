#!/usr/bin/env python3
"""ModelMate runtime primitives. Importing this module performs no I/O."""
import json
import copy
import math
import os
import selectors
import subprocess
import time
from datetime import datetime, timezone
from contextlib import contextmanager


class ProbeError(Exception):
    pass


class WorkflowPreflightPause(ProbeError):
    def __init__(self, reason):
        super().__init__('Workflow preflight paused: ' + reason)
        self.reason = reason


class Connection:
    allowed_methods = {"initialize", "account/read", "model/list", "account/rateLimits/read"}

    def __init__(self, command, timeout, *, cwd=None):
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
        except FileNotFoundError as exc:
            if command and command[0] == 'codex' and exc.filename == 'codex':
                raise ProbeError('Codex CLI ไม่พบใน PATH; ตรวจ command -v codex แล้วติดตั้ง/เพิ่ม Codex ใน PATH ก่อนเรียกใหม่') from exc
            raise
        os.set_blocking(self.process.stdout.fileno(), False)
        os.set_blocking(self.process.stderr.fileno(), False)
        self.timeout = timeout
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ, 'stdout')
        self.selector.register(self.process.stderr, selectors.EVENT_READ, 'stderr')
        self.buffer = b''
        self.request_id = 0
        self.stdout_closed = False

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.selector.close()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()

    def send(self, message):
        try:
            self.process.stdin.write((json.dumps(message) + '\n').encode())
            self.process.stdin.flush()
        except BrokenPipeError as exc:
            raise ProbeError('Codex closed the connection; check login and local filesystem permissions.') from exc

    def pop_message(self):
        if b'\n' not in self.buffer:
            return None
        line, self.buffer = self.buffer.split(b'\n', 1)
        try:
            response = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise ProbeError('Codex returned invalid JSON.') from exc
        if not isinstance(response, dict):
            raise ProbeError('Codex returned an invalid protocol message.')
        if 'method' in response:
            if (not isinstance(response['method'], str) or not response['method']
                    or not isinstance(response.get('params', {}), dict)):
                raise ProbeError('Codex returned an invalid event.')
        elif (type(response.get('id')) is not int
              or ('result' in response) == ('error' in response)):
            raise ProbeError('Codex returned an invalid RPC response.')
        return response

    def read_ready(self, stream):
        try:
            chunk = os.read(stream.fileno(), 65536)
        except BlockingIOError:
            # A synchronous RPC may already have consumed a selector's ready bytes.
            return True
        if not chunk:
            try:
                self.selector.unregister(stream)
            except KeyError:
                pass
            if stream is self.process.stdout:
                self.stdout_closed = True
            return False
        if stream is self.process.stdout:
            self.buffer += chunk
            if len(self.buffer) > 4 * 1024 * 1024:
                raise ProbeError('Codex response exceeded the diagnostic size limit.')
        # Drain stderr without retaining possible secrets from Codex logs.
        return True

    def receive(self, deadline):
        while time.monotonic() < deadline:
            response = self.pop_message()
            if response is not None:
                return response
            if self.stdout_closed:
                raise ProbeError('Codex exited; check local filesystem permissions and login.')
            for key, _ in self.selector.select(max(0, deadline - time.monotonic())):
                self.read_ready(key.fileobj)
        raise ProbeError('Codex request timed out.')

    def handle_event(self, message):
        if 'method' in message and 'id' in message:
            raise ProbeError('Unexpected server request; no action was approved.')

    def request(self, method, params=None):
        if method not in self.allowed_methods:
            raise ProbeError('This diagnostic does not permit that request.')
        self.request_id += 1
        request = {'id': self.request_id, 'method': method}
        if params is not None:
            request['params'] = params
        self.send(request)
        deadline = time.monotonic() + self.timeout
        while True:
            response = self.receive(deadline)
            if 'method' in response:
                self.handle_event(response)
                continue
            if response.get('id') != self.request_id:
                raise ProbeError('Unexpected RPC response ID.')
            if 'error' in response:
                # Raw errors can include account details or paths.
                raise ProbeError(f'{method} failed; check Codex login, network and version.')
            if not isinstance(response.get('result'), dict):
                raise ProbeError(f'{method} returned an invalid result.')
            return response['result']


def inspect(connection):
    connection.request('initialize', {'clientInfo': {'name': 'modelmate_doctor', 'version': '0.1.0'}})
    connection.send({'method': 'initialized'})
    account = connection.request('account/read', {'refreshToken': False}).get('account')
    if not isinstance(account, dict) or account.get('type') != 'chatgpt':
        raise ProbeError('ChatGPT login required. Run codex login and choose ChatGPT; API-key auth is not supported.')
    models = read_models(connection)
    quota = connection.request('account/rateLimits/read')
    buckets = quota.get('rateLimitsByLimitId')
    if buckets is None:
        buckets = {'default': quota.get('rateLimits')}
    safe_buckets = {}
    for name, bucket in buckets.items():
        if bucket is None:
            continue
        safe = {k: bucket.get(k) for k in ('limitName', 'planType', 'rateLimitReachedType', 'spendControlReached')}
        for window in ('primary', 'secondary'):
            value = bucket.get(window)
            safe[window] = None if value is None else {
                k: value.get(k) for k in ('usedPercent', 'windowDurationMins', 'resetsAt')}
        credits = bucket.get('credits')
        safe['credits'] = None if credits is None else {
            k: credits.get(k) for k in ('hasCredits', 'unlimited', 'balance')}
        safe_buckets[name] = safe
    return {
        'checkedAt': datetime.now(timezone.utc).isoformat(),
        'account': {'type': 'chatgpt', 'planType': account.get('planType')},
        'models': models,
        'ordinaryUsageAllowed': quota.get('ordinaryUsageAllowed'),
        'quota': safe_buckets,
        'note': 'Diagnostic only: null means unknown. No inference was requested. This is not a spending guarantee.',
    }



def quota_decision(quota, checked_at, *, now=None, expected_account=None):
    """Return a fail-closed decision; checked_at/now use the monotonic clock."""
    now = time.monotonic() if now is None else now
    result = {'state': 'pause', 'reason': 'quota_unknown', 'checked_at': checked_at,
              'account_id': None}
    if (type(checked_at) not in (int, float) or type(now) not in (int, float)
            or not math.isfinite(checked_at) or not math.isfinite(now)
            or not 0 <= now - checked_at <= 15):
        return dict(result, reason='quota_stale')
    if not isinstance(quota, dict):
        return result
    account = quota.get('accountId')
    if not isinstance(account, str) or not account.strip():
        return dict(result, reason='account_unknown')
    result['account_id'] = account
    if expected_account is not None and account != expected_account:
        return dict(result, reason='account_changed')
    allowed = quota.get('ordinaryUsageAllowed')
    if allowed is False:
        return dict(result, reason='quota_exhausted')
    if allowed is not True:
        return result
    buckets = quota.get('rateLimitsByLimitId')
    if buckets is None:
        buckets = {'default': quota.get('rateLimits')}
    if not isinstance(buckets, dict) or not buckets:
        return result
    # No reliable model-to-bucket mapping: require every returned bucket to pass.
    for name, bucket in buckets.items():
        if not isinstance(name, str) or not name or not isinstance(bucket, dict):
            return result
        spend = bucket.get('spendControlReached')
        if spend is not None and type(spend) is not bool:
            return result
        reached = bucket.get('rateLimitReachedType')
        if reached is not None and (not isinstance(reached, str) or not reached):
            return result
        if spend is True or reached is not None:
            return dict(result, reason='quota_exhausted')
        windows = [bucket.get(k) for k in ('primary', 'secondary')]
        if all(window is None for window in windows):
            return result
        for window in windows:
            if window is None:
                continue
            if not isinstance(window, dict):
                return result
            used = window.get('usedPercent')
            if type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 100:
                return result
            if used == 100:
                return dict(result, reason='quota_exhausted')
            for key in ('resetsAt', 'windowDurationMins'):
                value = window.get(key)
                if value is not None and (type(value) is not int or value <= 0):
                    return result
        credits = bucket.get('credits')
        if credits is not None:
            if not isinstance(credits, dict):
                return result
            for key in ('hasCredits', 'unlimited'):
                if type(credits.get(key)) is not bool:
                    return result
            if credits['hasCredits'] or credits['unlimited']:
                return dict(result, reason='extra_credit_access')
    return dict(result, state='allow', reason='included_usage_available')


def refresh_quota(connection, expected_account=None):
    """Read fresh account/quota state for a single controller-started turn."""
    checked_at = time.monotonic()
    try:
        account = connection.request('account/read', {'refreshToken': False}).get('account')
        if not isinstance(account, dict) or account.get('type') != 'chatgpt':
            return {'state': 'pause', 'reason': 'chatgpt_login_required',
                    'checked_at': checked_at, 'account_id': None}
        quota = connection.request('account/rateLimits/read')
    except (ProbeError, OSError, ValueError, TypeError, AttributeError):
        return {'state': 'pause', 'reason': 'quota_unavailable',
                'checked_at': checked_at, 'account_id': None}
    return quota_decision(quota, checked_at, expected_account=expected_account)


def ensure_quota(quota):
    """Compatibility entry point: reject a snapshot without authorizing a turn."""
    checked_at = time.monotonic()
    decision = quota_decision(quota, checked_at)
    if decision['state'] != 'allow':
        raise ProbeError('Quota check paused: ' + decision['reason'] + '; no new turn started.')


def read_models(connection):
    """Read fresh visible catalog entries; do not infer quality or price."""
    models = []
    cursor = None
    seen = set()
    model_ids = set()
    while True:
        params = {'limit': 100}
        if cursor:
            params['cursor'] = cursor
        page = connection.request('model/list', params)
        data = page.get('data')
        if not isinstance(data, list):
            raise ProbeError('Invalid model catalog page.')
        for model in data:
            if (not isinstance(model, dict) or not isinstance(model.get('model'), str)
                    or not model['model'].strip() or type(model.get('hidden', False)) is not bool):
                raise ProbeError('Invalid model catalog entry.')
            if model['model'] in model_ids:
                raise ProbeError('Duplicate model ID in catalog.')
            model_ids.add(model['model'])
            if not model.get('hidden'):
                models.append({k: model.get(k) for k in
                               ('model', 'displayName', 'defaultReasoningEffort', 'supportedReasoningEfforts')})
        cursor = page.get('nextCursor')
        if cursor is None:
            break
        if not isinstance(cursor, str) or not cursor:
            raise ProbeError('Invalid model catalog cursor.')
        if cursor in seen or len(seen) >= 100:
            raise ProbeError('Model catalog pagination did not terminate.')
        seen.add(cursor)
    return models


# No model has completed the live validation/review gate yet; do not guess roles.
MODEL_ROLE_POLICY = {}
ROLE_ORDER = {'economy': 0, 'standard': 1, 'strong': 2}
EFFORT_ORDER = {'none': 0, 'minimal': 1, 'low': 2, 'medium': 3,
                'high': 4, 'xhigh': 5, 'max': 6}


def select_model(catalog, model_id, effort=None):
    """Validate an explicit selection against the current catalog, not saved state."""
    if not isinstance(catalog, list) or not isinstance(model_id, str) or not model_id:
        raise ProbeError('Invalid model selection.')
    matches = [m for m in catalog if isinstance(m, dict) and m.get('model') == model_id]
    if len(matches) != 1 or (type(matches[0].get('hidden', False)) is not bool or matches[0].get('hidden', False)):
        raise ProbeError('Selected model is unavailable; refresh the catalog or choose manually.')
    model = matches[0]
    options = model.get('supportedReasoningEfforts')
    if not isinstance(options, list) or not options:
        raise ProbeError('Supported reasoning efforts are unavailable.')
    efforts = []
    for option in options:
        value = option.get('reasoningEffort') if isinstance(option, dict) else None
        if not isinstance(value, str) or not value or value in efforts:
            raise ProbeError('Invalid reasoning effort catalog.')
        efforts.append(value)
    if effort is None:
        effort = model.get('defaultReasoningEffort')
    if not isinstance(effort, str) or effort not in efforts:
        raise ProbeError('Selected reasoning effort is unsupported.')
    return {'model': model_id, 'effort': effort}


def select_role(catalog, role, role_policy=None, effort=None):
    """Resolve only a trusted reviewed policy or explicit user role binding."""
    policy = MODEL_ROLE_POLICY if role_policy is None else role_policy
    if not isinstance(role, str) or role not in ROLE_ORDER or not isinstance(policy, dict):
        raise ProbeError('Invalid role policy.')
    if any(k not in ROLE_ORDER or not isinstance(v, str) or not v for k, v in policy.items()):
        raise ProbeError('Invalid role binding.')
    model_id = policy.get(role)
    if model_id is None:
        raise ProbeError('Role is unassigned; choose a model explicitly or pause.')
    return select_model(catalog, model_id, effort)


def model_change_requires_approval(previous, proposed, role_policy=None):
    """Conservative comparison for later mode logic; never grants tool access."""
    policy = MODEL_ROLE_POLICY if role_policy is None else role_policy
    if not isinstance(policy, dict) or any(k not in ROLE_ORDER or not isinstance(v, str)
                                           for k, v in policy.items()):
        return True
    for selection in (previous, proposed):
        if (not isinstance(selection, dict) or not isinstance(selection.get('model'), str)
                or not selection['model'] or not isinstance(selection.get('effort'), str)
                or selection['effort'] not in EFFORT_ORDER):
            return True
    if previous['model'] != proposed['model']:
        old_roles = [ROLE_ORDER[k] for k, v in policy.items() if v == previous['model']]
        new_roles = [ROLE_ORDER[k] for k, v in policy.items() if v == proposed['model']]
        if len(old_roles) != 1 or len(new_roles) != 1 or new_roles[0] > old_roles[0]:
            return True
    return EFFORT_ORDER[proposed['effort']] > EFFORT_ORDER[previous['effort']]


PLAN_KEYS = {'version', 'goal', 'clarifications', 'success_criteria', 'steps'}
STEP_KEYS = {'kind', 'objective', 'role', 'effort', 'risk', 'reason', 'checks'}


def _plan_text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ProbeError('Invalid or oversized plan text.')
    return value


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProbeError('Duplicate JSON key in plan.')
        result[key] = value
    return result


def _invalid_plan_constant(_):
    raise ProbeError('Invalid JSON number.')


def validate_plan(raw):
    """Validate untrusted model output without granting authority or running tools."""
    if not isinstance(raw, str):
        raise ProbeError('Plan must be JSON text.')
    try:
        if len(raw.encode('utf-8')) > 65536:
            raise ProbeError('Plan exceeds 64 KiB.')
        plan = json.loads(raw, object_pairs_hook=_unique_json_object,
                          parse_constant=_invalid_plan_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProbeError('Invalid plan JSON.') from exc
    if not isinstance(plan, dict) or set(plan) != PLAN_KEYS or type(plan['version']) is not int or plan['version'] != 1:
        raise ProbeError('Invalid plan schema or version.')
    _plan_text(plan['goal'])
    for field in ('clarifications', 'success_criteria'):
        values = plan[field]
        if not isinstance(values, list) or len(values) > 32:
            raise ProbeError('Invalid plan criteria or questions.')
        for value in values:
            _plan_text(value)
    if not plan['success_criteria']:
        raise ProbeError('Plan requires success criteria.')
    steps = plan['steps']
    if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
        raise ProbeError('Plan requires 1 to 12 steps.')
    for step in steps:
        if not isinstance(step, dict) or set(step) != STEP_KEYS:
            raise ProbeError('Invalid plan step fields.')
        for field in ('objective', 'effort', 'reason', 'kind', 'role', 'risk'):
            _plan_text(step[field])
        if (step['kind'] not in ('plan', 'implement', 'review') or step['role'] not in ROLE_ORDER
                or step['risk'] not in ('normal', 'high')):
            raise ProbeError('Invalid plan step type, role or risk.')
        checks = step['checks']
        if not isinstance(checks, list) or not 1 <= len(checks) <= 32:
            raise ProbeError('Each step requires checks.')
        for check in checks:
            if not isinstance(check, dict) or set(check) != {'kind', 'criterion'}:
                raise ProbeError('Invalid plan check fields.')
            _plan_text(check['kind'])
            _plan_text(check['criterion'])
            if check['kind'] not in ('test', 'lint', 'source', 'rubric', 'manual'):
                raise ProbeError('Invalid check kind.')
    if any(step['risk'] == 'high' for step in steps):
        if not any(step['kind'] == 'review' and step['role'] == 'strong' for step in steps):
            raise ProbeError('High-risk plan requires strong review.')
        last_risky_work = max((i for i, step in enumerate(steps)
                               if step['risk'] == 'high' and step['kind'] != 'review'), default=-1)
        if last_risky_work >= 0 and not any(step['kind'] == 'review' and step['role'] == 'strong'
                                            for step in steps[last_risky_work + 1:]):
            raise ProbeError('Strong review must follow the high-risk work.')
    return plan


def suggest_workflow_models(plan):
    """Recommend an initial role and effort from explicit step risk and checks."""
    plan = copy.deepcopy(plan)
    for step in plan['steps']:
        if step['role'] == 'strong':
            # The author can mark the step where a strong model is needed.
            continue
        if step['risk'] == 'high':
            role, effort = 'standard', 'medium'
            reason = 'ขั้นนี้มีความเสี่ยงสูง จึงเพิ่ม effort และใช้เกณฑ์ตรวจที่ระบุ'
        elif step['kind'] == 'implement' and all(check['kind'] in ('test', 'lint') for check in step['checks']):
            role, effort = 'economy', 'low'
            reason = 'ขั้นลงมือความเสี่ยงปกติมี test/lint ตรวจผลทุกข้อ จึงเริ่มที่ economy/low'
        else:
            role, effort = 'standard', 'low'
            reason = 'ใช้ standard/low สำหรับการวางแผน การทบทวน หรือขั้นที่ต้องประเมินผลเพิ่มเติม'
        if (step['role'], step['effort']) != (role, effort):
            step.update(role=role, effort=effort, reason=reason)
    return plan


def routing_decision(raw, catalog, role_policy=None):
    """Resolve a proposal; ready means ready for approval, never for execution."""
    try:
        plan = validate_plan(raw)
        if plan['clarifications']:
            return {'state': 'clarify', 'plan': plan, 'selections': []}
        selections = [select_role(catalog, step['role'], role_policy, step['effort'])
                      for step in plan['steps']]
    except ProbeError:
        return {'state': 'pause', 'reason': 'invalid_or_unresolvable_plan'}
    return {'state': 'ready_for_approval', 'plan': plan, 'selections': selections}




class ModelApprovals:
    """Task-local model decisions. Only the controller may call answer/manual_select."""

    def __init__(self, catalog, role_policy=None):
        import uuid
        self.task_id = uuid.uuid4().hex
        self.baseline = select_role(catalog, 'standard', role_policy)
        self._grants = set()
        self._declined = set()
        self._pending = None
        self._plan_digest = None

    def _invalidate(self):
        self._grants.clear()
        self._declined.clear()
        self._pending = None
        self._plan_digest = None

    def decision(self, raw, catalog, role_policy=None, *, step_id, step_index=0,
                 mode='ask_to_escalate'):
        import hashlib
        import uuid
        if (mode not in ('auto', 'ask_to_escalate', 'approve_plan')
                or not isinstance(step_id, str) or not step_id.strip()
                or type(step_index) is not int or step_index < 0):
            self._invalidate()
            return {'state': 'pause', 'reason': 'invalid_mode_or_step'}
        route = routing_decision(raw, catalog, role_policy)
        if route['state'] != 'ready_for_approval':
            self._invalidate()
            return route
        if step_index >= len(route['selections']):
            self._invalidate()
            return {'state': 'pause', 'reason': 'invalid_step'}
        try:
            select_model(catalog, self.baseline['model'], self.baseline['effort'])
        except ProbeError:
            self._invalidate()
            return {'state': 'pause', 'reason': 'baseline_unavailable'}
        plan = route['plan']
        selection = route['selections'][step_index]
        # Bind approval to task, complete plan, resolved models and trusted policy.
        payload = {'task_id': self.task_id, 'plan': plan, 'selections': route['selections'],
                   'policy': MODEL_ROLE_POLICY if role_policy is None else role_policy}
        plan_digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True,
                                               separators=(',', ':')).encode()).hexdigest()
        if self._plan_digest != plan_digest:
            self._invalidate()
            self._plan_digest = plan_digest
        step_digest = hashlib.sha256(json.dumps([plan_digest, step_id, step_index],
                                               separators=(',', ':')).encode()).hexdigest()
        scope, digest = ('plan', plan_digest) if mode == 'approve_plan' else ('model', step_digest)
        key = (scope, digest)
        if self._pending is not None and self._pending['key'] != key:
            self._pending = None
        display = {'selection': dict(selection), 'reason': plan['steps'][step_index]['reason'],
                   'step_id': step_id, 'task_id': self.task_id, 'mode': mode}
        if key in self._declined or ('model', step_digest) in self._declined:
            self._pending = None
            return dict(display, state='pause', reason='model_selection_declined',
                        choices=['revise_scope_or_model', 'pause'])
        needs_approval = (mode == 'approve_plan' or
                          (mode == 'ask_to_escalate' and
                           (plan['steps'][step_index]['role'] == 'strong'
                            or model_change_requires_approval(self.baseline, selection, role_policy))))
        if not needs_approval or key in self._grants:
            self._pending = None
            return dict(display, state='allow_model')
        if self._pending is None:
            self._pending = {'token': uuid.uuid4().hex, 'key': key}
        return dict(display, state='ask', scope=scope, token=self._pending['token'],
                    plan=plan if scope == 'plan' else None,
                    selections=route['selections'] if scope == 'plan' else None)

    def answer(self, token, choice):
        """Record an explicit UI choice; never accept model output as a choice."""
        if (self._pending is None or not isinstance(token, str)
                or token != self._pending['token'] or choice not in ('approve', 'decline', 'pause')):
            raise ProbeError('Invalid or stale model approval response.')
        key = self._pending['key']
        self._pending = None
        if choice == 'approve':
            self._grants.add(key)
        else:
            self._declined.add(key)
        return {'state': 'recorded' if choice == 'approve' else 'pause', 'scope': key[0]}

    def manual_select(self, raw, catalog, role_policy=None, *, step_id, step_index=0):
        """An explicit human selection approves only this step's resolved model."""
        result = self.decision(raw, catalog, role_policy, step_id=step_id,
                               step_index=step_index, mode='ask_to_escalate')
        if result['state'] == 'ask':
            self.answer(result['token'], 'approve')
            return self.decision(raw, catalog, role_policy, step_id=step_id,
                                 step_index=step_index, mode='ask_to_escalate')
        return result


def workflow_check_result(kind, origin, result, exit_code, reference, finding):
    """Shared validation for newly observed evidence and its persisted representation."""
    if origin not in ('tool', 'manual', 'source', 'model_review') or result not in ('pass', 'fail', 'unknown'):
        raise ProbeError('Invalid evidence provenance or result.')
    _plan_text(reference)
    _plan_text(finding)
    if exit_code is not None and (type(exit_code) is not int or origin != 'tool'):
        raise ProbeError('Exit codes must be observed integers from tools.')
    if kind in ('test', 'lint') and origin == 'tool' and exit_code is not None:
        return 'pass' if exit_code == 0 else 'fail'
    if kind in ('rubric', 'manual') and origin == 'manual':
        return result
    if kind == 'source' and origin == 'source':
        from urllib.parse import urlsplit
        try:
            url = urlsplit(reference)
        except ValueError:
            raise ProbeError('Invalid source evidence URL.') from None
        if url.scheme not in ('https', 'http') or not url.netloc or url.username or url.password:
            raise ProbeError('Source evidence requires an HTTP(S) URL and a verified claim finding.')
        return result
    return 'unknown'


def _workflow_id(value):
    import re
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{32}', value) is None:
        raise ProbeError('Invalid workflow ID.')
    return value


def _workflow_timestamp(value):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError('timezone required')
    except (ValueError, TypeError, AttributeError):
        raise ProbeError('Invalid workflow evidence timestamp.') from None


def _workflow_selection(value):
    if not isinstance(value, dict) or set(value) != {'model', 'effort'}:
        raise ProbeError('Invalid workflow model selection.')
    _plan_text(value['model'])
    _plan_text(value['effort'])


def recheck_spec_digest(command, cwd):
    import hashlib
    _plan_text(command)
    _plan_text(cwd)
    if not os.path.isabs(cwd):
        raise ProbeError('Recheck cwd must be absolute.')
    return hashlib.sha256(json.dumps({'command': command, 'cwd': cwd}, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


class WorkflowController:
    """Offline state only. Methods accept trusted host/UI events, never model claims as authority."""

    def __init__(self, raw, catalog, role_policy=None, mode='ask_to_escalate'):
        import uuid
        if mode not in ('auto', 'ask_to_escalate', 'approve_plan'):
            raise ProbeError('Invalid workflow mode.')
        self._plan = validate_plan(raw)
        self._raw = raw
        self._approvals = ModelApprovals(catalog, role_policy)
        self.task_id = self._approvals.task_id
        self.mode = mode
        self.state = 'CLARIFYING' if self._plan['clarifications'] else 'READY'
        self.reason = None
        self._steps = [{'id': uuid.uuid4().hex, 'cycle': 0, 'attempts': 0,
                        'state': 'READY', 'evidence': []} for _ in self._plan['steps']]
        self._index = 0
        self._active = None
        self._history = []
        self._pause_token = None
        self._model_request = None
        self._account_id = None
        self._coverage = {}
        self._stale_evidence = set()
        self._accepted_at = None
        self._rechecks = []
        self._current_rechecks = set()
        self._recheck_fault = False
        self._persist = None

    def _updated(self):
        if self._recheck_fault:
            raise ProbeError('Recheck persistence outcome unknown; reopen the checkpoint before further work.')
        if self._persist is not None:
            self._persist(self)
        return self.snapshot()

    def export_checkpoint(self):
        import hashlib
        history = copy.deepcopy(self._history)
        active = copy.deepcopy(self._active)
        for attempt in history + ([active] if active is not None else []):
            if 'checks' in attempt:
                attempt['checks'] = sorted(attempt['checks'].values(), key=lambda e: e['check_index'])
        steps = copy.deepcopy(self._steps)
        for step in steps:
            step['evidence'].sort(key=lambda e: e['check_index'])
        data = {'version': 1, 'plan': self._raw, 'task_id': self.task_id, 'mode': self.mode,
            'baseline': copy.deepcopy(self._approvals.baseline), 'state': self.state, 'reason': self.reason,
            'step_index': self._index, 'steps': steps, 'active_attempt': active, 'history': history,
            'criterion_evidence': {str(i): ids for i, ids in self._coverage.items()},
            'account_hash': None if self._account_id is None else hashlib.sha256(self._account_id.encode()).hexdigest()}
        if self._rechecks:
            data.update(version=2, rechecks=copy.deepcopy(self._rechecks))
        return validate_workflow_checkpoint(data)

    @classmethod
    def restore_checkpoint(cls, data, quota, checked_at, catalog, role_policy=None):
        import hashlib
        data = validate_workflow_checkpoint(data)
        decision = quota_decision(quota, checked_at)
        if decision['state'] != 'allow':
            raise ProbeError('Workflow restore paused: ' + decision['reason'])
        fingerprint = hashlib.sha256(decision['account_id'].encode()).hexdigest()
        if data['account_hash'] is not None and data['account_hash'] != fingerprint:
            raise ProbeError('Workflow account mismatch.')
        baseline = select_model(catalog, data['baseline']['model'], data['baseline']['effort'])
        restored = cls(data['plan'], catalog, role_policy, data['mode'])
        restored.task_id = restored._approvals.task_id = data['task_id']
        restored._approvals.baseline = baseline
        restored._account_id = decision['account_id']
        restored._index, restored._steps = data['step_index'], data['steps']
        restored._active, restored._history = data['active_attempt'], data['history']
        restored._rechecks = data.get('rechecks', [])
        for attempt in restored._history + ([restored._active] if restored._active is not None else []):
            if 'checks' in attempt:
                attempt['checks'] = {e['check_index']: e for e in attempt['checks']}
        restored._coverage = {int(i): ids for i, ids in data['criterion_evidence'].items()}
        restored._stale_evidence = {e['id'] for step in restored._steps for e in step['evidence']}
        if restored._active is not None:
            restored._stale_evidence.update(e['id'] for e in restored._active['checks'].values())
        if data['state'] == 'CLARIFYING':
            restored.state = 'CLARIFYING'
        elif data['state'] in ('DONE', 'FAILED'):
            restored.state = 'UNVERIFIED' if data['state'] == 'DONE' else 'FAILED'
            restored.reason = 'restored_result_unverified' if data['state'] == 'DONE' else data['reason']
        else:
            step = restored._steps[restored._index] if restored._index < len(restored._steps) else None
            running = restored._active is not None and restored._active['status'] == 'running'
            limit = restored._active is None and step is not None and step['attempts'] >= 3
            restored._pause('outcome_unknown' if running else 'correction_limit' if limit else 'user_pause')
        return restored

    def snapshot(self):
        return copy.deepcopy({'task_id': self.task_id, 'state': self.state, 'reason': self.reason,
            'mode': self.mode, 'step_index': self._index, 'steps': self._steps,
            'active_attempt': self._active, 'history': self._history,
            'model_request': self._model_request, 'pause_token': self._pause_token,
            'choices': ['continue', 'revise_scope', 'pause'] if self.state == 'PAUSED' else [],
            'plan': self._plan,
            'clarifications': self._plan['clarifications'],
            'success_criteria': self._plan['success_criteria'], 'criterion_evidence': self._coverage,
            'stale_evidence': sorted(self._stale_evidence)})

    def recheck_operations(self):
        data = self.export_checkpoint()
        return validate_recheck_ledger(self._rechecks, workflow_saved_evidence(data))

    def _append_recheck(self, event):
        if self._recheck_fault or self._persist is None:
            raise ProbeError('Rechecks require a healthy durable workflow attachment.')
        candidate = self.export_checkpoint()
        candidate.update(version=2, rechecks=self._rechecks + [dict(event,
            timestamp=datetime.now(timezone.utc).isoformat())])
        validate_workflow_checkpoint(candidate)
        self._rechecks = candidate['rechecks']
        try:
            return self._updated()
        except BaseException:
            self._recheck_fault = True
            raise

    def reserve_recheck(self, evidence_id, command, cwd, selection, quota, checked_at, catalog, role_policy=None):
        """Reserve durable state only; the native adapter must separately obtain execution consent."""
        import uuid
        state = self.snapshot()
        current = [e for step in self._steps for e in step['evidence']]
        if self._active is not None:
            current.extend(self._active['checks'].values())
        saved = next((e for e in current if e['id'] == evidence_id), None)
        if (self._recheck_fault or saved is None or evidence_id not in self._stale_evidence
                or saved['kind'] not in ('test', 'lint') or saved['origin'] != 'tool'
                or saved['result'] not in ('pass', 'fail')
                or (state['active_attempt'] is not None and state['active_attempt']['status'] == 'running')):
            raise ProbeError('Only stale known tool evidence with no running work can reserve a recheck.')
        decision = quota_decision(quota, checked_at, expected_account=self._account_id)
        if decision['state'] != 'allow':
            raise ProbeError('Recheck preflight paused: ' + decision['reason'])
        if selection != select_role(catalog, 'standard', role_policy, 'low'):
            raise ProbeError('Rechecks require the explicitly bound standard model at low effort.')
        digest = recheck_spec_digest(command, cwd)
        operations = self.recheck_operations()
        if any(op['status'] in ('pending', 'unknown') for op in operations):
            raise ProbeError('Previous recheck outcome is unresolved; nothing replayed.')
        cycle = sum(e['kind'] == 'choice' and e['evidence_id'] == evidence_id and e['choice'] == 'continue'
                    for e in self._rechecks)
        number = 1 + sum(op['evidence_id'] == evidence_id and op['cycle'] == cycle for op in operations)
        if number > 3:
            raise ProbeError('Recheck correction limit: choose continue, revise_scope or pause explicitly.')
        identity = uuid.uuid4().hex
        self._append_recheck({'kind': 'reserve', 'id': identity, 'evidence_id': evidence_id,
            'spec_digest': digest, 'selection': copy.deepcopy(selection), 'cycle': cycle, 'number': number})
        self._current_rechecks.add(identity)
        return next(op for op in self.recheck_operations() if op['id'] == identity)

    def advance_recheck(self, operation_id, kind, **values):
        """Trusted native adapter supplies bindings/results; model text is never an event source."""
        if kind not in ('thread', 'turn_reserved', 'turn', 'finish', 'reconcile'):
            raise ProbeError('Unsupported recheck event.')
        previous = next((op for op in self.recheck_operations() if op['id'] == operation_id), None)
        if previous is not None and (kind == 'reconcile' or (kind == 'finish' and values.get('status') == 'unknown')):
            self._stale_evidence.add(previous['evidence_id'])
            if self.state == 'DONE':
                self.state, self.reason = 'UNVERIFIED', 'recheck_observation_conflict'
        self._append_recheck(dict(values, kind=kind, id=operation_id))
        operation = next(op for op in self.recheck_operations() if op['id'] == operation_id)
        if (kind == 'finish' and operation_id in self._current_rechecks
                and previous is not None and previous['status'] == 'pending'
                and operation['status'] == 'completed' and operation['exit_code'] is not None):
            try:
                self.revalidate_check(operation['evidence_id'], origin='tool', exit_code=operation['exit_code'],
                    reference='Native recheck operation ' + operation_id,
                    finding='Fresh bound command completion; no stdout/stderr retained.')
            except ProbeError:
                pass  # A mismatch or already-current result never converts saved evidence to pass.
        return copy.deepcopy(operation)

    def answer_recheck_limit(self, evidence_id, choice):
        if choice not in ('continue', 'revise_scope', 'pause'):
            raise ProbeError('Invalid recheck budget choice.')
        return self._append_recheck({'kind': 'choice', 'evidence_id': evidence_id, 'choice': choice})

    def _pause(self, reason):
        import uuid
        self.state, self.reason = 'PAUSED', reason
        self._pause_token = uuid.uuid4().hex
        self._model_request = None
        self._approvals._invalidate()
        return self._updated()

    def request_attempt(self, quota, checked_at, catalog, role_policy=None):
        """Consume a slot before dispatch. Returned data does not grant any tool permission."""
        if self._recheck_fault or any(op['status'] in ('pending', 'unknown') for op in self.recheck_operations()):
            raise ProbeError('Resolve the durable recheck outcome before starting work.')
        import uuid
        if self.state not in ('READY', 'AWAITING_MODEL_APPROVAL'):
            return self._updated()
        decision = quota_decision(quota, checked_at, expected_account=self._account_id)
        if decision['state'] != 'allow':
            return self._pause(decision['reason'])
        self._account_id = decision['account_id']
        step = self._steps[self._index]
        if step['attempts'] >= 3:
            return self._pause('correction_limit')
        gate = self._approvals.decision(self._raw, catalog, role_policy, step_id=step['id'],
                                        step_index=self._index, mode=self.mode)
        if gate['state'] == 'ask':
            self.state = 'AWAITING_MODEL_APPROVAL'
            self._model_request = gate
            return self._updated()
        if gate['state'] != 'allow_model':
            return self._pause(gate.get('reason', 'model_unavailable'))
        step['attempts'] += 1
        step['state'] = self.state = 'RUNNING'
        self.reason = None
        self._model_request = None
        self._active = {'id': uuid.uuid4().hex, 'step_id': step['id'], 'cycle': step['cycle'],
            'number': step['attempts'], 'selection': gate['selection'], 'status': 'running', 'checks': {}}
        return dict(self._updated(), dispatch=copy.deepcopy({
            'attempt_id': self._active['id'], 'step_id': step['id'], 'selection': gate['selection'],
            'step': self._plan['steps'][self._index], 'execution': 'not_dispatched', 'tool_permissions': 'none'}))

    def answer_model(self, token, choice):
        if self.state != 'AWAITING_MODEL_APPROVAL' or self._model_request is None:
            raise ProbeError('No current model approval request.')
        self._approvals.answer(token, choice)
        self._model_request = None
        if choice == 'approve':
            self.state = 'READY'
            return self._updated()
        return self._pause('model_selection_declined')

    def change_mode(self, mode):
        if mode not in ('auto', 'ask_to_escalate', 'approve_plan'):
            raise ProbeError('Invalid workflow mode.')
        if self._active is not None or self.state in ('DONE', 'FAILED'):
            raise ProbeError('Cannot change mode during an active or finished attempt.')
        self.mode = mode
        self._approvals._invalidate()
        self._model_request = None
        if self.state == 'AWAITING_MODEL_APPROVAL':
            self.state = 'READY'
        if self.state == 'PAUSED':
            return self._pause(self.reason)
        return self._updated()

    def revise_step(self, raw):
        """Rename or change selection without replacing identity, criteria or budget."""
        if self._active is not None or self._index >= len(self._steps) or self.state in ('DONE', 'FAILED'):
            raise ProbeError('Cannot revise an active or finished step.')
        candidate = validate_plan(raw)
        if len(candidate['steps']) != len(self._plan['steps']):
            raise ProbeError('Revision cannot replace step structure; budget is preserved.')
        expected = copy.deepcopy(self._plan)
        for key in ('objective', 'role', 'effort', 'reason'):
            expected['steps'][self._index][key] = candidate['steps'][self._index][key]
        if candidate != expected:
            raise ProbeError('Revision cannot replace task criteria or step structure; budget is preserved.')
        self._plan, self._raw = candidate, raw
        self._approvals._invalidate()
        self._model_request = None
        if self.state == 'AWAITING_MODEL_APPROVAL':
            self.state = 'READY'
        if self.state == 'PAUSED':
            return self._pause(self.reason)
        return self._updated()

    def _attempt(self, attempt_id):
        if self._active is None or not isinstance(attempt_id, str) or attempt_id != self._active['id']:
            raise ProbeError('Invalid or stale workflow attempt.')
        return self._active

    def finish_attempt(self, attempt_id, status, *, tool_observations=None):
        attempt = self._attempt(attempt_id)
        if attempt['status'] != 'running' or status not in ('completed', 'failed', 'interrupted'):
            raise ProbeError('Invalid attempt terminal event.')
        if tool_observations:
            if status != 'completed':
                raise ProbeError('Tool evidence requires a completed turn.')
            evidence = {index: self._check_evidence(attempt, index, origin='tool',
                result='unknown', exit_code=observed['exit_code'],
                reference='executor command item ' + observed['item_id'],
                finding='Observed host-bound native command completion; no stdout/stderr retained.')
                for index, observed in tool_observations.items()}
            attempt['checks'].update(evidence)
        attempt['status'] = status
        if status == 'completed':
            self.state, self.reason = 'CHECKING', None
            self._pause_token = None
        else:
            self._history.append(copy.deepcopy(attempt))
            self._active = None
            self._steps[self._index]['state'] = 'PAUSED' if status == 'interrupted' else 'FAILED'
            if status == 'interrupted':
                return self._pause('outcome_unknown')
            self.state, self.reason = 'FAILED', 'execution_failed'
        return self._updated()

    def _check_evidence(self, attempt, check_index, *, origin, result, exit_code, reference, finding):
        import uuid
        checks = self._plan['steps'][self._index]['checks']
        if (type(check_index) is not int or not 0 <= check_index < len(checks)
                or check_index in attempt['checks']):
            raise ProbeError('Invalid, duplicate or out-of-phase check.')
        kind = checks[check_index]['kind']
        verified = workflow_check_result(kind, origin, result, exit_code, reference, finding)
        return {'id': uuid.uuid4().hex, 'step_id': attempt['step_id'], 'attempt_id': attempt['id'],
                'check_index': check_index, 'kind': kind, 'origin': origin, 'result': verified,
                'exit_code': exit_code, 'reference': reference, 'finding': finding,
                'timestamp': datetime.now(timezone.utc).isoformat()}

    def record_check(self, attempt_id, check_index, *, origin, result='unknown', exit_code=None,
                     reference, finding):
        """Host adapters supply observed exit codes or verified findings, not parsed model assertions."""
        attempt = self._attempt(attempt_id)
        if self.state != 'CHECKING' or attempt['status'] != 'completed':
            raise ProbeError('Invalid, duplicate or out-of-phase check.')
        evidence = self._check_evidence(attempt, check_index, origin=origin, result=result,
            exit_code=exit_code, reference=reference, finding=finding)
        attempt['checks'][check_index] = evidence
        self._updated()
        return copy.deepcopy(evidence)

    def revalidate_check(self, evidence_id, *, origin, result='unknown', exit_code=None, reference, finding):
        """Trusted host explicitly rechecks saved evidence; confirmation never survives another restore."""
        evidence = [e for step in self._steps for e in step['evidence']]
        if self._active is not None:
            evidence.extend(self._active['checks'].values())
        saved = next((e for e in evidence if e['id'] == evidence_id), None)
        if saved is None or evidence_id not in self._stale_evidence:
            raise ProbeError('No stale workflow evidence with this identity.')
        observed = workflow_check_result(saved['kind'], origin, result, exit_code, reference, finding)
        if origin != saved['origin'] or observed == 'unknown' or observed != saved['result']:
            raise ProbeError('Revalidation disagrees with saved evidence; keep outcome unverified.')
        self._stale_evidence.remove(evidence_id)
        return self.snapshot()

    def evaluate_attempt(self, attempt_id):
        attempt = self._attempt(attempt_id)
        if self.state != 'CHECKING' or attempt['status'] != 'completed':
            raise ProbeError('Attempt is not ready for evaluation.')
        if any(e['id'] in self._stale_evidence for e in attempt['checks'].values()):
            raise ProbeError('Saved checks require explicit host revalidation before evaluation.')
        step = self._steps[self._index]
        expected = len(self._plan['steps'][self._index]['checks'])
        results = [e['result'] for e in attempt['checks'].values()]
        self._history.append(copy.deepcopy(attempt))
        self._active = None
        if 'fail' in results:
            step['state'] = 'READY'
            if step['attempts'] >= 3:
                return self._pause('correction_limit')
            self.state, self.reason = 'READY', 'checks_failed'
        elif len(results) != expected or 'unknown' in results:
            step['state'] = self.state = 'UNVERIFIED'
            self.reason = 'checks_unavailable'
        else:
            step['state'] = 'DONE'
            step['evidence'] = list(attempt['checks'].values())
            self._index += 1
            self.state = 'READY' if self._index < len(self._steps) else 'CHECKING'
            self.reason = None if self.state == 'READY' else 'task_criteria_pending'
        return self._updated()

    def finish_task(self, coverage):
        """Trusted checker maps each success criterion to accepted, current evidence IDs."""
        if self._recheck_fault or any(op['status'] in ('pending', 'unknown') for op in self.recheck_operations()):
            raise ProbeError('Unresolved durable recheck prevents task completion.')
        if self._index != len(self._steps) or self.state not in ('CHECKING', 'UNVERIFIED') or self._active is not None:
            raise ProbeError('Task steps are not fully checked.')
        if not isinstance(coverage, dict) or any(type(i) is not int or not 0 <= i < len(
                self._plan['success_criteria']) for i in coverage):
            raise ProbeError('Invalid success-criterion coverage.')
        if any(e['id'] in self._stale_evidence for step in self._steps for e in step['evidence']):
            raise ProbeError('Saved checks require explicit host revalidation before task completion.')
        accepted = {e['id'] for step in self._steps for e in step['evidence'] if e['result'] == 'pass'}
        for ids in coverage.values():
            if (not isinstance(ids, list) or not ids or len(ids) > 384
                    or any(not isinstance(eid, str) or eid not in accepted for eid in ids)):
                raise ProbeError('Criterion references missing or stale evidence.')
        if set(coverage) != set(range(len(self._plan['success_criteria']))):
            self.state, self.reason = 'UNVERIFIED', 'task_criteria_unverified'
        else:
            self.state, self.reason = 'DONE', None
        self._coverage = copy.deepcopy(coverage)
        updated = self._updated()
        if self.state == 'DONE':
            self._accepted_at = time.monotonic()
        return updated

    def pause(self, reason='user_pause'):
        if reason not in ('user_pause', 'quota_unknown', 'quota_exhausted', 'quota_stale', 'account_unknown',
                          'account_changed', 'chatgpt_login_required', 'extra_credit_access', 'catalog_unavailable',
                          'connection_lost', 'unsupported_capability'):
            raise ProbeError('Invalid pause reason.')
        if self.state in ('DONE', 'FAILED', 'CLARIFYING'):
            raise ProbeError('Cannot pause a terminal or unclarified task.')
        return self._pause(reason)

    def observe_quota(self, quota, checked_at):
        decision = quota_decision(quota, checked_at, expected_account=self._account_id)
        if decision['state'] != 'allow' and self.state not in ('DONE', 'FAILED', 'CLARIFYING'):
            return self._pause(decision['reason'])
        return self._updated()

    def answer_pause(self, token, choice):
        if (self.state != 'PAUSED' or not isinstance(token, str) or token != self._pause_token
                or choice not in ('continue', 'revise_scope', 'pause')):
            raise ProbeError('Invalid or stale workflow pause choice.')
        if self._active is not None and self._active['status'] == 'running':
            raise ProbeError('Turn outcome still unknown; reconcile a terminal event before continuing.')
        step = self._steps[self._index] if self._index < len(self._steps) else None
        self._history.append({'kind': 'user_choice', 'choice': choice, 'reason': self.reason,
                              'step_id': step['id'] if step is not None else None,
                              'timestamp': datetime.now(timezone.utc).isoformat()})
        if choice != 'continue':
            return self._pause(self.reason if choice == 'pause' else 'revise_scope')
        if self.reason == 'correction_limit' and step is not None:
            self._history.append({'kind': 'budget_extension', 'step_id': step['id'], 'cycle': step['cycle'],
                                  'attempts': step['attempts'], 'timestamp': datetime.now(timezone.utc).isoformat()})
            step['cycle'] += 1
            step['attempts'] = 0
        self._pause_token = None
        self.state = 'CHECKING' if self._active is not None or step is None else 'READY'
        self.reason = None
        return self._updated()


def observed_command_matches(observed, expected):
    """Accept literal commands or one explicit shell argv wrapper, never rewrite shell code."""
    if observed == expected:
        return True
    if not isinstance(observed, str):
        return False
    import shlex
    try:
        argv = shlex.split(observed)
    except ValueError:
        return False
    return (len(argv) == 3 and argv[0] in ('/bin/bash', '/usr/bin/bash', '/bin/sh', '/usr/bin/sh')
            and argv[1] in ('-c', '-lc') and argv[2] == expected)


class WorkflowHost:
    """Trusted executor adapter. No built-in native transport, tool approval or process runner."""

    def __init__(self, controller, preflight, dispatch, interrupt, timeout=120):
        if not isinstance(controller, WorkflowController) or not all(callable(fn) for fn in (preflight, dispatch, interrupt)):
            raise ProbeError('Workflow host requires a controller and trusted transport callbacks.')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ProbeError('Workflow host timeout must be finite and positive.')
        self.controller = controller
        self.preflight, self.dispatch, self.interrupt = preflight, dispatch, interrupt
        self.timeout = timeout
        self.on_change = None
        self.catalog, self.role_policy = [], None
        self._binding = None
        self._seen = set()
        self._specs, self._items, self._observations = {}, {}, {}
        self._command_diagnostics = dict.fromkeys(('started', 'completed', 'command_mismatches', 'cwd_mismatches'), 0)
        self._terminal = None
        self._deadline = None
        self._starting = self._interrupted = False
        self._connected = True

    def _signal(self):
        if self.on_change is not None:
            self.on_change({'type': 'workflow_changed', 'task_id': self.controller.task_id})

    def _fresh(self):
        data = self.preflight()
        if not isinstance(data, dict) or set(data) != {'quota', 'checked_at', 'catalog', 'role_policy'}:
            raise ProbeError('Invalid workflow preflight snapshot.')
        self.catalog, self.role_policy = copy.deepcopy(data['catalog']), copy.deepcopy(data['role_policy'])
        return data

    @staticmethod
    def _checked_binding(binding):
        if not isinstance(binding, dict) or set(binding) != {'thread_id', 'turn_id'}:
            raise ProbeError('Missing executor thread/turn binding; outcome unknown.')
        for value in binding.values():
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ProbeError('Invalid executor identity; outcome unknown.')
        return copy.deepcopy(binding)

    def configure_check(self, check_index, *, command, cwd, step_index=None):
        """Register a host-approved check specification; this never authorizes or executes it."""
        state = self.controller.snapshot()
        if ((state['active_attempt'] is not None and state['active_attempt']['status'] != 'completed')
                or state['step_index'] >= len(state['steps'])):
            raise ProbeError('Configure checks before an attempt.')
        target = state['step_index'] if step_index is None else step_index
        if type(target) is not int or not state['step_index'] <= target < len(state['steps']):
            raise ProbeError('Check must belong to the current or a future step.')
        checks = state['plan']['steps'][target]['checks']
        if (type(check_index) is not int or not 0 <= check_index < len(checks)
                or checks[check_index]['kind'] not in ('test', 'lint')):
            raise ProbeError('Only declared test/lint checks can bind command observations.')
        _plan_text(command)
        _plan_text(cwd)
        if not os.path.isabs(cwd):
            raise ProbeError('Check working directory must be absolute.')
        key = (state['steps'][target]['id'], check_index)
        self._specs[key] = {'command': command, 'cwd': cwd}

    def _request_interrupt(self):
        if self._binding is not None and self._terminal is None and not self._interrupted:
            self._interrupted = True
            self.interrupt(copy.deepcopy(self._binding))

    def _halt(self, reason):
        if reason != 'user_pause':
            self._observations = {}
        try:
            self._request_interrupt()
        finally:
            if self.controller.state not in ('DONE', 'FAILED', 'CLARIFYING'):
                self.controller.pause(reason)
            self._signal()

    def __call__(self, action):
        if (not isinstance(action, dict) or set(action) != {'action', 'task_id'}
                or action['task_id'] != self.controller.task_id):
            raise ProbeError('Invalid or foreign workflow host action.')
        if action['action'] == 'cancel':
            self._halt('user_pause')
            return
        if action['action'] == 'check':
            self.finish_checks()
            return
        if action['action'] != 'next':
            raise ProbeError('Unsupported workflow host action.')
        if not self._connected or self._binding is not None or self._starting:
            raise ProbeError('Executor is disconnected or previous attempt is not reconciled.')
        if self.controller.state != 'READY':
            raise ProbeError('Workflow is not READY; no dispatch attempted.')
        try:
            data = self._fresh()
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            reason = exc.reason if isinstance(exc, WorkflowPreflightPause) else 'quota_unknown'
            self.controller.pause(reason)
            self._signal()
            raise
        state = self.controller.snapshot()
        if state['plan']['steps'][state['step_index']]['effort'] == 'ultra':
            self.controller.pause('unsupported_capability')
            self._signal()
            return
        result = self.controller.request_attempt(data['quota'], data['checked_at'], data['catalog'], data['role_policy'])
        descriptor = result.get('dispatch')
        if descriptor is None:
            self._signal()
            return
        self._items, self._observations = {}, {}
        self._command_diagnostics = dict.fromkeys(('started', 'completed', 'command_mismatches', 'cwd_mismatches'), 0)
        self._terminal, self._deadline = None, None
        self._interrupted = False
        self._starting = True
        try:
            binding = self._checked_binding(self.dispatch(copy.deepcopy(descriptor)))
            identity = (binding['thread_id'], binding['turn_id'])
            if identity in self._seen:
                raise ProbeError('Executor reused an old turn identity; outcome unknown.')
            self._binding = dict(binding, attempt_id=descriptor['attempt_id'])
            self._seen.add(identity)
            self._items, self._observations = {}, {}
            self._terminal = None
            self._interrupted = False
            self._deadline = time.monotonic() + self.timeout
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError):
            self.controller.pause('connection_lost')
            self._signal()
            raise
        finally:
            self._starting = False
        self._signal()

    def reconcile(self, binding, status):
        """Trusted recovery adapter supplies inspected native identity and terminal status; never model text."""
        if self._binding is not None or self._starting:
            raise ProbeError('Cannot replace an already bound executor turn.')
        active = self.controller.snapshot()['active_attempt']
        if (active is None or active['status'] not in ('running', 'completed')
                or status not in ('completed', 'failed', 'interrupted')):
            raise ProbeError('No active attempt to reconcile.')
        if active['status'] == 'completed' and status != 'completed':
            raise ProbeError('Inspected terminal status conflicts with the cached completed attempt.')
        data = self._fresh()
        decision = quota_decision(data['quota'], data['checked_at'], expected_account=self.controller._account_id)
        if decision['state'] != 'allow':
            raise ProbeError('Recovery preflight paused: ' + decision['reason'])
        binding = self._checked_binding(binding)
        self._binding = dict(binding, attempt_id=active['id'])
        self._seen.add((binding['thread_id'], binding['turn_id']))
        self._items, self._observations = {}, {}
        self._command_diagnostics = dict.fromkeys(('started', 'completed', 'command_mismatches', 'cwd_mismatches'), 0)
        self._terminal = status
        if active['status'] == 'running':
            self.controller.finish_attempt(active['id'], status)
        if status != 'completed':
            self._binding = None
        self._signal()

    def observe_native(self, message):
        """Consume protocol observations from the trusted executor channel, not assistant JSON."""
        if self._starting:
            raise ProbeError('Queue executor events until dispatch returns its binding.')
        if (not isinstance(message, dict) or not isinstance(message.get('params'), dict)
                or not isinstance(message.get('method'), str) or not message['method']):
            raise ProbeError('Invalid executor observation.')
        if 'id' in message:
            self._halt('unsupported_capability')
            raise ProbeError('Workflow tool approvals are not enabled; nothing approved.')
        if self._binding is None:
            return False
        params = message['params']
        method = message.get('method')
        turn = params.get('turn', {})
        turn_id = turn.get('id') if method == 'turn/completed' and isinstance(turn, dict) else params.get('turnId')
        if params.get('threadId') != self._binding['thread_id'] or turn_id != self._binding['turn_id']:
            return False
        try:
            if method == 'turn/completed':
                status = turn.get('status')
                if status not in ('completed', 'failed', 'interrupted'):
                    raise ProbeError('Invalid executor terminal status.')
                if self._terminal is not None:
                    if self._terminal != status:
                        raise ProbeError('Conflicting executor terminal events.')
                    return False
                self._terminal = status
                self.controller.finish_attempt(self._binding['attempt_id'], status,
                    tool_observations=self._observations if status == 'completed' else None)
                self._deadline = None
                if status != 'completed':
                    self._binding = None
                self._signal()
                return True
            if method not in ('item/started', 'item/completed'):
                return False
            item = params.get('item')
            if not isinstance(item, dict):
                return False
            if item.get('type') != 'commandExecution':
                if item.get('id') in self._items.values():
                    raise ProbeError('Bound command item changed type.')
                return False
            if self._terminal is not None:
                raise ProbeError('Tool observation arrived after its terminal event.')
            state = self.controller.snapshot()
            active = state['active_attempt']
            if active is None or active['id'] != self._binding['attempt_id']:
                raise ProbeError('Executor/controller attempt identity mismatch.')
            specs = {index: spec for (sid, index), spec in self._specs.items() if sid == active['step_id']}
            matches_command = {index for index, spec in specs.items()
                               if observed_command_matches(item.get('command'), spec['command'])}
            matches_cwd = {index for index, spec in specs.items() if item.get('cwd') == spec['cwd']}
            self._command_diagnostics['started' if method == 'item/started' else 'completed'] += 1
            if specs and not matches_command:
                self._command_diagnostics['command_mismatches'] += 1
            if specs and not matches_cwd:
                self._command_diagnostics['cwd_mismatches'] += 1
            matching = sorted(matches_command & matches_cwd)
            known = {index for index, identity in self._items.items() if identity == item.get('id')}
            if known and known != set(matching):
                raise ProbeError('Observed command/cwd changed for a bound check item.')
            if not matching:
                return False
            item_id = item.get('id')
            if not isinstance(item_id, str) or not item_id or len(item_id) > 256:
                raise ProbeError('Invalid command item identity.')
            for index in matching:
                if method == 'item/started':
                    if index in self._items and self._items[index] != item_id:
                        raise ProbeError('Check was repeated within one attempt; use the correction controller.')
                    self._items[index] = item_id
                else:
                    if self._items.get(index) != item_id:
                        raise ProbeError('Check completion has no matching observed start.')
                    status, code = item.get('status'), item.get('exitCode')
                    if status not in ('completed', 'failed', 'declined') or (code is not None and type(code) is not int):
                        raise ProbeError('Invalid command completion evidence.')
                    observed = {'item_id': item_id, 'exit_code': code if status == 'completed' or (status == 'failed' and code != 0) else None}
                    if index in self._observations and self._observations[index] != observed:
                        raise ProbeError('Conflicting check completion observations.')
                    self._observations[index] = observed
            return True
        except (ProbeError, ValueError, TypeError, KeyError, AttributeError):
            self._halt('connection_lost')
            raise

    def finish_checks(self):
        state = self.controller.snapshot()
        active = state['active_attempt']
        if (self._binding is None or self._terminal != 'completed' or state['state'] != 'CHECKING'
                or active is None or active['id'] != self._binding['attempt_id']):
            raise ProbeError('No confirmed completed attempt ready for checks.')
        checks = state['plan']['steps'][state['step_index']]['checks']
        missing = [i + 1 for i, check in enumerate(checks)
                   if check['kind'] in ('test', 'lint') and i not in active['checks']]
        for number in missing:
            self.controller.record_check(active['id'], number - 1, origin='tool', exit_code=None,
                reference='No matching native command completion',
                finding=json.dumps(self._command_diagnostics))
        if missing and self.on_change is not None:
            self.on_change({'type': 'progress', 'text': 'ยังไม่มี command evidence สำหรับ checks '
                + ', '.join(map(str, missing)) + ' · diagnostics '
                + json.dumps(self._command_diagnostics) + ' · ไม่ใช้ข้อความโมเดลแทนผลตรวจ'})
        self.controller.evaluate_attempt(active['id'])
        self._binding, self._deadline = None, None
        self._signal()

    def disconnect(self):
        self._connected = False
        self._halt('connection_lost')

    def tick(self):
        if self._deadline is not None and self._terminal is None and time.monotonic() >= self._deadline:
            self._halt('connection_lost')
            raise ProbeError('Workflow executor timed out; outcome unknown; no automatic replay.')


def workflow_saved_evidence(data):
    attempts = data['history'] + ([data['active_attempt']] if data['active_attempt'] is not None else [])
    return {e['id']: e for attempt in attempts for e in attempt.get('checks', [])}


def validate_recheck_ledger(events, evidence):
    """Replay durable reservations/bindings without executing or trusting saved results as current."""
    import re
    if not isinstance(events, list) or len(events) > 4096:
        raise ProbeError('Invalid or oversized recheck ledger.')
    operations, counts, cycles, threads, turns = {}, {}, {}, set(), set()

    def native_id(value):
        if not isinstance(value, str) or not value or len(value) > 256 or not value.isprintable():
            raise ProbeError('Invalid native recheck identity.')
        return value

    for event in events:
        if not isinstance(event, dict):
            raise ProbeError('Invalid recheck event.')
        _workflow_timestamp(event.get('timestamp'))
        kind = event.get('kind')
        if not isinstance(kind, str):
            raise ProbeError('Invalid recheck event kind.')
        if kind in ('reserve', 'choice'):
            eid = event.get('evidence_id')
            saved = evidence.get(eid) if isinstance(eid, str) else None
            if (saved is None or saved['kind'] not in ('test', 'lint')
                    or saved['origin'] != 'tool' or saved['result'] not in ('pass', 'fail')):
                raise ProbeError('Recheck references unknown or unsuitable source evidence.')
            if any(op['status'] in ('pending', 'unknown') for op in operations.values()):
                raise ProbeError('Unresolved recheck cannot be replayed or bypassed.')
            if kind == 'choice':
                if (set(event) != {'kind', 'evidence_id', 'choice', 'timestamp'}
                        or event['choice'] not in ('continue', 'revise_scope', 'pause')
                        or counts.get(eid, 0) != 3):
                    raise ProbeError('Recheck budget extension requires an explicit limit choice.')
                if event['choice'] == 'continue':
                    counts[eid] = 0
                    cycles[eid] = cycles.get(eid, 0) + 1
                continue
            if set(event) != {'kind', 'id', 'evidence_id', 'spec_digest', 'selection', 'cycle', 'number', 'timestamp'}:
                raise ProbeError('Invalid recheck reservation fields.')
            identity = _workflow_id(event['id'])
            if identity in operations or identity in evidence:
                raise ProbeError('Duplicate recheck operation identity.')
            _workflow_selection(event['selection'])
            if (event['selection']['effort'] != 'low' or not isinstance(event['spec_digest'], str)
                    or re.fullmatch('[0-9a-f]{64}', event['spec_digest']) is None
                    or type(event['cycle']) is not int or event['cycle'] != cycles.get(eid, 0)
                    or type(event['number']) is not int or event['number'] != counts.get(eid, 0) + 1
                    or not 1 <= event['number'] <= 3):
                raise ProbeError('Invalid recheck digest, selection or budget counter.')
            counts[eid] = event['number']
            operations[identity] = dict(event, phase='reserved', status='pending',
                thread_id=None, turn_id=None, exit_code=None, item_id=None, client_message_id=None)
            continue
        identity = event.get('id')
        operation = operations.get(identity) if isinstance(identity, str) else None
        invalidating = kind == 'finish' and event.get('status') == 'unknown'
        if operation is None or (operation['status'] not in ('pending', 'unknown') and not invalidating):
            raise ProbeError('Recheck event has no unresolved reservation.')
        if kind == 'recover_turn':
            if (set(event) != {'kind', 'id', 'turn_id', 'status', 'timestamp'}
                    or operation['phase'] != 'turn_pending' or operation['client_message_id'] is None
                    or event['status'] not in ('completed', 'failed', 'interrupted')):
                raise ProbeError('Recovered turn requires a correlated reservation and terminal status.')
            turn_id = native_id(event['turn_id'])
            key = (operation['thread_id'], turn_id)
            if key in turns:
                raise ProbeError('Recheck reused a native identity.')
            turns.add(key)
            operation.update(phase='turn_bound', turn_id=turn_id, status=event['status'])
            continue
        if kind == 'reconcile':
            if (set(event) != {'kind', 'id', 'status', 'timestamp'} or operation['phase'] != 'turn_bound'
                    or event['status'] not in ('completed', 'failed', 'interrupted')):
                raise ProbeError('Reconciliation requires a known native binding and terminal status.')
            operation.update(status=event['status'], exit_code=None, item_id=None)
            continue
        if kind == 'finish':
            if set(event) != {'kind', 'id', 'status', 'exit_code', 'item_id', 'timestamp'}:
                raise ProbeError('Invalid recheck terminal fields.')
            status, code, item = event['status'], event['exit_code'], event['item_id']
            if (status not in ('completed', 'failed', 'interrupted', 'unknown')
                    or (code is not None and type(code) is not int)
                    or (status != 'completed' and (code is not None or item is not None))
                    or (status != 'unknown' and operation['phase'] != 'turn_bound')
                    or (status == 'unknown' and operation['status'] == 'unknown')):
                raise ProbeError('Invalid or premature recheck terminal observation.')
            if code is not None:
                native_id(item)
            elif item is not None:
                raise ProbeError('Recheck item requires an observed exit code.')
            operation.update(status=status, exit_code=code, item_id=item)
            continue
        phases = {'thread': ('reserved', 'thread_bound', 'thread_id'),
                  'turn_reserved': ('thread_bound', 'turn_pending', None),
                  'turn': ('turn_pending', 'turn_bound', 'turn_id')}
        if kind not in phases or operation['status'] != 'pending':
            raise ProbeError('Unsupported recheck transition.')
        before, after, field = phases[kind]
        expected = {'kind', 'id', 'timestamp'} | ({field} if field else set())
        if kind == 'turn_reserved' and 'client_message_id' in event:
            import uuid
            expected.add('client_message_id')
            if event['client_message_id'] != str(uuid.UUID(hex=identity)):
                raise ProbeError('Invalid recheck client message identity.')
            operation['client_message_id'] = event['client_message_id']
        if operation['phase'] != before or set(event) != expected:
            raise ProbeError('Recheck binding preceded its reservation or changed phase.')
        if field:
            value = native_id(event[field])
            key = value if field == 'thread_id' else (operation['thread_id'], value)
            seen = threads if field == 'thread_id' else turns
            if key in seen:
                raise ProbeError('Recheck reused a native identity.')
            seen.add(key)
            operation[field] = value
        operation['phase'] = after
    return copy.deepcopy(list(operations.values()))


def validate_workflow_checkpoint(data):
    """Validate JSON shape and replay the ledger's counters; never restore grants or execute actions."""
    import re
    fields = {'version', 'plan', 'task_id', 'mode', 'baseline', 'state', 'reason', 'step_index',
              'steps', 'active_attempt', 'history', 'criterion_evidence', 'account_hash'}
    if (not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] not in (1, 2)
            or set(data) != fields | ({'rechecks'} if data['version'] == 2 else set())):
        raise ProbeError('Invalid or unsupported workflow checkpoint schema.')
    try:
        # shortcut: full checkpoints share the session's 1 MiB cap; add storage changes only when needed.
        if len(json.dumps(data, ensure_ascii=True, allow_nan=False).encode()) > 1024 * 1024:
            raise ProbeError('Workflow checkpoint is too large; nothing saved.')
    except (ValueError, TypeError, RecursionError):
        raise ProbeError('Invalid workflow checkpoint JSON.') from None
    plan = validate_plan(data['plan'])
    _workflow_id(data['task_id'])
    _workflow_selection(data['baseline'])
    if data['mode'] not in ('auto', 'ask_to_escalate', 'approve_plan') or data['state'] not in (
            'READY', 'CLARIFYING', 'AWAITING_MODEL_APPROVAL', 'RUNNING', 'CHECKING',
            'DONE', 'UNVERIFIED', 'PAUSED', 'FAILED'):
        raise ProbeError('Invalid saved workflow mode/state.')
    if data['reason'] is not None and (not isinstance(data['reason'], str)
            or not data['reason'].strip() or len(data['reason']) > 256):
        raise ProbeError('Invalid workflow pause reason.')
    if data['state'] == 'PAUSED' and data['reason'] is None:
        raise ProbeError('Paused workflow requires a reason.')
    if data['account_hash'] is not None and (not isinstance(data['account_hash'], str)
            or re.fullmatch('[0-9a-f]{64}', data['account_hash']) is None):
        raise ProbeError('Invalid workflow account binding.')
    steps = data['steps']
    if not isinstance(steps, list) or len(steps) != len(plan['steps']):
        raise ProbeError('Workflow steps do not match the saved plan.')
    ids = []
    for step in steps:
        if not isinstance(step, dict) or set(step) != {'id', 'cycle', 'attempts', 'state', 'evidence'}:
            raise ProbeError('Invalid workflow step checkpoint.')
        ids.append(_workflow_id(step['id']))
    if len(set(ids)) != len(ids) or data['task_id'] in ids:
        raise ProbeError('Duplicate workflow identity.')
    count, cycles = [0] * len(steps), [0] * len(steps)
    states, accepted = ['READY'] * len(steps), [[] for _ in steps]
    attempt_ids, evidence_ids = set(ids) | {data['task_id']}, set()
    index = 0
    history = data['history']
    if not isinstance(history, list) or len(history) > 4096:
        raise ProbeError('Invalid or oversized workflow ledger.')

    def attempt_record(attempt, active=False):
        if (index >= len(steps) or not isinstance(attempt, dict)
                or set(attempt) != {'id', 'step_id', 'cycle', 'number', 'selection', 'status', 'checks'}):
            raise ProbeError('Invalid workflow attempt checkpoint.')
        aid = _workflow_id(attempt['id'])
        if aid in attempt_ids or aid in evidence_ids or attempt['step_id'] != ids[index]:
            raise ProbeError('Duplicate/stale workflow attempt identity.')
        attempt_ids.add(aid)
        if (type(attempt['cycle']) is not int or attempt['cycle'] != cycles[index]
                or type(attempt['number']) is not int or attempt['number'] != count[index] + 1
                or not 1 <= attempt['number'] <= 3):
            raise ProbeError('Workflow attempt counter does not match its ledger.')
        _workflow_selection(attempt['selection'])
        allowed = ('running', 'completed') if active else ('completed', 'failed', 'interrupted')
        if attempt['status'] not in allowed or not isinstance(attempt['checks'], list):
            raise ProbeError('Invalid workflow attempt status/checks.')
        checks = plan['steps'][index]['checks']
        if len(attempt['checks']) > len(checks) or (attempt['status'] != 'completed' and attempt['checks']):
            raise ProbeError('Evidence cannot precede a completed attempt.')
        seen = set()
        for e in attempt['checks']:
            if not isinstance(e, dict) or set(e) != {'id', 'step_id', 'attempt_id', 'check_index', 'kind',
                    'origin', 'result', 'exit_code', 'reference', 'finding', 'timestamp'}:
                raise ProbeError('Invalid workflow evidence fields.')
            eid, check = _workflow_id(e['id']), e['check_index']
            if (eid in evidence_ids or eid in attempt_ids or type(check) is not int or not 0 <= check < len(checks)
                    or check in seen or e['step_id'] != ids[index] or e['attempt_id'] != aid
                    or e['kind'] != checks[check]['kind']):
                raise ProbeError('Workflow evidence identity/check mismatch.')
            seen.add(check)
            evidence_ids.add(eid)
            _workflow_timestamp(e['timestamp'])
            if workflow_check_result(e['kind'], e['origin'], e['result'], e['exit_code'], e['reference'], e['finding']) != e['result']:
                raise ProbeError('Workflow evidence result disagrees with its observation.')
        count[index] += 1
        return len(attempt['checks']) == len(checks) and all(e['result'] == 'pass' for e in attempt['checks'])

    for position, event in enumerate(history):
        if not isinstance(event, dict) or (index < len(steps) and states[index] == 'FAILED'):
            raise ProbeError('Invalid workflow ledger progression.')
        if 'kind' not in event:
            passed = attempt_record(event)
            if event['status'] == 'completed':
                if passed:
                    states[index], accepted[index] = 'DONE', event['checks']
                    index += 1
                else:
                    states[index] = 'READY' if any(e['result'] == 'fail' for e in event['checks']) else 'UNVERIFIED'
            else:
                states[index] = 'FAILED' if event['status'] == 'failed' else 'PAUSED'
        elif event['kind'] == 'user_choice':
            if (set(event) != {'kind', 'choice', 'reason', 'step_id', 'timestamp'}
                    or event['choice'] not in ('continue', 'revise_scope', 'pause')
                    or event['step_id'] != (ids[index] if index < len(steps) else None)):
                raise ProbeError('Invalid workflow user-choice event.')
            _plan_text(event['reason'])
            _workflow_timestamp(event['timestamp'])
        elif event['kind'] == 'budget_extension':
            previous = history[position - 1] if position else {}
            if (set(event) != {'kind', 'step_id', 'cycle', 'attempts', 'timestamp'} or index >= len(steps)
                    or event['step_id'] != ids[index] or type(event['cycle']) is not int
                    or event['cycle'] != cycles[index] or type(event['attempts']) is not int
                    or event['attempts'] != count[index] or count[index] != 3
                    or previous.get('kind') != 'user_choice' or previous.get('choice') != 'continue'
                    or previous.get('reason') != 'correction_limit' or previous.get('step_id') != ids[index]):
                raise ProbeError('Workflow budget extension lacks its explicit user choice.')
            _workflow_timestamp(event['timestamp'])
            count[index] = 0
            cycles[index] += 1
        else:
            raise ProbeError('Unknown workflow ledger event.')
    active = data['active_attempt']
    if active is not None:
        attempt_record(active, active=True)
        states[index] = 'RUNNING'
    if type(data['step_index']) is not int or data['step_index'] != index:
        raise ProbeError('Workflow position disagrees with its ledger.')
    for i, step in enumerate(steps):
        if (type(step['cycle']) is not int or step['cycle'] != cycles[i]
                or type(step['attempts']) is not int or step['attempts'] != count[i]
                or step['state'] != states[i] or step['evidence'] != accepted[i]):
            raise ProbeError('Workflow state/evidence/counters disagree with their ledger.')
    coverage = data['criterion_evidence']
    passed_ids = {e['id'] for group in accepted for e in group}
    criterion_keys = {str(i) for i in range(len(plan['success_criteria']))}
    if not isinstance(coverage, dict) or not set(coverage) <= criterion_keys:
        raise ProbeError('Invalid saved criterion coverage.')
    for entries in coverage.values():
        if (not isinstance(entries, list) or not 1 <= len(entries) <= 384
                or any(not isinstance(eid, str) or eid not in passed_ids for eid in entries)):
            raise ProbeError('Saved criterion references stale or invalid evidence.')
    state = data['state']
    if bool(plan['clarifications']) != (state == 'CLARIFYING') or (state == 'CLARIFYING' and (history or active)):
        raise ProbeError('Saved clarification state is inconsistent.')
    if (any('kind' not in event for event in history) or active) and data['account_hash'] is None:
        raise ProbeError('Attempt history requires an account binding.')
    if active is not None:
        expected = 'RUNNING' if active['status'] == 'running' else 'CHECKING'
        if state not in (expected, 'PAUSED'):
            raise ProbeError('Saved active-attempt phase is inconsistent.')
    elif index == len(steps):
        if state not in ('CHECKING', 'UNVERIFIED', 'DONE', 'PAUSED'):
            raise ProbeError('Saved finished-step phase is inconsistent.')
    elif state not in ('READY', 'CLARIFYING', 'AWAITING_MODEL_APPROVAL', 'UNVERIFIED', 'PAUSED', 'FAILED'):
        raise ProbeError('Saved idle-step phase is inconsistent.')
    if state == 'FAILED' and (index >= len(steps) or states[index] != 'FAILED'):
        raise ProbeError('Saved failure has no failed attempt.')
    if state != 'FAILED' and index < len(steps) and states[index] == 'FAILED':
        raise ProbeError('Failed attempt cannot become ready without a new task.')
    if state == 'DONE' and (index != len(steps) or set(coverage) != criterion_keys):
        raise ProbeError('Saved DONE lacks completed steps or criterion evidence.')
    if data['version'] == 2:
        if not data['rechecks']:
            raise ProbeError('Version 2 checkpoint requires a recheck ledger.')
        operations = validate_recheck_ledger(data['rechecks'], workflow_saved_evidence(data))
        if any(op['id'] in attempt_ids for op in operations):
            raise ProbeError('Recheck identity collides with work state.')
        if any(op['status'] in ('pending', 'unknown') for op in operations) and state == 'DONE':
            raise ProbeError('Unresolved recheck cannot finish a workflow.')
    return copy.deepcopy(data)


def diagnostic_code(error):
    """Useful error identity without paths, prompts, account data or raw payloads."""
    name = type(error).__name__
    if isinstance(error, OSError) and isinstance(error.errno, int):
        return name + ':errno=' + str(error.errno)
    return name


def terminal_text(value):
    """Render untrusted text without terminal control or Unicode direction controls."""
    import unicodedata
    return ''.join(c for c in str(value)
                   if c in '\n\t' or not unicodedata.category(c).startswith('C'))


class ChatShell:
    """Single-owner Terminal state; an optional trusted controller receives actions."""

    def __init__(self, output, send=None, catalog=None, role_policy=None, *, workflow=None, workflow_action=None):
        if workflow is not None and (not isinstance(workflow, WorkflowController) or send is not None):
            raise ProbeError('Workflow UI requires a controller and cannot share a manual executor.')
        if workflow_action is not None and (workflow is None or not callable(workflow_action)):
            raise ProbeError('Invalid workflow host callback.')
        self.output = output
        self.send = send
        self.catalog = [] if catalog is None else catalog
        self.role_policy = role_policy
        self.mode = 'ask_to_escalate'
        self.permissions = 'read_only'
        self.selection = None
        self.active = False
        self.stopping = False
        self.exiting = False
        self.closed = False
        self.pending = None
        self.approvals = None
        self.route = None
        self.stop_deadline = None
        self.exit_code = 0
        self.workflow = workflow
        self.workflow_action = workflow_action
        self.started_at = time.monotonic()
        self._workflow_check_attempt = None
        self.recheck_backend = self.recheck = self.recheck_pending = None
        self.recheck_commands = {}
        if isinstance(workflow_action, WorkflowHost):
            if workflow_action.controller is not workflow or workflow_action.on_change is not None:
                raise ProbeError('Workflow host is already bound or belongs to another controller.')
            workflow_action.on_change = self.event

    def write(self, text):
        self.output.write(terminal_text(text) + '\n')
        self.output.flush()

    def start(self, prompt=None):
        if self.workflow is not None:
            self.write('ModelMate · Workflow UI prototype · execution ต้องผ่าน host ที่รองรับ')
            self.write('/workflow /next /verify /revalidate /check /finish /status /mode · /cancel /exit')
            self.show_workflow()
        elif getattr(self, 'live', False):
            self.write('ModelMate · live ChatGPT/Codex · read-only + on-request')
            self.write('คำสั่งที่ sandbox อนุญาตทำงานได้เอง; การขยายสิทธิ์จะถามก่อน')
            self.write('เลือกโมเดลเองในรุ่นนี้; ยังไม่มี auto routing · /help /exit')
            if getattr(self, 'sessions', None):
                self.write('บันทึก session ในเครื่องอัตโนมัติ; /sessions แสดงรายการ')
                self.write('Session: ' + self.session_id)
            self.write('โมเดลที่ร้องขอ: ' + json.dumps(self.selection, ensure_ascii=False))
        else:
            self.write('ModelMate · Terminal shell prototype · live execution unavailable')
            self.write('/help แสดงคำสั่ง · /exit ออก · ไม่มีการเชื่อมต่อโมเดลในรุ่นนี้')
        if prompt:
            self.line(prompt)

    def cancel(self, exit_after=False):
        if self.workflow is not None:
            self.recheck_pending = None
            self._workflow_check_attempt = None
            self.exiting = self.exiting or exit_after
            self.show_workflow(render=False)
            if self.active:
                if not self.stopping:
                    self.stopping = True
                    self.stop_deadline = time.monotonic() + 5
                    self.write('กำลังขอหยุด workflow — ยังไม่ยืนยันว่าหยุดแล้ว')
                    try:
                        if self.recheck_active():
                            self.recheck.cancel()
                        elif self.workflow_action is not None:
                            self.workflow_action({'action': 'cancel', 'task_id': self.workflow.task_id})
                    finally:
                        current = self.workflow.snapshot()['active_attempt']
                        if current is not None and current['status'] == 'running':
                            self.workflow.pause()
            elif self.pending is not None and self.pending['kind'] == 'workflow_pause':
                self.workflow.answer_pause(self.pending['token'], 'pause')
            elif self.pending is not None and self.pending['kind'] == 'workflow_model':
                self.workflow.answer_model(self.pending['token'], 'pause')
            elif self.workflow.state not in ('DONE', 'FAILED', 'CLARIFYING'):
                self.workflow.pause()
            self.show_workflow()
            return
        self.pending = None
        if getattr(self, 'sessions', None):
            self.sessions('/cancel', [])
        self.exiting = self.exiting or exit_after
        if self.active:
            if not self.stopping:
                self.stopping = True
                self.stop_deadline = time.monotonic() + 5
                self.write('กำลังขอหยุดงาน — ยังไม่ยืนยันว่าหยุดแล้ว')
                if self.send is not None:
                    self.send({'action': 'cancel'})
        elif self.exiting:
            self.closed = True
        else:
            self.write('ยกเลิกคำขอที่รออยู่แล้ว')

    def tick(self):
        if self.stopping and time.monotonic() >= self.stop_deadline:
            self.write('ยืนยันการหยุดไม่ได้ ผลงานยังไม่ทราบ — ตรวจ backend ก่อนเริ่มใหม่')
            self.exit_code = 130
            self.closed = True

    def show_workflow(self, render=True):
        state = self.workflow.snapshot()
        active, request = state['active_attempt'], state['model_request']
        self.active = (active is not None and active['status'] == 'running') or self.recheck_active()
        self.mode = state['mode']
        self.pending = None
        if state['state'] == 'AWAITING_MODEL_APPROVAL' and request is not None:
            self.pending = {'kind': 'workflow_model', 'token': request['token']}
        elif state['state'] == 'PAUSED' and not self.active and state['pause_token'] is not None:
            self.pending = {'kind': 'workflow_pause', 'token': state['pause_token']}
        if not self.active:
            self.stopping = False
            self.stop_deadline = None
            if self.exiting:
                self.closed = True
        if not render:
            return state
        self.write('งาน: ' + state['plan']['goal'])
        self.write('สถานะ: ' + state['state'] + ' · โหมด: ' + state['mode']
                   + (' · เหตุผล: ' + state['reason'] if state['reason'] else ''))
        for i, (step, proposal) in enumerate(zip(state['steps'], state['plan']['steps'])):
            marker = '→' if i == state['step_index'] else ' '
            try:
                model = select_role(self.catalog, proposal['role'], self.role_policy, proposal['effort'])['model']
            except ProbeError:
                model = 'ยัง resolve โมเดลไม่ได้'
            step_state = 'CHECKING' if (active is not None and active['step_id'] == step['id']
                                              and active['status'] == 'completed') else step['state']
            self.write(marker + ' ' + str(i + 1) + '. ' + proposal['kind'] + ': ' + proposal['objective']
                       + ' · ' + step_state + ' · รอบ ' + str(step['cycle'] + 1)
                       + ' · attempt ' + str(step['attempts']) + '/3'
                       + ' · โมเดลตามแผน: ' + model + '/' + proposal['effort'])
            self.write('  ความเสี่ยง: ' + proposal['risk'] + ' · เหตุผล: ' + proposal['reason'])
            latest = active if active is not None and active['step_id'] == step['id'] else next(
                (item for item in reversed(state['history']) if 'checks' in item and item['step_id'] == step['id']), None)
            checked = {} if latest is None else latest['checks']
            for index, check in enumerate(proposal['checks']):
                evidence = checked.get(index, {})
                result = 'stale' if evidence.get('id') in state['stale_evidence'] else evidence.get('result', 'pending')
                self.write('  [' + result + '] ' + check['kind'] + ': ' + check['criterion'] + ' · check ' + str(index + 1)
                           + (' · evidence ' + evidence['id'] + ' · ref ' + str(i + 1) + '.' + str(index + 1)
                              if evidence.get('id') else ''))
        for i, criterion in enumerate(state['success_criteria']):
            self.write('เกณฑ์ ' + str(i + 1) + ': ' + criterion + ' · หลักฐานที่บันทึก ' + str(len(state['criterion_evidence'].get(i, []))))
        if active is not None:
            self.write('โมเดลที่ร้องขอใน attempt นี้: ' + json.dumps(active['selection']))
        if state['stale_evidence']:
            self.write('หลักฐานที่ restore เป็น stale: ตรวจผลปัจจุบันแล้ว /revalidate STEP.CHECK pass|fail|unknown สำหรับ manual/rubric; tool checks ต้องตรวจด้วยเครื่องมือใหม่')
            if self.recheck_backend is not None:
                self.write('/recheck STEP.CHECK แสดงคำสั่ง/model ก่อนยืนยัน · ใช้โควตา subscription')
        operations = self.workflow.recheck_operations()
        if operations:
            operation = operations[-1]
            status = 'unknown' if self.workflow._recheck_fault else operation['status']
            code = None if self.workflow._recheck_fault else operation['exit_code']
            self.write('Recheck: ' + status + ' · รอบ ' + str(operation['cycle'] + 1)
                       + ' · reservation ' + str(operation['number']) + '/3'
                       + ' · exit code ' + str(code))
        if state['state'] == 'READY' and self.workflow_action is not None and not self.recheck_active():
            self.write('ใช้ /next เพื่อเริ่มขั้นปัจจุบัน')
        if state['state'] == 'CHECKING':
            if active is not None:
                checks = state['plan']['steps'][state['step_index']]['checks']
                pending_manual = [str(i + 1) for i, check in enumerate(checks)
                                  if check['kind'] in ('manual', 'rubric') and i not in active['checks']]
                if pending_manual:
                    self.write('ใช้ /verify CHECK_NUMBER pass|fail|unknown สำหรับข้อ '
                               + ', '.join(pending_manual) + ' แล้วใช้ /check')
                else:
                    self.write('Backend จบแล้ว ใช้ /check เพื่อประเมินผลขั้นนี้')
            elif state['step_index'] == len(state['steps']):
                self.write('ขั้นงานผ่านแล้ว; ยืนยันเกณฑ์ด้วย /finish เช่น /finish 1=1.1 โดยเลือก ref ที่รองรับเกณฑ์จริง')
        if request is not None and self.pending is not None:
            if request['scope'] == 'plan':
                self.write('ยืนยันโมเดลและ effort ของทั้งแผน')
                for index, selection in enumerate(request['selections'], 1):
                    self.write('  ขั้น ' + str(index) + ' · ' + selection['model'] + '/' + selection['effort'])
            else:
                self.write('โมเดลที่เสนอ: ' + json.dumps(request['selection']) + ' · ' + request['reason'])
            self.write('/approve ' + request['token'] + ' · /decline ' + request['token'] + ' · /pause ' + request['token'])
            if self.workflow_action is not None:
                self.write('อนุมัติและเริ่มขั้นนี้ในคำสั่งเดียว: /approve ' + request['token'] + ' --next')
        elif self.pending is not None:
            token = self.pending['token']
            self.write('/continue ' + token + ' · /revise ' + token + ' · /pause ' + token)
        if state['state'] == 'CLARIFYING':
            for question in state['clarifications']:
                self.write('ต้องชี้แจง: ' + question)
        if self.active and state['state'] == 'PAUSED':
            self.write('ผลขั้นงานยังไม่ทราบ ต้องรอ host ยืนยัน terminal event ก่อนทำต่อ')
        return state

    def recheck_active(self):
        return (self.recheck is not None and not self.recheck._closed and self.recheck.host is not None
                and self.recheck.host._binding is not None and self.recheck.host._terminal is None)

    def _recheck_evidence(self, reference):
        import re
        if not isinstance(reference, str) or re.fullmatch(r'[1-9][0-9]{0,3}\.[1-9][0-9]{0,3}', reference) is None:
            raise ProbeError('Use a step.check reference, for example 1.1.')
        step, check = [int(number) - 1 for number in reference.split('.')]
        state = self.workflow.snapshot()
        if step >= len(state['steps']):
            raise ProbeError('Unknown step/check reference.')
        target = state['steps'][step]
        active = state['active_attempt']
        candidates = list(active['checks'].values()) if active is not None and active['step_id'] == target['id'] else target['evidence']
        evidence = next((item for item in candidates if item['check_index'] == check), None)
        if evidence is None:
            raise ProbeError('Reference has no saved evidence to recheck.')
        return evidence

    def _recheck_fingerprint(self):
        import hashlib
        return hashlib.sha256(json.dumps({'checkpoint': self.workflow.export_checkpoint(),
            'stale': self.workflow.snapshot()['stale_evidence'], 'policy': self.role_policy},
            sort_keys=True, ensure_ascii=True).encode()).hexdigest()

    def recheck_command(self, cmd, values):
        import uuid
        if self.recheck_backend is None:
            raise ProbeError('Recheck CLI is not enabled for this session.')
        if self.active:
            raise ProbeError('Wait for the active turn or use /cancel before rechecking.')
        if cmd == '/recheck-budget':
            if len(values) != 2:
                raise ProbeError('Use /recheck-budget STEP.CHECK continue|revise_scope|pause.')
            evidence = self._recheck_evidence(values[0])
            self.recheck_pending = None
            self.workflow.answer_recheck_limit(evidence['id'], values[1])
            self.write('บันทึกตัวเลือกงบแล้ว ยังไม่เริ่ม model turn; ใช้ /recheck เพื่อแสดงแผนใหม่')
            return
        if cmd == '/recheck':
            self.recheck_pending = None
            if len(values) != 1:
                raise ProbeError('Use /recheck STEP.CHECK.')
            evidence = self._recheck_evidence(values[0])
            if (evidence['kind'] not in ('test', 'lint') or evidence['origin'] != 'tool'
                    or evidence['result'] not in ('pass', 'fail')
                    or evidence['id'] not in self.workflow.snapshot()['stale_evidence']):
                raise ProbeError('Recheck requires stale saved test/lint evidence with a known result.')
            operations = self.workflow.recheck_operations()
            if any(op['status'] in ('pending', 'unknown') for op in operations):
                raise ProbeError('Recheck outcome unresolved; inspect retained metadata before further work.')
            events = self.workflow.export_checkpoint().get('rechecks', [])
            cycle = sum(event['kind'] == 'choice' and event['evidence_id'] == evidence['id']
                        and event['choice'] == 'continue' for event in events)
            if sum(op['evidence_id'] == evidence['id'] and op['cycle'] == cycle for op in operations) >= 3:
                raise ProbeError('Recheck limit reached; use /recheck-budget STEP.CHECK continue|revise_scope|pause.')
            spec = self.recheck_commands.get(values[0])
            if spec is None:
                raise ProbeError('This check has no explicit user-owned command/cwd binding.')
            selection = select_role(self.catalog, 'standard', self.role_policy, 'low')
            token = uuid.uuid4().hex
            self.recheck_pending = {'token': token, 'reference': values[0], 'evidence_id': evidence['id'],
                'spec': copy.deepcopy(spec), 'selection': selection, 'fingerprint': self._recheck_fingerprint()}
            self.write('ตรวจซ้ำ ' + values[0] + ' · ใช้โควตา subscription หนึ่ง verification turn · read-only/on-request')
            self.write('คำสั่ง/cwd: ' + json.dumps(spec, ensure_ascii=True))
            self.write('โมเดลที่ร้องขอ: ' + json.dumps(selection, ensure_ascii=True))
            self.write('/confirm-recheck ' + token + ' เพื่อยืนยันครั้งเดียว · /cancel เพื่อยกเลิก')
            return
        pending = self.recheck_pending
        if len(values) != 1 or pending is None or values[0] != pending['token']:
            raise ProbeError('Invalid or expired recheck confirmation token.')
        self.recheck_pending = None
        if (pending['fingerprint'] != self._recheck_fingerprint()
                or self.recheck_commands.get(pending['reference']) != pending['spec']):
            raise ProbeError('Recheck plan/model/state changed; use /recheck for a new preview.')
        if self.recheck is not None:
            self.recheck.close()
        self.recheck = self.recheck_backend.open_recheck(pending['evidence_id'], pending['spec'],
                                                       pending['selection'], self.event)
        self.show_workflow()

    def show_workflow_status(self, state):
        stats = workflow_statistics(self.workflow, self.started_at)
        done = sum(step['state'] == 'DONE' for step in state['steps'])
        reason = ' · ' + state['reason'] if state['reason'] else ''
        self.write(state['state'] + reason + ' · ' + state['mode']
                   + ' · เสร็จ ' + str(done) + '/' + str(len(state['steps'])) + ' ขั้น')
        self.write(f"เวลาในแชต {stats['elapsedSeconds']:.1f} วินาทีรวมเวลารอ"
                   f" · {stats['attempts']} attempts · {stats['recheckAttempts']} rechecks")
        if state['active_attempt'] is not None:
            selection = state['active_attempt']['selection']
            self.write('โมเดลที่ร้องขอ: ' + selection['model'] + '/' + selection['effort'])
        operations = self.workflow.recheck_operations()
        if operations:
            status = 'unknown' if self.workflow._recheck_fault else operations[-1]['status']
            self.write('Recheck: ' + status)
        if self.recheck_active():
            self.write('ใช้ /cancel เพื่อขอหยุด recheck')
        elif state['state'] == 'READY' and self.workflow_action is not None:
            self.write('ใช้ /next เพื่อเริ่มขั้นปัจจุบัน')
        self.write('ใช้ /workflow เพื่อดูแผน เกณฑ์ตรวจ และตัวเลือกที่รอการตอบ')

    def workflow_command(self, cmd, values):
        state = self.show_workflow(render=False)
        try:
            if cmd in ('/recheck', '/confirm-recheck', '/recheck-budget'):
                self.recheck_command(cmd, values)
                return
            if self.recheck_active() and cmd not in ('/workflow', '/status'):
                raise ProbeError('A recheck is active; use /status or /cancel before changing work.')
            if cmd in ('/workflow', '/status'):
                if values:
                    raise ProbeError('Use /workflow or /status without arguments.')
                if cmd == '/status':
                    self.show_workflow_status(state)
                    return
            elif cmd in ('/next', '/check'):
                if values:
                    raise ProbeError('Use ' + cmd + ' without arguments.')
                if (cmd == '/check' and state['state'] == 'RUNNING'
                        and state['active_attempt'] is not None
                        and isinstance(self.workflow_action, WorkflowHost)
                        and all(check['kind'] in ('test', 'lint') for check in
                                state['plan']['steps'][state['step_index']]['checks'])):
                    self._workflow_check_attempt = state['active_attempt']['id']
                    self.write('รับคำขอ /check แล้ว จะตรวจเมื่อ backend ยืนยันจบ attempt นี้ ไม่เรียกโมเดลเพิ่ม')
                    return
                expected = 'READY' if cmd == '/next' else 'CHECKING'
                if state['state'] != expected:
                    raise ProbeError('Workflow is not ' + expected + '; answer its pending choice or wait for the host.')
                if self.workflow_action is None:
                    raise ProbeError('Workflow executor is unavailable; no attempt consumed or dispatched.')
                self.workflow_action({'action': cmd[1:], 'task_id': self.workflow.task_id})
                if isinstance(self.workflow_action, WorkflowHost):
                    return  # Host already emitted workflow_changed and rendered the authoritative state.
            elif cmd == '/revalidate':
                if len(values) != 2 or values[1] not in ('pass', 'fail', 'unknown'):
                    raise ProbeError('Use /revalidate STEP.CHECK pass|fail|unknown for saved manual/rubric evidence.')
                step_number, check_number = (int(part) for part in values[0].split('.'))
                if not 1 <= step_number <= len(state['steps']) or check_number < 1:
                    raise ProbeError('Invalid evidence reference.')
                step = state['steps'][step_number - 1]
                candidates = step['evidence']
                active = state['active_attempt']
                if active is not None and active['step_id'] == step['id']:
                    candidates = list(active['checks'].values())
                evidence = next((item for item in candidates if item['check_index'] == check_number - 1), None)
                if evidence is None or evidence['kind'] not in ('manual', 'rubric'):
                    raise ProbeError('Only saved manual/rubric evidence can be revalidated by the user; tool checks need fresh tool observations.')
                self.workflow.revalidate_check(evidence['id'], origin='manual', result=values[1],
                    reference='Explicit user revalidation after native resume', finding='User checked current result: ' + values[1])
            elif cmd == '/verify':
                if len(values) != 2 or values[1] not in ('pass', 'fail', 'unknown'):
                    raise ProbeError('Use /verify CHECK_NUMBER pass|fail|unknown (numbers start at 1).')
                active = state['active_attempt']
                if state['state'] != 'CHECKING' or active is None or active['status'] != 'completed':
                    raise ProbeError('Verification requires a confirmed completed attempt.')
                index = int(values[0]) - 1
                checks = state['plan']['steps'][state['step_index']]['checks']
                if not 0 <= index < len(checks) or checks[index]['kind'] not in ('manual', 'rubric'):
                    raise ProbeError('Only manual/rubric checks accept user verification.')
                self.workflow.record_check(active['id'], index, origin='manual', result=values[1],
                    reference='Explicit user verification in Terminal', finding='User recorded ' + values[1])
            elif cmd == '/finish':
                if not values:
                    raise ProbeError('Use /finish CRITERION_NUMBER=STEP.CHECK[,STEP.CHECK] ... (numbers start at 1).')
                coverage = {}
                for value in values:
                    number, evidence = value.split('=', 1)
                    index = int(number) - 1
                    if index in coverage:
                        raise ProbeError('Duplicate criterion number.')
                    coverage[index] = []
                    for reference in evidence.split(','):
                        if reference == 'EVIDENCE_ID':
                            raise ProbeError('EVIDENCE_ID เป็นตัวอย่าง; ใช้ ref ที่แสดง เช่น /finish 1=1.1')
                        if '.' in reference:
                            step_number, check_number = (int(part) for part in reference.split('.'))
                            if not 1 <= step_number <= len(state['steps']) or check_number < 1:
                                raise ProbeError('Invalid step/check evidence reference.')
                            step = state['steps'][step_number - 1]
                            matches = [item for item in step['evidence'] if item['check_index'] == check_number - 1]
                            if step['state'] != 'DONE' or len(matches) != 1:
                                raise ProbeError('Reference has no accepted completed-step evidence; use /check first.')
                            reference = matches[0]['id']
                        coverage[index].append(reference)
                self.workflow.finish_task(coverage)
            elif cmd == '/mode':
                if len(values) > 1:
                    raise ProbeError('Use /mode [auto|ask_to_escalate|approve_plan].')
                if values:
                    self.workflow.change_mode(values[0])
            else:
                start_now = cmd == '/approve' and len(values) == 2 and values[1] == '--next'
                if ((len(values) != 1 and not start_now) or self.pending is None
                        or values[0] != self.pending['token']):
                    raise ProbeError('Invalid or stale workflow choice token.')
                if self.pending['kind'] == 'workflow_model' and cmd in ('/approve', '/decline', '/pause'):
                    if start_now and self.workflow_action is None:
                        raise ProbeError('Workflow executor is unavailable; no attempt consumed or dispatched.')
                    self.workflow.answer_model(values[0], cmd[1:])
                    if start_now:
                        self.workflow_action({'action': 'next', 'task_id': self.workflow.task_id})
                        if isinstance(self.workflow_action, WorkflowHost):
                            return
                elif self.pending['kind'] == 'workflow_pause' and cmd in ('/continue', '/revise', '/pause'):
                    self.workflow.answer_pause(values[0], {'/continue': 'continue', '/revise': 'revise_scope', '/pause': 'pause'}[cmd])
                else:
                    raise ProbeError('Choice does not match the current workflow request.')
        except (ProbeError, ValueError) as exc:
            self.write(str(exc) if isinstance(exc, ProbeError) else 'รูปแบบหมายเลขหรือหลักฐานไม่ถูกต้อง')
        self.show_workflow()

    def line(self, text):
        import shlex
        text = text.strip()
        if not text or self.closed:
            return
        if len(text.encode('utf-8')) > 65536:
            self.write('ข้อความยาวเกิน 64 KiB')
            return
        if text.startswith('/'):
            try:
                args = shlex.split(text)
            except ValueError:
                self.write('รูปแบบคำสั่งไม่ถูกต้อง')
                return
            cmd, *values = args
            if self.workflow is not None and cmd in ('/workflow', '/next', '/check', '/verify', '/revalidate', '/finish', '/status', '/mode',
                                                      '/recheck', '/confirm-recheck', '/recheck-budget',
                                                      '/approve', '/decline', '/pause', '/continue', '/revise'):
                self.workflow_command(cmd, values)
            elif self.workflow is not None and cmd in ('/model', '/sessions', '/delete', '/confirm-delete', '/acknowledge'):
                self.write('คำสั่งนี้ยังไม่เชื่อม workflow host; ใช้ /workflow เพื่อดูแผนและสถานะ')
            elif cmd == '/help':
                self.write('/status /mode [auto|ask_to_escalate|approve_plan] /model [ID EFFORT]\n'
                           '/permissions [ask|read_only|workspace] /sessions [ID] /delete [ID]\n'
                           '/confirm-delete TOKEN /acknowledge TOKEN /cancel /exit\n'
                           '/approve TOKEN /decline TOKEN /pause TOKEN')
                if self.workflow is not None:
                    self.write('/workflow /next /approve TOKEN --next /verify CHECK_NUMBER pass|fail|unknown /check /finish CRITERION_NUMBER=STEP.CHECK /revalidate STEP.CHECK pass|fail|unknown /continue TOKEN /revise TOKEN · /approve TOKEN อย่างเดียวจะรอ /next')
                    if self.recheck_backend is not None:
                        self.write('/recheck STEP.CHECK /confirm-recheck TOKEN /recheck-budget STEP.CHECK continue|revise_scope|pause')
            elif cmd == '/status':
                self.write(json.dumps({'mode': self.mode, 'permissions': self.permissions,
                                       'selection': self.selection, 'active': self.active,
                                       'session': getattr(self, 'session_id', None),
                                       'stopping': self.stopping, 'quota': getattr(self, 'quota_status', 'unknown'),
                                       'backend': 'codex' if getattr(self, 'live', False) else
                                       ('injected test controller' if self.send else 'unavailable')},
                                      ensure_ascii=False))
            elif cmd == '/mode':
                if not values:
                    self.write(self.mode)
                elif len(values) != 1 or values[0] not in ('auto', 'ask_to_escalate', 'approve_plan'):
                    self.write('โหมดไม่ถูกต้อง')
                elif getattr(self, 'live', False):
                    self.write('Live chat ยังใช้โมเดลที่เลือกเอง; auto workflow ยังไม่เปิด')
                else:
                    self.mode = values[0]
                    self.pending = None
                    if self.route is not None:
                        self.present_route()
                    self.write('โหมด: ' + self.mode)
            elif cmd == '/permissions':
                if not values:
                    self.write(self.permissions)
                elif len(values) != 1 or values[0] not in ('ask', 'read_only', 'workspace'):
                    self.write('สิทธิ์ไม่ถูกต้อง')
                else:
                    self.write('รุ่นนี้ใช้ read-only + on-request; การขยายสิทธิ์อนุมัติเป็นรายคำขอ')
            elif cmd == '/model':
                if not values:
                    self.write(json.dumps({'selected': self.selection, 'catalog': self.catalog}, ensure_ascii=False))
                elif self.active or self.route is not None:
                    self.write('พักการเปลี่ยนโมเดลระหว่างงาน — ต้องเสนอแผนและขออนุมัติใหม่')
                elif len(values) not in (1, 2):
                    self.write('ใช้ /model ID [EFFORT]')
                else:
                    try:
                        self.selection = select_model(self.catalog, values[0], values[1] if len(values) == 2 else None)
                        self.write('เลือกโมเดลสำหรับงานถัดไป: ' + json.dumps(self.selection))
                    except ProbeError as exc:
                        self.write(str(exc))
            elif cmd in ('/sessions', '/delete', '/confirm-delete', '/acknowledge'):
                if not getattr(self, 'sessions', None):
                    self.write('Session lifecycle ยังไม่เปิดในโหมดนี้')
                elif self.active or self.stopping:
                    self.write('รอยืนยันว่า turn จบก่อนจัดการ session')
                else:
                    self.sessions(cmd, values)
            elif cmd in ('/approve', '/decline', '/pause'):
                if len(values) != 1 or self.pending is None or values[0] != self.pending.get('token'):
                    self.write('คำขออนุมัติไม่ถูกต้องหรือหมดอายุ')
                else:
                    try:
                        if self.pending.get('kind') == 'tool':
                            self.send({'action': 'tool_decision', 'token': values[0], 'choice': cmd[1:]})
                            self.pending = None
                            if cmd == '/pause':
                                self.cancel()
                        else:
                            self.approvals.answer(values[0], cmd[1:])
                            self.pending = None
                            self.present_route()
                    except ProbeError as exc:
                        self.write(str(exc))
            elif cmd in ('/cancel', '/exit'):
                self.cancel(exit_after=cmd == '/exit')
            else:
                self.write('ไม่รู้จักคำสั่ง ใช้ /help')
            return
        if self.workflow is not None:
            self.write('Workflow UI ยังไม่รับโจทย์/ชี้แจงเข้าโมเดลอัตโนมัติ ใช้ /workflow หรือ /next')
            return
        if self.pending is not None:
            self.write('ยังรอการอนุมัติ ใช้ /approve, /decline หรือ /pause พร้อม TOKEN')
            return
        if self.stopping:
            self.write('ยังรอยืนยันการหยุด จะไม่ส่งงานใหม่')
            return
        if self.send is None:
            self.write('โหมด offline ไม่ส่งโจทย์เข้าโมเดล ใช้ --live เพื่อเลือกโมเดลเอง หรือ --workflow เพื่อเปิดแผน')
            return
        action = 'steer' if self.active else 'submit'
        self.active = True
        self.send({'action': action, 'text': text, 'mode': self.mode, 'selection': self.selection})

    def present_route(self):
        route = self.route
        decision = self.approvals.decision(route['raw'], self.catalog, self.role_policy,
                                           step_id=route['step_id'], step_index=route['step_index'], mode=self.mode)
        self.pending = decision if decision['state'] == 'ask' else None
        self.write(json.dumps(decision, ensure_ascii=False))
        # Model choice only; no tool or inference dispatch occurs here.

    def event(self, message):
        if not isinstance(message, dict) or not isinstance(message.get('type'), str):
            raise ProbeError('Invalid chat controller event.')
        kind = message['type']
        if self.workflow is not None and kind not in ('text', 'progress'):
            if kind != 'workflow_changed' or set(message) != {'type', 'task_id'} or message['task_id'] != self.workflow.task_id:
                raise ProbeError('Workflow event is stale/unsupported; no action approved.')
            if isinstance(self.workflow_action, WorkflowHost):
                self.catalog = self.workflow_action.catalog
                self.role_policy = self.workflow_action.role_policy
            state = self.workflow.snapshot()
            active = state['active_attempt']
            if self._workflow_check_attempt is not None:
                requested = self._workflow_check_attempt
                if (state['state'] == 'CHECKING' and active is not None
                        and active['id'] == requested and active['status'] == 'completed'):
                    self._workflow_check_attempt = None
                    self.write('Backend จบแล้ว กำลังตรวจตามคำขอ /check ที่รอไว้')
                    self.workflow_action({'action': 'check', 'task_id': self.workflow.task_id})
                    return
                if state['state'] != 'RUNNING' or active is None or active['id'] != requested:
                    self._workflow_check_attempt = None
            self.show_workflow()
            return
        if kind in ('text', 'progress'):
            text = message.get('text')
            if not isinstance(text, str):
                raise ProbeError('Invalid text event.')
            self.write(text)
        elif kind == 'tool_approval':
            if (self.send is None or self.pending is not None
                    or not isinstance(message.get('token'), str) or not message['token']
                    or not isinstance(message.get('preview'), str)):
                raise ProbeError('Invalid tool approval event.')
            self.pending = {'kind': 'tool', 'token': message['token']}
            self.write(message['preview'])
            self.write('/approve ' + message['token'] + ' · /decline ' + message['token'])
        elif kind == 'plan':
            if self.stopping:
                return
            raw, step_id, index = message.get('raw'), message.get('step_id'), message.get('step_index', 0)
            result = routing_decision(raw, self.catalog, self.role_policy)
            if result['state'] != 'ready_for_approval':
                self.pending = None
                self.approvals = None
                self.route = None
                self.write(json.dumps(result, ensure_ascii=False))
                return
            if self.approvals is None:
                self.approvals = ModelApprovals(self.catalog, self.role_policy)
            self.route = {'raw': raw, 'step_id': step_id, 'step_index': index}
            self.present_route()
        elif kind in ('completed', 'stopped'):
            self.active = False
            self.stopping = False
            self.stop_deadline = None
            self.pending = None
            self.approvals = None
            self.route = None
            self.write('หยุดงานแล้ว' if kind == 'stopped' else 'จบ turn ของ backend; ผลตรวจงานต้องดูแยกต่างหาก')
            if self.exiting:
                self.closed = True
        else:
            # Tool approval/execution events are not supported by this shell stage.
            raise ProbeError('Unsupported controller event; no action approved.')


def run_chat(input_stream, output, *, event_stream=None, send=None, catalog=None,
             role_policy=None, prompt=None, backend=None, workflow=None, workflow_action=None, executor_stream=None,
             recheck_commands=None):
    """Multiplex Linux input and controller events in one owning thread."""
    native_workflow = isinstance(backend, NativeWorkflowConnection)
    if workflow is not None and backend is not None:
        if (not native_workflow or backend.host is None or backend.host is not workflow_action
                or backend.host.controller is not workflow):
            raise ProbeError('Native live workflow integration requires its bound transport host.')
    elif native_workflow:
        raise ProbeError('Native workflow transport requires its controller and host.')
    if executor_stream is not None and (workflow is None or not isinstance(workflow_action, WorkflowHost)):
        raise ProbeError('Executor observations require an explicitly bound workflow host.')
    if backend is not None and not native_workflow:
        send, catalog = backend.action, backend.catalog
    shell = ChatShell(output, send, catalog, role_policy, workflow=workflow, workflow_action=workflow_action)
    if recheck_commands is not None:
        if not native_workflow or backend.store is None or workflow is None:
            raise ProbeError('Recheck UI requires an attached durable native workflow.')
        specs = validate_check_commands({'version': 1, 'checks': recheck_commands},
                                        workflow.snapshot()['plan'], backend.cwd)
        shell.recheck_backend = backend
        shell.recheck_commands = {str(spec['step']) + '.' + str(spec['check']):
            {'command': spec['command'], 'cwd': spec['cwd']} for spec in specs}
    if backend is not None and not native_workflow:
        backend.shell = shell
        shell.live = True
        shell.mode = 'manual'
        shell.selection = dict(backend.selection)
        if backend.store is not None:
            shell.sessions = backend.session_command
            shell.session_id = backend.record['id']
            shell.quota_status = {k: backend.quota_status[k] for k in ('state', 'reason', 'checked_at')}
            if backend.recovery_token is not None:
                shell.write('ผล turn ก่อนปิดโปรแกรมยังไม่ทราบ; ตรวจไฟล์/process แล้วใช้ /acknowledge '
                            + backend.recovery_token + ' ก่อนส่งข้อความใหม่')
    selector = selectors.SelectSelector()
    buffers = {}
    registered_recheck, recheck_fds = None, []

    def sync_recheck_streams():
        nonlocal registered_recheck, recheck_fds
        child = shell.recheck if shell.recheck is not None and not shell.recheck._closed else None
        if child is registered_recheck:
            return
        for fd in recheck_fds:
            try:
                selector.unregister(fd)
            except KeyError:
                pass
        registered_recheck, recheck_fds = child, []
        if child is not None:
            for stream in (child.process.stdout, child.process.stderr):
                selector.register(stream, selectors.EVENT_READ, ('recheck', child))
                recheck_fds.append(stream.fileno())

    try:
        for stream, kind in ((input_stream, 'input'), (event_stream, 'events'), (executor_stream, 'executor')):
            if stream is not None:
                selector.register(stream, selectors.EVENT_READ, kind)
                buffers[kind] = b''
        if backend is not None:
            for stream in (backend.process.stdout, backend.process.stderr):
                selector.register(stream, selectors.EVENT_READ, 'codex')
        shell.start(prompt)
        while not shell.closed:
            try:
                sync_recheck_streams()
                ready = selector.select(.1)
                for key, _ in ready:
                    kind = key.data
                    if isinstance(kind, tuple) and kind[0] == 'recheck':
                        child = kind[1]
                        if child is not shell.recheck or child._closed:
                            continue
                        if not child.read_ready(key.fileobj):
                            selector.unregister(key.fd)
                        child.drain()
                        continue
                    if kind == 'codex':
                        if not backend.read_ready(key.fileobj):
                            selector.unregister(key.fileobj)
                        backend.drain()
                        continue
                    data = os.read(key.fd, 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                        if buffers[kind]:
                            if kind == 'input':
                                shell.line(buffers[kind].decode('utf-8'))
                            else:
                                raise ProbeError('Truncated controller event.')
                            buffers[kind] = b''
                        if kind == 'input':
                            shell.cancel(exit_after=True)
                        elif kind == 'executor':
                            workflow_action.disconnect()
                            raise ProbeError('Workflow executor disconnected; no automatic replay.')
                        else:
                            raise ProbeError('Controller disconnected; no more work can be submitted.')
                        continue
                    buffers[kind] += data
                    if len(buffers[kind]) > 1024 * 1024:
                        raise ProbeError('Terminal input/event buffer exceeded limit.')
                    while b'\n' in buffers[kind] and not shell.closed:
                        line, buffers[kind] = buffers[kind].split(b'\n', 1)
                        if kind == 'input':
                            shell.line(line.decode('utf-8'))
                        elif kind == 'executor':
                            workflow_action.observe_native(json.loads(line))
                        else:
                            shell.event(json.loads(line))
                if backend is not None:
                    backend.drain()
                    backend.tick()
                if shell.recheck is not None and not shell.recheck._closed:
                    shell.recheck.drain()
                    shell.recheck.tick()
                if isinstance(workflow_action, WorkflowHost):
                    workflow_action.tick()
                shell.tick()
            except KeyboardInterrupt:
                shell.cancel()
    except (ProbeError, OSError, ValueError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, ProbeError) else diagnostic_code(exc)
        phase = getattr(backend, 'phase', 'terminal')
        shell.write('Terminal หยุด [' + phase + ']: ' + reason + '; ผลงานที่กำลังทำยังไม่ทราบ')
        if shell.workflow is not None:
            if isinstance(workflow_action, WorkflowHost):
                try:
                    workflow_action.disconnect()
                except (ProbeError, OSError):
                    pass
            try:
                shell.cancel(exit_after=True)
            except (ProbeError, OSError):
                pass
        elif shell.active and send is not None:
            try:
                send({'action': 'cancel'})
            except (ProbeError, OSError):
                pass
        return 1
    finally:
        selector.close()
        if shell.recheck is not None:
            try:
                if shell.recheck_active():
                    shell.recheck.cancel()
            except (ProbeError, OSError):
                pass
            finally:
                shell.recheck.close()
        if isinstance(workflow_action, WorkflowHost):
            workflow_action.on_change = None
    return shell.exit_code



THREAD_SOURCE_KINDS = ['cli', 'vscode', 'exec', 'appServer', 'subAgent', 'subAgentReview',
                       'subAgentCompact', 'subAgentThreadSpawn', 'subAgentOther', 'unknown']


def native_thread_options(selection, cwd):
    return {
        'model': selection['model'], 'modelProvider': 'openai', 'cwd': cwd,
        'sandbox': 'read-only', 'approvalPolicy': 'on-request', 'approvalsReviewer': 'user',
        'serviceTier': 'default',
        'config': {'web_search': 'disabled', 'agents.enabled': False,
                   'features.apps': False, 'features.plugins': False,
                   'features.multi_agent_v2': False},
    }

def native_permissions_confirmed(result):
    sandbox = result.get('sandbox')
    return (result.get('approvalPolicy') == 'on-request' and result.get('approvalsReviewer') == 'user'
            and isinstance(sandbox, dict) and sandbox.get('type') == 'readOnly')


class LiveChatConnection(Connection):
    """Manual-model chat using native Codex read-only/on-request permissions."""
    allowed_methods = Connection.allowed_methods | {'thread/start', 'thread/read', 'thread/resume',
        'thread/turns/list', 'thread/list', 'thread/delete'}

    def __init__(self, command, timeout=15):
        super().__init__(command, timeout)
        self.shell = None
        self.catalog = []
        self.selection = None
        self.thread_id = None
        self.turn_id = None
        self.start_pending = False
        self.phase = 'idle'
        self.cancel_after_start = False
        self.account_id = None
        self.quota_status = None
        self._rpcs = {}
        self._approvals = {}
        self._previews = {}
        self._streamed = set()
        self._finished = set()
        self.store = None
        self.record = None
        self._session_lock = None
        self.recovery_token = None
        self.delete_proposal = None

    def connect(self, model, effort, cwd, store=None, session_id=None):
        self.catalog = inspect(self)['models']
        self.selection = select_model(self.catalog, model, effort)
        if effort == 'ultra':
            raise ProbeError('Automatic delegation effort is not enabled in this live chat.')
        self.cwd = os.path.realpath(cwd)
        self.store = store
        if store is not None:
            if store.project != self.cwd:
                raise ProbeError('Session store project mismatch.')
            if session_id is not None:
                self.open_session(session_id)
                return
            self._fresh_account(require_usage=False)
            self.record = store.create('New manual chat', account_hash=self._account_hash())
            self._session_lock = store._lock(self.record['id'])
            self._session_lock.__enter__()
            self.checkpoint(state='PAUSED', pause_reason='thread_start_unknown')
        result = self.request('thread/start', dict(self._thread_options(),
            ephemeral=store is None))
        thread = result.get('thread')
        if not isinstance(thread, dict) or not isinstance(thread.get('id'), str) or not thread['id']:
            raise ProbeError('Invalid live thread response.')
        self.thread_id = thread['id']
        self.checkpoint(thread_id=self.thread_id, mode='manual', state='READY', pause_reason=None)

    def _thread_options(self):
        return native_thread_options(self.selection, self.cwd)

    def _account_hash(self):
        import hashlib
        return hashlib.sha256(self.account_id.encode()).hexdigest()

    def _fresh_account(self, require_usage=True):
        quota = refresh_quota(self, self.account_id)
        if quota['state'] != 'allow' and not (not require_usage and quota['reason'] == 'quota_exhausted'
                                             and quota.get('account_id')):
            raise ProbeError('Session preflight paused: ' + quota['reason'])
        self.account_id = quota['account_id']
        self.quota_status = quota

    def checkpoint(self, **changes):
        if self.record is not None:
            self.record.update(changes)
            self.store.save(self.record)

    def close(self):
        try:
            super().close()
        finally:
            if self._session_lock is not None:
                self._session_lock.__exit__(None, None, None)
                self._session_lock = None

    def _check_identity(self, record):
        if record.get('account_hash') != self._account_hash():
            raise ProbeError('Session account mismatch or legacy unbound metadata; nothing resumed/deleted.')

    def _check_thread(self, thread, thread_id):
        if (not isinstance(thread, dict) or thread.get('id') != thread_id
                or thread.get('cwd') != self.cwd or thread.get('ephemeral') is not False
                or thread.get('modelProvider') != 'openai'
                or not isinstance(thread.get('status'), dict)
                or thread['status'].get('type') not in ('idle', 'notLoaded')):
            raise ProbeError('Thread identity/project/state is unsafe or unknown; no turn started.')

    def open_session(self, session_id):
        import uuid
        if self.start_pending or self.turn_id or self._rpcs or self._approvals:
            raise ProbeError('Current turn outcome is not settled.')
        if self.record is not None and self.record['id'] == session_id:
            raise ProbeError('Session is already open.')
        self._fresh_account(require_usage=False)
        catalog = read_models(self)
        select_model(catalog, self.selection['model'], self.selection['effort'])
        lock = self.store._lock(session_id)
        lock.__enter__()
        try:
            record = self.store.read(session_id)
            self._check_identity(record)
            if record.get('workflow') is not None:
                raise ProbeError('Saved workflow requires its controller; manual chat cannot resume it.')
            if record['deletion_state'] != 'none' or not record['thread_id']:
                raise ProbeError('Session has no resumable thread or has a pending deletion.')
            tid = record['thread_id']
            self._check_thread(self.request('thread/read', {'threadId': tid, 'includeTurns': False}).get('thread'), tid)
            history = self.request('thread/turns/list', {'threadId': tid, 'limit': 1,
                'sortDirection': 'desc', 'itemsView': 'summary'}).get('data')
            if not isinstance(history, list) or len(history) > 1:
                raise ProbeError('Cannot reconcile previous turn.')
            if history:
                turn = history[0]
                if (not isinstance(turn, dict) or not isinstance(turn.get('id'), str)
                        or turn.get('status') not in ('completed', 'failed', 'interrupted')):
                    raise ProbeError('Previous turn is active or unknown; inspect Codex before resuming.')
            result = self.request('thread/resume', dict(self._thread_options(), threadId=tid, excludeTurns=True))
            self._check_thread(result.get('thread'), tid)
            if not native_permissions_confirmed(result):
                raise ProbeError('Resumed permissions were not confirmed; no turn started.')
        except BaseException:
            lock.__exit__(None, None, None)
            raise
        if self._session_lock is not None:
            self._session_lock.__exit__(None, None, None)
        self._session_lock, self.record = lock, record
        self.thread_id, self.catalog = tid, catalog
        # An interrupted client cannot prove tool outcomes from a terminal turn alone.
        uncertain = record['state'] in ('RUNNING', 'AWAITING_TOOL_APPROVAL', 'CHECKING') or (
            record['state'] == 'PAUSED' and record['pause_reason'] == 'outcome_unknown')
        self.recovery_token = uuid.uuid4().hex if uncertain else None
        self.checkpoint(state='PAUSED' if uncertain else 'UNVERIFIED',
            pause_reason='outcome_unknown' if uncertain else None, mode='manual', permission_profile='read_only',
            summary='Resume checked; latest turn: ' + (history[0]['status'] if history else 'none'))
        if self.shell is not None:
            self.shell.catalog = catalog
            self.shell.session_id = record['id']
            self.shell.pending = self.shell.route = self.shell.approvals = None
            self.shell.write('เปิด session: ' + record['id'] + ' · ' + record['summary'])
            if uncertain:
                self.shell.write('ผลเครื่องมือเดิมยังไม่ทราบ ตรวจไฟล์/process ใน Codex ก่อน แล้วใช้ /acknowledge '
                                 + self.recovery_token + ' เพื่ออนุญาตข้อความใหม่; ไม่ replay งานเดิม')

    @contextmanager
    def _target_record(self, session_id):
        if self.record is not None and session_id == self.record['id']:
            yield self.record
        else:
            with self.store._lock(session_id):
                yield self.store.read(session_id)

    def _deletion_tree(self, record):
        """Preview every persisted root and its server-side cascade."""
        cleanup = self._recheck_cleanup_receipts(record)
        if record['deletion_state'] == 'remote_deleted' and (
                'recheck_cleanup' in record or cleanup is None):
            return []
        cleanup = cleanup or {}
        if cleanup.get('pending') is not None:
            raise ProbeError('Previous native deletion is unconfirmed; inspect Codex before proceeding.')
        roots = set(session_native_roots(record)) - set(cleanup.get('deleted', []))
        if not roots:
            return []
        threads = {}
        for archived in (False, True):
            cursor, seen = None, set()
            for _ in range(100):
                page = self.request('thread/list', {'archived': archived, 'cursor': cursor, 'limit': 100,
                    'sourceKinds': THREAD_SOURCE_KINDS})
                rows = page.get('data')
                if not isinstance(rows, list):
                    raise ProbeError('Cannot enumerate deletion scope.')
                for row in rows:
                    if not isinstance(row, dict) or not isinstance(row.get('id'), str):
                        raise ProbeError('Invalid deletion scope metadata.')
                    source = row.get('source')
                    agent = source.get('subAgent') if isinstance(source, dict) else None
                    if isinstance(agent, dict) and 'thread_spawn' in agent:
                        spawn = agent['thread_spawn']
                        parent = spawn.get('parent_thread_id') if isinstance(spawn, dict) else None
                        if (not isinstance(parent, str) or not parent
                                or row.get('parentThreadId') not in (None, parent)):
                            raise ProbeError('Cannot resolve spawned ancestry; nothing deleted.')
                        row = dict(row, parentThreadId=parent)
                    tid = row['id']
                    if tid in threads and any(threads[tid].get(key) != row.get(key)
                            for key in ('parentThreadId', 'cwd', 'ephemeral', 'modelProvider', 'status')):
                        raise ProbeError('Conflicting native thread listings; nothing deleted.')
                    threads[tid] = row
                cursor = page.get('nextCursor')
                if cursor is None:
                    break
                if not isinstance(cursor, str) or not cursor or cursor in seen:
                    raise ProbeError('Invalid deletion scope pagination.')
                seen.add(cursor)
            else:
                raise ProbeError('Deletion scope exceeds scan limit; nothing deleted.')
        children = {}
        for tid, row in threads.items():
            parent = row.get('parentThreadId')
            if parent is not None:
                if not isinstance(parent, str) or not parent:
                    raise ProbeError('Invalid native thread ancestry; nothing deleted.')
                children.setdefault(parent, []).append(tid)
        tree = []
        for root_id in sorted(roots):
            root = self.request('thread/read', {'threadId': root_id, 'includeTurns': False}).get('thread')
            self._check_thread(root, root_id)
            if record.get('workflow', {}).get('rechecks'):
                history = self.request('thread/turns/list', {'threadId': root_id, 'limit': 1,
                    'sortDirection': 'desc', 'itemsView': 'summary'}).get('data')
                if (not isinstance(history, list) or len(history) > 1
                        or any(not isinstance(turn, dict)
                               or turn.get('status') not in ('completed', 'failed', 'interrupted')
                               for turn in history)):
                    raise ProbeError('Latest native turn is active or unknown; nothing deleted.')
            selected = {root_id}
            pending = [root_id]
            while pending:
                for child in children.get(pending.pop(), []):
                    if child in selected:
                        raise ProbeError('Cyclic native thread ancestry; nothing deleted.')
                    selected.add(child)
                    pending.append(child)
            if selected & roots != {root_id}:
                raise ProbeError('Native deletion roots overlap; nothing deleted.')
            for tid in sorted(selected):
                row = threads.get(tid, root)
                self._check_thread(row, tid)
                tree.append({'thread_id': tid, 'project': row['cwd'], 'delete_root': root_id})
        selected = {row['thread_id'] for row in tree}
        # Other ModelMate records need their own writer locks and deletion receipts.
        for saved in self.store.list_sessions():
            if saved['id'] != record['id'] and selected.intersection(session_native_roots(saved, strict=False)):
                raise ProbeError('A thread in scope belongs to another ModelMate session.')
        return tree

    @staticmethod
    def _recheck_cleanup_receipts(record):
        if 'recheck_cleanup' in record:
            return record['recheck_cleanup']
        if record.get('workflow', {}).get('rechecks'):
            # Older versions could acknowledge the work root before local removal refused.
            deleted = [record['thread_id']] if record['deletion_state'] == 'remote_deleted' else []
            return {'deleted': deleted, 'pending': None}
        return None

    def _confirm_session_deletion(self, record, tree):
        if tree:
            cleanup = self._recheck_cleanup_receipts(record)
            record.update(deletion_state='requested', state='PAUSED', pause_reason='deletion_pending')
            if cleanup is not None:
                record.update(version=4, recheck_cleanup=cleanup)
            self.store.save(record)
            roots = {row['delete_root'] for row in tree}
            # Keep the work thread available until the independent recheck roots are acknowledged.
            for root in sorted(roots, key=lambda tid: (tid == record['thread_id'], tid)):
                if cleanup is not None:
                    self._fresh_account(require_usage=False)
                    self._check_identity(record)
                    current = self._deletion_tree(record)
                    remaining = roots - set(cleanup['deleted'])
                    if current != [row for row in tree if row['delete_root'] in remaining]:
                        raise ProbeError('Deletion scope changed; request a new preview.')
                    cleanup['pending'] = root
                    self.store.save(record)
                self.request('thread/delete', {'threadId': root})
                if cleanup is not None:
                    receipt = {'deleted': sorted(cleanup['deleted'] + [root]), 'pending': None}
                    self.store.save(dict(record, recheck_cleanup=receipt))
                    record['recheck_cleanup'] = cleanup = receipt
        if record['deletion_state'] != 'remote_deleted' and (tree or 'recheck_cleanup' in record):
            self.store.save(dict(record, deletion_state='remote_deleted'))
            record['deletion_state'] = 'remote_deleted'
        self.store.remove(record['id'])

    def session_command(self, command, values):
        import uuid
        try:
            if command == '/cancel':
                self.delete_proposal = None
                return
            if self._rpcs or self.turn_id or self.start_pending:
                raise ProbeError('Wait for pending backend requests before managing sessions.')
            if command == '/sessions':
                self.delete_proposal = None
                if not values:
                    for record in self.store.list_sessions():
                        self.shell.write(json.dumps({k: record[k] for k in ('id', 'title', 'state', 'updated_at')},
                                                    ensure_ascii=True))
                    return
                if len(values) != 1:
                    raise ProbeError('Use /sessions [ID].')
                self.open_session(values[0])
                return
            if command == '/acknowledge':
                if len(values) != 1 or self.recovery_token is None or values[0] != self.recovery_token:
                    raise ProbeError('Invalid or stale recovery token.')
                self._fresh_account()
                self._check_thread(self.request('thread/read', {'threadId': self.thread_id,
                    'includeTurns': False}).get('thread'), self.thread_id)
                self.checkpoint(state='UNVERIFIED', pause_reason=None,
                                summary='User acknowledged unknown prior outcome; no replay performed.')
                self.recovery_token = None
                self.shell.write('อนุญาตข้อความใหม่แล้ว; งานเดิมยังไม่ถือว่าผ่านเกณฑ์')
                return
            if command == '/delete':
                self.delete_proposal = None
                if len(values) > 1:
                    raise ProbeError('Use /delete [ID].')
                sid = values[0] if values else self.record['id']
                self._fresh_account(require_usage=False)
                with self._target_record(sid) as record:
                    self._check_identity(record)
                    tree = self._deletion_tree(record)
                    token = uuid.uuid4().hex
                    self.delete_proposal = {'token': token, 'record': dict(record), 'tree': tree}
                    self.shell.write(json.dumps({'delete_session': sid, 'title': record['title'],
                        'threads_including_descendants': tree, 'work_files_deleted': False}, ensure_ascii=True))
                    self.shell.write('ลบประวัติ Codex และ metadata; ไม่ย้อนการแก้ไฟล์ '
                                     'และไม่รับรองการลบข้อมูลทั้งหมดฝั่งบริการ · /confirm-delete ' + token)
                return
            proposal, self.delete_proposal = self.delete_proposal, None
            if len(values) != 1 or proposal is None or values[0] != proposal['token']:
                raise ProbeError('Invalid or stale deletion token.')
            self._fresh_account(require_usage=False)
            sid = proposal['record']['id']
            with self._target_record(sid) as record:
                self._check_identity(record)
                if record != proposal['record'] or self._deletion_tree(record) != proposal['tree']:
                    raise ProbeError('Deletion scope changed; request a new preview.')
                self._confirm_session_deletion(record, proposal['tree'])
            self.shell.write('ลบ session ตามขอบเขตที่ยืนยันแล้ว: ' + sid)
            if self.record is not None and sid == self.record['id']:
                self.record = None
                self.shell.closed = True
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            self.shell.write('Session operation paused: ' + (str(exc) if isinstance(exc, ProbeError)
                                                           else diagnostic_code(exc)))

    def _async(self, method, params):
        if method not in ('turn/start', 'turn/steer', 'turn/interrupt') or len(self._rpcs) >= 8:
            raise ProbeError('Unsupported or overloaded live request.')
        self.request_id += 1
        self._rpcs[self.request_id] = (method, time.monotonic() + self.timeout)
        self.send({'id': self.request_id, 'method': method, 'params': params})

    def action(self, action):
        kind = action['action']
        if kind == 'submit':
            self.delete_proposal = None
            if self.recovery_token is not None or (self.record is not None
                                                   and self.record['deletion_state'] != 'none'):
                self.shell.active = False
                self.shell.write('Session พักอยู่: ตรวจ outcome เดิมหรือจัดการ deletion ก่อนส่งข้อความใหม่')
                return
            if self.start_pending or self.turn_id:
                raise ProbeError('Previous turn outcome unknown; cannot start another.')
            if self._rpcs:
                self.shell.active = False
                self.shell.write('ยังรอ RPC เดิม กรุณาส่งงานใหม่อีกครั้งเมื่อคำขอเดิมจบ')
                return
            self.phase = 'catalog_preflight'
            try:
                self.catalog = read_models(self)
                self.shell.catalog = self.catalog
                selection = action.get('selection') or self.selection
                selected = select_model(self.catalog, selection['model'], selection['effort'])
            except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                self.shell.active = False
                self.checkpoint(state='PAUSED', pause_reason='catalog_unavailable')
                self.shell.write('พักก่อนส่ง prompt [catalog_preflight]: ' + diagnostic_code(exc)
                                 + '; ยังไม่เริ่ม turn ใหม่ ใช้ /model หรือส่งข้อความอีกครั้งเมื่อพร้อม')
                return
            if selected['effort'] == 'ultra':
                self.shell.active = False
                self.shell.write('ยังไม่เปิด automatic delegation; เลือก effort อื่น')
                return
            self.phase = 'quota_preflight'
            self.quota_status = refresh_quota(self, self.account_id)
            self.shell.quota_status = {k: self.quota_status[k] for k in ('state', 'reason', 'checked_at')}
            if self.quota_status['state'] != 'allow':
                self.shell.active = False
                self.checkpoint(state='PAUSED', pause_reason=self.quota_status['reason'])
                self.shell.write('พักงาน: ' + self.quota_status['reason'])
                return
            self.account_id = self.quota_status['account_id']
            self.selection = selected
            self._streamed.clear()
            self._previews.clear()
            self._finished.clear()
            self.phase = 'starting_turn'
            changes = {'state': 'RUNNING', 'pause_reason': None, 'turn_id': None}
            if self.record is not None and self.record['goal'] == 'New manual chat':
                changes.update(goal=action['text'][:4096], title=action['text'][:80])
            self.checkpoint(**changes)
            self.start_pending = True
            self._async('turn/start', {'threadId': self.thread_id, 'model': selected['model'],
                                      'effort': selected['effort'],
                                      'input': [{'type': 'text', 'text': action['text']}]})
        elif kind == 'steer':
            self.delete_proposal = None
            if self.turn_id is None or self.start_pending:
                self.shell.write('ยังรอ turn ID; กรุณาส่งข้อความเพิ่มหลังเริ่มตอบ')
                return
            self._async('turn/steer', {'threadId': self.thread_id, 'expectedTurnId': self.turn_id,
                                      'input': [{'type': 'text', 'text': action['text']}]})
        elif kind == 'cancel':
            for token in list(self._approvals):
                self._answer_tool(token, 'decline')
            if self.turn_id:
                self._async('turn/interrupt', {'threadId': self.thread_id, 'turnId': self.turn_id})
            elif self.start_pending:
                self.cancel_after_start = True
            elif self.shell.active:
                self.shell.event({'type': 'stopped'})
        elif kind == 'tool_decision':
            self._answer_tool(action['token'], action['choice'])
        else:
            raise ProbeError('Unsupported live action.')

    def _answer_tool(self, token, choice):
        request = self._approvals.get(token)
        if (request is None or choice not in ('approve', 'decline', 'pause')
                or request['turn_id'] != self.turn_id):
            raise ProbeError('Stale or invalid tool approval.')
        self._approvals.pop(token)
        self.checkpoint(state='RUNNING', pause_reason=None)
        self.send({'id': request['id'], 'result': {
            'decision': 'accept' if choice == 'approve' else 'decline'}})

    def handle_event(self, message):
        import uuid
        if self.shell is None:
            return super().handle_event(message)
        method, params = message['method'], message.get('params', {})
        if params.get('threadId') != self.thread_id:
            if 'id' in message:
                raise ProbeError('Request from unrelated thread; nothing approved.')
            return
        if 'id' in message:
            if (method not in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval')
                    or not self.turn_id or params.get('turnId') != self.turn_id
                    or not isinstance(params.get('itemId'), str) or not params['itemId']):
                raise ProbeError('Unsupported or stale server request; nothing approved.')
            if self.shell.stopping:
                self.send({'id': message['id'], 'result': {'decision': 'decline'}})
                return
            if self._approvals or self.shell.pending:
                # Never replace a visible approval with a second pending action.
                self.send({'id': message['id'], 'result': {'decision': 'decline'}})
                self.shell.write('ปฏิเสธคำขอซ้อนระหว่างรออนุมัติ')
                return
            if method == 'item/commandExecution/requestApproval':
                command, cwd = params.get('command'), params.get('cwd')
                if not isinstance(command, str) or not command or not isinstance(cwd, str):
                    raise ProbeError('Cannot display the exact command; nothing approved.')
                preview = json.dumps({'command': command, 'cwd': cwd, 'reason': params.get('reason')}, ensure_ascii=True)
            else:
                preview = self._previews.get(params['itemId'])
                if preview is None:
                    self.send({'id': message['id'], 'result': {'decision': 'decline'}})
                    self.shell.write('ปฏิเสธ patch เพราะไม่มี diff ให้ตรวจ')
                    return
            if len(preview.encode('utf-8')) > 65536:
                self.send({'id': message['id'], 'result': {'decision': 'decline'}})
                self.shell.write('ปฏิเสธคำขอที่ใหญ่เกินแสดงอย่างครบถ้วน')
                return
            token = uuid.uuid4().hex
            self.checkpoint(state='AWAITING_TOOL_APPROVAL')
            self._approvals[token] = {'id': message['id'], 'turn_id': self.turn_id}
            self.shell.event({'type': 'tool_approval', 'token': token, 'preview': preview})
            return
        if method == 'turn/started':
            turn = params.get('turn', {})
            tid = turn.get('id')
            if not isinstance(tid, str) or not tid or (self.turn_id and self.turn_id != tid):
                raise ProbeError('Invalid active turn metadata.')
            self.turn_id = tid
            self.checkpoint(turn_id=tid)
            self.phase = 'running_turn'
            if self.cancel_after_start:
                self.cancel_after_start = False
                self._async('turn/interrupt', {'threadId': self.thread_id, 'turnId': tid})
            return
        if params.get('turnId') != self.turn_id and method != 'turn/completed':
            return
        if method == 'item/started':
            item = params.get('item', {})
            if item.get('type') == 'fileChange' and isinstance(item.get('id'), str):
                changes = item.get('changes')
                if isinstance(changes, list) and changes:
                    preview = json.dumps(changes, ensure_ascii=True)
                    if len(preview.encode('utf-8')) <= 65536:
                        self._previews[item['id']] = preview
                    else:
                        self._previews.pop(item['id'], None)
                    if len(self._previews) > 100:
                        raise ProbeError('Too many pending file changes.')
        elif method == 'item/agentMessage/delta':
            delta, item_id = params.get('delta'), params.get('itemId')
            if not isinstance(delta, str) or not isinstance(item_id, str):
                raise ProbeError('Invalid text delta.')
            self._streamed.add(item_id)
            if len(self._streamed) > 10000:
                raise ProbeError('Too many streamed items.')
            self.shell.output.write(terminal_text(delta))
            self.shell.output.flush()
        elif method == 'item/completed':
            item = params.get('item', {})
            if item.get('type') == 'agentMessage' and item.get('id') not in self._streamed:
                if not isinstance(item.get('text'), str):
                    raise ProbeError('Invalid assistant text.')
                self.shell.write(item['text'])
        elif method == 'turn/completed':
            turn = params.get('turn', {})
            if turn.get('id') != self.turn_id:
                return
            self._finished.add(self.turn_id)
            self.turn_id = None
            self.start_pending = False
            self._approvals.clear()
            status = turn.get('status')
            if status not in ('completed', 'failed', 'interrupted'):
                raise ProbeError('Invalid terminal status.')
            self.checkpoint(state={'completed': 'UNVERIFIED', 'failed': 'FAILED', 'interrupted': 'PAUSED'}[status],
                            pause_reason='user_pause' if status == 'interrupted' else None,
                            summary='Backend turn ' + status + '; task checks are separate.')
            self.shell.write('')
            if status == 'failed':
                self.shell.write('Turn ล้มเหลว; ไม่ retry อัตโนมัติ')
            self.phase = 'idle'
            self.shell.event({'type': 'stopped' if status == 'interrupted' else 'completed'})

    def drain(self):
        while True:
            message = self.pop_message()
            if message is None:
                break
            if 'method' in message:
                self.handle_event(message)
                continue
            pending = self._rpcs.pop(message['id'], None)
            if pending is None:
                raise ProbeError('Unexpected live RPC response.')
            if 'error' in message:
                raise ProbeError('Live request failed; no automatic retry; inspect turn state.')
            if not isinstance(message.get('result'), dict):
                raise ProbeError('Invalid live RPC result.')
            if pending[0] == 'turn/start':
                tid = message['result'].get('turn', {}).get('id')
                if not isinstance(tid, str) or not tid:
                    raise ProbeError('Missing turn ID; outcome unknown.')
                self.start_pending = False
                if tid not in self._finished:
                    if self.turn_id and tid != self.turn_id:
                        raise ProbeError('Conflicting live turn ID.')
                    self.turn_id = tid
                    self.checkpoint(turn_id=tid)
                    if self.cancel_after_start:
                        self.cancel_after_start = False
                        self._async('turn/interrupt', {'threadId': self.thread_id, 'turnId': tid})
        if self.stdout_closed:
            raise ProbeError('Codex disconnected; active turn outcome may be unknown.')

    def tick(self):
        if any(time.monotonic() >= deadline for _, deadline in self._rpcs.values()):
            raise ProbeError('Live RPC timed out; outcome unknown; do not replay automatically.')




def native_token_snapshot(value):
    if not isinstance(value, dict):
        return None
    fields = ('inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningOutputTokens', 'totalTokens')
    result = {}
    for key in ('total', 'last'):
        row = value.get(key)
        if not isinstance(row, dict) or any(type(row.get(k)) is not int or row[k] < 0 for k in fields):
            return None
        result[key] = {k: row[k] for k in fields}
        cache_write = row.get('cacheWriteInputTokens')
        if type(cache_write) is int and cache_write >= 0:
            result[key]['cacheWriteInputTokens'] = cache_write
    return result


def quota_windows(quota):
    buckets = quota.get('rateLimitsByLimitId')
    if buckets is None:
        bucket = quota.get('rateLimits')
        identity = bucket.get('limitId') if isinstance(bucket, dict) else None
        buckets = {identity or 'default': bucket} if isinstance(identity or 'default', str) else {}
    windows = {}
    if not isinstance(buckets, dict):
        return windows
    for bucket, data in buckets.items():
        if not isinstance(bucket, str) or not bucket or not isinstance(data, dict):
            continue
        for key in ('primary', 'secondary'):
            row = data.get(key)
            if not isinstance(row, dict):
                continue
            used, duration, reset = (row.get(k) for k in ('usedPercent', 'windowDurationMins', 'resetsAt'))
            if (type(used) in (int, float) and 0 <= used <= 100
                    and type(duration) is int and duration > 0 and type(reset) is int and reset > 0):
                windows[bucket, key] = (used, duration, reset)
    return windows


def quota_window_changes(before, after, sampled_at):
    changes = []
    for (bucket, window), (used, duration, reset) in sorted(before.items()):
        current = after.get((bucket, window))
        if current is None or current[1:] != (duration, reset) or reset <= sampled_at or current[0] < used:
            continue
        changes.append({'bucket': terminal_text(bucket), 'window': window, 'windowDurationMins': duration,
                        'resetsAt': reset, 'beforePercent': used, 'afterPercent': current[0],
                        'deltaPercentagePoints': round(current[0] - used, 6)})
    return changes or None


class NativeWorkflowConnection(Connection):
    """Opt-in transport for an explicit host plan; no classifier or native approval acceptance."""
    allowed_methods = Connection.allowed_methods | {'thread/start', 'thread/read', 'thread/resume', 'thread/turns/list', 'turn/start', 'turn/interrupt'}

    def __init__(self, command, timeout=15):
        super().__init__(command, timeout)
        self.host = None
        self.thread_id = None
        self.account_id = None
        self._events = []
        self._event_bytes = 0
        self._sent_attempts = set()
        self._displayed = set()
        self.store = self.session_id = self._attachment = self.controller = None
        self._closed = False
        self.measure_quota = False
        self._quota_first = self._quota_ready = None
        self._measured_turn = self._latest_usage = None
        self._work_turn_measurements = []

    def workflow_measurements(self):
        changes = None
        if self._quota_first:
            try:
                account = self.request('account/read', {'refreshToken': False}).get('account')
                if isinstance(account, dict) and account.get('type') == 'chatgpt':
                    quota = self.request('account/rateLimits/read')
                    if quota.get('accountId') == self.account_id:
                        changes = quota_window_changes(self._quota_first, quota_windows(quota), time.time())
            except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError):
                pass
        turns = self._work_turn_measurements
        elapsed = [turn['elapsedSeconds'] for turn in turns if turn['elapsedSeconds'] is not None]
        return {'tokenUsage': self._latest_usage,
                'tokenUsageScope': 'last_observed_work_thread_update' if self._latest_usage else None,
                'quotaWindowChanges': changes,
                'turnElapsedSeconds': round(sum(elapsed), 3) if elapsed else None,
                'timedTurns': len(elapsed),
                'workTurnMeasurements': [dict(turn, elapsedSeconds=round(turn['elapsedSeconds'], 3))
                    if turn['elapsedSeconds'] is not None else dict(turn) for turn in turns]}

    def connect(self, controller, cwd, role_policy=None, *, store=None):
        if self.host is not None or self.thread_id is not None:
            raise ProbeError('Workflow transport is already connected.')
        if not isinstance(controller, WorkflowController):
            raise ProbeError('Workflow transport requires an explicit validated controller.')
        state = controller.snapshot()
        if state['active_attempt'] is not None or state['state'] != 'READY':
            raise ProbeError('Native transport supports a new READY workflow only; recovery is not enabled.')
        catalog = inspect(self)['models']
        baseline = controller._approvals.baseline
        select_model(catalog, baseline['model'], baseline['effort'])
        self.cwd = os.path.realpath(cwd)
        self.role_policy = copy.deepcopy(role_policy)
        self.account_id = controller._account_id
        fresh = self.preflight()
        if routing_decision(controller._raw, fresh['catalog'], self.role_policy)['state'] != 'ready_for_approval':
            raise ProbeError('Workflow model or effort is unavailable in the current catalog.')
        if store is not None:
            if store.project != self.cwd:
                raise ProbeError('Workflow project mismatch.')
            import hashlib
            self.store = store
            self.session_id = store.create(controller.snapshot()['plan']['goal'],
                account_hash=hashlib.sha256(self.account_id.encode()).hexdigest())['id']
            self._attach(controller, fresh)
            record = store.read(self.session_id)
            record['summary'] = 'Native thread start pending; no inference attempted.'
            store.save(record)
        result = self.request('thread/start', dict(native_thread_options(baseline, self.cwd), ephemeral=store is None))
        thread = result.get('thread')
        if (not isinstance(thread, dict) or not isinstance(thread.get('id'), str) or not thread['id']
                or thread.get('cwd') != self.cwd or thread.get('modelProvider') != 'openai'
                or thread.get('ephemeral') is not (store is None)
                or not native_permissions_confirmed(result)):
            raise ProbeError('Workflow thread permissions/identity were not confirmed; no turn started.')
        self.thread_id = thread['id']
        if store is not None:
            record = store.read(self.session_id)
            record['thread_id'] = self.thread_id
            record['summary'] = 'Durable native workflow thread confirmed.'
            store.save(record)
        self.controller = controller
        self.host = WorkflowHost(controller, self.preflight, self.dispatch, self.interrupt)
        return self.host

    def _attach(self, controller, fresh, *, persist_initial=True):
        attachment = self.store.workflow(self.session_id, fresh['quota'], fresh['checked_at'],
                                         fresh['catalog'], self.role_policy, controller=controller,
                                         persist_initial=persist_initial)
        restored = attachment.__enter__()
        self.controller = restored
        self._attachment = attachment
        return restored

    def resume(self, store, session_id, cwd, role_policy, expected_plan):
        if self.host is not None or self.thread_id is not None or self._attachment is not None:
            raise ProbeError('Workflow transport is already connected.')
        inspect(self)
        self.cwd = os.path.realpath(cwd)
        if store.project != self.cwd:
            raise ProbeError('Workflow project mismatch.')
        self.role_policy = copy.deepcopy(role_policy)
        fresh = self.preflight()
        self.store, self.session_id = store, session_id
        controller = self._attach(None, fresh, persist_initial=False)
        if any(op['status'] in ('pending', 'unknown') for op in controller.recheck_operations()):
            raise ProbeError('Unresolved recheck retained; inspect --show-workflow before native recovery. No replay.')
        record = store.read(session_id)
        if (record['workflow']['plan'] != expected_plan or record['deletion_state'] != 'none'
                or not record['thread_id']):
            raise ProbeError('Workflow changed, is deleting or has unknown thread identity; nothing replayed.')
        self.account_id = controller._account_id
        tid = record['thread_id']
        LiveChatConnection._check_thread(self, self.request('thread/read',
            {'threadId': tid, 'includeTurns': False}).get('thread'), tid)
        history = self.request('thread/turns/list', {'threadId': tid, 'limit': 1,
            'sortDirection': 'desc', 'itemsView': 'summary'}).get('data')
        if not isinstance(history, list) or len(history) > 1:
            raise ProbeError('Cannot reconcile native workflow history.')
        latest = history[0] if history else None
        active = controller.snapshot()['active_attempt']
        if latest is not None:
            if (not isinstance(latest, dict) or latest.get('id') != record['turn_id']
                    or latest.get('status') not in ('completed', 'failed', 'interrupted')):
                raise ProbeError('Native turn is active or does not match checkpoint; no replay.')
        elif record['turn_id'] is not None or active is not None:
            raise ProbeError('Native turn identity is unknown; no replay.')
        result = self.request('thread/resume', dict(native_thread_options(controller._approvals.baseline, self.cwd),
                                                   threadId=tid, excludeTurns=True))
        LiveChatConnection._check_thread(self, result.get('thread'), tid)
        if not native_permissions_confirmed(result):
            raise ProbeError('Resumed workflow permissions were not confirmed.')
        host = WorkflowHost(controller, self.preflight, self.dispatch, self.interrupt)
        if latest is not None:
            host._seen.add((tid, latest['id']))
        if active is not None:
            host.reconcile({'thread_id': tid, 'turn_id': latest['id']}, latest['status'])
        if active is None or active['status'] == 'completed':
            # A previously running attempt was already saved by reconciliation.
            store.save_workflow(session_id, controller)
        self.thread_id, self.host = tid, host
        return host

    def open_recheck(self, evidence_id, spec, selection, on_change):
        if (self._closed or self.store is None or self._attachment is None or self.host is None
                or self.controller is not self.host.controller
                or not isinstance(spec, dict) or set(spec) != {'command', 'cwd'}):
            raise ProbeError('Recheck requires the attached durable native workflow host.')
        record = self.store.read(self.session_id)
        if record['thread_id'] != self.thread_id or record['deletion_state'] != 'none':
            raise ProbeError('Parent native identity changed; no recheck started.')
        child = NativeRecheckConnection(self.process.args, self.timeout)
        try:
            child.start_recheck(self.controller, evidence_id, spec['command'], spec['cwd'], self.cwd,
                self.role_policy, selection, work_thread_id=self.thread_id, on_change=on_change)
            return child
        except BaseException:
            child.close()
            raise

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.host is not None:
                active = self.host.controller.snapshot()['active_attempt']
                if active is not None and active['status'] == 'running':
                    self.host.controller.pause('connection_lost')
        finally:
            try:
                super().close()
            finally:
                if self._attachment is not None:
                    self._attachment.__exit__(None, None, None)
                    self._attachment = None

    def preflight(self):
        checked_at = time.monotonic()
        account = self.request('account/read', {'refreshToken': False}).get('account')
        if not isinstance(account, dict) or account.get('type') != 'chatgpt':
            raise WorkflowPreflightPause('chatgpt_login_required')
        quota = self.request('account/rateLimits/read')
        decision = quota_decision(quota, checked_at, expected_account=self.account_id)
        if decision['state'] != 'allow':
            raise WorkflowPreflightPause(decision['reason'])
        try:
            catalog = read_models(self)
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise WorkflowPreflightPause('catalog_unavailable') from exc
        self.account_id = decision['account_id']
        if self.measure_quota and self._quota_first is None:
            self._quota_ready = quota_windows(quota)
        if self.host is not None:
            self.host.catalog = copy.deepcopy(catalog)
            self.host.role_policy = copy.deepcopy(self.role_policy)
        return dict(quota=quota, checked_at=checked_at, catalog=catalog, role_policy=self.role_policy)

    def dispatch(self, descriptor, *, client_message_id=None):
        state = self.host.controller.snapshot() if self.host is not None else None
        active = state['active_attempt'] if state is not None else None
        if (active is None or active['id'] != descriptor.get('attempt_id') or active['status'] != 'running'
                or descriptor.get('selection') != active['selection']):
            raise ProbeError('No controller-reserved workflow attempt; nothing dispatched.')
        if active['id'] in self._sent_attempts or any('id' in message for message in self._events):
            raise ProbeError('Attempt already sent or unresolved server request; no replay permitted.')
        selection = descriptor['selection']
        if selection['effort'] == 'ultra':
            raise ProbeError('Workflow delegation is disabled.')
        self._sent_attempts.add(active['id'])
        self._displayed.clear()
        verification = [dict(check=index + 1, **spec) for (step_id, index), spec in sorted(self.host._specs.items())
                        if step_id == active['step_id']]
        observed = {'step': state['step_index'] + 1, 'cycle': active['cycle'] + 1,
                    'attempt': active['number'], 'requestedSelection': dict(selection),
                    'terminalStatus': None, 'elapsedSeconds': None, 'lastReportedTokens': None,
                    'modelReroutes': []}
        self._work_turn_measurements.append(observed)
        self._measured_turn = {'id': None, 'started': time.monotonic(), 'observation': observed}
        if self.measure_quota and self._quota_first is None:
            self._quota_first = self._quota_ready
        params = {'threadId': self.thread_id, 'model': selection['model'],
            'effort': selection['effort'], 'input': [{'type': 'text', 'text': json.dumps({
                'goal': self.host.controller.snapshot()['plan']['goal'], 'step': descriptor['step'],
                'verification_commands': verification,
                'verification_instructions': 'After completing the step, use the native command tool to run each verification command exactly once in its specified cwd. Do not retry commands within this attempt. If execution is unavailable, report that limitation; do not claim a check passed.'}, ensure_ascii=False)}]}
        if client_message_id is not None:
            params['clientUserMessageId'] = client_message_id
        result = self.request('turn/start', params)
        turn = result.get('turn')
        if not isinstance(turn, dict) or not isinstance(turn.get('id'), str) or not turn['id']:
            raise ProbeError('Missing workflow turn identity; outcome unknown.')
        if (self.thread_id, turn['id']) in self.host._seen:
            raise ProbeError('Native workflow reused a prior turn ID; outcome unknown, no replay.')
        if self.store is not None:
            record = self.store.read(self.session_id)
            record['turn_id'] = turn['id']
            self.store.save(record)
        self._measured_turn['id'] = turn['id']
        return {'thread_id': self.thread_id, 'turn_id': turn['id']}

    def _observe_measurement(self, message):
        current = self._measured_turn
        params = message.get('params')
        if (current is None or current['id'] is None or not isinstance(params, dict)
                or params.get('threadId') != self.thread_id):
            return
        observed = current['observation']
        method = message['method']
        if method == 'thread/tokenUsage/updated' and params.get('turnId') == current['id']:
            snapshot = native_token_snapshot(params.get('tokenUsage'))
            if snapshot is not None:
                self._latest_usage = snapshot
                observed['lastReportedTokens'] = snapshot['last']
        elif method == 'model/rerouted' and params.get('turnId') == current['id']:
            previous, target = params.get('fromModel'), params.get('toModel')
            if (previous != target and all(isinstance(model, str) and 0 < len(model) <= 256
                                          and model.isascii() and model.isprintable() and not any(c.isspace() for c in model)
                                          for model in (previous, target))):
                reroute = {'fromModel': previous, 'toModel': target}
                if reroute not in observed['modelReroutes']:
                    observed['modelReroutes'].append(reroute)
        elif method == 'turn/completed' and observed['terminalStatus'] is None:
            turn = params.get('turn')
            if (isinstance(turn, dict) and turn.get('id') == current['id']
                    and turn.get('status') in ('completed', 'failed', 'interrupted')):
                observed['terminalStatus'] = turn['status']
                observed['elapsedSeconds'] = time.monotonic() - current['started']

    def interrupt(self, binding):
        if binding['thread_id'] != self.thread_id:
            raise ProbeError('Cannot interrupt a foreign workflow thread.')
        self.request('turn/interrupt', {'threadId': self.thread_id, 'turnId': binding['turn_id']})

    def handle_event(self, message):
        # RPCs can receive events before turn/start returns; bind first, then drain.
        size = len(json.dumps(message).encode())
        if len(self._events) >= 4096 or self._event_bytes + size > 4 * 1024 * 1024:
            raise ProbeError('Workflow event queue exceeded limit; outcome unknown.')
        self._events.append(message)
        self._event_bytes += size

    def _display_answer(self, message):
        binding = self.host._binding
        params = message.get('params', {})
        if (binding is None or self.host._terminal is not None
                or message.get('method') != 'item/completed'
                or params.get('threadId') != binding['thread_id']
                or params.get('turnId') != binding['turn_id']):
            return
        item = params.get('item')
        if not isinstance(item, dict) or item.get('type') != 'agentMessage':
            return
        item_id, text = item.get('id'), item.get('text')
        if (not isinstance(item_id, str) or not item_id or len(item_id) > 256
                or not isinstance(text, str) or len(text.encode()) > 4 * 1024 * 1024):
            raise ProbeError('Invalid workflow assistant text.')
        if item_id in self._displayed or self.host.on_change is None:
            return
        if len(self._displayed) >= 10000:
            raise ProbeError('Too many workflow assistant messages.')
        self._displayed.add(item_id)
        # Display completed text only: deltas never become evidence or duplicate the final answer.
        self.host.on_change({'type': 'text', 'text': text})

    def drain(self):
        while True:
            message = self.pop_message()
            if message is None:
                break
            if 'method' not in message:
                raise ProbeError('Unexpected workflow RPC response.')
            self.handle_event(message)
        while self._events:
            message = self._events.pop(0)
            self._event_bytes -= len(json.dumps(message).encode())
            if 'id' in message:
                if message['method'] in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
                    self.send({'id': message['id'], 'result': {'decision': 'decline'}})
                self.host.observe_native(message)
            else:
                self.host.observe_native(message)
                self._observe_measurement(message)
                self._display_answer(message)
        if self.stdout_closed:
            raise ProbeError('Workflow backend disconnected; no automatic replay.')

    def tick(self):
        self.host.tick()


class NativeRecheckConnection(NativeWorkflowConnection):
    """One explicitly consented verification turn; durable ownership stays with its parent."""
    allowed_methods = Connection.allowed_methods | {'thread/read', 'thread/start', 'turn/start', 'turn/interrupt'}

    def __init__(self, command, timeout=15):
        super().__init__(command, timeout)
        self.parent = self.operation_id = None
        self._started = self._tainted = self._cancel_requested = False
        self.on_change = None

    def operation(self):
        if self.parent is None or self.operation_id is None:
            return None
        operation = next(op for op in self.parent.recheck_operations() if op['id'] == self.operation_id)
        if self.parent._recheck_fault:
            operation['status'] = 'unknown'
        return operation

    def start_recheck(self, parent, evidence_id, command, cwd, project, role_policy, selection,
                      *, work_thread_id, on_change=None):
        """Caller must obtain consent for this exact evidence/spec/selection; no automatic retries."""
        if (self._started or not isinstance(parent, WorkflowController)
                or not isinstance(work_thread_id, str) or not work_thread_id.strip()
                or (on_change is not None and not callable(on_change))):
            raise ProbeError('Invalid or reused native recheck transport.')
        self._started = True
        self.cwd = os.path.realpath(project)
        self.role_policy = copy.deepcopy(role_policy)
        self.account_id = parent._account_id
        if self.account_id is None:
            raise ProbeError('Recheck requires an account-bound parent workflow.')
        inspect(self)
        fresh = self.preflight()
        LiveChatConnection._check_thread(self, self.request('thread/read',
            {'threadId': work_thread_id, 'includeTurns': False}).get('thread'), work_thread_id)
        self.parent, self.on_change = parent, on_change
        self._spec = {'command': command, 'cwd': cwd}
        operation = parent.reserve_recheck(evidence_id, command, cwd, selection,
            fresh['quota'], fresh['checked_at'], fresh['catalog'], self.role_policy)
        self.operation_id = operation['id']
        self._selection = copy.deepcopy(selection)
        try:
            result = self.request('thread/start', dict(native_thread_options(selection, self.cwd), ephemeral=False))
            thread = result.get('thread')
            if not isinstance(thread, dict) or not isinstance(thread.get('id'), str):
                raise ProbeError('Missing recheck thread identity; outcome unknown.')
            LiveChatConnection._check_thread(self, thread, thread['id'])
            if thread['id'] == work_thread_id or not native_permissions_confirmed(result):
                raise ProbeError('Recheck thread isolation/permissions were not confirmed.')
            self.thread_id = thread['id']
            parent.advance_recheck(self.operation_id, 'thread', thread_id=self.thread_id)
            source = workflow_saved_evidence(parent.export_checkpoint())[evidence_id]
            raw = json.dumps({'version': 1, 'goal': 'Revalidate one saved tool check', 'clarifications': [],
                'success_criteria': ['Observe the registered command result'], 'steps': [{
                    'kind': 'review', 'objective': 'Run the registered verification command once in its exact cwd. '
                        'Do not change files, use the network or retry. Report unavailable execution honestly.',
                    'role': 'standard', 'effort': 'low', 'risk': 'normal',
                    'reason': 'User explicitly requested a fresh check of saved evidence.',
                    'checks': [{'kind': source['kind'], 'criterion': 'Observe the registered command exit code'}]}]})
            # Reuse the command observer; only the parent ledger owns durable recheck state.
            self.controller = WorkflowController(raw, fresh['catalog'], self.role_policy, 'auto')
            self.host = WorkflowHost(self.controller, self.preflight, self.dispatch, self.interrupt)
            self.host.on_change = self._display_recheck_event
            self.host.configure_check(0, **self._spec)
            self.host({'action': 'next', 'task_id': self.controller.task_id})
            if self.host._binding is None:
                raise ProbeError('Recheck turn was not dispatched; outcome unverified.')
            return self.operation()
        except BaseException:
            self._mark_unknown()
            raise

    def _display_recheck_event(self, event):
        if self.on_change is not None and event.get('type') in ('text', 'progress'):
            self.on_change(copy.deepcopy(event))

    def dispatch(self, descriptor):
        import uuid

        operation = self.operation()
        expected = {(self.controller.snapshot()['steps'][0]['id'], 0): self._spec}
        if (operation is None or operation['phase'] != 'thread_bound' or operation['status'] != 'pending'
                or descriptor.get('selection') != operation['selection']
                or descriptor.get('selection') != self._selection
                or self.host._specs != expected
                or descriptor.get('step') != self.controller.snapshot()['plan']['steps'][0]
                or recheck_spec_digest(**self._spec) != operation['spec_digest']):
            raise ProbeError('Recheck no longer matches its durable reservation; no turn sent.')
        client_message_id = str(uuid.UUID(hex=self.operation_id))
        self.parent.advance_recheck(self.operation_id, 'turn_reserved', client_message_id=client_message_id)
        binding = super().dispatch(descriptor, client_message_id=client_message_id)
        self.parent.advance_recheck(self.operation_id, 'turn', turn_id=binding['turn_id'])
        return binding

    def _mark_unknown(self, *, invalidate_terminal=False):
        self._tainted = True
        operation = self.operation()
        if operation is None or operation['status'] == 'unknown':
            return
        if operation['status'] != 'pending' and not invalidate_terminal:
            return
        try:
            self.parent.advance_recheck(self.operation_id, 'finish', status='unknown', exit_code=None, item_id=None)
        except (Exception, KeyboardInterrupt):
            # A failed ledger write leaves the reservation unresolved and freezes its controller.
            self.parent._stale_evidence.add(operation['evidence_id'])

    def _finish_recheck(self):
        operation = self.operation()
        if operation is None or operation['status'] not in ('pending', 'unknown') or self.host._terminal is None:
            return
        status = self.host._terminal
        observed = self.host._observations.get(0, {})
        code = observed.get('exit_code') if status == 'completed' and not self._tainted and not self._cancel_requested else None
        self.parent.advance_recheck(self.operation_id, 'finish', status=status, exit_code=code,
                                    item_id=observed.get('item_id') if code is not None else None)
        if self.on_change is not None:
            self.on_change({'type': 'workflow_changed', 'task_id': self.parent.task_id})

    def drain(self):
        if self.host is None:
            raise ProbeError('Recheck has not started.')
        try:
            super().drain()
            self._finish_recheck()
        except BaseException:
            self._mark_unknown(invalidate_terminal=True)
            raise

    def cancel(self):
        if self.host is None or self.host._binding is None or self.host._terminal is not None:
            return
        self._cancel_requested = True
        try:
            self.host({'action': 'cancel', 'task_id': self.controller.task_id})
        except BaseException:
            self._mark_unknown()
            raise

    def tick(self):
        if self.host is not None:
            try:
                super().tick()
            except BaseException:
                self._mark_unknown(invalidate_terminal=True)
                raise

    def close(self):
        if self._closed:
            return
        try:
            self._mark_unknown()
        finally:
            super().close()


def unresolved_recheck(record):
    checkpoint = record.get('workflow')
    if not isinstance(checkpoint, dict):
        raise ProbeError('Session has no workflow checkpoint.')
    operations = validate_recheck_ledger(checkpoint.get('rechecks', []), workflow_saved_evidence(checkpoint))
    pending = [op for op in operations if op['status'] in ('pending', 'unknown')]
    if len(pending) > 1:
        raise ProbeError('Multiple unresolved rechecks; no native action attempted.')
    return pending[0] if pending else None


def correlated_turn_id(history, client_message_id):
    """A fresh probe thread must contain one complete turn and one matching user item."""
    turns = history.get('data')
    if not isinstance(turns, list) or len(turns) != 1 or history.get('nextCursor') is not None:
        return None
    turn = turns[0]
    if (not isinstance(turn, dict) or turn.get('itemsView') != 'full'
            or turn.get('status') not in ('completed', 'failed', 'interrupted') or not isinstance(turn.get('items'), list)
            or not isinstance(turn.get('id'), str) or not turn['id']):
        return None
    items = turn['items']
    if any(not isinstance(item, dict) for item in items):
        return None
    users = [item for item in items if item.get('type') == 'userMessage']
    if len(users) == 1 and users[0].get('clientId') == client_message_id:
        return turn['id']
    return None


class RecheckRecoveryConnection(Connection):
    """Metadata-only recovery; native interruption is the only permitted mutation."""
    allowed_methods = {'initialize', 'account/read', 'account/rateLimits/read',
                       'thread/read', 'thread/turns/list', 'turn/interrupt'}

    def __init__(self, command, timeout=15):
        super().__init__(command, timeout)
        self._initialized = False
        self._account_hash = self._poll_deadline = None

    def request(self, method, params=None):
        if method not in self.allowed_methods:
            return super().request(method, params)
        self.last_method = method
        previous = self.timeout
        try:
            if self._poll_deadline is not None:
                remaining = self._poll_deadline - time.monotonic()
                if remaining <= 0:
                    raise ProbeError('Recovery observation timed out; interruption is unconfirmed.')
                self.timeout = min(previous, remaining)
            return super().request(method, params)
        finally:
            self.timeout = previous

    def _account(self, record):
        import hashlib
        if not self._initialized:
            self.request('initialize', {'clientInfo': {'name': 'modelmate_recheck_recovery', 'version': '0.1.0'}})
            self.send({'method': 'initialized'})
            self._initialized = True
        account = self.request('account/read', {'refreshToken': False}).get('account')
        if not isinstance(account, dict) or account.get('type') != 'chatgpt':
            raise ProbeError('Recovery requires ChatGPT login.')
        checked_at = time.monotonic()
        quota = self.request('account/rateLimits/read')
        decision = quota_decision(quota, checked_at)
        if decision['state'] != 'allow' and not (decision['reason'] == 'quota_exhausted' and decision['account_id']):
            raise ProbeError('Recovery account/quota state unknown; no action attempted.')
        fingerprint = hashlib.sha256(decision['account_id'].encode()).hexdigest()
        if record.get('account_hash') != fingerprint or self._account_hash not in (None, fingerprint):
            raise ProbeError('Recovery account mismatch; no action attempted.')
        self._account_hash = fingerprint

    def inspect_recheck(self, store, session_id):
        if session_id not in store._locked_ids:
            raise ProbeError('Recovery requires the session writer lock.')
        record = store.read(session_id)
        if record['deletion_state'] != 'none':
            raise ProbeError('Session deletion is pending; recovery is unavailable.')
        operation = unresolved_recheck(record)
        if operation is None:
            return {'state': 'none'}
        report = {'state': 'unverified', 'operation_id': operation['id'],
                  'thread_id': operation['thread_id'], 'turn_id': operation['turn_id']}
        discover = operation['phase'] == 'turn_pending' and operation['client_message_id'] is not None
        if operation['phase'] != 'turn_bound' and not discover:
            return dict(report, reason='missing_native_binding')
        if operation['thread_id'] == record['thread_id']:
            raise ProbeError('Recheck points at the work thread; no native action attempted.')
        self._account(record)
        if discover:
            self._read_recovery_thread(store.project, operation['thread_id'])
            history = self.request('thread/turns/list', {'threadId': operation['thread_id'], 'limit': 2,
                'sortDirection': 'desc', 'itemsView': 'full'})
            turn_id = correlated_turn_id(history, operation['client_message_id'])
            if turn_id is None:
                return dict(report, reason='native_correlation_unconfirmed')
            observed = self.inspect_bound_turn(store.project, operation['thread_id'], turn_id, single_turn=True)
            if observed['state'] != 'terminal':
                return dict(report, reason='native_status_unconfirmed')
            return dict(report, **observed, turn_id=turn_id, client_message_id=operation['client_message_id'])
        return dict(report, **self.inspect_bound_turn(store.project, operation['thread_id'], operation['turn_id'],
                                                      single_turn=True))

    def _read_recovery_thread(self, project, thread_id):
        thread = self.request('thread/read', {'threadId': thread_id, 'includeTurns': False}).get('thread')
        if (not isinstance(thread, dict) or thread.get('id') != thread_id
                or thread.get('cwd') != project or thread.get('modelProvider') != 'openai'
                or thread.get('ephemeral') is not False or not isinstance(thread.get('status'), dict)
                or thread['status'].get('type') not in ('idle', 'notLoaded', 'active')):
            raise ProbeError('Recovery thread identity/project/provider/state is unsafe or unknown.')
        return thread

    def inspect_bound_turn(self, project, thread_id, turn_id, *, single_turn=False):
        thread = self._read_recovery_thread(project, thread_id)
        history = self.request('thread/turns/list', {'threadId': thread_id, 'limit': 1,
            'sortDirection': 'desc', 'itemsView': 'summary'})
        turns = history.get('data')
        cursor = history.get('nextCursor')
        if (not isinstance(turns, list) or len(turns) != 1
                or (cursor is not None and (single_turn or not isinstance(cursor, str) or not cursor))
                or not isinstance(turns[0], dict) or turns[0].get('id') != turn_id):
            return {'state': 'unverified', 'reason': 'native_history_mismatch'}
        status, thread_status = turns[0].get('status'), thread['status']['type']
        if status in ('completed', 'failed', 'interrupted') and thread_status in ('idle', 'notLoaded'):
            return {'state': 'terminal', 'status': status}
        if status == 'inProgress' and thread_status == 'active':
            return {'state': 'active'}
        return {'state': 'unverified', 'reason': 'native_status_unconfirmed'}

    def interrupt_recheck(self, store, session_id, expected, timeout=5):
        if (not isinstance(expected, dict) or expected.get('state') != 'active'
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
            raise ProbeError('Interruption requires an explicitly selected active recovery binding.')
        current = self.inspect_recheck(store, session_id)
        if any(current.get(key) != expected.get(key) for key in ('operation_id', 'thread_id', 'turn_id')):
            raise ProbeError('Recovery target changed; inspect again before interruption.')
        if current['state'] != 'active':
            return current
        self.request('turn/interrupt', {'threadId': current['thread_id'], 'turnId': current['turn_id']})
        self._poll_deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < self._poll_deadline:
                report = self.inspect_recheck(store, session_id)
                if any(report.get(key) != expected.get(key) for key in ('operation_id', 'thread_id', 'turn_id')):
                    return dict(current, state='unverified', reason='recovery_target_changed')
                if report['state'] != 'active':
                    return report
                time.sleep(min(.1, max(0, self._poll_deadline - time.monotonic())))
        except (ProbeError, OSError):
            pass
        finally:
            self._poll_deadline = None
        return dict(current, state='unverified', reason='interruption_unconfirmed')


SESSION_FIELDS = {'version', 'id', 'project', 'thread_id', 'title', 'goal', 'criteria',
                  'step_id', 'correction_count', 'mode', 'permission_profile', 'state',
                  'pause_reason', 'summary', 'updated_at'}
SESSION_V2_FIELDS = SESSION_FIELDS | {'account_hash', 'turn_id', 'deletion_state'}
SESSION_V3_FIELDS = SESSION_V2_FIELDS | {'workflow'}
SESSION_V4_FIELDS = SESSION_V3_FIELDS | {'recheck_cleanup'}


def session_native_roots(record, *, strict=True):
    flow = record.get('workflow', {})
    events = flow.get('rechecks', [])
    bindings = ({op['thread_id'] for op in validate_recheck_ledger(events, workflow_saved_evidence(flow))}
                if events else set())
    root = record['thread_id']
    if strict and (None in bindings or root in bindings
                   or root is None and (flow or record.get('pause_reason') == 'thread_start_unknown')):
        raise ProbeError('Native bindings are incomplete or ambiguous; nothing deleted.')
    return (bindings | {root}) - {None}

SESSION_STATES = {'READY', 'CLARIFYING', 'AWAITING_MODEL_APPROVAL', 'AWAITING_TOOL_APPROVAL',
                  'RUNNING', 'CHECKING', 'DONE', 'UNVERIFIED', 'PAUSED', 'FAILED'}


class SessionStore:
    """Local metadata only. Locks are held for the full edit context, not per write."""

    def __init__(self, project, state_home=None, *, read_only=False):
        import hashlib
        import stat
        from pathlib import Path
        self._fd = None
        self._locked_ids = set()
        self.read_only = read_only
        self.project = str(Path(project).resolve(strict=True))
        if not Path(self.project).is_dir():
            raise ProbeError('Session project must be a directory.')
        home = Path(state_home if state_home is not None else
                    os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state')
        if not home.is_absolute():
            raise ProbeError('State home must be an absolute path.')
        root = home / 'modelmate'
        if not read_only:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if stat.S_IMODE(os.fstat(root_fd).st_mode) & 0o077:
                raise ProbeError('ModelMate state directory must be private (0700).')
            key = hashlib.sha256(os.fsencode(self.project)).hexdigest()
            if not read_only:
                try:
                    os.mkdir(key, mode=0o700, dir_fd=root_fd)
                except FileExistsError:
                    pass
            project_fd = os.open(key, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 dir_fd=root_fd)
            if stat.S_IMODE(os.fstat(project_fd).st_mode) & 0o077:
                os.close(project_fd)
                raise ProbeError('Project state directory must be private (0700).')
            self._fd = project_fd
            self.directory = root / key
        finally:
            os.close(root_fd)

    def _require_writable(self):
        if self.read_only:
            raise ProbeError('Session store is read-only.')

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _name(self, session_id):
        import uuid
        if self._fd is None:
            raise ProbeError('Session store is closed.')
        try:
            valid = isinstance(session_id, str) and uuid.UUID(session_id).hex == session_id
        except (ValueError, AttributeError):
            valid = False
        if not valid:
            raise ProbeError('Invalid controller-generated session ID.')
        return session_id + '.json'

    def _validate(self, record, session_id):
        if not isinstance(record, dict):
            raise ProbeError('Invalid session metadata fields; file not modified.')
        version = record.get('version')
        if type(version) is not int or version not in (1, 2, 3, 4):
            raise ProbeError('Unsupported session version; file not modified.')
        if set(record) != {1: SESSION_FIELDS, 2: SESSION_V2_FIELDS, 3: SESSION_V3_FIELDS, 4: SESSION_V4_FIELDS}[version]:
            raise ProbeError('Invalid session metadata fields; file not modified.')
        if version >= 2:
            import re
            if (not isinstance(record['account_hash'], str)
                    or re.fullmatch('[0-9a-f]{64}', record['account_hash']) is None
                    or record['deletion_state'] not in ('none', 'requested', 'remote_deleted')):
                raise ProbeError('Invalid session account binding or deletion state.')
            if record['turn_id'] is not None and (not isinstance(record['turn_id'], str)
                    or not record['turn_id'].strip() or len(record['turn_id']) > 256):
                raise ProbeError('Invalid saved turn ID.')
        if record['id'] != session_id or record['project'] != self.project:
            raise ProbeError('Session identity or project mismatch; file not modified.')
        for field in ('title', 'goal', 'summary'):
            if not isinstance(record[field], str) or len(record[field]) > 4096:
                raise ProbeError('Invalid session text.')
        if not record['title'].strip() or not record['goal'].strip():
            raise ProbeError('Session title and goal are required.')
        for field in ('thread_id', 'step_id', 'pause_reason'):
            if record[field] is not None and (not isinstance(record[field], str)
                                             or not record[field].strip() or len(record[field]) > 256):
                raise ProbeError('Invalid session identifier or pause reason.')
        if (not isinstance(record['criteria'], list) or len(record['criteria']) > 32
                or any(not isinstance(v, str) or not v.strip() or len(v) > 4096 for v in record['criteria'])):
            raise ProbeError('Invalid session criteria.')
        if type(record['correction_count']) is not int or not 0 <= record['correction_count'] <= 2:
            raise ProbeError('Invalid session correction count.')
        if record['mode'] not in ('manual', 'auto', 'ask_to_escalate', 'approve_plan'):
            raise ProbeError('Invalid saved mode.')
        if record['permission_profile'] not in ('read_only', 'workspace'):
            raise ProbeError('Invalid saved permission profile.')
        if not isinstance(record['state'], str) or record['state'] not in SESSION_STATES:
            raise ProbeError('Invalid saved task state.')
        if record['state'] == 'PAUSED' and record['pause_reason'] is None:
            raise ProbeError('Paused session requires a reason.')
        if record['correction_count'] and record['step_id'] is None:
            raise ProbeError('Correction count requires a step ID.')
        try:
            stamp = datetime.fromisoformat(record['updated_at'])
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError('timezone required')
        except (ValueError, TypeError, AttributeError):
            raise ProbeError('Invalid session timestamp.') from None
        if version >= 3:
            flow = validate_workflow_checkpoint(record['workflow'])
            plan = validate_plan(flow['plan'])
            step = flow['steps'][flow['step_index']] if flow['step_index'] < len(flow['steps']) else None
            mirror = {'goal': plan['goal'], 'criteria': plan['success_criteria'], 'mode': flow['mode'],
                      'step_id': step['id'] if step else None,
                      'correction_count': max(0, step['attempts'] - 1) if step else 0}
            if record['deletion_state'] == 'none':
                mirror.update(state=flow['state'], pause_reason=flow['reason'] if flow['state'] == 'PAUSED' else None)
            if flow['account_hash'] != record['account_hash'] or any(record[k] != v for k, v in mirror.items()):
                raise ProbeError('Session metadata disagrees with its workflow checkpoint.')
        if version == 4:
            cleanup = record['recheck_cleanup']
            roots = session_native_roots(record)
            if (not flow.get('rechecks') or record['deletion_state'] == 'none'
                    or not isinstance(cleanup, dict) or set(cleanup) != {'deleted', 'pending'}
                    or not isinstance(cleanup['deleted'], list)
                    or any(not isinstance(tid, str) or tid not in roots for tid in cleanup['deleted'])
                    or cleanup['deleted'] != sorted(set(cleanup['deleted']))
                    or (cleanup['pending'] is not None and (
                        not isinstance(cleanup['pending'], str)
                        or cleanup['pending'] not in roots - set(cleanup['deleted'])))
                    or (record['deletion_state'] == 'remote_deleted' and set(cleanup['deleted']) != roots)):
                raise ProbeError('Invalid scoped native deletion receipts.')
        return record

    def _open_file(self, name, flags):
        import stat
        fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                     mode=0o600, dir_fd=self._fd)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_nlink != 1):
            os.close(fd)
            raise ProbeError('Session files must be private regular files without extra links.')
        return fd

    @contextmanager
    def _lock(self, session_id):
        self._require_writable()
        import fcntl
        name = self._name(session_id)
        fd = self._open_file(name + '.lock', os.O_RDWR | os.O_CREAT)
        acquired = False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ProbeError('Session is in use by another writer.') from exc
            acquired = True
            self._locked_ids.add(session_id)
            yield
        finally:
            if acquired:
                self._locked_ids.discard(session_id)
            os.close(fd)
        # Keep the lock file: unlinking would allow a second lock inode during a race.

    def read(self, session_id):
        name = self._name(session_id)
        fd = self._open_file(name, os.O_RDONLY)
        with os.fdopen(fd, 'rb') as source:
            payload = source.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise ProbeError('Session metadata is too large; file not modified.')
        try:
            record = json.loads(payload, object_pairs_hook=_unique_json_object,
                                parse_constant=_invalid_plan_constant)
        except (ProbeError, ValueError, UnicodeError, RecursionError) as exc:
            raise ProbeError('Corrupt session metadata; file not modified.') from exc
        return self._validate(record, session_id)

    def save(self, record):
        self._require_writable()
        import uuid
        if not isinstance(record, dict):
            raise ProbeError('Invalid session metadata.')
        session_id = record.get('id')
        self._name(session_id)
        if session_id not in self._locked_ids:
            raise ProbeError('Saving requires the session edit lock.')
        self._validate(record, session_id)
        record = dict(record, updated_at=datetime.now(timezone.utc).isoformat())
        payload = json.dumps(record, ensure_ascii=True, allow_nan=False, indent=2).encode() + b'\n'
        if len(payload) > 1024 * 1024:
            raise ProbeError('Session metadata is too large.')
        name = self._name(session_id)
        temporary = '.' + session_id + '.' + uuid.uuid4().hex + '.tmp'
        fd = self._open_file(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, name, src_dir_fd=self._fd, dst_dir_fd=self._fd)
            os.fsync(self._fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=self._fd)
            except FileNotFoundError:
                pass

    def create(self, goal, title=None, thread_id=None, account_hash=None):
        import uuid
        session_id = uuid.uuid4().hex
        record = {'version': 1, 'id': session_id, 'project': self.project, 'thread_id': thread_id,
                  'title': goal if title is None else title, 'goal': goal, 'criteria': [],
                  'step_id': None, 'correction_count': 0, 'mode': 'ask_to_escalate',
                  'permission_profile': 'read_only', 'state': 'READY', 'pause_reason': None,
                  'summary': '', 'updated_at': datetime.now(timezone.utc).isoformat()}
        if account_hash is not None:
            record.update(version=2, account_hash=account_hash, turn_id=None, deletion_state='none')
        with self._lock(session_id):
            try:
                os.stat(self._name(session_id), dir_fd=self._fd, follow_symlinks=False)
            except FileNotFoundError:
                self.save(record)
            else:
                raise ProbeError('Session ID collision; existing file not modified.')
        return self.read(session_id)

    def save_workflow(self, session_id, controller):
        self._name(session_id)
        if session_id not in self._locked_ids or not isinstance(controller, WorkflowController):
            raise ProbeError('Workflow checkpoint requires the session writer lock and controller.')
        record = self.read(session_id)
        if record['version'] < 2 or record['deletion_state'] != 'none':
            raise ProbeError('Cannot attach a workflow to unbound or deleting metadata.')
        if 'workflow' not in record and (record['state'] in ('RUNNING', 'CHECKING', 'AWAITING_TOOL_APPROVAL')
                or (record['state'] == 'PAUSED' and record['pause_reason'] in (
                    'outcome_unknown', 'connection_lost', 'thread_start_unknown'))):
            raise ProbeError('Reconcile the existing session outcome before attaching a workflow.')
        data = controller.export_checkpoint()
        if data['account_hash'] is None:
            data['account_hash'] = record['account_hash']
        if data['account_hash'] != record['account_hash']:
            raise ProbeError('Workflow/session account mismatch.')
        previous = record.get('workflow')
        if previous is not None:
            old_rechecks = previous.get('rechecks', [])
            if old_rechecks != data.get('rechecks', [])[:len(old_rechecks)]:
                raise ProbeError('Cannot discard or rewrite the durable recheck ledger.')
            if (previous['task_id'] != data['task_id'] or previous['history'] != data['history'][:len(previous['history'])]):
                raise ProbeError('Cannot replace a workflow task or roll back its ledger.')
            if (previous['baseline'] != data['baseline']
                    or [s['id'] for s in previous['steps']] != [s['id'] for s in data['steps']]):
                raise ProbeError('Cannot replace workflow baseline or step identities.')
            old_plan, new_plan = validate_plan(previous['plan']), validate_plan(data['plan'])
            allowed_plan = copy.deepcopy(old_plan)
            for i, old_step in enumerate(previous['steps']):
                if old_step['state'] != 'DONE':
                    for field in ('objective', 'role', 'effort', 'reason'):
                        allowed_plan['steps'][i][field] = new_plan['steps'][i][field]
            if new_plan != allowed_plan:
                raise ProbeError('Cannot rewrite saved workflow criteria, structure or completed steps.')
            old = previous['active_attempt']
            if old is not None:
                attempts = [event for event in data['history'] if 'kind' not in event]
                if data['active_attempt'] is not None:
                    attempts.append(data['active_attempt'])
                newer = next((event for event in attempts if event['id'] == old['id']), None)
                if (newer is None or any(e not in newer['checks'] for e in old['checks'])
                        or any(old[k] != newer[k] for k in old if k not in ('checks', 'status'))
                        or (old['status'] == 'completed' and newer['status'] != 'completed')):
                    raise ProbeError('Cannot discard an active attempt or its existing evidence.')
        plan = validate_plan(data['plan'])
        step = data['steps'][data['step_index']] if data['step_index'] < len(data['steps']) else None
        active = data['active_attempt']
        previous_active = previous.get('active_attempt') if previous is not None else None
        if active is not None and (previous_active is None or previous_active['id'] != active['id']):
            record['turn_id'] = None  # Reserve attempt and clear old native binding in the same write.
        record.update(version=3, workflow=data, goal=plan['goal'], criteria=plan['success_criteria'],
            step_id=step['id'] if step else None, correction_count=max(0, step['attempts'] - 1) if step else 0,
            mode=data['mode'], permission_profile='read_only', state=data['state'],
            pause_reason=data['reason'] if data['state'] == 'PAUSED' else None)
        self.save(record)

    def record_recheck_recovery(self, session_id, report):
        """Append inspected terminal state only; never create current tool evidence."""
        if session_id not in self._locked_ids:
            raise ProbeError('Recovery requires the session writer lock.')
        record = self.read(session_id)
        operation = unresolved_recheck(record)
        if (operation is None or not isinstance(report, dict) or report.get('state') != 'terminal'
                or report.get('thread_id') != operation['thread_id']
                or report.get('operation_id') != operation['id'] or record['deletion_state'] != 'none'):
            raise ProbeError('Recovery target changed or has no confirmed terminal state.')
        checkpoint = copy.deepcopy(record['workflow'])
        event = {'kind': 'reconcile', 'id': operation['id'], 'status': report.get('status'),
                 'timestamp': datetime.now(timezone.utc).isoformat()}
        if (operation['phase'] == 'turn_pending' and operation['client_message_id'] is not None
                and report.get('client_message_id') == operation['client_message_id']):
            event.update(kind='recover_turn', turn_id=report.get('turn_id'))
        elif report.get('turn_id') != operation['turn_id']:
            raise ProbeError('Recovery turn no longer matches the saved binding.')
        checkpoint['rechecks'].append(event)
        record['workflow'] = validate_workflow_checkpoint(checkpoint)
        record['summary'] = 'Native recheck terminal state reconciled; saved evidence still requires a fresh check.'
        self.save(record)

    @contextmanager
    def workflow(self, session_id, quota, checked_at, catalog, role_policy=None, *, controller=None,
                 persist_initial=True):
        """Hold the writer lock for transitions and optionally defer the initial resume checkpoint."""
        import hashlib
        with self._lock(session_id):
            record = self.read(session_id)
            if record.get('deletion_state') != 'none':
                raise ProbeError('Cannot attach a workflow to unbound or deleting metadata.')
            decision = quota_decision(quota, checked_at)
            if decision['state'] != 'allow':
                raise ProbeError('Workflow attachment paused: ' + decision['reason'])
            fingerprint = hashlib.sha256(decision['account_id'].encode()).hexdigest()
            if record.get('account_hash') != fingerprint:
                raise ProbeError('Workflow session account mismatch or legacy unbound record.')
            if controller is None:
                if 'workflow' not in record:
                    raise ProbeError('Session has no saved workflow.')
                controller = WorkflowController.restore_checkpoint(record['workflow'], quota, checked_at, catalog, role_policy)
            elif controller._persist is not None:
                raise ProbeError('Workflow is already attached or closed; restore its checkpoint instead.')
            elif controller._account_id is None:
                controller._account_id = decision['account_id']
            if persist_initial:
                self.save_workflow(session_id, controller)
            controller._persist = lambda current: self.save_workflow(session_id, current)
            try:
                yield controller
            finally:
                def closed(_):
                    raise ProbeError('Workflow attachment is closed; restore from its checkpoint.')
                controller._persist = closed

    def remove(self, session_id):
        self._require_writable()
        name = self._name(session_id)
        if session_id not in self._locked_ids:
            raise ProbeError('Deleting metadata requires the session lock.')
        record = self.read(session_id)
        if (record.get('workflow', {}).get('rechecks')
                and (record['version'] != 4 or record['deletion_state'] != 'remote_deleted')):
            raise ProbeError('Retained native recheck threads require scoped cleanup; metadata was not removed.')
        os.unlink(name, dir_fd=self._fd)
        os.fsync(self._fd)

    @contextmanager
    def edit(self, session_id):
        with self._lock(session_id):
            record = self.read(session_id)
            yield record
            self.save(record)

    def list_sessions(self):
        if self._fd is None:
            raise ProbeError('Session store is closed.')
        records = [self.read(name[:-5]) for name in os.listdir(self._fd)
                   if name.endswith('.json') and not name.startswith('.')]
        return sorted(records, key=lambda record: record['updated_at'], reverse=True)



def inspect_local_sessions(project, output, session_id=None):
    """Read cached metadata without opening a backend or restoring approval state."""
    def write(text):
        output.write(terminal_text(text) + '\n')

    try:
        store = SessionStore(project, read_only=True)
    except FileNotFoundError:
        if session_id is not None:
            raise ProbeError('No local session store for this project.')
        write('ไม่มี session ที่บันทึกไว้ในโปรเจกต์นี้')
        return
    with store:
        if session_id is None:
            records = store.list_sessions()
            write('Local sessions · สถานะที่บันทึกไว้ ไม่ใช่สถานะ backend ปัจจุบัน')
            for record in records:
                write(record['id'] + ' · ' + record['title'] + ' · ' + record['state']
                      + ' · ' + record['updated_at'])
            if not records:
                write('ไม่มี session ที่บันทึกไว้ในโปรเจกต์นี้')
            return
        record = store.read(session_id)
        checkpoint = record.get('workflow')
        if checkpoint is None:
            raise ProbeError('This session has no workflow checkpoint.')
        # Reading validates the full checkpoint; display only task data, never account/approval fields.
        plan = validate_plan(checkpoint['plan'])
        write('Workflow checkpoint · ข้อมูลเก่าในเครื่อง ยังไม่ได้ตรวจ backend หรือไฟล์งานใหม่')
        write('งาน: ' + plan['goal'])
        write('สถานะที่บันทึก: ' + checkpoint['state'] + ' · โหมด: ' + checkpoint['mode'])
        write('บันทึกเมื่อ: ' + record['updated_at'])
        if checkpoint['reason']:
            write('เหตุผล: ' + checkpoint['reason'])
        active = checkpoint['active_attempt']
        if active is not None:
            if active['status'] == 'completed':
                write('Turn จบตาม checkpoint และยังรอประเมินผลขั้นนี้')
            else:
                write('มี attempt ค้างใน checkpoint; ผลปัจจุบันยังไม่ทราบ ห้าม replay อัตโนมัติ')
        if checkpoint.get('rechecks'):
            rechecks = validate_recheck_ledger(checkpoint['rechecks'], workflow_saved_evidence(checkpoint))
            write('Recheck reservations: ' + str(len(rechecks)) + ' · unresolved: '
                  + str(sum(op['status'] in ('pending', 'unknown') for op in rechecks)))
            for index, operation in enumerate(rechecks):
                write('Recheck ' + str(index + 1) + ': ' + operation['status'] + ' · retained native IDs '
                      + json.dumps({'thread': operation['thread_id'], 'turn': operation['turn_id']}, ensure_ascii=True))
        for index, (step, proposal) in enumerate(zip(checkpoint['steps'], plan['steps'])):
            step_state = ('CHECKING' if active is not None and active['step_id'] == step['id']
                          and active['status'] == 'completed' else step['state'])
            write(str(index + 1) + '. ' + proposal['objective'] + ' · ' + step_state
                  + ' · รอบ ' + str(step['cycle'] + 1) + ' · attempt ' + str(step['attempts']) + '/3')
            latest = active
            if latest is None or latest['step_id'] != step['id']:
                latest = next((item for item in reversed(checkpoint['history'])
                               if 'checks' in item and item['step_id'] == step['id']), None)
            checked = {} if latest is None else {e['check_index']: e for e in latest['checks']}
            for number, check in enumerate(proposal['checks']):
                write('  [' + checked.get(number, {}).get('result', 'pending') + '] '
                      + check['kind'] + ': ' + check['criterion'])
        for index, criterion in enumerate(plan['success_criteria']):
            write('เกณฑ์: ' + criterion + ' · หลักฐานที่บันทึก '
                  + str(len(checkpoint['criterion_evidence'].get(str(index), []))))


def workflow_statistics(controller, started_at, *, now=None):
    """Local session duration includes user wait; requested selections are not dispatch telemetry."""
    now = time.monotonic() if now is None else now
    if (type(started_at) not in (int, float) or type(now) not in (int, float)
            or not math.isfinite(started_at) or not math.isfinite(now) or now < started_at):
        raise ProbeError('Invalid workflow statistics clock.')
    state = controller.snapshot()
    attempts = [event for event in state['history'] if 'checks' in event]
    if state['active_attempt'] is not None:
        attempts.append(state['active_attempt'])
    first_attempts = {}
    for attempt in attempts:
        first_attempts.setdefault(attempt['step_id'], attempt)
    first_pass = dict.fromkeys(('passed', 'failed', 'unknown'), 0)
    for step, proposal in zip(state['steps'], state['plan']['steps']):
        first = first_attempts.get(step['id'])
        if first is None:
            continue
        results = [check['result'] for check in first['checks'].values()]
        if first is state['active_attempt'] or first['status'] != 'completed':
            outcome = 'unknown'
        elif 'fail' in results:
            outcome = 'failed'
        elif len(results) == len(proposal['checks']) and all(result == 'pass' for result in results):
            outcome = 'passed'
        else:
            outcome = 'unknown'
        first_pass[outcome] += 1
    assessed = first_pass['passed'] + first_pass['failed']
    accepted_at = controller._accepted_at
    time_to_acceptance = (round(accepted_at - started_at, 3)
                          if state['state'] == 'DONE' and accepted_at is not None
                          and started_at <= accepted_at <= now else None)
    selections = []
    for attempt in attempts:
        if attempt['selection'] not in selections:
            selections.append(attempt['selection'])
    rechecks = controller.recheck_operations()
    for operation in rechecks:
        if operation['selection'] not in selections:
            selections.append(operation['selection'])
    return {'state': state['state'], 'elapsedSeconds': round(now - started_at, 3),
            'includesUserWait': True, 'attempts': len(attempts), 'attemptsScope': 'workflow_total',
            'elapsedScope': 'current_cli_session', 'requestedSelections': selections,
            'recheckAttempts': len(rechecks), 'firstPassSteps': first_pass,
            'firstPassRate': first_pass['passed'] / assessed if assessed else None,
            'timeToAcceptanceSeconds': time_to_acceptance,
            'reportedModels': None, 'tokenUsage': None}


def append_workflow_metrics(path, stats):
    """Append a private, quota-free workflow summary without storing session data."""
    import fcntl
    import stat

    fields = ('state', 'elapsedSeconds', 'includesUserWait', 'attempts', 'attemptsScope',
              'elapsedScope', 'requestedSelections', 'recheckAttempts', 'reportedModels',
              'tokenUsage', 'tokenUsageScope', 'turnElapsedSeconds', 'timedTurns',
              'workTurnMeasurements', 'firstPassSteps', 'firstPassRate', 'timeToAcceptanceSeconds')
    report = {'schemaVersion': 1, **{name: stats.get(name) for name in fields}}
    line = (json.dumps(report, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1):
            raise ProbeError('Metrics output requires a private regular file owned by this user.')
        fcntl.flock(fd, fcntl.LOCK_EX)
        original_size = os.fstat(fd).st_size
        try:
            pending = memoryview(line)
            while pending:
                written = os.write(fd, pending)
                if written <= 0:
                    raise OSError('Incomplete metrics write.')
                pending = pending[written:]
        except OSError:
            os.ftruncate(fd, original_size)
            raise
    finally:
        os.close(fd)


def load_check_commands(path, plan, project):
    """User-owned bindings are separate from model proposals; loading never executes commands."""
    if path is None:
        return []
    with open(path, 'rb') as source:
        payload = source.read(65537)
    if len(payload) > 65536:
        raise ProbeError('Check command file exceeds 64 KiB.')
    try:
        data = json.loads(payload, object_pairs_hook=_unique_json_object, parse_constant=_invalid_plan_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProbeError('Invalid check command JSON.') from exc
    return validate_check_commands(data, plan, project)


def validate_check_commands(data, plan, project):
    """Use the same binding validation for files and explicitly enabled CLI rechecks."""
    if (not isinstance(data, dict) or set(data) != {'version', 'checks'}
            or type(data['version']) is not int or data['version'] != 1
            or not isinstance(data['checks'], list) or len(data['checks']) > 384):
        raise ProbeError('Expected check command schema: version 1 and checks list.')
    result, identities, commands = [], set(), set()
    for item in data['checks']:
        if (not isinstance(item, dict) or set(item) != {'step', 'check', 'command', 'cwd'}
                or type(item['step']) is not int or type(item['check']) is not int
                or not 1 <= item['step'] <= len(plan['steps'])):
            raise ProbeError('Invalid step/check command binding.')
        checks = plan['steps'][item['step'] - 1]['checks']
        if not 1 <= item['check'] <= len(checks) or checks[item['check'] - 1]['kind'] not in ('test', 'lint'):
            raise ProbeError('Command bindings require a declared test/lint check.')
        _plan_text(item['command'])
        _plan_text(item['cwd'])
        cwd = os.path.realpath(os.path.join(project, item['cwd']))
        if not os.path.isdir(cwd):
            raise ProbeError('Check working directory must exist.')
        identity = (item['step'], item['check'])
        command_key = (item['step'], item['command'], cwd)
        if identity in identities or command_key in commands:
            raise ProbeError('Duplicate check identity or ambiguous command/cwd within a step.')
        identities.add(identity); commands.add(command_key)
        result.append(dict(item, cwd=cwd))
    return result


def read_workflow_confirmation(input_stream, write, *, confirmation='START', cancellation='CANCEL'):
    """Read one explicit confirmation without consuming buffered workflow commands."""
    import sys
    interactive = input_stream is sys.stdin and input_stream.isatty() and sys.stdout.isatty()
    if interactive:
        try:
            import readline  # Let the Terminal editor handle paste boundaries and editing keys.
        except ImportError:
            interactive = False
    while True:
        line = b''
        ended = False
        if interactive:
            try:
                line = input().encode('utf-8')
                ended = True
            except EOFError:
                return False
        else:
            while len(line) <= 256:
                chunk = os.read(input_stream.fileno(), 1)
                if not chunk or chunk == b'\n':
                    ended = chunk == b'\n'
                    break
                line += chunk
        if len(line) > 256:
            write('ข้อมูลยืนยันยาวเกินกำหนด; ไม่อนุมัติ')
            return False
        value = line.strip()
        if not value and ended:
            write('ยังไม่ได้ยืนยัน: พิมพ์ ' + confirmation + ' แล้ว Enter หรือ ' + cancellation + ' เพื่อยกเลิก')
            continue
        if value.startswith(b'\x1b[200~') and value.endswith(b'\x1b[201~'):
            value = value[6:-6].strip()
        if ended and value == confirmation.encode('ascii'):
            return True
        if value and value != cancellation.encode('ascii'):
            details = {'bytes': len(line), 'ascii': line.isascii(),
                       'control_bytes': sum(byte < 32 or byte == 127 for byte in line),
                       'paste_marker': b'\x1b[200~' in line or b'\x1b[201~' in line}
            write('ข้อมูลยืนยันไม่ตรง ' + confirmation + '; ไม่อนุมัติ · input diagnostics ' + json.dumps(details))
        return False


def check_workflow_account(plan, policy):
    """Read account policy and catalog for an explicit workflow without creating a thread."""
    connection = Connection(['codex', 'app-server', '--stdio',
        '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"'], 15)
    try:
        connection.request('initialize', {'clientInfo': {'name': 'modelmate_workflow_preflight', 'version': '0.1.0'}})
        connection.send({'method': 'initialized'})
        quota = refresh_quota(connection)
        report = {'state': 'paused', 'quotaReason': quota['reason'], 'modelTurnsRequested': 0}
        if quota['state'] != 'allow':
            return report
        try:
            catalog = read_models(connection)
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError):
            return dict(report, catalogReason='catalog_unavailable')
        steps = []
        baseline = {'model': policy['standard'], 'effort': 'low'}
        try:
            select_model(catalog, baseline['model'], baseline['effort'])
            baseline['available'] = True
        except ProbeError as exc:
            baseline.update(available=False, reason=str(exc))
        for index, step in enumerate(plan['steps'], 1):
            requested = {'step': index, 'role': step['role'],
                         'model': policy[step['role']], 'effort': step['effort']}
            try:
                select_role(catalog, step['role'], policy, step['effort'])
                requested['available'] = True
            except ProbeError as exc:
                requested.update(available=False, reason=str(exc))
            steps.append(requested)
        if time.monotonic() - quota['checked_at'] > 15:
            report['quotaReason'] = 'quota_stale'
        elif baseline['available'] and all(step['available'] for step in steps):
            report['state'] = 'ready'
        return dict(report, baseline=baseline, steps=steps)
    finally:
        connection.close()


def run_workflow_file(path, bindings, mode, execute, input_stream, output, checks_path=None, resume_id=None,
                      experimental_rechecks=False, suggest_models=False, measure_quota=False, metrics_jsonl=None,
                      check_catalog=False):
    """Explicit-plan preview is offline; live execution requires flag plus interactive confirmation."""
    started_at = time.monotonic()
    if experimental_rechecks and resume_id is None:
        raise ProbeError('--experimental-rechecks requires --resume-workflow.')
    if check_catalog and (execute or resume_id is not None):
        raise ProbeError('--check-catalog requires a new workflow preview without execution.')
    if metrics_jsonl is not None and not execute:
        raise ProbeError('--metrics-jsonl requires an executing workflow.')
    if suggest_models and resume_id is not None:
        raise ProbeError('--suggest-models requires a new --workflow plan.')
    if resume_id is not None:
        with SessionStore(os.getcwd(), read_only=True) as reader:
            saved = reader.read(resume_id)
        if saved.get('workflow') is None:
            raise ProbeError('Session has no workflow checkpoint.')
        raw = saved['workflow']['plan']
        mode = mode or saved['workflow']['mode']
    else:
        with open(path, 'rb') as source:
            raw = source.read(65537).decode('utf-8')
    mode = mode or 'ask_to_escalate'
    plan = validate_plan(raw)
    if suggest_models and not plan['clarifications']:
        raw = json.dumps(suggest_workflow_models(plan), ensure_ascii=False)
        plan = validate_plan(raw)
    commands = load_check_commands(checks_path, plan, os.getcwd())
    policy = {}
    for binding in bindings:
        if '=' not in binding:
            raise ProbeError('Use --role-model ROLE=MODEL.')
        role, model = binding.split('=', 1)
        if role not in ROLE_ORDER or role in policy or not model.strip():
            raise ProbeError('Use unique --role-model economy|standard|strong=MODEL bindings.')
        policy[role] = model
    needed = {'standard'} | {step['role'] for step in plan['steps']}
    if not needed <= set(policy):
        raise ProbeError('Explicit role bindings required: ' + ', '.join(sorted(needed)))
    # Requested efforts are placeholders for preview; native preflight validates actual availability.
    catalog = [{'model': model, 'defaultReasoningEffort': 'low',
                'supportedReasoningEfforts': [{'reasoningEffort': effort} for effort in sorted(
                    {'low'} | {step['effort'] for step in plan['steps'] if policy[step['role']] == model})]}
               for model in sorted(set(policy.values()))]
    controller = WorkflowController(raw, catalog, policy, mode)
    preview = ChatShell(output, catalog=catalog, role_policy=policy, workflow=controller)
    if resume_id is not None:
        inspect_local_sessions(os.getcwd(), output, resume_id)
        preview.write('Resume preview; จะตรวจบัญชี/project/thread/permissions หลัง START · mode ' + mode)
        for i, step in enumerate(plan['steps']):
            preview.write('Requested step ' + str(i + 1) + ': ' + policy[step['role']] + '/' + step['effort'])
    else:
        preview.show_workflow()
    for spec in commands:
        preview.write('คำสั่งตรวจ ' + str(spec['step']) + '.' + str(spec['check']) + ': '
                      + json.dumps({'command': spec['command'], 'cwd': spec['cwd']}, ensure_ascii=True))
    if suggest_models:
        preview.write('ข้อเสนอจาก risk และ checks ของแต่ละขั้น · คุณภาพยังต้องยืนยันจากผลตรวจ')
    preview.write('โมเดลข้างต้นเป็นค่าที่ร้องขอ; ยังไม่ได้ตรวจ catalog/quota จริง')
    if experimental_rechecks:
        preview.write('Experimental recheck · standard=' + policy['standard'] + '/low · native threads retained')
        preview.write('/recheck แสดงแผน; /confirm-recheck TOKEN ใช้โควตาเพิ่มหนึ่ง verification turn')
    if not execute and not check_catalog:
        preview.write('Preview เท่านั้น ไม่เปิด Codex ไม่ใช้โควตา; --execute-workflow เพื่อเริ่มแบบ opt-in')
        return 0
    required = {(i + 1, j + 1) for i, step in enumerate(plan['steps'])
                for j, check in enumerate(step['checks']) if check['kind'] in ('test', 'lint')}
    if controller.state != 'READY' or any(check['kind'] == 'source'
            for step in plan['steps'] for check in step['checks']):
        raise ProbeError('Live explicit plans require no clarifications; source checks are not supported.')
    if resume_id is not None and required and not experimental_rechecks:
        raise ProbeError('Native CLI resume currently supports manual/rubric workflows only; saved tool checks require fresh trusted rechecks.')
    if resume_id is not None and experimental_rechecks:
        if any(op['status'] in ('pending', 'unknown') for op in validate_recheck_ledger(
                saved['workflow'].get('rechecks', []), workflow_saved_evidence(saved['workflow']))):
            raise ProbeError('Recheck outcome unresolved; use --show-workflow to inspect retained native IDs. No replay.')
        active = saved['workflow']['active_attempt']
        if active is not None:
            known = {e['check_index']: e for e in active['checks']}
            index = saved['workflow']['step_index']
            if active['status'] != 'completed' or any(known.get(j, {}).get('result') not in ('pass', 'fail')
                    for j, check in enumerate(plan['steps'][index]['checks']) if check['kind'] in ('test', 'lint')):
                raise ProbeError('Experimental resume needs a completed work turn and known saved tool results; missing/unknown checks are unsupported.')
    if required != {(spec['step'], spec['check']) for spec in commands}:
        raise ProbeError('Every test/lint check needs an explicit --check-commands binding before execution.')
    if any(step['effort'] == 'ultra' for step in plan['steps']):
        raise ProbeError('Automatic delegation effort is not enabled.')
    if check_catalog:
        report = check_workflow_account(plan, policy)
        preview.write('Workflow preflight · ' + json.dumps(report, ensure_ascii=True))
        return 0 if report['state'] == 'ready' else 2
    preview.write('Experimental · read-only/on-request · tool approvals ถูกปฏิเสธ · resume ต้องตรวจ native state ใหม่')
    preview.write('ใช้โควตา subscription เมื่อกด /next หรือยืนยัน recheck; พิมพ์ START แล้ว Enter เพื่อยืนยันแผน หรือ CANCEL เพื่อยกเลิก:')
    output.flush()
    if not read_workflow_confirmation(input_stream, preview.write):
        preview.write('ยกเลิกแล้ว ยังไม่เปิด backend')
        return 0
    backend = store = None
    try:
        store = SessionStore(os.getcwd())
        backend = NativeWorkflowConnection(['codex', 'app-server', '--stdio',
            '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"',
            '-c', 'web_search="disabled"', '-c', 'approvals_reviewer="user"'])
        backend.measure_quota = measure_quota
        if resume_id is None:
            host = backend.connect(controller, os.getcwd(), policy, store=store)
        else:
            host = backend.resume(store, resume_id, os.getcwd(), policy, raw)
            controller = host.controller
            if controller.mode != mode:
                controller.change_mode(mode)
        for spec in commands:
            if spec['step'] - 1 >= controller.snapshot()['step_index']:
                host.configure_check(spec['check'] - 1, step_index=spec['step'] - 1,
                                     command=spec['command'], cwd=spec['cwd'])
        snapshot = backend.preflight()
        preview.write('Session: ' + backend.session_id + ' · durable checkpoint; ไม่ replay turn อัตโนมัติ')
        return run_chat(input_stream, output, backend=backend, workflow=controller,
                        workflow_action=host, catalog=snapshot['catalog'], role_policy=policy,
                        recheck_commands=commands if experimental_rechecks else None)
    finally:
        elapsed_end = time.monotonic()
        measurements = {}
        try:
            if backend is not None:
                try:
                    measurements = backend.workflow_measurements()
                finally:
                    backend.close()
        finally:
            if store is not None:
                store.close()
        observed = backend.controller if backend is not None and backend.controller is not None else controller
        stats = workflow_statistics(observed, started_at, now=elapsed_end)
        stats.update(measurements)
        preview.write('สถิติ workflow: ' + json.dumps(stats, ensure_ascii=False))
        if metrics_jsonl is not None:
            try:
                append_workflow_metrics(metrics_jsonl, stats)
            except (ProbeError, OSError, ValueError, TypeError) as exc:
                detail = str(exc) if isinstance(exc, ProbeError) else diagnostic_code(exc)
                preview.write('บันทึก metrics JSONL ไม่สำเร็จ · ' + detail)


def run_work_turn_inspection(session_id, output):
    """Inspect the saved work binding, without replaying or revalidating its checks."""
    with SessionStore(os.getcwd(), read_only=True) as store:
        record = store.read(session_id)
        flow = record.get('workflow')
        if flow is None or record['deletion_state'] != 'none':
            raise ProbeError('Inspection requires a saved workflow without pending deletion.')
        latest = flow['active_attempt']
        if latest is None:
            latest = next((event for event in reversed(flow['history']) if 'checks' in event), None)
        if not record['thread_id'] or not record['turn_id'] or latest is None:
            report = {'state': 'unverified', 'reason': 'missing_native_binding'}
        elif latest['status'] == 'running':
            # A crash before turn/start replies can leave the previous turn ID in the checkpoint.
            report = {'state': 'unverified', 'reason': 'unconfirmed_attempt_binding'}
        else:
            connection = RecheckRecoveryConnection(['codex', 'app-server', '--stdio',
                '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"'])
            try:
                connection.allowed_methods = connection.allowed_methods - {'turn/interrupt'}
                connection._account(record)
                report = connection.inspect_bound_turn(store.project, record['thread_id'], record['turn_id'])
                if report['state'] == 'terminal' and report['status'] != latest['status']:
                    report = {'state': 'unverified', 'reason': 'native_status_mismatch'}
                if store.read(session_id) != record:
                    raise ProbeError('Workflow checkpoint changed during inspection; run it again.')
            finally:
                connection.close()
        counts = dict.fromkeys(('pass', 'fail', 'unknown'), 0)
        if latest is not None:
            for check in latest['checks']:
                counts[check['result']] += 1
        output.write(json.dumps(dict(report, historicalChecks=counts, modelTurnsRequested=0),
                                ensure_ascii=True) + '\n')
        return 0 if report['state'] == 'terminal' else 2


def run_recheck_recovery(session_id, input_stream, output):
    """Inspect/reconcile retained bindings without model dispatch or restored grants."""
    def write(text):
        output.write(terminal_text(text) + '\n');output.flush()

    # Require existing metadata before opening a writable store or native process.
    with SessionStore(os.getcwd(), read_only=True) as reader:
        reader.read(session_id)
    with SessionStore(os.getcwd()) as store, store._lock(session_id):
        operation = unresolved_recheck(store.read(session_id))
        if operation is None:
            write('ไม่มี recheck ที่ค้างอยู่ · ไม่เรียกโมเดล');return 0
        if operation['phase'] != 'turn_bound' and operation['client_message_id'] is None:
            detail = {
                'reserved': 'ไม่มี thread ID ที่บันทึกไว้ การสร้าง native thread อาจเกิดขึ้นแล้ว',
                'thread_bound': 'บันทึก thread ID แล้ว แต่ยังไม่ถึงจุดจองส่ง turn',
                'turn_pending': 'จองส่ง turn แล้ว แต่ไม่มี turn ID ที่บันทึกไว้ ผลการส่งยังไม่ทราบ',
            }[operation['phase']]
            write(f"Native binding ไม่ครบ ({operation['phase']}) · {detail} · ใช้ --show-workflow ตรวจ metadata")
            return 2
        connection = RecheckRecoveryConnection(['codex', 'app-server', '--stdio',
            '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"'])
        try:
            report = connection.inspect_recheck(store, session_id)
            write('Recovery · ไม่เริ่ม model turn · ' + json.dumps(report, ensure_ascii=True))
            if report['state'] == 'active':
                write('พิมพ์ STOP เพื่อขอหยุด turn นี้ หรือ PAUSE เพื่อพักการ recovery; EOF ไม่อนุมัติ')
                if not read_workflow_confirmation(input_stream, write, confirmation='STOP', cancellation='PAUSE'):
                    write('พักการ recovery แล้ว; native turn อาจยังทำงานอยู่');return 2
                report = connection.interrupt_recheck(store, session_id, report)
                write('ผล native: ' + json.dumps(report, ensure_ascii=True))
            if report['state'] != 'terminal':
                write('ยังยืนยัน terminal state ไม่ได้ เก็บ metadata เดิมไว้ ไม่ replay');return 2
            store.record_recheck_recovery(session_id, report)
            write('บันทึกสถานะ native แล้ว หลักฐานเก่ายัง stale; resume แล้วใช้ /recheck และยืนยันรอบใหม่ได้')
            return 0
        finally:
            connection.close()


def run_session_cleanup(session_id, input_stream, output):
    """Preview and delete one account-bound session without opening a chat."""
    import uuid

    def write(text):
        output.write(terminal_text(text) + '\n')
        output.flush()

    project = os.getcwd()
    with SessionStore(project, read_only=True) as reader:
        reader.read(session_id)
    with SessionStore(project) as store, store._lock(session_id):
        record = store.read(session_id)
        backend = LiveChatConnection(['codex', 'app-server', '--stdio',
            '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"'])
        try:
            backend.allowed_methods = {'initialize', 'account/read', 'account/rateLimits/read',
                                       'thread/read', 'thread/turns/list', 'thread/list', 'thread/delete'}
            backend.store, backend.cwd = store, store.project
            backend.request('initialize', {'clientInfo': {'name': 'modelmate_session_cleanup', 'version': '0.1.0'}})
            backend.send({'method': 'initialized'})
            backend._fresh_account(require_usage=False)
            backend._check_identity(record)
            tree = backend._deletion_tree(record)
            write(json.dumps({'delete_session': session_id, 'title': record['title'],
                              'threads_including_descendants': tree,
                              'work_files_deleted': False}, ensure_ascii=True))
            token = 'DELETE ' + uuid.uuid4().hex
            write('พิมพ์ ' + token + ' แล้ว Enter เพื่อยืนยันการลบ หรือ CANCEL เพื่อยกเลิก')
            if not read_workflow_confirmation(input_stream, write, confirmation=token):
                write('ยกเลิกการลบ session')
                return 2
            backend._fresh_account(require_usage=False)
            backend._check_identity(record)
            if record != store.read(session_id) or tree != backend._deletion_tree(record):
                raise ProbeError('Deletion scope changed; request a new preview.')
            backend._confirm_session_deletion(record, tree)
            write('ลบ session ตามขอบเขตที่ยืนยันแล้ว: ' + session_id)
            return 0
        finally:
            backend.close()


def read_search_json(host, path, method, body=None, *, source):
    import http.client

    headers = {'Accept': 'application/json', 'User-Agent': 'ModelMate/0.1 (https://github.com/GearJP2/ModelMate)'}
    if body is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    connection = http.client.HTTPSConnection(host, timeout=8)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise ProbeError(source + ' search returned HTTP ' + str(response.status) + '.')
        data = response.read(262145)
        if len(data) > 262144:
            raise ProbeError(source + ' search response exceeded its size limit.')
        try:
            payload = json.loads(data)
        except (ValueError, RecursionError) as exc:
            raise ProbeError('Invalid ' + source + ' search response.') from exc
        if not isinstance(payload, dict):
            raise ProbeError('Invalid ' + source + ' search response.')
        return payload
    except (OSError, http.client.HTTPException) as exc:
        raise ProbeError(source + ' search connection failed (' + diagnostic_code(exc) + ').') from None
    finally:
        connection.close()


def search_text(value, limit):
    import html
    import re
    plain = html.unescape(re.sub(r'<[^<>]{0,128}>', '', value))
    return terminal_text(' '.join(plain.split()))[:limit]


def search_wikipedia(query, language):
    """Fetch source candidates with only the explicitly supplied query."""
    from urllib.parse import urlencode

    host = {'en': 'en.wikipedia.org', 'th': 'th.wikipedia.org'}[language]
    path = '/w/rest.php/v1/search/page?' + urlencode({'q': query, 'limit': 5})
    pages = read_search_json(host, path, 'GET', source='Wikipedia').get('pages')
    if not isinstance(pages, list) or len(pages) > 5:
        raise ProbeError('Invalid Wikipedia search results.')
    results = []
    for page in pages:
        if not isinstance(page, dict):
            raise ProbeError('Invalid Wikipedia search result.')
        identifier, title, excerpt = (page.get(key) for key in ('id', 'title', 'excerpt'))
        if (type(identifier) is not int or not 0 < identifier < 2 ** 63
                or not isinstance(title, str) or not title.strip() or not isinstance(excerpt, str)):
            raise ProbeError('Invalid Wikipedia source metadata.')
        results.append({'title': search_text(title, 300), 'excerpt': search_text(excerpt, 600),
                        'url': 'https://' + host + '/?curid=' + str(identifier)})
    return results


def searxng_host(origin):
    import re
    from urllib.parse import urlsplit

    try:
        url = urlsplit(origin)
        if (url.scheme == 'https' and url.path in ('', '/') and not url.query and not url.fragment
                and re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]+)?', url.netloc)
                and url.port != 0):
            return url.netloc
    except ValueError:
        pass
    raise ProbeError('Provide the HTTPS origin of a trusted SearXNG instance, without credentials or a path.')


def search_searxng(query, host):
    from urllib.parse import urlencode, urlsplit

    body = urlencode({'q': query, 'format': 'json'}).encode('ascii')
    rows = read_search_json(host, '/search', 'POST', body, source='SearXNG').get('results')
    if not isinstance(rows, list):
        raise ProbeError('Invalid SearXNG search results. Check that JSON output is enabled.')
    results = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url, title, content = (row.get(key) for key in ('url', 'title', 'content'))
        if (not isinstance(url, str) or len(url) > 4096 or not isinstance(title, str) or not title.strip()
                or terminal_text(url) != url or any(c.isspace() for c in url)):
            continue
        try:
            link = urlsplit(url)
            if link.scheme not in ('http', 'https') or not link.hostname or link.username is not None:
                continue
        except ValueError:
            continue
        results.append({'title': search_text(title, 300),
                        'excerpt': search_text(content, 600) if isinstance(content, str) else '',
                        'url': url})
        if len(results) == 5:
            break
    return results


def run_wikipedia_search(input_stream, output, language):
    host = {'en': 'en.wikipedia.org', 'th': 'th.wikipedia.org'}[language]
    return run_confirmed_search(input_stream, output, host, 'Wikipedia',
                                lambda query: search_wikipedia(query, language))


def run_confirmed_search(input_stream, output, host, source, search):
    import secrets
    import unicodedata

    def write(message):
        output.write(message + '\n')
        output.flush()

    def read_line(limit):
        # Decode only the current line, even when a terminal paste contains later invalid bytes.
        binary = getattr(input_stream, 'buffer', None)
        if binary is not None:
            return binary.readline(limit * 4).decode('utf-8')
        return input_stream.readline(limit)

    write('พิมพ์คำค้น ' + source + ' หนึ่งบรรทัด แล้วกด Enter')
    while True:
        try:
            line = read_line(1026)
            break
        except UnicodeDecodeError as exc:
            if not exc.object.endswith(b'\n'):
                raise ProbeError('คำค้นอ่านเป็น UTF-8 ไม่ได้ กรุณาเปิดคำสั่งค้นใหม่') from None
            write('คำค้นอ่านเป็น UTF-8 ไม่ได้ กรุณาพิมพ์คำค้นใหม่แล้วกด Enter')
    if not line.endswith('\n'):
        raise ProbeError('Search requires a complete query line of up to 1024 characters.')
    query = line.strip()
    if (not query or len(query) > 1024 or any(unicodedata.category(c).startswith('C') for c in query)):
        raise ProbeError('Invalid search query.')
    token = 'SEARCH ' + secrets.token_hex(4)
    write('คำค้นที่จะส่งไปยัง ' + host + ' · ' + json.dumps(query, ensure_ascii=False))
    if source == 'SearXNG':
        write('SearXNG อาจส่งคำค้นนี้ต่อให้เครื่องมือค้นหาที่ instance เปิดใช้')
    write('พิมพ์ ' + token + ' แล้ว Enter เพื่อส่งคำค้น หรือ CANCEL เพื่อยกเลิก')
    try:
        confirmation = read_line(128)
    except UnicodeDecodeError:
        write('ยกเลิกการค้น เพราะรหัสยืนยันอ่านเป็น UTF-8 ไม่ได้')
        return 2
    if not confirmation.endswith('\n') or confirmation.strip(' \t\r\n') != token:
        write('ยกเลิกการค้น')
        return 2
    results = search(query)
    if not results:
        write('ไม่พบผลจาก ' + source)
    for index, result in enumerate(results, 1):
        write(str(index) + '. ' + result['title'] + '\n   ' + result['excerpt'] + '\n   ' + result['url'])
    return 0


def main():
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='ModelMate Terminal chat: offline by default; --live uses ChatGPT subscription quota.')
    parser.add_argument('prompt', nargs='?', help='initial task text')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--delete-session', metavar='SESSION_ID',
                       help='preview and confirm scoped native thread and metadata deletion; no model turns')
    modes.add_argument('--search-web', metavar='HTTPS_ORIGIN',
                       help='search a configured SearXNG instance with a separately confirmed query')
    modes.add_argument('--search-wikipedia', choices=('en', 'th'), metavar='{en,th}',
                       help='search Wikipedia with a separately entered and confirmed query; no model turns')
    modes.add_argument('--inspect-work-turn', metavar='SESSION_ID',
                       help='inspect the last saved workflow turn; no inference or checkpoint changes')
    modes.add_argument('--recover-recheck', metavar='SESSION_ID',
                       help='inspect/reconcile a retained recheck; no model turns; STOP/PAUSE if active')
    modes.add_argument('--resume-workflow', metavar='SESSION_ID', help='preview/resume a durable workflow; never replay unknown work')
    modes.add_argument('--workflow', metavar='PLAN_JSON', help='preview an explicit workflow plan offline')
    parser.add_argument('--check-catalog', action='store_true',
                        help='validate a new workflow against live catalog and quota without inference')
    parser.add_argument('--suggest-models', action='store_true',
                        help='recommend role/effort from explicit step risk and checks; requires a new --workflow')
    parser.add_argument('--role-model', action='append', default=[], metavar='ROLE=MODEL', help='explicit workflow role binding')
    parser.add_argument('--workflow-mode', choices=('auto', 'ask_to_escalate', 'approve_plan'), help='workflow model policy (default: ask_to_escalate)')
    parser.add_argument('--check-commands', metavar='CHECKS_JSON', help='user-owned command/cwd bindings for workflow test/lint checks')
    parser.add_argument('--measure-quota', action='store_true',
                        help='include matching quota window observations in the live workflow summary')
    parser.add_argument('--metrics-jsonl', metavar='FILE',
                        help='append a private live workflow metrics record without account quota data')
    parser.add_argument('--execute-workflow', action='store_true', help='opt-in native workflow; requires START confirmation')
    parser.add_argument('--experimental-rechecks', action='store_true',
                        help='experimental tool-check resume; /confirm-recheck consumes an extra model turn; native threads retained')
    modes.add_argument('--sessions', action='store_true', help='list local sessions without connecting to Codex')
    modes.add_argument('--show-workflow', metavar='SESSION_ID', help='inspect a cached workflow without resuming it')
    modes.add_argument('--live', action='store_true', help='manual-model live chat using ChatGPT subscription quota')
    parser.add_argument('--model', help='explicit model ID for --live')
    parser.add_argument('--effort', default='low', help='explicit effort for --live (default: low)')
    parser.add_argument('--resume', metavar='SESSION_ID', help='resume a local session with --live; never replay old work')
    modes.add_argument('--doctor', action='store_true', help='connect to real Codex and read account, models and quota; no inference')
    args = parser.parse_args()
    if args.check_catalog and (not args.workflow or args.execute_workflow):
        parser.error('--check-catalog requires --workflow without --execute-workflow')
    if args.measure_quota and (not args.execute_workflow or not (args.workflow or args.resume_workflow)):
        parser.error('--measure-quota requires an executing workflow')
    if args.metrics_jsonl is not None and (not args.execute_workflow or not (args.workflow or args.resume_workflow)):
        parser.error('--metrics-jsonl requires an executing workflow')
    if args.suggest_models and not args.workflow:
        parser.error('--suggest-models requires a new --workflow plan')
    if args.experimental_rechecks and not args.resume_workflow:
        parser.error('--experimental-rechecks requires --resume-workflow')
    if not (args.workflow or args.resume_workflow) and (args.role_model or args.workflow_mode or args.execute_workflow or args.check_commands):
        parser.error('Workflow options require --workflow PLAN_JSON or --resume-workflow SESSION_ID')
    if args.delete_session:
        if args.prompt is not None or args.model or args.resume or args.effort != 'low':
            parser.error('Session deletion does not accept prompt/model/effort overrides')
        try:
            return run_session_cleanup(args.delete_session, sys.stdin, sys.stdout)
        except KeyboardInterrupt:
            return 130
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, ProbeError) else diagnostic_code(exc)
            print('ModelMate cleanup: ' + terminal_text(message), file=sys.stderr)
            return 1
    if args.search_wikipedia or args.search_web is not None:
        if args.prompt is not None or args.model or args.resume or args.effort != 'low':
            parser.error('Web search only accepts its own confirmed query')
        try:
            if args.search_wikipedia:
                return run_wikipedia_search(sys.stdin, sys.stdout, args.search_wikipedia)
            host = searxng_host(args.search_web)
            return run_confirmed_search(sys.stdin, sys.stdout, host, 'SearXNG',
                                        lambda query: search_searxng(query, host))
        except KeyboardInterrupt:
            return 130
        except (ProbeError, OSError, ValueError, UnicodeError) as exc:
            message = str(exc) if isinstance(exc, ProbeError) else diagnostic_code(exc)
            print('ModelMate search: ' + terminal_text(message), file=sys.stderr)
            return 1
    if args.inspect_work_turn:
        if args.prompt is not None or args.model or args.resume or args.effort != 'low':
            parser.error('Work-turn inspection does not accept prompt/model/effort overrides')
        try:
            return run_work_turn_inspection(args.inspect_work_turn, sys.stdout)
        except KeyboardInterrupt:
            return 130
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, ProbeError) else diagnostic_code(exc)
            print('ModelMate work inspection: ' + terminal_text(message), file=sys.stderr)
            return 1
    if args.recover_recheck:
        if args.prompt is not None or args.model or args.resume or args.effort != 'low':
            parser.error('Recheck recovery does not accept prompt/model/effort overrides')
        try:
            return run_recheck_recovery(args.recover_recheck, sys.stdin, sys.stdout)
        except KeyboardInterrupt:
            return 130
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, ProbeError) else diagnostic_code(exc)
            print('ModelMate recovery: ' + terminal_text(message), file=sys.stderr)
            return 1
    if args.workflow or args.resume_workflow:
        if args.prompt is not None or args.model or args.resume or args.effort != 'low':
            parser.error('Workflow uses plan efforts and explicit role bindings; no prompt/model/resume overrides')
        try:
            return run_workflow_file(args.workflow, args.role_model, args.workflow_mode,
                                     args.execute_workflow, sys.stdin, sys.stdout, args.check_commands, args.resume_workflow,
                                     experimental_rechecks=args.experimental_rechecks, suggest_models=args.suggest_models,
                                     measure_quota=args.measure_quota, metrics_jsonl=args.metrics_jsonl,
                                     check_catalog=args.check_catalog)
        except KeyboardInterrupt:
            return 130
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, ProbeError) else 'Cannot load/start explicit workflow.'
            print('ModelMate workflow: ' + terminal_text(message), file=sys.stderr)
            return 1
    if args.sessions or args.show_workflow is not None:
        if args.prompt is not None or args.model or args.resume or args.effort != 'low':
            parser.error('Local inspection does not accept prompt, model, resume or effort overrides')
        try:
            inspect_local_sessions(os.getcwd(), sys.stdout, args.show_workflow)
            return 0
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, ProbeError) else 'Cannot read local session metadata.'
            print('ModelMate local: ' + terminal_text(message), file=sys.stderr)
            return 1
    if args.live and (args.doctor or not args.model):
        parser.error('--live requires --model and cannot be combined with --doctor')
    if args.model and not args.live:
        parser.error('--model requires --live')
    if args.resume and not args.live:
        parser.error('--resume requires --live and --model')
    if args.live:
        backend = None
        store = None
        try:
            store = SessionStore(os.getcwd())
            backend = LiveChatConnection(['codex', 'app-server', '--stdio',
                '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"',
                '-c', 'web_search="disabled"', '-c', 'approvals_reviewer="user"'])
            backend.connect(args.model, args.effort, os.getcwd(), store=store, session_id=args.resume)
            return run_chat(sys.stdin, sys.stdout, backend=backend, prompt=args.prompt)
        except KeyboardInterrupt:
            return 130
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, ProbeError) else 'Cannot start live Codex chat.'
            print('ModelMate live: ' + terminal_text(message), file=sys.stderr)
            return 1
        finally:
            if backend is not None:
                backend.close()
            if store is not None:
                store.close()
    if args.doctor:
        if args.prompt is not None:
            parser.error('--doctor does not accept a prompt')
        connection = None
        try:
            connection = Connection(['codex', 'app-server', '--stdio'], 15)
            print(json.dumps(inspect(connection), ensure_ascii=False, indent=2))
            return 0
        except KeyboardInterrupt:
            return 130
        except (ProbeError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, ProbeError) else 'Check Codex installation, login, filesystem and protocol compatibility.'
            print('ModelMate connection check: ' + message, file=sys.stderr)
            return 1
        finally:
            if connection is not None:
                connection.close()
    return run_chat(sys.stdin, sys.stdout, prompt=args.prompt)


if __name__ == '__main__':
    import sys
    sys.exit(main())
