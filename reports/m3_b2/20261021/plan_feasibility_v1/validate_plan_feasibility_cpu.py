"""CPU checks for the single-stream timing model and the b2_slack counterexample.

Analysis-only: no model, no CUDA, no device import. It recomputes the executed
batch from its raw fields, checks the model against those statistics, and runs
declared counterfactuals. A passing model check is NOT GPU correctness, NOT a
performance proof, and NOT a WCET argument.
"""
import argparse
import json
import sys
import unittest
from pathlib import Path

from plan_model import PLANS, THREE, TWO, simulate
from scenarios import (MEASURED, b2_slack_arithmetic, crossing_scenario, idle_scenario,
                       lower_bound, ordering_scenarios, overrun_scenario,
                       slow_version_scenario, termination_scenario)

HERE = Path(__file__).resolve().parent
RUN = HERE.parent/'split_priority_ablation_v1_r2'/'gpu_run_01'
CELLS = RUN/'offline'/'CELLS.json'
RESULT = RUN/'board'/'run_01'/'model'/'result.json'


def measured_raw():
    """Recompute the executed statistics from the raw result fields."""
    d = json.load(open(RESULT))
    out = {}
    for s in d['segments']:
        t0 = s['t0_ns']
        cycles = s['statistics']['cycles']
        ev = [c for c in cycles if c['cycle'] % 2 == 0]
        od = [c for c in cycles if c['cycle'] % 2 == 1]
        out.setdefault(s['cell'], []).append(dict(
            cycle_even=sum(c['response_upper_ns'] for c in ev)/len(ev)/1e6,
            cycle_odd=sum(c['response_upper_ns'] for c in od)/len(od)/1e6,
            expert_even=sum(c['expert_response_upper_ns'] for c in ev)/len(ev)/1e6,
            vlm_even=sum(c['VLM_response_upper_ns'] for c in ev)/len(ev)/1e6,
            publish=sum(r['ready_upper_ns'] for r in s['statistics']['refreshes'])/len(s['statistics']['refreshes'])/1e6,
            tail_starts=[c['VLM_completion_upper_ns']-t0 for c in od],
            statuses=[c['status'] for c in cycles],
            refreshes=[r['status'] for r in s['statistics']['refreshes']]))
    return d, out


