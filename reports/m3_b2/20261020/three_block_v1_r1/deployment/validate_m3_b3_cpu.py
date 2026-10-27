"""CPU-only validation of the M3 three-block candidate. No CUDA/Torch import.

Covers state transitions, publish guards, retention/obligation semantics, the
arrival/boundary policy branches and the frozen-work budget. Passing here proves
symbolic logic only, never GPU correctness or performance.
"""
import argparse
import ast
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
import validate_m2_clean_cpu as old
from m2_executor import Handle, Snapshot, VersionedKV, DEFAULT_PLAN
from m2_clean_core import SIZES, RetentionLedger, gate_retention_layout, retention_layout
from m2_clean_backend import CleanBackend
from m3_b2_core import run_segment
from m3_b3_plan import (CANDIDATES, CONTROL, CYCLES, PHASE_NS, PROTOCOL, THREE,
                        budget, manifest, protocol)

SNAPS = old.SNAPS


class PlanDevice(old.Device):
    """Symbolic device with declared per-block durations and plan semantics."""

    def __init__(self, plan=THREE, phase=None, prefix=30_000_000, b1=49_000_000,
                 b2=44_000_000, expert=74_000_000, **kw):
        super().__init__(**kw)
        self.plan = plan
        self.durations = dict(P=prefix, B1=b1, B2=b2, Expert=expert)
        self.phase = phase
        self.events = {}

    def mark(self, key, index):
        e = super().mark(key, index)
        self.events.setdefault(key, [None]*8)[index] = e
        return e

    def use_plan(self, plan, block_math=None):
        self.plan = plan

    def set_segment_id(self, value):
        if not isinstance(value, str) or not value:
            raise ValueError('segment id must be a non-empty string')
        if value in getattr(self, 'segment_ids', set()):
            raise RuntimeError('duplicate segment id: '+value)
        self.segment_ids = getattr(self, 'segment_ids', set()) | {value}
        self.segment_id = value

    def label(self):
        return (getattr(self, 'segment_id', None)
                or (getattr(self, 'namespace', 'segment')+str(getattr(self, 'epoch', 0))))

    def wait_event(self, event):
        if not event.query():
            raise TimeoutError('injected finite Event wait')
        return self.clock()

    def bootstrap(self, m, snapshots, key):
        self.outside('bootstrap')
        h = m.begin(0, snapshots[0])
        e = old.Event()
        for b in range(len(m.plan)):
            m.submit_block(h, b, snapshots[0], m.plan.blocks[b], e)
            assert m.poll_block(h)
        assert m.get(h).valid_layers == 18
        m.publish(h)
        self.physical[0].update(v=0, state='full')
        self.now += 100_000_000
        self.trace.append(('bootstrap',))

    def run_math(self, key, slot, kind):
        self.trace.append(('math', self.label()+'/'+key, slot, kind))
        if key == self.fail_at:
            raise TimeoutError('injected unfinished work')
        s = self.physical[slot]
        if kind == 'Expert':
            assert s['state'] == 'full', 'Expert must consume a fully published prefix'
            s.update(raw_job=key, raw_version=s['v'], noise='overwritten')
            self.now += self.durations['Expert']
            from m2_executor import DECODER
            return DECODER
        b = self.plan.kinds.index(kind)
        if kind == 'P':
            s.update(v=self.nextv, state='prefix')
            self.nextv += 1
        elif kind == 'B1' and self.plan is CONTROL:
            s.update(v=self.nextv, state='mid')
            self.nextv += 1
        elif kind == 'B1':
            assert s['state'] == 'prefix'
            s['state'] = 'mid'
        else:
            assert s['state'] in ('mid', 'prefix')
            s['state'] = 'full'
        self.now += self.durations[kind]
        return self.plan.blocks[b]


