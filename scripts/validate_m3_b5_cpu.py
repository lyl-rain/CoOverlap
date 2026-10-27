"""CPU checks for the two-anchor (180/240 ms) boundary-priority preparation.

Analysis/CPU only. A passing run is not GPU correctness, performance or WCET.
"""
import argparse, json, sys, tempfile, unittest
from pathlib import Path

from m2_clean_core import gate_retention_layout, retention_layout
from m2_executor import VersionedKV
from m3_b3_orchestrate import run_candidates
from m3_b3_plan import CONTROL, THREE
from m3_b5_plan import (ANCHORS, CELLS, CYCLES, GATE_PLAN, PLANS, PROTOCOL, RUN, SEGMENT_IDS,
                        budget, manifest, manifests, protocol)
from validate_m3_b3_cpu import SNAPS, PlanDevice
from validate_m3_b3_entry_cpu import _augment, _require, _write_tables

HERE = Path(__file__).resolve().parent
R1 = HERE.parent/'reports'/'m3_b2'/'20261021'/'plan_feasibility_v1_r1'


def records():
    return [dict(index=i, candidate=c['cell'], cell=c['cell'], pass_=c['pass_'],
                 policy=c['policy'], plan=c['plan'], period_ns=c['period_ns'],
                 segment_id=SEGMENT_IDS[i], status='NOT_STARTED') for i, c in enumerate(RUN)]


def maths(plan):
    return {k: (lambda p: None) for k in plan.kinds}


class ProtocolTests(unittest.TestCase):
    def test_four_conditions_and_order(self):
        p = protocol()
        self.assertEqual(p['id'], PROTOCOL)
        self.assertEqual([c['id'] for c in CELLS],
                         ['A_p240_serial', 'B_p240_boundary', 'C_p180_serial', 'D_p180_boundary'])
        self.assertEqual([c['period_ns'] for c in CELLS], [240_000_000, 240_000_000, 180_000_000, 180_000_000])
        self.assertEqual([c['policy'] for c in CELLS], ['serial_context', 'b2_boundary', 'serial_context', 'b2_boundary'])
        self.assertTrue(all(c['plan'] == CONTROL.id for c in CELLS))
        self.assertEqual([r['cell'][0] for r in RUN], ['A', 'B', 'C', 'D', 'D', 'C', 'B', 'A'])
        self.assertEqual(len(set(SEGMENT_IDS)), 8)
        self.assertEqual(sorted({r['period_ns'] for r in RUN}), sorted(ANCHORS))

    def test_manifests_drive_release_deadline_and_refresh(self):
        for ns in ANCHORS:
            conf = manifest(ns)
            self.assertEqual(conf['schema'], PROTOCOL)
            self.assertEqual(conf['period_ns'], ns)
            self.assertEqual(len(conf['experts']), CYCLES)
            self.assertEqual(len(conf['refreshes']), CYCLES // 2)
            for e in conf['experts']:
                self.assertEqual(e['release_ns'], e['id']*ns + 15_000_000, 'Expert release = jP + phase')
                self.assertEqual(e['deadline_ns'] - e['release_ns'], ns, 'relative deadline stays one period')
                self.assertEqual(e['version'], e['id'] // 2)
            for r in conf['refreshes']:
                self.assertEqual(r['release_ns'], r['id']*2*ns, 'refresh release from the raw period clock')
                self.assertEqual(r['deadline_ns'] - r['release_ns'], 2*ns)
        self.assertEqual(set(manifests()), set(ANCHORS))
        self.assertIs(manifests()[240_000_000], manifests()[240_000_000],
                      'both policies at one budget must reuse the same manifest object')

    def test_budget_is_recomputed_from_the_declared_trajectory(self):
        b = budget()
        self.assertEqual(b['layout']['nbytes'], retention_layout(CYCLES, CONTROL)['nbytes'])
        self.assertEqual(b['batch_payload_bytes'], 8*b['bank_bytes'])
        self.assertEqual(b['gpu_and_pinned_bytes'], 2*b['bank_bytes'])
        self.assertEqual(b['admission_bytes'], 12*1024**3)
        self.assertEqual(b['timeline_s'], sum(r['period_ns'] for r in RUN)*CYCLES/1e9)
        self.assertLess(b['estimate_bytes'], b['admission_bytes'])
        p = protocol()
        self.assertEqual(p['work']['batch']['total_C'], 52)
        self.assertEqual(p['work']['batch']['total_E'], 70)
        self.assertEqual(p['work']['observed_ledger']['rows'], 13_400)

    def test_gate_budget_matches_the_entry_plan(self):
        # The timed plan is two-block; the actual correctness gates remain
        # three-block. Checking only a budget against itself missed this defect.
        import ast
        import inspect
        import pi05_m3_b5_anchors as entry
        actual = gate_retention_layout(CYCLES, GATE_PLAN)
        self.assertIs(GATE_PLAN, THREE)
        self.assertIs(entry.GATE_PLAN, GATE_PLAN)
        self.assertEqual((actual['count'], actual['nbytes']), (15, 124_121_472))
        b = budget()
        self.assertEqual(b['gate_layout'], dict(plan=GATE_PLAN.id, count=actual['count'], nbytes=actual['nbytes']))
        self.assertEqual(b['gate_payload_bytes'], 2*actual['nbytes'])
        self.assertEqual(b['binary_total_bytes'], 4_646_026_472)
        self.assertEqual(b['estimate_bytes'], 5_653_281_189)
        self.assertEqual(b['estimate_gib'], 5.27)
        self.assertEqual(protocol()['gates']['plan'], GATE_PLAN.id)
        # Tie the declaration to the actual entry call sites without CUDA.
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

    def test_capacity_refuses_a_larger_layout(self):
        layout = retention_layout(CYCLES, CONTROL)
        with self.assertRaises(ValueError):
            from m2_clean_core import RetentionLedger
            RetentionLedger(layout, layout['nbytes'] - 1)


class EntryTests(unittest.TestCase):
    def test_eight_segments_drive_their_own_budget_and_policy(self):
        device = PlanDevice()
        recs = records()
        confs = [manifests()[c['period_ns']] for c in RUN]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = run_candidates(device, SNAPS, RUN, PLANS, 'performance', out, device.clock,
                                     _require, maths, list(SEGMENT_IDS), None, recs,
                                     _augment, _write_tables, confs=confs)
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(SEGMENT_IDS))
        self.assertEqual([r['segment_id'] for r in summary], list(SEGMENT_IDS))
        self.assertEqual([r['period_ns'] for r in summary], [c['period_ns'] for c in RUN])
        self.assertEqual([r['policy'] for r in summary], [c['policy'] for c in RUN])
        for row, rec in zip(summary, recs):
            self.assertEqual(rec['protocol'], PROTOCOL)
            self.assertEqual(rec['mode'], row['policy'])
            self.assertEqual(rec['block_plan']['id'], CONTROL.id)
            self.assertEqual(rec['manifest']['period_ns'], row['period_ns'])
            self.assertEqual(len(rec['units']), CYCLES)
        self.assertEqual(device.segment_ids, set(SEGMENT_IDS))
        self.assertFalse(device.leased)

    def test_failure_attributes_to_the_active_segment(self):
        from m3_b3_orchestrate import describe_active
        class Failing(PlanDevice):
            def run_math(self, key, slot, kind):
                if self.label() == SEGMENT_IDS[5] and key == 'E3':
                    raise TimeoutError('injected')
                return super().run_math(key, slot, kind)
        device = Failing()
        active = {}
        confs = [manifests()[c['period_ns']] for c in RUN]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TimeoutError):
                run_candidates(device, SNAPS, RUN, PLANS, 'performance', Path(tmp), device.clock,
                               _require, maths, list(SEGMENT_IDS), None, records(),
                               _augment, None, active=active, confs=confs)
        info = describe_active(active)
        self.assertEqual(info['segment_id'], SEGMENT_IDS[5])
        self.assertEqual(info['plan'], CONTROL.id)
        self.assertEqual(info['period_ns'], 180_000_000)


