#!/usr/bin/env python3
"""Minimal cross-budget prediction for the B8 split x budget challenge.

Status: EXTRAPOLATIVE_PREDICTION_NOT_VALIDATED.

The formal r1 selector applicability domain is NOT changed.  This entry reuses
the r1 frozen costs, rules and analysis model, changes only the declared period
(and the corresponding manifest), and writes a pre-run prediction.  It does not
read any B8 measurement, add a correction constant/multiplier/fit, or write to
the r1 freeze.
"""
from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[5]
R1 = PROJECT / 'reports/m3_b2/20261022/empirical_plan_selector_v1_r1'
HERE = Path(__file__).resolve().parent
DEPLOY = HERE.parent / 'deployment'
for path in (str(R1 / 'selector'), str(DEPLOY)):
    if path not in sys.path:
        sys.path.insert(0, path)

from evidence import canonical_sha, sha  # noqa: E402
from evaluator import evaluate  # noqa: E402
from selection import TARGET, select, scenario_for  # noqa: E402
from validate import verify_freeze  # noqa: E402
import m3_b8_plan as b8  # noqa: E402

MARKER = 'EXTRAPOLATIVE_PREDICTION_NOT_VALIDATED'
CONDITION_STATUS = 'OUT_OF_SOURCE_APPLICABILITY_DOMAIN'
SOURCE_DIR = R1


def _load(path):
    return json.loads(Path(path).read_text())


def _release_completion_margin(row):
    release = row.get('release_ms')
    completion = row.get('completion_ms')
    response = None if release is None or completion is None else round(completion - release, 6)
    return response


def _refresh_version(refresh_id):
    return refresh_id + 1


