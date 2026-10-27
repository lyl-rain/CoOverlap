#!/usr/bin/env python3
"""Freeze the B9 pre-run prediction and the per-budget selection record.

Reads only the frozen B8 evidence and the frozen revision-r1 rule.  It never
looks at any B9 measurement (none exists) and never writes back to the B8
selected costs, the r1 selector, or the B8 prediction.

Outputs (all under prediction/):
  PREDICTION.json        per budget: candidates, scenarios, per-job margins,
                         order, versions, release-boundary distances, S0/S10
  SELECTION_FREEZE.json  the minimal record the runtime copies before each segment
  PREDICTION.md          human summary
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
B9 = HERE.parent
DAY = B9.parent
ERS = DAY / 'expert_reserve_selector_v1_r1' / 'ers'
sys.path.insert(0, str(ERS))

import ablation          # noqa: E402
import common            # noqa: E402
import rules             # noqa: E402
import select as select_mod  # noqa: E402

PROTOCOL = 'm3_b9_expert_reserve_validation_v1'
PHASE_MS = 15.0


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                      ensure_ascii=False).encode()).hexdigest()


def boundary_rows(result, plan, period_ms):
    """Release-boundary distance of the model's own dispatch order."""
    cands, _ = ablation.build_candidates(result, period_ms)
    rows = []
    for kind in common.SCENARIOS:
        raw = cands[plan]['raw'][kind]
        blocks = {(b['refresh'], b['block']): b for b in raw['blocks']}
        experts = {int(e['job_id'][1:]): e for e in raw['experts']}
        nblocks = common.BLOCKS[plan]
        for q in range(4):
            tail = blocks.get((q, nblocks - 1))
            expert = experts.get(2 * q + 1)
            if tail is None or expert is None:
                continue
            decision = min(tail['start_ms'], expert['dispatch_ms'])
            release = (2 * q + 1) * period_ms + PHASE_MS
            chosen = ('Context' if tail['start_ms'] <= expert['dispatch_ms'] else 'Expert')
            rows.append(dict(budget_ms=period_ms, plan=plan, scenario=kind, refresh=q,
                             decision_ms=round(decision, 6), release_ms=release,
                             distance_ms=round(release - decision, 6),
                             chosen=chosen, tail_block='B%d' % nblocks,
                             next_expert='E%d' % (2 * q + 1)))
    return rows


def jobs(cands, plan, period_ms):
    rows = []
    for kind in common.SCENARIOS:
        raw = cands[plan]['raw'][kind]
        for e in raw['experts']:
            rows.append(dict(budget_ms=period_ms, plan=plan, scenario=kind,
                             job_id=e['job_id'], dispatch_ms=e['dispatch_ms'],
                             completion_ms=e['completion_ms'], margin_ms=e['margin_ms'],
                             reserve_met=(e['margin_ms'] is not None
                                          and e['margin_ms'] >= rules.RE_MS),
                             version=e['version'], status=e['status']))
    return rows


