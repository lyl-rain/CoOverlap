"""CPU-only validation of the b6 controlled-interference integration.

Passing proves symbolic orchestration, timing contracts, worker adapter behavior
and shared-driver ordering only.  It is not GPU correctness, board safety,
performance or a real 32 MiB pressure-worker result.
"""
import argparse
import ast
import hashlib
import inspect
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from m2_clean_core import retention_layout, gate_retention_layout
from m2_clean_stats import augment
from m3_b3_orchestrate import describe_active, export_failed_retention, run_candidates
from m3_b3_plan import CONTROL, THREE
from m3_b6_plan import (CELLS, CYCLES, DRAIN_NS, GATE_PLAN, LEAD_NS, NOMINAL_NS,
                        PERIOD_NS, PLANS, PROTOCOL, RESULT_STATUS, RUN,
                        SEGMENT_IDS, WORKER_END_NS, budget, manifest, manifests,
                        protocol, worker_budget)
from m3_b6_window import SegmentWindow
from validate_m3_b3_cpu import PlanDevice, SNAPS
from validate_m3_b3_entry_cpu import _augment, _require
import validate_m3_interference_lifecycle_cpu as r1test
import m3_interference_lifecycle as L

HERE = Path(__file__).resolve().parent
PACKAGE = Path(os.environ.get(
    'B6_PACKAGE',
    HERE.parent / 'reports/m3_b2/20261021/controlled_interference_b6_v1_r1/deployment'))


def records():
    return [dict(index=i, candidate=c['cell'], cell=c['cell'], pass_=c['pass_'],
                 interference=c['interference'], policy=c['policy'], plan=c['plan'],
                 period_ns=c['period_ns'], segment_id=SEGMENT_IDS[i],
                 status='NOT_STARTED') for i, c in enumerate(RUN)]


def maths(plan):
    return {k: (lambda p: None) for k in plan.kinds}


class FakeWindow:
    """Shared-driver test double; the actual worker adapter is SegmentWindow."""

    def __init__(self, device, index, candidate, condition=True):
        self.device = device
        self.index = index
        self.mode = candidate['interference']
        self.condition = condition
        self.plan = None
        self.t0 = None
        self.finished = False
        self.aborted = False
        self.opened = False
        self.record = None

    def open(self, now, conf):
        if getattr(self.device, 'window_active', False):
            raise RuntimeError('overlapping worker window')
        self.t0 = int(now) + LEAD_NS
        self.plan = L.WindowPlan.from_replay_t0(self.t0, NOMINAL_NS, DRAIN_NS)
        self.opened = True
        self.device.window_active = True
        self.device.trace.append(('window_open', self.index, self.mode, self.t0))
        return self.t0

    def await_start(self):
        self.device.now = max(self.device.now, self.plan.start_ns)
        self.start_observed_ns = self.device.clock()
        self.start_lateness_ns = max(0, self.start_observed_ns - self.plan.start_ns)
        self.device.trace.append(('window_await', self.index, self.start_lateness_ns))

    def finish(self, replay_end_ns, replay_status=None, replay_error=None):
        if self.finished:
            return self.result
        self.finished = True
        self.statistics_at_finish = (self.record is not None
                                     and 'statistics' in self.record)
        self.device.window_active = False
        self.device.now = max(self.device.now, self.plan.end_ns)
        self.device.trace.append(('window_finish', self.index, replay_end_ns,
                                  self.mode, replay_status, replay_error))
        self.result = dict(
            mode=self.mode, plan=self.plan.as_dict(), t0_ns=self.plan.start_ns,
            replay_end_ns=replay_end_ns, replay_status=replay_status,
            replay_error=replay_error, condition_valid=bool(
                self.condition and replay_error is None
                and replay_end_ns is not None
                and int(replay_end_ns) <= self.plan.end_ns),
            worker_count=(0 if self.mode == 'quiet' else 1),
            resource_release={'resources_released': True,
                              'process_exit_confirmed': (None if self.mode == 'quiet' else True)},
            worker_evidence={'status': 'QUIET_COMPLETE' if self.mode == 'quiet' else 'WINDOW_COMPLETE'},
        )
        return self.result

    def abort(self, reason):
        if self.finished:
            return self.result
        self.finished = True
        self.aborted = True
        self.device.window_active = False
        self.device.trace.append(('window_abort', self.index, reason))
        self.result = dict(mode=self.mode, condition_valid=False,
                           condition_failure_reasons=[reason], aborted=True,
                           plan=None if self.plan is None else self.plan.as_dict(),
                           t0_ns=None if self.plan is None else self.plan.start_ns,
                           worker_count=0,
                           resource_release={'resources_released': True},
                           worker_evidence=None)
        return self.result