class ModelTests(unittest.TestCase):
    def test_actual_recomputation_matches_the_stored_cells(self):
        d, raw = measured_raw()
        stored = json.load(open(CELLS))
        for cell, rows in raw.items():
            mean = lambda k: sum(r[k] for r in rows)/len(rows)
            self.assertLess(abs(mean('cycle_even')-stored[cell]['cycle_resp_even']), 5e-3)
            self.assertLess(abs(mean('cycle_odd')-stored[cell]['cycle_resp_odd']), 5e-3)
            self.assertLess(abs(mean('expert_even')-stored[cell]['expert_resp_even']), 5e-3)
            self.assertLess(abs(mean('publish')-stored[cell]['refresh_ready_mean']), 5e-3)
            for r in rows:
                self.assertNotIn('FAIL', r['statuses'])
                self.assertNotIn('FAIL', r['refreshes'])
        self.assertEqual(len(d['segments']), 8)
        self.assertEqual(sum(len(row['statuses']) for rows in raw.values() for row in rows), 64)
        self.assertEqual(sum(len(row['refreshes']) for rows in raw.values() for row in rows), 32)

    def test_model_reproduces_measured_means_within_stated_residual(self):
        residuals = {}
        for name, policy, key in ((TWO, 'serial_context', ('two_9_9', 'serial_context')),
                                  (TWO, 'b2_boundary', ('two_9_9', 'b2_boundary')),
                                  (THREE, 'serial_context', ('three_prefix_9_9', 'serial_context')),
                                  (THREE, 'b2_boundary', ('three_prefix_9_9', 'b2_boundary'))):
            s = simulate(name, policy, cycles=8).summary()
            m = MEASURED[key]
            residuals[key] = dict(cycle_even=s['cycle_even']-m['cycle_even'],
                                  cycle_odd=s['cycle_odd']-m['cycle_odd'],
                                  publish=s['publish']-m['publish'])
            self.assertLess(abs(s['cycle_even']-m['cycle_even']), 1.5)
            self.assertLess(abs(s['cycle_odd']-m['cycle_odd']), 0.5)
            self.assertLess(abs(s['publish']-m['publish']), 1.5)
        extremes = [v for r in residuals.values() for v in r.values()]
        self.assertLess(max(abs(x) for x in extremes), 1.5,
                        'model residual must stay within the stated band')

    def test_obligation_assignment_is_the_frozen_one(self):
        self.assertEqual(TWO.groups, ((0,), (1,)))
        self.assertEqual(THREE.groups, ((0, 1), (2,)))
        conf = json.load(open(HERE.parent/'split_priority_ablation_v1_r2'/'deployment'/'CONFIG.json'))
        self.assertEqual(conf['plans']['two_9_9']['groups'], [[0], [1]])
        self.assertEqual(conf['plans']['three_prefix_9_9']['groups'], [[0, 1], [2]])
        # the even cycle's VLM obligation is group 0 only; the tail is the odd unit
        two = simulate(TWO, 'b2_boundary', cycles=8).summary()
        self.assertAlmostEqual(two['vlm_even'], TWO.blocks[0]-15, delta=1.5)
        three = simulate(THREE, 'b2_boundary', cycles=8).summary()
        # in the three-block plan the Expert is inserted between P and Encoder0-8,
        # so the same even unit now completes after the Expert: P + Expert + B1
        self.assertAlmostEqual(three['vlm_even'], THREE.blocks[0]+75.16+THREE.blocks[1]-15, delta=2.0)

    def test_lower_bound_is_conditional_not_physical(self):
        b = lower_bound(TWO, 75.16)
        s = simulate(TWO, 'b2_boundary', cycles=8).summary()
        self.assertEqual(b['unit_ms'], round(TWO.blocks[0], 3))
        self.assertAlmostEqual(b['even_cycle_ms'], TWO.blocks[0]+75.16-15, places=3)
        self.assertGreater(s['cycle_even'], b['even_cycle_ms'])
        self.assertLess(s['cycle_even']-b['even_cycle_ms'], 0.5,
                        'measured-model even cycle is within 0.5 ms of the serial-sum bound')
        self.assertIn('serial-sum', lower_bound.__doc__ or 'serial-sum')

    def test_boundary_services_even_expert_before_its_vlm_unit_completes(self):
        b = simulate(TWO, 'b2_boundary', cycles=8).summary()
        s = simulate(TWO, 'serial_context', cycles=8).summary()
        self.assertGreater(s['cycle_even']-b['cycle_even'], 40.0)
        self.assertAlmostEqual(b['vlm_even'], TWO.blocks[0]-15, delta=2.0)
        self.assertGreater(s['expert_even'], s['vlm_even'])