def run(plan=THREE, policy='b2_boundary', period=240_000_000, cycles=CYCLES,
        mode='performance', phase=PHASE_NS, **kw):
    d = PlanDevice(plan=plan, **kw)
    conf = manifest(period, cycles, phase)
    b = CleanBackend(d, SNAPS, mode, layout=retention_layout(cycles, plan), plan=plan)
    from m3_b2_backend import BoundaryBackend
    backend = BoundaryBackend(b.d, SNAPS, mode, layout=retention_layout(cycles, plan), plan=plan)
    m = VersionedKV(plan)
    r = {}
    run_segment(m, SNAPS, policy, backend, r, d.clock, conf=conf, expect=conf)
    return d, backend, m, r


def maths(d):
    """Ledger keys are segment-prefixed by the device; tests compare the job part."""
    return [x[1].split('/', 1)[-1] for x in d.trace if x[0] == 'math']


class Tests(unittest.TestCase):
    def test_three_block_plan_semantics(self):
        self.assertEqual(THREE.valid_layers, (0, 9, 18))
        self.assertEqual(THREE.shapes, ('prefix', 'mid', 'full'))
        self.assertEqual(THREE.groups, ((0, 1), (2,)))
        self.assertEqual(THREE.blocks[0], ('language', 'vision27', 'norm', 'project', 'bias'))
        self.assertEqual(THREE.blocks[1], tuple(range(0, 9)))
        self.assertEqual(THREE.blocks[2], tuple(range(9, 18)))
        self.assertEqual(CONTROL.blocks, DEFAULT_PLAN.blocks)
        self.assertEqual(budget()['layouts']['two_9_9'], dict(count=32, nbytes=243660032))

    def test_prefix_state_has_zero_effective_kv_and_cannot_publish(self):
        m = VersionedKV(THREE)
        h = m.begin(1, SNAPS[1])
        e = old.Event()
        m.submit_block(h, 0, SNAPS[1], THREE.blocks[0], e)
        self.assertTrue(m.poll_block(h))
        self.assertEqual(m.get(h).valid_layers, 0, 'prefix creates no effective new KV layer')
        self.assertEqual(m.get(h).phase, 'BUILDING')
        with self.assertRaises(RuntimeError):
            m.publish(h)
        m.submit_block(h, 1, SNAPS[1], THREE.blocks[1], e)
        self.assertTrue(m.poll_block(h))
        self.assertEqual(m.get(h).valid_layers, 9)
        with self.assertRaises(RuntimeError):
            m.publish(h)
        m.submit_block(h, 2, SNAPS[1], THREE.blocks[2], e)
        self.assertTrue(m.poll_block(h))
        self.assertEqual(m.get(h).valid_layers, 18)
        self.assertEqual(m.get(h).phase, 'READY')
        m.publish(h)
        self.assertEqual(m.get(h).phase, 'PUBLISHED')
        layers = [row[3] for row in m.journal if row[0] == 'block_submit']
        self.assertEqual(layers, [0, 9, 18])

    def test_missing_repeated_or_out_of_order_block_rejected(self):
        m = VersionedKV(THREE)
        h = m.begin(1, SNAPS[1])
        e = old.Event()
        with self.assertRaises(RuntimeError):
            m.submit_block(h, 1, SNAPS[1], THREE.blocks[1], e)
        with self.assertRaises(ValueError):
            m.submit_block(h, 0, SNAPS[1], THREE.blocks[1], e)
        with self.assertRaises(RuntimeError):
            m.submit_block(h, 3, SNAPS[1], THREE.blocks[2], e)
        m.submit_block(h, 0, SNAPS[1], THREE.blocks[0], e)
        with self.assertRaises(RuntimeError):
            m.submit_block(h, 0, SNAPS[1], THREE.blocks[0], e)
        self.assertTrue(m.poll_block(h))
        with self.assertRaises(RuntimeError):
            m.submit_block(h, 0, SNAPS[1], THREE.blocks[0], e)

    def test_three_block_segment_transitions_and_publication(self):
        d, backend, m, r = run()
        blocks = [x[1].split('/', 1)[-1] for x in d.trace
                  if x[0] == 'math' and x[1].endswith(('R0/B1', 'R0/B2', 'R0/B3'))]
        self.assertEqual(blocks, ['R0/B1', 'R0/B2', 'R0/B3'])
        self.assertTrue(all(x[1].startswith('segment0/') for x in d.trace if x[0] == 'math'))
        self.assertEqual(r['published_valid_layers'], {0: 18, 1: 18})
        self.assertEqual(len(r['blocks']), CYCLES//2*3)
        self.assertEqual(sorted(r['units']), [(0, 0), (0, 1), (1, 0), (1, 1)])
        self.assertEqual(r['statistics']['units_are_declared_groups'], [[0, 1], [2]])
        backend.validate_and_persist()

    def test_retention_layout_and_capacity_for_three_blocks(self):
        l = retention_layout(CYCLES, THREE)
        self.assertEqual((l['count'], l['nbytes']), (38, 298808576))
        g = gate_retention_layout(CYCLES, THREE)
        self.assertEqual((g['count'], g['nbytes']), (15, 124121472))
        b = budget()
        self.assertEqual(b['bank_bytes'], 298808576)
        self.assertEqual(b['gpu_and_pinned_bytes'], 597617152)
        self.assertEqual(b['gate_bank_bytes'], 124121472)
        self.assertEqual(b['timed_payload_bytes'], 243660032+298808576)
        prefix = [e for e in l['entries'] if e['shape'] == 'prefix']
        self.assertEqual(len(prefix), 2)
        for e in prefix:
            self.assertEqual(e['nbytes'], SIZES['prefix'])
            self.assertEqual(e['nbytes'], 561*2048*2)
        with self.assertRaises(ValueError):
            RetentionLedger(l, l['nbytes']-1)
        bank = RetentionLedger(l, l['nbytes'])
        bank.begin(0)
        with self.assertRaises(ValueError):
            bank.claim([e for e in l['entries'] if e['key'].endswith('/B2/target')][0]['key'],
                       Handle(0, 2, 0), SNAPS[0])

    def test_expert_arrival_during_prefix_precedes_encoder_block(self):
        d, backend, m, r = run(prefix=30_000_000, b1=49_000_000)
        seq = maths(d)
        self.assertEqual(seq[:3], ['R0/B1', 'E0', 'R0/B2'])
        first = next(x for x in r['decisions'] if x['kind'] == 'Context')
        self.assertEqual(first['block_kind'], 'P')
        self.assertEqual(first['valid_layers_expected'], 0)

    def test_expert_arrival_inside_encoder_block_precedes_next_block(self):
        d, backend, m, r = run(prefix=5_000_000, b1=80_000_000)
        seq = maths(d)
        self.assertEqual(seq[:2], ['R0/B1', 'R0/B2'])
        self.assertEqual(seq[2], 'E0')
        self.assertEqual(seq[3], 'R0/B3')

    def test_no_expert_three_blocks_run_back_to_back(self):
        d, backend, m, r = run(prefix=5_000_000, b1=5_000_000, b2=5_000_000)
        seq = maths(d)
        self.assertEqual(seq[:3], ['R0/B1', 'R0/B2', 'R0/B3'])
        self.assertEqual(sum(x['kind'] == 'Expert' for x in r['decisions'][:3]), 0)
        backend.validate_and_persist()

    def test_publication_defers_until_even_consumer_is_reserved(self):
        # Blocks faster than the first Expert release: the refresh may not publish
        # (retiring v0) before E0 is dispatched and thereby reserves E1 on v0.
        d, backend, m, r = run(prefix=5_000_000, b1=5_000_000, b2=5_000_000)
        self.assertTrue(r.get('publication_deferred'), 'deferral must be recorded, never hidden')
        journal = m.journal
        first_publish = next(i for i, x in enumerate(journal) if x[0] == 'publish' and x[1] == 1)
        binds = [x[1] for x in journal[:first_publish] if x[0] == 'bind']
        self.assertEqual(sorted(binds), ['E0', 'E1'])
        self.assertEqual(r['published_valid_layers'], {0: 18, 1: 18})
        self.assertEqual(len(r['experts']), CYCLES)
        backend.validate_and_persist()

    def test_expert_waits_for_version_and_fifo_backlog(self):
        d, backend, m, r = run(expert=350_000_000, cycles=8, phase=0)
        self.assertTrue(any(len(x['version_wait_experts']) >= 1 for x in r['progress']))
        contexts = [x for x in r['arrivals'] if x['kind'] == 'Context']
        self.assertEqual([x['release_ns']-r['t0_ns'] for x in contexts],
                         [0, 480_000_000, 960_000_000, 1440_000_000])
        self.assertTrue(any(x['observed_host_ns'] > x['release_ns'] for x in contexts))
        self.assertGreater(max(x['context_backlog'] for x in r['progress']), 1)
        self.assertEqual([x[1] for x in m.journal if x[0] == 'publish'], list(range(5)))
        self.assertEqual(r['statistics']['backlog'], 0)
        backend.validate_and_persist()

    def test_publish_and_reader_protection_three_blocks(self):
        d, backend, m, r = run()
        self.assertEqual(len([x for x in m.journal if x[0] == 'expert_done']), CYCLES)
        for idx, row in enumerate(m.journal):
            if row[0] == 'reclaim':
                version = row[1]
                done = [i for i, y in enumerate(m.journal)
                        if y[0] == 'expert_done' and y[2] == version]
                self.assertTrue(done)
                self.assertLess(max(done), idx)

    def test_pending_event_timeout_keeps_denominators_and_bank(self):
        class Pending(PlanDevice):
            def mark(self, key, index):
                e = super().mark(key, index)
                if key == 'R0/B2' and index == 7:
                    e.done = False
                return e
        d = Pending()
        conf = manifest()
        backend = __import__('m3_b2_backend').BoundaryBackend(
            d, SNAPS, 'performance', layout=retention_layout(CYCLES, THREE), plan=THREE)
        m = VersionedKV(THREE)
        r = {}
        with self.assertRaises(TimeoutError):
            run_segment(m, SNAPS, 'b2_boundary', backend, r, d.clock, conf=conf, expect=conf)
        self.assertFalse(backend.window)
        self.assertFalse(backend.bank.reusable)
        self.assertEqual(r['statistics']['cycle_counts']['denominator'], CYCLES)
        self.assertEqual(r['statistics']['refresh_counts']['denominator'], CYCLES//2)
        self.assertTrue(r['remaining_Context_ids'])
        self.assertIsNone(r['statistics']['response_upper_p99_ns'])
        self.assertFalse(d.operations.get('R0/B2', {}).get('completed'))
        with self.assertRaises(RuntimeError):
            m.publish(m.slots[1].handle)

    def test_failure_exit_incomplete_not_silent(self):
        d, backend, m, r = None, None, None, None
        d = PlanDevice(fail_at='E1')
        conf = manifest()
        from m3_b2_backend import BoundaryBackend
        backend = BoundaryBackend(d, SNAPS, 'performance', layout=retention_layout(CYCLES, THREE), plan=THREE)
        m = VersionedKV(THREE)
        r = {}
        with self.assertRaises(TimeoutError):
            run_segment(m, SNAPS, 'b2_boundary', backend, r, d.clock, conf=conf, expect=conf)
        self.assertEqual(r['statistics']['cycle_counts']['denominator'], CYCLES)
        self.assertIn(1, r['remaining_Expert_ids'])
        self.assertFalse(backend.bank.reusable)

    def test_deferred_reads_survive_source_overwrite(self):
        d, backend, m, r = run()
        retained = copy.deepcopy(d.outputs)
        d.physical = {0: dict(v=999, state='destroyed'), 1: dict(v=999, state='destroyed')}
        self.assertTrue(backend.validate_and_persist()['pass_'])
        self.assertEqual(retained, d.outputs)
        self.assertTrue(any(k.endswith('/B1/target') for k in d.outputs))

    def test_both_plans_have_identical_work_and_versions(self):
        runs = [run(plan=p) for p in (CONTROL, THREE)]
        (d0, b0, m0, r0), (d1, b1, m1, r1) = runs
        self.assertEqual(r0['manifest']['period_ns'], r1['manifest']['period_ns'])
        self.assertEqual([e['version'] for e in r0['manifest']['experts']],
                         [e['version'] for e in r1['manifest']['experts']])
        self.assertEqual([x[2] for x in m0.journal if x[0] == 'bind'],
                         [x[2] for x in m1.journal if x[0] == 'bind'])
        enc0 = sum(x[0] == 'math' and x[3] in ('B1', 'B2') for x in d0.trace)
        enc1 = sum(x[0] == 'math' and x[3] in ('P', 'B1', 'B2') for x in d1.trace)
        self.assertEqual(enc0, 2*CYCLES//2)          # 2 blocks per refresh
        self.assertEqual(enc1, 3*CYCLES//2)          # 3 blocks per refresh
        self.assertEqual(sum(x[0] == 'math' and x[3] == 'Expert' for x in d0.trace),
                         sum(x[0] == 'math' and x[3] == 'Expert' for x in d1.trace))
        self.assertEqual(len(r0['units']), len(r1['units']))
        b0.validate_and_persist(); b1.validate_and_persist()

    def test_prefix_block_call_sequence_matches_validated_block1_prefix(self):
        from m2_pi05_ops import block1, encoder_block, prefix_block
        calls = {'vision': 0, 'lang': 0, 'enc': [], 'norm': 0, 'gemm': 0, 'bias': 0}

        class Fvk:
            def layer_norm(self, *a, **k): calls['norm'] += 1
            def add_bias_bf16(self, *a, **k): calls['bias'] += 1
        class Gemm:
            def bf16_nn(self, *a, **k): calls['gemm'] += 1
        class P:
            def __init__(self):
                self.bufs = {k: type('B', (), dict(ptr=type('P2', (), dict(value=i))()))()
                             for i, k in enumerate(('vision_x_pooled', 'vision_x_norm', 'encoder_x'))}
                self.weights = {k: None for k in ('vision_final_norm_w', 'vision_final_norm_b',
                                                  'encoder_multi_modal_projector_w',
                                                  'encoder_multi_modal_projector_b')}
                self.fvk, self.gemm, self.vision_seq_enc = Fvk(), Gemm(), 512
            def _copy_lang_embeds_to_encoder_x(self, stream=0): calls['lang'] += 1
            def vision_encoder(self, stream=0): calls['vision'] += 1
            def _encoder_layer(self, i, *a): calls['enc'].append((i, a))
        p = P()
        block1(p, 2048, 1152)
        single = (dict(calls), copy.deepcopy(calls))
        calls.update(vision=0, lang=0, enc=[], norm=0, gemm=0, bias=0)
        prefix_block(p, 2048, 1152)
        encoder_block(p, 0, 9)
        split = (dict(calls), copy.deepcopy(calls))
        self.assertEqual(single, split)
        self.assertEqual([i for i, _ in calls['enc']], list(range(9)))
        self.assertEqual([a for _, a in calls['enc']], [(561, False, 0)]*9)

    def test_protocol_work_and_memory_budget(self):
        p = protocol()
        w = p['work']['batch']
        o = p['work']['observed_ledger']
        self.assertEqual((w['total_C'], w['total_E']), (18, 14))
        self.assertEqual((o['contexts'], o['experts']), (15, 13))
        self.assertEqual(o['rows'], 15*20+13*180)
        self.assertEqual(o['encoder_layers'], 270)
        self.assertEqual(o['decoder_layers'], 2340)
        self.assertEqual(p['gates']['old_reader']['journal_entries'], 22)
        self.assertEqual(p['gates']['interrupt']['journal_entries'], 24)
        self.assertEqual(p['segments']['ids'], ['seg0_control_two_9_9', 'seg1_three_prefix_9_9'])
        self.assertEqual(p['retention']['bank_bytes'], 298808576)
        self.assertEqual(p['retention']['gpu_and_pinned_bytes'], 597617152)
        self.assertEqual(p['phase']['ns'], PHASE_NS)
        self.assertEqual(len(p['candidates']), 2)
        self.assertEqual(p['splits']['isolates_split'], 'C1 - C0 (same policy/arrivals/budget/work, one extra legal cut)')
        self.assertEqual(p['limits']['retries'], 0)
        self.assertEqual(p['limits']['model_processes'], 1)
        self.assertNotIn('torch', sys.modules)
        self.assertNotIn('numpy', sys.modules)

    def test_phase_only_shifts_experts_and_keeps_relative_deadlines(self):
        base = manifest(phase_ns=0)
        phased = manifest(phase_ns=PHASE_NS)
        for a, b in zip(base['experts'], phased['experts']):
            self.assertEqual(b['release_ns']-a['release_ns'], PHASE_NS)
            self.assertEqual(b['deadline_ns']-b['release_ns'], a['deadline_ns']-a['release_ns'])
        self.assertEqual(base['refreshes'], phased['refreshes'])
        with self.assertRaises(ValueError):
            manifest(phase_ns=240_000_000)

    def test_plan_and_core_contain_no_model_math(self):
        base = Path(__file__).parent
        for name in ('m3_b3_plan.py', 'm3_b2_core.py'):
            text = (base/name).read_text()
            self.assertNotIn('_encoder_layer', text)
            self.assertNotIn('gemm', text)
            self.assertNotIn('vision_encoder', text)
        entry = (base/'pi05_m3_b3_prepare.py').read_text()
        self.assertIn('from m2_pi05_ops import encoder_block, prefix_block', entry)
        self.assertNotIn('def prefix_block', entry)

    def test_new_authorization_and_dry_run(self):
        script = Path(__file__).with_name('pi05_m3_b3_prepare.py')
        dry = subprocess.run([sys.executable, str(script), '--dry-run'], capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertEqual(json.loads(dry.stdout)['protocol'], protocol())
        denied = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(denied.returncode, 2)
        self.assertIn('NEW M3 three-block approval', denied.stderr)
        control = (Path(__file__).with_name('m3_b3_control.py')).read_text()
        self.assertIn("'--approved-m3-b3-three-block-v1'", control)
        self.assertIn('cooverlap-m3-b3-three-block-20261021-run01', control)
        self.assertNotIn('--approved-m3-b2-profile-v1', control)
        self.assertIn("'--kill-after=10s','180s'", control)
        self.assertEqual(control.count('subprocess.Popen('), 1)

    def test_window_has_no_intrusive_observation(self):
        d, backend, m, r = run()
        active = False
        for row in d.trace:
            if row[0] == 'window':
                active = row[1]
            if row[0] in ('prepare', 'bootstrap', 'ready', 'deferred', 'eager_compare'):
                self.assertFalse(active)
            if row[0] in ('restore', 'capture', 'math'):
                self.assertTrue(active)
        self.assertFalse(any(x[0] == 'eager_compare' for x in d.trace))
        backend.validate_and_persist()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    data = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests=result.testsRun,
                failures=len(result.failures), errors=len(result.errors),
                scope='CPU symbolic scheduling/ownership/retention only; no GPU correctness or performance claim',
                model_starts=0, hardware_writes=0, scopes=0)
    if args.json:
        args.json.write_text(json.dumps(data, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