class ControllerTests(unittest.TestCase):
    def test_approved_flag_and_protocol_are_this_batch(self):
        import m3_b5_control as c
        src = Path(c.__file__).read_text()
        self.assertIn('from m3_b5_plan import PROTOCOL, protocol', src)
        self.assertIn("c['protocol']!=PROTOCOL", src)
        self.assertEqual(src.count('--approved-m3-b5-boundary-budget-anchors-v1'), 3)
        self.assertNotIn('approved_m3_b4', src)
        self.assertEqual(c.PROTOCOL, PROTOCOL)
        base = Path(c.__file__).resolve().parent
        old = sys.argv
        sys.argv = ['m3_b5_control.py', 'submit', '--base', str(base), '--run', str(base/'run_01'),
                    '--credential-sha', '0'*64, '--approved-m3-b5-boundary-budget-anchors-v1']
        try:
            with self.assertRaises(BaseException) as ctx:
                c.main()
            self.assertIsInstance(ctx.exception, PermissionError)
        finally:
            sys.argv = old


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--json', type=Path); args = ap.parse_args()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                               for cls in (ProtocolTests, EntryTests, ControllerTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests=result.testsRun,
                failures=len(result.failures), errors=len(result.errors),
                scope='CPU: four conditions, per-segment budget/policy, 180/240 releases and deadlines,'
                      ' 8 segments with per-segment manifests, failure attribution, controller token;'
                      ' no GPU correctness/performance claim',
                model_starts=0, ssh=0, hardware_writes=0, scopes=0)
    if args.json: args.json.write_text(json.dumps(data, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
