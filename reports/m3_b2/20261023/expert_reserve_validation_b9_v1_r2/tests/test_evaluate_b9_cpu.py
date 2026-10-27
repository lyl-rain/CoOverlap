#!/usr/bin/env python3
"""CPU counterexamples for the B9-r2 evaluation chain (no GPU, no hardware).

Fixtures are synthetic, entry-shaped (eight pre-created records, NOT_STARTED when
unexecuted) and marked ``fixture: true``.  The B8 case uses the real recorded B8
result only to validate the official statistics chain.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
B9 = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(B9 / 'analysis'))
sys.path.insert(0, str(B9 / 'prediction'))

import fixture_b9 as fx          # noqa: E402
import evaluate_b9 as ev         # noqa: E402
import prediction_model as pm    # noqa: E402

CONFIG_PATH = B9 / 'deployment' / 'CONFIG.json'
RULES = B9.parent / 'expert_reserve_selector_v1_r1' / 'RULES.json'
COSTS = B9.parent / 'expert_reserve_selector_v1_r1' / 'COSTS.json'
PRED = B9 / 'prediction' / 'PREDICTION.json'
SEL = B9 / 'prediction' / 'SELECTION_FREEZE.json'
B8 = (B9.parents[1] / '20261022' / 'split_budget_challenge_b8_v1' / 'gpu_run_01' /
      'board' / 'run_01' / 'model' / 'result.json')


def load(p):
    return json.loads(Path(p).read_text())


def config_copy(tmp):
    cfg = load(CONFIG_PATH)
    cfg['prediction']['sha256'] = fx.sha(PRED)
    cfg['selection']['sha256'] = fx.sha(SEL)
    cfg['selection']['rule_sha256'] = fx.sha(RULES)
    cfg['selection']['costs_sha256'] = fx.sha(COSTS)
    cfg['analysis_modules'] = {
        'evaluate_b9.py': fx.sha(B9 / 'analysis' / 'evaluate_b9.py'),
        'prediction_model.py': fx.sha(B9 / 'prediction' / 'prediction_model.py')}
    path = Path(tmp) / 'CONFIG.json'
    path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + '\n')
    return cfg, path


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg, cls.cfg_path = config_copy(cls.tmp.name)
        cls.result = fx.build(cls.cfg, cls.cfg_path, PRED, SEL)
        cls.result_path = Path(cls.tmp.name) / 'result.json'
        fx.write(cls.result_path, cls.result)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def summary(self, result=None, config=None):
        return ev.official_summary(result or self.result, config or self.cfg)

    def run_cli(self, result, name):
        path = Path(self.tmp.name) / (name + '.json')
        fx.write(path, result)
        out = Path(self.tmp.name) / (name + '_out')
        code = ev.main(['--result', str(path), '--out', str(out),
                        '--config', str(self.cfg_path), '--rules', str(RULES),
                        '--costs', str(COSTS), '--prediction', str(PRED),
                        '--selection', str(SEL)])
        return code, load(out / 'EVALUATION.json')


class B8FixtureChain(Base):
    def test_b8_official_counts(self):
        s = self.summary(load(B8))
        self.assertEqual(s['declared'], dict(Expert=64, Cycle=64, Refresh=32))
        self.assertEqual(s['totals']['Expert']['PASS'], 64)
        self.assertEqual(s['totals']['Cycle']['PASS'], 64)
        self.assertEqual(s['totals']['Refresh']['PASS'], 32)
        self.assertNotIn('fixture', str(s))


class MissingRecords(Base):
    def test_missing_expert_refresh_and_unit(self):
        result = fx.build(self.cfg, self.cfg_path, PRED, SEL,
                          damage={0: dict(drop_expert=0, drop_refresh=0,
                                          drop_unit='(1, 0)')})
        s = self.summary(result)
        self.assertEqual(s['declared'], dict(Expert=64, Cycle=64, Refresh=32))
        row = s['segments'][0]
        self.assertEqual(row['status'], 'OK')
        self.assertEqual(s['totals']['Expert']['INCOMPLETE'], 1)
        self.assertEqual(s['totals']['Refresh']['INCOMPLETE'], 1)
        self.assertEqual(s['totals']['Cycle']['INCOMPLETE'], 2)
        self.assertIsNone([e for e in row['experts']
                           if e['completion_status'] == 'INCOMPLETE'][0]['margin_ms'])


class IntervalStraddle(Base):
    def test_straddling_interval_is_uncertain(self):
        result = fx.build(self.cfg, self.cfg_path, PRED, SEL,
                          damage={0: dict(straddle_expert=0, straddle_refresh=0)})
        row = self.summary(result)['segments'][0]
        expert = [e for e in row['experts'] if e['job_id'] == 'E0'][0]
        self.assertEqual(expert['deadline_status'], 'UNCERTAIN')
        refresh = [r for r in row['refreshes'] if r['job_id'] == 'refresh0'][0]
        self.assertEqual(refresh['status'], 'UNCERTAIN')
        self.assertIsNotNone(refresh['response_interval_ms'][1])


class NotStartedRecords(Base):
    """The real pre-created structure: eight records, some still NOT_STARTED."""

    def test_five_executed_three_not_started(self):
        result = fx.build(self.cfg, self.cfg_path, PRED, SEL, executed=5)
        self.assertEqual(len(result['segments']), 8)
        self.assertEqual([s['status'] for s in result['segments'][5:]],
                         ['NOT_STARTED'] * 3)
        s = self.summary(result)
        self.assertEqual(s['declared'], dict(Expert=64, Cycle=64, Refresh=32))
        self.assertEqual(s['totals']['Expert']['PASS'], 40)
        self.assertEqual(s['totals']['Expert']['INCOMPLETE'], 24)
        self.assertEqual(s['totals']['Cycle']['PASS'], 40)
        self.assertEqual(s['totals']['Cycle']['INCOMPLETE'], 24)
        self.assertEqual(s['totals']['Refresh']['PASS'], 20)
        self.assertEqual(s['totals']['Refresh']['INCOMPLETE'], 12)
        for row in s['segments'][5:]:
            self.assertEqual(row['status'], 'NOT_STARTED')
            self.assertEqual(len(row['experts']), 8)
            self.assertEqual(len(row['cycles']), 8)
            self.assertEqual(len(row['refreshes']), 4)
            self.assertTrue(all(e['completion_status'] == 'INCOMPLETE'
                                and e['deadline_status'] == 'INCOMPLETE'
                                and e['completion_ms'] is None
                                and e['response_ms'] is None
                                and e['margin_ms'] is None for e in row['experts']))
        condition = ev.condition_check(result, self.cfg, self.cfg_path)
        self.assertEqual(condition['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIn('segments.phase_ns', condition['unknown'])
        self.assertEqual(len(condition['not_started']), 3)
        self.assertEqual(condition['mismatches'], [])

    def test_five_and_three_cli_report(self):
        result = fx.build(self.cfg, self.cfg_path, PRED, SEL, executed=5)
        code, doc = self.run_cli(result, 'mixed')
        self.assertEqual(code, 0, 'an incomplete but valid record must be reportable')
        self.assertEqual(doc['verdict'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(doc['invalid_evidence'], [])
        self.assertEqual(doc['part_b_official_performance']['declared'],
                         dict(Expert=64, Cycle=64, Refresh=32))
        self.assertEqual(doc['part_b_official_performance']['totals']['Expert']['INCOMPLETE'],
                         24)
        self.assertEqual(doc['part_c_selection']['prediction_status'], 'NOT_EVALUABLE')
        self.assertEqual(doc['part_c_selection']['selector_domain'], 'INSUFFICIENT_EVIDENCE')
        self.assertGreater(doc['part_c_selection']['reserve']['unknown'], 0)

    def test_all_not_started_cli(self):
        result = fx.build(self.cfg, self.cfg_path, PRED, SEL, executed=0)
        code, doc = self.run_cli(result, 'none')
        self.assertEqual(code, 0)
        self.assertEqual(doc['verdict'], 'INSUFFICIENT_EVIDENCE')
        totals = doc['part_b_official_performance']['totals']
        self.assertEqual(totals['Expert']['INCOMPLETE'], 64)
        self.assertEqual(totals['Cycle']['INCOMPLETE'], 64)
        self.assertEqual(totals['Refresh']['INCOMPLETE'], 32)
        self.assertEqual(totals['Refresh']['PASS'], 0)
        self.assertFalse(totals['Expert']['PASS'])
        self.assertEqual(doc['part_c_selection']['reserve']['unknown'], 64)
        self.assertEqual(doc['part_c_selection']['reserve']['short'], 0)
        self.assertEqual(doc['part_b_official_performance']['declared'],
                         dict(Expert=64, Cycle=64, Refresh=32))
        self.assertIn('segments.phase_ns',
                      doc['part_c_selection']['condition']['unknown'])

    def test_identity_conflict_is_invalid(self):
        result = fx.build(self.cfg, self.cfg_path, PRED, SEL)
        result['segments'][3]['plan'] = 'two_9_9' if result['segments'][3]['plan'] != 'two_9_9' \
            else 'three_prefix_9_9'
        s = self.summary(result)
        self.assertEqual(s['segments'][3]['status'], 'INVALID_EVIDENCE')
        self.assertTrue(any('identity conflict' in i for i in s['segments'][3]['issues']))
        self.assertEqual(s['totals']['Expert']['INVALID'], 8)
        code, doc = self.run_cli(result, 'conflict')
        self.assertEqual(code, 2)
        self.assertEqual(doc['verdict'], 'INVALID_EVIDENCE')


class PredictionIsUsed(Base):
    def setUp(self):
        self.rows = self.summary()['segments']
        self.pred = load(PRED)
        self.seg = self.result['segments'][0]

    def test_completion_shift_changes_the_error_by_the_same_amount(self):
        base = ev.compare_segment(self.rows[0], self.pred, 'typical')
        job = next(j for j in base['jobs'] if j['job_type'] == 'Expert'
                   and j['completion_error_ms'] is not None)
        mutated = copy.deepcopy(self.pred)
        for r in mutated['jobs']:
            if (r['budget_ms'] == 180.0 and r['plan'] == 'two_9_9'
                    and r['scenario'] == 'typical' and r['job_id'] == job['job_id']
                    and r['job_type'] == 'Expert'):
                r['completion_ms'] += 5.0
        after = ev.compare_segment(self.rows[0], mutated, 'typical')
        job2 = next(j for j in after['jobs'] if j['job_type'] == 'Expert'
                    and j['job_id'] == job['job_id'])
        self.assertAlmostEqual(job2['completion_error_ms'] - job['completion_error_ms'],
                               5.0, places=6)

    def test_order_and_version_changes_are_reported(self):
        base = ev.order_and_versions(self.seg, self.pred, 'typical')
        mutated = copy.deepcopy(self.pred)
        key = 'p%d' % int(self.seg['period_ns'] / 1e6)
        order = mutated['order'][key][self.seg['plan']]['typical']
        order[0], order[1] = order[1], order[0]
        after = ev.order_and_versions(self.seg, mutated, 'typical')
        self.assertNotEqual(base['first_divergence'], after['first_divergence'])
        mutated2 = copy.deepcopy(self.pred)
        for r in mutated2['jobs']:
            if (r['job_type'] == 'Expert'
                    and r['budget_ms'] == self.seg['period_ns'] / 1e6
                    and r['plan'] == self.seg['plan'] and r['scenario'] == 'typical'
                    and r['job_id'] == 'E0'):
                r['version'] = 99
        after2 = ev.order_and_versions(self.seg, mutated2, 'typical')
        self.assertFalse(after2['version_match'])
        self.assertIn('E0', after2['version_mismatched'])

    def test_missing_prediction_is_not_a_match(self):
        mutated = copy.deepcopy(self.pred)
        mutated['jobs'] = [r for r in mutated['jobs'] if r['job_type'] != 'Refresh']
        out = ev.compare_segment(self.rows[0], mutated, 'typical')
        self.assertNotEqual(out['status'], 'OK')
        self.assertTrue(any(x.startswith('Refresh:') for x in out['predicted_missing']))


class StressDirection(Base):
    """stress_exceedance = actual - predicted; only > 0 counts, positive amount."""

    def _doc(self, completion_ns, name):
        result = copy.deepcopy(self.result)
        fx.set_expert_completion(result, 0, 0, completion_ns)
        code, doc = self.run_cli(result, name)
        self.assertEqual(code, 0)
        comp = doc['part_c_selection']['comparison']
        job = [j for seg in comp['per_segment'] if seg['segment_id'] ==
               result['segments'][0]['segment_id'] and seg['scenario'] == 'stress'
               for j in seg['jobs'] if j['job_type'] == 'Expert' and j['job_id'] == 'E0'][0]
        listed = [x for x in comp['stress_completion_exceed']
                  if x['segment_id'] == result['segments'][0]['segment_id']
                  and x['job'] == 'E0']
        return job, listed, comp

    def test_equal_is_not_an_exceedance(self):
        predicted = fx.predicted_stress(self.result, load(PRED), 0, 0)
        t0 = self.result['segments'][0]['t0_ns']
        job, listed, _comp = self._doc(t0 + int(predicted * 1e6), 'eq')
        self.assertEqual(job['completion_exceedance_ms'], 0.0)
        self.assertEqual(job['completion_error_ms'], 0.0)
        self.assertEqual(listed, [])

    def test_actual_later_than_predicted_is_positive_exceedance(self):
        predicted = fx.predicted_stress(self.result, load(PRED), 0, 0)
        t0 = self.result['segments'][0]['t0_ns']
        job, listed, comp = self._doc(t0 + int((predicted + 10.0) * 1e6), 'late')
        self.assertAlmostEqual(job['completion_exceedance_ms'], 10.0, places=6)
        self.assertAlmostEqual(job['completion_error_ms'], -10.0, places=6)
        self.assertEqual(len(listed), 1)
        self.assertAlmostEqual(listed[0]['completion_exceed_ms'], 10.0, places=6)
        self.assertEqual(comp['exceedance_definition'].split(';')[0], 'actual - predicted')

    def test_actual_earlier_than_predicted_is_not_an_exceedance(self):
        predicted = fx.predicted_stress(self.result, load(PRED), 0, 0)
        t0 = self.result['segments'][0]['t0_ns']
        job, listed, _comp = self._doc(t0 + int((predicted - 10.0) * 1e6), 'early')
        self.assertAlmostEqual(job['completion_exceedance_ms'], -10.0, places=6)
        self.assertAlmostEqual(job['completion_error_ms'], 10.0, places=6)
        self.assertEqual(listed, [])


class ConditionRejection(Base):
    def test_same_label_is_not_enough(self):
        ok = ev.condition_check(self.result, self.cfg, self.cfg_path)
        self.assertEqual(ok['status'], 'MATCH', ok['mismatches'])
        bad = copy.deepcopy(self.cfg)
        bad['phase_ns'] = 20_000_000
        out = ev.condition_check(self.result, bad, self.cfg_path)
        self.assertEqual(out['status'], 'CONDITION_MISMATCH')
        self.assertIn('segments.phase_ns', out['mismatches'])
        bad2 = copy.deepcopy(self.cfg)
        bad2['binding'] = 'different consumption'
        out2 = ev.condition_check(self.result, bad2, self.cfg_path)
        self.assertIn('manifest.binding', out2['mismatches'])
        result3 = copy.deepcopy(self.result)
        result3.pop('initial_clock_limits')
        out3 = ev.condition_check(result3, self.cfg, self.cfg_path)
        self.assertEqual(out3['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIn('initial_clock_limits', out3['unknown'])

    def test_lead_mismatch_is_a_mismatch(self):
        bad = copy.deepcopy(self.cfg)
        bad['design']['lead_ms'] = 4000
        self.assertNotEqual(ev.condition_check(self.result, bad, self.cfg_path)['status'],
                            'MATCH')


class FrozenRejection(Base):
    def test_tampered_prediction_and_selection_are_rejected(self):
        before = {p: fx.sha(p) for p in (PRED, SEL, RULES, COSTS)}
        tmp = Path(self.tmp.name)
        pred = load(PRED)
        pred['jobs'][0]['completion_ms'] += 1.0
        bad_pred = tmp / 'PRED.json'
        bad_pred.write_text(json.dumps(pred))
        sel = load(SEL)
        sel['reserve_ms'] = 5.0
        bad_sel = tmp / 'SEL.json'
        bad_sel.write_text(json.dumps(sel))
        v = ev.verify_frozen(self.cfg_path, RULES, COSTS, bad_pred, bad_sel,
                             {'evaluate_b9.py': B9 / 'analysis' / 'evaluate_b9.py',
                              'prediction_model.py': B9 / 'prediction' / 'prediction_model.py'})
        self.assertFalse(v['ok'])
        self.assertIn('config.prediction.sha256', v['failed'])
        self.assertIn('config.selection.sha256', v['failed'])
        self.assertEqual(before, {p: fx.sha(p) for p in (PRED, SEL, RULES, COSTS)})


class FullCli(Base):
    def test_cli_fixture_three_parts_and_exit(self):
        code, doc = self.run_cli(self.result, 'full')
        self.assertEqual(code, 0)
        for key in ('part_a_correctness', 'part_b_official_performance',
                    'part_c_selection', 'frozen', 'source'):
            self.assertIn(key, doc)
        self.assertEqual(doc['part_b_official_performance']['declared'],
                         dict(Expert=64, Cycle=64, Refresh=32))
        self.assertEqual(doc['part_b_official_performance']['totals']['Expert']['PASS'], 64)
        self.assertEqual(doc['verdict'], 'EVALUATED')
        self.assertEqual(doc['part_c_selection']['condition']['status'], 'MATCH')
        self.assertEqual(doc['part_c_selection']['prediction_status'], 'EVALUATED')
        self.assertEqual(doc['invalid_evidence'], [])

    def test_cli_condition_mismatch_keeps_comparison_but_not_a_pass(self):
        bad = copy.deepcopy(self.cfg)
        bad['phase_ns'] = 20_000_000
        bad_path = Path(self.tmp.name) / 'CONFIG_bad.json'
        bad_path.write_text(json.dumps(bad))
        result = fx.build(bad, bad_path, PRED, SEL)
        code, doc = self.run_cli(result, 'mismatch')
        self.assertEqual(code, 0)
        self.assertEqual(doc['verdict'], 'CONDITION_MISMATCH')
        self.assertEqual(doc['part_c_selection']['selector_domain'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(doc['part_c_selection']['prediction_status'], 'CONDITION_MISMATCH')
        self.assertTrue(doc['part_c_selection']['comparison']['per_segment'])

    def test_cli_invalid_evidence_exits_2(self):
        result = copy.deepcopy(self.result)
        result['segments'][0]['experts']['0'] = (5, 1)
        code, doc = self.run_cli(result, 'broken')
        self.assertEqual(code, 2)
        self.assertEqual(doc['verdict'], 'INVALID_EVIDENCE')
        self.assertTrue(doc['invalid_evidence'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
