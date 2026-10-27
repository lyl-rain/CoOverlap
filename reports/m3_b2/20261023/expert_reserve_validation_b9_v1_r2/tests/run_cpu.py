#!/usr/bin/env python3
"""Run the B9-r1 CPU suites and write one authoritative CPU_RESULTS.json.

structural : deployment/validate_m3_b9_cpu.py (protocol, matrix, selection record,
             entry/controller, fairness/retention, attribution, manifest, syntax)
evaluation : tests/test_evaluate_b9_cpu.py (official statistics on the real B8
             fixture, missing/uncertain/unstarted records, prediction use, condition
             rejection, frozen rejection, full CLI on a B9-structure fixture)
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
B9 = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(B9 / 'deployment'))


def run_structural():
    spec = importlib.util.spec_from_file_location(
        'validate_m3_b9_cpu', B9 / 'deployment' / 'validate_m3_b9_cpu.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with redirect_stdout(io.StringIO()):
        return mod.main()


def run_evaluation():
    spec = importlib.util.spec_from_file_location(
        'test_evaluate_b9_cpu', str(HERE / 'test_evaluate_b9_cpu.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    suite = unittest.defaultTestLoader.loadTestsFromModule(mod)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    failures = [str(t) for t, _ in result.failures] + [str(t) for t, _ in result.errors]
    return dict(passed=result.testsRun - len(result.failures) - len(result.errors),
                total=result.testsRun, failures=failures, log=stream.getvalue())


def main():
    structural = run_structural()
    evaluation = run_evaluation()
    total = structural['total'] + evaluation['total']
    passed = structural['passed'] + evaluation['passed']
    doc = dict(schema='m3_b9_cpu_v2', protocol='m3_b9_expert_reserve_validation_v1',
               revision='r1', passed=passed, total=total,
               structural=dict(passed=structural['passed'], total=structural['total'],
                               checks=structural['checks']),
               evaluation=dict(passed=evaluation['passed'], total=evaluation['total'],
                               failures=evaluation['failures'],
                               cases=[line.strip() for line in evaluation['log'].splitlines()
                                      if line.strip().endswith('... ok')]))
    (B9 / 'CPU_RESULTS.json').write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n')
    (B9 / 'CPU_TESTS.log').write_text(
        'structural %d/%d\nevaluation %d/%d\n\n%s' % (
            structural['passed'], structural['total'], evaluation['passed'],
            evaluation['total'], evaluation['log']))
    print(json.dumps(dict(passed=passed, total=total,
                          structural=structural['passed'], evaluation=evaluation['passed'],
                          failures=evaluation['failures']), indent=2))
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
