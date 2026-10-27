"""CPU regression for the REAL two-block/three-block adapter ledger contract.

Calls `CudaDevice.run_math` and the real `CallLedger` on a fake pipeline (no CUDA
initialisation). This is the path that previously mangled the two-block B1
expectation into `('encoder', 'language')` and would have been rejected at run
time. Scheduling is covered elsewhere; here the adapter and the ledger are real.
"""
import argparse
import json
import sys
import unittest
from pathlib import Path

from m2_clean_cuda import CudaDevice
from m2_executor import BLOCKS, DECODER, DECODER_CALLS, expected_calls
from m2_pi05_ops import CallLedger, block1, block2, encoder_block, prefix_block
from m3_b3_plan import CONTROL, THREE


class FakePipe:
    """Deterministic stand-in for a Pi0.5 pipeline: only the wrapped calls exist."""

    def __init__(self):
        self.calls = []
        self.bufs = {k: type('B', (), dict(ptr=type('P', (), dict(value=i))()))()
                     for i, k in enumerate(('vision_x_pooled', 'vision_x_norm', 'encoder_x'))}
        self.weights = {k: None for k in ('vision_final_norm_w', 'vision_final_norm_b',
                                          'encoder_multi_modal_projector_w',
                                          'encoder_multi_modal_projector_b')}
        self.fvk = self
        self.gemm = self
        self.vision_seq_enc = 512

    def layer_norm(self, *a, **k):
        pass

    def add_bias_bf16(self, *a, **k):
        pass

    def bf16_nn(self, *a, **k):
        pass

    def _copy_lang_embeds_to_encoder_x(self, stream=0):
        self.calls.append(('language',))

    def vision_encoder(self, stream=0):
        self.calls.append(('vision27',))

    def _encoder_layer(self, i, seq, fuse_b1, stream):
        self.calls.append(('encoder', i))

    def _decoder_layer(self, i, step, enc_seq, ds, skip_c1, stream):
        self.calls.append(('decoder', step, i))

    def transformer_decoder(self, stream=0):
        for step in range(10):
            for i in range(18):
                self._decoder_layer(i, step, 561, None, False, stream)


def make_device(plans, pipes):
    d = CudaDevice.__new__(CudaDevice)
    d.deadline = 10**30
    d.clock = lambda: 0
    d.window = False
    d.mode = 'performance'
    d.namespace = 'segment'
    d.epoch = 0
    d.segment_id = 'seg_adapter'
    d.segment_ids = {'seg_adapter'}
    d.plan = plans
    d.ps = list(pipes)
    d.ledger = CallLedger(list(pipes))
    return d


TWO_MATH = dict(B1=lambda p: block1(p, 2048, 1152), B2=block2)
THREE_MATH = dict(P=lambda p: prefix_block(p, 2048, 1152),
                  B1=lambda p: encoder_block(p, 0, 9), B2=block2)


def observed(ledger, key):
    return [row[2:] for row in ledger.calls if row[0] == key]


