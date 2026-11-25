import json
import subprocess
import unittest
from unittest.mock import patch

import search_isolation_probe as isolation


class IsolationProbeTests(unittest.TestCase):
    def test_local_capability_or_explicit_unavailable(self):
        report = isolation.probe()
        self.assertIn(report['status'], ('capability_verified', 'unverified'))
        if 'checks' in report:
            self.assertTrue(all(report['checks'].values()), report)
            self.assertFalse(report['g3Passed'])
        else:
            self.assertIn(report['reason'], ('missing_host_utility', 'unsupported_runtime_profile', 'namespace_or_worker_failed', 'launch_failed'))

    def test_missing_utility_does_not_launch(self):
        with patch.object(isolation.shutil, 'which', return_value=None), patch.object(isolation.subprocess, 'run') as run:
            self.assertEqual(isolation.probe()['reason'], 'missing_host_utility')
            run.assert_not_called()

    def test_bad_worker_reports_never_pass_or_leak(self):
        for output in (b'private diagnostic', b'{}', json.dumps(dict.fromkeys(isolation.KEYS, 1)).encode()):
            with self.subTest(output=output), patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, b'private stderr')):
                report = isolation.probe()
                self.assertEqual(report, {'status': 'unverified', 'reason': 'invalid_worker_report'})

    def test_failure_and_timeout_never_pass(self):
        for failure, reason in ((subprocess.TimeoutExpired('bwrap', 1), 'timeout'), (OSError('private detail'), 'launch_failed')):
            with self.subTest(reason=reason), patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation.subprocess, 'run', side_effect=failure):
                self.assertEqual(isolation.probe(), {'status': 'unverified', 'reason': reason})

    def test_boundary_uses_sterile_environment_and_closed_fds(self):
        def run(command, **kwargs):
            self.assertEqual(kwargs['env'], {'PATH': isolation.os.defpath})
            self.assertIs(kwargs['close_fds'], True)
            self.assertNotIn('--bind', command)
            self.assertIn('--die-with-parent', command)
            mounts = [command[index + 2] for index, flag in enumerate(command) if flag == '--ro-bind']
            self.assertNotIn('/usr', mounts)
            self.assertNotIn('/lib', mounts)
            self.assertNotIn('/etc', mounts)
            self.assertIn('/public-ca.pem', mounts)
            return subprocess.CompletedProcess(command, 1, b'', b'private error')
        with patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation.subprocess, 'run', side_effect=run):
            self.assertEqual(isolation.probe()['reason'], 'namespace_or_worker_failed')

    def test_timeout_validation(self):
        for value in (0, -1, float('inf'), float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                isolation.probe(value)

    def test_missing_profile_never_falls_back_to_broad_mounts(self):
        with patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation, 'MOUNTS', (('/nonexistent-modelmate-profile', '/runtime'),)), patch.object(isolation.subprocess, 'run') as run:
            self.assertEqual(isolation.probe()['reason'], 'unsupported_runtime_profile')
            run.assert_not_called()
