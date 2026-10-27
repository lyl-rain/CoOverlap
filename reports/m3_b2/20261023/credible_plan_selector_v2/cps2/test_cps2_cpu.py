#!/usr/bin/env python3
"""Targeted CPU checks for credible_plan_selector_v2 (no GPU, no board)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'cps2'))
sys.path.insert(0, str(core_b9 := HERE.parent / 'expert_reserve_validation_b9_v1_r2' / 'deployment'))
import core  # noqa: E402
import plan_model  # noqa: E402
import m3_b9_plan  # noqa: E402

B9 = core.measured_cells(core.load(core.B9_RESULT))
B8 = core.measured_cells(core.load(core.B8_RESULT))


class TimeOrigins(unittest.TestCase):
    def test_manifest_identity(self):
        for period in (180.0, 140.0):
            m = m3_b9_plan.manifest(int(period * 1e6))
            for e in m['experts']:
                rel = e['id'] * period + 15.0
                self.assertAlmostEqual(e['release_ns'] / 1e6, rel, places=6)
                self.assertAlmostEqual(e['deadline_ns'] / 1e6, rel + period, places=6)
            for r in m['refreshes']:
                self.assertAlmostEqual(r['release_ns'] / 1e6, r['id'] * 2 * period, places=6)
                self.assertAlmostEqual(r['deadline_ns'] / 1e6,
                                       (r['id'] + 1) * 2 * period, places=6)

    def test_phase_moves_release_and_deadline_together(self):
        v = core.traj('two_9_9', core.scenario(B9[('two_9_9', 180.0)], 'typical'), 180.0)
        self.assertAlmostEqual(v['experts'][0]['release_ms'], 15.0, places=6)
        self.assertAlmostEqual(v['experts'][0]['deadline_ms'], 195.0, places=6)
        self.assertAlmostEqual(v['refreshes'][0]['release_ms'], 0.0, places=6)
        self.assertAlmostEqual(v['refreshes'][0]['deadline_ms'], 360.0, places=6)


class Margins(unittest.TestCase):
    def test_mc_equals_min_me_mu_on_these_traces(self):
        for plan in core.CANDIDATES:
            for src in (180.0, 140.0):
                for kind in ('typical', 'stress'):
                    for b in (160.0, 150.0):
                        m = core.traj(plan, core.scenario(B9[(plan, src)], kind), b)['margins']
                        self.assertAlmostEqual(m['MC'], min(m['ME'], m['MU']), places=6)

    def test_reserve_boundary(self):
        self.assertEqual(core.margin_state(10.0, 10.0), 'CONFIRMED_OK')
        self.assertEqual(core.margin_state(9.999, 10.0), 'CONFIRMED_SHORT')
        self.assertEqual(core.margin_state(None, 10.0), 'MISSING')

    def test_me_and_mu_fail_independently_at_150(self):
        two = core.traj('two_9_9', core.scenario(B9[('two_9_9', 180.0)], 'stress'), 150.0)
        three = core.traj('three_prefix_9_9', core.scenario(B9[('three_prefix_9_9', 180.0)], 'stress'), 150.0)
        self.assertLess(two['margins']['ME'], core.RE_MS)
        self.assertGreaterEqual(two['margins']['MU'], core.RU_MS)
        self.assertGreaterEqual(three['margins']['ME'], core.RE_MS)
        self.assertLess(three['margins']['MU'], core.RU_MS)


class Perturbation(unittest.TestCase):
    def test_single_operation_only(self):
        scen = core.scenario(B9[('two_9_9', 180.0)], 'typical')
        base = core.traj('two_9_9', scen, 160.0)
        pert = core.traj('two_9_9', scen, 160.0, extra_ms=lambda k: 3.5 if k == ('Expert', 0) else 0.0)
        self.assertAlmostEqual(pert['experts'][0]['completion_ms'] - base['experts'][0]['completion_ms'],
                               3.5, places=6)
        self.assertAlmostEqual(pert['experts'][0]['release_ms'], base['experts'][0]['release_ms'], places=6)
        self.assertAlmostEqual(pert['experts'][0]['deadline_ms'], base['experts'][0]['deadline_ms'], places=6)
        self.assertAlmostEqual(pert['experts'][1]['completion_ms'] - base['experts'][1]['completion_ms'],
                               3.5, places=6)

    def test_block_perturbation_hits_its_group_only(self):
        scen = core.scenario(B9[('three_prefix_9_9', 180.0)], 'typical')
        base = core.traj('three_prefix_9_9', scen, 160.0)
        pert = core.traj('three_prefix_9_9', scen, 160.0,
                         extra_ms=lambda k: 3.5 if k == ('block', 0, 1) else 0.0)
        self.assertAlmostEqual(pert['units']['R0/U0'] - base['units']['R0/U0'], 3.5, places=6)
        self.assertAlmostEqual(pert['units']['R0/U1'] - base['units']['R0/U1'], 3.5, places=6)

    def test_order_flip_is_scheduler_generated(self):
        scen = core.scenario(B9[('three_prefix_9_9', 140.0)], 'stress')
        base = core.traj('three_prefix_9_9', scen, 160.0)
        pert = core.traj('three_prefix_9_9', scen, 160.0,
                         extra_ms=lambda k: 45.0 if k == ('block', 0, 1) else 0.0)
        self.assertNotEqual(base['order'], pert['order'])
        self.assertEqual(len(base['order']), len(pert['order']))

    def test_g3_has_no_independent_decision_contribution(self):
        d = json.loads((HERE / 'outputs' / 'SELECTION.json').read_text())
        for b in ('160', '150'):
            self.assertEqual(d['schemes'][b]['S2'], d['schemes'][b]['S3'])


class Selection(unittest.TestCase):
    def test_160_selects_two_and_150_has_no_plan(self):
        d = json.loads((HERE / 'outputs' / 'SELECTION.json').read_text())
        self.assertEqual(d['budgets']['160']['selection']['status'], 'SELECTED')
        self.assertEqual(d['budgets']['160']['selection']['selected'], 'two_9_9')
        self.assertEqual(d['budgets']['150']['selection']['status'],
                         'NO_ACCEPTABLE_PLAN_UNDER_RULE')

    def test_missing_cost_is_insufficient_evidence(self):
        cands = {'two_9_9': dict(accepted=False, evidence_ok=False, missing=['cost:two@150']),
                 'three_prefix_9_9': dict(accepted=False, evidence_ok=True, missing=[])}
        sel = core.select(cands)
        self.assertEqual(sel['status'], 'INSUFFICIENT_EVIDENCE')

    def test_lifecycle_failure_never_selected(self):
        cands = {'two_9_9': dict(accepted=False, evidence_ok=True, missing=[]),
                 'three_prefix_9_9': dict(accepted=True, evidence_ok=True, missing=[])}
        self.assertEqual(core.select(cands)['selected'], 'three_prefix_9_9')


class Costs(unittest.TestCase):
    def test_b8_and_b9_are_separate(self):
        self.assertNotEqual(core.sha256, None)
        c = json.loads((HERE / 'outputs' / 'COSTS.json').read_text())
        self.assertEqual(c['primary'], 'B9')
        self.assertIn('HISTORICAL', c['mapping']['source_match']['b8'])
        self.assertEqual(c['mapping']['target']['status'], 'UNMEASURED')

    def test_no_pooling_in_cost_doc(self):
        c = json.loads((HERE / 'outputs' / 'COSTS.json').read_text())
        self.assertEqual(len(c['b9']['cells']), 4)
        self.assertTrue(all(k in c['b9']['cells'] for k in ('two_9_9@180', 'three_prefix_9_9@140')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
