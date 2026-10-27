"""Plan selection and nondominance over the two predeclared scenarios."""
from __future__ import annotations

import copy

from evaluator import evaluate

CANDIDATES = ('two_9_9', 'three_prefix_9_9')
POLICY = 'b2_boundary'
TARGET = dict(period_ms=240.0, phase_ms=15.0, cycles=8)


def scenario_for(costs, plan, kind):
    c = costs['candidates'][plan]
    d = copy.deepcopy(c)
    d['kind'] = kind
    # blocks are already {label: {n, median, max}}; evaluator selects kind.
    return d


def margin_vector(result):
    return dict(min_cycle_margin_ms=result.get('min_cycle_margin_ms'),
                min_expert_margin_ms=result.get('min_expert_margin_ms'),
                min_refresh_margin_ms=result.get('min_refresh_margin_ms'),
                max_refresh_ready_ms=result.get('max_refresh_ready_ms'))


def dominates(a, b):
    """a weakly beats b on all three margins and is strictly better on one."""
    if any(a[k] is None or b[k] is None for k in ('min_cycle_margin_ms', 'min_expert_margin_ms', 'min_refresh_margin_ms')):
        return False
    ge = all(a[k] >= b[k] for k in ('min_cycle_margin_ms', 'min_expert_margin_ms', 'min_refresh_margin_ms'))
    gt = any(a[k] > b[k] for k in ('min_cycle_margin_ms', 'min_expert_margin_ms', 'min_refresh_margin_ms'))
    return ge and gt


def select(costs, target=None, rules=None):
    target = target or TARGET
    rules = rules or {}
    if target.get('phase_ms') != 15.0 or target.get('cycles') != 8:
        return dict(status='UNSUPPORTED_INPUT', target=target, candidates={},
                    reason='the frozen selector supports phase=+15 ms and cycles=8 only')
    if target.get('period_ms') == 180.0:
        return dict(status='INSUFFICIENT_EVIDENCE', target=target, candidates={},
                    reason='B4 split evidence is fixed at P=240 ms; B5/B6/B7 are two_9_9-only and cannot supply three-plan 180 ms evidence.',
                    no_evidence_for_three=True)
    if target.get('period_ms') != 240.0:
        return dict(status='UNSUPPORTED_INPUT', target=target, candidates={},
                    reason='no measured two-vs-three split condition at this period')
    missing = [p for p in CANDIDATES if p not in costs.get('candidates', {})]
    if missing:
        return dict(status='INSUFFICIENT_EVIDENCE', target=target, candidates={},
                    reason='missing training costs for: ' + ','.join(missing))
    results = {}
    for plan in CANDIDATES:
        results[plan] = {}
        for kind in ('typical', 'stress'):
            results[plan][kind] = evaluate(plan, scenario_for(costs, plan, kind), policy=POLICY,
                                           cycles=target['cycles'], period=target['period_ms'],
                                           phase=target['phase_ms'],
                                           gap_ms=float(rules.get('model_constants', {}).get('gap_ms', 0.041)),
                                           publish_cost_ms=float(rules.get('model_constants', {}).get('publish_cost_ms', 0.012)))
    feasible = {p: all(results[p][k]['feasible'] for k in ('typical', 'stress')) for p in CANDIDATES}
    # worst-case margin by metric across scenarios
    agg = {}
    for p in CANDIDATES:
        vec = {}
        for key in ('min_cycle_margin_ms', 'min_expert_margin_ms', 'min_refresh_margin_ms'):
            vals = [results[p][k][key] for k in ('typical', 'stress')]
            vec[key] = None if any(v is None for v in vals) else min(vals)
        ready = [results[p][k]['max_refresh_ready_ms'] for k in ('typical', 'stress')]
        vec['max_refresh_ready_ms'] = None if any(v is None for v in ready) else max(ready)
        agg[p] = vec
    serial = {}
    for plan, sc in (costs.get('serial_comparison') or {}).items():
        if not sc:
            continue
        d = copy.deepcopy(sc); d['kind'] = 'typical'
        serial[plan] = evaluate(plan, d, policy='serial_context', cycles=target['cycles'],
                                period=target['period_ms'], phase=target['phase_ms'],
                                gap_ms=float(rules.get('model_constants', {}).get('gap_ms', 0.041)),
                                publish_cost_ms=float(rules.get('model_constants', {}).get('publish_cost_ms', 0.012)))
    if not any(feasible.values()):
        return dict(status='NO_EMPIRICALLY_FEASIBLE_PLAN', target=target, results=results,
                    feasible=feasible, margins=agg, serial_comparison=serial,
                    reason='all declared candidates have an incomplete obligation or a negative empirical margin in at least one scenario')
    feasible_plans = [p for p in CANDIDATES if feasible[p]]
    nondominated = [p for p in feasible_plans
                    if not any(dominates(agg[q], agg[p]) for q in feasible_plans if q != p)]
    return dict(status='EMPIRICALLY_FEASIBLE', target=target, results=results,
                feasible=feasible, margins=agg, serial_comparison=serial, feasible_plans=feasible_plans,
                nondominated=nondominated,
                selected=nondominated if len(nondominated) != 1 else nondominated[:1],
                reason='margins are worst over typical and stress scenarios; no weighted score is used',
                two_is_engineering_default='not proven performance-optimal; retain only as the lower-boundary-count default when evidence does not distinguish')
