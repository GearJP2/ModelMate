import io
import json
import subprocess
import tempfile
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
            self.assertEqual(report['runtimeSha256'], isolation.hashlib.sha256(
                isolation.Path(isolation.__file__).with_name('modelmate.py').read_bytes()).hexdigest())
        else:
            self.assertIn(report['reason'], ('missing_host_utility', 'unsupported_runtime_profile', 'namespace_or_worker_failed', 'launch_failed'))

    def test_missing_utility_does_not_launch(self):
        with patch.object(isolation.shutil, 'which', return_value=None), patch.object(isolation, 'run_search_process') as run:
            self.assertEqual(isolation.probe()['reason'], 'missing_host_utility')
            run.assert_not_called()

    def test_bad_worker_reports_never_pass_or_leak(self):
        for output in (b'private diagnostic', b'{}', b'x' * 65537, b'[' * 1500,
                       b'{"checks":{},"checks":{}}',
                       json.dumps(dict(checks=dict.fromkeys(isolation.KEYS, 1), response='{}')).encode()):
            with self.subTest(output=output), patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation, 'run_search_process', return_value=subprocess.CompletedProcess([], 0, output, b'private stderr')):
                report = isolation.probe()
                self.assertEqual(report, {'status': 'unverified', 'reason': 'invalid_worker_report'})

    def test_failure_and_timeout_never_pass(self):
        for failure, reason in ((subprocess.TimeoutExpired('bwrap', 1), 'timeout'), (OSError('private detail'), 'launch_failed'), (isolation.ProbeError('output cap'), 'output_limit')):
            with self.subTest(reason=reason), patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation, 'run_search_process', side_effect=failure):
                self.assertEqual(isolation.probe(), {'status': 'unverified', 'reason': reason})

    def test_boundary_uses_sterile_environment_and_closed_fds(self):
        def run(command, content, **kwargs):
            self.assertEqual(content, b'{"query": "synthetic public query"}')
            self.assertEqual(kwargs['output_limit'], 65536)
            self.assertNotIn('--bind', command)
            self.assertIn('--die-with-parent', command)
            mounts = [command[index + 2] for index, flag in enumerate(command) if flag == '--ro-bind']
            self.assertNotIn('/usr', mounts)
            self.assertNotIn('/lib', mounts)
            self.assertNotIn('/etc', mounts)
            self.assertIn('/public-ca.pem', mounts)
            return subprocess.CompletedProcess(command, 1, b'', b'private error')
        with patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation, 'run_search_process', side_effect=run):
            self.assertEqual(isolation.probe()['reason'], 'namespace_or_worker_failed')

    def test_timeout_validation(self):
        for value in (0, -1, float('inf'), float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                isolation.probe(value)

    def test_missing_profile_never_falls_back_to_broad_mounts(self):
        with patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation, 'MOUNTS', (('/nonexistent-modelmate-profile', '/runtime'),)), patch.object(isolation, 'run_search_process') as run:
            self.assertEqual(isolation.probe()['reason'], 'unsupported_runtime_profile')
            run.assert_not_called()

    def test_worker_side_effect_attempt_cannot_pass(self):
        # Audit instrumentation observes a deliberate effect in the trusted test worker.
        child = isolation.CHILD.replace("runtime['run_search_worker'](worker_input, worker_output)", "os.system('synthetic-forbidden-command'); runtime['run_search_worker'](worker_input, worker_output)")
        with patch.object(isolation, 'CHILD', child):
            report = isolation.probe()
        self.assertEqual(report['status'], 'unverified')
        self.assertIn(report['reason'], ('missing_host_utility', 'unsupported_runtime_profile',
            'namespace_or_worker_failed', 'launch_failed'))

    def test_false_worker_check_is_not_promoted_to_capability_verified(self):
        checks = dict.fromkeys(isolation.KEYS, True)
        checks['injectionRemainsData'] = False
        response = dict(version=1, source='Wikipedia', host='en.wikipedia.org', query='synthetic public query', results=[])
        result = subprocess.CompletedProcess([], 0, json.dumps(dict(checks=checks, response=json.dumps(response))).encode(), b'')
        with patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation, 'run_search_process', return_value=result):
            report = isolation.probe()
        self.assertEqual(report['status'], 'unverified')
        self.assertFalse(report['checks']['injectionRemainsData'])
        self.assertFalse(report['g3Passed'])

    def test_mismatched_child_response_is_rejected_by_parent(self):
        response = dict(version=1, source='Wikipedia', host='en.wikipedia.org', query='different query', results=[])
        report = dict(checks=dict.fromkeys(isolation.KEYS, True), response=json.dumps(response))
        result = subprocess.CompletedProcess([], 0, json.dumps(report).encode(), b'')
        with patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation, 'run_search_process', return_value=result):
            self.assertEqual(isolation.probe(), {'status': 'unverified', 'reason': 'invalid_worker_response'})

    def test_lifecycle_failure_never_passes_on_successful_parser_checks(self):
        response = dict(version=1, source='Wikipedia', host='en.wikipedia.org', query='synthetic public query', results=[])
        report = dict(checks=dict.fromkeys(isolation.KEYS, True), response=json.dumps(response))
        first = subprocess.CompletedProcess([], 0, json.dumps(report).encode(), b'')
        for failure in (subprocess.TimeoutExpired('synthetic launcher', 2),
                        OSError('private detail'), isolation.ProbeError('overflow')):
            with self.subTest(failure=type(failure).__name__), patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation, 'run_search_process', side_effect=[first, failure]) as run:
                self.assertEqual(isolation.probe(), {'status': 'unverified', 'reason': 'namespace_lifecycle_unverified'})
                self.assertEqual(run.call_count, 2)
                self.assertIn(isolation.LIFECYCLE_CHILD, run.call_args.args[0])
                self.assertEqual(run.call_args.kwargs['timeout'], 2)

    def test_lifecycle_wrong_exit_or_missing_readiness_cannot_pass(self):
        response = dict(version=1, source='Wikipedia', host='en.wikipedia.org', query='synthetic public query', results=[])
        report = dict(checks=dict.fromkeys(isolation.KEYS, True), response=json.dumps(response))
        first = subprocess.CompletedProcess([], 0, json.dumps(report).encode(), b'')
        for code, output in ((0, b''), (7, b'namespace-descendant-ready\n')):
            last = subprocess.CompletedProcess([], code, output, b'')
            with self.subTest(code=code), patch.object(isolation.shutil, 'which', return_value='/usr/bin/bwrap'), patch.object(isolation, 'run_search_process', side_effect=[first, last]):
                report = isolation.probe()
                self.assertEqual(report['status'], 'unverified')
                self.assertFalse(report['checks']['namespaceExitStopsDetachedChild'])

    def test_parent_death_failure_cannot_pass_otherwise_successful_checks(self):
        response = dict(version=1, source='Wikipedia', host='en.wikipedia.org', query='synthetic public query', results=[])
        first = subprocess.CompletedProcess([],0,json.dumps(dict(checks=dict.fromkeys(isolation.KEYS,True),response=json.dumps(response))).encode(),b'')
        second = subprocess.CompletedProcess([],0,b'namespace-descendant-ready\n',b'')
        with patch.object(isolation.shutil,'which',return_value='/usr/bin/bwrap'),patch.object(isolation,'run_search_process',side_effect=[first,second]),patch.object(isolation,'probe_parent_death',return_value=False):
            report=isolation.probe()
        self.assertEqual(report['status'],'unverified')
        self.assertFalse(report['checks']['namespaceParentDeathStopsDetachedChild'])

    def test_without_parent_death_flag_control_does_not_pass(self):
        original=isolation.probe_parent_death
        def no_parent_policy(command,runtime_copy,root):
            return original([value for value in command if value!='--die-with-parent'],runtime_copy,root)
        with patch.object(isolation,'probe_parent_death',side_effect=no_parent_policy):
            report=isolation.probe()
        self.assertEqual(report['status'],'unverified')
        if 'checks' in report:
            self.assertFalse(report['checks']['namespaceParentDeathStopsDetachedChild'])

    def test_deliberately_exposed_synthetic_secret_is_detected(self):
        original=isolation.run_search_process
        def expose_fixture(command, content, **kwargs):
            command=command.copy()
            secret=command[command.index(isolation.CHILD)+1]
            index=command.index('--')
            command[index:index]=['--ro-bind',secret,secret]
            return original(command,content,**kwargs)
        with patch.object(isolation,'run_search_process',side_effect=expose_fixture):
            report=isolation.probe()
        self.assertEqual(report['status'],'unverified')
        if 'checks' in report:
            self.assertFalse(report['checks']['privateFileHidden'])
            self.assertFalse(report['checks']['procRootCannotReadPrivateFile'])


