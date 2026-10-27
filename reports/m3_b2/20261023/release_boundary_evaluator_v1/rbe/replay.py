"""Condition-specific replay of one plan through the frozen analysis model.

Two entries, never pooled:

``b4``  the frozen r1 costs (B4 r2 source condition).  Re-running it at 140/180
        reproduces the frozen pre-run prediction; it is not new evidence about B8.

``b8``  costs extracted from that cell's own B8 operations.  Using a batch's own
        numbers to explain that batch is retrospective by construction: it is not a
        forward validation and it does not update the frozen prediction.

Both entries drive the copied r1 ``plan_model`` which in turn drives the real
frozen ``m2_executor.VersionedKV``.  Nothing here re-implements the lifecycle.
"""
from __future__ import annotations

import statistics

import costs as cost_mod
import env

BLOCK_ORDER = cost_mod.BLOCK_ORDER
GAP_MS = 0.041
PUBLISH_COST_MS = 0.012


def _evaluate(plan, scenario, period_ms, cycles=env.CYCLES, phase_ms=env.PHASE_MS):
    from evaluator import evaluate
    return evaluate(plan, scenario, policy='b2_boundary', cycles=cycles,
                    period=period_ms, phase=phase_ms, gap_ms=GAP_MS,
                    publish_cost_ms=PUBLISH_COST_MS)


def block_key(block):
    """Raw-record operation key of one predicted block (R{q}/B{index+1})."""
    return 'R%d/B%d' % (block['refresh'], block['block'] + 1)


def _dispatch_order(result):
    rows = []
    for e in result['experts']:
        if e['dispatch_ms'] is not None:
            rows.append((e['dispatch_ms'], 'Expert', e['job_id']))
    for b in result['blocks']:
        if b['start_ms'] is not None:
            rows.append((b['start_ms'], 'ContextBlock', block_key(b)))
    rows.sort()
    return [r[2] for r in rows]


def replay_b4(period_ms, cycles=env.CYCLES):
    """Frozen r1 costs -> analysis model -> plan outcome."""
    b4 = cost_mod.b4_source_costs()
    out = {}
    for plan in ('two_9_9', 'three_prefix_9_9'):
        for kind in ('typical', 'stress'):
            scenario = cost_mod.forecast_scenario(b4, plan, kind)
            r = _evaluate(plan, scenario, period_ms, cycles=cycles)
            out[(plan, kind)] = dict(
                plan=plan, scenario=kind, period_ms=period_ms,
                feasible=r['feasible'], complete=r['complete'], model_status=r['status'],
                min_cycle_margin_ms=r['min_cycle_margin_ms'],
                min_expert_margin_ms=r['min_expert_margin_ms'],
                min_refresh_margin_ms=r['min_refresh_margin_ms'],
                max_refresh_response_ms=r['max_refresh_response_ms'],
                counts=r['counts'], order=_dispatch_order(r),
                experts=r['experts'], blocks=r['blocks'], cycles=r['cycles'],
                refreshes=r['refreshes'], result=r)
    return dict(source='b4', condition=env.CONDITION_LABELS['b4_source'],
                retrospective=False, cells=out)


def replay_b8(measured, cycles=env.CYCLES):
    """B8-measured costs of one cell -> analysis model -> plan outcome."""
    out = {}
    plan = measured['plan']
    period_ms = measured['period_ns'] / 1e6
    for kind in ('typical', 'stress'):
        scenario = cost_mod.b8_scenario(measured, kind)
        r = _evaluate(plan, scenario, period_ms, cycles=cycles)
        out[(plan, kind)] = dict(
            plan=plan, scenario=kind, period_ms=period_ms,
            feasible=r['feasible'], complete=r['complete'], model_status=r['status'],
            min_cycle_margin_ms=r['min_cycle_margin_ms'],
            min_expert_margin_ms=r['min_expert_margin_ms'],
            min_refresh_margin_ms=r['min_refresh_margin_ms'],
            max_refresh_response_ms=r['max_refresh_response_ms'],
            counts=r['counts'], order=_dispatch_order(r),
            experts=r['experts'], blocks=r['blocks'], cycles=r['cycles'],
            refreshes=r['refreshes'], result=r)
    return dict(source='b8', condition=env.CONDITION_LABELS['b8_actual'],
                retrospective=True, cell=measured['cell'], period_ms=period_ms,
                cells=out)


