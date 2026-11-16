import json
import sys
import unittest
from unittest.mock import Mock

from doctor import Connection, ProbeError, inspect


class DoctorTests(unittest.TestCase):
    def test_pagination_privacy_and_unknown_quota(self):
        connection = Mock()
        connection.request.side_effect = [
            {}, {'account': {'type': 'chatgpt', 'planType': 'plus', 'email': 'PRIVATE'}},
            {'data': [{'model': 'first', 'hidden': False}], 'nextCursor': 'page2'},
            {'data': [{'model': 'hidden', 'hidden': True}, {'model': 'second'}]},
            {'accountId': 'PRIVATE', 'rateLimits': {'primary': {'usedPercent': 71, 'resetsAt': 123}}},
        ]
        report = inspect(connection)
        self.assertEqual([m['model'] for m in report['models']], ['first', 'second'])
        self.assertIsNone(report['ordinaryUsageAllowed'])
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertEqual(report['quota']['default']['primary']['usedPercent'], 71)
        self.assertEqual(connection.request.call_args_list[3].args[1]['cursor'], 'page2')
        self.assertEqual(connection.send.call_args.args[0], {'method': 'initialized'})

    def test_api_key_login_stops_before_catalog_or_quota(self):
        connection = Mock()
        connection.request.side_effect = [{}, {'account': {'type': 'apiKey'}}]
        with self.assertRaises(ProbeError):
            inspect(connection)
        self.assertEqual(connection.request.call_count, 2)

    def test_protocol_roundtrip_notifications_and_stderr(self):
        code = '''import sys,json
for line in sys.stdin:
 x=json.loads(line)
 print('private stderr',file=sys.stderr,flush=True)
 print(json.dumps({'method':'notification'}),flush=True)
 print(json.dumps({'id':x['id'],'result':{'ok':True}}),flush=True)
'''
        c = Connection([sys.executable, '-u', '-c', code], 2)
        try:
            self.assertEqual(c.request('account/read'), {'ok': True})
            with self.assertRaises(ProbeError):
                c.request('turn/start')
        finally:
            c.close()
        self.assertIsNotNone(c.process.returncode)

    def test_timeout_and_shutdown(self):
        c = Connection([sys.executable, '-c', 'import time; time.sleep(30)'], .1)
        try:
            with self.assertRaisesRegex(ProbeError, 'timed out'):
                c.request('account/read')
        finally:
            c.close()
        self.assertIsNotNone(c.process.returncode)

    def test_closed_or_malformed_stream(self):
        for code in ["pass", "print('not json',flush=True)"]:
            with self.subTest(code=code):
                c = Connection([sys.executable, '-c', code], 2)
                try:
                    with self.assertRaises(ProbeError):
                        c.request('account/read')
                finally:
                    c.close()


if __name__ == '__main__':
    unittest.main()
