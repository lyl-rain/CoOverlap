"""Per-candidate plan evaluation from the audit, replay and sensitivity outputs.

Four evidence classes are kept separate and never merged into one verdict:

``EMPIRICALLY_FEASIBLE``              this batch's recorded cycles/refreshes all passed
``MODEL_FEASIBLE``                    a declared analysis scenario replays as feasible
``SENSITIVE_TO_CHECKED_CONSTRUCTION`` a legal duration change flips a checked order branch
``INSUFFICIENT_EVIDENCE``             the sample cannot support the quantity asked for

Nothing here computes a violation *rate* when no violation was observed, and no
observed maximum is promoted to a bound.
"""
from __future__ import annotations

import costs

PERIODS = (180.0, 140.0)
PLANS = ('two_9_9', 'three_prefix_9_9')

COLUMNS = [
    'plan', 'period_ms', 'cells', 'tail_block',
    'empirical_cycle_pass', 'empirical_cycle_den', 'empirical_refresh_pass',
    'empirical_refresh_den',
    'min_cycle_margin_ms', 'min_cycle_job', 'min_expert_margin_ms', 'min_expert_job',
    'min_refresh_margin_ms', 'min_refresh_job',
    'release_distance_min_ms', 'release_distance_max_ms', 'release_distance_refreshes',
    'tail_dispatched_first', 'order_flip_typical', 'order_flip_stress',
    'b8_self_feasible_typical', 'b8_self_feasible_stress',
    'b8_self_min_cycle_margin_ms', 'b8_self_min_expert_margin_ms',
    'b4_source_feasible_typical', 'b4_source_feasible_stress',
    'b4_source_min_cycle_margin_ms', 'b4_source_min_expert_margin_ms',
    'critical_delta_min_ms', 'critical_delta_max_ms',
    'critical_within_observed', 'stress_envelope_min_ms',
    'successor_advance_ms', 'tail_delay_ms', 'publication_delay_ms',
    'evidence_classes',
]


def plan_evaluation(result, audit_payload, replay_payload, sens_payload):
    from replay import actual_job_table
    cells = {}
    for segment in result['segments']:
        cells.setdefault(segment['cell'], []).append(segment)
    cell_of = {}
    for cell, segs in cells.items():
        cell_of[(segs[0]['plan'], segs[0]['period_ns'] / 1e6)] = cell

    coverage = audit_payload['coverage']
    flips = audit_payload['flips']
    identity = audit_payload['margin_identity']

    rows = []
    for plan in PLANS:
        for period in PERIODS:
            cell = cell_of.get((plan, period))
            if cell is None:
                continue
            rows.append(_one(result, plan, period, cell, cells[cell], coverage, flips,
                             identity, replay_payload, sens_payload, actual_job_table))

    uncovered = [
        dict(item='violation rate / p99 tail',
             status='INSUFFICIENT_EVIDENCE',
             detail='no cycle or refresh violated in any of the 64 cycles / 32 refreshes; '
                    'n=16 cycles per cell cannot support a rate, p99 or p99.9',
             needed='longer or adversarial-budget replay with counted violations'),
        dict(item='version-not-ready at a boundary',
             status='NOT_OBSERVED_IN_B8',
             detail='0 of 176 recorded decision boundaries had a released Expert whose '
                    'version was neither published nor token-bound',
             needed='CPU coverage only (this package); a GPU case would need a publication '
                    'deferral that B8 did not produce'),
        dict(item='completion interval spanning a release',
             status='NOT_OBSERVED_IN_B8',
             detail='0 of 176 boundaries had the release inside the previous operation '
                    'completion interval; the UNCERTAIN_INTERVAL rule is exercised only by '
                    'the CPU suite',
             needed='a boundary closer than the ~10-14 us confirmation cost, or a declared '
                    'coarser completion interval'),
        dict(item='block-duration perturbation',
             status='NOT_CONSTRUCTED',
             detail='constructions change Expert E(2q) duration only; B2/B3 block durations '
                    'were not perturbed because one Plan duration applies to every refresh',
             needed='a per-refresh block-duration model if that path is to be claimed'),
        dict(item='condition mismatch cause',
             status='OPEN_OUT_OF_SCOPE',
             detail='B4 source costs and B8 runtime numeric configuration differ; why the '
                    'Expert envelope is ~3.3 ms shorter in B8 is not explained here',
             needed='a dedicated, approved root-cause batch (not required for this method)'),
        dict(item='independence of segments',
             status='LIMITED',
             detail='each cell has two segments in one process in a fixed order; they are '
                    'not independent repetitions',
             needed='independent process-level repetitions'),
    ]

    return dict(schema='rbe_plan_evaluation_v1',
                status='OFFLINE_PLAN_EVALUATION',
                inputs=audit_payload['inputs'],
                condition=audit_payload['condition'],
                frozen_prediction=audit_payload['frozen_prediction'],
                candidates={p: _candidate_summary(rows, p) for p in PLANS},
                rows=rows, columns=COLUMNS, uncovered=uncovered,
                notes=[
                    'EMPIRICALLY_FEASIBLE is limited to this batch, configuration, phase and '
                    'sample; it is not a boundary, a WCET or a rate',
                    'MODEL_FEASIBLE is an analysis-scenario statement, not a measurement',
                    'SENSITIVE_TO_CHECKED_CONSTRUCTION covers only the constructed duration '
                    'changes, not all branches',
                    'a per-item maximum duration is not a bound on all job responses',
                ])


