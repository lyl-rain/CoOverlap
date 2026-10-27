#!/usr/bin/env python3
"""Supplemental B5/B6/B7 replay: own-batch costs, own condition, no pooling."""
import json
import statistics
from pathlib import Path

from evidence import B5_RESULT, B6_RESULT, B7_RESULT, cost_rows, scenario_from_rows, sha
from evaluator import evaluate
from validate import actual_jobs, predicted_jobs

CASES = [
    ('B5_D180_two_boundary', B5_RESULT, 'p1_D_p180_boundary', 'p2_D_p180_boundary', 180.0),
    ('B6_B180_two_boundary', B6_RESULT, 'p1_B_quiet_boundary', 'p2_B_quiet_boundary', 180.0),
    ('B7_A180_10ms_two_boundary', B7_RESULT, 'p1_A_lead10ms', 'p4_A_lead10ms', 180.0),
    ('B7_B180_4s_two_boundary', B7_RESULT, 'p2_B_lead4s', 'p3_B_lead4s', 180.0),
]


def run_case(label, result_path, train_id, val_id, period):
    data = json.loads(Path(result_path).read_text())
    train = next(s for s in data['segments'] if s['segment_id'] == train_id)
    val = next(s for s in data['segments'] if s['segment_id'] == val_id)
    rows = cost_rows(train)
    base = scenario_from_rows(rows)[train['plan']]
    out = {}
    for kind in ('typical', 'stress'):
        sc = json.loads(json.dumps(base)); sc['kind'] = kind
        pred = evaluate(train['plan'], sc, policy='b2_boundary', cycles=train['manifest']['cycles'],
                        period=period, phase=train['manifest']['phase_ns']/1e6,
                        gap_ms=0.041, publish_cost_ms=0.012)
        pj = predicted_jobs(pred); aj = actual_jobs(val)
        errors=[]; matches=0; missing=0
        for key, a in aj.items():
            p=pj.get(key)
            if p is None: missing+=1; continue
            pc=p.get('completion_ms'); ac=a.get('completion_ms')
            if pc is not None and ac is not None: errors.append(abs(pc-ac))
            if p.get('status')==a.get('status'): matches+=1
        out[kind]=dict(model_status=pred['status'], feasible=pred['feasible'],
                       min_cycle_margin_ms=pred['min_cycle_margin_ms'],
                       min_expert_margin_ms=pred['min_expert_margin_ms'],
                       min_refresh_margin_ms=pred['min_refresh_margin_ms'],
                       max_refresh_ready_ms=pred['max_refresh_ready_ms'],
                       actual_cycle_counts=val['statistics']['cycle_counts'],
                       actual_refresh_counts=val['statistics']['refresh_counts'],
                       status_match=matches, actual_jobs=len(aj), missing=missing,
                       mean_abs_completion_error_ms=round(statistics.mean(errors),6) if errors else None,
                       max_abs_completion_error_ms=round(max(errors),6) if errors else None)
    return dict(label=label, result=str(result_path), result_sha256=sha(result_path),
                train_segment=train_id, validation_segment=val_id,
                period_ms=period, phase_ms=train['manifest']['phase_ns']/1e6,
                sample_in_batch=True, scenarios=out,
                boundary='own-batch costs, same batch/condition; not pooled with B4; not a selection')


def main(out_dir):
    out_dir=Path(out_dir).resolve(); out_dir.mkdir(parents=True,exist_ok=False)
    results=[run_case(*c) for c in CASES]
    (out_dir/'SUPPLEMENTAL.json').write_text(json.dumps(dict(schema='m3_b2_empirical_plan_selector_supplemental_v1',cases=results),indent=2,sort_keys=True)+'\n')
    lines=['# Supplemental B5/B6/B7 replay','',
           'Each case uses its own batch and own condition; costs are not pooled with B4. This is sample-in-batch replay, not independent validation and not a selection.','',
           '| case | train → validation | P | model feasible | actual cycles | actual refresh | status match | mean/max abs ms |','|---|---|---:|---|---|---|---:|---|']
    for r in results:
        s=r['scenarios']['typical']; a=s['actual_cycle_counts']; f=s['actual_refresh_counts']
        lines.append('| %s | %s → %s | %.0f | %s | %d/%d | %d/%d | %d/%d | %s / %s |'%(
            r['label'],r['train_segment'],r['validation_segment'],r['period_ms'],s['feasible'],
            a.get('PASS',0),a.get('denominator',0),f.get('PASS',0),f.get('denominator',0),
            s['status_match'],s['actual_jobs'],s['mean_abs_completion_error_ms'],s['max_abs_completion_error_ms']))
    lines+=['','Boundary: B5/B6/B7 are two-plan only; no three-plan 180 ms evidence. B7 A/B startup conditions and B6 fixed/quiet conditions differ; their margins do not enter the B4 selector.','']
    (out_dir/'SUPPLEMENTAL.md').write_text('\n'.join(lines))
    print(json.dumps(dict(status='PASS',cases=len(results),out=str(out_dir)),indent=2))

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,required=True); a=ap.parse_args(); main(a.out)