def _cell_prediction(costs, rules, cell):
    scenarios = {}
    for kind in ('typical', 'stress'):
        result = evaluate(cell['plan'], scenario_for(costs, cell['plan'], kind),
                          policy='b2_boundary', cycles=b8.CYCLES,
                          period=cell['period_ns'] / 1e6, phase=b8.PHASE_NS / 1e6,
                          gap_ms=float(rules['model_constants']['gap_ms']),
                          publish_cost_ms=float(rules['model_constants']['publish_cost_ms']))
        experts = []
        for x in result['experts']:
            experts.append(dict(job_id=x['job_id'], release_ms=x['release_ms'],
                                deadline_ms=x['deadline_ms'], dispatch_ms=x['dispatch_ms'],
                                completion_ms=x['completion_ms'],
                                response_ms=_release_completion_margin(x),
                                margin_ms=x['margin_ms'], version=x['version'],
                                status=x['status']))
        blocks = []
        for x in result['blocks']:
            blocks.append(dict(job_id=x['job_id'], refresh=x['refresh'], block=x['block'],
                               start_ms=x['start_ms'], completion_ms=x['completion_ms'],
                               status=x['status']))
        cycles = []
        for x in result['cycles']:
            cycles.append(dict(cycle=x['cycle'], release_ms=x['release_ms'],
                               deadline_ms=x['deadline_ms'],
                               completion_ms=x['predicted_completion_ms'],
                               response_ms=x['response_ms'],
                               margin_ms=x['predicted_margin_ms'],
                               expert_response_ms=x['expert_response_ms'],
                               vlm_response_ms=x['vlm_response_ms'], status=x['status']))
        refreshes = []
        for x in result['refreshes']:
            release = x['release_ms']
            deadline_rel = x['deadline_ms']
            refreshes.append(dict(id=x['id'], version=_refresh_version(x['id']),
                                  release_ms=release,
                                  deadline_ms=round(release + deadline_rel, 6),
                                  deadline_relative_ms=deadline_rel,
                                  response_ms=x['refresh_response_ms'],
                                  completion_offset_ms=x['completion_offset_ms'],
                                  margin_ms=x['refresh_margin_ms'], status=x['status']))
        dispatch = []
        for x in experts:
            dispatch.append(dict(kind='Expert', job_id=x['job_id'], start_ms=x['dispatch_ms']))
        for x in blocks:
            dispatch.append(dict(kind='ContextBlock', job_id=x['job_id'], start_ms=x['start_ms']))
        dispatch.sort(key=lambda x: (x['start_ms'] is None, x['start_ms'] if x['start_ms'] is not None else 0, x['kind'], x['job_id']))
        checkpoints = sorted({r['release_ms'] for r in refreshes}
                             | {c['release_ms'] for c in cycles}
                             | {e['release_ms'] for e in experts})
        backlog_rows = []
        for t in checkpoints:
            pending = sum(1 for r in refreshes
                          if r['release_ms'] <= t and (r['completion_offset_ms'] is None
                                                       or r['completion_offset_ms'] > t))
            backlog_rows.append(dict(t_ms=round(t, 6), pending_refreshes=pending))
        incomplete = dict(
            experts=[x['job_id'] for x in experts if x['status'] == 'INCOMPLETE'],
            blocks=[x['job_id'] for x in blocks if x['status'] == 'INCOMPLETE'],
            cycles=[x['cycle'] for x in cycles if x['status'] == 'INCOMPLETE'],
            refreshes=[x['id'] for x in refreshes if x['status'] == 'INCOMPLETE'],
        )
        scenarios[kind] = dict(
            feasible=result['feasible'], complete=result['complete'],
            model_status=result['status'], counts=result['counts'],
            min_cycle_margin_ms=result['min_cycle_margin_ms'],
            min_expert_margin_ms=result['min_expert_margin_ms'],
            min_refresh_margin_ms=result['min_refresh_margin_ms'],
            max_refresh_response_ms=result['max_refresh_response_ms'],
            max_refresh_completion_offset_ms=result['max_refresh_completion_offset_ms'],
            experts=experts, blocks=blocks, cycles=cycles, refreshes=refreshes,
            dispatch_order=dispatch,
            backlog=dict(max_pending_refreshes=max(x['pending_refreshes'] for x in backlog_rows),
                         rows=backlog_rows,
                         source='derived from predicted refresh releases/publications'),
            deferred_publications=result['deferred'],
            refused_slots=result['refusals'],
            max_expert_dispatch_delay_ms=(max(
                [round(x['dispatch_ms'] - x['release_ms'], 6) for x in experts
                 if x['dispatch_ms'] is not None and x['release_ms'] is not None] or [None])
                if experts else None),
            max_expert_response_ms=max(
                [x['response_ms'] for x in experts if x['response_ms'] is not None] or [None])
            if experts else None,
            incomplete=incomplete,
        )
    return dict(cell=cell['id'], letter=cell['letter'], plan=cell['plan'],
                policy=cell['policy'], period_ns=cell['period_ns'],
                period_ms=cell['period_ns'] / 1e6, scenarios=scenarios)


def _deltas(a, b, kind):
    keys = ('min_cycle_margin_ms', 'min_expert_margin_ms', 'min_refresh_margin_ms',
            'max_refresh_response_ms', 'max_refresh_completion_offset_ms',
            'max_pending_refreshes')
    out = {}
    for key in keys:
        if key == 'max_pending_refreshes':
            av = a['scenarios'][kind]['backlog']['max_pending_refreshes']
            bv = b['scenarios'][kind]['backlog']['max_pending_refreshes']
        else:
            av = a['scenarios'][kind][key]
            bv = b['scenarios'][kind][key]
        out[key] = None if av is None or bv is None else round(av - bv, 6)
    out['feasible_a'] = a['scenarios'][kind]['feasible']
    out['feasible_b'] = b['scenarios'][kind]['feasible']
    return out


