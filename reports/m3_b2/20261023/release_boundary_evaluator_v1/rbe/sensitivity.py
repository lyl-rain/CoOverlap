"""Release-crossing sensitivity at a declared legal decision boundary.

At one boundary the competing candidates are the next Expert (id 2q+1) and the
tail Context block of refresh q.  The model dispatches the Expert iff its release
is not after the decision instant.  This module computes how much the preceding
completion path must change for that comparison to land on the other side, and
builds the two executable analysis trajectories on either side of the release
point with a 1 ns mathematical probe.

Only durations of one clearly owned preceding operation (Expert 2q) are changed.
Arrivals, deadlines, workload, block structure, obligation groups, FIFO order,
version binding and publication rules are untouched: every trajectory is driven
through the same frozen ``VersionedKV`` lifecycle by the frozen analysis model.

The 1 ns probe is a mathematical separation, not a platform resolution, a
physical perturbation or a measurable safety margin.
"""
from __future__ import annotations

import copy

import costs as cost_mod
import env

PROBE_MS = 1e-6          # 1 ns expressed in ms
GAP_MS = 0.041
PUBLISH_COST_MS = 0.012
NO_CROSS = 'NO_CROSSING_OBSERVED'


def _plan_obj(plan_name, scenario):
    from evaluator import build_plan
    return build_plan(plan_name, scenario)


def _simulate(plan, period_ms, cycles, expert, stage, delta_job, delta_ms, phase_ms):
    from plan_model import simulate

    def override(j, base):
        return base + delta_ms if j == delta_job else base

    return simulate(plan, policy='b2_boundary', cycles=cycles, period=period_ms,
                    phase=phase_ms, expert=expert,
                    stage_first=stage['first'], stage_later=stage['later'],
                    gap=GAP_MS, publish_cost=PUBLISH_COST_MS, expert_override=override)


def competition_point(res, refresh, nblocks):
    """Decision instant of the boundary where the tail block competes with 2q+1."""
    tail = None
    expert = None
    for e in res.events:
        if e['kind'] == 'block' and e['refresh'] == refresh and e['block'] == nblocks - 1:
            tail = e
        if e['kind'] == 'Expert' and e['id'] == 2 * refresh + 1:
            expert = e
    if tail is None or expert is None:
        raise RuntimeError('boundary not present in the model trajectory')
    first = tail if tail['start'] <= expert['start'] else expert
    return dict(decision_ms=first['start'], first=first['kind'],
                tail_start_ms=tail['start'], expert_start_ms=expert['start'],
                tail_job='R%d/%s' % (refresh, costs_labels(nblocks)[-1]),
                expert_job='E%d' % (2 * refresh + 1))


def costs_labels(nblocks):
    """Operation-key naming of the blocks: the tail is B2 (two) / B3 (three)."""
    return ('B1', 'B2') if nblocks == 2 else ('B1', 'B2', 'B3')


def _snapshot(res, nblocks, period_ms, phase_ms, cycles):
    experts, blocks, pubs, order = {}, {}, {}, []
    for e in sorted(res.events, key=lambda x: x.get('start', x.get('end', 0))):
        if e['kind'] == 'Expert':
            experts[e['id']] = dict(start=e['start'], end=e['end'], version=e['version'])
            order.append(('Expert', 'E%d' % e['id']))
        elif e['kind'] == 'block':
            label = costs_labels(nblocks)[e['block']]
            blocks[(e['refresh'], e['block'])] = dict(start=e['start'], end=e['end'], label=label)
            order.append(('ContextBlock', 'R%d/%s' % (e['refresh'], label)))
        elif e['kind'] == 'publish':
            pubs[e['refresh']] = dict(end=e['end'], version=e['version'])
            order.append(('publish', 'R%d/publish' % e['refresh']))
    cycles_out = {}
    for c in res.cycles:
        cycles_out[c['cycle']] = dict(status=c['status'], response_ms=c['response_ms'],
                                      expert_response_ms=c['expert_response_ms'],
                                      vlm_response_ms=c['vlm_response_ms'])
    refreshes_out = {}
    for r in res.refreshes:
        refreshes_out[r['id']] = dict(status=r['status'], ready_ms=r['ready_ms'],
                                      deadline_ms=r['deadline_ms'])
    expert_margin = {}
    for j, e in experts.items():
        deadline = (j + 1) * period_ms + phase_ms
        expert_margin[j] = round(deadline - e['end'], 6)
    return dict(status=res.status, order=order, experts=experts, blocks=blocks,
                publishes=pubs, cycles=cycles_out, refreshes=refreshes_out,
                expert_margin_ms=expert_margin, deferred=len(res.deferred),
                refusals=len(res.slot_refusals),
                note=res.note, journal=list(res.journal))


