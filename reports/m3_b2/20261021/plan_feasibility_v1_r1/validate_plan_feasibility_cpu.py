"""CPU checks for the revised single-stream model, the statistics rebuild and
the b2_slack counterexample. Analysis-only: no model, no CUDA, no device.

A passing run proves model/ledger/logic consistency only. It is not GPU
correctness, performance or WCET evidence.
"""
import argparse
import json
import sys
import unittest
from pathlib import Path

from model_env import DEPLOYMENT, executor_identity
from plan_model import THREE, TWO, simulate
from rebuild_stats import (MUTATIONS, RUN_RESULT, compare_with_stored,
                           cross_check_operations, derived_responses, inject,
                           load_result, raw_maps, rebuild)
from scenarios import (MEASURED, b2_slack_arithmetic, crossing_scenario, idle_scenario,
                       illegal_reclaim_scenario, lower_bound, multi_expert_scenario,
                       ordering_scenarios, overrun_scenario, slow_version_scenario,
                       termination_scenario)

HERE = Path(__file__).resolve().parent
RUN = HERE.parent/'split_priority_ablation_v1_r2'/'gpu_run_01'
CELLS = RUN/'offline'/'CELLS.json'


class RebuildTests(unittest.TestCase):
    def test_rebuild_from_raw_maps_matches_stored_per_job(self):
        doc = load_result()
        self.assertEqual(len(doc['segments']), 8)
        total_cycles = total_refreshes = 0
        for seg in doc['segments']:
            raw = raw_maps(seg)
            stats = rebuild(raw)
            derived = derived_responses(raw, stats)
            bad = compare_with_stored(seg, stats, derived)
            self.assertEqual(bad, [], '%s: %s' % (seg['segment_id'], bad[:3]))
            self.assertEqual(len(stats['cycles']), 8)
            self.assertEqual(len(stats['refreshes']), 4)
            for row in stats['cycles']:
                self.assertEqual(row['release_ns'], raw['t0'] + row['cycle']*240_000_000 + 15_000_000,
                                 'cycle release = t0 + j*P + phase')
                self.assertEqual(row['deadline_ns'] - row['release_ns'], 240_000_000)
            for row in stats['refreshes']:
                self.assertEqual(row['ready_lower_ns'] is not None, True)
            total_cycles += len(stats['cycles'])
            total_refreshes += len(stats['refreshes'])
        self.assertEqual((total_cycles, total_refreshes), (64, 32))

    def test_operation_events_agree_with_raw_maps(self):
        doc = load_result()
        for seg in doc['segments']:
            bad = cross_check_operations(seg)
            self.assertEqual(bad, [], '%s: %s' % (seg['segment_id'], bad[:2]))

    def test_rebuild_detects_injected_faults(self):
        detected = {}
        for name, mutation in MUTATIONS.items():
            ok, detail = inject(mutation)
            detected[name] = ok
            self.assertTrue(ok, '%s not detected: %s' % (name, detail))
        self.assertEqual(len(detected), 4)

    def test_rebuild_is_independent_of_the_stored_statistics(self):
        """The audit probe: +1000 ms on a raw Expert upper must change the
        rebuilt cycle-0 response by +1000 ms while the stored statistics stay
        untouched (the old circular check could not see this)."""
        doc = load_result()
        seg = doc['segments'][0]
        raw = raw_maps(seg)
        base = rebuild(raw)
        seg2 = json.loads(json.dumps(seg))
        seg2['experts']['0'][1] += 1_000_000_000
        bumped = rebuild(raw_maps(seg2))
        delta = (bumped['cycles'][0]['response_upper_ns'] - base['cycles'][0]['response_upper_ns']) / 1e6
        self.assertAlmostEqual(delta, 1000.0, places=3)
        self.assertEqual(seg2['statistics']['cycles'][0]['response_upper_ns'],
                         seg['statistics']['cycles'][0]['response_upper_ns'],
                         'stored statistics must not be used as the source')


