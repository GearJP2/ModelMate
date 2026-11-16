#!/usr/bin/env python3
"""ModelMate runtime primitives. Importing this module performs no I/O."""
import json
import math
import os
import selectors
import subprocess
import time
from datetime import datetime, timezone


class ProbeError(Exception):
    pass


class Connection:
    allowed_methods = {"initialize", "account/read", "model/list", "account/rateLimits/read"}

    def __init__(self, command, timeout):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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

    def receive(self, deadline):
        while time.monotonic() < deadline:
            if b'\n' in self.buffer:
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
            if self.stdout_closed:
                raise ProbeError('Codex exited; check local filesystem permissions and login.')
            for key, _ in self.selector.select(max(0, deadline - time.monotonic())):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    self.selector.unregister(key.fileobj)
                    if key.data == 'stdout':
                        self.stdout_closed = True
                elif key.data == 'stdout':
                    self.buffer += chunk
                    if len(self.buffer) > 4 * 1024 * 1024:
                        raise ProbeError('Codex response exceeded the diagnostic size limit.')
                # Drain stderr without retaining possible secrets from Codex logs.
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
    models = []
    cursor = None
    seen = set()
    while True:
        params = {'limit': 100}
        if cursor:
            params['cursor'] = cursor
        page = connection.request('model/list', params)
        models.extend({k: model.get(k) for k in
                       ('model', 'displayName', 'defaultReasoningEffort', 'supportedReasoningEfforts')}
                      for model in page['data'] if not model.get('hidden'))
        cursor = page.get('nextCursor')
        if not cursor:
            break
        if cursor in seen or len(seen) >= 100:
            raise ProbeError('Model catalog pagination did not terminate.')
        seen.add(cursor)
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
