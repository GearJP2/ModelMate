#!/usr/bin/env python3
"""Read Codex account, model catalog and quota without starting a model turn."""
import argparse
import json
import math
import sys

from modelmate import Connection, ProbeError, inspect


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
