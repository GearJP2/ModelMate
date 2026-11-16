"""Quota policy tests use synthetic accounts and an offline JSONL server."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modelmate import ProbeError, quota_decision, refresh_quota
from verify import VerificationConnection


GOOD = {'ordinaryUsageAllowed': True, 'accountId': 'synthetic',
        'rateLimits': {'primary': {'usedPercent': 29, 'windowDurationMins': 300,
                                   'resetsAt': 2000000000}}}

FAKE_SERVER = r'''
import json,sys
payloads=json.loads(sys.argv[1])
trace=sys.argv[2]
account=json.loads(sys.argv[3])
turn=0
for line in sys.stdin:
    req=json.loads(line)
    method=req['method']
    with open(trace,'a') as out:
        out.write(json.dumps({'method':method})+'\n')
    if method=='account/read':
        result={'account':account}
    elif method=='account/rateLimits/read':
        value=payloads.pop(0)
        if value=='CLOSE':
            break
        if value=='RPC_ERROR':
            print(json.dumps({'id':req['id'],'error':{'code':-1,'message':'synthetic'}}),flush=True)
            continue
        result=value
    elif method=='turn/start':
        turn+=1
        result={'turn':{'id':str(turn)}}
    else:
        raise RuntimeError(method)
    print(json.dumps({'id':req['id'],'result':result}),flush=True)
    if method=='turn/start':
        print(json.dumps({'method':'item/completed','params':{
            'threadId':'thread','turnId':str(turn),'item':{'type':'agentMessage','text':'ok'}}}),flush=True)
        print(json.dumps({'method':'turn/completed','params':{
            'threadId':'thread','turn':{'id':str(turn),'status':'completed'}}}),flush=True)
'''


class QuotaPolicyTests(unittest.TestCase):
    def decide(self, quota, **kwargs):
        return quota_decision(quota, 100, now=101, **kwargs)

    def test_allowed_decision_contains_time_and_identity(self):
        self.assertEqual(self.decide(GOOD), {
            'state': 'allow', 'reason': 'included_usage_available',
            'checked_at': 100, 'account_id': 'synthetic'})

    def test_stale_future_and_invalid_timestamps_pause(self):
        for checked, now in [(0, 16), (101, 100), (float('nan'), 100),
                             (True, 1), (100, float('inf'))]:
            with self.subTest(checked=checked, now=now):
                self.assertEqual(quota_decision(GOOD, checked, now=now)['reason'], 'quota_stale')

    def test_expired_reset_time_does_not_override_exhaustion(self):
        q = copy.deepcopy(GOOD)
        q['rateLimits']['primary'].update(usedPercent=100, resetsAt=1)
        self.assertEqual(self.decide(q)['reason'], 'quota_exhausted')

    def test_missing_or_changed_account_pause(self):
        self.assertEqual(self.decide(dict(GOOD, accountId=None))['reason'], 'account_unknown')
        self.assertEqual(self.decide(GOOD, expected_account='other')['reason'], 'account_changed')

    def test_unknown_or_malformed_policy_values_pause(self):
        cases = [None, {}, dict(GOOD, ordinaryUsageAllowed=1),
                 dict(GOOD, rateLimitsByLimitId={}), dict(GOOD, rateLimitsByLimitId=[])]
        for flags in [{'spendControlReached': 'false'}, {'rateLimitReachedType': False},
                      {'credits': []}, {'credits': {'hasCredits': 'false', 'unlimited': False}},
                      {'primary': {'usedPercent': True}}, {'primary': {'usedPercent': -1}},
                      {'primary': {'usedPercent': float('nan')}},
                      {'primary': {'usedPercent': 2, 'resetsAt': True}}]:
            cases.append(dict(GOOD, rateLimits=flags))
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(self.decide(value)['state'], 'pause')

    def test_every_bucket_must_pass_without_model_mapping(self):
        buckets = {'codex': GOOD['rateLimits'], 'other': {'secondary': {'usedPercent': 100}}}
        q = dict(GOOD, rateLimitsByLimitId=buckets)
        self.assertEqual(self.decide(q)['reason'], 'quota_exhausted')
        buckets['other'] = {'secondary': {'usedPercent': 5}}
        self.assertEqual(self.decide(q)['state'], 'allow')

    def test_credit_access_and_spend_limit_pause(self):
        for bucket, reason in [
            ({'primary': {'usedPercent': 5}, 'credits': {'hasCredits': True, 'unlimited': False}}, 'extra_credit_access'),
            ({'primary': {'usedPercent': 5}, 'spendControlReached': True}, 'quota_exhausted'),
            ({'primary': {'usedPercent': 5}, 'rateLimitReachedType': 'new_unknown_limit'}, 'quota_exhausted')]:
            self.assertEqual(self.decide(dict(GOOD, rateLimits=bucket))['reason'], reason)

    def test_refresh_errors_are_pauses_not_raw_error_logs(self):
        for error in [ProbeError('private details'), OSError('private details')]:
            connection = Mock()
            connection.request.side_effect = error
            result = refresh_quota(connection)
            self.assertEqual(result['reason'], 'quota_unavailable')
            self.assertNotIn('private details', json.dumps(result))

    def test_slow_refresh_cannot_produce_a_fresh_grant(self):
        connection = Mock()
        connection.request.side_effect = [{'account': {'type': 'chatgpt'}}, GOOD]
        with patch('modelmate.time.monotonic', side_effect=[100, 116]):
            self.assertEqual(refresh_quota(connection)['reason'], 'quota_stale')


class QuotaWireTests(unittest.TestCase):
    def server(self, quotas, account=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        trace = Path(tmp.name) / 'requests.jsonl'
        c = VerificationConnection([sys.executable, '-u', '-c', FAKE_SERVER,
                                    json.dumps(quotas), str(trace),
                                    json.dumps(account or {'type': 'chatgpt'})], 2)
        self.addCleanup(c.close)
        c.thread_id = 'thread'
        return c, trace

    def methods(self, trace):
        return [json.loads(line)['method'] for line in trace.read_text().splitlines()]

    def test_blocked_gate_never_sends_turn_start(self):
        for quota in [{}, dict(GOOD, ordinaryUsageAllowed=False),
                      dict(GOOD, rateLimits={'primary': {'usedPercent': 100}}),
                      dict(GOOD, accountId=None), 'RPC_ERROR', 'CLOSE']:
            with self.subTest(quota=quota):
                c, trace = self.server([quota])
                with self.assertRaises(ProbeError):
                    c.run_turn('synthetic', 'model', 'low')
                self.assertEqual(self.methods(trace), ['account/read', 'account/rateLimits/read'])
                self.assertEqual(c.quota_status['state'], 'pause')
                self.assertFalse(c.start_pending)

    def test_api_auth_never_reads_quota_or_starts_turn(self):
        c, trace = self.server([GOOD], account={'type': 'apiKey'})
        with self.assertRaises(ProbeError):
            c.run_turn('synthetic', 'model', 'low')
        self.assertEqual(self.methods(trace), ['account/read'])

    def test_each_turn_refreshes_and_does_not_reuse_previous_allow(self):
        c, trace = self.server([GOOD, dict(GOOD, ordinaryUsageAllowed=False)])
        self.assertEqual(c.run_turn('first', 'model', 'low'), ('ok', set()))
        with self.assertRaises(ProbeError):
            c.run_turn('second', 'model', 'low')
        self.assertEqual(self.methods(trace), ['account/read', 'account/rateLimits/read', 'turn/start',
                                             'account/read', 'account/rateLimits/read'])

    def test_pause_can_resume_only_after_fresh_successful_read(self):
        c, trace = self.server([dict(GOOD, ordinaryUsageAllowed=False), GOOD])
        with self.assertRaises(ProbeError):
            c.run_turn('first', 'model', 'low')
        self.assertEqual(c.run_turn('second', 'model', 'low'), ('ok', set()))
        self.assertEqual(self.methods(trace), ['account/read', 'account/rateLimits/read',
                                             'account/read', 'account/rateLimits/read', 'turn/start'])

    def test_account_switch_stops_second_turn(self):
        c, trace = self.server([GOOD, dict(GOOD, accountId='other')])
        c.run_turn('first', 'model', 'low')
        with self.assertRaisesRegex(ProbeError, 'account_changed'):
            c.run_turn('second', 'model', 'low')
        self.assertEqual(self.methods(trace).count('turn/start'), 1)


if __name__ == '__main__':
    unittest.main()
