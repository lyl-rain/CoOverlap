"""Bounded E/C/I prefix-tree DFS. No state merging or pruning (r2).

Distinct histories are intentionally retained even when their future-ready
states agree: accumulated deadline and worst-response objectives can differ.
"""
from __future__ import annotations
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'gap'))
sys.path.insert(0, str(HERE / 'lsg2'))
import inputs  # imports the frozen environment before transition
import transition as core
import plan_model

NODE_CAP = 100_000
WALL_CAP_S = 10.0


class SearchDeadline(Exception):
    """Cooperative deadline reached inside a prefix replay."""


def replay(plan_name, period_ms, extra, prefix, stop, cycles=8, budget_check=None):
    it = iter(prefix)

    def pol(state):
        return next(it, 'STOP' if stop else None)

    return core.simulate(plan_model.PLANS[plan_name], policy='b2_boundary',
                         cycles=cycles, period=period_ms, phase=15.0,
                         expert=1e-6, stage_first=1e-6, stage_later=1e-6,
                         gap=0.041, publish_cost=0.012,
                         extra_ms=lambda k: extra.get(k, 0.0),
                         policy_fn=pol, budget_check=budget_check)


def legacy_state_key(state):
    """r1's UNSAFE key, retained solely to reproduce the regression.

    Not called by search_segment. Does not establish state equivalence.
    """
    payload = dict(now=round(state['now'], 6), runnable=state['runnable'],
                   active=state['active'], next_refresh=state['next_refresh'],
                   dispatched=state['dispatched'], pubs=sorted(state['pubs']),
                   next_event=state['next_event'],
                   versions=sorted(state['versions'].items()),
                   readers=sorted(state['readers'].items()))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def search_segment(plan_name, period_ms, extra, baseline, node_cap=NODE_CAP,
                   wall_cap=WALL_CAP_S, cycles=8, clock=time.monotonic):
    if node_cap < 0 or wall_cap < 0:
        raise ValueError('negative search budget')
    started = clock()
    deadline = started + wall_cap
    stats = dict(nodes_expanded=0, branches_generated=0, terminal_schedules=0,
                 invalid_branches=0, invalid_reasons={}, invalid_examples=[],
                 pruned_nodes=0, elapsed_s=0.0, stop_reason=None,
                 replay_calls=0, interrupted_replays=0, pending_prefixes=0,
                 improvement_schedules=0, memoization='DISABLED',
                 timing_clock='monotonic', node_cap=node_cap, wall_cap_s=wall_cap)
    stack = [()]
    best = None

    def check():
        if clock() >= deadline:
            raise SearchDeadline()

    # Nodes count decision states actually expanded. Terminal/invalid replays
    # are counted separately. Every replay is charged to this same deadline.
    while stack:
        if stats['nodes_expanded'] >= node_cap:
            stats['stop_reason'] = 'NODE_CAP'
            break
        prefix = stack.pop()
        try:
            check()
            stats['replay_calls'] += 1
            r = replay(plan_name, period_ms, extra, prefix, stop=True,
                       cycles=cycles, budget_check=check)
            check()
            if r.status == 'STOPPED_FOR_SEARCH':
                legal = tuple(r.search_state['legal'])
                stats['nodes_expanded'] += 1
                stats['branches_generated'] += len(legal)
                # E then C then I, deterministic traversal, no branch omitted.
                stack.extend(prefix + (a,) for a in reversed(legal))
                if not legal:
                    stats['invalid_branches'] += 1
                    stats['invalid_reasons']['NO_LEGAL_ACTION'] = stats['invalid_reasons'].get('NO_LEGAL_ACTION', 0) + 1
            elif r.status == 'DRAINED':
                stats['terminal_schedules'] += 1
                # Evaluate this exact replay, never append a default-policy tail.
                m = inputs.metrics(plan_name, period_ms, r)
                verdict = _improves(baseline, m)
                if verdict:
                    stats['improvement_schedules'] += 1
                    cand = dict(prefix=list(prefix), verdict=verdict, metrics=m)
                    if best is None or _better(cand, best):
                        best = cand
            else:
                stats['invalid_branches'] += 1
                stats['invalid_reasons'][r.status] = stats['invalid_reasons'].get(r.status, 0) + 1
                if len(stats['invalid_examples']) < 8:
                    stats['invalid_examples'].append(dict(status=r.status, note=r.note,
                                                          prefix=list(prefix)))
            check()
        except SearchDeadline:
            # Even a returned-but-not-fully-accounted prefix stays unresolved.
            stack.append(prefix)
            stats['interrupted_replays'] += 1
            stats['stop_reason'] = 'WALL_CAP'
            break
    stats['pending_prefixes'] = len(stack)
    stats['elapsed_s'] = clock() - started
    stats['stop_reason'] = stats['stop_reason'] or 'COMPLETE'
    return stats, best


def _improves(base, cand):
    if not cand['complete']:
        return None
    if (cand['cycle_fail'] < base['cycle_fail']
            and cand['expert_fail'] <= base['expert_fail']
            and cand['refresh_fail'] <= base['refresh_fail']):
        return 'A'
    if (cand['cycle_fail'] == 0 and cand['expert_fail'] == 0
            and cand['refresh_fail'] == 0
            and cand['worst_cycle_response'] <= base['worst_cycle_response']
            and cand['max_refresh_response'] <= base['max_refresh_response']
            and (cand['worst_cycle_response'] < base['worst_cycle_response']
                 or cand['max_refresh_response'] < base['max_refresh_response'])):
        return 'B'
    return None


def _better(cand, best):
    keys = ('cycle_fail', 'expert_fail', 'refresh_fail',
            'worst_cycle_response', 'max_refresh_response')
    return tuple(cand['metrics'][k] for k in keys) < tuple(best['metrics'][k] for k in keys)


def first_divergence(prefix, default_actions):
    for i, a in enumerate(prefix):
        if i >= len(default_actions) or a != default_actions[i]:
            return i
    return None


def default_action_trace(plan_name, period_ms, extra, cycles=8):
    trace = []

    def observe(state):
        legal = state['legal']
        trace.append(next((a for a in ('E', 'C', 'I') if a in legal), 'NO_ACTION'))
        return None  # actually execute the shared default branch

    r = core.simulate(plan_model.PLANS[plan_name], policy='b2_boundary',
                      cycles=cycles, period=period_ms, phase=15.0,
                      expert=1e-6, stage_first=1e-6, stage_later=1e-6,
                      gap=0.041, publish_cost=0.012,
                      extra_ms=lambda k: extra.get(k, 0.0), policy_fn=observe)
    return trace, r.status