def main():
    result = common.rbe_env.load(common.rbe_env.B8_RESULT)
    rules_doc = common.load(DAY / 'expert_reserve_selector_v1_r1' / 'RULES.json')
    costs_doc = common.load(DAY / 'expert_reserve_selector_v1_r1' / 'COSTS.json')
    rules_sha = sha(DAY / 'expert_reserve_selector_v1_r1' / 'RULES.json')
    costs_sha = sha(DAY / 'expert_reserve_selector_v1_r1' / 'COSTS.json')

    pred = dict(schema='m3_b9_expert_reserve_prediction_v1', protocol=PROTOCOL,
                status='PRE_RUN_PREDICTION_FROZEN',
                identity=dict(
                    rule=dict(id=rules_doc['id'], sha256=rules_sha,
                              reserve_ms=rules_doc['reserve']['value_ms'],
                              identity=rules_doc['reserve']),
                    costs=dict(path='expert_reserve_selector_v1_r1/COSTS.json',
                               sha256=costs_sha,
                               source='B8 own operations, per cell'),
                    b8_result_sha256=common.rbe_env.fingerprint_inputs()['b8_result_json']['sha256'],
                    note='costs are the frozen B8 condition costs; no B9 timing is used'),
                budgets={}, jobs=[], boundary=[], selection={})
    for period in common.PERIODS_MS:
        key = 'p%d' % int(period)
        cands, condition = ablation.build_candidates(result, period)
        s0 = select_mod.select(cands, 0.0)
        s10 = select_mod.select(cands, rules.RE_MS)
        pred['budgets'][key] = dict(
            period_ms=period, condition=condition,
            candidates={p: dict(blocks=cands[p]['blocks'], MC=cands[p]['MC'],
                                ME=cands[p]['ME'], MR=cands[p]['MR'],
                                feasible=cands[p]['feasible'],
                                reserve_ok=cands[p]['reserve_ok'],
                                scenarios={k: dict(MC=v['MC'], ME=v['ME'], MR=v['MR'])
                                           for k, v in cands[p]['scenarios'].items() if v})
                          for p in common.CANDIDATES},
            S0=dict(selected=s0['selected'], status=s0['status'], reason=s0['reason']),
            S10=dict(selected=s10['selected'], status=s10['status'], reason=s10['reason']),
            order={p: cands[p]['raw']['typical']['order'] for p in common.CANDIDATES},
            versions={p: {e['job_id']: e['version']
                          for e in cands[p]['raw']['typical']['experts']}
                      for p in common.CANDIDATES})
        pred['selection'][key] = dict(
            S0=dict(selected=s0['selected'], status=s0['status'], reserve_ms=0.0),
            S10=dict(selected=s10['selected'], status=s10['status'],
                     reserve_ms=rules.RE_MS))
        for p in common.CANDIDATES:
            pred['jobs'].extend(jobs(cands, p, period))
            pred['boundary'].extend(boundary_rows(result, p, period))
    pred['fingerprint'] = canonical_sha({k: v for k, v in pred.items() if k != 'fingerprint'})
    (HERE / 'PREDICTION.json').write_text(json.dumps(pred, indent=2, sort_keys=True) + '\n')

    freeze = dict(
        schema='m3_b9_selection_freeze_v1', protocol=PROTOCOL,
        status='FROZEN_BEFORE_RUN', rule_id=rules_doc['id'],
        rule_sha256=rules_sha, costs_sha256=costs_sha, reserve_ms=rules.RE_MS,
        by_period_ns={str(int(period * 1e6)): pred['selection']['p%d' % int(period)]
                      for period in common.PERIODS_MS},
        note='recorded before each segment; it does not change the executed plan')
    freeze['fingerprint'] = canonical_sha(freeze)
    (HERE / 'SELECTION_FREEZE.json').write_text(
        json.dumps(freeze, indent=2, sort_keys=True) + '\n')

    lines = ['# B9 pre-run prediction (frozen before any B9 measurement)', '',
             'Protocol `%s`; rule `%s`; RE = %g ms.' % (PROTOCOL, rules_doc['id'],
                                                       rules_doc['reserve']['value_ms']), '',
             '| budget | S0 | S10 | two MC/ME/MR | three MC/ME/MR |', '|---|---|---|---|---|']
    for key in ('p180', 'p140'):
        b = pred['budgets'][key]
        c2, c3 = b['candidates']['two_9_9'], b['candidates']['three_prefix_9_9']
        lines.append('| %s | %s | **%s** | %.3f/%.3f/%.3f | %.3f/%.3f/%.3f |' % (
            key, b['S0']['selected'], b['S10']['selected'],
            c2['MC'], c2['ME'], c2['MR'], c3['MC'], c3['ME'], c3['MR']))
    lines += ['', 'Per-job margins, dispatch order, versions and release-boundary distances are in',
              '`PREDICTION.json`; the runtime copies `SELECTION_FREEZE.json` into each segment',
              'record before the timed window. The recommendation is not an acceptance condition.', '']
    (HERE / 'PREDICTION.md').write_text('\n'.join(lines))

    freezes = {}
    for name in ('PREDICTION.json', 'SELECTION_FREEZE.json', 'PREDICTION.md'):
        freezes[name] = sha(HERE / name)
    print(json.dumps(dict(prediction_fingerprint=pred['fingerprint'],
                          selection=freeze['by_period_ns'],
                          files=freezes), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
