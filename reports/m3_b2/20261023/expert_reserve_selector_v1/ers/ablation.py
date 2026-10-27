"""Retrospective ablation: F2 / F3 / S0 / S10 at each B8 budget.

F2  fixed two_9_9                 F3  fixed three_prefix_9_9
S0  the frozen rule with RE = 0    S10 the frozen rule with RE = 10 ms

Model side (A): per-condition B8 costs replayed through the same frozen model.
Actual side (B): the recorded B8 trajectory of the corresponding plan.
Comparison (C): whether the model's predicted reserve is met by that trajectory.

The actual side never feeds back into the selection.  When S10 picks the same plan
as a fixed scheme, its performance is that scheme's recorded result and is marked
as reused -- this round contains no selector GPU run.
"""
from __future__ import annotations

import statistics

import common
import rules
import select as select_mod

SCHEME_ORDER = ('F2', 'F3', 'S0', 'S10')


def _scenario_result(rep_cells, plan, kind):
    r = rep_cells[(plan, kind)]
    return dict(complete=r['complete'], model_status=r['model_status'],
                min_cycle_margin_ms=r['min_cycle_margin_ms'],
                min_expert_margin_ms=r['min_expert_margin_ms'],
                min_refresh_margin_ms=r['min_refresh_margin_ms'],
                counts=r['counts'], deferred=len(r['result'].get('deferred') or []),
                refusals=len(r['result'].get('slot_refusals') or []),
                experts=r['experts'], cycles=r['cycles'], refreshes=r['refreshes'],
                blocks=r['blocks'], order=r['order'])


def build_candidates(result, period_ms):
    """Per-candidate evidence from that condition's own B8 cells."""
    measured = common.rbe_costs.b8_measured_costs(result)
    declared = result.get('configuration') or {}
    cells = {}
    missing_global = []
    for plan in common.CANDIDATES:
        try:
            cells[plan] = common.cell_for(measured, plan, period_ms)
        except KeyError:
            missing_global.append('cell:%s@%s' % (plan, period_ms))
    phase = set()
    for plan, cell in cells.items():
        for seg_id in cell['segments']:
            seg = next(s for s in result['segments'] if s['segment_id'] == seg_id)
            if seg['period_ns'] != int(round(period_ms * 1e6)):
                missing_global.append('period:%s' % seg_id)
            phase.add(seg['manifest'].get('phase_ns'))
        if not cell['expert']['n'] or not all(v['n'] for v in cell['blocks'].values()):
            missing_global.append('samples:%s' % plan)
    condition = dict(period_ms=period_ms, phase_ns=sorted(phase) if len(phase) == 1 else None,
                     configuration_label=declared.get('label'),
                     matches_declared=len(phase) == 1,
                     cells={p: cells[p]['cell'] for p in cells},
                     segments={p: list(cells[p]['segments']) for p in cells})

    out = {}
    for plan in common.CANDIDATES:
        if plan not in cells:
            out[plan] = select_mod.summarize_candidate(plan, {}, evidence_ok=False,
                                                       missing=['no cell for %s' % plan])
            continue
        rep = common.rbe_replay.replay_b8(cells[plan])
        scenarios = {kind: _scenario_result(rep['cells'], plan, kind)
                     for kind in common.SCENARIOS}
        missing = list(missing_global)
        lifecycle_ok = all(s['deferred'] == 0 and s['refusals'] == 0
                           for s in scenarios.values())
        out[plan] = select_mod.summarize_candidate(
            plan, scenarios, evidence_ok=not missing, missing=missing,
            lifecycle_ok=lifecycle_ok)
        out[plan]['cell'] = cells[plan]['cell']
        out[plan]['period_ms'] = period_ms
        out[plan]['raw'] = scenarios
        out[plan]['costs'] = dict(
            expert=dict(cells[plan]['expert']),
            blocks={k: dict(v) for k, v in cells[plan]['blocks'].items()},
            stage={k: dict(v) for k, v in cells[plan]['stage'].items()})
        out[plan]['retention'] = _retention(result, cells[plan])
        out[plan]['boundary_costs'] = _boundary_costs(result, cells[plan])
    return out, condition


def _retention(result, cell):
    entries = bytes_ = None
    for seg in result['segments']:
        if seg['segment_id'] in cell['segments']:
            v = seg.get('validation') or {}
            entries = max(entries or 0, v.get('records') or 0)
            bytes_ = max(bytes_ or 0, v.get('payload_B') or 0)
    return dict(entries=entries, payload_B=bytes_,
                note='retention differs by plan by design; it is not a condition mismatch')


def _boundary_costs(result, cell):
    """Already-measured per-operation boundaries: retention envelope and D2D."""
    keys = set(cell['segments'])
    post, pre = [], []
    for seg in result['segments']:
        if seg['segment_id'] not in keys:
            continue
        for op in seg.get('operations') or []:
            if op.get('kind') in ('B1', 'B2', 'P'):
                if op.get('GPU_post_retention_envelope_ms') is not None:
                    post.append(op['GPU_post_retention_envelope_ms'])
                if op.get('GPU_pre_D2D_envelope_ms') is not None:
                    pre.append(op['GPU_pre_D2D_envelope_ms'])
    return dict(block_post_retention_median_ms=_med(post),
                block_pre_d2d_median_ms=_med(pre), n=len(post),
                note='per-block GPU envelopes recorded by B8; not a model input')


def _med(values):
    return None if not values else round(statistics.median(values), 6)


# ------------------------------------------------------------------ actual side