def _diff(pre, post, nblocks):
    """Per-job completion change from the pre-release to the post-release branch."""
    rows = []
    for j in sorted(pre['experts']):
        rows.append(dict(job='E%d' % j, kind='Expert',
                         pre_completion_ms=pre['experts'][j]['end'],
                         post_completion_ms=post['experts'][j]['end'],
                         change_ms=round(post['experts'][j]['end'] - pre['experts'][j]['end'], 6),
                         pre_margin_ms=pre['expert_margin_ms'][j],
                         post_margin_ms=post['expert_margin_ms'][j]))
    for key in sorted(pre['blocks']):
        q, b = key
        rows.append(dict(job='R%d/%s' % (q, pre['blocks'][key]['label']), kind='ContextBlock',
                         pre_completion_ms=pre['blocks'][key]['end'],
                         post_completion_ms=post['blocks'][key]['end'],
                         change_ms=round(post['blocks'][key]['end'] - pre['blocks'][key]['end'], 6),
                         pre_margin_ms=None, post_margin_ms=None))
    for q in sorted(pre['publishes']):
        rows.append(dict(job='R%d/publish' % q, kind='Refresh',
                         pre_completion_ms=pre['publishes'][q]['end'],
                         post_completion_ms=post['publishes'][q]['end'],
                         change_ms=round(post['publishes'][q]['end'] - pre['publishes'][q]['end'], 6),
                         pre_margin_ms=pre['refreshes'][q]['deadline_ms'] - pre['refreshes'][q]['ready_ms'],
                         post_margin_ms=post['refreshes'][q]['deadline_ms'] - post['refreshes'][q]['ready_ms']))
    return rows


def _cycle_diff(pre, post):
    rows = []
    for c in sorted(pre['cycles']):
        rows.append(dict(cycle=c, pre_status=pre['cycles'][c]['status'],
                         post_status=post['cycles'][c]['status'],
                         pre_response_ms=pre['cycles'][c]['response_ms'],
                         post_response_ms=post['cycles'][c]['response_ms'],
                         change_ms=round(post['cycles'][c]['response_ms']
                                         - pre['cycles'][c]['response_ms'], 6)))
    return rows


