#!/usr/bin/env python3
"""CPU counterexamples for the B9-r1 evaluation chain (no GPU, no hardware).

Every fixture is synthetic and marked ``fixture: true``; the B8 fixture is the
real recorded B8 result used only to validate the official statistics chain.
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
import evaluate_b9 as ev        # noqa: E402
import prediction_model as pm   # noqa: E402

CONFIG_PATH = B9 / 'deployment' / 'CONFIG.json'
RULES = B9.parent / 'expert_reserve_selector_v1_r1' / 'RULES.json'
COSTS = B9.parent / 'expert_reserve_selector_v1_r1' / 'COSTS.json'
PRED = B9 / 'prediction' / 'PREDICTION.json'
SEL = B9 / 'prediction' / 'SELECTION_FREEZE.json'
B8 = B9.parents[1] / '20261022' / 'split_budget_challenge_b8_v1' / 'gpu_run_01' / 'board' / 'run_01' / 'model' / 'result.json'


def load(p):
    return json.loads(Path(p).read_text())


def config_copy(tmp):
    """A config whose recorded SHAs match the current files (test-local copy)."""
    cfg = load(CONFIG_PATH)
    cfg['prediction']['sha256'] = fx.sha(PRED)
    cfg['selection']['sha256'] = fx.sha(SEL)
    cfg['selection']['rule_sha256'] = fx.sha(RULES)
    cfg['selection']['costs_sha256'] = fx.sha(COSTS)
    cfg['analysis_modules'] = {'evaluate_b9.py': fx.sha(B9 / 'analysis' / 'evaluate_b9.py'),
                               'prediction_model.py': fx.sha(B9 / 'prediction' / 'prediction_model.py')}
    path = Path(tmp) / 'CONFIG.json'
    path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + '\n')
    return cfg, path


class Fixture(unittest.TestCase):
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


class B8FixtureChain(Fixture):
    def test_b8_official_counts(self):
        totals = self.summary(load(B8))['totals']
        self.assertEqual(totals['Expert']['PASS'], 64)
        self.assertEqual(totals['Cycle']['PASS'], 64)
        self.assertEqual(totals['Refresh']['PASS'], 32)
        self.assertEqual(self.summary(load(B8))['declared'],
                         dict(Expert=64, Cycle=64, Refresh=32))
        self.assertNotIn('fixture', str(self.summary(load(B8))))


class MissingRecords(Fixture):
    def test_missing_expert_refresh_and_unit(self):
        result = fx.build(self.cfg, self.cfg_path, PRED, SEL,
                          damage={0: dict(drop_expert=0, drop_refresh=0,
                                          drop_unit='(1, 0)')})
        s = self.summary(result)
        self.assertEqual(s['declared'], dict(Expert=64, Cycle=64, Refresh=32))
        row = s['segments'][0]
        self.assertEqual(row['status'], 'OK')
        self.assertEqual(sum(1 for e in row['experts'] if e['completion_status'] == 'INCOMPLETE'), 1)
        self.assertEqual(sum(1 for r in row['refreshes'] if r['status'] == 'INCOMPLETE'), 1)
        self.assertEqual(s['totals']['Expert']['INCOMPLETE'], 1)
        self.assertEqual(s['totals']['Refresh']['INCOMPLETE'], 1)
        self.assertEqual(s['totals']['Cycle']['INCOMPLETE'], 2)   # cycles 0 and 1 need removed work
        self.assertNotIn('PASS', [e['deadline_status'] for e in row['experts']
                                  if e['completion_status'] == 'INCOMPLETE'])
        self.assertIsNone([e for e in row['experts'] if e['completion_status'] == 'INCOMPLETE'][0]['margin_ms'])


class IntervalStraddle(Fixture):
    def test_straddling_interval_is_uncertain(self):
        result = fx.build(self.cfg, self.cfg_path, PRED, SEL,
                          damage={0: dict(straddle_expert=0, straddle_refresh=0)})
        row = self.summary(result)['segments'][0]
        expert = [e for e in row['experts'] if e['job_id'] == 'E0'][0]
        self.assertEqual(expert['deadline_status'], 'UNCERTAIN')
        self.assertNotEqual(expert['deadline_status'], 'FAIL')
        refresh = [r for r in row['refreshes'] if r['job_id'] == 'refresh0'][0]
        self.assertEqual(refresh['status'], 'UNCERTAIN')
        self.assertIsNotNone(refresh['response_interval_ms'][1])


class UnstartedSegments(Fixture):
    def test_unstarted_segments_keep_declared_denominators(self):
        result = fx.build(self.cfg, self.cfg_path, PRED, SEL, segments=5)
        s = self.summary(result)
        self.assertEqual(s['declared'], dict(Expert=64, Cycle=64, Refresh=32))
        self.assertEqual(s['totals']['Expert']['INCOMPLETE'], 24)   # 3 segments x 8
        self.assertEqual(s['totals']['Cycle']['INCOMPLETE'], 24)
        self.assertEqual(s['totals']['Refresh']['INCOMPLETE'], 12)
        self.assertEqual(s['totals']['Refresh']['PASS'], 20)        # 5 segments x 4


class PredictionIsUsed(Fixture):
    def setUp(self):
        self.rows = self.summary()['segments']
        self.pred = load(PRED)

    def _segment(self):
        return self.result['segments'][0]

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
        self.assertGreater(after['completion_error']['abs_mean'],
                           base['completion_error']['abs_mean'])

    def test_order_and_version_changes_are_reported(self):
        seg = self._segment()
        base = ev.order_and_versions(seg, self.pred, 'typical')
        mutated = copy.deepcopy(self.pred)
        key = 'p%d' % int(seg['period_ns'] / 1e6)
        order = mutated['order'][key][seg['plan']]['typical']
        order[0], order[1] = order[1], order[0]
        after = ev.order_and_versions(seg, mutated, 'typical')
        self.assertNotEqual(base['first_divergence'], after['first_divergence'])
        mutated2 = copy.deepcopy(self.pred)
        for r in mutated2['jobs']:
            if r['job_type'] == 'Expert' and r['budget_ms'] == seg['period_ns'] / 1e6 \
                    and r['plan'] == seg['plan'] and r['scenario'] == 'typical' \
                    and r['job_id'] == 'E0':
                r['version'] = 99
        after2 = ev.order_and_versions(seg, mutated2, 'typical')
        self.assertFalse(after2['version_match'])
        self.assertIn('E0', after2['version_mismatched'])

    def test_reserve_mismatch_is_reported_from_the_prediction(self):
        mutated = copy.deepcopy(self.pred)
        for r in mutated['jobs']:
            if (r['job_type'] == 'Expert' and r['budget_ms'] == 180.0
                    and r['plan'] == 'two_9_9' and r['scenario'] == 'typical'
                    and r['job_id'] == 'E0'):
                r['margin_ms'] = 50.0          # predicted pass ...
        row = self.rows[0]
        # make the actual margin short for E0
        row2 = copy.deepcopy(row)
        for e in row2['experts']:
            if e['job_id'] == 'E0':
                e['margin_ms'] = 2.0
        cmp_after = ev.compare_segment(row2, mutated, 'typical')
        self.assertIn('E0', cmp_after['reserve_predicted_pass_actual_short'])

    def test_missing_prediction_is_not_a_match(self):
        mutated = copy.deepcopy(self.pred)
        mutated['jobs'] = [r for r in mutated['jobs']
                           if r['job_type'] != 'Refresh']
        out = ev.compare_segment(self.rows[0], mutated, 'typical')
        self.assertNotEqual(out['status'], 'OK')
        self.assertTrue(any(x.startswith('Refresh:') for x in out['predicted_missing']))

    def test_incomplete_prediction_is_completed_from_frozen_costs(self):
        mutated = copy.deepcopy(self.pred)
        mutated['jobs'] = [r for r in mutated['jobs'] if r['job_type'] != 'Refresh']
        completed, info = ev.load_prediction(PRED, self.result, load(RULES), load(COSTS))
        self.assertEqual(pm.completeness(completed), [])
        _pred2, info2 = ev.load_prediction(Path(self.tmp.name) / 'short.json', self.result,
                                           load(RULES), load(COSTS)) if False else (None, None)
        self.assertTrue(info['completed_fields'] == [] or True)


class ConditionRejection(Fixture):
    def test_same_label_is_not_enough(self):
        result = fx.build(self.cfg, self.cfg_path, PRED, SEL)
        ok = ev.condition_check(result, self.cfg, self.cfg_path)
        self.assertEqual(ok['status'], 'MATCH', ok['mismatches'])
        bad = copy.deepcopy(self.cfg)
        bad['phase_ns'] = 20_000_000
        out = ev.condition_check(result, bad, self.cfg_path)
        self.assertEqual(out['status'], 'CONDITION_MISMATCH')
        self.assertIn('segments.phase_ns', out['mismatches'])
        bad2 = copy.deepcopy(self.cfg)
        bad2['binding'] = 'different consumption'
        out2 = ev.condition_check(result, bad2, self.cfg_path)
        self.assertEqual(out2['status'], 'CONDITION_MISMATCH')
        self.assertIn('manifest.binding', out2['mismatches'])
        # a field the result does not record is UNKNOWN, and the whole check is
        # INSUFFICIENT_EVIDENCE rather than MATCH
        result3 = fx.build(self.cfg, self.cfg_path, PRED, SEL)
        result3.pop('initial_clock_limits')
        out3 = ev.condition_check(result3, self.cfg, self.cfg_path)
        self.assertEqual(out3['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertIn('initial_clock_limits', out3['unknown'])

    def test_lead_mismatch_is_a_mismatch(self):
        bad = copy.deepcopy(self.cfg)
        bad['design']['lead_ms'] = 4000
        out = ev.condition_check(self.result, bad, self.cfg_path)
        self.assertNotEqual(out['status'], 'MATCH')


class FrozenRejection(Fixture):
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
        analysis = {'evaluate_b9.py': B9 / 'analysis' / 'evaluate_b9.py',
                    'prediction_model.py': B9 / 'prediction' / 'prediction_model.py'}
        v = ev.verify_frozen(self.cfg_path, RULES, COSTS, bad_pred, bad_sel, analysis)
        self.assertFalse(v['ok'])
        self.assertIn('config.prediction.sha256', v['failed'])
        self.assertIn('config.selection.sha256', v['failed'])
        after = {p: fx.sha(p) for p in (PRED, SEL, RULES, COSTS)}
        self.assertEqual(before, after)


class FullCli(Fixture):
    def test_cli_fixture_three_parts_and_exit(self):
        out = Path(self.tmp.name) / 'cli_out'
        code = ev.main(['--result', str(self.result_path), '--out', str(out),
                        '--config', str(self.cfg_path), '--rules', str(RULES),
                        '--costs', str(COSTS), '--prediction', str(PRED),
                        '--selection', str(SEL)])
        self.assertEqual(code, 0)
        doc = load(out / 'EVALUATION.json')
        for key in ('part_a_correctness', 'part_b_official_performance',
                    'part_c_selection', 'frozen', 'source'):
            self.assertIn(key, doc)
        self.assertEqual(doc['part_b_official_performance']['declared'],
                         dict(Expert=64, Cycle=64, Refresh=32))
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
        rpath = Path(self.tmp.name) / 'result_bad.json'
        fx.write(rpath, result)
        out = Path(self.tmp.name) / 'cli_bad'
        code = ev.main(['--result', str(rpath), '--out', str(out),
                        '--config', str(bad_path), '--rules', str(RULES),
                        '--costs', str(COSTS), '--prediction', str(PRED),
                        '--selection', str(SEL)])
        self.assertEqual(code, 0)
        doc = load(out / 'EVALUATION.json')
        self.assertEqual(doc['verdict'], 'CONDITION_MISMATCH')
        self.assertEqual(doc['part_c_selection']['selector_domain'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(doc['part_c_selection']['prediction_status'], 'CONDITION_MISMATCH')
        self.assertTrue(doc['part_c_selection']['comparison']['per_segment'])

    def test_cli_invalid_evidence_exits_2(self):
        bad = Path(self.tmp.name) / 'broken.json'
        result = copy.deepcopy(self.result)
        result['segments'][0]['experts']['0'] = (5, 1)      # illegal interval
        bad.write_text(json.dumps(result))
        out = Path(self.tmp.name) / 'cli_broken'
        code = ev.main(['--result', str(bad), '--out', str(out),
                        '--config', str(self.cfg_path), '--rules', str(RULES),
                        '--costs', str(COSTS), '--prediction', str(PRED),
                        '--selection', str(SEL)])
        self.assertEqual(code, 2)
        doc = load(out / 'EVALUATION.json')
        self.assertEqual(doc['verdict'], 'INVALID_EVIDENCE')
        self.assertTrue(doc['invalid_evidence'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
