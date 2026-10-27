#!/usr/bin/env python3
"""Targeted CPU tests for the Expert-only reserve correction (no GPU, no board)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reserve_correction as rc  # noqa: E402

BASE = HERE.parent
ORIGINAL = BASE / 'analysis' / 'EVALUATION.json'
RESULT = BASE / 'board_small' / 'model' / 'result.json'
CORRECTED = HERE / 'EVALUATION_CORRECTED.json'


def job(job_type, margin_pred, margin_act, job_id='E0'):
    return dict(job_type=job_type, job_id=job_id, predicted_margin_ms=margin_pred,
                actual_margin_ms=margin_act)


def comparison(jobs):
    return dict(per_segment=[dict(segment_id='s1', scenario='typical', jobs=jobs)])


class ExpertOnly(unittest.TestCase):
    def test_expert_satisfied_predicted_but_short_actual(self):
        out = rc.expert_reserve(comparison([job('Expert', 11.0, 9.0)]))
        self.assertEqual(len(out['predicted_pass_actual_short']), 1)
        self.assertEqual(out['predicted_pass_actual_short'][0]['job_id'], 'E0')
        self.assertEqual(out['short'], 1)
        self.assertEqual(out['satisfied'], 0)

    def test_refresh_and_cycle_never_enter_the_expert_list(self):
        out = rc.expert_reserve(comparison([job('Refresh', 11.0, 9.0),
                                            job('Cycle', 11.0, 9.0),
                                            job('ContextBlock', 11.0, 9.0)]))
        self.assertEqual(out['predicted_pass_actual_short'], [])
        self.assertEqual(out['total'], 0)
        self.assertEqual(out['short'], 0)

    def test_missing_actual_margin_is_unknown(self):
        out = rc.expert_reserve(comparison([job('Expert', 11.0, None)]))
        self.assertEqual(out['predicted_pass_actual_short'], [])
        self.assertEqual(out['unknown'], 1)
        self.assertEqual(out['short'], 0)
        self.assertEqual(out['satisfied'], 0)

    def test_boundary_is_not_short(self):
        out = rc.expert_reserve(comparison([job('Expert', 10.0, 10.0)]))
        self.assertEqual(out['predicted_pass_actual_short'], [])
        self.assertEqual(out['satisfied'], 1)

    def test_real_batch_rebuild(self):
        doc, block = rc.rebuild(ORIGINAL, RESULT, CORRECTED)
        self.assertEqual(block['predicted_pass_actual_short'], [])
        self.assertEqual((block['short'], block['satisfied'], block['unknown'], block['total']),
                         (8, 56, 0, 64))
        self.assertEqual(block['denominator']['expert_jobs'], 64)
        self.assertEqual(block['denominator']['segment_scenario_comparisons'], 128)
        self.assertEqual(block['inconsistent_actual_margins'], [])
        check = rc.verify_unchanged(ORIGINAL, CORRECTED)
        self.assertTrue(check['other_fields_identical'])
        self.assertTrue(check['counts_equal'])

    def test_original_files_untouched(self):
        before = {p: rc.sha256(p) for p in (ORIGINAL, RESULT)}
        rc.rebuild(ORIGINAL, RESULT, CORRECTED)
        self.assertEqual(before, {p: rc.sha256(p) for p in (ORIGINAL, RESULT)})


if __name__ == '__main__':
    unittest.main(verbosity=2)