def _checks(view, nblocks, cycles):
    problems = []
    if view['status'] != 'DRAINED':
        problems.append('model status %r' % view['status'])
    if len(view['experts']) != cycles:
        problems.append('expert count %d' % len(view['experts']))
    if len(view['blocks']) != (cycles // 2) * nblocks:
        problems.append('block count %d' % len(view['blocks']))
    if len(view['publishes']) != cycles // 2:
        problems.append('publish count %d' % len(view['publishes']))
    if view['deferred']:
        problems.append('deferred publications %d' % view['deferred'])
    if view['refusals']:
        problems.append('refused slot reclaims %d' % view['refusals'])
    for q in range(cycles // 2):
        for b in range(nblocks):
            if (q, b) not in view['blocks']:
                problems.append('missing block R%d/%d' % (q, b))
    binds = {(row[0], row[1]) for row in view['journal'] if row and row[0] == 'bind'}
    missing = [j for j in range(cycles) if ('bind', 'E%d' % j) not in binds]
    if missing:
        problems.append('missing bind for E%s' % (','.join(map(str, missing))))
    if sum(1 for row in view['journal'] if row and row[0] == 'expert_done') != cycles:
        problems.append('expert_done journal count')
    if sum(1 for row in view['journal'] if row and row[0] == 'publish') != cycles // 2 + 1:
        problems.append('publish journal count')  # +1 for the pre-window bootstrap version
    return problems


def _order(res, nblocks):
    labels = costs_labels(nblocks)
    out = []
    for e in res.events:
        if e['kind'] == 'Expert':
            out.append('E%d' % e['id'])
        elif e['kind'] == 'block':
            out.append('R%d/%s' % (e['refresh'], labels[e['block']]))
    return out


def _tail_first(res, refresh, nblocks):
    order = _order(res, nblocks)
    tail = 'R%d/%s' % (refresh, costs_labels(nblocks)[-1])
    expert = 'E%d' % (2 * refresh + 1)
    if tail not in order or expert not in order:
        raise RuntimeError('competing pair not both dispatched')
    return order.index(tail) < order.index(expert)


def _threshold(plan, period_ms, cycles, expert_ms, stage, delta_job, start_delta,
               phase_ms, refresh, nblocks):
    """Bisect the duration change at which the dispatch order flips.

    The model prints event times rounded to 1 us, which is coarser than the 1 ns
    probe; the *order* of dispatched operations is exact, so it is used as the
    oracle instead of a printed timestamp.
    """
    def tail_first(delta):
        res = _simulate(plan, period_ms, cycles, expert_ms, stage, delta_job, delta, phase_ms)
        return _tail_first(res, refresh, nblocks)

    lo, hi = start_delta - 1.0, start_delta + 1.0
    f_lo, f_hi = tail_first(lo), tail_first(hi)
    if f_lo == f_hi:
        raise RuntimeError('order does not respond to the declared duration change')
    if f_lo is not True:
        raise RuntimeError('bisection invariant broken: tail-first expected below threshold')
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if tail_first(mid):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def construct(measured, refresh, period_ms=None, cycles=env.CYCLES, phase_ms=env.PHASE_MS):
    """Two executable branches either side of the next Expert release."""
    plan_name = measured['plan']
    period_ms = measured['period_ns'] / 1e6 if period_ms is None else period_ms
    release_ms = (2 * refresh + 1) * period_ms + phase_ms
    delta_job = 2 * refresh
    base_scenario = cost_mod.b8_scenario(measured, 'typical')
    plan = _plan_obj(plan_name, base_scenario)
    nblocks = len(plan)
    stage = {k: base_scenario['stage'][k]['median'] for k in ('first', 'later')}
    base_expert = base_scenario['expert']['median']

    base = _simulate(plan, period_ms, cycles, base_expert, stage, delta_job, 0.0, phase_ms)
    point = competition_point(base, refresh, nblocks)
    start_delta = release_ms - point['decision_ms']
    theta = _threshold(plan, period_ms, cycles, base_expert, stage, delta_job, start_delta,
                       phase_ms, refresh, nblocks)

    # the same boundary with every operation at its B8-observed maximum: does the
    # condition's own envelope reach the release at all?
    stress_scenario = cost_mod.b8_scenario(measured, 'stress')
    stress_stage = {k: stress_scenario['stage'][k]['max'] for k in ('first', 'later')}
    stress_plan = _plan_obj(plan_name, stress_scenario)
    stress_res = _simulate(stress_plan, period_ms, cycles,
                           stress_scenario['expert']['max'], stress_stage, delta_job, 0.0, phase_ms)
    stress_point = competition_point(stress_res, refresh, nblocks)
    stress_theta = release_ms - stress_point['decision_ms']

    pre_delta = round(theta - PROBE_MS, 9)
    post_delta = round(theta + PROBE_MS, 9)
    pre = _simulate(plan, period_ms, cycles, base_expert, stage, delta_job, pre_delta, phase_ms)
    post = _simulate(plan, period_ms, cycles, base_expert, stage, delta_job, post_delta, phase_ms)
    pre_view = _snapshot(pre, nblocks, period_ms, phase_ms, cycles)
    post_view = _snapshot(post, nblocks, period_ms, phase_ms, cycles)
    pre_tail = _tail_first(pre, refresh, nblocks)
    post_tail = _tail_first(post, refresh, nblocks)
    observed = cost_mod.observed_expert_range(measured)
    modified = base_expert + theta

    out = dict(
        cell=measured['cell'], plan=plan_name, period_ms=period_ms, refresh=refresh,
        boundary=dict(key='after:%s' % ('E%d' % (2 * refresh) if nblocks == 2
                                        else 'R%d/B1' % refresh),
                      competitors=[point['expert_job'], point['tail_job']],
                      release_ms=release_ms,
                      release_rule='release(Expert 2q+1) = (2q+1)*P + phase; equals deadline(Expert 2q)'),
        base=dict(source='B8_MEASURED_TYPICAL (this cell, retrospective)',
                  expert_ms=base_expert, stage_ms=stage,
                  blocks_ms={k: base_scenario['blocks'][k]['median']
                             for k in cost_mod.BLOCK_ORDER[plan_name]},
                  model_decision_ms=round(release_ms - theta, 6),
                  model_first=point['first'],
                  model_distance_ms=round(theta, 9),
                  model_decision_rounded_ms=point['decision_ms']),
        stress_envelope=dict(source='B8_MEASURED_MAX (this cell, retrospective)',
                             expert_ms=stress_scenario['expert']['max'],
                             model_decision_ms=round(release_ms - stress_theta, 6),
                             model_distance_ms=round(stress_theta, 9),
                             crosses=(stress_theta <= 0)),
        critical=dict(delta_to_release_ms=round(theta, 9),
                      direction=('delay' if theta > 0 else 'shorten'),
                      perturbed='Expert E%d duration' % delta_job,
                      base_duration_ms=base_expert,
                      modified_duration_ms=round(modified, 6),
                      observed_expert_min_ms=observed['min'],
                      observed_expert_max_ms=observed['max'],
                      observed_expert_n=observed['n'],
                      within_observed_range=bool(observed['min'] <= modified <= observed['max']),
                      label=('WITHIN_OBSERVED_RANGE' if observed['min'] <= modified
                             <= observed['max'] else 'SENSITIVITY_CONSTRUCTION'),
                      probe_ns=1,
                      probe_note='1 ns is a mathematical separation only: not a platform '
                                 'resolution, a physical perturbation or a safety margin',
                      threshold_method='order-oracle bisection; model event times are '
                                       'printed rounded to 1 us, so the 1 ns probe is below '
                                       'the printable timestamp resolution'),
        branches=dict(
            pre=dict(delta_ms=pre_delta, decision_ms=round(release_ms - PROBE_MS, 9),
                     distance_ms=PROBE_MS, tail_block_first=pre_tail),
            post=dict(delta_ms=post_delta, decision_ms=round(release_ms + PROBE_MS, 9),
                      distance_ms=-PROBE_MS, tail_block_first=post_tail)),
        outcomes=dict(pre=pre_view, post=post_view),
        job_changes=_diff(pre_view, post_view, nblocks),
        cycle_changes=_cycle_diff(pre_view, post_view),
        checks=dict(pre=_checks(pre_view, nblocks, cycles),
                    post=_checks(post_view, nblocks, cycles),
                    order_flipped=pre_tail != post_tail,
                    releases_unchanged=True,
                    deadlines_unchanged=True,
                    workload_unchanged=(len(pre_view['blocks']) == len(post_view['blocks'])
                                        and len(pre_view['experts']) == len(post_view['experts']))),
    )
    out['advanced'] = [r['job'] for r in out['job_changes'] if r['change_ms'] < 0]
    out['delayed'] = [r['job'] for r in out['job_changes'] if r['change_ms'] > 0]
    # the analysis-model scheduling anomaly: a shorter predecessor delays its successor
    successor = out['job_changes'][delta_job + 1]
    predecessor = out['job_changes'][delta_job]
    # the predecessor difference is exact by construction (the two branches differ by
    # 2 ns); the successor difference is real and far above the 1 us print resolution
    shorter = round(abs(out['branches']['post']['delta_ms']
                        - out['branches']['pre']['delta_ms']), 9)
    later = round(successor['pre_completion_ms'] - successor['post_completion_ms'], 6)
    out['anomaly'] = dict(
        predecessor='E%d' % delta_job, successor='E%d' % (delta_job + 1),
        predecessor_shorter_in_pre_ms=shorter,
        successor_later_in_pre_ms=later,
        is_anomaly=bool(shorter > 0 and later > 0),
        scope='legal same-condition analysis construction only; not a B4-vs-B8 causal claim')
    return out


def record_critical(rows):
    """Every observed competition boundary: the change needed to reach the release."""
    out = []
    for r in rows:
        if not r['competition'] or r['distance_decision_ms'] is None:
            continue
        d = r['distance_decision_ms']
        out.append(dict(
            side=r['side'], segment_id=r['segment_id'], cell=r['cell'], plan=r['plan'],
            period_ms=r['period_ms'], refresh=r['refresh'], boundary_key=r['boundary_key'],
            decision_ms=r['decision_ms'], release_ms=r['next_expert_release_ms'],
            distance_ms=d,
            crosses_by_ms=max(0.0, -d), short_by_ms=max(0.0, d),
            direction=('delay' if d > 0 else 'shorten'),
            chosen_job=r['chosen_job'], competing_job=r['competing_job'],
            flip_observed=None))
    return out
