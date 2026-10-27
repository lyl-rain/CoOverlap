"""CPU-only validation of B7 stage-startup diagnostic.

Covers protocol/manifest/lead mapping, the shared SegmentWindow with 10 ms/4 s
leads, the preallocated Host stage observer, actual BoundaryBackend stage order,
shared-driver exception/resource gates, work/ledger/disk counts, CLI tokens and
the actual entry credential path. It does not start a model, worker, scope, SSH
or hardware write, and is not GPU correctness/performance evidence.
"""
import argparse
import ast
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from m2_clean_core import gate_retention_layout, retention_layout
from m3_b3_orchestrate import run_candidates
from m3_b3_plan import CONTROL, THREE
from m3_b6_window import SegmentWindow
from m3_b7_plan import (CELLS, CYCLES, DRAIN_NS, GATE_PLAN, LEAD_LONG_NS,
                        LEAD_SHORT_NS, NOMINAL_NS, PERIOD_NS, PLANS, PROTOCOL,
                        RESULT_STATUS, RUN, SEGMENT_IDS, WORKER_END_NS, budget,
                        manifest, manifests, protocol)
from m3_b7_stage_observe import StageObservation, SegmentStageObservation, TIMESTAMP_NAMES
from validate_m3_b3_cpu import PlanDevice, SNAPS
from validate_m3_b3_entry_cpu import _augment, _require
import validate_m3_interference_lifecycle_cpu as r1test

HERE = Path(__file__).resolve().parent
PACKAGE = Path(os.environ.get(
    'B7_PACKAGE', HERE.parent / 'reports/m3_b2/20261021/stage_startup_b7_v1/deployment'))


def records():
    return [dict(index=i, candidate=c['cell'], cell=c['cell'], pass_=c['pass_'],
                 interference=c['interference'], lead_ns=c['lead_ns'],
                 policy=c['policy'], plan=c['plan'], period_ns=c['period_ns'],
                 segment_id=SEGMENT_IDS[i], status='NOT_STARTED')
            for i, c in enumerate(RUN)]


def maths(plan):
    return {k: (lambda p: None) for k in plan.kinds}


class StartupWindow:
    """Finite quiet window double with no process; lead is config-driven."""
    def __init__(self, device, candidate, condition=True, resources=True):
        self.device = device
        self.candidate = candidate
        self.lead_ns = int(candidate['lead_ns'])
        self.condition = condition
        self.resources = resources
        self.plan = None
        self.t0 = None
        self.prepared_ns = None
        self.worker_count = 0
        self.mode = 'quiet'
        self.worker_mode = 'quiet'
        self.record = None

    def open(self, now, conf):
        self.t0 = int(now) + self.lead_ns
        self.prepared_ns = int(now)
        self.plan = __import__('m3_interference_lifecycle').WindowPlan.from_replay_t0(
            self.t0, int(conf['period_ns']) * int(conf['cycles']), DRAIN_NS)
        self.device.trace.append(('window_open', self.candidate['cell'], self.t0))
        return self.t0

    def await_start(self):
        self.device.now = max(self.device.now, self.plan.start_ns)
        self.start_observed_ns = self.device.clock()
        self.start_lateness_ns = max(0, self.start_observed_ns - self.plan.start_ns)
        self.device.trace.append(('window_await', self.candidate['cell'],
                                  self.start_lateness_ns))

    def finish(self, replay_end_ns, replay_status=None, replay_error=None):
        self.device.now = max(self.device.now, self.plan.end_ns)
        valid = bool(self.condition and replay_error is None and replay_end_ns is not None
                     and int(replay_end_ns) <= self.plan.end_ns)
        self.device.trace.append(('window_finish', self.candidate['cell'], replay_end_ns))
        return dict(mode='quiet', worker_mode='quiet', lead_ns=self.lead_ns,
                    plan=self.plan.as_dict(), t0_ns=self.t0,
                    nominal_end_ns=self.plan.nominal_end_ns,
                    worker_end_ns=self.plan.end_ns,
                    prepared_ns=self.prepared_ns, worker_count=0,
                    replay_end_ns=replay_end_ns, replay_status=replay_status,
                    replay_error=None,
                    condition_valid=valid,
                    condition_failure_reasons=[] if valid else ['injected'],
                    resource_release=dict(resources_released=bool(self.resources),
                                          process_exit_confirmed=None),
                    worker_evidence=dict(status='QUIET_COMPLETE', window_complete=True,
                                         quiet_no_worker=True,
                                         resource_release=dict(resources_released=bool(self.resources))))

    def abort(self, reason):
        return dict(mode='quiet', condition_valid=False, condition_failure_reasons=[reason],
                    plan=None if self.plan is None else self.plan.as_dict(),
                    t0_ns=None if self.plan is None else self.plan.start_ns,
                    worker_count=0, resource_release=dict(resources_released=False),
                    worker_evidence=None)


