"""Twelve fixed segments and their per-operation costs (no pooling)."""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DAY = HERE.parent
PREV = DAY.parent
sys.path.insert(0, str(DAY / 'credible_plan_selector_v2_r1' / 'cps2'))
sys.path.insert(0, str(PREV / '20261022' / 'empirical_plan_selector_v1_r1' / 'selector'))
import core  # noqa: E402
import plan_model  # noqa: E402

B9 = DAY / 'expert_reserve_validation_b9_v1_r2' / 'gpu_run_01' / 'board_small' / 'model' / 'result.json'
B10 = DAY / 'credible_selector_validation_b10_v1_r1' / 'gpu_run_01' / 'board' / 'run_01' / 'model' / 'result.json'
SEGMENTS = [
    ('B9@140', 'p1_C_p140_two_b2_boundary'), ('B9@140', 'p2_C_p140_two_b2_boundary'),
    ('B9@140', 'p1_D_p140_three_b2_boundary'), ('B9@140', 'p2_D_p140_three_b2_boundary'),
    ('B10@150', 'p1_C_p150_two_b2_boundary'), ('B10@150', 'p2_C_p150_two_b2_boundary'),
    ('B10@150', 'p1_D_p150_three_b2_boundary'), ('B10@150', 'p2_D_p150_three_b2_boundary'),
    ('B10@160', 'p1_A_p160_two_b2_boundary'), ('B10@160', 'p2_A_p160_two_b2_boundary'),
    ('B10@160', 'p1_B_p160_three_b2_boundary'), ('B10@160', 'p2_B_p160_three_b2_boundary'),
]


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def load(tag, sid):
    result = core.load(B9 if tag.startswith('B9') else B10)
    seg = next(s for s in result['segments'] if s['segment_id'] == sid)
    return result, seg


def costs(seg):
    plan = seg['plan']
    out = {}
    for op in seg['operations']:
        k = op['key']
        ms = op['GPU_total_envelope_ms']
        if k.startswith('E'):
            out[('Expert', int(k[1:]))] = ms
        elif k.endswith('/stage'):
            out[('stage', int(k[1:k.index('/')]))] = ms
        elif k.startswith('R'):
            q, b = k[1:].split('/B')
            out[('block', int(q), int(b) - 1)] = ms
    base = plan_model.PLANS[plan].durations
    extra = {}
    eps = 1e-6
    for (kind, *rest), ms in out.items():
        if kind == 'Expert':
            extra[('Expert', rest[0])] = ms - eps
        elif kind == 'stage':
            extra[('stage', rest[0])] = ms - eps
        else:
            extra[('block', rest[0], rest[1])] = ms - base[rest[1]]
    return out, extra


def manifest_geometry(seg):
    return dict(period_ns=seg['period_ns'], phase_ns=seg['manifest']['phase_ns'],
                cycles=seg['manifest']['cycles'], plan=seg['plan'])


def run(plan_name, period_ms, extra, block_priority=False, tail_rule=None):
    plan = plan_model.PLANS[plan_name]
    return core.hooked.simulate(plan, policy='b2_boundary', cycles=8, period=period_ms,
                                phase=15.0, expert=1e-6, stage_first=1e-6, stage_later=1e-6,
                                gap=core.GAP_MS, publish_cost=core.PUBLISH_COST_MS,
                                block_priority=block_priority, tail_rule=tail_rule,
                                extra_ms=lambda k: extra.get(k, 0.0))


def metrics(plan_name, period_ms, r):
    plan = plan_model.PLANS[plan_name]
    experts, units, blocks, cycles, refreshes = {}, {}, {}, [], []
    for ev in r.events:
        if ev['kind'] == 'Expert':
            experts[ev['id']] = ev['end']
        elif ev['kind'] == 'block':
            blocks[(ev['refresh'], ev['block'])] = ev['end']
        elif ev['kind'] == 'publish':
            pass
    pubs = {ev['refresh']: ev['end'] for ev in r.events if ev['kind'] == 'publish'}
    if hasattr(r, 'exact_times'):
        experts = dict(r.exact_times['experts'])
        blocks = dict(r.exact_times['blocks'])
        pubs = dict(r.exact_times['publications'])
    count = len(r.cycles)
    refresh_count = count // 2
    for q in range(refresh_count):
        for gi, group in enumerate(plan.groups):
            vals = [blocks.get((q, b)) for b in group]
            units[(q, gi)] = None if any(v is None for v in vals) else max(vals)
        tail_key = (q, len(plan.groups) - 1)
        # The final obligation includes publication; missing publication is
        # INCOMPLETE, never a fabricated zero completion.
        tail_end = units.get(tail_key)
        units[tail_key] = None if tail_end is None or q not in pubs else max(tail_end, pubs[q])
    for j in range(count):
        rel = j * period_ms + 15.0
        dl = rel + period_ms
        q, gi = j // 2, j % 2
        e = experts.get(j); u = units.get((q, gi))
        pair = None if (e is None or u is None) else max(e, u)
        cycles.append(dict(cycle=j, release=rel, deadline=dl, expert=e, unit=u,
                           response=None if pair is None else pair - rel,
                           status='INCOMPLETE' if pair is None else ('PASS' if pair <= dl else 'FAIL'),
                           expert_margin=None if e is None else dl - e,
                           unit_margin=None if u is None else dl - u,
                           margin=None if pair is None else dl - pair))
    for q in range(refresh_count):
        rel = q * 2 * period_ms
        dl = rel + 2 * period_ms
        end = pubs.get(q)
        refreshes.append(dict(refresh=q, release=rel, deadline=dl, end=end,
                              response=None if end is None else end - rel,
                              margin=None if end is None else dl - end,
                              status='INCOMPLETE' if end is None else ('PASS' if end <= dl else 'FAIL')))
    cyc_fail = sum(1 for c in cycles if c['status'] == 'FAIL')
    cyc_unc = sum(1 for c in cycles if c['status'] == 'INCOMPLETE')
    return dict(plan=plan_name, period_ms=period_ms, cycles=cycles, refreshes=refreshes,
                experts=[dict(id=j, end=experts.get(j),
                              margin=None if experts.get(j) is None else
                              (j * period_ms + 15.0 + period_ms - experts[j])) for j in range(count)],
                cycle_fail=cyc_fail, cycle_unc=cyc_unc,
                refresh_fail=sum(1 for r in refreshes if r['status'] == 'FAIL'),
                expert_fail=sum(1 for e in cycles if e['expert_margin'] is not None and e['expert_margin'] < 0),
                ME=min((c['expert_margin'] for c in cycles if c['expert_margin'] is not None), default=None),
                MU=min((c['unit_margin'] for c in cycles if c['unit_margin'] is not None), default=None),
                MC=min((c['margin'] for c in cycles if c['margin'] is not None), default=None),
                MR=min((r['margin'] for r in refreshes if r['margin'] is not None), default=None),
                worst_cycle_response=max((c['response'] for c in cycles if c['response'] is not None), default=None),
                max_refresh_response=max((r['response'] for r in refreshes if r['response'] is not None), default=None),
                status=r.status, deferred=len(r.deferred), refusals=len(r.slot_refusals),
                complete=(r.status == 'DRAINED' and len(experts) == count and len(pubs) == refresh_count))