class LiveWikipediaProbeTests(unittest.TestCase):
    def input_file(self, text):
        stream = tempfile.TemporaryFile('w+')
        self.addCleanup(stream.close)
        stream.write(text);stream.seek(0)
        return stream

    def test_default_command_never_calls_live_lookup(self):
        with patch.object(isolation, 'probe', return_value={'status':'capability_verified'}), patch.object(isolation, 'live_wikipedia') as live, patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(isolation.main([]),0)
            live.assert_not_called()

    def test_eof_cancellation_and_stale_token_never_launch(self):
        for answer in ('','CANCEL\n','SEARCH stale\n','SEARCH deadbeef'):
            with self.subTest(answer=answer), patch.object(isolation.secrets,'token_hex',return_value='deadbeef'), patch.object(isolation,'run_isolated_search') as launch:
                report=isolation.live_wikipedia('en',self.input_file(answer),io.StringIO())
                self.assertEqual(report['status'],'cancelled')
                self.assertEqual(report['searchLaunches'],0)
                launch.assert_not_called()

    def test_confirmed_fixture_query_runs_once_and_report_does_not_dump_sources(self):
        results=[dict(title='Synthetic private title',excerpt='Synthetic private body',url='https://en.wikipedia.org/?curid=7')]
        with patch.object(isolation.secrets,'token_hex',return_value='deadbeef'), patch.object(isolation,'run_isolated_search',return_value=results) as launch:
            report=isolation.live_wikipedia('en',self.input_file('SEARCH deadbeef\nprivate history\n'),io.StringIO())
        launch.assert_called_once_with('Python programming language','en.wikipedia.org','Wikipedia')
        self.assertEqual(report['status'],'scoped_live_verified')
        self.assertFalse(report['g3Passed'])
        self.assertEqual(report['modelTurnsRequested'],0)
        self.assertEqual(len(report['runtimeSha256']),64)
        self.assertNotIn('Synthetic private',json.dumps(report))
        self.assertNotIn('private history',json.dumps(report))
        self.assertNotIn('deadbeef',json.dumps(report))

    def test_lookup_failure_and_invalid_results_are_sanitized_without_retry(self):
        for value in (isolation.ProbeError('private trace'),[],[dict(title='Bad',excerpt='',url='file:///private')]):
            options=dict(side_effect=value) if isinstance(value,Exception) else dict(return_value=value)
            with self.subTest(value=type(value).__name__),patch.object(isolation.secrets,'token_hex',return_value='deadbeef'),patch.object(isolation,'run_isolated_search',**options) as launch:
                report=isolation.live_wikipedia('th',self.input_file('SEARCH deadbeef\n'),io.StringIO())
                self.assertEqual(report['status'],'unverified')
                self.assertEqual(report['searchLaunches'],1)
                self.assertNotIn('private',json.dumps(report))
                self.assertEqual(launch.call_count,1)

    def test_live_flag_routes_to_separate_zero_model_mode(self):
        with patch.object(isolation,'probe',side_effect=AssertionError('offline probe not selected')),patch.object(isolation,'live_wikipedia',return_value={'status':'cancelled'}) as live,patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(isolation.main(['--live-wikipedia','en']),2)
            self.assertEqual(live.call_args.args[0],'en')