class ObserverTests(unittest.TestCase):
    def fill(self, obs):
        obs.stage_enter()
        obs.event_before('R0/stage', 0); obs.event_after('R0/stage', 0)
        obs.event_before('R0/stage', 1); obs.event_after('R0/stage', 1)
        obs.restore_before('images'); obs.restore_after('images')
        obs.restore_before('noise'); obs.restore_after('noise')
        obs.capture_before('images'); obs.capture_after('images')
        obs.capture_before('noise'); obs.capture_after('noise')
        obs.event_before('R0/stage', 2); obs.event_after('R0/stage', 2)
        obs.event_before('R0/stage', 7); obs.event_after('R0/stage', 7)
        obs.event7_wait_before(); obs.event7_wait_after(37)
        obs.confirmation_before(); obs.confirmation_after()
        obs.stage_exit()
        return obs.snapshot()

    def test_preallocated_22_slots_and_aggregate_poll_count(self):
        obs = StageObservation(clock=lambda: 1_000_000_000)
        snap = self.fill(obs)
        self.assertEqual(len(obs.slots), 22)
        self.assertEqual(len(TIMESTAMP_NAMES), 22)
        self.assertTrue(snap['complete'])
        self.assertFalse(snap['missing'])
        self.assertEqual(set(snap['timestamps']), set(TIMESTAMP_NAMES))
        self.assertEqual(snap['counts']['event_records'], 4)
        self.assertEqual(snap['counts']['restore_calls'], 2)
        self.assertEqual(snap['counts']['capture_calls'], 2)
        self.assertEqual(snap['counts']['confirmation_calls'], 1)
        self.assertEqual(snap['counts']['event7_polls'], 37)
        self.assertNotIn('event7_polls_log', snap['counts'])


    def test_incomplete_stage_is_reported_not_fabricated(self):
        coll = SegmentStageObservation(clock=lambda: 1_000_000_000, segment_id='s')
        coll.stage_enter()
        coll.event_before('R0/stage', 0)
        snap = coll.snapshot()
        self.assertFalse(snap['complete'])
        self.assertEqual(snap['missing'], [0, 1, 2, 3])
        self.assertFalse(snap['stages'][0]['complete'])

    def test_segment_collector_preallocates_four_stages(self):
        coll = SegmentStageObservation(clock=lambda: 1_000_000_000, segment_id='s')
        self.assertEqual(len(coll.records), 4)
        for i in range(4):
            self.fill(coll)
        with self.assertRaises(RuntimeError):
            coll.stage_enter()
        snap = coll.snapshot()
        self.assertEqual(snap['stage_count'], 4)
        self.assertTrue(snap['complete'])
        self.assertEqual(snap['counts']['event_records'], 16)
        self.assertEqual(snap['counts']['restore_calls'], 8)
        self.assertEqual(snap['counts']['capture_calls'], 8)
        self.assertEqual(snap['counts']['confirmation_calls'], 4)

    def test_duplicate_or_unreviewed_stamp_is_rejected(self):
        obs = StageObservation()
        obs.stage_enter()
        with self.assertRaises(RuntimeError):
            obs.stage_enter()
        with self.assertRaises(ValueError):
            obs.event_before('R0/stage', 3)
        with self.assertRaises(ValueError):
            obs.capture_before('other')


