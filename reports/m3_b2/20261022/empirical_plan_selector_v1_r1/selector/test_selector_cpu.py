#!/usr/bin/env python3
"""Targeted CPU tests for the empirical plan selector bindings.

Only new risks are checked. The model is the copied revised plan_model driving
the frozen VersionedKV; no production executor is imported or modified.  Fault
injection is done only on temporary copies.
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from evidence import extract_training, B4_RESULT, B4_CANDIDATE_CELLS, canonical_sha, sha
from evaluator import evaluate, PLAN_LAYOUT, refresh_metrics, summarize_refresh
from plan_model import Plan, simulate, TWO
from selection import select, scenario_for, CANDIDATES, TARGET
from model_env import EXECUTOR
from validate import (actual_jobs, predicted_jobs, verify_freeze, FreezeMismatch,
                      validate as validate_fn, write_validation)

FREEZE_DIR = HERE.parent / 'freeze'
COSTS = json.loads((FREEZE_DIR / 'TRAIN_COSTS.json').read_text())
RULES = json.loads((FREEZE_DIR / 'RULES.json').read_text())
FREEZE_PATH = FREEZE_DIR / 'FREEZE.json'


def scaled(costs, factors):
    bad = copy.deepcopy(costs)
    for plan, factor in factors.items():
        c = bad['candidates'][plan]
        for b in c['blocks'].values():
            b['median'] *= factor; b['max'] *= factor
        c['expert']['median'] *= factor; c['expert']['max'] *= factor
        c['stage']['first']['median'] *= factor; c['stage']['first']['max'] *= factor
        c['stage']['later']['median'] *= factor; c['stage']['later']['max'] *= factor
    return bad


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
        # The two pass-1 candidates must describe one shared condition; only
        # plan-specific layout/obligation/retention may differ.
        self.assertEqual(train['two_9_9']['condition'], train['three_prefix_9_9']['condition'])
        self.assertNotEqual(train['two_9_9']['candidate_condition'],
                            train['three_prefix_9_9']['candidate_condition'])

    def test_condition_has_required_fields_and_unknowns_are_explicit(self):
        cond = COSTS['condition']
        self.assertEqual(cond['fingerprint'],
                         canonical_sha({k: v for k, v in cond.items() if k != 'fingerprint'}))
        for section in ('configuration', 'input', 'version_consumption',
                        'retention', 'observation', 'hardware'):
            body = cond[section]
            self.assertEqual(body['fingerprint'],
                             canonical_sha({k: v for k, v in body.items() if k != 'fingerprint'}))
        self.assertIsInstance(cond['lead']['lead_ms'], (int, float))
        self.assertEqual(cond['pressure']['mode'], 'quiet')
        self.assertEqual(cond['pressure']['worker_processes'], 'UNKNOWN')
        self.assertEqual(cond['hardware']['device'], 'UNKNOWN')
        self.assertIn('clock_limits', cond['hardware'])
        for plan in CANDIDATES:
            c = COSTS['candidates'][plan]['condition']
            self.assertEqual(c['plan'], plan)
            self.assertEqual(c['fingerprint'],
                             canonical_sha({k: v for k, v in c.items() if k != 'fingerprint'}))

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
        self.assertIn('period_ms', s['missing_or_mismatched'])

    def test_complete_but_infeasible_is_not_feasible(self):
        s = select(scaled(COSTS, {p: 3.0 for p in CANDIDATES}), rules=RULES)
        self.assertEqual(s['status'], 'NO_EMPIRICALLY_FEASIBLE_PLAN')
        self.assertTrue(s['complete_evidence'])
        self.assertFalse(any(s['feasible'].values()))

    def test_one_infeasible_one_feasible_keeps_feasible(self):
        s = select(scaled(COSTS, {'three_prefix_9_9': 3.0}), rules=RULES)
        self.assertEqual(s['status'], 'EMPIRICALLY_FEASIBLE')
        self.assertNotEqual(s['status'], 'NO_EMPIRICALLY_FEASIBLE_PLAN')
        self.assertTrue(s['feasible']['two_9_9'])
        self.assertFalse(s['feasible']['three_prefix_9_9'])
        self.assertEqual(s['feasible_plans'], ['two_9_9'])
        self.assertEqual(s['nondominated'], ['two_9_9'])
        self.assertFalse(s['all_candidates_feasible'])
        self.assertEqual(s['candidate_status']['three_prefix_9_9'], 'INFEASIBLE')

    def test_unsupported_target_is_explicit(self):
        s = select(COSTS, target=dict(period_ms=200.0, phase_ms=15.0, cycles=8), rules=RULES)
        self.assertEqual(s['status'], 'UNSUPPORTED_INPUT')

    def test_unrecognised_target_parameter_is_not_ignored(self):
        s = select(COSTS, target=dict(TARGET, foo=1), rules=RULES)
        self.assertEqual(s['status'], 'UNSUPPORTED_INPUT')
        self.assertIn('foo', s['unrecognized'])

    def test_fixed_pressure_target_is_insufficient(self):
        s = select(COSTS, target=dict(TARGET, pressure='fixed_cpu_mem'), rules=RULES)
        self.assertEqual(s['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIn('pressure', s['missing_or_mismatched'])

    def test_lead_condition_mismatch_is_rejected(self):
        bad = copy.deepcopy(COSTS)
        bad['condition']['lead']['lead_ms'] = 4000.0
        s = select(bad, rules=RULES)
        self.assertEqual(s['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIn('lead_ms', s['missing_or_mismatched'])

    def test_configuration_condition_mismatch_is_rejected(self):
        bad = copy.deepcopy(COSTS)
        bad['condition']['configuration']['numeric']['work']['steps'] = 20
        s = select(bad, rules=RULES)
        self.assertEqual(s['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertTrue(any('configuration' in f for f in s['missing_or_mismatched']))

    def test_incompatible_frozen_rules_target_is_rejected(self):
        bad = copy.deepcopy(RULES)
        bad['target']['lead_ms'] = 4000.0
        s = select(COSTS, rules=bad)
        self.assertEqual(s['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIn('rules.lead_ms', s['missing_or_mismatched'])

    def test_protocol_condition_mismatch_is_rejected(self):
        bad = copy.deepcopy(COSTS)
        bad['condition']['protocol'] = 'other_protocol'
        s = select(bad, rules=RULES)
        self.assertEqual(s['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIn('protocol', s['missing_or_mismatched'])

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
        self.assertGreater(slow['refreshes'][0]['completion_offset_ms'],
                           base['refreshes'][0]['completion_offset_ms'] + 40)
        self.assertLess(slow['refreshes'][0]['completion_offset_ms'],
                        base['refreshes'][0]['completion_offset_ms'] + 60)

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

    def test_missing_completion_is_incomplete_not_zero(self):
        # Directly use the copied model's analysis-only hold_expert knob.
        plan = Plan('two_9_9', (79.423, 44.583), PLAN_LAYOUT['two_9_9']['blocks'],
                    PLAN_LAYOUT['two_9_9']['groups'], PLAN_LAYOUT['two_9_9']['valid_layers'],
                    PLAN_LAYOUT['two_9_9']['kinds'])
        r = simulate(plan, 'b2_boundary', cycles=8, period=240.0, phase=15.0,
                     expert=75.0, stage_first=0.56, stage_later=0.04,
                     gap=0.041, publish_cost=0.012, hold_expert=1)
        incomplete = [c for c in r.cycles if c['status'] == 'INCOMPLETE']
        self.assertTrue(incomplete)
        for c in incomplete:
            self.assertIsNone(c['response_ms'])
            self.assertIsNone(c['expert_response_ms'])
            self.assertIsNone(c['vlm_response_ms'])
            self.assertNotEqual(c['response_ms'], 0.0)
        self.assertGreaterEqual(r.counts()['INCOMPLETE'], 1)

    def test_refresh_response_uses_release_origin(self):
        r = evaluate('two_9_9', scenario_for(COSTS, 'two_9_9', 'typical'),
                     cycles=8, period=240.0, phase=15.0,
                     gap_ms=RULES['model_constants']['gap_ms'],
                     publish_cost_ms=RULES['model_constants']['publish_cost_ms'])
        responses = [x['refresh_response_ms'] for x in r['refreshes']]
        offsets = [x['completion_offset_ms'] for x in r['refreshes']]
        self.assertEqual(r['max_refresh_response_ms'], max(responses))
        self.assertEqual(r['max_refresh_completion_offset_ms'], max(offsets))
        self.assertGreater(max(offsets), max(responses))
        for x in r['refreshes']:
            self.assertAlmostEqual(x['refresh_response_ms'], x['ready_ms'], places=6)
            self.assertAlmostEqual(x['completion_offset_ms'],
                                   x['release_ms'] + x['ready_ms'], places=6)
            self.assertAlmostEqual(x['refresh_margin_ms'],
                                   x['release_ms'] + x['deadline_ms'] - x['completion_offset_ms'],
                                   places=6)

    def test_same_response_different_release_does_not_inflate_max(self):
        # A two-refresh counterexample: identical 200 ms responses at release 0
        # and 480 ms.  The old max-of-completion-offset metric would report 680.
        rows = [dict(id=0, ready_ms=200.0, deadline_ms=480.0, status='PASS'),
                dict(id=1, ready_ms=200.0, deadline_ms=480.0, status='PASS')]
        detailed = refresh_metrics(rows, 240.0)
        self.assertEqual([x['refresh_response_ms'] for x in detailed], [200.0, 200.0])
        self.assertEqual([x['completion_offset_ms'] for x in detailed], [200.0, 680.0])
        summary = summarize_refresh(rows, 240.0)
        self.assertEqual(summary['max_refresh_response_ms'], 200.0)
        self.assertEqual(summary['max_refresh_completion_offset_ms'], 680.0)

    def test_expert_completion_and_deadline_status_are_separate(self):
        data = json.loads(B4_RESULT.read_text())
        seg = copy.deepcopy(next(s for s in data['segments']
                                 if s['segment_id'] == 'p2_B_two_b2_boundary'))
        t0 = seg['t0_ns']
        # Expert 0 completes after its 255 ms deadline but still has a completion.
        seg['experts']['0'] = [t0 + 300_000_000, t0 + 301_000_000]
        actual = actual_jobs(seg)
        e0 = actual[('Expert', 'E0')]
        self.assertEqual(e0['status'], 'COMPLETE')
        self.assertLess(e0['margin_ms'], 0)
        # A predicted Expert can likewise be COMPLETE while its deadline margin
        # is checked separately by the validator summary.
        pred = evaluate('two_9_9', scenario_for(COSTS, 'two_9_9', 'typical'),
                        cycles=8, period=240.0, phase=15.0,
                        gap_ms=RULES['model_constants']['gap_ms'],
                        publish_cost_ms=RULES['model_constants']['publish_cost_ms'])
        pj = predicted_jobs(pred)
        self.assertEqual(pj[('Expert', 'E0')]['status'], 'COMPLETE')
        self.assertIsNotNone(pj[('Expert', 'E0')]['margin_ms'])

    def test_selection_is_nondominated_not_weighted(self):
        s = select(COSTS, rules=RULES)
        self.assertEqual(s['status'], 'EMPIRICALLY_FEASIBLE')
        self.assertEqual(set(s['feasible']), set(CANDIDATES))
        self.assertEqual(set(s['nondominated']), set(CANDIDATES))
        self.assertTrue(s['all_candidates_feasible'])
        self.assertGreater(s['margins']['three_prefix_9_9']['min_expert_margin_ms'],
                           s['margins']['two_9_9']['min_expert_margin_ms'])
        self.assertLess(s['margins']['three_prefix_9_9']['min_cycle_margin_ms'],
                        s['margins']['two_9_9']['min_cycle_margin_ms'])
        self.assertGreater(s['margins']['two_9_9']['max_refresh_completion_offset_ms'],
                           s['margins']['two_9_9']['max_refresh_response_ms'])
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

    def test_freeze_manifest_has_no_self_hash(self):
        f = json.loads(FREEZE_PATH.read_text())
        self.assertEqual(f['manifest_self_hash'], 'not included by design')
        self.assertNotIn('self_sha256', f)
        self.assertNotIn('manifest_sha256', f)
        self.assertEqual(set(f['modules']),
                         {'evidence','evaluator','selection','plan_model','model_env','validate','freeze'})

    def _temp_freeze(self, td, mutate):
        f = json.loads(FREEZE_PATH.read_text())
        mutate(f, td)
        p = td/'FREEZE.json'
        p.write_text(json.dumps(f, indent=2, sort_keys=True)+'\n')
        return p

    def test_freeze_rejects_modified_costs(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            bad = td/'TRAIN_COSTS.json'
            bad.write_text(json.dumps(dict(COSTS, tampered=True), indent=2)+'\n')
            def mutate(f, td):
                f['costs']['path'] = str(bad)
            with self.assertRaises(FreezeMismatch):
                verify_freeze(self._temp_freeze(td, mutate))

    def test_freeze_rejects_modified_rules(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            bad = td/'RULES.json'
            bad.write_text(json.dumps(dict(RULES, tampered=True), indent=2)+'\n')
            def mutate(f, td):
                f['rules']['path'] = str(bad)
            with self.assertRaises(FreezeMismatch):
                verify_freeze(self._temp_freeze(td, mutate))

    def test_freeze_rejects_modified_source_module(self):
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            bad = td/'evaluator.py'
            bad.write_text((HERE/'evaluator.py').read_text() + '\n# injected fault\n')
            def mutate(f, td):
                f['modules']['evaluator']['path'] = str(bad)
            with self.assertRaises(FreezeMismatch):
                verify_freeze(self._temp_freeze(td, mutate))

    def test_validate_rejects_before_output_and_preserves_freeze(self):
        before = sha(FREEZE_PATH)
        with tempfile.TemporaryDirectory() as raw:
            td = Path(raw)
            bad = td/'TRAIN_COSTS.json'
            bad.write_text(json.dumps(dict(COSTS, tampered=True), indent=2)+'\n')
            def mutate(f, td):
                f['costs']['path'] = str(bad)
            fp = self._temp_freeze(td, mutate)
            out = td/'out'
            with self.assertRaises(FreezeMismatch):
                write_validation(bad, FREEZE_DIR/'RULES.json', out, fp)
            self.assertFalse(out.exists())
        self.assertEqual(sha(FREEZE_PATH), before)

    def test_validate_separates_completion_and_deadline(self):
        v = validate_fn(FREEZE_DIR/'TRAIN_COSTS.json', FREEZE_DIR/'RULES.json', FREEZE_PATH)
        self.assertEqual(v['identity']['kind'], 'retrospective_check')
        self.assertFalse(v['identity']['prospective'])
        self.assertFalse(v['identity']['previously_unseen'])
        for key, s in v['summaries'].items():
            expected_completion = 16 if s['plan'] == 'two_9_9' else 20
            self.assertEqual(s['completion_jobs'], expected_completion)
            self.assertEqual(s['completion_match'], expected_completion)
            self.assertEqual(s['deadline_jobs'], 12)
            self.assertEqual(s['deadline_match'], 12)
            self.assertEqual(s['status_match'], s['completion_match'] + s['deadline_match'])
            self.assertEqual(s['false_feasible'], 0)
            self.assertEqual(s['false_infeasible'], 0)
            self.assertEqual(s['expert_deadline_status_match'], s['expert_deadline_jobs'])
            self.assertEqual(s['actual_cycle_counts']['PASS'], 8)
            self.assertEqual(s['actual_refresh_counts']['PASS'], 4)
        # The full validation writes a receipt, not a rewritten freeze manifest.
        before = sha(FREEZE_PATH)
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)/'out'
            write_validation(FREEZE_DIR/'TRAIN_COSTS.json', FREEZE_DIR/'RULES.json', out, FREEZE_PATH)
            self.assertTrue((out/'VALIDATION.json').exists())
            self.assertTrue((out/'VALIDATION_JOBS.csv').exists())
            self.assertTrue((out/'VALIDATION.md').exists())
        self.assertEqual(sha(FREEZE_PATH), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
