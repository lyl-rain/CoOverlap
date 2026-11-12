"""Run the reviewed CPU-only checks without importing GPU entry points."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='List commands without running them')
    args = parser.parse_args()
    commands = [
        ['scripts/validate_m2_cpu.py'],
        ['scripts/validate_period_obligations_cpu.py'],
        ['scripts/day1_pm_cpu_trace_repair_20261111/test_gap_accounting.py'],
    ]
    if args.list:
        print(json.dumps(commands, indent=2)); return 0
    results = []
    for command in commands:
        print('Checking ' + command[0], flush=True)
        try:
            run = subprocess.run([sys.executable, '-B', *command], cwd=ROOT,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                                          COOVERLAP_SOURCE_ROOT=str(ROOT)), timeout=45)
            results.append(dict(test=command[0], returncode=run.returncode))
        except subprocess.TimeoutExpired:
            results.append(dict(test=command[0], timeout=True, returncode=124))
    print(json.dumps(dict(scope='CPU contracts and synthetic trace intervals only; no GPU or sysfs access',
                          results=results), indent=2))
    return int(any(r['returncode'] != 0 for r in results))

if __name__ == '__main__':
    raise SystemExit(main())