class ProtocolTests(unittest.TestCase):
    def test_only_lead_differs_and_order_is_A_B_B_A(self):
        self.assertEqual(PROTOCOL, 'm3_b7_stage_startup_v1')
        self.assertEqual([c['cell'] for c in CELLS], ['A', 'B'])
        self.assertEqual([c['lead_ns'] for c in CELLS], [10_000_000, 4_000_000_000])
        self.assertEqual([c['policy'] for c in CELLS], ['b2_boundary', 'b2_boundary'])
        self.assertEqual([c['plan'] for c in CELLS], [CONTROL.id, CONTROL.id])
        self.assertEqual([r['cell'] for r in RUN], ['A', 'B', 'B', 'A'])
        self.assertEqual([r['lead_ns'] for r in RUN],
                         [10_000_000, 4_000_000_000, 4_000_000_000, 10_000_000])
        self.assertEqual([r['interference'] for r in RUN], ['quiet'] * 4)
        self.assertEqual(len(set(SEGMENT_IDS)), 4)
        p = protocol()
        self.assertEqual(p['order'], list('ABBA'))
        self.assertTrue(p['fairness']['only_lead_differs'])
        self.assertEqual(p['design']['only_variable'], 'lead_ns: 10 ms (A) vs 4 s (B)')

    def test_timing_window_and_no_t0_move(self):
        self.assertEqual(PERIOD_NS, 180_000_000)
        self.assertEqual(CYCLES, 8)
        self.assertEqual(NOMINAL_NS, 1_440_000_000)
        self.assertEqual(DRAIN_NS, 720_000_000)
        self.assertEqual(WORKER_END_NS, 2_160_000_000)
        self.assertEqual(LEAD_SHORT_NS, 10_000_000)
        self.assertEqual(LEAD_LONG_NS, 4_000_000_000)
        t = protocol()['timing']
        self.assertTrue(t['no_t0_move'] and t['no_retry'])
        self.assertEqual(t['lead_B_ns'], 4_000_000_000)
        self.assertIn('1.440', t['nominal_end'])
        self.assertIn('2.160', t['worker_end'])

    def test_same_manifest_and_no_worker_or_extra_work(self):
        conf = manifest()
        self.assertEqual(conf['schema'], PROTOCOL)
        self.assertIs(manifests()[PERIOD_NS], manifests()[PERIOD_NS])
        self.assertEqual(len(conf['experts']), 8)
        self.assertEqual(len(conf['refreshes']), 4)
        for e in conf['experts']:
            self.assertEqual(e['release_ns'], e['id'] * PERIOD_NS + 15_000_000)
            self.assertEqual(e['deadline_ns'] - e['release_ns'], PERIOD_NS)
        for r in conf['refreshes']:
            self.assertEqual(r['release_ns'], r['id'] * 2 * PERIOD_NS)
            self.assertEqual(r['deadline_ns'] - r['release_ns'], 2 * PERIOD_NS)
        p = protocol()
        self.assertTrue(p['no_pressure_worker'])
        self.assertEqual(p['limits']['pressure_workers'], 0)
        self.assertEqual(p['retention']['worker_budget']['max_workers'], 0)
        self.assertFalse(any(r['interference'] == 'fixed_cpu_mem' for r in RUN))
        self.assertEqual(p['work']['batch']['total_C'], 32)
        self.assertEqual(p['work']['batch']['total_E'], 38)
        self.assertEqual(p['work']['observed_ledger']['contexts'], 29)
        self.assertEqual(p['work']['observed_ledger']['experts'], 37)
        self.assertEqual(p['work']['observed_ledger']['rows'], 7_240)
        self.assertEqual(p['work']['autotune_requests'], 36)

    def test_budget_is_recomputed_for_four_segments(self):
        b = budget()
        self.assertEqual(b['bank_bytes'], 487_320_064)
        self.assertEqual(b['layout'], dict(count=64, nbytes=487_320_064))
        self.assertEqual(b['gate_layout']['nbytes'], 124_121_472)
        self.assertEqual(b['batch_payload_bytes'], 4 * b['bank_bytes'])
        self.assertEqual(b['gpu_and_pinned_bytes'], 2 * b['bank_bytes'])
        self.assertEqual(b['estimate_bytes'], 3_342_248_562)
        self.assertEqual(b['admission_bytes'], 12 * 1024**3)
        self.assertEqual(b['timeline_s'], 4 * 8 * 0.180)
        self.assertFalse(b['time_budget']['measured'])
        self.assertLess(b['time_budget']['projection_s'], 170)
        self.assertLess(b['time_budget']['projection_with_allowance_s'], 170)
        self.assertLess(b['time_budget']['scope_max_s'], 421)
        self.assertEqual(b['worker_budget']['max_workers'], 0)
        self.assertEqual(b['stage_observation']['slots'], 22)
        self.assertTrue(b['stage_observation']['preallocated'])

    def test_gate_budget(self):
        actual = gate_retention_layout(CYCLES, GATE_PLAN)
        self.assertIs(GATE_PLAN, THREE)
        self.assertEqual((actual['count'], actual['nbytes']), (15, 124_121_472))
        self.assertEqual(budget()['gate_layout'],
                         dict(plan=GATE_PLAN.id, count=15, nbytes=124_121_472))


