"""List retained analyzers or run their synthetic CPU checks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LEGACY = 'scripts/day1_pm_cpu_trace_repair_20261111'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='Show actual analyzer and test paths')
    parser.add_argument('command', nargs='?', choices=['check'], help='Run synthetic Trace checks')
    args = parser.parse_args()
    if args.list:
        print(json.dumps(dict(trace=LEGACY+'/analyze_trace.py',
                              api_gaps=LEGACY+'/analyze_cpu_gaps.py',
                              synthetic_test=LEGACY+'/test_gap_accounting.py',
                              GPU_required=False), indent=2))
        return 0
    if args.command == 'check':
        try:
            return subprocess.run([sys.executable, '-B', LEGACY+'/test_gap_accounting.py'],
                                  cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                                  timeout=45).returncode
        except subprocess.TimeoutExpired:
            return 124
    parser.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
