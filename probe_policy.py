#!/usr/bin/env python3
"""Opt-in command-policy diagnostic. No model turns; never certifies permission parity."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile

from modelmate import Connection, ProbeError, __file__ as runtime_file


class PolicyProbeConnection(Connection):
    # Diagnostic only: do not add these methods to runtime workflow connections.
    allowed_methods = {'initialize', 'config/read', 'command/exec'}


def probe_policy(timeout=15):
    result = {'version': None, 'phase': 'version', 'fixtureDecisions': 'unverified',
              'projectConfigObserved': False, 'baseline': 'unverified',
              'forbiddenCommand': 'unverified', 'permissionParity': 'unverified',
              'scope': 'Synthetic printf only; no thread/model turn. Not managed-policy, approval or recovery proof.'}
    connection = None
    try:
        result['probeSha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        result['runtimeSha256'] = hashlib.sha256(Path(runtime_file).read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix='modelmate-policy-') as directory:
            root = Path(directory)
            config_dir = root / '.codex'
            rules_dir = config_dir / 'rules'
            rules_dir.mkdir(parents=True)
            (root / '.git').mkdir()
            marker = 'ModelMate synthetic policy fixture; no model turns.'
            (config_dir / 'config.toml').write_text(
                'developer_instructions = ' + json.dumps(marker) + '\n', encoding='utf-8')
            rules = rules_dir / 'probe.rules'
            commands = (['printf', 'MM-POLICY-ALLOW'], ['printf', 'MM-POLICY-DENY'])
            rules.write_text(''.join('prefix_rule(pattern=' + json.dumps(command)
                + ', decision=' + json.dumps(decision) + ')\n'
                for command, decision in zip(commands, ('allow', 'forbidden'))), encoding='utf-8')
            result['rulesSha256'] = hashlib.sha256(rules.read_bytes()).hexdigest()

            def cli(arguments):
                completed = subprocess.run(['codex'] + arguments, cwd=directory,
                    stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
                if completed.returncode != 0 or len(completed.stdout) > 65536:
                    raise ProbeError('Policy diagnostic CLI prerequisite failed.')
                return completed.stdout.decode('utf-8')

            version = cli(['--version']).strip()
            if not re.fullmatch(r'codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.-]+)?', version):
                raise ProbeError('Unrecognized CLI version.')
            result['version'] = version
            result['phase'] = 'rule_evaluation'
            for command, decision in zip(commands, ('allow', 'forbidden')):
                report = json.loads(cli(['execpolicy', 'check', '--rules', str(rules), '--'] + command))
                if not isinstance(report, dict) or report.get('decision') != decision:
                    raise ProbeError('Synthetic rule decision mismatch.')
            result['fixtureDecisions'] = 'matched'
            result['phase'] = 'server_initialize'

            # Trust only this disposable fixture, through a process-local override.
            # Keep user/managed configuration and credentials in their normal locations.
            # CLI key paths split on dots literally; put the path in the TOML value.
            trust = 'projects={' + json.dumps(directory, ensure_ascii=False) + '={trust_level="trusted"}}'
            connection = PolicyProbeConnection(['codex', '-c', trust, 'app-server', '--stdio'],
                                               timeout, cwd=directory)
            try:
                connection.request('initialize', {'clientInfo': {'name': 'modelmate_policy_probe', 'version': '0.1.0'}})
                connection.send({'method': 'initialized'})
                result['phase'] = 'project_config'
                # config/read resolves project layers from its own explicit cwd.
                config = connection.request('config/read', {'includeLayers': True, 'cwd': directory})
                layers = config.get('layers')
                fixture_layers = [layer for layer in (layers if isinstance(layers, list) else [])
                    if isinstance(layer, dict) and isinstance(layer.get('name'), dict)
                    and layer['name'].get('type') == 'project'
                    and layer['name'].get('dotCodexFolder') == str(config_dir)]
                enabled_layers = [layer for layer in fixture_layers if layer.get('disabledReason') is None]
                result['configEvidence'] = {
                    'effectiveMarkerMatches': isinstance(config.get('config'), dict)
                        and config['config'].get('developer_instructions') == marker,
                    'layersPresent': isinstance(layers, list),
                    'fixtureLayerPresent': bool(fixture_layers),
                    'fixtureLayerEnabled': bool(enabled_layers),
                    'fixtureLayerMarkerMatches': any(isinstance(layer.get('config'), dict)
                        and layer['config'].get('developer_instructions') == marker for layer in enabled_layers),
                }
                if not all(result['configEvidence'].values()):
                    raise ProbeError('Synthetic project config not confirmed; no commands sent.')
                result['projectConfigObserved'] = True
                for command, field in zip(commands, ('baseline', 'forbiddenCommand')):
                    result['phase'] = field
                    observed = connection.request('command/exec', {'command': command, 'cwd': directory,
                        'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False},
                        'timeoutMs': max(1, int(min(timeout, 10) * 1000)), 'outputBytesCap': 1024})
                    if (type(observed.get('exitCode')) is not int
                            or observed['exitCode'] != 0 or observed.get('stdout') != command[1]
                            or observed.get('stderr') != ''):
                        raise ProbeError('Command result did not confirm execution.')
                    result[field] = 'executed'
                # Config visibility + standalone rule evaluation do not prove server rule loading.
                result['permissionParity'] = 'not_established_for_fixture'
                result['phase'] = 'finished'
            finally:
                connection.close()
                connection = None
    except (ProbeError, OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        # RPC errors may mean unsupported capability, not successful policy enforcement.
        result['diagnostic'] = 'prerequisite_or_execution_unverified'
    finally:
        if connection is not None:
            connection.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='run synthetic rule checks and at most two native printf commands; no inference')
    parser.add_argument('--timeout', type=float, default=15, help='per-process/RPC deadline in seconds')
    args = parser.parse_args()
    if not args.run:
        parser.print_help()
        return 0
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 60:
        parser.error('--timeout must be finite, positive and at most 60')
    try:
        result = probe_policy(args.timeout)
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, indent=2))
    # No outcome from this narrow probe certifies the runtime gate.
    return 1 if result['forbiddenCommand'] == 'executed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
