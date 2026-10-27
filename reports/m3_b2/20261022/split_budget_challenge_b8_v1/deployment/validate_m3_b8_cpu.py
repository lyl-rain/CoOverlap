"""Targeted CPU checks for the B8 split x budget challenge (no GPU, no hardware).

The symbolic device, real ownership state machine, real candidate loop and real
retention/attribution paths are reused from the frozen B3/B4/B5 CPU evidence.
Passing here proves symbolic logic and preparation consistency only, never GPU
correctness, performance or a tail/WCET claim.
"""
import argparse
import ast
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from m2_clean_core import gate_retention_layout, retention_layout
from m2_executor import VersionedKV
from m3_b2_backend import BoundaryBackend
from m3_b2_core import run_segment
from m3_b3_orchestrate import describe_active, export_failed_retention, run_candidates
from m3_b3_plan import CONTROL, THREE
from m3_b8_plan import (BUDGETS, CELLS, CYCLES, GATE_PLAN, PLANS, PROTOCOL, RUN,
                        SEGMENT_IDS, budget, manifest, manifests, protocol)
from validate_m3_b3_cpu import PlanDevice, SNAPS, maths
from validate_m3_b3_entry_cpu import _augment, _math_for, _require, _write_tables

HERE = Path(__file__).resolve().parent
PREDICTION = HERE.parent / 'prediction' / 'PREDICTION.json'
PREDICTION_RECEIPT = HERE.parent / 'prediction' / 'PREDICTION_RECEIPT.json'


def records():
    return [dict(index=i, candidate=c['cell'], cell=c['cell'], pass_=c['pass_'],
                 policy=c['policy'], plan=c['plan'], period_ns=c['period_ns'],
                 segment_id=SEGMENT_IDS[i], status='NOT_STARTED') for i, c in enumerate(RUN)]


def kind_maths(plan):
    return {k: (lambda p: None) for k in plan.kinds}


def run_cell(cell, expert=74_000_000, b1=49_000_000, b2=44_000_000):
    plan = PLANS[cell['plan']]
    device = PlanDevice(plan=plan, expert=expert, b1=b1, b2=b2)
    conf = manifest(cell['period_ns'])
    backend = BoundaryBackend(device, SNAPS, 'performance',
                              layout=retention_layout(CYCLES, plan), plan=plan)
    manager = VersionedKV(plan)
    record = {}
    run_segment(manager, SNAPS, cell['policy'], backend, record, device.clock,
                conf=conf, expect=conf)
    return device, backend, manager, record


