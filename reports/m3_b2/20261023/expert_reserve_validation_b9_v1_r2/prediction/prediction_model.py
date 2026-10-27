"""Prediction model shared by the freeze builder and the evaluator's补齐 path.

Given the frozen B8 condition costs and the frozen revision-r1 rule, this builds
the complete per-job pre-run prediction:

  Expert / Context block / Cycle / Refresh  x  typical, stress

with release, deadline, dispatch, completion, response, margin, status and the
time origin of every field.  It never reads a B9 measurement; the only inputs are
the frozen B8 result, the frozen r1 rule/costs and the frozen manifest geometry.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
B9 = HERE.parent
DAY = B9.parent
ERS = DAY / 'expert_reserve_selector_v1_r1' / 'ers'
RBE = DAY / 'release_boundary_evaluator_v1' / 'rbe'
for path in (str(ERS), str(RBE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import ablation            # noqa: E402
import common as ers_common  # noqa: E402
import rules as ers_rules    # noqa: E402
import select as ers_select  # noqa: E402

PHASE_MS = 15.0
GROUPS = {'two_9_9': ((0,), (1,)),
          'three_prefix_9_9': ((0, 1), (2,))}
BLOCKS = {'two_9_9': 2, 'three_prefix_9_9': 3}
ORIGIN = dict(
    t0='segment release origin (the manifest is relative to the segment t0)',
    release='manifest release (relative to t0)',
    dispatch='model dispatch instant (relative to t0)',
    completion='model completion instant (relative to t0); the model has no Host '
               'confirmation term, so this is a GPU-end-plus-gap instant, not a measured bound',
    response='completion - release',
    margin='deadline - completion',
)


def _group_of(plan, block):
    for gi, group in enumerate(GROUPS[plan]):
        if block in group:
            return gi
    raise ValueError('block outside plan: %r' % (block,))


def build_jobs(result, rules_doc, reserve_ms=None):
    """Complete per-job prediction rows for every budget, plan and scenario."""
    reserve = ers_rules.RE_MS if reserve_ms is None else float(reserve_ms)
    rows = []
    for period in ers_common.PERIODS_MS:
        cands, _condition = ablation.build_candidates(result, period)
        for plan in ers_common.CANDIDATES:
            raw_by = cands[plan]['raw']
            blocks = BLOCKS[plan]
            for kind in ers_common.SCENARIOS:
                raw = raw_by[kind]
                cycle_by = {c['cycle']: c for c in raw['cycles']}
                refresh_by = {r['id']: r for r in raw['refreshes']}
                block_by = {(b['refresh'], b['block']): b for b in raw['blocks']}
                for e in raw['experts']:
                    j = int(e['job_id'][1:])
                    rows.append(dict(
                        budget_ms=period, plan=plan, scenario=kind, job_type='Expert',
                        job_id=e['job_id'], release_ms=e['release_ms'],
                        deadline_ms=e['deadline_ms'], dispatch_ms=e['dispatch_ms'],
                        completion_ms=e['completion_ms'],
                        response_ms=(None if e['completion_ms'] is None else
                                     round(e['completion_ms'] - e['release_ms'], 6)),
                        margin_ms=e['margin_ms'],
                        status=('INCOMPLETE' if e['margin_ms'] is None else
                                ('PASS' if e['margin_ms'] >= 0 else 'FAIL')),
                        completion_status=e['status'],
                        version=e['version'],
                        reserve_met=(e['margin_ms'] is not None and e['margin_ms'] >= reserve),
                        deadline_kind='Expert deadline (release + P)'))
                for q in range(4):
                    group_last = len(GROUPS[plan]) - 1
                    for b in range(blocks):
                        key = (q, b)
                        blk = block_by.get(key)
                        gi = _group_of(plan, b)
                        cyc = cycle_by.get(2 * q + gi)
                        completion = None
                        if blk is not None:
                            completion = blk['completion_ms']
                        rows.append(dict(
                            budget_ms=period, plan=plan, scenario=kind,
                            job_type='ContextBlock',
                            job_id='R%d/B%d' % (q, b + 1), refresh=q, block=b,
                            obligation_group=gi,
                            release_ms=q * 2 * period,
                            deadline_ms=(None if cyc is None else cyc['deadline_ms']),
                            dispatch_ms=(None if blk is None else blk['start_ms']),
                            completion_ms=completion,
                            response_ms=(None if completion is None else
                                         round(completion - q * 2 * period, 6)),
                            margin_ms=(None if completion is None or cyc is None else
                                       round(cyc['deadline_ms'] - completion, 6)),
                            status=(None if cyc is None else cyc['status']),
                            deadline_kind='obligation group deadline (cycle %d)' % (2 * q + gi),
                            tail=(b == blocks - 1)))
                for j, cyc in sorted(cycle_by.items()):
                    rows.append(dict(
                        budget_ms=period, plan=plan, scenario=kind, job_type='Cycle',
                        job_id='cycle%d' % j, release_ms=cyc['release_ms'],
                        deadline_ms=cyc['deadline_ms'], dispatch_ms=None,
                        completion_ms=cyc.get('predicted_completion_ms',
                                              cyc.get('completion_ms')),
                        response_ms=cyc.get('response_ms'),
                        margin_ms=cyc.get('predicted_margin_ms', cyc.get('margin_ms')),
                        status=cyc['status'],
                        deadline_kind='cycle deadline (release + P)'))
                for m, ref in sorted(refresh_by.items()):
                    rows.append(dict(
                        budget_ms=period, plan=plan, scenario=kind, job_type='Refresh',
                        job_id='refresh%d' % m, release_ms=ref['release_ms'],
                        deadline_ms=ref['release_ms'] + ref['deadline_ms'],
                        dispatch_ms=None,
                        completion_ms=ref.get('completion_offset_ms'),
                        response_ms=ref.get('refresh_response_ms', ref.get('ready_ms')),
                        margin_ms=ref.get('refresh_margin_ms', ref.get('margin_ms')),
                        status=ref['status'],
                        deadline_kind='refresh deadline (release + 2P)'))
    return rows


def boundary_rows(result, plan, period_ms):
    cands, _ = ablation.build_candidates(result, period_ms)
    rows = []
    for kind in ers_common.SCENARIOS:
        raw = cands[plan]['raw'][kind]
        block_by = {(b['refresh'], b['block']): b for b in raw['blocks']}
        expert_by = {int(e['job_id'][1:]): e for e in raw['experts']}
        nblocks = BLOCKS[plan]
        for q in range(4):
            tail = block_by.get((q, nblocks - 1))
            expert = expert_by.get(2 * q + 1)
            if tail is None or expert is None:
                continue
            decision = min(tail['start_ms'], expert['dispatch_ms'])
            release = (2 * q + 1) * period_ms + PHASE_MS
            rows.append(dict(budget_ms=period_ms, plan=plan, scenario=kind, refresh=q,
                             decision_ms=round(decision, 6), release_ms=release,
                             distance_ms=round(release - decision, 6),
                             chosen=('ContextBlock' if tail['start_ms'] <= expert['dispatch_ms']
                                     else 'Expert'),
                             tail_block='B%d' % nblocks, next_expert='E%d' % (2 * q + 1)))
    return rows


def build(result, rules_doc, costs_doc, config_sha, reserve_ms=None):
    """Full prediction document (schema v2)."""
    reserve = ers_rules.RE_MS if reserve_ms is None else float(reserve_ms)
    pred = dict(
        schema='m3_b9_expert_reserve_prediction_v2',
        protocol=rules_doc.get('protocol') or 'm3_b9_expert_reserve_validation_v1',
        status='PRE_RUN_PREDICTION_FROZEN',
        identity=dict(rule=dict(id=rules_doc['id'], sha256=rules_doc['_sha256'],
                                reserve_ms=reserve, identity=rules_doc['reserve']),
                      costs=dict(path='expert_reserve_selector_v1_r1/COSTS.json',
                                 sha256=costs_doc['_sha256'],
                                 source='B8 own operations, per cell'),
                      b8_result_sha256=ers_common.rbe_env.fingerprint_inputs(
                      )['b8_result_json']['sha256'],
                      note='frozen before B9; the timed window neither evaluates nor changes it'),
        origin=ORIGIN, reserve_ms=reserve,
        budgets={}, jobs=[], boundary=[], order={}, selection={})
    pred['jobs'] = build_jobs(result, rules_doc, reserve)
    for period in ers_common.PERIODS_MS:
        key = 'p%d' % int(period)
        cands, condition = ablation.build_candidates(result, period)
        s0 = ers_select.select(cands, 0.0)
        s10 = ers_select.select(cands, reserve)
        pred['budgets'][key] = dict(
            period_ms=period, condition=condition,
            candidates={p: dict(blocks=cands[p]['blocks'], MC=cands[p]['MC'],
                                ME=cands[p]['ME'], MR=cands[p]['MR'],
                                feasible=cands[p]['feasible'],
                                reserve_ok=cands[p]['reserve_ok'],
                                scenarios={k: dict(MC=v['MC'], ME=v['ME'], MR=v['MR'])
                                           for k, v in cands[p]['scenarios'].items() if v})
                          for p in ers_common.CANDIDATES},
            S0=dict(selected=s0['selected'], status=s0['status'], reason=s0['reason']),
            S10=dict(selected=s10['selected'], status=s10['status'], reason=s10['reason']))
        pred['selection'][key] = dict(
            S0=dict(selected=s0['selected'], status=s0['status'], reserve_ms=0.0),
            S10=dict(selected=s10['selected'], status=s10['status'], reserve_ms=reserve))
        pred['order'][key] = {p: {k: cands[p]['raw'][k]['order']
                                  for k in ers_common.SCENARIOS}
                              for p in ers_common.CANDIDATES}
        for p in ers_common.CANDIDATES:
            pred['boundary'].extend(boundary_rows(result, p, period))
    return pred


def required_job_counts(plan):
    return dict(Expert=8, ContextBlock=4 * BLOCKS[plan], Cycle=8, Refresh=4)


def completeness(pred):
    """Missing / malformed prediction fields, per budget/plan/scenario/job type."""
    problems = []
    if not isinstance(pred, dict):
        return ['prediction is not an object']
    for key in ('schema', 'budgets', 'jobs', 'order'):
        if key not in pred:
            problems.append('missing:' + key)
    jobs = pred.get('jobs') or []
    for period in ers_common.PERIODS_MS:
        for plan in ers_common.CANDIDATES:
            for kind in ers_common.SCENARIOS:
                got = {}
                for row in jobs:
                    if (row.get('budget_ms') == period and row.get('plan') == plan
                            and row.get('scenario') == kind):
                        got[row.get('job_type')] = got.get(row.get('job_type'), 0) + 1
                want = required_job_counts(plan)
                for jt, n in want.items():
                    if got.get(jt, 0) != n:
                        problems.append('jobs:%s/%s/%s %s %d!=%d' % (
                            int(period), plan, kind, jt, got.get(jt, 0), n))
    return problems