class LifecycleTests(unittest.TestCase):
    def test_executor_class_is_the_one_used(self):
        import m2_executor
        self.assertEqual(Path(m2_executor.__file__).resolve(), (DEPLOYMENT/'m2_executor.py').resolve())
        self.assertEqual(executor_identity()['sha256'],
                         '7890fa54896dd65635be741fddc50771bbc1b42b120abd6122c75170c6841654')

    def _published_pair(self):
        from m2_executor import VersionedKV
        from plan_model import SNAPSHOTS, Plan
        from plan_model import Fence
        plan = Plan('probe', (1.0, 1.0), (tuple(range(9)), tuple(range(9, 18))),
                    ((0,), (1,)), (9, 18), ('B1', 'B2'))
        kv = VersionedKV(plan=plan)
        def build(slot, snap):
            h = kv.begin(slot, snap)
            for b in range(2):
                f = Fence(); kv.submit_block(h, b, snap, plan.blocks[b], f); f.done = True; kv.poll_block(h)
            kv.publish(h)
            return h
        h0 = build(0, SNAPSHOTS[0])
        return kv, plan, h0, build

    def test_reclaim_requires_readers_done(self):
        kv, plan, h0, build = self._published_pair()
        from m2_executor import DECODER
        from plan_model import Fence, SNAPSHOTS
        h0b = kv.readers.get('E0')
        kv.bind('E0', SNAPSHOTS[0].noise_sha, version=0)
        kv.bind('E1', SNAPSHOTS[0].noise_sha, version=0)   # odd partner reservation
        h1 = build(1, SNAPSHOTS[1])                         # retires version 0
        self.assertEqual(kv.get(h1).phase, 'PUBLISHED')
        with self.assertRaises(RuntimeError):
            kv.reclaim(h0)                                  # two readers, both BOUND
        f = Fence(); kv.submit_expert('E0', kv.readers['E0'].handle, DECODER, f); f.done = True
        kv.poll_expert('E0')
        with self.assertRaises(RuntimeError):
            kv.reclaim(h0)                                  # E1 still reserved
        f = Fence(); kv.submit_expert('E1', kv.readers['E1'].handle, DECODER, f); f.done = True
        kv.poll_expert('E1')
        kv.reclaim(h0)                                      # now safe
        self.assertIsNone(kv.slots[0])

    def test_retired_version_cannot_take_a_new_reader(self):
        kv, plan, h0, build = self._published_pair()
        from plan_model import SNAPSHOTS
        h1 = build(1, SNAPSHOTS[1])
        with self.assertRaises(RuntimeError):
            kv.bind('E9', SNAPSHOTS[0].noise_sha, version=0)

    def test_generation_mismatch_is_detected(self):
        kv, plan, h0, build = self._published_pair()
        from plan_model import SNAPSHOTS
        build(1, SNAPSHOTS[1])          # retire version 0 without readers
        kv.reclaim(h0)
        h_new = kv.begin(0, SNAPSHOTS[1])
        self.assertNotEqual(h_new.generation, h0.generation)
        with self.assertRaises(ValueError):
            kv.get(h0)

    def test_phase_outside_period_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            simulate(TWO, 'b2_boundary', cycles=4, period=10.0, phase=15.0)
        self.assertIn('phase', str(ctx.exception))
        with self.assertRaises(ValueError):
            simulate(TWO, 'b2_boundary', cycles=4, period=10.0, phase=-1.0)

    def test_illegal_reclaim_is_refused_with_full_denominators(self):
        r = illegal_reclaim_scenario()
        s = r.summary()
        self.assertEqual(s['status'], 'ILLEGAL_RECLAIM')
        self.assertEqual(len(r.slot_refusals), 1)
        refusal = r.slot_refusals[0]
        self.assertEqual((refusal['refresh'], refusal['slot'], refusal['version']), (1, 0, 0))
        self.assertEqual(refusal['readers'], ['E1'])
        self.assertEqual(s['counts']['denominator'], 8)
        self.assertEqual(len(r.refreshes), 4)
        self.assertGreater(s['counts']['INCOMPLETE'], 0)

    def test_no_illegal_reclaim_in_the_supported_domain(self):
        for plan, policy in ((TWO, 'serial_context'), (TWO, 'b2_boundary'),
                             (THREE, 'serial_context'), (THREE, 'b2_boundary')):
            r = simulate(plan, policy, cycles=8)
            self.assertEqual(r.summary()['status'], 'DRAINED')
            self.assertEqual(r.slot_refusals, [])

    def test_awaiting_publication_still_services_other_experts(self):
        r = multi_expert_scenario()
        s = r.summary()
        self.assertEqual(s['status'], 'DRAINED')
        self.assertGreaterEqual(s['deferred'], 1)
        self.assertTrue(all(c['expert_response_ms'] is not None for c in r.cycles),
                        'an Expert was skipped while a publication was pending')
        self.assertEqual(s['counts']['INCOMPLETE'], 0)


