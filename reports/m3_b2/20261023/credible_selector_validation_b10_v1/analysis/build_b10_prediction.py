#!/usr/bin/env python3
"""Freeze the B10 per-job prediction from the v2 selector's extrapolation.

Every row comes from the frozen scheduler with B9 costs (source 180 and source
140 as two separate scenarios).  Nothing here is a B10 measurement.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DAY = HERE.parent
sys.path.insert(0, str(DAY / 'credible_plan_selector_v2' / 'cps2'))
sys.path.insert(0, str(HERE / 'deployment'))
import core                     # noqa: E402
import m3_b10_plan as plan      # noqa: E402


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rows_for(cell, source_cell, kind, source_label):
    scen = core.scenario(source_cell, kind)
    v = core.traj(cell['plan'], scen, cell['period_ns'] / 1e6)
    rows = []
    for e in v['experts']:
        rows.append(dict(job_type='Expert', job_id=e['job_id'], release_ms=e['release_ms'],
                         deadline_ms=e['deadline_ms'], completion_ms=e['completion_ms'],
                         response_ms=None if e['completion_ms'] is None else
                         round(e['completion_ms'] - e['release_ms'], 6),
                         margin_ms=e['margin_ms'], status=e['status']))
    for jid, comp in sorted(v['blocks'].items()):
        rows.append(dict(job_type='ContextBlock', job_id=jid, completion_ms=comp))
    for c in v['cycles']:
        rows.append(dict(job_type='Cycle', job_id=c['job_id'], release_ms=c['release_ms'],
                         deadline_ms=c['deadline_ms'], completion_ms=c['completion_ms'],
                         response_ms=None if c['completion_ms'] is None else
                         round(c['completion_ms'] - c['release_ms'], 6),
                         margin_ms=c['margin_ms'], status=c['status'],
                         expert_margin_ms=c['expert_margin_ms'],
                         unit_margin_ms=c['unit_margin_ms']))
    for r in v['refreshes']:
        rows.append(dict(job_type='Refresh', job_id=r['job_id'], release_ms=r['release_ms'],
                         deadline_ms=r['deadline_ms'], completion_ms=r['completion_ms'],
                         response_ms=None if r['completion_ms'] is None else
                         round(r['completion_ms'] - r['release_ms'], 6),
                         margin_ms=r['margin_ms'], status=r['status']))
    return dict(period_ms=cell['period_ns'] / 1e6, plan=cell['plan'], source=source_label,
                scenario=kind, margins=v['margins'], order=v['order'], rows=rows,
                complete=v['complete'], status=v['status'])


def main():
    b9 = core.measured_cells(core.load(core.B9_RESULT))
    doc = dict(schema='m3_b10_prediction_v1',
               protocol='m3_b10_credible_selector_validation_v1',
               status='PRE_RUN_PREDICTION_FROZEN',
               identity=dict(costs='B9-r2 run 01 operation costs', rule='credible_plan_selector_v2',
                             b9_result_sha256=core.sha256(core.B9_RESULT),
                             reserve=dict(RE_ms=core.RE_MS, RU_ms=core.RU_MS,
                                          refresh_reserve=False),
                             delta_ms=core.DELTA_MS),
               note='160/150 have no measured target-condition costs; these are extrapolations '
                    'from B9 180 and B9 140 costs, not target-domain validation',
               segments={})
    for cell in plan.CELLS:
        seg = {}
        for source in (180.0, 140.0):
            src = b9[(cell['plan'], source)]
            for kind in ('typical', 'stress'):
                seg['%s|b9@%g|%s' % (cell['id'], source, kind)] = rows_for(cell, src, kind, 'b9@%g' % source)
        doc['segments'][cell['id']] = seg
    doc['fingerprint'] = hashlib.sha256(json.dumps(doc, sort_keys=True,
                                                   separators=(',', ':')).encode()).hexdigest()
    out = HERE / 'prediction' / 'PREDICTION.json'
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n')
    freeze = dict(schema='m3_b10_selection_freeze_v1',
                  rule='credible_plan_selector_v2',
                  reserve=dict(RE_ms=core.RE_MS, RU_ms=core.RU_MS, refresh_reserve=False),
                  delta_ms=core.DELTA_MS,
                  by_budget={'160': dict(status='SELECTED', selected='two_9_9'),
                             '150': dict(status='NO_ACCEPTABLE_PLAN_UNDER_RULE', selected=None)},
                  note='recorded before each segment; it does not change the executed matrix')
    freeze['fingerprint'] = hashlib.sha256(json.dumps(freeze, sort_keys=True,
                                                      separators=(',', ':')).encode()).hexdigest()
    (HERE / 'prediction' / 'SELECTION_FREEZE.json').write_text(
        json.dumps(freeze, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(rows=sum(len(v) for s in doc['segments'].values() for v in s.values()),
                          segments=len(doc['segments']),
                          prediction_sha=sha(out),
                          selection_sha=sha(HERE / 'prediction' / 'SELECTION_FREEZE.json'),
                          fingerprint=doc['fingerprint']), indent=2))


if __name__ == '__main__':
    main()