class WindowTests(unittest.TestCase):
    def test_quiet_window_has_10ms_and_4s_lead_with_no_worker(self):
        for lead in (LEAD_SHORT_NS, LEAD_LONG_NS):
            clock = r1test.FakeClock(1_000_000_000)
            w = SegmentWindow('quiet', clock=clock, lead_ns=lead)
            t0 = w.open(clock.monotonic_ns(), manifest())
            self.assertEqual(t0, clock.monotonic_ns() + lead)
            self.assertEqual(w.worker_count, 0)
            self.assertEqual(w.lead_ns, lead)
            self.assertEqual(w.plan.nominal_end_ns, t0 + NOMINAL_NS)
            self.assertEqual(w.plan.end_ns, t0 + WORKER_END_NS)
            w.await_start()
            self.assertEqual(w.plan.start_ns, t0)
            self.assertGreaterEqual(w.start_observed_ns, t0)
            w.abort('test_cleanup')

    def test_default_window_still_uses_4s(self):
        clock = r1test.FakeClock(2_000_000_000)
        w = SegmentWindow('quiet', clock=clock)
        t0 = w.open(clock.monotonic_ns(), manifest())
        self.assertEqual(t0 - clock.monotonic_ns(), LEAD_LONG_NS)
        w.abort('test_cleanup')


