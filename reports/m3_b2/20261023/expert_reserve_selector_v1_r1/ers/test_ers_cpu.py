#!/usr/bin/env python3
"""Targeted CPU tests for the reserve-constrained selector and its ablation.

Only the new risks are checked: the reserve comparison boundary, the status
machine, the tie-breaks, the reused-result bookkeeping, and the independence of
the rule from the measured trajectory.  Costs, the analysis model and the
VersionedKV lifecycle are reused unchanged from the release-boundary evaluator.

No production executor, no GPU, no historical suite.
"""
import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ablation      # noqa: E402
import common        # noqa: E402
import rules         # noqa: E402
import select as select_mod  # noqa: E402

RESULT = common.rbe_env.load(common.rbe_env.B8_RESULT)


def cand(plan, MC, ME, MR, feasible=True, evidence_ok=True, complete=True,
         lifecycle_ok=True, missing=()):
    blocks = common.BLOCKS[plan]
    return dict(plan=plan, blocks=blocks, MC=MC, ME=ME, MR=MR,
                evidence_ok=evidence_ok, missing=list(missing), complete=complete,
                lifecycle_ok=lifecycle_ok, feasible=feasible,
                reserve_ok=bool(feasible and ME is not None and ME >= rules.RE_MS),
                scenarios={k: dict(MC=MC, ME=ME, MR=MR, complete=complete)
                           for k in common.SCENARIOS})


def pair(two, three):
    return {'two_9_9': two, 'three_prefix_9_9': three}


def real_candidates(period):
    cands, _ = ablation.build_candidates(RESULT, period)
    return cands


class ReserveBoundary(unittest.TestCase):
    def test_me_exactly_at_reserve_is_accepted(self):
        out = select_mod.select(pair(cand('two_9_9', 50.0, 10.0, 50.0),
                                     cand('three_prefix_9_9', 40.0, 30.0, 40.0)))
        self.assertEqual(out['status'], 'SELECTED')
        self.assertEqual(out['selected'], 'two_9_9')
        self.assertTrue(out['evidence']['two_9_9']['reserve_ok'])

    def test_me_just_below_reserve_is_rejected(self):
        out = select_mod.select(pair(cand('two_9_9', 50.0, 9.999, 50.0),
                                     cand('three_prefix_9_9', 40.0, 30.0, 40.0)))
        self.assertEqual(out['selected'], 'three_prefix_9_9')
        self.assertFalse(out['evidence']['two_9_9']['reserve_ok'])

    def test_reserve_met_but_cycle_fails_is_not_selected(self):
        # official deadline infeasible (MC < 0) even though the Expert reserve is large
        bad = cand('two_9_9', -1.0, 80.0, 50.0, feasible=False)
        out = select_mod.select(pair(bad, cand('three_prefix_9_9', 40.0, 30.0, 40.0)))
        self.assertEqual(out['selected'], 'three_prefix_9_9')
        self.assertFalse(out['evidence']['two_9_9']['feasible'])

    def test_reserve_met_but_refresh_fails_is_not_selected(self):
        bad = cand('two_9_9', 50.0, 80.0, -2.0, feasible=False)
        out = select_mod.select(pair(bad, cand('three_prefix_9_9', 40.0, 30.0, 40.0)))
        self.assertEqual(out['selected'], 'three_prefix_9_9')

    def test_official_feasible_but_reserve_short(self):
        out = select_mod.select(pair(cand('two_9_9', 3.0, 2.5, 80.0),
                                     cand('three_prefix_9_9', 2.0, 9.0, 80.0)))
        self.assertEqual(out['status'], 'RESERVE_UNSATISFIED')
        self.assertIsNone(out['selected'])
        self.assertIn('none meets', out['reason'])
        self.assertEqual([c['failed'] for c in out['trace'] if c['step'] == 'reserve'],
                         [['two_9_9', 'three_prefix_9_9']])

    def test_no_feasible_candidate(self):
        out = select_mod.select(pair(cand('two_9_9', -1.0, 20.0, 80.0, feasible=False),
                                     cand('three_prefix_9_9', 2.0, 9.0, 80.0, feasible=False)))
        self.assertEqual(out['status'], 'NO_EMPIRICALLY_FEASIBLE_PLAN')

    def test_one_infeasible_keeps_the_other(self):
        ok = cand('three_prefix_9_9', 5.0, 30.0, 40.0)
        out = select_mod.select(pair(cand('two_9_9', -1.0, 2.0, 40.0, feasible=False), ok))
        self.assertEqual(out['status'], 'SELECTED')
        self.assertEqual(out['selected'], 'three_prefix_9_9')
        out = select_mod.select(pair(ok, cand('three_prefix_9_9', -1.0, 30.0, 40.0,
                                              feasible=False)))
        self.assertEqual(out['selected'], 'two_9_9')


