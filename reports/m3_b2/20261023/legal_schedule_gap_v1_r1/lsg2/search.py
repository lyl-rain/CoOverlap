"""Bounded action-level DFS (E/C/I) over the shared state-transition core."""
from __future__ import annotations
import hashlib, json, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'lsg2'))
sys.path.insert(0, str(HERE))
import transition as core  # noqa: E402
import inputs  # noqa: E402
import plan_model  # noqa: E402

NODE_CAP = 100_000
WALL_CAP_S = 10.0


def replay(plan_name, period_ms, extra, prefix, stop):
    it = iter(prefix)

    def pol(state):
        try:
            return next(it)
        except StopIteration:
            return 'STOP' if stop else None
    plan = plan_model.PLANS[plan_name]
    return core.simulate(plan, policy='b2_boundary', cycles=8, period=period_ms,
                         phase=15.0, expert=1e-6, stage_first=1e-6, stage_later=1e-6,
                         gap=0.041, publish_cost=0.012,
                         extra_ms=lambda k: extra.get(k, 0.0),
                         policy_fn=pol)


def state_key(state):
    payload = dict(now=round(state['now'], 6), runnable=state['runnable'],
                   active=state['active'], next_refresh=state['next_refresh'],
                   dispatched=state['dispatched'], pubs=sorted(state['pubs']),
                   next_event=state['next_event'],
                   versions=sorted((k, v) for k, v in state['versions'].items()),
                   readers=sorted((k, v) for k, v in state['readers'].items()))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def evaluate(plan_name, period_ms, extra, prefix, baseline):
    r = replay(plan_name, period_ms, extra, prefix, stop=False)
    m = inputs.metrics(plan_name, period_ms, r)
    return m, r


def search_segment(plan_name, period_ms, extra, baseline, node_cap=NODE_CAP,
                   wall_cap=WALL_CAP_S):
    t0 = time.time()
    stats = dict(nodes_expanded=0, branches_generated=0, terminal_schedules=0,
                 invalid_branches=0, pruned_nodes=0, elapsed_s=0.0, stop_reason=None)
    root = replay(plan_name, period_ms, extra, [], stop=True)
    if root.status != 'STOPPED_FOR_SEARCH':
        stats['stop_reason'] = 'root_not_stopped:%s' % root.status
        return stats, None
    stack = [([], root.search_state)]
    seen = set()
    best = None
    while stack:
        if stats['nodes_expanded'] >= node_cap:
            stats['stop_reason'] = 'NODE_CAP'; break
        if time.time() - t0 >= wall_cap:
            stats['stop_reason'] = 'WALL_CAP'; break
        prefix, state = stack.pop()
        stats['nodes_expanded'] += 1
        key = state_key(state)
        if key in seen:
            stats['pruned_nodes'] += 1
            continue
        seen.add(key)
        for action in state['legal']:
            if stats['nodes_expanded'] >= node_cap:
                stats['stop_reason'] = 'NODE_CAP'; break
            if time.time() - t0 >= wall_cap:
                stats['stop_reason'] = 'WALL_CAP'; break
            child = prefix + [action]
            stats['branches_generated'] += 1
            r = replay(plan_name, period_ms, extra, child, stop=True)
            if r.status == 'STOPPED_FOR_SEARCH':
                stack.append((child, r.search_state))
            elif r.status == 'DRAINED':
                stats['terminal_schedules'] += 1
                m, _ = evaluate(plan_name, period_ms, extra, child, baseline)
                verdict = _improves(baseline, m)
                if verdict:
                    cand = dict(prefix=child, verdict=verdict, metrics=m)
                    if best is None or _better(cand, best):
                        best = cand
            else:
                stats['invalid_branches'] += 1
    stats['elapsed_s'] = round(time.time() - t0, 3)
    if stats['stop_reason'] is None:
        stats['stop_reason'] = 'COMPLETE'
    return stats, best


def _improves(base, cand):
    if not cand['complete']:
        return None
    if (cand['cycle_fail'] < base['cycle_fail']
            and cand['expert_fail'] <= base['expert_fail']
            and cand['refresh_fail'] <= base['refresh_fail']):
        return 'A'
    if (base['cycle_fail'] == 0 and cand['cycle_fail'] == 0
            and cand['worst_cycle_response'] <= base['worst_cycle_response']
            and cand['max_refresh_response'] <= base['max_refresh_response']
            and (cand['worst_cycle_response'] < base['worst_cycle_response']
                 or cand['max_refresh_response'] < base['max_refresh_response'])
            and cand['expert_fail'] == 0):
        return 'B'
    return None


def _better(cand, best):
    a = (cand['metrics']['cycle_fail'], -cand['metrics']['worst_cycle_response'])
    b = (best['metrics']['cycle_fail'], -best['metrics']['worst_cycle_response'])
    return a < b


def first_divergence(prefix, default_actions):
    for i, a in enumerate(prefix):
        if i >= len(default_actions) or a != default_actions[i]:
            return i
    return None


def default_action_trace(plan_name, period_ms, extra):
    """Actions the default policy takes at each decision boundary."""
    trace, prefix = [], []
    while True:
        r = replay(plan_name, period_ms, extra, prefix, stop=True)
        if r.status != 'STOPPED_FOR_SEARCH':
            return trace, r.status
        st = r.search_state
        # emulate default: E if runnable else C if active/refresh else I
        if st['runnable']:
            a = 'E'
        elif st['active'] is not None or st['next_refresh'] < 0 or True:
            a = 'C' if (st['active'] is not None) else ('C' if st['next_refresh'] < 8 else 'I')
        else:
            a = 'I'
        if st['active'] is None and st['next_refresh'] >= 4:
            a = 'I'
        trace.append(a)
        prefix = prefix + [a]
        if len(trace) > 500:
            return trace, 'TRACE_LIMIT'
