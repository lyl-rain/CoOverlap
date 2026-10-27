#!/usr/bin/env python3
"""Targeted CPU tests for the empirical plan selector bindings.

Only new risks are checked. The model is the copied revised plan_model driving
the frozen VersionedKV; no production executor is imported or modified.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from evidence import extract_training, B4_RESULT
from evaluator import evaluate, PLAN_LAYOUT
from plan_model import Plan, simulate, TWO
from selection import select, scenario_for, CANDIDATES, TARGET
from model_env import EXECUTOR

COSTS = json.loads((HERE.parent / 'freeze' / 'TRAIN_COSTS.json').read_text())
RULES = json.loads((HERE.parent / 'freeze' / 'RULES.json').read_text())


class SelectorTests(unittest.TestCase):
    def test_training_validation_are_disjoint(self):
        data = json.loads(B4_RESULT.read_text())
        train, serial = extract_training(data)
        for plan, block in train.items():
            self.assertTrue(all(r['pass_'] == 1 for r in block['rows']))
            self.assertEqual(len(block['rows']), 8 + 4 * (2 if plan == 'two_9_9' else 3) + 4)
        # Validation is pass 2 only and is not used by extract_training.
        self.assertFalse(any(r['pass_'] == 2 for p in train for r in train[p]['rows']))
        self.assertEqual(data['segments'][4]['pass_'], 2)

    def test_missing_cost_is_insufficient_not_zero(self):
        bad = copy.deepcopy(COSTS)
        bad['candidates'].pop('three_prefix_9_9')
        s = select(bad, rules=RULES)
        self.assertEqual(s['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIn('three_prefix_9_9', s['reason'])

    def test_180_has_no_three_plan_evidence(self):
        s = select(COSTS, target=dict(period_ms=180.0, phase_ms=15.0, cycles=8), rules=RULES)
        self.assertEqual(s['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertTrue(s.get('no_evidence_for_three'))

    def test_complete_but_infeasible_is_not_feasible(self):
        bad = copy.deepcopy(COSTS)
        for plan, c in bad['candidates'].items():
            for b in c['blocks'].values(): b['median'] *= 3.0; b['max'] *= 3.0
            c['expert']['median'] *= 3.0; c['expert']['max'] *= 3.0
            c['stage']['first']['median'] *= 3.0; c['stage']['first']['max'] *= 3.0
            c['stage']['later']['median'] *= 3.0; c['stage']['later']['max'] *= 3.0
        s = select(bad, rules=RULES)
        self.assertEqual(s['status'], 'NO_EMPIRICALLY_FEASIBLE_PLAN')

    def test_unsupported_target_is_explicit(self):
        s = select(COSTS, target=dict(period_ms=200.0, phase_ms=15.0, cycles=8), rules=RULES)
        self.assertEqual(s['status'], 'UNSUPPORTED_INPUT')

    def test_fixed_releases_are_not_reset_by_startup(self):
        def run(stage_first):
            sc = scenario_for(COSTS, 'two_9_9', 'typical')
            sc['stage']['first'] = {'n': 1, 'median': stage_first, 'max': stage_first}
            return evaluate('two_9_9', sc, cycles=8, period=240.0, phase=15.0,
                            gap_ms=RULES['model_constants']['gap_ms'],
                            publish_cost_ms=RULES['model_constants']['publish_cost_ms'])
        a = run(0.6); b = run(50.0)
        self.assertEqual([x['release_ms'] for x in a['experts']],
                         [x['release_ms'] for x in b['experts']])
        self.assertEqual([x['release_ms'] for x in a['refreshes']],
                         [x['release_ms'] for x in b['refreshes']])
        self.assertTrue(all(x['dispatch_ms'] is None or x['dispatch_ms'] >= x['release_ms']
                            for x in a['experts'] + b['experts']))
        self.assertGreater(b['cycles'][0]['predicted_completion_ms'],
                           a['cycles'][0]['predicted_completion_ms'] + 40)

    def test_complete_obligations_and_version_binding(self):
        r = evaluate('two_9_9', scenario_for(COSTS, 'two_9_9', 'typical'),
                     cycles=8, period=240.0, phase=15.0,
                     gap_ms=RULES['model_constants']['gap_ms'],
                     publish_cost_ms=RULES['model_constants']['publish_cost_ms'])
        self.assertEqual(r['status'], 'DRAINED')
        self.assertEqual(len(r['experts']), 8)
        self.assertEqual(len(r['blocks']), 8)
        self.assertEqual(len(r['cycles']), 8)
        self.assertEqual(len(r['refreshes']), 4)
        self.assertTrue(all(x['status'] == 'COMPLETE' for x in r['experts']))
        for j in range(0, 8, 2):
            self.assertEqual(r['experts'][j]['version'], r['experts'][j+1]['version'])
        self.assertEqual([x['version'] for x in r['experts']], [0,0,1,1,2,2,3,3])

    def test_startup_is_in_timeline_not_subtracted(self):
        sc = scenario_for(COSTS, 'two_9_9', 'typical')
        base = evaluate('two_9_9', sc, cycles=8, period=240.0, phase=15.0,
                        gap_ms=RULES['model_constants']['gap_ms'],
                        publish_cost_ms=RULES['model_constants']['publish_cost_ms'])
        sc2 = copy.deepcopy(sc); sc2['stage']['first'] = {'n': 1, 'median': 50.0, 'max': 50.0}
        slow = evaluate('two_9_9', sc2, cycles=8, period=240.0, phase=15.0,
                        gap_ms=RULES['model_constants']['gap_ms'],
                        publish_cost_ms=RULES['model_constants']['publish_cost_ms'])
        self.assertGreater(slow['cycles'][0]['predicted_completion_ms'],
                           base['cycles'][0]['predicted_completion_ms'] + 40)
        # No second subtraction: the first refresh moves by approximately the
        # injected startup delta, not by twice it.
        self.assertGreater(slow['refreshes'][0]['predicted_completion_ms'],
                           base['refreshes'][0]['predicted_completion_ms'] + 40)
        self.assertLess(slow['refreshes'][0]['predicted_completion_ms'],
                        base['refreshes'][0]['predicted_completion_ms'] + 60)

    def test_expert_early_can_still_worsen_cycle(self):
        two = evaluate('two_9_9', scenario_for(COSTS, 'two_9_9', 'typical'),
                       cycles=8, period=240.0, phase=15.0,
                       gap_ms=RULES['model_constants']['gap_ms'],
                       publish_cost_ms=RULES['model_constants']['publish_cost_ms'])
        three = evaluate('three_prefix_9_9', scenario_for(COSTS, 'three_prefix_9_9', 'typical'),
                         cycles=8, period=240.0, phase=15.0,
                         gap_ms=RULES['model_constants']['gap_ms'],
                         publish_cost_ms=RULES['model_constants']['publish_cost_ms'])
        self.assertGreater(three['min_expert_margin_ms'], two['min_expert_margin_ms'])
        self.assertLess(three['min_cycle_margin_ms'], two['min_cycle_margin_ms'])
        self.assertLess(three['min_refresh_margin_ms'], two['min_refresh_margin_ms'])

    def test_missing_completion_is_incomplete_not_pass(self):
        # Directly use the copied model's analysis-only hold_expert knob.
        plan = Plan('two_9_9', (79.423, 44.583), PLAN_LAYOUT['two_9_9']['blocks'],
                    PLAN_LAYOUT['two_9_9']['groups'], PLAN_LAYOUT['two_9_9']['valid_layers'],
                    PLAN_LAYOUT['two_9_9']['kinds'])
        r = simulate(plan, 'b2_boundary', cycles=8, period=240.0, phase=15.0,
                     expert=75.0, stage_first=0.56, stage_later=0.04,
                     gap=0.041, publish_cost=0.012, hold_expert=1)
        self.assertTrue(any(c['status'] == 'INCOMPLETE' for c in r.cycles))

    def test_selection_is_nondominated_not_weighted(self):
        s = select(COSTS, rules=RULES)
        self.assertEqual(s['status'], 'EMPIRICALLY_FEASIBLE')
        self.assertEqual(set(s['feasible']), set(CANDIDATES))
        self.assertEqual(set(s['nondominated']), set(CANDIDATES))
        self.assertGreater(s['margins']['three_prefix_9_9']['min_expert_margin_ms'],
                           s['margins']['two_9_9']['min_expert_margin_ms'])
        self.assertLess(s['margins']['three_prefix_9_9']['min_cycle_margin_ms'],
                        s['margins']['two_9_9']['min_cycle_margin_ms'])
        self.assertIn('no weighted score', s['reason'])

    def test_max_is_analytical_not_formal_upper_bound(self):
        sc = scenario_for(COSTS, 'two_9_9', 'stress')
        for label, v in sc['blocks'].items():
            self.assertEqual(v['max'], max(v['max'], v['median']))
        self.assertIn('not a formal upper bound', RULES['scenarios'][1])
        self.assertNotIn('WCET', RULES['scenarios'][0])

    def test_executor_is_frozen_analysis_import(self):
        self.assertEqual(EXECUTOR.name, 'm2_executor.py')
        self.assertTrue(EXECUTOR.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
