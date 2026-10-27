"""Entry point for the reserve-constrained selector and its retrospective ablation.

    python3 ers/cli.py freeze       # RULES.json + condition costs + evidence catalog
    python3 ers/cli.py select       # S0 / S10 decisions per budget
    python3 ers/cli.py ablate       # F2 / F3 / S0 / S10 tables + per-job reserve rows
    python3 ers/cli.py fingerprints
    python3 ers/cli.py all

Read-only on B8 raw data, the frozen prediction and the r1 selector.  Everything
written goes to this directory (``RULES.json``, ``COSTS.json``,
``EVIDENCE_CATALOG.json``) or to ``outputs/``.  No GPU, model, worker, SSH or
hardware access.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'ers'))

import ablation          # noqa: E402
import common            # noqa: E402
import rules             # noqa: E402
import select as select_mod  # noqa: E402

OUT = HERE / 'outputs'


def _write_csv(path, rows, columns=None):
    rows = list(rows)
    if not rows:
        Path(path).write_text('')
        return
    columns = columns or list(rows[0])
    with Path(path).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: _cell(r.get(k)) for k in columns})


def _cell(v):
    if isinstance(v, (list, tuple)):
        return '|'.join(str(x) for x in v)
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if v is None:
        return ''
    return v


def _result():
    return common.rbe_env.load(common.rbe_env.B8_RESULT)


# ---------------------------------------------------------------------- freeze

def run_freeze():
    result = _result()
    measured = common.rbe_costs.b8_measured_costs(result)
    doc = rules.rules_document()
    rules.validate_rules(doc)
    common.write_json(HERE / 'RULES.json', doc)
    rules_sha = common.sha(HERE / 'RULES.json')

    costs, conditions, cells = {}, {}, {}
    for period in common.PERIODS_MS:
        key = 'p%d' % int(period)
        candidates, condition = ablation.build_candidates(result, period)
        conditions[key] = dict(condition)
        costs[key] = {plan: candidates[plan]['costs'] for plan in candidates}
        cells[key] = {plan: dict(cell=candidates[plan]['cell'],
                                 segments=candidates[plan]['cell'] and
                                 list(measured['cells'][candidates[plan]['cell']]['segments']),
                                 retention=candidates[plan]['retention'],
                                 boundary_costs=candidates[plan]['boundary_costs'])
                      for plan in candidates}
    costs_doc = dict(
        schema='m3_expert_reserve_costs_v1', rule=common.RULE_ID,
        source='B8 own operations.GPU_total_envelope_ms, per cell',
        retrospective=True,
        scenarios=dict(typical='per-operation median of that cell',
                       stress='per-operation maximum of that cell'),
        warnings=['a per-item maximum does not imply all maxima occur together',
                  'this is not an upper bound on any response',
                  'B4/B8 and 180/140 costs are never pooled',
                  'layers are not divided; Host/Event intervals are not summed'],
        conditions=conditions, costs=costs, cells=cells)
    common.write_json(HERE / 'COSTS.json', costs_doc)
    costs_sha = common.sha(HERE / 'COSTS.json')

    inputs = common.rbe_env.fingerprint_inputs()
    catalog = dict(
        schema='m3_expert_reserve_evidence_v1', rule=common.RULE_ID,
        status=common.RULE_STATUS,
        rules=dict(path='RULES.json', sha256=rules_sha,
                   reserve_ms=doc['reserve']['value_ms'],
                   identity=doc['reserve']),
        costs=dict(path='COSTS.json', sha256=costs_sha,
                   source='B8 result.json segments[*].operations',
                   per_cell=dict(
                       **{k: dict(condition=v,
                                  cells={p: dict(cell=cells[k][p]['cell'],
                                                 segments=cells[k][p]['segments'],
                                                 retention=cells[k][p]['retention'])
                                         for p in cells[k]})
                          for k, v in conditions.items()})),
        b8_result=dict(path=str(common.rbe_env.B8_RESULT.relative_to(common.PROJECT)),
                       sha256=inputs['b8_result_json']['sha256']),
        b8_prediction=dict(path=str(common.rbe_env.B8_PREDICTION.relative_to(common.PROJECT)),
                           sha256=inputs['b8_prediction_json']['sha256'],
                           status='frozen pre-run prediction, not rewritten'),
        r1_selector=dict(dir=str(common.rbe_env.R1.relative_to(common.PROJECT)),
                         applicability_domain_unchanged=True,
                         note='the new rule is a separate module; r1 180/140 statuses unchanged'),
        modules=common.module_identity(),
        reused=['rbe/costs.py (per-cell extraction)', 'rbe/replay.py (frozen model replay)',
                'rbe/env.py (frozen input identity)', 'rbe/audit.py (actual job table)'],
        notes=['no selector GPU run exists; S0/S10 performance is reused from the '
               'corresponding fixed plan and marked as such',
               'retention differs by plan by design and is not a condition mismatch'],
    )
    common.write_json(HERE / 'EVIDENCE_CATALOG.json', catalog)
    return dict(rules_sha=rules_sha, costs_sha=costs_sha, catalog=catalog)


# ---------------------------------------------------------------------- select

def _decisions(result, reserve):
    out = {}
    for period in common.PERIODS_MS:
        candidates, condition = ablation.build_candidates(result, period)
        out['p%d' % int(period)] = dict(
            condition=condition, candidates=candidates,
            S0=select_mod.select(candidates, 0.0),
            S10=select_mod.select(candidates, reserve),
            F2=select_mod.fixed('two_9_9', candidates, reserve),
            F3=select_mod.fixed('three_prefix_9_9', candidates, reserve))
    return out


def run_select():
    result = _result()
    dec = _decisions(result, rules.RE_MS)
    payload = dict(schema='m3_expert_reserve_selection_v1', rule=common.RULE_ID,
                   status=common.RULE_STATUS, reserve_ms=rules.RE_MS,
                   reserve_identity=rules.RESERVE_IDENTITY,
                   budgets={}, notes=[
                       'the rule sees only the two scenario summaries; the recorded '
                       'trajectory is not an input',
                       'reserve shortfall is auxiliary and never an official deadline miss',
                       'the reserve value was proposed after B8 and is not tuned here'])
    rows = []
    for key, d in dec.items():
        payload['budgets'][key] = dict(
            period_ms=float(key[1:]), condition=d['condition'],
            candidates={p: _cand_row(d['candidates'][p]) for p in d['candidates']},
            S0=d['S0'], S10=d['S10'], F2=d['F2'], F3=d['F3'])
        for plan in common.CANDIDATES:
            c = d['candidates'][plan]
            rows.append(dict(budget=key, period_ms=float(key[1:]), candidate=plan,
                             blocks=c['blocks'], evidence_ok=c['evidence_ok'],
                             complete=c['complete'], feasible=c['feasible'],
                             MC=c['MC'], ME=c['ME'], MR=c['MR'],
                             reserve_ms=rules.RE_MS, reserve_ok=c['reserve_ok'],
                             S0_selected=_sel(d['S0'], plan),
                             S10_selected=_sel(d['S10'], plan)))
    common.write_json(OUT / 'SELECTION.json', payload)
    _write_csv(OUT / 'SELECTION.csv', rows, ['budget', 'period_ms', 'candidate', 'blocks',
                                             'evidence_ok', 'complete', 'feasible',
                                             'MC', 'ME', 'MR', 'reserve_ms', 'reserve_ok',
                                             'S0_selected', 'S10_selected'])
    return payload


def _cand_row(c):
    return dict(plan=c['plan'], blocks=c['blocks'], MC=c['MC'], ME=c['ME'], MR=c['MR'],
                feasible=c['feasible'], reserve_ok=c['reserve_ok'],
                complete=c['complete'], evidence_ok=c['evidence_ok'],
                scenarios={k: None if v is None else dict(MC=v['MC'], ME=v['ME'],
                                                          MR=v['MR'])
                           for k, v in c['scenarios'].items()})


def _sel(decision, plan):
    return bool(decision.get('selected') == plan)


# ---------------------------------------------------------------------- ablate

def run_ablate():
    result = _result()
    dec = _decisions(result, rules.RE_MS)
    payload = dict(schema='m3_expert_reserve_ablation_v1', rule=common.RULE_ID,
                   status=common.RULE_STATUS, reserve_ms=rules.RE_MS,
                   budgets={}, notes=[
                       'F2/F3 are fixed plans; S0/S10 are the frozen rule at RE=0/10 ms',
                       'when a scheme resolves to a fixed plan its performance is that '
                       'plan\'s recorded result and is marked reused; there is no '
                       'selector GPU run',
                       'model selection (A), recorded performance (B) and predicted-vs-actual '
                       'reserve (C) are reported separately'])
    rows, jobs, agree_rows, actuals = [], [], [], []
    for key, d in dec.items():
        period = float(key[1:])
        cands = d['candidates']
        schemes = {'F2': d['F2'], 'F3': d['F3'], 'S0': d['S0'], 'S10': d['S10']}
        actual = {p: ablation.actual_metrics(result, p, period) for p in common.CANDIDATES}
        for p in common.CANDIDATES:
            actuals.append(dict(budget=key, period_ms=period, plan=p, blocks=common.BLOCKS[p],
                                **{k: actual[p][k] for k in
                                   ('cell', 'cycles_pass', 'cycles_total', 'refreshes_pass',
                                    'refreshes_total', 'reserve_short', 'reserve_total',
                                    'min_expert_margin_ms', 'min_cycle_margin_ms',
                                    'min_refresh_margin_ms', 'incomplete', 'uncertain',
                                    'official_feasible', 'reserve_ok')}))
            agree = ablation.reserve_agreement(cands, actual[p], p)
            for a in agree:
                agree_rows.append(dict(budget=key, plan=p, segment_id=a['segment_id'],
                                       scenario=a['scenario'],
                                       denominator=a['denominator'],
                                       predicted_short=a['predicted_short'],
                                       actual_short=a['actual_short'],
                                       predicted_short_actual_ok=a['predicted_short_actual_ok'],
                                       predicted_ok_actual_short=a['predicted_ok_actual_short']))
            preds_all = ablation.predicted_rows(cands, p)
            for j in actual[p]['jobs']:
                if j['job_type'] != 'Expert':
                    continue
                pt = (preds_all.get('typical') or {}).get(j['job_id'])
                ps = (preds_all.get('stress') or {}).get(j['job_id'])
                jobs.append(dict(
                    budget=key, plan=p, segment_id=j['segment_id'], job_id=j['job_id'],
                    segment_experts=sum(1 for x in actual[p]['jobs']
                                        if x['segment_id'] == j['segment_id']
                                        and x['job_type'] == 'Expert'),
                    actual_margin_ms=j['margin_ms'], official_status=j['status'],
                    official_deadline_status=('INCOMPLETE' if j['margin_ms'] is None else
                                              ('PASS' if j['margin_ms'] >= 0 else 'FAIL')),
                    official_basis='Expert deadline (unchanged)',
                    reserve_short=j['reserve_short'],
                    predicted_typical_ms=pt, predicted_stress_ms=ps,
                    predicted_typical_short=None if pt is None else pt < rules.RE_MS,
                    predicted_stress_short=None if ps is None else ps < rules.RE_MS,
                    predicted_ok_actual_short_typical=(None if pt is None else
                                                       (pt >= rules.RE_MS and j['reserve_short'])),
                    predicted_ok_actual_short_stress=(None if ps is None else
                                                      (ps >= rules.RE_MS and j['reserve_short']))))
        for name in ablation.SCHEME_ORDER:
            s = schemes[name]
            chosen = s.get('selected')
            reused = None
            if chosen:
                fixed_name = 'F2' if chosen == 'two_9_9' else 'F3'
                reused = fixed_name if name in ('S0', 'S10') else None
            row = dict(budget=key, period_ms=period, scheme=name, status=s['status'],
                       selected_plan=chosen,
                       blocks=None if chosen is None else common.BLOCKS[chosen],
                       boundaries_per_refresh=None if chosen is None
                       else common.BLOCKS[chosen] + 1,
                       reused_from=reused,
                       equivalent_to=reused,
                       reason=s.get('reason'))
            if chosen:
                c = cands[chosen]
                row.update(model_MC=c['MC'], model_ME=c['ME'], model_MR=c['MR'],
                           model_feasible=c['feasible'], model_reserve_ok=c['reserve_ok'])
                a = actual[chosen]
                row.update(actual_cell=a['cell'],
                           actual_cycles_pass=a['cycles_pass'],
                           actual_cycles_total=a['cycles_total'],
                           actual_refreshes_pass=a['refreshes_pass'],
                           actual_refreshes_total=a['refreshes_total'],
                           actual_reserve_short=a['reserve_short'],
                           actual_reserve_total=a['reserve_total'],
                           actual_min_expert_margin_ms=a['min_expert_margin_ms'],
                           actual_min_cycle_margin_ms=a['min_cycle_margin_ms'],
                           actual_min_refresh_margin_ms=a['min_refresh_margin_ms'],
                           actual_official_feasible=a['official_feasible'],
                           actual_reserve_ok=a['reserve_ok'],
                           retention_entries=cands[chosen]['retention']['entries'],
                           retention_payload_B=cands[chosen]['retention']['payload_B'],
                           block_post_retention_ms=cands[chosen]['boundary_costs'][
                               'block_post_retention_median_ms'])
                base2, base3 = cands['two_9_9'], cands['three_prefix_9_9']
                row.update(dMC_vs_F2=None if base2['MC'] is None or c['MC'] is None
                           else round(c['MC'] - base2['MC'], 6),
                           dME_vs_F2=None if base2['ME'] is None or c['ME'] is None
                           else round(c['ME'] - base2['ME'], 6),
                           dMR_vs_F2=None if base2['MR'] is None or c['MR'] is None
                           else round(c['MR'] - base2['MR'], 6),
                           dMC_vs_F3=None if base3['MC'] is None or c['MC'] is None
                           else round(c['MC'] - base3['MC'], 6),
                           dME_vs_F3=None if base3['ME'] is None or c['ME'] is None
                           else round(c['ME'] - base3['ME'], 6),
                           dMR_vs_F3=None if base3['MR'] is None or c['MR'] is None
                           else round(c['MR'] - base3['MR'], 6))
            rows.append(row)
        payload['budgets'][key] = dict(
            period_ms=period, condition=d['condition'],
            schemes={n: schemes[n] for n in ablation.SCHEME_ORDER},
            actual={p: {k: v for k, v in actual[p].items() if k != 'jobs'}
                    for p in common.CANDIDATES})
    _write_csv(OUT / 'ABLATION.csv', rows, [
        'budget', 'period_ms', 'scheme', 'status', 'selected_plan', 'blocks',
        'boundaries_per_refresh', 'reused_from', 'equivalent_to', 'reason',
        'model_MC', 'model_ME', 'model_MR', 'model_feasible', 'model_reserve_ok',
        'actual_cell', 'actual_cycles_pass', 'actual_cycles_total',
        'actual_refreshes_pass', 'actual_refreshes_total',
        'actual_reserve_short', 'actual_reserve_total',
        'actual_min_expert_margin_ms', 'actual_min_cycle_margin_ms',
        'actual_min_refresh_margin_ms', 'actual_official_feasible', 'actual_reserve_ok',
        'retention_entries', 'retention_payload_B', 'block_post_retention_ms',
        'dMC_vs_F2', 'dME_vs_F2', 'dMR_vs_F2', 'dMC_vs_F3', 'dME_vs_F3', 'dMR_vs_F3'])
    _write_csv(OUT / 'ACTUAL_METRICS.csv', actuals, [
        'budget', 'period_ms', 'plan', 'blocks', 'cell', 'cycles_pass', 'cycles_total',
        'refreshes_pass', 'refreshes_total', 'reserve_short', 'reserve_total',
        'min_expert_margin_ms', 'min_cycle_margin_ms', 'min_refresh_margin_ms',
        'incomplete', 'uncertain', 'official_feasible', 'reserve_ok'])
    _write_csv(OUT / 'JOB_RESERVE.csv', jobs, [
        'budget', 'plan', 'segment_id', 'job_id', 'segment_experts',
        'actual_margin_ms', 'official_status', 'official_deadline_status',
        'official_basis', 'reserve_short', 'predicted_typical_ms', 'predicted_stress_ms',
        'predicted_typical_short', 'predicted_stress_short',
        'predicted_ok_actual_short_typical', 'predicted_ok_actual_short_stress'])
    _write_csv(OUT / 'RESERVE_AGREEMENT.csv', agree_rows, [
        'budget', 'plan', 'segment_id', 'scenario', 'denominator', 'predicted_short',
        'actual_short', 'predicted_short_actual_ok', 'predicted_ok_actual_short'])
    common.write_json(OUT / 'ABLATION.json', payload)
    return payload


# ---------------------------------------------------------------- fingerprints

def run_fingerprints():
    outputs = {}
    for p in sorted(OUT.glob('*')):
        if p.is_file() and p.name != 'FINGERPRINTS.json':
            outputs[p.name] = common.sha(p)
    payload = dict(
        schema='m3_expert_reserve_fingerprints_v1', rule=common.RULE_ID,
        status=common.RULE_STATUS,
        inputs=common.rbe_env.fingerprint_inputs(),
        rules=dict(path='RULES.json',
                   sha256=common.sha(HERE / 'RULES.json') if (HERE / 'RULES.json').exists()
                   else None),
        costs=dict(path='COSTS.json',
                   sha256=common.sha(HERE / 'COSTS.json') if (HERE / 'COSTS.json').exists()
                   else None),
        catalog=dict(path='EVIDENCE_CATALOG.json',
                     sha256=common.sha(HERE / 'EVIDENCE_CATALOG.json')
                     if (HERE / 'EVIDENCE_CATALOG.json').exists() else None),
        modules=common.module_identity(),
        outputs=outputs,
        note='outputs are hashed before this manifest is written')
    common.write_json(OUT / 'FINGERPRINTS.json', payload)
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('what', choices=('freeze', 'select', 'ablate', 'fingerprints', 'all'))
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    if a.what in ('freeze', 'all'):
        f = run_freeze()
        summary['freeze'] = dict(
            rules_sha256=f['rules_sha'], costs_sha256=f['costs_sha'],
            inputs_ok=all(v['match'] for v in
                          common.rbe_env.fingerprint_inputs().values()))
    if a.what in ('select', 'all'):
        s = run_select()
        summary['select'] = {k: dict(S0=v['S0']['selected'], S0_status=v['S0']['status'],
                                     S10=v['S10']['selected'],
                                     S10_status=v['S10']['status'])
                             for k, v in s['budgets'].items()}
    if a.what in ('ablate', 'all'):
        ab = run_ablate()
        summary['ablate'] = {k: {n: v['schemes'][n]['selected']
                                 for n in ablation.SCHEME_ORDER}
                             for k, v in ab['budgets'].items()}
    if a.what in ('fingerprints', 'all'):
        fp = run_fingerprints()
        summary['fingerprints'] = dict(outputs=len(fp['outputs']),
                                       inputs_ok=all(v['match'] for v in fp['inputs'].values()))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