class DriverTests(unittest.TestCase):
    def run_all(self, condition=True, resources=True, fail_at=None, observer=True):
        device = PlanDevice(fail_at=fail_at)
        recs = records(); windows=[]
        def factory(index, candidate, conf, record):
            w = StartupWindow(device, candidate, condition=condition, resources=resources)
            windows.append(w); w.record=record
            return w
        def obs_factory(index, candidate, record):
            return SegmentStageObservation(clock=time.monotonic_ns, segment_id=SEGMENT_IDS[index])
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_candidates(
                device, SNAPS, RUN, PLANS, 'performance', Path(tmp), device.clock,
                _require, maths, list(SEGMENT_IDS), manifest(), recs,
                _augment, lambda record, out: device.trace.append(('write', record['segment_id'])),
                confs=[manifest() for _ in RUN], window_factory=factory,
                stage_observer_factory=(obs_factory if observer else None))
        return device, recs, windows, summary

    def test_A_B_B_A_uses_declared_lead_and_no_worker(self):
        device, recs, windows, summary = self.run_all()
        self.assertEqual([w.lead_ns for w in windows],
                         [10_000_000, 4_000_000_000, 4_000_000_000, 10_000_000])
        self.assertEqual([w.worker_count for w in windows], [0, 0, 0, 0])
        self.assertEqual(len(summary), 4)
        for record, window in zip(recs, windows):
            self.assertEqual(record['t0_ns'], window.plan.start_ns)
            self.assertEqual(record['window_t0_ns'], window.plan.start_ns)
            self.assertEqual(record['interference']['lead_ns'], window.lead_ns)
            self.assertEqual(record['interference']['worker_count'], 0)
            self.assertEqual(record['interference']['worker_evidence']['quiet_no_worker'], True)
            self.assertTrue(record['condition_valid'])

    def test_t0_is_single_after_preparation_boundary(self):
        device = PlanDevice()
        device.trace.append(('ready', 'preparation_complete'))
        recs = records(); windows=[]
        def factory(index, candidate, conf, record):
            w = StartupWindow(device, candidate); windows.append(w); w.record=record; return w
        with tempfile.TemporaryDirectory() as tmp:
            run_candidates(device, SNAPS, RUN, PLANS, 'performance', Path(tmp), device.clock,
                           _require, maths, list(SEGMENT_IDS), manifest(), recs,
                           _augment, None, confs=[manifest() for _ in RUN], window_factory=factory,
                           stage_observer_factory=lambda i, c, r: SegmentStageObservation(
                               clock=time.monotonic_ns, segment_id=SEGMENT_IDS[i]))
        first_ready = next(i for i, x in enumerate(device.trace) if x[0] == 'ready')
        for i, (record, window) in enumerate(zip(recs, windows)):
            open_at = next(j for j, x in enumerate(device.trace)
                           if x[0] == 'window_open' and j > first_ready)
            self.assertLess(first_ready, open_at)
            self.assertEqual(record['window_t0_ns'], window.plan.start_ns)
            self.assertEqual(record['window_t0_ns'], window.prepared_ns + window.lead_ns)
            self.assertGreaterEqual(window.plan.start_ns, window.prepared_ns)
            self.assertEqual(window.worker_count, 0)
            self.assertEqual(len([x for x in device.trace if x[0] == 'window_open'
                                  and x[1] == window.candidate['cell']]), 2)

    def test_stage_observation_is_complete_ordered_and_counted(self):
        device, recs, windows, summary = self.run_all()
        for record in recs:
            obs = record['stage_observation']
            self.assertTrue(obs['complete'], obs['missing'])
            self.assertEqual(obs['stage_count'], 4)
            self.assertEqual(len(obs['stages']), 4)
            for stage in obs['stages']:
                values = [stage['timestamps'][n] for n in TIMESTAMP_NAMES]
                self.assertEqual(values, sorted(values))
                self.assertEqual(values[0], stage['timestamps']['stage_enter'])
                self.assertEqual(values[-1], stage['timestamps']['stage_exit'])
                counts = stage['counts']
                self.assertEqual(counts['event_records'], 4)
                self.assertEqual(counts['restore_calls'], 2)
                self.assertEqual(counts['capture_calls'], 2)
                self.assertEqual(counts['confirmation_calls'], 1)
                self.assertGreaterEqual(counts['event7_polls'], 1)
            self.assertEqual(len(record['experts']), 8)
            self.assertEqual(len(record['published']), 4)

    def test_observation_does_not_change_gpu_trace(self):
        a, ar, aw, asum = self.run_all(observer=True)
        b, br, bw, bsum = self.run_all(observer=False)
        self.assertEqual(a.trace, b.trace)
        self.assertEqual(len(ar), len(br))
        self.assertIn('stage_observation', ar[0])
        self.assertNotIn('stage_observation', br[0])

    def test_unsafe_quiet_resources_stop_validation_and_write(self):
        device, recs, windows, summary = self.run_all(resources=False)
        self.assertEqual(len(summary), 1)
        self.assertFalse(summary[0]['condition_valid'])
        self.assertTrue(device.leased)
        self.assertFalse(any(x[0] == 'deferred' for x in device.trace))
        self.assertFalse(any(x[0] == 'write' for x in device.trace))
        self.assertFalse(any(x[0] == 'release_bank' for x in device.trace))

    def test_replay_failure_keeps_segment_id_and_skips_deferred_work(self):
        device = PlanDevice(fail_at='E1')
        recs = records(); windows=[]
        def factory(index, candidate, conf, record):
            w = StartupWindow(device, candidate); windows.append(w); w.record=record; return w
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TimeoutError):
                run_candidates(device, SNAPS, RUN, PLANS, 'performance', Path(tmp),
                               device.clock, _require, maths, list(SEGMENT_IDS),
                               manifest(), recs, _augment, None,
                               confs=[manifest() for _ in RUN], window_factory=factory,
                               stage_observer_factory=lambda i, c, r: SegmentStageObservation(
                                   clock=time.monotonic_ns, segment_id=SEGMENT_IDS[i]))
        self.assertEqual(recs[0]['status'], 'FAILED_REPLAY')
        self.assertEqual(recs[0]['stage_observation']['segment_id'], SEGMENT_IDS[0])
        self.assertFalse(any(x[0] == 'deferred' for x in device.trace))
        self.assertFalse(any(x[0] == 'write' for x in device.trace))