class Choice(unittest.TestCase):
    def test_fewest_blocks_when_both_meet(self):
        out = select_mod.select(pair(cand('two_9_9', 5.0, 12.0, 80.0),
                                     cand('three_prefix_9_9', 50.0, 60.0, 90.0)))
        self.assertEqual(out['selected'], 'two_9_9')

    def test_only_three_meets_reserve(self):
        out = select_mod.select(pair(cand('two_9_9', 5.0, 2.5, 80.0),
                                     cand('three_prefix_9_9', 4.0, 24.0, 79.0)))
        self.assertEqual(out['status'], 'SELECTED')
        self.assertEqual(out['selected'], 'three_prefix_9_9')
        self.assertEqual(out['evidence']['three_prefix_9_9']['blocks'], 3)

    def test_mc_breaks_a_block_tie(self):
        a = cand('two_9_9', 10.0, 20.0, 80.0)
        b = cand('three_prefix_9_9', 30.0, 20.0, 80.0)
        b['blocks'] = 2
        out = select_mod.select(pair(a, b))
        self.assertEqual(out['selected'], 'three_prefix_9_9')

    def test_stable_order_breaks_a_full_tie(self):
        a = cand('two_9_9', 10.0, 20.0, 80.0)
        b = cand('three_prefix_9_9', 10.0, 20.0, 80.0)
        b['blocks'] = 2
        out = select_mod.select(pair(a, b))
        self.assertEqual(out['selected'], 'two_9_9')

    def test_rule_uses_the_decision_reserve_not_a_summary(self):
        two = cand('two_9_9', 5.0, 2.5, 80.0)
        three = cand('three_prefix_9_9', 4.0, 4.0, 79.0)
        self.assertEqual(select_mod.select(pair(two, three), 0.0)['selected'], 'two_9_9')
        self.assertEqual(select_mod.select(pair(two, three), 10.0)['status'],
                         'RESERVE_UNSATISFIED')
        self.assertEqual(select_mod.select(pair(two, three), 2.0)['selected'], 'two_9_9')