class CounterexampleTests(unittest.TestCase):
    def test_review_arithmetic(self):
        r = b2_slack_arithmetic()
        self.assertAlmostEqual(r['boundary']['tail_done'], 200.6, places=6)
        self.assertAlmostEqual(r['boundary']['expert_done'], 276.2, places=6)
        self.assertAlmostEqual(r['boundary']['expert_response'], 81.2, places=6)
        self.assertAlmostEqual(r['boundary']['cycle_response'], 81.2, places=6)
        self.assertAlmostEqual(r['delayed']['expert_done'], 270.6, places=6)
        self.assertAlmostEqual(r['delayed']['tail_done'], 315.2, places=6)
        self.assertAlmostEqual(r['delayed']['expert_response'], 75.6, places=6)
        self.assertAlmostEqual(r['delayed']['cycle_response'], 120.2, places=6)
        self.assertAlmostEqual(r['expert_delta'], -5.6, places=6)
        self.assertAlmostEqual(r['cycle_delta'], 39.0, places=6)

    def test_no_release_crosses_a_tail_in_the_measured_trajectory(self):
        d, raw = measured_raw()
        for s in d['segments']:
            t0 = s['t0_ns']
            releases = [x['release_ns']-t0 for x in s['decisions'] if x['kind'] == 'Expert']
            ends = [o['gpu_completion_upper_host_ns']-t0 for o in s['operations']
                    if o['key'].endswith(('/B2', '/B3'))]
            starts = [o['gpu_completion_upper_host_ns']-o.get('lower_ns', 0) for o in s['operations']][:1]
            for rel in releases:
                for end in ends:
                    self.assertFalse(end-45.0 < rel < end,
                                     'a release fell inside a tail window: %s %.2f' % (s['segment_id'], rel))

    def test_delayed_tail_improves_expert_but_worsens_cycle_and_refresh(self):
        base, slack = crossing_scenario()
        b, s = base.summary(), slack.summary()
        self.assertEqual(b['status'], 'DRAINED')
        self.assertEqual(s['status'], 'DRAINED')
        self.assertLess(s['expert_odd'], b['expert_odd'], 'the delay must improve the Expert metric')
        self.assertGreater(s['cycle_odd'], b['cycle_odd']+50, 'the delay must worsen the odd cycle')
        self.assertGreater(s['publish'], b['publish']+100, 'the delay must move the refresh later')
        self.assertEqual(b['counts']['FAIL'], 0)
        self.assertEqual(s['counts']['FAIL'], 0)

    def test_expert_first_and_block_first_differ_by_the_tail(self):
        o = ordering_scenarios()
        self.assertGreater(o['block_first'].summary()['cycle_even'],
                           o['expert_first'].summary()['cycle_even']+40)
        self.assertAlmostEqual(o['block_first'].summary()['cycle_even'],
                               o['serial'].summary()['cycle_even'], places=1)
        for k, v in o.items():
            self.assertEqual(v.summary()['counts']['FAIL'], 0)

    def test_artificial_idle_is_paid_by_the_cycle_and_the_refresh(self):
        base = simulate(TWO, 'b2_boundary', cycles=8).summary()
        idle = idle_scenario(50.0).summary()
        self.assertGreater(idle['cycle_even'], base['cycle_even']+40)
        self.assertGreater(idle['publish'], base['publish']+40)
        self.assertGreater(idle['vlm_even'], base['vlm_even']+40,
                           'the idle cost lands on the VLM obligation, not only on the Expert')

    def test_version_not_ready_waits_and_keeps_the_miss(self):
        r = slow_version_scenario()
        s = r.summary()
        cyc2 = next(c for c in r.cycles if c['cycle'] == 2)
        self.assertGreater(cyc2['expert_response_ms'], 300.0)
        self.assertEqual(cyc2['status'], 'FAIL')
        self.assertEqual(s['counts']['denominator'], 8)
        self.assertEqual(s['counts']['FAIL'], 8)

    def test_overrun_keeps_real_misses_and_no_guarantee(self):
        r = overrun_scenario(200.0)
        s = r.summary()
        self.assertEqual(s['counts']['denominator'], 8)
        self.assertGreater(s['counts']['FAIL'], 0)
        self.assertEqual(s['counts']['PASS']+s['counts']['FAIL']+s['counts']['INCOMPLETE'],
                         s['counts']['denominator'])

    def test_termination_without_a_runnable_dependency(self):
        r = termination_scenario()
        s = r.summary()
        self.assertEqual(s['status'], 'NO_RUNNABLE_DEPENDENCY')
        self.assertGreater(s['counts']['INCOMPLETE'], 0)
        self.assertIn('guard', r.note)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c)
                               for c in (ModelTests, CounterexampleTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests=result.testsRun,
                failures=len(result.failures), errors=len(result.errors),
                scope='CPU/offline: model replay vs measured statistics, obligation groups, '
                      'b2_slack arithmetic and full-trajectory counterexample, ordering, idle, '
                      'version wait, overrun, termination; no GPU correctness/performance/WCET claim',
                model_starts=0, ssh=0, hardware_writes=0, scopes=0)
    if args.json:
        args.json.write_text(json.dumps(data, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
