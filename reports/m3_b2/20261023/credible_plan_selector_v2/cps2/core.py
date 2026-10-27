"""credible_plan_selector_v2 core: costs, trajectories, gates, selection, perturbation.

Time definitions come from the frozen manifest conventions (same as the B9 entry):
    Expert j      release = j*P + 15 ms      deadline = release + P
    Cycle j       same release/deadline as Expert j
    Refresh q     release = 2*q*P            deadline = release + 2*P
    three-block group 0 = {block 0, block 1} = prefix + Encoder0-8 (unit (q,0))
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DAY = HERE.parent
PROJECT = DAY.parents[2]
RBE = DAY / 'release_boundary_evaluator_v1'
PREV = DAY.parent
R1 = PREV / '20261022' / 'empirical_plan_selector_v1_r1' / 'selector'
for p in (str(RBE / 'rbe'), str(R1), str(HERE / 'cps2')):
    if p not in sys.path:
        sys.path.insert(0, p)

import env as rbe_env            # noqa: E402
rbe_env.prepare_imports()
import costs as rbe_costs        # noqa: E402
import evaluator                 # noqa: E402
import plan_model                # noqa: E402
import model as hooked           # noqa: E402

PHASE_MS = 15.0
GAP_MS = 0.041
PUBLISH_COST_MS = 0.012
CYCLES = 8
BLOCKS = {p.name: len(p.durations) for p in plan_model.PLANS.values()}
BLOCK_LABELS = {p.name: rbe_costs.BLOCK_ORDER[p.name] for p in plan_model.PLANS.values()}
CANDIDATES = ('two_9_9', 'three_prefix_9_9')
RE_MS = 10.0
RU_MS = 10.0
DELTA_MS = 3.5
B10_BUDGETS = (160.0, 150.0)
B9_BUDGETS = (180.0, 140.0)

B9_RESULT = DAY / 'expert_reserve_validation_b9_v1_r2' / 'gpu_run_01' / 'board_small' / 'model' / 'result.json'
B8_RESULT = PREV / '20261022' / 'split_budget_challenge_b8_v1' / 'gpu_run_01' / 'board' / 'run_01' / 'model' / 'result.json'


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


# ------------------------------------------------------------------ costs
def measured_cells(result):
    """Per (plan, period) cost cell from a recorded batch (B8 or B9)."""
    raw = rbe_costs.b8_measured_costs(result)['cells']
    out = {}
    for cell in raw.values():
        key = (cell['plan'], cell['period_ns'] / 1e6)
        out[key] = cell
    return out


def scenario(cell, kind):
    if kind not in ('typical', 'stress'):
        raise ValueError(kind)
    return rbe_costs.b8_scenario(cell, kind)


# ------------------------------------------------------------- trajectory
def traj(plan_name, scen, period_ms, extra_ms=None):
    plan = plan_model.PLANS[plan_name]
    blocks = {lab: (scen['blocks'][lab]['median'] if scen['kind'] == 'typical'
                    else scen['blocks'][lab]['max']) for lab in BLOCK_LABELS[plan_name]}
    dur = tuple(blocks[lab] for lab in BLOCK_LABELS[plan_name])
    plan2 = plan_model.Plan(plan_name, dur, plan.blocks, plan.groups, plan.valid_layers, plan.kinds)
    expert = scen['expert']['median'] if scen['kind'] == 'typical' else scen['expert']['max']
    stage = scen['stage']
    sf = stage['first']['median'] if scen['kind'] == 'typical' else stage['first']['max']
    sl = stage['later']['median'] if scen['kind'] == 'typical' else stage['later']['max']
    r = hooked.simulate(plan2, policy='b2_boundary', cycles=CYCLES, period=period_ms,
                        phase=PHASE_MS, expert=expert, stage_first=sf, stage_later=sl,
                        gap=GAP_MS, publish_cost=PUBLISH_COST_MS, extra_ms=extra_ms)
    return build_view(plan_name, plan, period_ms, r)


def build_view(plan_name, plan, period_ms, r):
    experts, blocks, units, cycles, refreshes = [], {}, {}, [], []
    for j in range(CYCLES):
        rel = j * period_ms + PHASE_MS
        dl = rel + period_ms
        e = next((x for x in r.events if x['kind'] == 'Expert' and x['id'] == j), None)
        end = None if e is None else e['end']
        experts.append(dict(job_id='E%d' % j, release_ms=rel, deadline_ms=dl,
                            completion_ms=end,
                            margin_ms=None if end is None else round(dl - end, 6),
                            status='COMPLETE' if end is not None else 'INCOMPLETE'))
    for ev in r.events:
        if ev['kind'] == 'block':
            blocks[(ev['refresh'], ev['block'])] = ev['end']
    for q in range(CYCLES // 2):
        for gi, group in enumerate(plan.groups):
            vals = [blocks.get((q, b)) for b in group]
            units[(q, gi)] = None if any(v is None for v in vals) else max(vals)
        tail_gi = len(plan.groups) - 1
        pub = next((x for x in r.events if x['kind'] == 'publish' and x['refresh'] == q), None)
        if pub is not None:
            base = units.get((q, tail_gi))
            units[(q, tail_gi)] = pub['end'] if base is None else max(base, pub['end'])
    for j in range(CYCLES):
        q, gi = j // 2, j % 2
        rel, dl = experts[j]['release_ms'], experts[j]['deadline_ms']
        e = experts[j]['completion_ms']
        u = units.get((q, gi))
        pair = None if (e is None or u is None) else max(e, u)
        cycles.append(dict(job_id='cycle%d' % j, cycle=j, release_ms=rel, deadline_ms=dl,
                           expert_completion_ms=e, unit_completion_ms=u,
                           completion_ms=pair,
                           margin_ms=None if pair is None else round(dl - pair, 6),
                           expert_margin_ms=None if e is None else round(dl - e, 6),
                           unit_margin_ms=None if u is None else round(dl - u, 6),
                           status='INCOMPLETE' if pair is None else ('PASS' if pair <= dl else 'FAIL')))
    for q in range(CYCLES // 2):
        rel = q * 2 * period_ms
        dl = rel + 2 * period_ms
        pub = next((x for x in r.events if x['kind'] == 'publish' and x['refresh'] == q), None)
        end = None if pub is None else pub['end']
        refreshes.append(dict(job_id='refresh%d' % q, release_ms=rel, deadline_ms=dl,
                              completion_ms=end,
                              margin_ms=None if end is None else round(dl - end, 6),
                              status='INCOMPLETE' if end is None else
                              ('PASS' if end <= dl else 'FAIL')))
    order = []
    for ev in sorted([x for x in r.events if x['kind'] in ('Expert', 'block')],
                     key=lambda x: (x.get('start', x['end']), x['kind'])):
        order.append('E%d' % ev['id'] if ev['kind'] == 'Expert'
                     else 'R%d/B%d' % (ev['refresh'], ev['block'] + 1))
    m = dict(
        ME=min([x['margin_ms'] for x in experts if x['margin_ms'] is not None], default=None),
        MU=min([x['unit_margin_ms'] for x in cycles if x['unit_margin_ms'] is not None], default=None),
        MC=min([x['margin_ms'] for x in cycles if x['margin_ms'] is not None], default=None),
        MR=min([x['margin_ms'] for x in refreshes if x['margin_ms'] is not None], default=None))
    incomplete = sum(1 for x in experts + cycles + refreshes if x['status'] == 'INCOMPLETE')
    return dict(plan=plan_name, period_ms=period_ms, status=r.status,
                complete=(incomplete == 0 and r.status in ('DRAINED',)),
                experts=experts, blocks={'R%d/B%d' % (q, b + 1): v
                                         for (q, b), v in blocks.items()},
                units={'R%d/U%d' % (q, gi): v for (q, gi), v in units.items()},
                cycles=cycles, refreshes=refreshes, order=order, margins=m,
                deferred=len(r.deferred), refusals=len(r.slot_refusals),
                incomplete=incomplete)


def margin_state(value, reserve=None):
    if value is None:
        return 'MISSING'
    if reserve is None:
        return 'CONFIRMED_OK' if value >= 0 else 'CONFIRMED_SHORT'
    return 'CONFIRMED_OK' if value >= reserve else ('CONFIRMED_SHORT' if value < reserve else 'UNKNOWN')


def gates(view, source, scenario_kind=None):
    """G1 official, G2 reserve (Expert + VLM). Returns per-gate verdicts."""
    m = view['margins']
    official = (view['complete'] and view['status'] == 'DRAINED' and view['deferred'] == 0
                and view['refusals'] == 0 and view['incomplete'] == 0
                and all(m[k] is not None and m[k] >= 0 for k in ('ME', 'MU', 'MC', 'MR')))
    me_ok = m['ME'] is not None and m['ME'] >= RE_MS
    mu_ok = m['MU'] is not None and m['MU'] >= RU_MS
    return dict(source=source, scenario=scenario_kind,
                G1=dict(pass_=official, margins=dict(m)),
                G2=dict(pass_=(me_ok and mu_ok), ME_ok=me_ok, MU_ok=mu_ok,
                        reason=('expert reserve short' if not me_ok else
                                ('vlm reserve short' if not mu_ok else None))))


def perturbation_keys(view):
    keys = [('stage', q) for q in range(CYCLES // 2)]
    keys += [('block', q, b) for q in range(CYCLES // 2) for b in range(BLOCKS[view['plan']])]
    keys += [('Expert', j) for j in range(CYCLES)]
    return keys


def perturbed(view, scen, delta=DELTA_MS, key=None):
    def extra(k):
        return delta if k == key else 0.0
    return traj(view['plan'], scen, view['period_ms'], extra_ms=extra)


def gate3(plan_name, scen, period_ms, delta=DELTA_MS):
    base = traj(plan_name, scen, period_ms)
    results = []
    for key in perturbation_keys(base):
        pv = perturbed(base, scen, delta, key)
        g = gates(pv, 'perturb', scen['kind'])
        results.append(dict(key=list(key), official_pass=g['G1']['pass_'],
                            margins=pv['margins'], status=pv['status'],
                            order=base['order'] != pv['order']))
    bad = [r for r in results if not r['official_pass']]
    return dict(scenarios=len(results), failed=len(bad), failed_keys=[r['key'] for r in bad],
                order_flips=sum(1 for r in results if r['order']), detail=results)


def select(cands):
    """cands: {plan: dict(gates..., view...)}. Returns selection with reason."""
    accepted = [p for p, c in cands.items() if c['accepted']]
    if accepted:
        accepted.sort(key=lambda p: (BLOCKS[p], -(cands[p].get('MC') if cands[p].get('MC') is not None else -1e9), p))
        return dict(status='SELECTED', selected=accepted[0], accepted=accepted,
                    rule='fewest blocks, then largest MC, then stable candidate id')
    if all(c['evidence_ok'] for c in cands.values()):
        return dict(status='NO_ACCEPTABLE_PLAN_UNDER_RULE', selected=None, accepted=[],
                    note='not a mathematical infeasibility claim')
    return dict(status='INSUFFICIENT_EVIDENCE', selected=None, accepted=[],
                missing=sorted({m for c in cands.values() for m in c.get('missing', [])}))