class CounterexampleTests(unittest.TestCase):
    def test_model_reproduces_measured_means(self):
        for plan, policy, key in ((TWO, 'serial_context', ('two_9_9', 'serial_context')),
                                  (TWO, 'b2_boundary', ('two_9_9', 'b2_boundary')),
                                  (THREE, 'serial_context', ('three_prefix_9_9', 'serial_context')),
                                  (THREE, 'b2_boundary', ('three_prefix_9_9', 'b2_boundary'))):
            s = simulate(plan, policy, cycles=8).summary()
            m = MEASURED[key]
            self.assertLess(abs(s['cycle_even']-m['cycle_even']), 1.5)
            self.assertLess(abs(s['cycle_odd']-m['cycle_odd']), 0.5)
            self.assertLess(abs(s['publish']-m['publish']), 1.5)

    def test_review_example_uses_period_180_deadlines(self):
        r = b2_slack_arithmetic()
        self.assertEqual(r['period'], 180.0)
        self.assertEqual(r['cycle_deadline'], 375.0)
        self.assertEqual(r['refresh_deadline'], 360.0)
        self.assertAlmostEqual(r['boundary']['expert_response'], 81.2, places=3)
        self.assertAlmostEqual(r['boundary']['cycle_response'], 81.2, places=3)
        self.assertAlmostEqual(r['delayed']['expert_response'], 75.6, places=3)
        self.assertAlmostEqual(r['delayed']['cycle_response'], 120.2, places=3)
        self.assertAlmostEqual(r['expert_delta'], -5.6, places=3)
        self.assertAlmostEqual(r['cycle_delta'], 39.0, places=3)
        # both variants still meet both deadlines; the cost is completion time
        self.assertGreater(r['delayed']['cycle_margin'], 0)
        self.assertGreater(r['delayed']['refresh_margin'], 0)
        self.assertAlmostEqual(r['refresh_margin_delta'], -114.6, places=3)

    def test_delayed_tail_tradeoff_in_the_full_model(self):
        base, slack = crossing_scenario()
        b, s = base.summary(), slack.summary()
        self.assertLess(s['expert_odd'], b['expert_odd'])
        self.assertGreater(s['cycle_odd'], b['cycle_odd']+50)
        self.assertGreater(s['publish'], b['publish']+100)
        self.assertEqual((b['counts']['FAIL'], s['counts']['FAIL']), (0, 0))

    def test_ordering_and_idle(self):
        o = ordering_scenarios()
        self.assertGreater(o['block_first'].summary()['cycle_even'],
                           o['expert_first'].summary()['cycle_even']+40)
        base = simulate(TWO, 'b2_boundary', cycles=8).summary()
        idle = idle_scenario(50.0).summary()
        self.assertGreater(idle['cycle_even'], base['cycle_even']+40)
        self.assertGreater(idle['publish'], base['publish']+40)

    def test_version_wait_and_overrun_keep_real_misses(self):
        slow = slow_version_scenario()
        cyc2 = next(c for c in slow.cycles if c['cycle'] == 2)
        self.assertEqual(cyc2['status'], 'FAIL')
        self.assertGreater(cyc2['expert_response_ms'], 300.0)
        self.assertEqual(slow.summary()['counts']['denominator'], 8)
        over = overrun_scenario(200.0).summary()
        self.assertEqual(over['counts']['denominator'], 8)
        self.assertGreater(over['counts']['FAIL'], 0)

    def test_termination_keeps_incomplete(self):
        r = termination_scenario()
        s = r.summary()
        self.assertEqual(s['status'], 'NO_RUNNABLE_DEPENDENCY')
        self.assertGreater(s['counts']['INCOMPLETE'], 0)

    def test_tail_coverage_uses_the_real_tail_block(self):
        doc = load_result()
        for seg in doc['segments']:
            blocks = seg['block_plan']['blocks']
            nblocks = len(blocks)
            tail_key = 'R0/B%d' % nblocks
            ops = {o['key']: o for o in seg['operations']}
            self.assertIn(tail_key, ops, '%s: %s must be the last block' % (seg['segment_id'], tail_key))
            if nblocks == 3:
                self.assertNotEqual(tail_key, 'R0/B2', 'three-block B2 is a middle block')
            tail = ops[tail_key]
            start, end = tail['lower_ns'], tail['upper_ns']
            for rel in (d['release_ns'] for d in seg['decisions'] if d['kind'] == 'Expert'):
                self.assertFalse(start <= rel < end,
                                 '%s: release %.3f inside the tail window' % (seg['segment_id'], (rel-seg['t0_ns'])/1e6))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c)
                               for c in (RebuildTests, LifecycleTests, CounterexampleTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests=result.testsRun,
                failures=len(result.failures), errors=len(result.errors),
                scope='CPU/offline: independent statistics rebuild from raw maps + 4 fault injections, '
                      'frozen VersionedKV lifecycle probes (reclaim/retirement/generation/illegal reclaim), '
                      'model vs measured, review arithmetic at P=180, counterexamples; no GPU/WCET claim',
                model_starts=0, ssh=0, hardware_writes=0, scopes=0,
                executor=executor_identity())
    if args.json:
        args.json.write_text(json.dumps(data, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