def actual_metrics(result, plan, period_ms, reserve_ms=None):
    """Recorded B8 trajectory of one plan at one budget."""
    reserve = rules.RE_MS if reserve_ms is None else float(reserve_ms)
    measured = common.rbe_costs.b8_measured_costs(result)
    cell = common.cell_for(measured, plan, period_ms)
    segments = [s for s in result['segments'] if s['segment_id'] in cell['segments']]
    out = dict(plan=plan, period_ms=period_ms, reserve_ms=reserve, per_segment=[],
               cycles_pass=0, cycles_total=0, refreshes_pass=0, refreshes_total=0,
               reserve_short=0, reserve_total=0, incomplete=0, uncertain=0,
               jobs=[])
    expert_margins, cycle_margins, refresh_margins = [], [], []
    for seg in segments:
        jobs = common.rbe_replay.actual_job_table(seg)
        stats = seg['statistics']
        cp = sum(1 for c in stats['cycles'] if c['status'] == 'PASS')
        ct = len(stats['cycles'])
        rp = sum(1 for r in stats['refreshes'] if r['status'] == 'PASS')
        rt = len(stats['refreshes'])
        seg_keys = [k for k in jobs if k[0] == 'Expert']
        short = [k[1] for k in seg_keys
                 if jobs[k]['margin_ms'] is not None and jobs[k]['margin_ms'] < reserve]
        seg_inc = (sum(1 for c in stats['cycles'] if c['status'] == 'INCOMPLETE')
                   + sum(1 for r in stats['refreshes'] if r['status'] == 'INCOMPLETE'))
        seg_unc = (sum(1 for c in stats['cycles'] if c['status'] == 'UNCERTAIN')
                   + sum(1 for r in stats['refreshes'] if r['status'] == 'UNCERTAIN'))
        out['per_segment'].append(dict(
            segment_id=seg['segment_id'], cycles_pass=cp, cycles_total=ct,
            refreshes_pass=rp, refreshes_total=rt,
            reserve_short=len(short), reserve_total=len(seg_keys),
            min_cycle_margin_ms=min((jobs[k]['margin_ms'] for k in jobs
                                     if k[0] == 'Cycle' and jobs[k]['margin_ms'] is not None),
                                    default=None),
            min_expert_margin_ms=min((jobs[k]['margin_ms'] for k in seg_keys
                                      if jobs[k]['margin_ms'] is not None), default=None),
            min_refresh_margin_ms=min((jobs[k]['margin_ms'] for k in jobs
                                       if k[0] == 'Refresh'
                                       and jobs[k]['margin_ms'] is not None), default=None)))
        out['cycles_pass'] += cp
        out['cycles_total'] += ct
        out['refreshes_pass'] += rp
        out['refreshes_total'] += rt
        out['reserve_short'] += len(short)
        out['reserve_total'] += len(seg_keys)
        out['incomplete'] += seg_inc
        out['uncertain'] += seg_unc
        for k, j in jobs.items():
            margin = j.get('margin_ms')
            if margin is None:
                continue
            if k[0] == 'Expert':
                expert_margins.append(margin)
            elif k[0] == 'Cycle':
                cycle_margins.append(margin)
            elif k[0] == 'Refresh':
                refresh_margins.append(margin)
            out['jobs'].append(dict(segment_id=seg['segment_id'], job_type=k[0],
                                    job_id=k[1], margin_ms=margin,
                                    status=j['status'],
                                    reserve_short=(k[0] == 'Expert' and margin < reserve)))
    out['min_expert_margin_ms'] = min(expert_margins) if expert_margins else None
    out['min_cycle_margin_ms'] = min(cycle_margins) if cycle_margins else None
    out['min_refresh_margin_ms'] = min(refresh_margins) if refresh_margins else None
    out['official_feasible'] = (out['cycles_pass'] == out['cycles_total']
                                and out['refreshes_pass'] == out['refreshes_total']
                                and out['incomplete'] == 0)
    out['reserve_ok'] = out['reserve_short'] == 0
    out['cell'] = cell['cell']
    return out


def predicted_rows(candidates, plan):
    """Per-Expert predicted margins of one candidate, by scenario."""
    out = {}
    cand = candidates[plan]
    for kind in common.SCENARIOS:
        rows = (cand.get('raw') or {}).get(kind)
        if rows is None:
            continue
        out[kind] = {e['job_id']: e['margin_ms'] for e in rows['experts']}
    return out


def reserve_agreement(candidates, actual, plan, reserve_ms=None):
    """Predicted reserve vs the recorded trajectory, per segment and scenario."""
    reserve = rules.RE_MS if reserve_ms is None else float(reserve_ms)
    pred = predicted_rows(candidates, plan)
    out = []
    for seg_stat in actual['per_segment']:
        seg_id = seg_stat['segment_id']
        for kind, table in pred.items():
            rows = [j for j in actual['jobs']
                    if j['segment_id'] == seg_id and j['job_type'] == 'Expert']
            rows.sort(key=lambda j: int(j['job_id'][1:]))
            pred_fail_actual_ok = 0
            pred_ok_actual_fail = 0
            for j in rows:
                p = table.get(j['job_id'])
                if p is None or j['margin_ms'] is None:
                    continue
                pf = p < reserve
                af = j['margin_ms'] < reserve
                if pf and not af:
                    pred_fail_actual_ok += 1
                if not pf and af:
                    pred_ok_actual_fail += 1
            out.append(dict(segment_id=seg_id, scenario=kind,
                            predicted_short=sum(1 for p in table.values()
                                                if p is not None and p < reserve),
                            actual_short=sum(1 for j in rows
                                             if j['margin_ms'] is not None
                                             and j['margin_ms'] < reserve),
                            predicted_short_actual_ok=pred_fail_actual_ok,
                            predicted_ok_actual_short=pred_ok_actual_fail,
                            denominator=len(rows)))
    return out
