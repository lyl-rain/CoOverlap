"""Evaluate one fixed plan/scenario through the copied revised plan model.

The model drives the frozen B4 VersionedKV.  Block/Expert/stage costs are
operation Event totals from the frozen evidence; stage startup is inserted at
its actual first/later position.  No Event0 correction or subtraction is done.
"""
from __future__ import annotations

import statistics

from plan_model import Plan, simulate

PLAN_LAYOUT = {
    'two_9_9': dict(blocks=(tuple(range(9)), tuple(range(9, 18))),
                    groups=((0,), (1,)), valid_layers=(9, 18), kinds=('B1', 'B2')),
    'three_prefix_9_9': dict(blocks=(('language', 'vision27'), tuple(range(9)),
                                     tuple(range(9, 18))),
                             groups=((0, 1), (2,)), valid_layers=(0, 9, 18),
                             kinds=('P', 'B1', 'B2')),
}
BLOCK_ORDER = {'two_9_9': ('B1', 'B2'), 'three_prefix_9_9': ('P', 'B1', 'B2')}


def build_plan(plan_name, scenario):
    if plan_name not in PLAN_LAYOUT:
        raise ValueError('unsupported plan: %r' % (plan_name,))
    key = 'median' if scenario['kind'] == 'typical' else 'max'
    durations = tuple(float(scenario['blocks'][k][key]) for k in BLOCK_ORDER[plan_name])
    lay = PLAN_LAYOUT[plan_name]
    return Plan(plan_name, durations, lay['blocks'], lay['groups'], lay['valid_layers'], lay['kinds'])


def _scenario_value(d, scenario):
    key = 'median' if scenario['kind'] == 'typical' else 'max'
    return float(d[key])


def evaluate(plan_name, scenario, policy='b2_boundary', cycles=8, period=240.0, phase=15.0,
             gap_ms=0.041, publish_cost_ms=0.012):
    plan = build_plan(plan_name, scenario)
    stage = scenario['stage']
    res = simulate(plan, policy=policy, cycles=cycles, period=period, phase=phase,
                   expert=_scenario_value(scenario['expert'], scenario),
                   stage_first=_scenario_value(stage['first'], scenario),
                   stage_later=_scenario_value(stage['later'], scenario),
                   gap=gap_ms, publish_cost=publish_cost_ms)
    expert_events = {e['id']: e for e in res.events if e['kind'] == 'Expert'}
    block_events = {(e['refresh'], e['block']): e for e in res.events if e['kind'] == 'block'}
    publish_events = {e['refresh']: e for e in res.events if e['kind'] == 'publish'}
    experts = []
    for j in range(cycles):
        release = j * period + phase
        deadline = release + period
        e = expert_events.get(j)
        end = None if e is None else e['end']
        experts.append(dict(job_type='Expert', job_id='E%d' % j, release_ms=round(release, 6),
                            deadline_ms=round(deadline, 6),
                            dispatch_ms=None if e is None else e['start'],
                            completion_ms=end, version=None if e is None else e['version'],
                            margin_ms=None if end is None else round(deadline - end, 6),
                            status='COMPLETE' if e is not None else 'INCOMPLETE',
                            source='plan_model.events'))
    blocks = []
    for q in range(cycles // 2):
        for b in range(len(BLOCK_ORDER[plan_name])):
            e = block_events.get((q, b))
            blocks.append(dict(job_type='ContextBlock', job_id='R%d/%s' % (q, BLOCK_ORDER[plan_name][b]),
                               refresh=q, block=b,
                               start_ms=None if e is None else e['start'],
                               completion_ms=None if e is None else e['end'],
                               status='COMPLETE' if e is not None else 'INCOMPLETE',
                               source='plan_model.events'))
    cycles_out = []
    for c in res.cycles:
        cycles_out.append(dict(c, predicted_completion_ms=(c['release_ms'] + c['response_ms'])
                               if c['response_ms'] is not None else None,
                               predicted_margin_ms=(c['deadline_ms'] - c['release_ms'] - c['response_ms'])
                               if c['response_ms'] is not None else None))
    refreshes = []
    for r in res.refreshes:
        rel = r['id'] * 2 * period
        ready = None if r['ready_ms'] is None else rel + r['ready_ms']
        refreshes.append(dict(r, release_ms=rel, predicted_completion_ms=ready,
                              predicted_margin_ms=None if ready is None else (rel + r['deadline_ms'] - ready)))
    all_expert_margins = [x['margin_ms'] for x in experts if x['margin_ms'] is not None]
    all_cycle_margins = [x['predicted_margin_ms'] for x in cycles_out if x['predicted_margin_ms'] is not None]
    all_refresh_margins = [x['predicted_margin_ms'] for x in refreshes if x['predicted_margin_ms'] is not None]
    complete = (res.status == 'DRAINED' and len(experts) == cycles and len(cycles_out) == cycles
                and len(refreshes) == cycles // 2 and all(x['status'] == 'COMPLETE' for x in experts)
                and all(x['status'] != 'INCOMPLETE' for x in cycles_out)
                and all(x['status'] != 'INCOMPLETE' for x in refreshes))
    feasible = (complete and all(x['status'] == 'PASS' for x in cycles_out)
                and all(x['status'] == 'PASS' for x in refreshes)
                and all(m >= 0 for m in all_expert_margins + all_cycle_margins + all_refresh_margins))
    return dict(plan=plan_name, policy=policy, scenario=scenario['kind'], model=res.summary(),
                status=res.status, complete=complete, feasible=feasible,
                experts=experts, blocks=blocks, cycles=cycles_out, refreshes=refreshes,
                min_expert_margin_ms=None if not all_expert_margins else round(min(all_expert_margins), 6),
                min_cycle_margin_ms=None if not all_cycle_margins else round(min(all_cycle_margins), 6),
                min_refresh_margin_ms=None if not all_refresh_margins else round(min(all_refresh_margins), 6),
                max_refresh_ready_ms=None if not all(r['predicted_completion_ms'] is not None for r in refreshes)
                else round(max(r['predicted_completion_ms'] for r in refreshes), 6),
                counts=res.counts(), deferred=res.deferred, refusals=res.slot_refusals,
                note=res.note)