class ProtocolTests(unittest.TestCase):
    def test_four_conditions_mapping_order_and_unique_ids(self):
        self.assertEqual(PROTOCOL, 'm3_b6_controlled_interference_v1')
        self.assertEqual([c['cell'] for c in CELLS], ['A', 'B', 'C', 'D'])
        self.assertEqual([c['interference'] for c in CELLS],
                         ['quiet', 'quiet', 'fixed_cpu_mem', 'fixed_cpu_mem'])
        self.assertEqual([c['policy'] for c in CELLS],
                         ['serial_context', 'b2_boundary', 'serial_context', 'b2_boundary'])
        self.assertTrue(all(c['plan'] == CONTROL.id for c in CELLS))
        self.assertEqual([r['cell'] for r in RUN], ['A', 'B', 'C', 'D', 'D', 'C', 'B', 'A'])
        self.assertEqual(len(set(SEGMENT_IDS)), 8)
        self.assertEqual([r['interference'] for r in RUN],
                         ['quiet', 'quiet', 'fixed_cpu_mem', 'fixed_cpu_mem',
                          'fixed_cpu_mem', 'fixed_cpu_mem', 'quiet', 'quiet'])
        self.assertEqual(sum(r['interference'] == 'fixed_cpu_mem' for r in RUN), 4)
        self.assertEqual(sum(r['interference'] == 'quiet' for r in RUN), 4)
        self.assertEqual({r['cell'] for r in RUN}, {c['cell'] for c in CELLS})
        self.assertEqual({c['cell'] for c in CELLS}, {'A', 'B', 'C', 'D'})

    def test_timing_constants_are_the_declared_b6_window(self):
        self.assertEqual(PERIOD_NS, 180_000_000)
        self.assertEqual(CYCLES, 8)
        self.assertEqual(LEAD_NS, 4_000_000_000)
        self.assertEqual(NOMINAL_NS, 1_440_000_000)
        self.assertEqual(DRAIN_NS, 720_000_000)
        self.assertEqual(WORKER_END_NS, 2_160_000_000)
        self.assertEqual(CYCLES * PERIOD_NS, NOMINAL_NS)
        t = protocol()['timing']
        self.assertEqual(t['lead_ns'], LEAD_NS)
        self.assertEqual(t['drain_ns'], DRAIN_NS)
        self.assertEqual(t['readiness_timeout_ns'], 3_000_000_000)
        self.assertEqual(t['ready_margin_ns'], 10_000_000)
        self.assertTrue(t['no_retry'] and t['no_t0_move'] and t['no_window_extension'])

    def test_manifests_are_the_same_180ms_relative_trajectory(self):
        conf = manifest()
        self.assertEqual(conf['schema'], PROTOCOL)
        self.assertEqual(conf['period_ns'], PERIOD_NS)
        self.assertEqual(conf['cycles'], CYCLES)
        self.assertEqual(len(conf['experts']), CYCLES)
        self.assertEqual(len(conf['refreshes']), CYCLES // 2)
        self.assertIs(manifests()[PERIOD_NS], manifests()[PERIOD_NS])
        for e in conf['experts']:
            self.assertEqual(e['release_ns'], e['id'] * PERIOD_NS + 15_000_000)
            self.assertEqual(e['deadline_ns'] - e['release_ns'], PERIOD_NS)
            self.assertEqual(e['version'], e['id'] // 2)
        for r in conf['refreshes']:
            self.assertEqual(r['release_ns'], r['id'] * 2 * PERIOD_NS)
            self.assertEqual(r['deadline_ns'] - r['release_ns'], 2 * PERIOD_NS)

    def test_work_budget_and_worker_budget_are_recomputed(self):
        b = budget()
        self.assertEqual(b['layout'], dict(count=64, nbytes=487_320_064))
        self.assertEqual(b['gate_layout'], dict(plan=THREE.id, count=15, nbytes=124_121_472))
        self.assertEqual(b['batch_payload_bytes'], 8 * b['bank_bytes'])
        self.assertEqual(b['gpu_and_pinned_bytes'], 2 * b['bank_bytes'])
        self.assertEqual(b['estimate_bytes'], 5_653_281_189)
        self.assertEqual(b['admission_bytes'], 12 * 1024**3)
        self.assertEqual(b['timeline_s'], 8 * 8 * 0.180)
        p = protocol()
        self.assertEqual(p['work']['batch']['total_C'], 52)
        self.assertEqual(p['work']['batch']['total_E'], 70)
        self.assertEqual(p['work']['observed_ledger']['rows'], 13_400)
        self.assertEqual(p['work']['autotune_requests'], 36)
        w = worker_budget()
        self.assertEqual(w['max_workers'], 4)
        self.assertEqual(w['simultaneous_workers'], 1)
        self.assertEqual(w['quiet_workers'], 0)
        self.assertEqual(w['data_buffers_bytes_per_worker'], 2 * (32 * 1024 * 1024 + 128))
        self.assertEqual(w['shared_memory_bytes'], 64)
        self.assertFalse(w['rss_limit'])
        self.assertIn('not bounded', w['python_runtime_overhead'])

    def test_time_projection_is_not_a_guarantee_and_fits_budgets(self):
        t = protocol()['time_budget']
        self.assertFalse(t['measured'])
        self.assertIn('NOT a startup bound', t['caveat'])
        self.assertGreater(t['projection_s'], 76.468)
        self.assertLess(t['projection_s'], t['internal_deadline_s'])
        self.assertLess(t['projection_with_cleanup_allowance_s'], t['internal_deadline_s'])
        self.assertLess(t['projection_with_cleanup_allowance_s'], t['outer_timeout_s'])
        self.assertLess(t['scope_projection_s'], t['scope_max_s'])
        self.assertEqual(t['internal_deadline_s'], 170)
        self.assertEqual(t['outer_timeout_s'], 180)
        self.assertEqual(t['scope_max_s'], 420)

    def test_gate_budget_matches_entry_plan(self):
        actual = gate_retention_layout(CYCLES, GATE_PLAN)
        self.assertIs(GATE_PLAN, THREE)
        self.assertEqual((actual['count'], actual['nbytes']), (15, 124_121_472))
        self.assertEqual(budget()['gate_layout'],
                         dict(plan=GATE_PLAN.id, count=actual['count'],
                              nbytes=actual['nbytes']))
        self.assertEqual(protocol()['gates']['plan'], GATE_PLAN.id)

    def test_fairness_declares_only_policy_and_interference(self):
        f = protocol()['fairness']
        self.assertTrue(f['same_manifest'])
        self.assertTrue(f['same_relative_releases'])
        self.assertFalse(f['wallclock_paired'])
        self.assertEqual(f['pairs'], ['A/B quiet policy', 'C/D fixed policy',
                                      'A/C serial response', 'B/D boundary response'])
        self.assertEqual(set(protocol()['design']['comparisons']),
                         {'A->B: quiet priority-policy difference',
                          'C->D: fixed-interference priority-policy difference',
                          'A->C: serial response to interference',
                          'B->D: boundary response to interference'})


class SegmentWindowTests(unittest.TestCase):
    def factory(self, clock, behavior=None):
        def make(plan, config):
            return L.InterferenceController(
                config, clock=clock,
                backend=r1test.FakeBackend(clock, dict(behavior or {
                    'self_exit_at_ns': plan.end_ns})))
        return make

    def make_window(self, mode='fixed_cpu_mem', behavior=None):
        clock = r1test.FakeClock()
        window = SegmentWindow(mode, clock=clock,
                               controller_factory=self.factory(clock, behavior))
        t0 = window.open(clock.monotonic_ns(), manifest())
        window.await_start()
        return clock, window, t0

    def test_fixed_window_shares_t0_and_waits_full_worker_end(self):
        clock, window, t0 = self.make_window()
        self.assertEqual(window.plan.start_ns, t0)
        self.assertEqual(window.plan.nominal_end_ns, t0 + NOMINAL_NS)
        self.assertEqual(window.plan.end_ns, t0 + WORKER_END_NS)
        self.assertEqual(window.worker_count, 1)
        early_replay_end = t0 + 300_000_000
        result = window.finish(early_replay_end, 'DRAINED_PENDING_VALIDATION')
        self.assertTrue(result['condition_valid'], result['condition_failure_reasons'])
        self.assertFalse(result['replay_overran_worker_end'])
        self.assertGreaterEqual(result['worker_end_observed_ns'], t0 + WORKER_END_NS)
        self.assertGreaterEqual(result['replay_end_ns'], early_replay_end)
        self.assertTrue(result['resource_release']['resources_released'])
        self.assertEqual(result['worker_evidence']['worker_final']['copies'] > 0, True)
        self.assertTrue(result['worker_evidence']['worker_final']['work_valid'])

    def test_t0_is_four_seconds_from_open_time(self):
        clock = r1test.FakeClock(1_000_000_000)
        before = clock.monotonic_ns()
        window = SegmentWindow('fixed_cpu_mem', clock=clock,
                               controller_factory=self.factory(clock))
        t0 = window.open(before, manifest())
        self.assertEqual(t0, before + LEAD_NS)
        self.assertEqual(window.plan.start_ns, before + LEAD_NS)
        self.assertEqual(window.plan.nominal_end_ns, before + LEAD_NS + NOMINAL_NS)
        self.assertEqual(window.plan.end_ns, before + LEAD_NS + WORKER_END_NS)
        window.abort('test_cleanup')

    def test_late_await_start_keeps_original_t0(self):
        clock, window, t0 = self.make_window()
        # make_window already awaited; create a fresh window and advance the
        # parent observation time before await_start.
        clock2 = r1test.FakeClock()
        w = SegmentWindow('fixed_cpu_mem', clock=clock2,
                          controller_factory=self.factory(clock2))
        t0 = w.open(clock2.monotonic_ns(), manifest())
        clock2.now_ns = t0 + 500_000_000
        w.await_start()
        self.assertGreater(w.start_lateness_ns, 400_000_000)
        self.assertEqual(w.plan.start_ns, t0)
        result = w.finish(t0 + 300_000_000, 'DRAINED_PENDING_VALIDATION')
        self.assertEqual(result['t0_ns'], t0)
        self.assertTrue(result['condition_valid'], result['condition_failure_reasons'])

    def test_coverage_marks_late_operation_and_invalidates(self):
        clock, window, t0 = self.make_window()
        result = window.finish(t0 + 300_000_000, 'DRAINED_PENDING_VALIDATION')
        self.assertTrue(result['condition_valid'])
        end = window.plan.end_ns
        record = dict(
            experts={0: [t0 + 10_000_000, end + 1]},
            blocks={'(0, 0)': [t0 + 10_000_000, end + 2]},
            units={'(0, 0)': [t0 + 10_000_000, end + 3]},
            published={'0': [t0 + 10_000_000, end + 4]},
            manifest=manifest(),
            statistics=dict(cycles=[dict(cycle=0, release_ns=t0 + 15_000_000,
                                         response_upper_ns=end - t0 + 10_000_000)]),
        )
        detail = window.annotate_record(record)
        self.assertTrue(detail['any_late'])
        self.assertFalse(window.result['condition_valid'])
        self.assertIn('operations_after_worker_end',
                      window.result['condition_failure_reasons'])
        self.assertTrue(detail['late_experts'])
        self.assertTrue(detail['late_blocks'])
        self.assertTrue(detail['late_units'])
        self.assertTrue(detail['late_published'])
        self.assertTrue(detail['late_cycles'])

    def test_quiet_window_creates_no_worker_and_completes_at_end(self):
        clock, window, t0 = self.make_window(mode='quiet')
        self.assertEqual(window.worker_count, 0)
        result = window.finish(t0 + 300_000_000, 'DRAINED_PENDING_VALIDATION')
        self.assertTrue(result['condition_valid'], result['condition_failure_reasons'])
        self.assertEqual(result['worker_count'], 0)
        self.assertTrue(result['worker_evidence']['quiet_no_worker'])
        self.assertTrue(result['resource_release']['resources_released'])

    def test_readiness_failure_does_not_start_replay(self):
        clock = r1test.FakeClock()
        window = SegmentWindow('fixed_cpu_mem', clock=clock,
                               controller_factory=self.factory(clock, {
                                   'ready_ok': False, 'self_exit_at_ns': None}))
        before = clock.monotonic_ns()
        with self.assertRaises(BaseException):
            window.open(before, manifest())
        self.assertEqual(window.plan.start_ns, before + LEAD_NS)
        self.assertEqual(window.plan.end_ns, before + LEAD_NS + WORKER_END_NS)
        result = window.abort('readiness_failed')
        self.assertFalse(result['condition_valid'])
        self.assertFalse(window.started)

    def test_zero_copy_worker_is_not_valid(self):
        clock = r1test.FakeClock()
        def factory(plan, config):
            return L.InterferenceController(
                config, clock=clock,
                backend=r1test.FakeBackend(clock, {
                    'self_exit_at_ns': plan.end_ns,
                    'copy_period_ns': 10_000_000_000}))
        w = SegmentWindow('fixed_cpu_mem', clock=clock, controller_factory=factory)
        t0 = w.open(clock.monotonic_ns(), manifest()); w.await_start()
        result = w.finish(t0 + 300_000_000, 'DRAINED_PENDING_VALIDATION')
        self.assertFalse(result['condition_valid'])
        self.assertIn('worker_window_not_valid', result['condition_failure_reasons'])
        self.assertEqual(result['worker_evidence']['worker_final']['copies'], 0)

    def test_replay_overrun_is_invalid_and_does_not_extend_window(self):
        clock, window, t0 = self.make_window()
        end = window.plan.end_ns
        result = window.finish(end + 500_000_000, 'DRAINED_PENDING_VALIDATION')
        self.assertFalse(result['condition_valid'])
        self.assertTrue(result['replay_overran_worker_end'])
        self.assertIn('replay_overran_worker_end', result['condition_failure_reasons'])
        self.assertEqual(window.plan.end_ns, end)

    def test_replay_error_is_kept_separate_from_worker_evidence(self):
        clock, window, t0 = self.make_window()
        result = window.finish(t0 + 300_000_000, 'INCOMPLETE', 'TimeoutError("replay")')
        self.assertFalse(result['condition_valid'])
        self.assertEqual(result['replay_error'], 'TimeoutError("replay")')
        self.assertIsNotNone(result['worker_evidence'])
        self.assertIn('replay_error', result['condition_failure_reasons'])
        self.assertTrue(result['resource_release']['resources_released'])


class SharedDriverTests(unittest.TestCase):
    def run_all(self, condition=None, fail_at=None, fail_open_index=None):
        device = PlanDevice(fail_at=fail_at)
        recs = records()
        windows = []
        def factory(index, candidate, conf, record):
            if fail_open_index == index:
                class Bad(FakeWindow):
                    def open(self, now, conf):
                        self.device.trace.append(('window_open_failed', index))
                        raise RuntimeError('injected readiness failure')
                w = Bad(device, index, candidate)
            else:
                w = FakeWindow(device, index, candidate,
                               condition=(condition is None or condition(index)))
            w.record = record
            windows.append(w)
            return w
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_candidates(
                device, SNAPS, RUN, PLANS, 'performance', Path(tmp), device.clock,
                _require, maths, list(SEGMENT_IDS), manifest(), recs,
                _augment, lambda record, out: device.trace.append(('write', record['segment_id'])),
                confs=[manifest() for _ in RUN], window_factory=factory)
        return device, recs, windows, summary

    def test_eight_segments_use_one_shared_t0_each_and_no_overlap(self):
        device, recs, windows, summary = self.run_all()
        self.assertEqual(len(summary), 8)
        self.assertEqual([row['segment_id'] for row in summary], list(SEGMENT_IDS))
        self.assertEqual(sum(row['interference'] == 'fixed_cpu_mem' for row in summary), 4)
        self.assertEqual(sum(row['interference'] == 'quiet' for row in summary), 4)
        for row, rec, window in zip(summary, recs, windows):
            self.assertEqual(rec['t0_ns'], window.plan.start_ns)
            self.assertEqual(rec['window_t0_ns'], window.plan.start_ns)
            self.assertEqual(rec['window_plan']['end_ns'],
                             window.plan.start_ns + WORKER_END_NS)
            self.assertTrue(row['condition_valid'])
            self.assertEqual(row['comparison_status'], 'VALID_INTERFERENCE')
            self.assertFalse(window.device.window_active, 'window must close before next segment')
        self.assertEqual(len(windows), 8)
        self.assertEqual([w.mode for w in windows],
                         ['quiet', 'quiet', 'fixed_cpu_mem', 'fixed_cpu_mem',
                          'fixed_cpu_mem', 'fixed_cpu_mem', 'quiet', 'quiet'])

    def test_bootstrap_and_ready_precede_window_open(self):
        device, recs, windows, summary = self.run_all()
        trace = device.trace
        for index in range(len(windows)):
            open_at = next(i for i, x in enumerate(trace)
                           if x[0] == 'window_open' and x[1] == index)
            ready_at = max(i for i, x in enumerate(trace[:open_at])
                           if x[0] == 'ready')
            self.assertLess(ready_at, open_at)
        self.assertEqual(sum(1 for x in trace if x[0] == 'window_open'), 8)

    def test_finish_precedes_deferred_validation_and_write(self):
        device, recs, windows, summary = self.run_all()
        trace = device.trace
        for window in windows:
            self.assertFalse(window.statistics_at_finish,
                             'statistics must be finalized after worker finish')
        for index, sid in enumerate(SEGMENT_IDS):
            finish_at = min(i for i, x in enumerate(trace)
                            if x[0] == 'window_finish' and x[1] == index)
            deferred_at = min(i for i, x in enumerate(trace) if x[0] == 'deferred'
                              and i > finish_at - 1)
            write_at = min(i for i, x in enumerate(trace)
                           if x[0] == 'write' and x[1] == sid)
            self.assertLess(finish_at, write_at)
            # The deferred D2H/compare for this segment occurs after its finish.
            next_finish = min([i for i, x in enumerate(trace)
                               if x[0] == 'window_finish' and x[1] > index] + [len(trace)])
            self.assertTrue(any(x[0] == 'deferred' for x in trace[finish_at:next_finish]))

    def test_invalid_condition_validates_then_stops_following_segments(self):
        device, recs, windows, summary = self.run_all(condition=lambda i: i != 3)
        self.assertEqual(len(summary), 4)
        self.assertFalse(summary[-1]['condition_valid'])
        self.assertEqual(summary[-1]['comparison_status'], 'INVALID_INTERFERENCE_CONDITION')
        self.assertEqual([row['segment_id'] for row in summary], list(SEGMENT_IDS[:4]))
        self.assertEqual(sum(1 for x in device.trace if x[0] == 'deferred'), 4)
        self.assertEqual(sum(1 for x in device.trace if x[0] == 'write'), 4)
        self.assertEqual(device.leased, False)

    def test_replay_failure_finishes_worker_but_skips_validation(self):
        from m3_b3_orchestrate import describe_active
        active = {}
        device = PlanDevice(fail_at='E1')
        recs = records()
        windows = []
        def factory(index, candidate, conf, record):
            w = FakeWindow(device, index, candidate)
            windows.append(w)
            return w
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TimeoutError):
                run_candidates(device, SNAPS, RUN, PLANS, 'performance', Path(tmp),
                               device.clock, _require, maths, list(SEGMENT_IDS),
                               manifest(), recs, _augment, None, active=active,
                               confs=[manifest() for _ in RUN], window_factory=factory)
        self.assertEqual(describe_active(active)['segment_id'], SEGMENT_IDS[0])
        self.assertTrue(any(x[0] == 'window_finish' for x in device.trace))
        self.assertFalse(any(x[0] == 'deferred' for x in device.trace))
        self.assertEqual(recs[0].get('comparison_status'), 'INVALID_INTERFERENCE_CONDITION')
        self.assertFalse(device.window_active)

    def test_open_failure_prevents_replay_and_stops(self):
        from m3_b3_orchestrate import describe_active
        active = {}
        device = PlanDevice()
        windows = []
        def factory(index, candidate, conf, record):
            w = FakeWindow(device, index, candidate)
            if index == 0:
                original = w.open
                def bad(now, conf):
                    device.trace.append(('window_open_failed', index))
                    raise RuntimeError('injected readiness failure')
                w.open = bad
            windows.append(w)
            return w
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                run_candidates(device, SNAPS, RUN, PLANS, 'performance', Path(tmp),
                               device.clock, _require, maths, list(SEGMENT_IDS),
                               manifest(), records(), _augment, None, active=active,
                               confs=[manifest() for _ in RUN], window_factory=factory)
        self.assertEqual(describe_active(active)['segment_id'], SEGMENT_IDS[0])
        self.assertFalse(any(x[0] == 'math' for x in device.trace))
        self.assertFalse(any(x[0] == 'deferred' for x in device.trace))
        self.assertTrue(any(x[0] == 'window_abort' for x in device.trace))
        self.assertFalse(device.window_active)

    def test_start_failure_does_not_start_replay_or_fabricate_stats(self):
        from m3_b3_orchestrate import describe_active
        active = {}
        device = PlanDevice()
        windows = []
        def factory(index, candidate, conf, record):
            w = FakeWindow(device, index, candidate)
            if index == 0:
                def bad_start():
                    device.trace.append(('window_start_failed', index))
                    raise RuntimeError('injected late start')
                w.await_start = bad_start
            w.record = record
            windows.append(w)
            return w
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                run_candidates(device, SNAPS, RUN, PLANS, 'performance', Path(tmp),
                               device.clock, _require, maths, list(SEGMENT_IDS),
                               manifest(), records(), _augment, None, active=active,
                               confs=[manifest() for _ in RUN], window_factory=factory)
        self.assertEqual(describe_active(active)['segment_id'], SEGMENT_IDS[0])
        self.assertFalse(any(x[0] == 'math' for x in device.trace))
        self.assertFalse(any(x[0] == 'deferred' for x in device.trace))
        self.assertTrue(any(x[0] == 'window_abort' for x in device.trace))
        self.assertFalse(hasattr(windows[0].record, 'does_not_exist'))

    def test_original_release_deadline_version_and_denominators(self):
        device, recs, windows, summary = self.run_all()
        for rec in recs:
            t0 = rec['t0_ns']
            conf = rec['manifest']
            self.assertEqual(len(rec['units']), CYCLES)
            self.assertEqual(len(rec['published']), CYCLES // 2)
            self.assertEqual(len(rec['statistics']['cycles']), CYCLES)
            self.assertEqual(len(rec['statistics']['refreshes']), CYCLES // 2)
            for e in conf['experts']:
                self.assertEqual(e['release_ns'], e['id'] * PERIOD_NS + 15_000_000)
                self.assertEqual(e['deadline_ns'] - e['release_ns'], PERIOD_NS)
                self.assertEqual(e['version'], e['id'] // 2)
            self.assertEqual(rec['statistics']['cycles'][0]['release_ns'],
                             t0 + 15_000_000)
            self.assertEqual(rec['statistics']['cycles'][-1]['deadline_ns'],
                             t0 + 7 * PERIOD_NS + 15_000_000 + PERIOD_NS)


class DeviceClock:
    """Shared fake monotonic clock for PlanDevice + r1 lifecycle/SegmentWindow."""

    def __init__(self, device):
        self.device = device

    def monotonic_ns(self):
        return self.device.clock()

    def sleep_ns(self, ns):
        self.device.now += max(0, int(ns))


class CountingDevice(PlanDevice):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.release_bank_calls = 0

    def release_bank(self):
        self.release_bank_calls += 1
        return super().release_bank()


class ReleaseFailBackend(r1test.FakeBackend):
    """Real fake process exits, but its release receipt is deliberately false."""

    def spawn(self, plan, config):
        handle = super().spawn(plan, config)
        original = handle.release

        def release_failed():
            receipt = dict(original())
            receipt.update(process_exit_confirmed=True, resources_released=False,
                           stdout_closed=True, stderr_closed=True,
                           shm_present=True, shm_closed=False, shm_unlinked=False)
            handle.resources_released = False
            return receipt
        handle.release = release_failed
        return handle


class FaultInjectionTests(unittest.TestCase):
    """Actual run_candidates + actual SegmentWindow/r1 lifecycle.

    Only the process/clock/GPU device boundaries are replaced: PlanDevice is
    the GPU/device double, DeviceClock is the shared fake monotonic clock, and
    FakeBackend/FakeHandle are the process boundary.  Orchestration and
    SegmentWindow are the shipped implementations.
    """

    def run_case(self, behavior=None, release_fail=False, count=2, offset=2):
        device = CountingDevice()
        clock = DeviceClock(device)
        writes = []
        windows = []
        active = {}

        def controller_factory(plan, config):
            cls = ReleaseFailBackend if release_fail else r1test.FakeBackend
            b = dict(behavior or {})
            b.setdefault('self_exit_at_ns', plan.end_ns)
            backend = cls(clock, b)
            return L.InterferenceController(config, clock=clock, backend=backend)

        def window_factory(index, candidate, conf, record):
            w = SegmentWindow(candidate['interference'], clock=clock,
                              controller_factory=controller_factory)
            windows.append(w)
            return w

        recs = records()[offset:offset+count]
        cands = RUN[offset:offset+count]
        ids = SEGMENT_IDS[offset:offset+count]
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_candidates(
                device, SNAPS, cands, PLANS, 'performance', Path(tmp),
                device.clock, _require, maths, list(ids), manifest(), recs,
                _augment, lambda record, out: writes.append(record['segment_id']),
                active=active, confs=[manifest() for _ in ids],
                window_factory=window_factory)
        return dict(device=device, clock=clock, writes=writes, windows=windows,
                    active=active, records=recs, summary=summary, out=Path(tmp))

    def test_worker_ignores_term_kill_blocks_validation_write_reuse_and_export(self):
        r = self.run_case(behavior={
            'self_exit_at_ns': None, 'respond_to_term': False,
            'ignore_kill': True})
        self.assertEqual(len(r['summary']), 1)
        self.assertEqual(len(r['windows']), 1)
        rec = r['records'][0]
        self.assertEqual(rec['status'], 'FAILED_UNSAFE_WORKER_RESOURCES')
        self.assertEqual(rec['overall_status'], 'FAILED_UNSAFE_WORKER_RESOURCES')
        self.assertEqual(rec['validation_status'], 'NOT_RUN_UNSAFE_RESOURCES')
        self.assertFalse(rec['resource_safety']['safe'])
        self.assertFalse(rec['resource_safety']['resources_released'])
        self.assertFalse(rec['resource_safety']['process_exit_confirmed'])
        self.assertTrue(r['device'].leased)
        self.assertEqual(r['device'].release_bank_calls, 0)
        self.assertEqual(sum(1 for x in r['device'].trace if x[0] == 'deferred'), 0)
        self.assertEqual(r['writes'], [])
        self.assertTrue(r['active']['unsafe_resources'])
        export = export_failed_retention(
            r['device'], r['active'], r['out'], time.monotonic_ns() + 5_000_000_000,
            time.monotonic_ns)
        self.assertTrue(export['status'].startswith('NOT_EXPORTED_no_reliable_worker_release'),
                        export['status'])
        self.assertEqual(r['device'].downloads, [])
        self.assertFalse((r['out']/'PARTIAL_UNVERIFIED_RETENTION.bin').exists())

    def test_worker_exited_but_release_failed_blocks_validation_write_and_reuse(self):
        r = self.run_case(release_fail=True)
        self.assertEqual(len(r['summary']), 1)
        rec = r['records'][0]
        self.assertEqual(rec['status'], 'FAILED_UNSAFE_WORKER_RESOURCES')
        self.assertEqual(rec['validation_status'], 'NOT_RUN_UNSAFE_RESOURCES')
        self.assertFalse(rec['resource_safety']['safe'])
        self.assertTrue(rec['resource_safety']['process_exit_confirmed'])
        self.assertFalse(rec['resource_safety']['resources_released'])
        self.assertTrue(r['device'].leased)
        self.assertEqual(r['device'].release_bank_calls, 0)
        self.assertEqual(sum(1 for x in r['device'].trace if x[0] == 'deferred'), 0)
        self.assertEqual(r['writes'], [])
        export = export_failed_retention(
            r['device'], r['active'], r['out'], time.monotonic_ns() + 5_000_000_000,
            time.monotonic_ns)
        self.assertTrue(export['status'].startswith('NOT_EXPORTED_no_reliable_worker_release'),
                        export['status'])
        self.assertEqual(r['device'].downloads, [])

    def test_zero_copy_saves_numeric_but_segment_fails_and_stops(self):
        r = self.run_case(behavior={
            'self_exit_at_ns': None, 'copy_period_ns': 10_000_000_000})
        self.assertEqual(len(r['summary']), 1)
        rec = r['records'][0]
        self.assertEqual(rec['status'], 'FAILED_INTERFERENCE_CONDITION')
        self.assertEqual(rec['overall_status'], 'FAILED_INTERFERENCE_CONDITION')
        self.assertEqual(rec['validation_status'], 'PASS')
        self.assertTrue(rec['numeric_pass'])
        self.assertTrue(rec['resource_safety']['safe'])
        self.assertFalse(rec['condition_valid'])
        self.assertEqual(sum(1 for x in r['device'].trace if x[0] == 'deferred'), 1)
        self.assertEqual(len(r['writes']), 1)
        self.assertEqual(r['device'].release_bank_calls, 1)
        self.assertFalse(r['device'].leased)
        self.assertFalse(r['active']['unsafe_resources'])
        export = export_failed_retention(
            r['device'], r['active'], r['out'], time.monotonic_ns() + 5_000_000_000,
            time.monotonic_ns)
        self.assertEqual(export['status'], 'NOT_EXPORTED_already_validated_and_persisted')
        self.assertEqual(r['device'].downloads, [])

    def test_actual_entry_exception_cleanup_cannot_bypass_unsafe_gate(self):
        r = self.run_case(behavior={
            'self_exit_at_ns': None, 'respond_to_term': False,
            'ignore_kill': True})
        entry = __import__('pi05_m3_b6_interference')
        report = dict(checks=[])
        saves = []
        with tempfile.TemporaryDirectory() as tmp:
            before = len(r['device'].downloads)
            entry.finish_failed_active(
                report, r['active'], r['device'], Path(tmp),
                time.monotonic_ns() + 5_000_000_000, time.monotonic_ns,
                lambda: saves.append('report'))
            self.assertEqual(len(saves), 1)
            self.assertEqual(report['partial_retention_status'],
                             'NOT_EXPORTED_no_reliable_worker_release')
            self.assertEqual(len(r['device'].downloads), before)
            self.assertFalse((Path(tmp)/'PARTIAL_UNVERIFIED_RETENTION.bin').exists())
        self.assertEqual(report['failed_phase']['segment_id'], SEGMENT_IDS[2])

    def test_normal_real_window_path_remains_successful(self):
        r = self.run_case(count=2)
        self.assertEqual(len(r['summary']), 2)
        for rec in r['records']:
            self.assertEqual(rec['status'], 'PASS')
            self.assertEqual(rec['overall_status'], 'PASS')
            self.assertEqual(rec['validation_status'], 'PASS')
            self.assertTrue(rec['numeric_pass'])
            self.assertTrue(rec['condition_valid'])
            self.assertTrue(rec['resource_safety']['safe'])
        self.assertEqual(sum(1 for x in r['device'].trace if x[0] == 'deferred'), 2)
        self.assertEqual(len(r['writes']), 2)
        self.assertEqual(r['device'].release_bank_calls, 2)
        self.assertFalse(r['device'].leased)


class PrepareSentinel(Exception):
    pass


class EntryMainCredentialTests(unittest.TestCase):
    """Real pi05_m3_b6_interference.main, before any GPU import.

    A valid package/preflight credential must reach the controlled prepare
    sentinel; wrong-protocol and expired credentials must be rejected earlier.
    """

    def setUp(self):
        self.entry = __import__('pi05_m3_b6_interference')
        self.control = __import__('m3_b6_control')
        self.package = PACKAGE.resolve()
        self.assertTrue((self.package/'CONFIG.json').is_file(), self.package)
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)/'out'
        self.run = Path(self.tmp.name)/'run_01'
        self.run.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def credential(self, protocol=PROTOCOL, created=None):
        package = self.control.package_files(self.package)
        obj = dict(protocol=protocol, host=socket.gethostname(), uid=os.geteuid(),
                   created=time.time() if created is None else created,
                   base=str(self.package), run=str(self.run.resolve()),
                   package=package, sources={}, hardware_before={})
        path = self.run/'PREFLIGHT.json'
        path.write_text(json.dumps(obj, indent=2))
        return self.control.sha(path)

    def invoke(self, credential):
        flag = '--approved-m3-b6-controlled-interference-v1'
        old_argv, old_prepare = sys.argv, self.entry.prepare
        old_env = os.environ.get('COOVERLAP_APPROVED_BATCH')
        os.environ['COOVERLAP_APPROVED_BATCH'] = PROTOCOL
        self.entry.prepare = lambda *a, **k: (_ for _ in ()).throw(PrepareSentinel())
        sys.argv = [str(self.entry.__file__), flag, '--verification-mode', 'performance',
                    '--config', str(self.package/'CONFIG.json'),
                    '--reference', str(self.package/'reference'),
                    '--source-preflight', str(self.run/'PREFLIGHT.json'),
                    '--out', str(self.out)]
        before = {name for name in ('torch', 'm2_clean_cuda', 'flash_rt')
                  if name in sys.modules}
        reached = False
        try:
            try:
                self.entry.main()
            except PrepareSentinel:
                reached = True
        finally:
            self.entry.prepare = old_prepare
            sys.argv = old_argv
            if old_env is None:
                os.environ.pop('COOVERLAP_APPROVED_BATCH', None)
            else:
                os.environ['COOVERLAP_APPROVED_BATCH'] = old_env
            after = {name for name in ('torch', 'm2_clean_cuda', 'flash_rt')
                     if name in sys.modules}
            self.assertEqual(after, before, 'CPU credential path imported GPU modules')
        return reached

    def test_valid_credential_reaches_controlled_prepare_sentinel(self):
        cred = self.credential()
        self.assertTrue(self.invoke(cred))
        self.assertTrue(self.out.is_dir())
        report = json.loads((self.out/'result.json').read_text())
        self.assertEqual(report['status'], 'FAIL_OR_INCOMPLETE')
        self.assertEqual(report['partial_retention_status'],
                         'NOT_EXPORTED_no_active_segment')

    def test_wrong_protocol_credential_is_rejected_before_prepare(self):
        cred = self.credential(protocol='not_this_batch')
        with self.assertRaises(ValueError):
            self.invoke(cred)
        self.assertFalse(self.out.exists())

    def test_expired_credential_is_rejected_before_prepare(self):
        cred = self.credential(created=time.time() - 601)
        with self.assertRaises(ValueError):
            self.invoke(cred)
        self.assertFalse(self.out.exists())


class EntryTests(unittest.TestCase):
    def test_entry_dry_run_and_protocol(self):
        proc = subprocess.run(
            [sys.executable, str(HERE / 'pi05_m3_b6_interference.py'), '--dry-run'],
            cwd=HERE, text=True, capture_output=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        doc = json.loads(proc.stdout)
        self.assertEqual(doc['protocol']['id'], PROTOCOL)
        self.assertEqual(len(doc['protocol']['run']), 8)
        self.assertEqual(doc['protocol']['timing']['worker_end'], 't0 + 2.160 s')
        self.assertIn('source_sha256', doc['preparation_reuse'])

    def test_entry_refuses_without_this_batch_token(self):
        proc = subprocess.run(
            [sys.executable, str(HERE / 'pi05_m3_b6_interference.py')],
            cwd=HERE, text=True, capture_output=True, timeout=60)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('controlled-interference approval', proc.stderr)

    def test_entry_uses_window_factory_and_shared_run_candidates(self):
        src = (HERE / 'pi05_m3_b6_interference.py').read_text()
        tree = ast.parse(src)
        self.assertIn('SegmentWindow', src)
        self.assertIn('window_factory=window_factory', src)
        self.assertIn("sorted(c['cell'] for c in CELLS)", src)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'run_candidates']
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(k.arg == 'window_factory' for k in calls[0].keywords))
        self.assertEqual(src.count('--approved-m3-b6-controlled-interference-v1'), 1)
        self.assertIn('RESULT_STATUS', src)

    def test_control_tokens_and_permission_gate(self):
        import m3_b6_control as c
        src = Path(c.__file__).read_text()
        self.assertIn('from m3_b6_plan import PROTOCOL, protocol', src)
        self.assertEqual(src.count('--approved-m3-b6-controlled-interference-v1'), 3)
        self.assertEqual(src.count('m3_b6_control.py'), 2)
        self.assertNotIn('m3_b5', src)
        self.assertEqual(c.PROTOCOL, PROTOCOL)
        base = Path(c.__file__).resolve().parent
        old = sys.argv
        sys.argv = ['m3_b6_control.py', 'submit', '--base', str(base),
                    '--run', str(base / 'run_01'), '--credential-sha', '0' * 64,
                    '--approved-m3-b6-controlled-interference-v1']
        try:
            with self.assertRaises(PermissionError):
                c.main()
        finally:
            sys.argv = old

    def test_config_round_trip_if_present(self):
        cfg = HERE.parent / 'reports/m3_b2/20261021/controlled_interference_b6_v1/deployment/CONFIG.json'
        if not cfg.is_file():
            self.skipTest('deployment CONFIG not built yet; not counted as PASS')
        self.assertEqual(json.loads(cfg.read_text()), protocol())


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = dict(status='PASS' if result.wasSuccessful() else 'FAIL',
                tests=result.testsRun, failures=len(result.failures),
                errors=len(result.errors), skipped=len(result.skipped),
                scope='CPU: b6 mapping/timing + actual SegmentWindow/r1 resource-fault closeout + '
                      'actual main credential sentinel; no GPU correctness, performance, board safety or real pressure worker',
                model_starts=0, ssh=0, hardware_writes=0, scopes=0)
    if args.json:
        args.json.write_text(json.dumps(data, indent=2) + '\n')
    sys.exit(0 if result.wasSuccessful() else 1)
