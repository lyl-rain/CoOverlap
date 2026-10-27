#!/usr/bin/env python3
"""Targeted CPU tests for the read-only B7 interval analyzer.

Only the new analysis risk is tested: missing/ordered/negative timestamps,
closure, Event0 formula mutation, 4x4 coverage, source/input hashes and
non-modification of the raw result.  The historical B7 run is not rerun.
"""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULT = HERE.parent / 'gpu_run_01' / 'board' / 'run_01' / 'model' / 'result.json'
SOURCE = HERE.parent / 'deployment' / 'm2_clean_cuda.py'
MODULE_PATH = HERE / 'analyze_b7_stage_intervals.py'
spec = importlib.util.spec_from_file_location('b7_interval', MODULE_PATH)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


def sha(path):
    h = hashlib.sha256(); h.update(Path(path).read_bytes()); return h.hexdigest()


class IntervalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw_before = sha(RESULT)

    def tearDown(self):
        self.assertEqual(sha(RESULT), self.raw_before, 'raw result was modified')
        self.tmp.cleanup()

    def test_4x4_coverage_and_unique_ids(self):
        data, rows = mod.analyze(RESULT)
        self.assertEqual(len(rows), 16)
        self.assertEqual(len({r['segment_id'] for r in rows}), 4)
        self.assertEqual({r['stage_index'] for r in rows}, {0, 1, 2, 3})
        self.assertEqual(len({(r['segment_id'], r['stage_index']) for r in rows}), 16)
        self.assertEqual([r['segment_id'] for r in rows][0], 'p1_A_lead10ms')

    def test_closure_and_no_negative_or_overlap(self):
        data, rows = mod.analyze(RESULT)
        for r in rows:
            self.assertGreater(r['stage_host_ms'], 0)
            self.assertEqual(r['closure_delta_ms'], 0.0)
            self.assertAlmostEqual(r['classified_sum_ms'] + r['unclassified_gap_ms'],
                                   r['stage_host_ms'], places=9)
            self.assertGreaterEqual(r['unclassified_gap_ms'], 0.0)
        # The two long B first stages are dominated by the first Event0 Host call.
        for r in rows:
            if r['segment_id'] in ('p2_B_lead4s', 'p3_B_lead4s') and r['stage_index'] == 0:
                self.assertGreater(r['event0_share_percent'], 99.0)
            if r['segment_id'] in ('p1_A_lead10ms', 'p4_A_lead10ms') and r['stage_index'] == 0:
                self.assertLess(r['event0_share_percent'], 10.0)

    def test_missing_timestamp_fails_not_zero(self):
        d = json.loads(RESULT.read_text())
        del d['segments'][0]['stage_observation']['stages'][0]['timestamps']['event0_after']
        with self.assertRaisesRegex(mod.AnalysisError, 'missing timestamp'):
            mod.analyze_obj(d)

    def test_negative_and_overlap_fail(self):
        d = json.loads(RESULT.read_text())
        st = d['segments'][0]['stage_observation']['stages'][0]
        st['timestamps']['event0_after'] = st['timestamps']['event0_before'] - 1
        with self.assertRaisesRegex(mod.AnalysisError, 'negative interval'):
            mod.analyze_obj(d)
        d = json.loads(RESULT.read_text())
        st = d['segments'][0]['stage_observation']['stages'][0]
        st['timestamps']['event1_before'] = st['timestamps']['event0_before']
        with self.assertRaisesRegex(mod.AnalysisError, 'overlapping intervals'):
            mod.analyze_obj(d)

    def test_event0_formula_on_temp_copy(self):
        d = json.loads(RESULT.read_text())
        st = d['segments'][0]['stage_observation']['stages'][0]
        shift = 1_000_000
        order = ['event0_after', 'event1_before', 'event1_after',
                 'restore_images_before', 'restore_images_after',
                 'restore_noise_before', 'restore_noise_after',
                 'capture_images_before', 'capture_images_after',
                 'capture_noise_before', 'capture_noise_after',
                 'event2_before', 'event2_after', 'event7_before', 'event7_after',
                 'event7_wait_before', 'event7_wait_after',
                 'confirmation_before', 'confirmation_after', 'stage_exit']
        for name in order:
            st['timestamps'][name] += shift
        temp_result = self.root / 'modified.json'
        temp_result.write_text(json.dumps(d))
        out = self.root / 'out'
        payload, manifest = mod.write_outputs(temp_result, out, SOURCE, MODULE_PATH)
        base = mod.analyze(RESULT)[1][0]
        r = payload['rows'][0]
        self.assertAlmostEqual(r['event0_record_ms'], base['event0_record_ms'] + 1.0, places=6)
        self.assertAlmostEqual(r['stage_host_ms'], base['stage_host_ms'] + 1.0, places=6)
        self.assertEqual(r['closure_delta_ms'], 0.0)
        self.assertTrue((out / 'B7_STAGE_INTERVALS.csv').is_file())
        self.assertTrue((out / 'B7_STAGE_INTERVALS.json').is_file())
        self.assertTrue((out / 'B7_STAGE_INTERVALS.md').is_file())
        self.assertTrue((out / 'B7_ANALYSIS_MANIFEST.json').is_file())
        self.assertEqual(manifest['input_sha256'], sha(temp_result))

    def test_outputs_manifest_and_event_gpu_separate(self):
        out = self.root / 'out'
        payload, manifest = mod.write_outputs(RESULT, out, SOURCE, MODULE_PATH)
        self.assertEqual(len(payload['rows']), 16)
        self.assertEqual(manifest['input_sha256'], self.raw_before)
        self.assertEqual(manifest['source_sha256'], sha(SOURCE))
        self.assertEqual(manifest['script_sha256'], sha(MODULE_PATH))
        self.assertTrue(all(r['event_gpu_ms'] > 0 for r in payload['rows']))
        # Event GPU is an Event envelope, not part of the Host decomposition.
        for r in payload['rows']:
            self.assertNotIn('event_gpu_ms', r['intervals'])
            self.assertEqual(r['closure_delta_ms'], 0.0)

    def test_unclassified_gap_is_not_a_named_interval(self):
        _, rows = mod.analyze(RESULT)
        for r in rows:
            self.assertNotIn('unclassified_gap', r['intervals'])
            self.assertGreaterEqual(r['unclassified_gap_ms'], 0.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