def build():
    freeze = verify_freeze(R1 / 'freeze/FREEZE.json')
    costs = _load(R1 / 'freeze/TRAIN_COSTS.json')
    rules = _load(R1 / 'freeze/RULES.json')
    formal = {
        'p180': select(costs, target=dict(period_ms=180.0, phase_ms=15.0, cycles=8), rules=rules),
        'p140': select(costs, target=dict(period_ms=140.0, phase_ms=15.0, cycles=8), rules=rules),
    }
    cells = {}
    for cell in b8.CELLS:
        cells[cell['letter']] = _cell_prediction(costs, rules, cell)
    differences = {}
    for budget, pair in ((180, ('A', 'B')), (140, ('C', 'D'))):
        differences['p%d' % budget] = {}
        for kind in ('typical', 'stress'):
            differences['p%d' % budget][kind] = _deltas(cells[pair[0]], cells[pair[1]], kind)
    budget_differences = {}
    for label, pair in (('two', ('A', 'C')), ('three', ('B', 'D'))):
        budget_differences[label] = {}
        for kind in ('typical', 'stress'):
            budget_differences[label][kind] = _deltas(cells[pair[0]], cells[pair[1]], kind)
    source_condition = costs['condition']
    out = dict(
        schema='m3_b8_split_budget_prediction_v1',
        status=MARKER,
        condition_status=CONDITION_STATUS,
        prediction_purpose='pre-run cross-budget comparison only; not a formal selector decision',
        source=dict(
            selector_dir=str(SOURCE_DIR),
            freeze=dict(path=str(SOURCE_DIR / 'freeze/FREEZE.json'), sha256=sha(SOURCE_DIR / 'freeze/FREEZE.json')),
            costs=dict(path=str(SOURCE_DIR / 'freeze/TRAIN_COSTS.json'), sha256=sha(SOURCE_DIR / 'freeze/TRAIN_COSTS.json')),
            rules=dict(path=str(SOURCE_DIR / 'freeze/RULES.json'), sha256=sha(SOURCE_DIR / 'freeze/RULES.json')),
            model=dict(path=str(SOURCE_DIR / 'selector/plan_model.py'), sha256=sha(SOURCE_DIR / 'selector/plan_model.py')),
            evaluator=dict(path=str(SOURCE_DIR / 'selector/evaluator.py'), sha256=sha(SOURCE_DIR / 'selector/evaluator.py')),
            executor=dict(path=freeze['executor']['path'], sha256=freeze['executor']['sha256']),
            condition_fingerprint=source_condition['fingerprint'],
        ),
        formal_selector=dict(
            p180=dict(status=formal['p180']['status'],
                      missing_or_mismatched=formal['p180'].get('missing_or_mismatched'),
                      reason=formal['p180'].get('reason')),
            p140=dict(status=formal['p140']['status'],
                      missing_or_mismatched=formal['p140'].get('missing_or_mismatched'),
                      reason=formal['p140'].get('reason')),
            note='r1 formal applicability domain retained; this prediction is not a selection'),
        compatibility=dict(
            status=CONDITION_STATUS,
            source_condition=source_condition,
            source_condition_fingerprint=source_condition['fingerprint'],
            extrapolation_variable='period only',
            period_changes=dict(source_240_ms=240.0, target_180_ms=180.0, target_140_ms=140.0),
            same=['plan definitions', 'policy b2_boundary', 'phase +15 ms', 'lead 10 ms declaration',
                  'quiet declared pressure', 'fixed input/checkpoint/BF16', 'version consumption',
                  'obligation groups', 'retention layout per plan/8 cycles', 'normal Event/Host observation',
                  'recorded clock limits (device/temperature remain UNKNOWN)'],
            changed=['protocol identity (new batch)', 'period (180/140 ms)', 'both split plans at both budgets',
                     'no serial control', 'no B7 22-point diagnostics / 4 s lead / pressure worker'],
            not_claimed='the period change is not assumed to leave numeric configuration, observation protocol'
                        ' or executor behavior unchanged; any additional mismatch must be disclosed before'
                        ' treating a result as an original-condition prediction validation',
        ),
        cells=cells,
        candidate_differences=differences,
        budget_differences=budget_differences,
        generated_from='frozen r1 costs/rules/model only; no B8 measurement',
        notes=['typical uses the frozen per-dimension median; stress uses the frozen per-dimension sample maximum',
               'stress is not a hard upper bound; a stress exceedance is an envelope exceedance, not automatically'
               ' an executor correctness failure',
               'prediction may be infeasible; the 140 ms challenge condition is retained regardless',
               'completion offset is relative to segment t0; refresh response is relative to refresh release',
               'the formal r1 selector is not modified and still refuses 180/140 formal selection'],
    )
    out['prediction_fingerprint'] = canonical_sha({k: v for k, v in out.items()
                                                   if k != 'prediction_fingerprint'})
    return out


