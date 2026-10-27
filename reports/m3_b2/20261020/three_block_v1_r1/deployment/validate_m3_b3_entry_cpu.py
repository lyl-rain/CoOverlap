"""CPU regressions that drive the REAL entry orchestration (no GPU, no Torch).

These exercise `m3_b3_orchestrate`, which `pi05_m3_b3_prepare.py` calls unchanged:
two-slot prefix reference completion, both gates with exact journal content/order,
two different plans run consecutively with persistence, and the total call counts.
"""
import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from m2_clean_core import gate_retention_layout, retention_layout
from m2_executor import VersionedKV
from m3_b2_backend import BoundaryBackend
from m3_b3_orchestrate import (expected_gate_signature, journal_signature, run_candidates,
                               run_gate, run_prefix_reference)
from m3_b3_plan import (CANDIDATES, CONTROL, CYCLES, PLANS, PROTOCOL, SEGMENT_IDS, THREE,
                        manifest, protocol)
from validate_m3_b3_cpu import PlanDevice, SNAPS, maths

JOURNAL_ENTRIES = dict(old_reader=22, interrupt=24)


class FakePipe:
    """Deterministic stand-in for a pipeline: records the real call sequence."""

    def __init__(self):
        self.calls = []
        self.x = ('prefix',)
        self.kv = ()
        self.bufs = {k: type('B', (), dict(ptr=type('P', (), dict(value=i))()))()
                     for i, k in enumerate(('vision_x_pooled', 'vision_x_norm', 'encoder_x'))}
        self.weights = {k: None for k in ('vision_final_norm_w', 'vision_final_norm_b',
                                          'encoder_multi_modal_projector_w',
                                          'encoder_multi_modal_projector_b')}
        self.fvk = self
        self.gemm = self
        self.vision_seq_enc = 512

    def layer_norm(self, *a, **k):
        self.calls.append(('norm',))

    def add_bias_bf16(self, *a, **k):
        self.calls.append(('bias',))

    def bf16_nn(self, *a, **k):
        self.calls.append(('gemm',))

    def _copy_lang_embeds_to_encoder_x(self, stream=0):
        self.calls.append(('language',))

    def vision_encoder(self, stream=0):
        self.calls.append(('vision27',))

    def _encoder_layer(self, i, seq, fuse_b1, stream):
        self.calls.append(('encoder', i))
        self.kv = tuple(sorted(set(self.kv) | {i}))
        self.x = ('layer', i)


def fake_snap(p, name, layers=18):
    return (repr(p.x).encode(), b'kv'+bytes(p.kv[:layers]), b'v'+bytes(p.kv[:layers]))


class FakeLedger:
    def __init__(self):
        self.executed = []

    def execute(self, key, slot, kind, fn, expected=None, work=None):
        before = len(CURRENT[0].calls)
        fn()
        self.executed.append(dict(key=key, slot=slot, kind=kind,
                                  calls=tuple(CURRENT[0].calls[before:])))
        return work


CURRENT = [None]


def reference_state():
    """Expected prefix/mid/full triplets from the validated two-block sequence."""
    p = FakePipe()
    CURRENT[0] = p
    from m2_pi05_ops import block1, block2
    stage_calls = []
    block1(p, 2048, 1152)
    mid = fake_snap(p, 'mid', 9)
    block2(p)
    full = fake_snap(p, 'full', 18)
    return p, mid, full


