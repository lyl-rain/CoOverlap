#!/usr/bin/env python3
"""Run the v2 selector offline: gates, perturbation, S0-S3 ablation, outputs."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'cps2'))
import core  # noqa: E402

OUT = HERE / 'outputs'


def evaluate_budget(b9, b8, budget, sources=(180.0, 140.0)):
    if budget not in core.B10_BUDGETS+core.B9_BUDGETS:
        return {},dict(status='UNSUPPORTED_INPUT',selected=None,period_ms=budget)
    proof = getattr(b9, 'evidence', dict(status='INSUFFICIENT_EVIDENCE',missing=['source provenance']))
    cands = {}
    for plan in core.CANDIDATES:
        rows, missing = [], ([] if proof['status']=='MATCH' else ['source condition or identity'])
        for src in sources:
            for kind in ('typical', 'stress'):
                cell = b9.get((plan, src))
                if cell is None:
                    missing.append('cost:%s@%g' % (plan, src))
                    continue
                scen = core.scenario(cell, kind)
                view = core.traj(plan, scen, budget)
                g = core.gates(view, 'b9@%g' % src, kind)
                p = core.gate3(plan, scen, budget)
                rows.append(dict(source='b9@%g' % src, scenario=kind, margins=view['margins'],
                                 G1=g['G1']['pass_'], G2=g['G2']['pass_'],
                                 perturbation=p, G3=dict(scenarios=p['scenarios'], failed=p['failed'],
                                         failed_keys=p['failed_keys'],
                                         order_flips=p['order_flips']),
                                 view=view, g1=g, g2=g['G2']))
        g1 = all(r['G1'] for r in rows) and bool(rows)
        g2 = all(r['G2'] for r in rows) and bool(rows)
        g3 = all(r['G3']['failed'] == 0 for r in rows) and bool(rows)
        full_work = all(r['view']['complete'] for r in rows) and bool(rows)
        lifecycle = all(r['view']['refusals'] == 0 and r['view']['status']=='DRAINED' for r in rows)
        cands[plan] = dict(
            evidence_ok=not missing, missing=missing, source_status=proof['status'], source_check=proof,
            G0=dict(pass_=(not missing and full_work and lifecycle), missing=missing,
                    full_work=full_work, lifecycle=lifecycle),
            G1=dict(pass_=g1), G2=dict(pass_=g2), G3=dict(pass_=g3),
            G3_detail=[dict(source=r['source'], scenario=r['scenario'], **r['perturbation']) for r in rows],
            MC=min((r['margins']['MC'] for r in rows if r['margins']['MC'] is not None), default=None),
            ME=min((r['margins']['ME'] for r in rows if r['margins']['ME'] is not None), default=None),
            MU=min((r['margins']['MU'] for r in rows if r['margins']['MU'] is not None), default=None),
            MR=min((r['margins']['MR'] for r in rows if r['margins']['MR'] is not None), default=None),
            sources=[dict(source=r['source'], scenario=r['scenario'], margins=r['margins'],
                          G1=r['G1'], G2=r['G2'], G3=r['G3']) for r in rows],
            accepted=(not missing and full_work and lifecycle and g1 and g2 and g3),
            reason=('' if (not missing and full_work and lifecycle and g1 and g2 and g3)
                    else ('missing evidence' if missing else
                          ('G1 official fail' if not g1 else
                           ('G2 reserve fail' if not g2 else 'G3 perturbation fail')))))
    sel = core.select(cands)
    return cands, sel


def scheme_rows(budget, cands):
    """S0 official, S1 +ME, S2 +MU, S3 +perturbation."""
    schemes = ('S0', 'S1', 'S2', 'S3')
    out = []
    for plan in core.CANDIDATES:
        c = cands[plan]
        g = {'S0': c['G1']['pass_'],
             'S1': c['G1']['pass_'] and all(s['margins']['ME'] is not None
                                            and s['margins']['ME'] >= core.RE_MS for s in c['sources']),
             'S2': c['G1']['pass_'] and all(s['margins']['ME'] is not None
                                            and s['margins']['ME'] >= core.RE_MS
                                            and s['margins']['MU'] is not None
                                            and s['margins']['MU'] >= core.RU_MS for s in c['sources']),
             'S3': c['G3']['pass_'] and c['G1']['pass_'] and all(
                 s['margins']['ME'] is not None and s['margins']['ME'] >= core.RE_MS
                 and s['margins']['MU'] is not None and s['margins']['MU'] >= core.RU_MS
                 for s in c['sources'])}
        for s in schemes:
            out.append(dict(budget_ms=budget, plan=plan, scheme=s, accepted=(g[s] and core.candidate_g0(c) and all(x.get('evidence_ok') for x in cands.values())),
                            ME=c['ME'], MU=c['MU'], MC=c['MC'], MR=c['MR'],
                            missing=len(c['missing'])))
    return out


def recommend(budget, rows):
    for s in ('S0', 'S1', 'S2', 'S3'):
        acc = [r for r in rows if r['budget_ms'] == budget and r['scheme'] == s and r['accepted']]
        if acc:
            acc.sort(key=lambda r: (core.BLOCKS[r['plan']], -(r['MC'] if r['MC'] is not None else -1e9), r['plan']))
            yield s, acc[0]['plan']
        else:
            yield s, None


def main():
    core.integrity.verify_freeze()
    OUT.mkdir(exist_ok=True)
    b9 = core.measured_cells(core.load(core.B9_RESULT))
    b8 = core.measured_cells(core.load(core.B8_RESULT))
    results, table = {}, []
    for budget in (160.0, 150.0, 180.0, 140.0):
        cands, sel = evaluate_budget(b9, b8, budget)
        results['%g' % budget] = dict(candidates=cands, selection=sel)
        table.extend(scheme_rows(budget, cands))
    rec = {}
    for budget in (160.0, 150.0, 180.0, 140.0):
        rec['%g' % budget] = dict(recommend(budget, table))
    (OUT / 'SELECTION.json').write_text(json.dumps(
        dict(schema='cps2_selection_v1', rule='credible_plan_selector_v2',
             gates='G0 evidence/lifecycle, G1 official, G2 reserve (ME>=10, MU>=10), G3 fixed perturbation',
             reserve=dict(RE_ms=core.RE_MS, RU_ms=core.RU_MS, refresh_reserve=False),
             delta_ms=core.DELTA_MS, budgets=results, schemes=rec,
             note='160/150 are extrapolations of B9 costs; 180/140 are retrospective replays'),
        indent=2, sort_keys=True) + '\n')
    (OUT/'PERTURBATION.json').write_text(json.dumps({b:{p:c['G3_detail'] for p,c in x['candidates'].items()} for b,x in results.items()},indent=2,sort_keys=True)+'\n')
    with (OUT / 'ABLATION.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    print(json.dumps({k: {kk: (vv['selection']['status'], vv['selection'].get('selected'))
                          for kk, vv in [('sel', vv0)]} for k, vv0 in results.items()}, indent=1)[:400])
    print(json.dumps(rec, indent=1, default=str))
    for b in ('160', '150'):
        for plan in core.CANDIDATES:
            c = results[b]['candidates'][plan]
            print(b, plan, 'G1', c['G1']['pass_'], 'G2', c['G2']['pass_'], 'G3', c['G3']['pass_'],
                  'ME %.3f MU %.3f MC %.3f' % (c['ME'], c['MU'], c['MC']),
                  'G3 fails', [(x['source'], x['scenario'], x['failed']) for x in c['G3_detail']])


if __name__ == '__main__':
    main()