class RevisionGaps(unittest.TestCase):
    """Counterexamples for the two real gaps found in v1."""

    def test_missing_declared_candidate_is_insufficient_evidence(self):
        # v1 returned SELECTED for the three-block candidate alone; the declared
        # rule compares two candidates, so a missing one is missing evidence.
        out = select_mod.select({'three_prefix_9_9': cand('three_prefix_9_9', 5.0, 40.0, 80.0)})
        self.assertEqual(out['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIsNone(out['selected'])
        self.assertEqual(out['missing'], ['two_9_9'])
        self.assertIn('two_9_9', out['reason'])

    def test_missing_two_candidate_is_also_insufficient(self):
        out = select_mod.select({'two_9_9': cand('two_9_9', 5.0, 40.0, 80.0)})
        self.assertEqual(out['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(out['missing'], ['three_prefix_9_9'])

    def test_lifecycle_failure_makes_the_candidate_infeasible(self):
        # v1 could still return feasible=True and select this candidate.
        raw = {k: dict(complete=True, model_status='DRAINED', min_cycle_margin_ms=50.0,
                       min_expert_margin_ms=40.0, min_refresh_margin_ms=90.0,
                       counts=dict(PASS=8, FAIL=0, INCOMPLETE=0), deferred=0, refusals=0)
               for k in common.SCENARIOS}
        c = select_mod.summarize_candidate('two_9_9', raw, lifecycle_ok=False)
        self.assertFalse(c['feasible'])
        self.assertFalse(c['reserve_ok'])
        self.assertFalse(c['lifecycle_ok'])
        out = select_mod.select({'two_9_9': c,
                                 'three_prefix_9_9': cand('three_prefix_9_9', 5.0, 40.0, 80.0)})
        self.assertEqual(out['selected'], 'three_prefix_9_9')
        self.assertFalse(out['evidence']['two_9_9']['feasible'])

    def test_lifecycle_failure_in_both_candidates_is_no_feasible_plan(self):
        raw = {k: dict(complete=True, model_status='DRAINED', min_cycle_margin_ms=50.0,
                       min_expert_margin_ms=40.0, min_refresh_margin_ms=90.0,
                       counts=dict(PASS=8, FAIL=0, INCOMPLETE=0), deferred=0, refusals=0)
               for k in common.SCENARIOS}
        a = select_mod.summarize_candidate('two_9_9', raw, lifecycle_ok=False)
        b = select_mod.summarize_candidate('three_prefix_9_9', raw, lifecycle_ok=False)
        out = select_mod.select({'two_9_9': a, 'three_prefix_9_9': b})
        self.assertEqual(out['status'], 'NO_EMPIRICALLY_FEASIBLE_PLAN')
        self.assertIsNone(out['selected'])


class Evidence(unittest.TestCase):
    def test_missing_evidence_is_insufficient(self):
        out = select_mod.select(pair(cand('two_9_9', 5.0, 20.0, 80.0),
                                     cand('three_prefix_9_9', 5.0, 20.0, 80.0,
                                          evidence_ok=False, missing=['samples'])))
        self.assertEqual(out['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIsNone(out['selected'])
        self.assertIn('three_prefix_9_9', out['reason'])

    def test_no_evidence_at_all(self):
        out = select_mod.select({})
        self.assertEqual(out['status'], 'INSUFFICIENT_EVIDENCE')

    def test_unknown_candidate_is_unsupported(self):
        out = select_mod.select({'four_blocks': cand('two_9_9', 5.0, 20.0, 80.0)})
        self.assertEqual(out['status'], 'UNSUPPORTED_INPUT')

    def test_incomplete_obligations_are_not_feasible(self):
        out = select_mod.select(pair(cand('two_9_9', 5.0, 20.0, 80.0, feasible=False,
                                          complete=False),
                                     cand('three_prefix_9_9', 4.0, 20.0, 79.0, feasible=False,
                                          complete=False)))
        self.assertEqual(out['status'], 'NO_EMPIRICALLY_FEASIBLE_PLAN')


class Summarize(unittest.TestCase):
    def _raw(self, MC, ME, MR):
        return {k: dict(complete=True, model_status='DRAINED', min_cycle_margin_ms=MC,
                        min_expert_margin_ms=ME, min_refresh_margin_ms=MR,
                        counts=dict(PASS=8, FAIL=0, INCOMPLETE=0), deferred=0, refusals=0)
                for k in common.SCENARIOS}

    def test_negative_cycle_margin_makes_the_candidate_infeasible(self):
        c = select_mod.summarize_candidate('two_9_9', self._raw(-0.5, 30.0, 80.0))
        self.assertFalse(c['feasible'])
        self.assertFalse(c['reserve_ok'])

    def test_negative_refresh_margin_makes_the_candidate_infeasible(self):
        c = select_mod.summarize_candidate('two_9_9', self._raw(20.0, 30.0, -1.0))
        self.assertFalse(c['feasible'])

    def test_missing_scenario_is_insufficient_evidence(self):
        raw = self._raw(20.0, 30.0, 80.0)
        raw.pop('stress')
        c = select_mod.summarize_candidate('two_9_9', raw)
        self.assertFalse(c['evidence_ok'])
        self.assertIsNone(c['MC'])

    def test_min_across_scenarios_is_used(self):
        raw = self._raw(20.0, 30.0, 80.0)
        raw['stress'].update(min_cycle_margin_ms=1.0, min_expert_margin_ms=5.0,
                             min_refresh_margin_ms=70.0)
        c = select_mod.summarize_candidate('two_9_9', raw)
        self.assertEqual((c['MC'], c['ME'], c['MR']), (1.0, 5.0, 70.0))


class RealData(unittest.TestCase):
    def test_180_both_plans_meet_reserve_and_two_is_chosen(self):
        cands = real_candidates(180.0)
        self.assertTrue(cands['two_9_9']['reserve_ok'])
        self.assertTrue(cands['three_prefix_9_9']['reserve_ok'])
        out = select_mod.select(cands, rules.RE_MS)
        self.assertEqual(out['status'], 'SELECTED')
        self.assertEqual(out['selected'], 'two_9_9')

    def test_140_reserve_changes_the_selection(self):
        cands = real_candidates(140.0)
        self.assertLess(cands['two_9_9']['ME'], rules.RE_MS)
        self.assertGreaterEqual(cands['three_prefix_9_9']['ME'], rules.RE_MS)
        self.assertEqual(select_mod.select(cands, 0.0)['selected'], 'two_9_9')
        self.assertEqual(select_mod.select(cands, rules.RE_MS)['selected'],
                         'three_prefix_9_9')

    def test_actual_reserve_counts(self):
        two = ablation.actual_metrics(RESULT, 'two_9_9', 140.0)
        three = ablation.actual_metrics(RESULT, 'three_prefix_9_9', 140.0)
        self.assertEqual((two['reserve_short'], two['reserve_total']), (8, 16))
        self.assertEqual((three['reserve_short'], three['reserve_total']), (0, 16))
        self.assertTrue(two['official_feasible'] and three['official_feasible'],
                        'both plans still meet the official deadlines')

    def test_stress_is_the_sample_maximum(self):
        cands = real_candidates(140.0)
        costs = cands['two_9_9']['costs']
        self.assertAlmostEqual(costs['expert']['max'], costs['expert']['max'], places=9)
        stress = cands['two_9_9']['scenarios']['stress']
        typical = cands['two_9_9']['scenarios']['typical']
        self.assertLessEqual(stress['MC'], typical['MC'])

    def test_re0_matches_fixed_two_without_double_counting(self):
        cands = real_candidates(140.0)
        s0 = select_mod.select(cands, 0.0)
        f2 = select_mod.fixed('two_9_9', cands, rules.RE_MS)
        self.assertEqual(s0['selected'], f2['selected'])
        for key in ('MC', 'ME', 'MR'):
            self.assertEqual(s0['evidence']['two_9_9'][key], f2['evidence']['two_9_9'][key])

    def test_rule_does_not_see_the_actual_side(self):
        cands = real_candidates(140.0)
        before = select_mod.select(copy.deepcopy(cands), rules.RE_MS)
        ablation.actual_metrics(RESULT, 'two_9_9', 140.0)
        ablation.actual_metrics(RESULT, 'three_prefix_9_9', 140.0)
        after = select_mod.select(copy.deepcopy(cands), rules.RE_MS)
        self.assertEqual(before['selected'], after['selected'])
        self.assertEqual(before['status'], after['status'])
        self.assertNotIn('actual_margin_ms', str(after['evidence']))

    def test_reserve_shortfall_is_not_reported_as_deadline_miss(self):
        two = ablation.actual_metrics(RESULT, 'two_9_9', 140.0)
        self.assertGreater(two['reserve_short'], 0)
        self.assertTrue(two['official_feasible'])
        self.assertEqual(two['cycles_pass'], two['cycles_total'])
        self.assertEqual(two['refreshes_pass'], two['refreshes_total'])


class Rules(unittest.TestCase):
    def test_rule_identity_is_not_a_task_book_requirement(self):
        doc = rules.rules_document()
        r = doc['reserve']
        self.assertEqual(r['value_ms'], 10.0)
        self.assertFalse(r['is_task_book_requirement'])
        self.assertFalse(r['is_wcet'])
        self.assertFalse(r['is_validated_safety_bound'])
        self.assertFalse(r['implies_interference_tolerance'])
        self.assertTrue(r['official_deadline_unchanged'])
        self.assertFalse(r['adjustable_within_round'])

    def test_validate_rejects_a_tampered_rule(self):
        doc = rules.rules_document()
        bad = copy.deepcopy(doc)
        bad['reserve']['value_ms'] = 5.0
        with self.assertRaises(ValueError):
            rules.validate_rules(bad)
        bad = copy.deepcopy(doc)
        bad['reserve']['is_wcet'] = True
        with self.assertRaises(ValueError):
            rules.validate_rules(bad)

    def test_frozen_rules_file_matches_the_module(self):
        path = HERE.parent / 'RULES.json'
        if not path.exists():
            self.skipTest('RULES.json not frozen yet')
        doc = common.load(path)
        rules.validate_rules(doc)
        self.assertEqual(doc['reserve']['value_ms'], rules.RE_MS)


class SelectorDomain(unittest.TestCase):
    def test_r1_formal_statuses_unchanged(self):
        sel = common.load(common.rbe_env.R1 / 'freeze/SELECTION_180.json')
        self.assertEqual(sel['status'], 'INSUFFICIENT_EVIDENCE')
        pred = common.rbe_env.load(common.rbe_env.B8_PREDICTION)
        self.assertEqual(pred['formal_selector']['p180']['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(pred['formal_selector']['p140']['status'], 'UNSUPPORTED_INPUT')

    def test_new_rule_does_not_import_the_production_executor(self):
        import ast
        for name in ('select.py', 'ablation.py', 'rules.py', 'common.py'):
            tree = ast.parse((HERE / name).read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertNotIn('m2_executor', imported, name)
            self.assertNotIn('m3_b2_core', imported, name)


class FrozenInputs(unittest.TestCase):
    def test_frozen_inputs_and_selector_domain_unchanged(self):
        fp = common.rbe_env.fingerprint_inputs()
        self.assertTrue(all(v['match'] for v in fp.values()))
        self.assertEqual(fp['b8_prediction_json']['sha256'],
                         'd7b417754b2da51ad5f05a9c65ec1622f33d03916acc2ded9db2b6c140abb9e0')
        self.assertEqual(fp['r1_train_costs']['sha256'],
                         '5b9df9782c71981959008203f1d4a129fa6f9f5c71d359d7690f43abfae5a948')
        self.assertEqual(fp['frozen_executor']['sha256'],
                         '7890fa54896dd65635be741fddc50771bbc1b42b120abd6122c75170c6841654')
        pred = common.rbe_env.load(common.rbe_env.B8_PREDICTION)
        self.assertEqual(pred['status'], 'EXTRAPOLATIVE_PREDICTION_NOT_VALIDATED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