class EntryTests(unittest.TestCase):
    def test_prefix_reference_two_slots_complete_and_verify_full_context(self):
        for slot in (0, 1):
            p, midref, fullref = reference_state()
            CURRENT[0] = p
            staged = []
            ledger = FakeLedger()
            checks = []

            def require(ok, name):
                checks.append((name, bool(ok)))
                if not ok:
                    raise AssertionError(name)

            def stage(pipe, with_images=False):
                staged.append((slot, bool(with_images)))

            prefix = run_prefix_reference(p, slot, stage, fake_snap, ledger,
                                          __import__('m2_pi05_ops').block1,
                                          __import__('m2_pi05_ops').block2, 2048, 1152,
                                          require, [(fullref, b'raw', b'act')]*2, [midref]*2)
            self.assertEqual(staged, [(slot, True)])
            kinds = [row['kind'] for row in ledger.executed]
            self.assertEqual(kinds, ['B1', 'B2'], 'the prefix reference must complete B2')
            encoder = [c for row in ledger.executed for c in row['calls'] if c[0] == 'encoder']
            self.assertEqual([c[1] for c in encoder], list(range(18)))
            self.assertEqual(sum(1 for row in ledger.executed for c in row['calls']
                                 if c[0] == 'language'), 1)
            self.assertEqual(sum(1 for row in ledger.executed for c in row['calls']
                                 if c[0] == 'vision27'), 1)
            self.assertIn(('prefix_snapshot_once', True), checks)
            self.assertIn(('prefix_reference_path_matches_validated_mid', True), checks)
            self.assertIn(('prefix_reference_full_context_byte_exact', True), checks)
            self.assertEqual(prefix, fake_snap(p, 'p', 0)[0])

    def test_prefix_reference_rejects_incomplete_context(self):
        p, midref, fullref = reference_state()
        CURRENT[0] = p

        def require(ok, name):
            if not ok:
                raise AssertionError(name)
        bad = list(fullref)
        bad[0] = b'wrong'
        with self.assertRaises(AssertionError):
            run_prefix_reference(p, 0, lambda *a, **k: None, fake_snap, FakeLedger(),
                                 __import__('m2_pi05_ops').block1,
                                 __import__('m2_pi05_ops').block2, 2048, 1152, require,
                                 [(tuple(bad), b'raw', b'act')]*2, [midref]*2)

    def test_both_gates_have_exact_content_and_order(self):
        observed = {}
        for interleave, name in ((False, 'old_reader'), (True, 'interrupt')):
            device = PlanDevice(plan=THREE)
            backend = BoundaryBackend(device, SNAPS, 'correctness',
                                      layout=gate_retention_layout(CYCLES, THREE), plan=THREE)
            manager = VersionedKV(THREE)
            checks = []

            def require(ok, check_name, checks=checks):
                checks.append((check_name, bool(ok)))
                if not ok:
                    raise AssertionError(check_name)
            result = run_gate(backend, manager, SNAPS, SNAPS[0].noise_sha, THREE, interleave,
                              require, {})
            expected = expected_gate_signature(THREE, interleave)
            self.assertEqual(result['entries'], JOURNAL_ENTRIES[name])
            self.assertEqual(len(expected), JOURNAL_ENTRIES[name])
            self.assertEqual(journal_signature(manager.journal), expected,
                             'gate journal content/order must match, not just its length')
            self.assertEqual(result['journal'], [tuple(row) for row in manager.journal])
            names = [c[0] for c in checks]
            self.assertIn('prefix_only_cannot_publish', names)
            self.assertIn('prefix_state_reports_zero_effective_kv', names)
            self.assertIn('layers_after_encoder_0_8', names)
            self.assertIn('layers_after_encoder_9_17', names)
            self.assertIn('old_reader_prevents_reuse', names)
            self.assertIn('full_context_published', names)
            backend.validate_and_persist()
            observed[name] = len(manager.journal)
        self.assertEqual(observed, JOURNAL_ENTRIES)
        self.assertEqual(protocol()['gates']['old_reader']['journal_entries'], 22)
        self.assertEqual(protocol()['gates']['interrupt']['journal_entries'], 24)

    def test_two_plans_run_consecutively_with_persistence_and_unique_ids(self):
        device = PlanDevice()
        records = [dict(index=i, candidate=c['id'], plan=c['plan'], segment_id=SEGMENT_IDS[i],
                        status='NOT_STARTED') for i, c in enumerate(CANDIDATES)]
        math_for = lambda plan: {k: (lambda p: None) for k in plan.kinds}
        checks = []

        def require(ok, name):
            checks.append((name, bool(ok)))
            if not ok:
                raise AssertionError(name)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = run_candidates(device, SNAPS, CANDIDATES, PLANS, 'performance', out,
                                     device.clock, require, math_for, list(SEGMENT_IDS),
                                     manifest(), records, _augment, _write_tables)
            self.assertEqual([row['segment_id'] for row in summary], list(SEGMENT_IDS))
            self.assertEqual([row['plan'] for row in summary],
                             ['two_9_9', 'three_prefix_9_9'])
            self.assertEqual([row['blocks'] for row in summary], [2, 3])
            self.assertEqual(device.segment_ids, set(SEGMENT_IDS))
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(SEGMENT_IDS))
            for record, segment_id, plan in zip(records, SEGMENT_IDS,
                                                (CONTROL, THREE)):
                self.assertEqual(record['segment_id'], segment_id)
                keys = [x[1] for x in device.trace if x[0] == 'math' and x[1].startswith(segment_id)]
                self.assertEqual(len(keys), CYCLES + CYCLES//2*len(plan))
                self.assertTrue(all(k.startswith(segment_id+'/') for k in keys))
                expert_keys = [k for k in keys if '/E' in k]
                self.assertEqual(len(expert_keys), CYCLES)
        # bank released only after a successful validate_and_persist, twice
        self.assertFalse(device.leased)
        self.assertEqual(sum(1 for x in device.trace if x[0] == 'deferred'), 2)
        self.assertIn(('segment_retention_and_calls_exact', True), checks)
        self.assertIn(('segment_id_threaded_through_record', True), checks)
        with self.assertRaises(RuntimeError):
            device.set_segment_id('seg0_control_two_9_9')

    def test_total_call_counts_match_the_declared_split(self):
        p = protocol()
        batch = p['work']['batch']
        observed = p['work']['observed_ledger']
        self.assertEqual((batch['total_C'], batch['total_E']), (18, 14))
        self.assertEqual(sum(v for k, v in batch.items()
                             if k.endswith('_C') and k != 'total_C'), 18)
        self.assertEqual(sum(v for k, v in batch.items()
                             if k.endswith('_E') and k != 'total_E'), 14)
        self.assertEqual((observed['contexts'], observed['experts']), (15, 13))
        self.assertEqual(observed['contexts']*(18+1+1)+observed['experts']*180,
                         observed['rows'])
        self.assertEqual(observed['rows'], 2640)
        self.assertEqual(observed['encoder_layers'], 270)
        self.assertEqual(observed['decoder_layers'], 2340)
        self.assertEqual(len(observed['excluded']), 2)

    def test_entry_calls_the_tested_orchestration(self):
        entry = (Path(__file__).parent/'pi05_m3_b3_prepare.py').read_text()
        for name in ('run_gate', 'run_prefix_reference', 'run_candidates'):
            self.assertIn('from m3_b3_orchestrate import', entry)
            self.assertIn(name+'(', entry)
        # The entry must not re-implement the gate sequence or the prefix walk.
        self.assertNotIn('prefix_only_cannot_publish', entry)
        self.assertNotIn("manager.bind('hold'", entry)
        self.assertIn('SEGMENT_IDS', entry)
        self.assertIn('device.set_segment_id(segment_id)', entry)
        self.assertIn("require(len(ledger.calls) == observed['rows']", entry)


def _augment(record):
    return dict(units=len(record.get('units', {})))


def _write_tables(record, out):
    Path(out).mkdir(exist_ok=True)
    (Path(out)/'cycles.csv').write_text('cycle\n')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(EntryTests))
    data = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests=result.testsRun,
                failures=len(result.failures), errors=len(result.errors),
                scope='CPU orchestration of the real entry: prefix reference, gates, candidate '
                      'loop and call counts; no GPU correctness or performance claim',
                model_starts=0, hardware_writes=0, scopes=0)
    if args.json:
        args.json.write_text(json.dumps(data, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