# ------------------------------------------------------------------ comparison

def actual_job_table(segment):
    """Actual job table with blocks renamed to the raw-record operation keys."""
    from validate import actual_jobs
    jobs = actual_jobs(segment)
    if segment['plan'] not in cost_mod.BLOCK_KIND:
        return jobs
    kinds = cost_mod.BLOCK_KIND[segment['plan']]
    keys = cost_mod.BLOCK_KEY[segment['plan']]
    out = {}
    for (jt, jid), value in jobs.items():
        if jt == 'ContextBlock':
            q, label = jid.split('/')
            jid = '%s/%s' % (q, keys[kinds.index(label)])
        out[(jt, jid)] = value
    return out


def compare(replay_cells, segment):
    """Order and completion agreement between one replay and one recorded segment."""
    actual = actual_job_table(segment)
    from audit import actual_order
    order_actual = actual_order(segment)
    out = {}
    for key, rep in replay_cells.items():
        order_pred = rep['order']
        n = min(len(order_actual), len(order_pred))
        common = sum(1 for a, b in zip(order_actual, order_pred) if a == b)
        errs = []
        abs_errs = []
        for jt, jid in sorted(actual):
            a = actual.get((jt, jid))
            p = _pred_job(rep, jt, jid)
            if a is None or p is None or a['completion_ms'] is None or p['completion_ms'] is None:
                continue
            d = p['completion_ms'] - a['completion_ms']
            errs.append(d)
            abs_errs.append(abs(d))
        out[key] = dict(plan=rep['plan'], scenario=rep['scenario'],
                        order_pred=order_pred, order_actual=order_actual,
                        order_match=order_actual == order_pred,
                        order_prefix_match=common, order_len=len(order_actual),
                        completion_signed_mean_ms=_mean(errs),
                        completion_abs_mean_ms=_mean(abs_errs),
                        completion_abs_max_ms=None if not abs_errs else round(max(abs_errs), 6),
                        feasible=rep['feasible'],
                        min_cycle_margin_ms=rep['min_cycle_margin_ms'],
                        min_expert_margin_ms=rep['min_expert_margin_ms'],
                        min_refresh_margin_ms=rep['min_refresh_margin_ms'])
    return out


def _pred_job(rep, jt, jid):
    if jt == 'Expert':
        for e in rep['experts']:
            if e['job_id'] == jid:
                return e
    elif jt == 'ContextBlock':
        for b in rep['blocks']:
            if block_key(b) == jid:
                return b
    elif jt == 'Cycle':
        for c in rep['cycles']:
            if 'cycle%d' % c['cycle'] == jid:
                return dict(completion_ms=c['predicted_completion_ms'],
                            margin_ms=c['predicted_margin_ms'], status=c['status'])
    elif jt == 'Refresh':
        for r in rep['refreshes']:
            if 'refresh%d' % r['id'] == jid:
                return dict(completion_ms=r['completion_offset_ms'],
                            margin_ms=r['refresh_margin_ms'], status=r['status'])
    return None


def _mean(values):
    return None if not values else round(statistics.mean(values), 6)


def order_disagreements(segment, rep):
    """First index where the replay and the record disagree about the next job."""
    from audit import actual_order
    a = actual_order(segment)
    p = rep['order']
    for i in range(min(len(a), len(p))):
        if a[i] != p[i]:
            return dict(index=i, actual=a[i], replay=p[i],
                        actual_head=a[:i + 3], replay_head=p[:i + 3])
    if len(a) != len(p):
        return dict(index=min(len(a), len(p)), actual=None, replay=None,
                    actual_head=a[-3:], replay_head=p[-3:])
    return None