class EntryTests(unittest.TestCase):
    def test_dry_run_protocol_and_config(self):
        proc = subprocess.run(
            [sys.executable, str(HERE/'pi05_m3_b7_stage_startup.py'), '--dry-run',
             '--config', str(PACKAGE/'CONFIG.json')],
            cwd=HERE, text=True, capture_output=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        doc = json.loads(proc.stdout)
        self.assertEqual(doc['protocol']['id'], PROTOCOL)
        self.assertEqual(len(doc['protocol']['run']), 4)
        self.assertEqual(doc['protocol']['timing']['lead_A_ns'], 10_000_000)
        self.assertEqual(doc['protocol']['timing']['lead_B_ns'], 4_000_000_000)
        self.assertEqual(doc['protocol']['limits']['pressure_workers'], 0)
        self.assertIn('source_sha256', doc['preparation_reuse'])

    def test_config_round_trip(self):
        self.assertEqual(json.loads((PACKAGE/'CONFIG.json').read_text()), protocol())

    def test_refuses_without_this_batch_token(self):
        proc = subprocess.run(
            [sys.executable, str(HERE/'pi05_m3_b7_stage_startup.py')],
            cwd=HERE, text=True, capture_output=True, timeout=60)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('B7 stage-startup approval', proc.stderr)

    def test_entry_uses_one_window_factory_and_stage_observer(self):
        src = (HERE/'pi05_m3_b7_stage_startup.py').read_text()
        tree = ast.parse(src)
        self.assertIn('SegmentWindow', src)
        self.assertIn("SegmentWindow('quiet', lead_ns=candidate['lead_ns'])", src)
        self.assertIn('stage_observer_factory=stage_observer_factory', src)
        self.assertEqual(src.count('--approved-m3-b7-stage-startup-v1'), 1)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'run_candidates']
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(k.arg == 'window_factory' for k in calls[0].keywords))
        self.assertTrue(any(k.arg == 'stage_observer_factory' for k in calls[0].keywords))

    def test_control_tokens_and_permission_gate(self):
        import m3_b7_control as c
        src = Path(c.__file__).read_text()
        self.assertIn('from m3_b7_plan import PROTOCOL, protocol', src)
        self.assertEqual(src.count('--approved-m3-b7-stage-startup-v1'), 3)
        self.assertEqual(src.count('m3_b7_control.py'), 2)
        self.assertNotIn('m3_b6', src)
        self.assertEqual(c.PROTOCOL, PROTOCOL)
        old = sys.argv
        sys.argv = ['m3_b7_control.py', 'submit', '--base', str(Path(c.__file__).resolve().parent),
                    '--run', str(Path(c.__file__).resolve().parent/'run_01'),
                    '--credential-sha', '0'*64,
                    '--approved-m3-b7-stage-startup-v1']
        try:
            with self.assertRaises(PermissionError):
                c.main()
        finally:
            sys.argv = old


class EntryMainCredentialTests(unittest.TestCase):
    """Actual B7 main before any GPU import."""
    def setUp(self):
        self.entry = __import__('pi05_m3_b7_stage_startup')
        self.control = __import__('m3_b7_control')
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
        flag = '--approved-m3-b7-stage-startup-v1'
        old_argv, old_prepare = sys.argv, self.entry.prepare
        old_env = os.environ.get('COOVERLAP_APPROVED_BATCH')
        os.environ['COOVERLAP_APPROVED_BATCH'] = PROTOCOL
        self.entry.prepare = lambda *a, **k: (_ for _ in ()).throw(PrepareSentinel())
        sys.argv = [str(self.entry.__file__), flag, '--verification-mode', 'performance',
                    '--config', str(self.package/'CONFIG.json'),
                    '--reference', str(self.package/'reference'),
                    '--source-preflight', str(self.run/'PREFLIGHT.json'),
                    '--out', str(self.out)]
        before = {name for name in ('torch', 'm2_clean_cuda', 'flash_rt') if name in sys.modules}
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
            after = {name for name in ('torch', 'm2_clean_cuda', 'flash_rt') if name in sys.modules}
            self.assertEqual(after, before, 'CPU credential path imported GPU modules')
        return reached

    def test_valid_credential_reaches_controlled_prepare_sentinel(self):
        cred = self.credential()
        self.assertTrue(self.invoke(cred))
        self.assertTrue(self.out.is_dir())
        report = json.loads((self.out/'result.json').read_text())
        self.assertEqual(report['status'], 'FAIL_OR_INCOMPLETE')
        self.assertEqual(report['partial_retention_status'], 'NOT_EXPORTED_no_active_segment')

    def test_wrong_protocol_is_rejected_before_prepare(self):
        cred = self.credential(protocol='not_this_batch')
        with self.assertRaises(ValueError):
            self.invoke(cred)
        self.assertFalse(self.out.exists())

    def test_expired_credential_is_rejected_before_prepare(self):
        cred = self.credential(created=time.time()-601)
        with self.assertRaises(ValueError):
            self.invoke(cred)
        self.assertFalse(self.out.exists())


class PrepareSentinel(Exception):
    pass


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = dict(status='PASS' if result.wasSuccessful() else 'FAIL',
                tests=result.testsRun, failures=len(result.failures),
                errors=len(result.errors), skipped=len(result.skipped),
                scope='CPU: B7 lead/order, shared SegmentWindow, preallocated stage observer, '
                      'actual BoundaryBackend stage order, B6 r1 resource gate, work/ledger/disk, '
                      'CLI/credential; no GPU/model/worker/SSH/hardware',
                model_starts=0, worker_starts=0, ssh=0, hardware_writes=0, scopes=0)
    if args.json:
        args.json.write_text(json.dumps(data, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