class ProtocolTests(unittest.TestCase):
    def test_four_conditions_and_declared_order(self):
        p = protocol()
        self.assertEqual(p['id'], PROTOCOL)
        self.assertEqual([c['id'] for c in CELLS],
                         ['A_p180_two_b2_boundary', 'B_p180_three_b2_boundary',
                          'C_p140_two_b2_boundary', 'D_p140_three_b2_boundary'])
        self.assertEqual([c['period_ns'] for c in CELLS],
                         [180_000_000, 180_000_000, 140_000_000, 140_000_000])
        self.assertEqual([c['plan'] for c in CELLS],
                         [CONTROL.id, THREE.id, CONTROL.id, THREE.id])
        self.assertTrue(all(c['policy'] == 'b2_boundary' for c in CELLS))
        self.assertEqual([r['cell'][0] for r in RUN], ['A', 'B', 'C', 'D', 'D', 'C', 'B', 'A'])
        self.assertEqual(len(set(SEGMENT_IDS)), 8)
        self.assertEqual(sorted({r['period_ns'] for r in RUN}), sorted(BUDGETS))
        self.assertEqual(p['pass_order'], [['A', 'B', 'C', 'D'], ['D', 'C', 'B', 'A']])

    def test_each_manifest_drives_releases_deadlines_refreshes_and_plan(self):
        for ns in BUDGETS:
            conf = manifest(ns)
            self.assertEqual(conf['schema'], PROTOCOL)
            self.assertEqual(conf['period_ns'], ns)
            self.assertEqual(len(conf['experts']), CYCLES)
            self.assertEqual(len(conf['refreshes']), CYCLES // 2)
            self.assertEqual(set(conf['block_plans']), {CONTROL.id, THREE.id})
            for e in conf['experts']:
                self.assertEqual(e['release_ns'], e['id'] * ns + 15_000_000,
                                 'Expert release = jP + phase')
                self.assertEqual(e['deadline_ns'] - e['release_ns'], ns,
                                 'Expert relative deadline = P')
                self.assertEqual(e['version'], e['id'] // 2)
            for r in conf['refreshes']:
                self.assertEqual(r['release_ns'], r['id'] * 2 * ns,
                                 'refresh release = 2qP')
                self.assertEqual(r['deadline_ns'] - r['release_ns'], 2 * ns,
                                 'refresh relative deadline = 2P')
        self.assertEqual(set(manifests()), set(BUDGETS))
        self.assertIs(manifests()[180_000_000], manifests()[180_000_000],
                      'both 180 ms conditions must share one canonical manifest object')

    def test_budget_and_work_are_recomputed_from_the_declared_trajectory(self):
        b = budget()
        self.assertEqual(b['layouts'][CONTROL.id]['nbytes'], 487_320_064)
        self.assertEqual(b['layouts'][THREE.id]['nbytes'], 597_617_152)
        self.assertEqual(b['bank_bytes'], 597_617_152)
        self.assertEqual(b['gate_layout']['nbytes'], 124_121_472)
        self.assertEqual(b['batch_payload_bytes'], 4 * 487_320_064 + 4 * 597_617_152)
        self.assertEqual(b['gpu_and_pinned_bytes'], 2 * b['bank_bytes'])
        self.assertEqual(b['timeline_s'], 10.24)
        self.assertEqual(b['disk']['admission_bytes'], 12 * 1024**3)
        self.assertLess(b['disk']['estimate_bytes'], b['disk']['admission_bytes'])
        p = protocol()
        self.assertEqual(p['work']['batch']['total_C'], 52)
        self.assertEqual(p['work']['batch']['total_E'], 70)
        self.assertEqual(p['work']['observed_ledger']['contexts'], 49)
        self.assertEqual(p['work']['observed_ledger']['experts'], 69)
        self.assertEqual(p['work']['observed_ledger']['rows'], 13_400)
        self.assertEqual(p['work']['batch']['timed_C'], 32)
        self.assertEqual(p['work']['batch']['timed_E'], 64)
        self.assertEqual(p['work']['batch']['segment_bootstrap_C'], 8)

    def test_work_counts_follow_segments_and_the_actual_entry_calls(self):
        p = protocol()
        w = p['work']['batch']
        self.assertEqual(w['timed_C'], len(RUN) * CYCLES // 2)
        self.assertEqual(w['timed_E'], len(RUN) * CYCLES)
        self.assertEqual(w['segment_bootstrap_C'], len(RUN))
        pre_c = ['warmup_C', 'reference_C', 'D1_C', 'prefix_reference_C',
                 'assembly_C', 'old_reader_gate_C', 'interrupt_gate_C']
        pre_e = ['reference_E', 'D1_E', 'assembly_E', 'old_reader_gate_E',
                 'interrupt_gate_E']
        self.assertEqual(w['total_C'], sum(w[k] for k in pre_c)
                         + w['segment_bootstrap_C'] + w['timed_C'])
        self.assertEqual(w['total_E'], sum(w[k] for k in pre_e) + w['timed_E'])
        self.assertEqual(p['work']['observed_ledger']['contexts'],
                         w['total_C'] - w['warmup_C'] - w['D1_C'])
        self.assertEqual(p['work']['observed_ledger']['experts'],
                         w['total_E'] - w['D1_E'])
        self.assertEqual(p['work']['observed_ledger']['rows'],
                         (w['total_C'] - w['warmup_C'] - w['D1_C']) * 20
                         + (w['total_E'] - w['D1_E']) * 180)
        # Actual entry call sites: two prefix references via the (0,1) loop,
        # one assembly sequence, one gate loop over two gates, one candidate loop.
        entry = (HERE/'pi05_m3_b8_challenge.py').read_text()
        self.assertEqual(entry.count('run_prefix_reference('), 1)
        self.assertIn('for slot in (0, 1):', entry)
        self.assertEqual(entry.count('run_gate('), 1)
        self.assertIn('for name, segment_id, interleave in ((OLD_READER_GATE,', entry)
        self.assertEqual(entry.count('run_candidates('), 1)
        self.assertIn('seg_confs = [manifests()[c[\'period_ns\']] for c in RUN]', entry)
        self.assertIn('canonical_confs = [manifest(c[\'period_ns\']) for c in RUN]', entry)

    def test_gate_budget_matches_the_entry_plan(self):
        import inspect
        import pi05_m3_b8_challenge as entry
        actual = gate_retention_layout(CYCLES, GATE_PLAN)
        self.assertIs(GATE_PLAN, THREE)
        self.assertIs(entry.GATE_PLAN, GATE_PLAN)
        self.assertEqual((actual['count'], actual['nbytes']), (15, 124_121_472))
        b = budget()
        self.assertEqual(b['gate_layout'], dict(plan=GATE_PLAN.id, count=15, nbytes=124_121_472))
        self.assertEqual(protocol()['gates']['plan'], GATE_PLAN.id)
        tree = ast.parse(inspect.getsource(entry.main))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        layouts = [n for n in calls if isinstance(n.func, ast.Name)
                   and n.func.id == 'gate_retention_layout']
        self.assertEqual(len(layouts), 1)
        self.assertIsInstance(layouts[0].args[1], ast.Name)
        self.assertEqual(layouts[0].args[1].id, 'GATE_PLAN')
        gates = [n for n in calls if isinstance(n.func, ast.Name) and n.func.id == 'run_gate']
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0].args[4].id, 'GATE_PLAN')


class EntryTests(unittest.TestCase):
    def test_eight_segments_drive_their_own_plan_budget_and_policy(self):
        device = PlanDevice()
        recs = records()
        confs = [manifests()[c['period_ns']] for c in RUN]
        expects = [manifest(c['period_ns']) for c in RUN]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = run_candidates(device, SNAPS, RUN, PLANS, 'performance', out,
                                     device.clock, _require, kind_maths, list(SEGMENT_IDS),
                                     None, recs, _augment, _write_tables,
                                     confs=confs, expects=expects)
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(SEGMENT_IDS))
        self.assertEqual([r['segment_id'] for r in summary], list(SEGMENT_IDS))
        self.assertEqual([r['period_ns'] for r in summary], [c['period_ns'] for c in RUN])
        self.assertEqual([r['plan'] for r in summary], [c['plan'] for c in RUN])
        self.assertEqual([r['policy'] for r in summary], [c['policy'] for c in RUN])
        for row, rec in zip(summary, recs):
            self.assertEqual(rec['protocol'], PROTOCOL)
            self.assertEqual(rec['mode'], row['policy'])
            self.assertEqual(rec['block_plan']['id'], row['plan'])
            self.assertEqual(rec['manifest']['period_ns'], row['period_ns'])
            self.assertEqual(len(rec['units']), CYCLES)
        self.assertEqual(device.segment_ids, set(SEGMENT_IDS))
        self.assertFalse(device.leased)

    def test_two_and_three_block_obligations_are_complete(self):
        for cell in CELLS:
            device, backend, manager, r = run_cell(cell)
            plan = PLANS[cell['plan']]
            self.assertEqual(r['status'], 'DRAINED_PENDING_VALIDATION')
            self.assertEqual(r['block_plan']['id'], plan.id)
            self.assertEqual(len(r['units']), CYCLES)
            self.assertEqual(r['statistics']['units_are_declared_groups'], [list(g) for g in plan.groups])
            self.assertEqual(len(r['experts']), CYCLES)
            self.assertEqual(len(r['published']), CYCLES // 2)
            for q in range(CYCLES // 2):
                blocks = [x['block'] for x in r['decisions']
                          if x['kind'] == 'Context' and x['id'] == q]
                self.assertEqual(blocks, list(range(len(plan))))
            binds = {row[1]: row[2] for row in r['journal'] if row[0] == 'bind'}
            self.assertEqual(binds, {'E%d' % j: j // 2 for j in range(CYCLES)})
            backend.validate_and_persist()

    def test_140_long_work_exercises_queue_backlog_versions_and_reader_protection(self):
        for cell in (CELLS[2], CELLS[3]):   # C/D at 140 ms
            device, backend, manager, r = run_cell(cell, expert=220_000_000, b2=180_000_000)
            self.assertEqual(r['status'], 'DRAINED_PENDING_VALIDATION')
            self.assertGreaterEqual(r['statistics']['cycle_counts']['denominator'], 8)
            self.assertGreater(r['statistics']['cycle_counts']['FAIL'], 0,
                               'long work must produce deadline FAILs, not be discarded')
            self.assertTrue(any(p.get('context_backlog', 0) > 1 for p in r['progress']),
                            'long Context must create a visible backlog')
            self.assertTrue(any(len(p.get('ready_experts') or []) > 1 for p in r['progress'])
                            or any(p.get('version_wait_experts') for p in r['progress']),
                            'long Expert work must exercise queueing/version wait')
            self.assertEqual(len(r['units']), CYCLES)
            binds = {row[1]: row[2] for row in r['journal'] if row[0] == 'bind'}
            self.assertEqual(binds, {'E%d' % j: j // 2 for j in range(CYCLES)})
            # A successful drain means no illegal reclaim of a reader-pinned slot.
            self.assertNotEqual(r['status'], 'ILLEGAL_RECLAIM')
            backend.validate_and_persist()

    def test_performance_fail_does_not_stop_later_segments(self):
        device = PlanDevice(expert=220_000_000, b2=180_000_000)
        recs = records()
        confs = [manifests()[c['period_ns']] for c in RUN]
        expects = [manifest(c['period_ns']) for c in RUN]
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_candidates(device, SNAPS, RUN, PLANS, 'performance', Path(tmp),
                                     device.clock, _require, kind_maths, list(SEGMENT_IDS),
                                     None, recs, _augment, _write_tables,
                                     confs=confs, expects=expects)
        self.assertEqual(len(summary), len(RUN))
        self.assertEqual([r['segment_id'] for r in summary], list(SEGMENT_IDS))
        self.assertTrue(all(r['status'] == 'PASS' for r in recs),
                        'performance FAIL must not turn into a correctness stop')
        self.assertTrue(any(r['statistics']['cycle_counts']['FAIL'] > 0 for r in recs))
        self.assertEqual([r['period_ns'] for r in summary], [c['period_ns'] for c in RUN])

    def test_total_cutoff_preserves_denominators_and_incomplete(self):
        from m3_b3_orchestrate import run_candidates as loop

        class Failing(PlanDevice):
            def run_math(self, key, slot, kind):
                if self.label() == SEGMENT_IDS[5] and key == 'E3':
                    raise TimeoutError('injected fixed-cutoff')
                return super().run_math(key, slot, kind)

        device = Failing()
        active = {}
        recs = records()
        confs = [manifests()[c['period_ns']] for c in RUN]
        expects = [manifest(c['period_ns']) for c in RUN]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TimeoutError):
                loop(device, SNAPS, RUN, PLANS, 'performance', Path(tmp), device.clock,
                     _require, kind_maths, list(SEGMENT_IDS), None, recs, _augment, None,
                     active=active, confs=confs, expects=expects)
        record = recs[5]
        self.assertEqual(record['status'], 'INCOMPLETE')
        self.assertEqual(record['statistics']['cycle_counts']['denominator'], CYCLES)
        self.assertEqual(record['statistics']['refresh_counts']['denominator'], CYCLES // 2)
        self.assertTrue(record['remaining_Expert_ids'])
        self.assertTrue(record['remaining_Context_ids'] or record['published'])
        info = describe_active(active)
        self.assertEqual(info['segment_id'], SEGMENT_IDS[5])
        self.assertEqual(info['period_ns'], 140_000_000)
        self.assertEqual(info['plan'], RUN[5]['plan'])

    def test_first_and_middle_failure_attribution_keep_bank_unusable(self):
        for index in (0, 4):
            class Failing(PlanDevice):
                def run_math(self, key, slot, kind):
                    if self.label() == SEGMENT_IDS[index] and key == 'E2':
                        raise TimeoutError('injected at %d' % index)
                    return super().run_math(key, slot, kind)

            device = Failing()
            active = {}
            recs = records()
            confs = [manifests()[c['period_ns']] for c in RUN]
            expects = [manifest(c['period_ns']) for c in RUN]
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                with self.assertRaises(TimeoutError):
                    run_candidates(device, SNAPS, RUN, PLANS, 'performance', out,
                                   device.clock, _require, kind_maths, list(SEGMENT_IDS),
                                   None, recs, _augment, None, active=active,
                                   confs=confs, expects=expects)
                info = describe_active(active)
                self.assertEqual(info['segment_id'], SEGMENT_IDS[index])
                self.assertEqual(info['plan'], RUN[index]['plan'])
                self.assertEqual(info['period_ns'], RUN[index]['period_ns'])
                status = export_failed_retention(device, active, out,
                                                 device.clock() + 10**12, device.clock)
                self.assertEqual(status['segment_id'], SEGMENT_IDS[index])
                self.assertEqual(status['layout_nbytes'],
                                 budget()['per_cell_segment_bytes'][RUN[index]['cell']])
                self.assertEqual(device.downloads, [(0, status['layout_nbytes'])])
                self.assertNotIn('PASS', status['status'])
                self.assertNotEqual(recs[index]['status'], 'PASS')


class PredictionTests(unittest.TestCase):
    def test_prediction_is_frozen_and_does_not_change_formal_domain(self):
        import m3_b8_plan as b8
        self.assertEqual(hashlib.sha256(PREDICTION.read_bytes()).hexdigest(),
                         b8.PREDICTION_SHA256)
        pred = json.loads(PREDICTION.read_text())
        self.assertEqual(pred['status'], 'EXTRAPOLATIVE_PREDICTION_NOT_VALIDATED')
        self.assertEqual(pred['condition_status'], 'OUT_OF_SOURCE_APPLICABILITY_DOMAIN')
        self.assertEqual(pred['formal_selector']['p180']['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(pred['formal_selector']['p140']['status'], 'UNSUPPORTED_INPUT')
        self.assertEqual(pred['prediction_fingerprint'], b8.PREDICTION_FINGERPRINT)
        self.assertEqual(len(pred['source']['condition_fingerprint']), 64)
        # The source freeze identity is the r1 freeze; no B8 measurement is read.
        self.assertIn('empirical_plan_selector_v1_r1', pred['source']['selector_dir'])
        self.assertEqual(pred['generated_from'],
                         'frozen r1 costs/rules/model only; no B8 measurement')

    def test_prediction_time_origin_is_consistent(self):
        pred = json.loads(PREDICTION.read_text())
        for letter in 'ABCD':
            for kind in ('typical', 'stress'):
                s = pred['cells'][letter]['scenarios'][kind]
                for e in s['experts']:
                    if e['completion_ms'] is not None and e['release_ms'] is not None:
                        self.assertAlmostEqual(e['response_ms'],
                                               round(e['completion_ms'] - e['release_ms'], 6),
                                               places=6)
                    if e['margin_ms'] is not None:
                        self.assertAlmostEqual(e['margin_ms'],
                                               round(e['deadline_ms'] - e['completion_ms'], 6),
                                               places=6)
                for c in s['cycles']:
                    if c['completion_ms'] is not None:
                        self.assertAlmostEqual(c['completion_ms'],
                                               round(c['release_ms'] + c['response_ms'], 6),
                                               places=6)
                        self.assertAlmostEqual(c['margin_ms'],
                                               round(c['deadline_ms'] - c['completion_ms'], 6),
                                               places=6)
                for r in s['refreshes']:
                    if r['completion_offset_ms'] is not None:
                        self.assertAlmostEqual(r['completion_offset_ms'],
                                               round(r['release_ms'] + r['response_ms'], 6),
                                               places=6)
                        self.assertAlmostEqual(r['margin_ms'],
                                               round(r['deadline_ms'] - r['completion_offset_ms'], 6),
                                               places=6)

    def test_prediction_does_not_write_back_r1_freeze(self):
        costs = Path('/Users/moblumen/Desktop/CoOverlap/reports/m3_b2/20261022/'
                     'empirical_plan_selector_v1_r1/freeze/TRAIN_COSTS.json')
        rules = costs.parent / 'RULES.json'
        freeze = costs.parent / 'FREEZE.json'
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (costs, rules, freeze)}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'pred'
            subprocess.run([sys.executable, str(HERE.parent/'prediction'/'predict_b8.py'),
                            '--out', str(out)], check=True, cwd=str(HERE.parent),
                           capture_output=True, text=True)
            self.assertTrue((out/'PREDICTION.json').exists())
            self.assertEqual(json.loads((out/'PREDICTION_RECEIPT.json').read_text())['status'],
                             'EXTRAPOLATIVE_PREDICTION_NOT_VALIDATED')
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (costs, rules, freeze)}
        self.assertEqual(before, after)


class ConsistencyTests(unittest.TestCase):
    def test_config_entry_and_controller_are_this_batch(self):
        config = json.loads((HERE/'CONFIG.json').read_text())
        self.assertEqual(config, protocol())
        import m3_b8_control as control
        self.assertEqual(control.PROTOCOL, PROTOCOL)
        source = Path(control.__file__).read_text()
        self.assertIn('from m3_b8_plan import PROTOCOL, protocol', source)
        self.assertEqual(source.count('--approved-m3-b8-split-budget-challenge-v1'), 3)
        self.assertNotIn('approved_m3_b5', source)
        entry = (HERE/'pi05_m3_b8_challenge.py').read_text()
        self.assertIn('confs=seg_confs', entry)
        self.assertIn('expects=canonical_confs', entry)
        self.assertIn('--approved-m3-b8-split-budget-challenge-v1', entry)
        self.assertNotIn('--approved-m3-b5', entry)
        self.assertNotIn('empirical_plan_selector', entry)
        self.assertNotIn('TRAIN_COSTS', entry)
        from m3_b3_orchestrate import run_candidates as rc
        self.assertIn('expects', rc.__code__.co_varnames)
        self.assertIn('confs', rc.__code__.co_varnames)

    def test_entry_dry_run_imports_no_gpu_and_reports_this_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [sys.executable, str(HERE/'pi05_m3_b8_challenge.py'),
                   '--dry-run', '--config', str(HERE/'CONFIG.json')]
            p = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr)
            data = json.loads(p.stdout)
            self.assertEqual(data['protocol']['id'], PROTOCOL)
            self.assertEqual(data['preparation_reuse']['source_sha256'],
                             'd91cdc465b87f1c76bc985cb0ea475176fe20cbf579dd2c8c824a92bef96ba18')

    def test_controller_submit_cannot_run_without_root(self):
        import m3_b8_control as control
        old = sys.argv
        sys.argv = ['m3_b8_control.py', 'submit', '--base', str(HERE),
                    '--run', str(HERE/'run_01'), '--credential-sha', '0'*64,
                    '--approved-m3-b8-split-budget-challenge-v1']
        try:
            with self.assertRaises(BaseException) as ctx:
                control.main()
            self.assertIsInstance(ctx.exception, PermissionError)
        finally:
            sys.argv = old


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                               for cls in (ProtocolTests, EntryTests, PredictionTests,
                                           ConsistencyTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests=result.testsRun,
                failures=len(result.failures), errors=len(result.errors),
                scope='CPU: four split x budget conditions, per-segment plan/P manifests,'
                      ' 8 unique segments and declared order, two-plan obligations, 140 ms'
                      ' queue/backlog/version/reader behavior, performance FAIL continues,'
                      ' cutoff denominators/INCOMPLETE, failure attribution, prediction freeze'
                      ' and time origin, config/entry/controller consistency; no GPU claim',
                model_starts=0, worker_starts=0, ssh=0, hardware_writes=0, scopes=0)
    if args.json:
        args.json.write_text(json.dumps(data, indent=2)+'\n')
    print(json.dumps(data, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
