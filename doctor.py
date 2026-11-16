#!/usr/bin/env python3
"""Read Codex account, model catalog and quota without starting a model turn."""
import argparse
import json
import math
import os
import selectors
import subprocess
import sys
import time
from datetime import datetime, timezone


class ProbeError(Exception):
    pass


class Connection:
    def __init__(self, command, timeout):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.timeout = timeout
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ, 'stdout')
        self.selector.register(self.process.stderr, selectors.EVENT_READ, 'stderr')
        self.buffer = b''
        self.request_id = 0

    def close(self):
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

    def request(self, method, params=None):
        if method not in {'initialize', 'account/read', 'model/list', 'account/rateLimits/read'}:
            raise ProbeError('This diagnostic only permits read-only requests.')
        self.request_id += 1
        request = {'id': self.request_id, 'method': method}
        if params is not None:
            request['params'] = params
        self.send(request)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                try:
                    response = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise ProbeError('Codex returned invalid JSON.') from exc
                if not isinstance(response, dict):
                    raise ProbeError('Codex returned an invalid protocol message.')
                if 'method' in response and 'id' in response:
                    raise ProbeError('Unexpected server request; no action was approved.')
                if response.get('id') != self.request_id:
                    continue
                if 'error' in response:
                    # Server errors can contain paths or account details; do not print raw payloads.
                    raise ProbeError(f'{method} failed; check Codex login, network and version.')
                if not isinstance(response.get('result'), dict):
                    raise ProbeError(f'{method} returned an invalid result.')
                return response['result']
            for key, _ in self.selector.select(max(0, deadline - time.monotonic())):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    self.selector.unregister(key.fileobj)
                    if key.data == 'stdout':
                        raise ProbeError('Codex exited; check local filesystem permissions and login.')
                elif key.data == 'stdout':
                    self.buffer += chunk
                    if len(self.buffer) > 4 * 1024 * 1024:
                        raise ProbeError('Codex response exceeded the diagnostic size limit.')
                # Drain stderr without retaining possible secrets from Codex logs.
        raise ProbeError(f'{method} timed out after {self.timeout:g}s.')


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=15, help='timeout per RPC in seconds (default: 15)')
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and greater than zero')
    connection = None
    try:
        connection = Connection(['codex', 'app-server', '--stdio'], args.timeout)
        report = inspect(connection)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (ProbeError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        message = str(exc) if isinstance(exc, ProbeError) else 'Could not inspect Codex. Check installation, permissions and protocol compatibility.'
        print('ModelMate doctor: ' + message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('ModelMate doctor: cancelled.', file=sys.stderr)
        return 130
    finally:
        if connection is not None:
            connection.close()


if __name__ == '__main__':
    sys.exit(main())