def _candidate_summary(rows, plan):
    mine = [r for r in rows if r['plan'] == plan]
    return dict(periods=[r['period_ms'] for r in mine],
                by_period={r['period_ms']: r['evidence_classes'] for r in mine},
                min_cycle_margin_ms=min((r['min_cycle_margin_ms'] for r in mine), default=None),
                min_expert_margin_ms=min((r['min_expert_margin_ms'] for r in mine), default=None),
                release_distance_min_ms=min((r['release_distance_min_ms'] for r in mine),
                                            default=None))


def _one(result, plan, period, cell, segments, coverage, flips, identity,
         replay_payload, sens_payload, actual_job_table):
    period_ns = int(period * 1e6)
    seg_ids = {s['segment_id'] for s in segments}

    cycle_pass = cycle_den = refresh_pass = refresh_den = 0
    best = {}
    for segment in segments:
        stats = segment['statistics']
        cycle_pass += sum(1 for c in stats['cycles'] if c['status'] == 'PASS')
        cycle_den += len(stats['cycles'])
        refresh_pass += sum(1 for r in stats['refreshes'] if r['status'] == 'PASS')
        refresh_den += len(stats['refreshes'])
        jobs = actual_job_table(segment)
        for (jt, jid) in jobs:
            j = jobs[(jt, jid)]
            if j.get('margin_ms') is None:
                continue
            cur = best.get(jt)
            if cur is None or j['margin_ms'] < cur['margin_ms']:
                best[jt] = dict(job_id=jid, margin_ms=j['margin_ms'])

    cov = [c for c in coverage if c['segment_id'] in seg_ids]
    dist = [c['actual_distance_ms'] for c in cov if c['actual_distance_ms'] is not None]
    tail_first = sum(1 for c in cov if c['actual_tail_before_expert'])
    flips_t = [f for f in flips if f['segment_id'] in seg_ids and f['scenario'] == 'typical']
    flips_s = [f for f in flips if f['segment_id'] in seg_ids and f['scenario'] == 'stress']

    b8c = replay_payload['b8']['cells'][cell]
    b4p = replay_payload['b4']['periods']['p%d' % int(period)]
    b8t, b8s = b8c['%s/typical' % plan], b8c['%s/stress' % plan]
    b4t, b4s = b4p['%s/typical' % plan], b4p['%s/stress' % plan]
    b8_min_cycle = min(b8t['min_cycle_margin_ms'], b8s['min_cycle_margin_ms'])
    b8_min_expert = min(b8t['min_expert_margin_ms'], b8s['min_expert_margin_ms'])
    b4_min_cycle = min(b4t['min_cycle_margin_ms'], b4s['min_cycle_margin_ms'])
    b4_min_expert = min(b4t['min_expert_margin_ms'], b4s['min_expert_margin_ms'])

    cons = [c for c in sens_payload['constructions']
            if c.get('plan') == plan and c.get('period_ms') == period]
    cons = [c for c in cons if 'critical' in c]
    deltas = [c['critical']['delta_to_release_ms'] for c in cons]
    stress = [c['stress_envelope']['model_distance_ms'] for c in cons]
    within = all(c['critical']['within_observed_range'] for c in cons) if cons else None
    successor = [c['anomaly']['successor_later_in_pre_ms'] for c in cons]
    tail_delay = []
    pub_delay = []
    tail_key = costs.BLOCK_KEY[plan][-1]
    for c in cons:
        for j in c['job_changes']:
            if j['job'] == 'R0/%s' % tail_key:
                tail_delay.append(j['change_ms'])
            if j['job'] == 'R0/publish':
                pub_delay.append(j['change_ms'])

    classes = []
    if cycle_pass == cycle_den and refresh_pass == refresh_den and cycle_den:
        classes.append('EMPIRICALLY_FEASIBLE')
    if b8t['feasible'] and b8s['feasible']:
        classes.append('MODEL_FEASIBLE_B8_SELF_RETROSPECTIVE')
    if b4t['feasible'] and b4s['feasible']:
        classes.append('MODEL_FEASIBLE_B4_SOURCE')
    else:
        classes.append('MODEL_INFEASIBLE_B4_SOURCE')
    if any(c['checks']['order_flipped'] for c in cons):
        classes.append('SENSITIVE_TO_CHECKED_CONSTRUCTION')
    if within is False:
        classes.append('CONSTRUCTION_OUTSIDE_OBSERVED_RANGE')
    if len(cov) and all(c['actual_tail_before_expert'] for c in cov):
        classes.append('ORDER_BRANCH_TAIL_FIRST_AT_EVERY_REFRESH')
    classes.append('INSUFFICIENT_EVIDENCE_FOR_RATE')

    return dict(
        plan=plan, period_ms=period, cells=cell, tail_block=tail_key,
        empirical_cycle_pass=cycle_pass, empirical_cycle_den=cycle_den,
        empirical_refresh_pass=refresh_pass, empirical_refresh_den=refresh_den,
        min_cycle_margin_ms=_min(best, 'Cycle'), min_cycle_job=_job(best, 'Cycle'),
        min_expert_margin_ms=_min(best, 'Expert'), min_expert_job=_job(best, 'Expert'),
        min_refresh_margin_ms=_min(best, 'Refresh'), min_refresh_job=_job(best, 'Refresh'),
        release_distance_min_ms=min(dist) if dist else None,
        release_distance_max_ms=max(dist) if dist else None,
        release_distance_refreshes=len(dist),
        tail_dispatched_first=tail_first,
        order_flip_typical=len(flips_t), order_flip_stress=len(flips_s),
        b8_self_feasible_typical=b8t['feasible'], b8_self_feasible_stress=b8s['feasible'],
        b8_self_min_cycle_margin_ms=b8_min_cycle,
        b8_self_min_expert_margin_ms=b8_min_expert,
        b4_source_feasible_typical=b4t['feasible'], b4_source_feasible_stress=b4s['feasible'],
        b4_source_min_cycle_margin_ms=b4_min_cycle,
        b4_source_min_expert_margin_ms=b4_min_expert,
        critical_delta_min_ms=min(deltas) if deltas else None,
        critical_delta_max_ms=max(deltas) if deltas else None,
        critical_within_observed=within,
        stress_envelope_min_ms=min(stress) if stress else None,
        successor_advance_ms=abs(max(successor)) if successor else None,
        tail_delay_ms=max(tail_delay) if tail_delay else None,
        publication_delay_ms=max(pub_delay) if pub_delay else None,
        evidence_classes='|'.join(classes),
    )


def _min(best, kind):
    return None if kind not in best else best[kind]['margin_ms']


def _job(best, kind):
    return None if kind not in best else best[kind]['job_id']