class AdapterTests(unittest.TestCase):
    def test_expected_calls_mapping_for_every_plan_block(self):
        self.assertEqual(expected_calls(BLOCKS[0]),
                         [('language',), ('vision27',)] + [('encoder', i) for i in range(9)])
        self.assertEqual(expected_calls(BLOCKS[1]), [('encoder', i) for i in range(9, 18)])
        self.assertEqual(expected_calls(THREE.blocks[0]), [('language',), ('vision27',)])
        self.assertEqual(expected_calls(THREE.blocks[1]), [('encoder', i) for i in range(9)])
        self.assertEqual(expected_calls(THREE.blocks[2]),
                         [('encoder', i) for i in range(9, 18)])
        for plan in (CONTROL, THREE):
            for work in plan.blocks:
                for call in expected_calls(work):
                    self.assertIn(call[0], ('language', 'vision27', 'encoder'))
                    if call[0] == 'encoder':
                        self.assertIsInstance(call[1], int, 'encoder id must be a layer index')
        with self.assertRaises(ValueError):
            expected_calls(('norm', 'unreviewed-op'))

    def test_two_block_b1_and_b2_agree_with_the_real_ledger(self):
        seen = {}
        for kind, key in (('B1', 'R0/B1'), ('B2', 'R0/B2')):
            pipe = FakePipe()
            d = make_device(CONTROL, [pipe])
            d.block_math = dict(TWO_MATH)
            work = d.run_math(key, 0, kind)
            self.assertEqual(tuple(work), CONTROL.blocks[0 if kind == 'B1' else 1])
            seen[kind] = observed(d.ledger, 'seg_adapter/'+key)
            self.assertEqual(seen[kind],
                             expected_calls(CONTROL.blocks[0 if kind == 'B1' else 1]))
        self.assertEqual(seen['B1'][:2], [('language',), ('vision27',)])
        self.assertEqual([c[1] for c in seen['B1'] if c[0] == 'encoder'], list(range(9)))

    def test_three_block_blocks_agree_with_the_real_ledger(self):
        seen = {}
        for kind, index in (('P', 0), ('B1', 1), ('B2', 2)):
            pipe = FakePipe()
            d = make_device(THREE, [pipe])
            d.block_math = dict(THREE_MATH)
            key = 'R0/B'+str(index+1)
            work = d.run_math(key, 0, kind)
            self.assertEqual(tuple(work), THREE.blocks[index])
            seen[kind] = observed(d.ledger, 'seg_adapter/'+key)
            self.assertEqual(seen[kind], expected_calls(THREE.blocks[index]))
        self.assertEqual(seen['P'], [('language',), ('vision27',)])
        self.assertFalse(any(row[0] == 'encoder' for row in seen['P']))

    def test_expert_requires_the_complete_decoder_sequence(self):
        pipe = FakePipe()
        d = make_device(THREE, [pipe])
        work = d.run_math('E0', 0, 'Expert')
        self.assertEqual(tuple(work), DECODER)
        rows = observed(d.ledger, 'seg_adapter/E0')
        # work is the (step, layer) pair list; observed rows carry the call name.
        self.assertEqual(tuple(rows), DECODER_CALLS)
        self.assertEqual(tuple((step, layer) for _, step, layer in rows), DECODER)
        self.assertEqual(len(rows), 180)

    def test_missing_duplicate_or_extra_calls_are_rejected(self):
        def missing(p):
            p._copy_lang_embeds_to_encoder_x(stream=0)
            p.vision_encoder(0)
            for i in range(9):
                if i != 4:
                    p._encoder_layer(i, 561, False, 0)

        def duplicated(p):
            p._copy_lang_embeds_to_encoder_x(stream=0)
            p.vision_encoder(0)
            for i in range(9):
                p._encoder_layer(i, 561, False, 0)
                if i == 2:
                    p._encoder_layer(i, 561, False, 0)

        def extra_language(p):
            p._copy_lang_embeds_to_encoder_x(stream=0)
            p._copy_lang_embeds_to_encoder_x(stream=0)
            p.vision_encoder(0)
            for i in range(9):
                p._encoder_layer(i, 561, False, 0)

        for fn in (missing, duplicated, extra_language):
            pipe = FakePipe()
            d = make_device(CONTROL, [pipe])
            d.block_math = dict(B1=fn)
            with self.assertRaises(RuntimeError):
                d.run_math('R0/B1', 0, 'B1')

    def test_wrong_slot_is_rejected(self):
        pa, pb = FakePipe(), FakePipe()
        d = make_device(THREE, [pa, pb])
        d.block_math = dict(P=lambda p: prefix_block(pb, 2048, 1152))
        with self.assertRaises(RuntimeError):
            d.run_math('R0/B1', 0, 'P')
        self.assertEqual(observed(d.ledger, 'seg_adapter/R0/B1'), [('language',), ('vision27',)])

    def test_segment_identity_is_part_of_every_ledger_key(self):
        pipe = FakePipe()
        d = make_device(THREE, [pipe])
        d.block_math = THREE_MATH
        d.run_math('R0/B2', 0, 'B1')
        self.assertTrue(all(row[0] == 'seg_adapter/R0/B2' for row in d.ledger.calls))
        with self.assertRaises(RuntimeError):
            d.set_segment_id('seg_adapter')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(AdapterTests))
    data = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests=result.testsRun,
                failures=len(result.failures), errors=len(result.errors),
                scope='CPU: real CudaDevice.run_math + real CallLedger on a fake pipeline; '
                      'no GPU correctness or performance claim',
                model_starts=0, hardware_writes=0, scopes=0)
    if args.json:
        args.json.write_text(json.dumps(data, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