def _md(pred):
    lines = ['# B8 pre-run prediction', '',
             '**Status: %s.** This is not a validation result. The formal r1 selector domain is unchanged;' % MARKER,
             '180 ms is INSUFFICIENT_EVIDENCE and 140 ms is UNSUPPORTED_INPUT for formal selection.', '',
             '| cell | plan | P | scenario | feasible | min cycle | min Expert | min refresh | max refresh response | max completion offset | max pending refreshes | deferred |',
             '|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for letter in ('A', 'B', 'C', 'D'):
        c = pred['cells'][letter]
        for kind in ('typical', 'stress'):
            s = c['scenarios'][kind]
            lines.append('| %s | %s | %.0f | %s | %s | %s | %s | %s | %s | %s | %d | %d |' % (
                letter, c['plan'], c['period_ms'], kind, s['feasible'],
                s['min_cycle_margin_ms'], s['min_expert_margin_ms'], s['min_refresh_margin_ms'],
                s['max_refresh_response_ms'], s['max_refresh_completion_offset_ms'],
                s['backlog']['max_pending_refreshes'], len(s['deferred_publications'])))
    lines += ['', 'Candidate differences are A-B at 180 ms and C-D at 140 ms; budget differences are A-C'
                  ' and B-D. Full per-job order, versions, completions, responses, margins and incomplete'
                  ' lists are in `PREDICTION.json`.', '',
              '`condition_status=%s`: period is the explicit extrapolation variable; this is not an' % CONDITION_STATUS,
              'original-condition validation even if the prediction matches.', '',
              'Evaluation protocol: `prediction/EVALUATION_PROTOCOL.md`. No post-hoc tolerance and no'
              ' prediction PASS threshold.', '']
    return '\n'.join(lines) + '\n'


def _write_files(pred, out_dir):
    out_dir = Path(out_dir)
    (out_dir / 'PREDICTION.json').write_text(json.dumps(pred, indent=2, sort_keys=True) + '\n')
    receipt = dict(
        schema='m3_b8_split_budget_prediction_receipt_v1',
        status=MARKER, condition_status=CONDITION_STATUS,
        prediction=dict(path=str(out_dir / 'PREDICTION.json'),
                        sha256=sha(out_dir / 'PREDICTION.json'),
                        fingerprint=pred['prediction_fingerprint']),
        source=pred['source'], formal_selector=pred['formal_selector'],
        note='pre-run prediction; not a validation result; do not rewrite from the B8 outcome')
    (out_dir / 'PREDICTION_RECEIPT.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    (out_dir / 'PREDICTION.md').write_text(_md(pred))
    return receipt


def write(out_dir):
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=False)
    pred = build()
    return pred, _write_files(pred, out_dir)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=HERE)
    a = ap.parse_args()
    out_dir = a.out.resolve()
    if out_dir == HERE:
        pred = build()
        receipt = _write_files(pred, HERE)
        print(json.dumps(dict(status=MARKER, sha256=receipt['prediction']['sha256'],
                              fingerprint=pred['prediction_fingerprint']), indent=2))
    else:
        pred, receipt = write(out_dir)
        print(json.dumps(dict(status=MARKER, out=str(out_dir),
                              sha256=receipt['prediction']['sha256']), indent=2))
