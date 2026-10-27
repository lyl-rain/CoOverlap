#!/usr/bin/env python3
"""Targeted CPU tests for the release-boundary evaluator.

Only the new risks of this round are checked: the two margins, the branch
decision, the 1 ns construction, and the condition/data separation.  The real
frozen records are read, never written; the model is the copied r1 analysis
model driving the real frozen ``m2_executor.VersionedKV``.  No production
executor is imported or modified and no historical suite is re-run.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import audit      # noqa: E402
import costs      # noqa: E402
import env        # noqa: E402
import evaluation  # noqa: E402
import replay     # noqa: E402
import sensitivity  # noqa: E402

env.prepare_imports()

RESULT = env.load(env.B8_RESULT)
PREDICTION = env.load(env.B8_PREDICTION)
MEASURED = costs.b8_measured_costs(RESULT)
CELL = {c['cell'][0]: c for c in MEASURED['cells'].values()}


def segment(name):
    for s in RESULT['segments']:
        if s['segment_id'] == name:
            return s
    raise KeyError(name)


def make_view(release1=110.0, publish=92.0, token='default', gpu=(89.0, 89.5),
              decision=90.0, branch='tail'):
    """A minimal two-block view.

    ``branch`` states what the executor actually did at the post-E0 boundary:
    ``tail`` runs the tail block (the Expert was not runnable) and ``expert``
    dispatches E1 (it was released and runnable).  This mirrors how the records
    and the frozen prediction express the two branches; the audit describes what
    happened and what the alternative was, it does not re-simulate the choice.
    """
    events = [
        dict(kind='stage', refresh=0, block=None, block_kind=None, id=0, job='R0/stage',
             decision_ms=0.0, end_ms=5.0, gpu_lower_ms=4.0, gpu_upper_ms=4.5, op=None,
             version=1, after_idle=False),
        dict(kind='Context', refresh=0, block=0, block_kind='B1', id=0, job='R0/B1',
             decision_ms=5.0, end_ms=40.0, gpu_lower_ms=39.0, gpu_upper_ms=39.5, op=None,
             version=1, after_idle=False),
        dict(kind='Expert', refresh=None, block=None, block_kind=None, id=0, job='E0',
             decision_ms=40.0, end_ms=decision, gpu_lower_ms=gpu[0], gpu_upper_ms=gpu[1],
             op=None, version=0, after_idle=False),
    ]
    if branch == 'tail':
        events.append(dict(kind='Context', refresh=0, block=1, block_kind='B2', id=0,
                           job='R0/B2', decision_ms=decision, end_ms=160.0,
                           gpu_lower_ms=159.0, gpu_upper_ms=159.5, op=None, version=1,
                           after_idle=False))
    else:
        events.append(dict(kind='Expert', refresh=None, block=None, block_kind=None, id=1,
                           job='E1', decision_ms=decision, end_ms=160.0,
                           gpu_lower_ms=159.0, gpu_upper_ms=159.5, op=None, version=0,
                           after_idle=False))
        events.append(dict(kind='Context', refresh=0, block=1, block_kind='B2', id=0,
                           job='R0/B2', decision_ms=160.0, end_ms=205.0,
                           gpu_lower_ms=204.0, gpu_upper_ms=204.5, op=None, version=1,
                           after_idle=False))
    if token == 'default':
        # the frozen executor binds the even Expert and reserves its odd partner on
        # the same version at the even dispatch, so both tokens exist from 40 ms
        token_ms = {0: 40.0, 1: 40.0}
    else:
        token_ms = token
    return dict(side='synthetic', segment_id='synthetic', cell='SYN', plan='two_9_9',
                period_ms=100.0, pass_=None, cycles=2,
                releases_ms={0: 10.0, 1: release1}, deadlines_ms={0: 110.0, 1: 210.0},
                events=events, jobs={}, block_end={(0, 0): 40.0, (0, 1): 205.0},
                publish_ms={} if publish is None else {0: publish},
                token_ms=token_ms, version={0: 0, 1: 0}, progress=[],
                decision_origin='synthetic', note='synthetic')


def after_e0(rows):
    return [r for r in rows if r['boundary_key'] == 'after:E0'][0]


class ReleaseSide(unittest.TestCase):
    def test_before_release_the_tail_block_runs(self):
        row = after_e0(audit.boundaries(make_view(release1=110.0)))
        self.assertEqual(row['next_expert_state'], audit.STATE_NOT_RELEASED)
        self.assertEqual(row['release_side_at_decision'], 'BEFORE_RELEASE')
        self.assertAlmostEqual(row['distance_decision_ms'], 20.0)
        self.assertFalse(row['release_crossed_by_decision'])
        self.assertEqual(row['chosen_job'], 'R0/B2')
        self.assertTrue(row['release_during_chosen_op'])

    def test_release_exactly_at_the_decision_uses_the_executor_rule(self):
        row = after_e0(audit.boundaries(make_view(release1=90.0, branch='expert')))
        self.assertEqual(row['release_side_at_decision'], 'AT_RELEASE')
        self.assertAlmostEqual(row['distance_decision_ms'], 0.0)
        self.assertTrue(row['release_crossed_by_decision'])
        self.assertEqual(row['next_expert_state'], audit.STATE_READY)
        self.assertEqual(row['chosen_job'], 'E1', 'release <= now must dispatch the Expert')
        self.assertEqual(row['competing_job'], 'R0/B2')

    def test_after_release_the_expert_preempts_the_block(self):
        row = after_e0(audit.boundaries(make_view(release1=70.0, branch='expert')))
        self.assertEqual(row['release_side_at_decision'], 'AFTER_RELEASE')
        self.assertLess(row['distance_decision_ms'], 0)
        self.assertEqual(row['chosen_job'], 'E1')
        self.assertEqual(row['competing_job'], 'R0/B2')
        self.assertTrue(row['competition'])


class ExpertState(unittest.TestCase):
    def test_completed_and_not_released_are_distinct(self):
        rows = audit.boundaries(make_view(release1=110.0))
        row = after_e0(rows)
        self.assertEqual(row['prev_expert_state'], audit.STATE_COMPLETED)
        self.assertEqual(row['next_expert_state'], audit.STATE_NOT_RELEASED)

    def test_released_but_version_not_ready_waits(self):
        # E3 uses version 1; refresh 0 has not published it and no ownership token
        # exists for E3, so a released E3 must not be dispatched.
        view = dict(side='synthetic', segment_id='synthetic', cell='SYN', plan='two_9_9',
                    period_ms=100.0, pass_=None, cycles=4,
                    releases_ms={0: 10.0, 1: 30.0, 2: 60.0, 3: 80.0},
                    deadlines_ms={0: 110.0, 1: 130.0, 2: 160.0, 3: 180.0},
                    events=[
                        dict(kind='stage', refresh=0, block=None, block_kind=None, id=0,
                             job='R0/stage', decision_ms=0.0, end_ms=5.0, gpu_lower_ms=4.0,
                             gpu_upper_ms=4.5, op=None, version=1, after_idle=False),
                        dict(kind='Context', refresh=0, block=0, block_kind='B1', id=0,
                             job='R0/B1', decision_ms=5.0, end_ms=40.0, gpu_lower_ms=39.0,
                             gpu_upper_ms=39.5, op=None, version=1, after_idle=False),
                        dict(kind='Expert', refresh=None, block=None, block_kind=None, id=0,
                             job='E0', decision_ms=40.0, end_ms=50.0, gpu_lower_ms=49.0,
                             gpu_upper_ms=49.5, op=None, version=0, after_idle=False),
                        dict(kind='Expert', refresh=None, block=None, block_kind=None, id=1,
                             job='E1', decision_ms=50.0, end_ms=60.0, gpu_lower_ms=59.0,
                             gpu_upper_ms=59.5, op=None, version=0, after_idle=False),
                        dict(kind='Context', refresh=0, block=1, block_kind='B2', id=0,
                             job='R0/B2', decision_ms=60.0, end_ms=95.0, gpu_lower_ms=94.0,
                             gpu_upper_ms=94.5, op=None, version=1, after_idle=False),
                        dict(kind='stage', refresh=1, block=None, block_kind=None, id=1,
                             job='R1/stage', decision_ms=100.0, end_ms=105.0, gpu_lower_ms=104.0,
                             gpu_upper_ms=104.5, op=None, version=2, after_idle=True),
                        dict(kind='Context', refresh=1, block=0, block_kind='B1', id=1,
                             job='R1/B1', decision_ms=105.0, end_ms=140.0, gpu_lower_ms=139.0,
                             gpu_upper_ms=139.5, op=None, version=2, after_idle=False),
                        dict(kind='Expert', refresh=None, block=None, block_kind=None, id=2,
                             job='E2', decision_ms=140.0, end_ms=150.0, gpu_lower_ms=149.0,
                             gpu_upper_ms=149.5, op=None, version=1, after_idle=False),
                        dict(kind='Context', refresh=1, block=1, block_kind='B2', id=1,
                             job='R1/B2', decision_ms=150.0, end_ms=190.0, gpu_lower_ms=189.0,
                             gpu_upper_ms=189.5, op=None, version=2, after_idle=False),
                    ],
                    jobs={}, block_end={(0, 0): 40.0, (0, 1): 95.0, (1, 0): 140.0, (1, 1): 190.0},
                    publish_ms={}, token_ms={0: 40.0, 1: 40.0, 2: 140.0},
                    version={0: 0, 2: 1}, progress=[],
                    decision_origin='synthetic', note='synthetic')
        row = [r for r in audit.boundaries(view) if r['boundary_key'] == 'after:E2'][0]
        self.assertEqual(row['next_expert_id'], 3)
        self.assertEqual(row['next_expert_state'], audit.STATE_VERSION_WAIT)
        self.assertFalse(row['next_expert_version_ready'])
        self.assertEqual(row['released_ready_experts'], [])
        self.assertEqual(row['released_version_wait_experts'], [3])
        self.assertEqual(row['chosen_job'], 'R1/B2',
                         'a released but unready Expert must not be dispatched')
        self.assertLess(row['distance_decision_ms'], 0,
                        'a negative distance alone does not force a dispatch')

    def test_ready_evidence_names_the_mechanism(self):
        row = after_e0(audit.boundaries(make_view(release1=70.0, branch='expert')))
        self.assertEqual(row['next_expert_version_evidence'], 'ownership_token')
        row = after_e0(audit.boundaries(make_view(release1=70.0, branch='expert',
                                                  token={0: 40.0}, publish=60.0)))
        self.assertEqual(row['next_expert_version_evidence'], 'published_version')

    def test_queue_and_future_arrival_are_not_confused(self):
        before = after_e0(audit.boundaries(make_view(release1=110.0)))
        self.assertEqual(before['released_ready_experts'], [])
        self.assertEqual(before['next_expert_id'], 1)
        self.assertGreater(before['distance_decision_ms'], 0)
        after = after_e0(audit.boundaries(make_view(release1=70.0, branch='expert')))
        self.assertEqual(after['released_ready_experts'], [1])
        self.assertLess(after['distance_decision_ms'], 0)


class IntervalUncertainty(unittest.TestCase):
    def test_release_inside_completion_interval_is_uncertain(self):
        view = make_view(release1=90.0, gpu=(85.0, 95.0), decision=90.0)
        row = after_e0(audit.boundaries(view))
        self.assertEqual(row['release_side_interval'], 'UNCERTAIN_INTERVAL')
        self.assertTrue(row['release_interval_uncertain'])
        self.assertIsNotNone(row['distance_decision_ms'],
                             'the decision-time comparison stays reported')

    def test_release_outside_the_interval_is_not_flagged(self):
        row = after_e0(audit.boundaries(make_view(release1=110.0)))
        self.assertFalse(row['release_interval_uncertain'])
        self.assertEqual(row['release_side_interval'], 'BEFORE_RELEASE')


class RealTrajectory(unittest.TestCase):
    def test_every_recorded_boundary_matches_the_executor_ready_view(self):
        rows = []
        for s in RESULT['segments']:
            rows.extend(audit.attach_record(audit.actual_view(s)))
        self.assertEqual(len(rows), 176)
        self.assertTrue(all(r['ready_matches_record'] for r in rows))
        self.assertEqual(sum(1 for r in rows if r['released_version_wait_experts']), 0)

    def test_140ms_two_block_boundary_reproduces_the_flip(self):
        row = after_e0(audit.attach_record(audit.actual_view(segment('p1_C_p140_two_b2_boundary'))))
        self.assertAlmostEqual(row['decision_ms'], 151.193885, places=6)
        self.assertAlmostEqual(row['distance_decision_ms'], 3.806115, places=6)
        self.assertEqual(row['chosen_job'], 'R0/B2')
        self.assertEqual(row['next_expert_state'], audit.STATE_NOT_RELEASED)

    def test_140ms_three_block_tail_is_b3_not_the_middle_block(self):
        rows = audit.attach_record(audit.actual_view(segment('p1_D_p140_three_b2_boundary')))
        tails = [r for r in rows if r['chosen_job'] == 'R0/B3']
        self.assertEqual(len(tails), 1)
        tail = tails[0]
        self.assertEqual(tail['chosen_block_index'], 2)
        self.assertEqual(tail['chosen_block_kind'], 'B2',
                         'the third block of three_prefix_9_9 is kind B2 / operation B3')
        self.assertAlmostEqual(tail['distance_decision_ms'], 2.555139, places=6)

    def test_thirty_two_refreshes_and_their_branch(self):
        actual = []
        for s in RESULT['segments']:
            actual.extend(audit.attach_record(audit.actual_view(s)))
        predicted = {}
        for letter, cell in PREDICTION['cells'].items():
            for kind in ('typical', 'stress'):
                predicted[(letter, kind)] = audit.boundaries(
                    audit.predicted_view(cell, kind, cell['scenarios'][kind]))
        cov = __import__('cli').refresh_coverage(RESULT, actual, predicted)
        self.assertEqual(len(cov), 32)
        self.assertTrue(all(c['actual_tail_before_expert'] for c in cov))
        self.assertTrue(all(c['actual_distance_ms'] > 0 for c in cov))
        flips_180 = [c for c in cov if c['period_ms'] == 180.0 and c['order_flip_typical']]
        flips_140 = [c for c in cov if c['period_ms'] == 140.0 and c['order_flip_typical']]
        self.assertEqual(len(flips_180), 0)
        self.assertEqual(len(flips_140), 16)

    def test_margin_identity_holds_at_every_tight_boundary(self):
        actual = []
        for s in RESULT['segments']:
            actual.extend(audit.attach_record(audit.actual_view(s)))
        rows = __import__('cli').identity_check(RESULT, actual)
        self.assertEqual(len(rows), 32)
        self.assertTrue(all(r['cycle_on_boundary_op'] for r in rows))
        self.assertTrue(all(r['same_instant'] for r in rows), 'distance == cycle margin - confirm')


class MissingEvidence(unittest.TestCase):
    def test_missing_job_is_incomplete_not_zero(self):
        broken = copy.deepcopy(segment('p1_C_p140_two_b2_boundary'))
        del broken['experts']['3']
        del broken['blocks']['(0, 1)']
        jobs = replay.actual_job_table(broken)
        self.assertIsNone(jobs[('Expert', 'E3')]['margin_ms'])
        self.assertEqual(jobs[('Expert', 'E3')]['status'], 'INCOMPLETE')
        self.assertIsNone(jobs[('ContextBlock', 'R0/B2')]['completion_ms'])
        rows = audit.attach_record(audit.actual_view(broken))
        self.assertEqual(len(rows), 20)
        e3 = [r for r in rows if r['next_expert_id'] == 3]
        self.assertTrue(e3)
        self.assertIsNone(e3[0]['expert_margin_ms'])
        self.assertEqual(len(broken['statistics']['cycles']), 8, 'denominator is kept')


class Conditions(unittest.TestCase):
    def test_cells_are_extracted_separately(self):
        for letter, cell in CELL.items():
            self.assertEqual(len(cell['segments']), 2)
            self.assertTrue(all((s.startswith('p1_') or s.startswith('p2_'))
                                and ('_%s_' % letter) in s for s in cell['segments']))
            self.assertLessEqual(cell['expert']['min'], cell['expert']['median'])
            self.assertLessEqual(cell['expert']['median'], cell['expert']['max'])

    def test_b4_and_b8_costs_are_not_pooled(self):
        b4 = costs.b4_source_costs()
        b4_expert = b4['candidates']['two_9_9']['expert']['median']
        key = [k for k in CELL if CELL[k]['plan'] == 'two_9_9' and CELL[k]['period_ns'] == 140_000_000][0]
        b8_expert = CELL[key]['expert']['median']
        self.assertGreater(abs(b4_expert - b8_expert), 2.0,
                           'the Expert envelope differs between conditions')
        scenario = costs.b8_scenario(CELL[key], 'typical')
        self.assertEqual(scenario['expert']['median'], CELL[key]['expert']['median'])
        self.assertNotEqual(scenario['expert']['median'], b4_expert)

    def test_conditions_have_distinct_labels(self):
        self.assertIn('H_frozen', env.CONDITION_LABELS['b8_actual'])
        self.assertIn('OTHER_S0', env.CONDITION_LABELS['b4_source'])


class Replay(unittest.TestCase):
    def test_b4_replay_reproduces_the_frozen_prediction(self):
        for period, letters in ((180.0, ('A', 'B')), (140.0, ('C', 'D'))):
            rep = replay.replay_b4(period)
            for letter, plan in zip(letters, ('two_9_9', 'three_prefix_9_9')):
                for kind in ('typical', 'stress'):
                    got = rep['cells'][(plan, kind)]
                    want = PREDICTION['cells'][letter]['scenarios'][kind]
                    self.assertEqual(got['feasible'], want['feasible'])
                    self.assertAlmostEqual(got['min_cycle_margin_ms'],
                                           want['min_cycle_margin_ms'], places=6)

    def test_b8_self_replay_reproduces_the_actual_order(self):
        """Retrospective: the same-condition costs put the actual branch first."""
        for name in ('p1_C_p140_two_b2_boundary', 'p1_D_p140_three_b2_boundary'):
            seg = segment(name)
            rep = replay.replay_b8(CELL[seg['cell'][0]])
            comp = replay.compare(rep['cells'], seg)
            self.assertTrue(all(v['order_match'] for v in comp.values()))
            self.assertLess(max(v['completion_abs_max_ms'] for v in comp.values()), 6.0)


class Construction(unittest.TestCase):
    def test_critical_delta_and_branches(self):
        c = sensitivity.construct(CELL['C'], 0)
        self.assertTrue(c['checks']['order_flipped'])
        self.assertTrue(c['branches']['pre']['tail_block_first'])
        self.assertFalse(c['branches']['post']['tail_block_first'])
        self.assertAlmostEqual(c['boundary']['release_ms'], 155.0)
        self.assertAlmostEqual(c['branches']['pre']['distance_ms'], 1e-6, places=12)
        self.assertAlmostEqual(c['branches']['post']['distance_ms'], -1e-6, places=12)
        self.assertEqual(c['checks']['pre'], [])
        self.assertEqual(c['checks']['post'], [])
        self.assertTrue(c['checks']['workload_unchanged'])

    def test_release_and_deadline_are_not_moved(self):
        c = sensitivity.construct(CELL['D'], 0)
        self.assertAlmostEqual(c['boundary']['release_ms'], 155.0)
        self.assertEqual(c['checks']['releases_unchanged'], True)
        self.assertEqual(c['checks']['deadlines_unchanged'], True)
        nblocks = 3 if c['plan'] == 'three_prefix_9_9' else 2
        self.assertEqual(len(c['job_changes']), 8 + 4 * nblocks + 4)

    def test_duration_change_is_labelled_outside_the_observed_range(self):
        c = sensitivity.construct(CELL['C'], 0)
        self.assertFalse(c['critical']['within_observed_range'])
        self.assertEqual(c['critical']['label'], 'SENSITIVITY_CONSTRUCTION')
        self.assertGreater(c['critical']['modified_duration_ms'],
                           c['critical']['observed_expert_max_ms'])

    def test_observed_envelope_does_not_reach_the_release(self):
        for letter in ('C', 'D'):
            c = sensitivity.construct(CELL[letter], 0)
            self.assertGreater(c['stress_envelope']['model_distance_ms'], 0,
                               'all-maximum costs stay before the release')
            self.assertFalse(c['stress_envelope']['crosses'])

    def test_expert_earlier_but_publication_later_is_not_an_improvement(self):
        c = sensitivity.construct(CELL['C'], 0)
        self.assertIn('E1', c['advanced'])
        self.assertIn('R0/B2', c['delayed'])
        self.assertIn('R0/publish', c['delayed'])
        self.assertTrue(c['anomaly']['is_anomaly'])
        self.assertGreater(c['anomaly']['successor_later_in_pre_ms'], 1.0)
        self.assertNotIn('improvement', c)
        # the construction reports a trade, never a net gain: both lists are non-empty
        self.assertTrue(c['advanced'] and c['delayed'])

    def test_every_construction_keeps_the_lifecycle_legal(self):
        for letter in ('A', 'B', 'C', 'D'):
            for q in range(4):
                c = sensitivity.construct(CELL[letter], q)
                self.assertEqual(c['checks']['pre'], [], (letter, q))
                self.assertEqual(c['checks']['post'], [], (letter, q))
                self.assertTrue(c['checks']['order_flipped'], (letter, q))


class Evaluation(unittest.TestCase):
    def test_evidence_classes_are_not_merged(self):
        audit_payload = env.load(env.OUT / 'BOUNDARY_AUDIT.json')
        replay_payload = env.load(env.OUT / 'REPLAY.json')
        sens_payload = env.load(env.OUT / 'SENSITIVITY.json')
        ev = evaluation.plan_evaluation(RESULT, audit_payload, replay_payload, sens_payload)
        rows = {(r['plan'], r['period_ms']): r for r in ev['rows']}
        two140 = rows[('two_9_9', 140.0)]
        three140 = rows[('three_prefix_9_9', 140.0)]
        self.assertIn('EMPIRICALLY_FEASIBLE', two140['evidence_classes'])
        self.assertIn('INSUFFICIENT_EVIDENCE_FOR_RATE', two140['evidence_classes'])
        self.assertIn('SENSITIVE_TO_CHECKED_CONSTRUCTION', three140['evidence_classes'])
        # the report table must not conflate the two margins for the three-block plan
        self.assertGreater(three140['min_expert_margin_ms'],
                           10 * three140['min_cycle_margin_ms'])
        self.assertAlmostEqual(two140['min_expert_margin_ms'],
                               two140['min_cycle_margin_ms'], places=6)

    def test_corrected_140ms_margin_statement(self):
        """The numbers used in the B8 report correction."""
        mins = {}
        for letter, cell in CELL.items():
            segs = [s for s in RESULT['segments'] if s['cell'] == cell['cell']]
            cyc, exp = [], []
            for s in segs:
                jobs = replay.actual_job_table(s)
                cyc += [j['margin_ms'] for (t, i), j in jobs.items()
                        if t == 'Cycle' and j['margin_ms'] is not None]
                exp += [j['margin_ms'] for (t, i), j in jobs.items()
                        if t == 'Expert' and j['margin_ms'] is not None]
            mins[letter] = (min(cyc), min(exp))
        self.assertAlmostEqual(min(mins['C'][0], mins['D'][0]), 1.934219, places=6)
        self.assertAlmostEqual(max(mins['C'][0], mins['D'][0]), 2.551198, places=6)
        self.assertAlmostEqual(mins['C'][1], 2.551198, places=6)
        self.assertAlmostEqual(mins['D'][1], 24.322046, places=6)


class Fingerprints(unittest.TestCase):
    def test_frozen_inputs_match_and_do_not_change(self):
        before = env.fingerprint_inputs()
        self.assertTrue(all(v['match'] for v in before.values()))
        audit_payload = env.load(env.OUT / 'BOUNDARY_AUDIT.json')
        self.assertEqual(audit_payload['inputs'], before)
        after = env.fingerprint_inputs()
        self.assertEqual(before, after)
        self.assertEqual(env.sha(env.B8_PREDICTION), env.FROZEN_SHA256['b8_prediction_json'])
        self.assertEqual(env.sha(env.B8_RESULT), env.FROZEN_SHA256['b8_result_json'])

    def test_frozen_prediction_is_not_rewritten(self):
        self.assertEqual(PREDICTION['status'], 'EXTRAPOLATIVE_PREDICTION_NOT_VALIDATED')
        self.assertEqual(PREDICTION['condition_status'], 'OUT_OF_SOURCE_APPLICABILITY_DOMAIN')


if __name__ == '__main__':
    unittest.main(verbosity=2)
