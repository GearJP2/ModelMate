"""Synthetic CLI decisions and native RPC; no installed Codex or model required."""
import io
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import probe_policy


SERVER = r'''
import json,sys
from pathlib import Path
trace,mode=sys.argv[1:]
root=Path.cwd()
marker=json.loads((root/'.codex/config.toml').read_text().split('=',1)[1].strip())
for line in sys.stdin:
 req=json.loads(line)
 with open(trace,'a') as stream:stream.write(json.dumps(req)+'\n')
 method=req.get('method')
 if 'id' not in req:continue
 if method=='initialize':result={}
 elif method=='config/read':
  config={'developer_instructions':marker}
  result={'config':config,'layers':[{'name':{'type':'project','dotCodexFolder':str(root/'.codex')},'config':config}]}
  if mode=='untrusted':result['layers'][0]['disabledReason']='untrusted'
  if mode=='wrong_config':result['config']={'developer_instructions':'PRIVATE_CONFIG'}
  if mode=='wrong_layer':result['layers'][0]['name']['dotCodexFolder']='/PRIVATE_PATH'
  if mode=='missing_marker':result['layers'][0]['config']={}
  if mode=='layers_not_list':result['layers']={'private':'PRIVATE_CONFIG'}
  if req.get('params',{}).get('cwd')!=str(root):result={'config':{},'layers':[]}
 elif method=='command/exec':
  text=req['params']['command'][1]
  if mode=='rpc_error' and text.endswith('DENY'):
   print(json.dumps({'id':req['id'],'error':{'code':-32000,'message':'PRIVATE_ERROR'}}),flush=True);continue
  if mode=='approval':
   print(json.dumps({'id':99,'method':'item/commandExecution/requestApproval','params':{'private':'PRIVATE_REQUEST'}}),flush=True);continue
  if mode=='eof':break
  result={'exitCode':0,'stdout':text,'stderr':''}
  if mode=='bad_baseline':result['stdout']='PRIVATE_OUTPUT'
  if mode=='bool_exit':result['exitCode']=False
  if mode=='timeout_exit':result['exitCode']=124
 else:raise RuntimeError(method)
 print(json.dumps({'id':req['id'],'result':result}),flush=True)
'''


class PolicyProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Path(self.temp.name) / 'trace'
        self.cli_calls = []

    def cli(self, command, **kwargs):
        self.cli_calls.append(command)
        self.assertEqual(command[0], 'codex')
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
        if command[1:] == ['--version']:
            return subprocess.CompletedProcess(command, 0, b'codex-cli 0.169.0\n', b'PRIVATE_STDERR')
        self.assertEqual(command[1:3], ['execpolicy', 'check'])
        rules = Path(command[4]).read_text()
        self.assertIn('decision="forbidden"', rules)
        decision = 'forbidden' if command[-1].endswith('DENY') else 'allow'
        return subprocess.CompletedProcess(command, 0, json.dumps({'decision': decision}).encode(), b'')

    def probe(self, mode='executed'):
        original = probe_policy.PolicyProbeConnection
        def factory(command, timeout, *, cwd):
            self.assertEqual(command[0], 'codex')
            key, value = command[2].split('=', 1)
            self.assertEqual(key.split('.'), ['projects'])
            table = re.fullmatch(r'\{("(?:[^"\\]|\\.)*")=\{trust_level="trusted"\}\}', value)
            self.assertIsNotNone(table, 'Trust must be a single-entry inline TOML table')
            self.assertEqual(json.loads(table[1]), cwd)
            self.assertEqual(command[3:], ['app-server', '--stdio'])
            self.scratch = Path(cwd)
            return original([sys.executable, '-u', '-c', SERVER, str(self.trace), mode], timeout, cwd=cwd)
        with patch('probe_policy.subprocess.run', side_effect=self.cli), \
             patch('probe_policy.PolicyProbeConnection', side_effect=factory):
            result = probe_policy.probe_policy(.5)
        self.assertFalse(self.scratch.exists())
        self.assertNotIn('PRIVATE_', json.dumps(result))
        return result

    def records(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def test_trust_value_preserves_dots_spaces_and_unicode_in_project_path(self):
        original = tempfile.TemporaryDirectory
        def directory(**kwargs):
            return original(dir=self.temp.name, prefix='โปรเจกต์.v1 ')
        with patch('probe_policy.tempfile.TemporaryDirectory', side_effect=directory):
            result = self.probe()
        self.assertIn('โปรเจกต์.v1 ', str(self.scratch))
        self.assertTrue(result['projectConfigObserved'])
        self.assertEqual(result['phase'], 'finished')

    def test_executed_forbidden_fixture_never_certifies_permission_parity(self):
        result = self.probe()
        self.assertEqual(result['phase'], 'finished')
        self.assertEqual(result['forbiddenCommand'], 'executed')
        self.assertEqual(result['permissionParity'], 'not_established_for_fixture')
        commands = [r['params'] for r in self.records() if r['method'] == 'command/exec']
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertEqual(command['sandboxPolicy'], {'type': 'readOnly', 'networkAccess': False})
            self.assertNotIn('env', command)
        self.assertEqual({r['method'] for r in self.records()},
                         {'initialize', 'initialized', 'config/read', 'command/exec'})
        self.assertEqual(len(self.cli_calls), 3)
        config_request = next(r for r in self.records() if r['method'] == 'config/read')
        self.assertEqual(config_request['params'], {'includeLayers': True, 'cwd': str(self.scratch)})
        self.assertTrue(all(result['configEvidence'].values()))
        self.assertTrue(all(type(value) is bool for value in result['configEvidence'].values()))

    def test_rpc_error_is_unverified_not_successful_denial(self):
        result = self.probe('rpc_error')
        self.assertEqual(result['baseline'], 'executed')
        self.assertEqual(result['forbiddenCommand'], 'unverified')
        self.assertEqual(result['permissionParity'], 'unverified')
        self.assertEqual(result['phase'], 'forbiddenCommand')

    def test_config_must_be_effective_and_enabled_before_commands(self):
        for mode in ('untrusted', 'wrong_config', 'wrong_layer', 'missing_marker', 'layers_not_list'):
            with self.subTest(mode=mode):
                self.trace.unlink(missing_ok=True)
                result = self.probe(mode)
                self.assertFalse(result['projectConfigObserved'])
                self.assertEqual(result['phase'], 'project_config')
                self.assertFalse(all(result['configEvidence'].values()))
                self.assertFalse(any(r['method'] == 'command/exec' for r in self.records()))

    def test_bad_result_or_eof_stops_without_retry_or_second_command(self):
        for mode in ('bad_baseline', 'bool_exit', 'timeout_exit', 'eof'):
            with self.subTest(mode=mode):
                self.trace.unlink(missing_ok=True)
                result = self.probe(mode)
                self.assertEqual(result['baseline'], 'unverified')
                self.assertEqual(sum(r['method'] == 'command/exec' for r in self.records()), 1)

    def test_approval_request_is_never_accepted(self):
        result = self.probe('approval')
        self.assertEqual(result['baseline'], 'unverified')
        self.assertFalse(any('result' in r or 'error' in r for r in self.records()))

    def test_cli_failure_stops_before_server_and_redacts_details(self):
        with patch('probe_policy.subprocess.run', side_effect=subprocess.TimeoutExpired('PRIVATE_COMMAND', 1)), \
             patch('probe_policy.PolicyProbeConnection') as connection:
            result = probe_policy.probe_policy(.5)
        connection.assert_not_called()
        self.assertEqual(result['phase'], 'version')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_wrong_rule_decision_stops_before_server(self):
        calls = 0
        def wrong_decision(command, **kwargs):
            nonlocal calls
            calls += 1
            if command[1] == '--version':
                return self.cli(command, **kwargs)
            return subprocess.CompletedProcess(command, 0, b'{"decision":"allow"}', b'')
        with patch('probe_policy.subprocess.run', side_effect=wrong_decision), \
             patch('probe_policy.PolicyProbeConnection') as connection:
            result = probe_policy.probe_policy(.5)
        connection.assert_not_called()
        self.assertEqual(calls, 3)
        self.assertEqual(result['fixtureDecisions'], 'unverified')
        self.assertEqual(result['phase'], 'rule_evaluation')

    def test_server_initialization_failure_sends_no_command(self):
        with patch('probe_policy.subprocess.run', side_effect=self.cli), \
             patch('probe_policy.PolicyProbeConnection', side_effect=probe_policy.ProbeError('PRIVATE_FAILURE')):
            result = probe_policy.probe_policy(.5)
        self.assertEqual(result['phase'], 'server_initialize')
        self.assertEqual(result['baseline'], 'unverified')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_help_does_not_run_probe_and_cli_never_reports_gate_passed(self):
        with patch('sys.argv', ['probe_policy.py']), patch('sys.stdout', new_callable=io.StringIO), \
             patch('probe_policy.probe_policy') as probe:
            self.assertEqual(probe_policy.main(), 0)
            probe.assert_not_called()
        for state, code in (('executed', 1), ('unverified', 2)):
            with patch('sys.argv', ['probe_policy.py', '--run']), patch('sys.stdout', new_callable=io.StringIO), \
                 patch('probe_policy.probe_policy', return_value={'forbiddenCommand': state}):
                self.assertEqual(probe_policy.main(), code)

    def test_invalid_timeouts_do_not_start_probe(self):
        for value in ('nan', 'inf', '0', '-1', '61'):
            with self.subTest(timeout=value), patch('sys.argv', ['probe_policy.py', '--run', '--timeout', value]), \
                 patch('sys.stderr', new_callable=io.StringIO), patch('probe_policy.probe_policy') as probe:
                with self.assertRaises(SystemExit) as raised:
                    probe_policy.main()
                self.assertEqual(raised.exception.code, 2)
                probe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
