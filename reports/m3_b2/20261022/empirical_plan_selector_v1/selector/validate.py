"""Freeze-first validation on B4 pass 2 (candidate cells D/B only).

This module reads costs/rules only after verifying their frozen SHA.  It never
re-estimates costs or uses validation outcomes to tune the model.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

from evidence import B4_RESULT, B4_CANDIDATE_CELLS, sha
from evaluator import evaluate
from selection import CANDIDATES, POLICY, TARGET, scenario_for

BLOCK_LABELS = {'two_9_9': ('B1', 'B2'), 'three_prefix_9_9': ('P', 'B1', 'B2')}


def _ms(v):
    return round(v / 1e6, 6)


def actual_jobs(segment):
    t0 = segment['t0_ns']; m = segment['manifest']; p = m['period_ns'] / 1e6
    actual = {}
    for j in range(m['cycles']):
        x = segment.get('experts', {}).get(str(j))
        deadline = m['experts'][j]['deadline_ns'] / 1e6
        completion = None if x is None else _ms(x[1] - t0)
        actual[('Expert', 'E%d' % j)] = dict(release_ms=round(m['experts'][j]['release_ns'] / 1e6, 6),
                                            deadline_ms=round(deadline, 6),
                                            completion_ms=completion,
                                            status='COMPLETE' if x is not None else 'INCOMPLETE',
                                            margin_ms=None if completion is None else round(deadline - completion, 6))
    for q in range(m['cycles'] // 2):
        for b, label in enumerate(BLOCK_LABELS[segment['plan']]):
            x = segment.get('blocks', {}).get('(%d, %d)' % (q, b))
            actual[('ContextBlock', 'R%d/%s' % (q, label))] = dict(
                start_ms=None if x is None else _ms(x[0] - t0), completion_ms=None if x is None else _ms(x[1] - t0),
                status='COMPLETE' if x is not None else 'INCOMPLETE')
    for c in segment['statistics']['cycles']:
        release_rel = (c['release_ns'] - t0) / 1e6
        deadline_rel = (c['deadline_ns'] - t0) / 1e6
        completion = release_rel + c['response_upper_ns'] / 1e6
        actual[('Cycle', 'cycle%d' % c['cycle'])] = dict(
            release_ms=round(release_rel, 6), deadline_ms=round(deadline_rel, 6),
            completion_ms=round(completion, 6), status=c['status'],
            margin_ms=round(deadline_rel - completion, 6),
            expert_ms=round(c['expert_response_upper_ns'] / 1e6, 6),
            vlm_ms=round(c['VLM_response_upper_ns'] / 1e6, 6))
    for r in segment['statistics']['refreshes']:
        rel = r['id'] * 2 * p
        deadline = rel + 2 * p
        actual[('Refresh', 'refresh%d' % r['id'])] = dict(
            release_ms=round(rel, 6), deadline_ms=round(deadline, 6),
            completion_ms=round(rel + r['ready_upper_ns'] / 1e6, 6), status=r['status'],
            margin_ms=round(deadline - (rel + r['ready_upper_ns'] / 1e6), 6))
    return actual


def predicted_jobs(result):
    jobs = {}
    for x in result['experts']:
        jobs[('Expert', x['job_id'])] = x
    for x in result['blocks']:
        jobs[('ContextBlock', x['job_id'])] = x
    for x in result['cycles']:
        jobs[('Cycle', 'cycle%d' % x['cycle'])] = dict(
            release_ms=x['release_ms'], deadline_ms=x['deadline_ms'],
            completion_ms=x['predicted_completion_ms'], margin_ms=x['predicted_margin_ms'],
            status=x['status'], expert_ms=x['expert_response_ms'], vlm_ms=x['vlm_response_ms'])
    for x in result['refreshes']:
        jobs[('Refresh', 'refresh%d' % x['id'])] = dict(
            release_ms=x['release_ms'], deadline_ms=x['deadline_ms'],
            completion_ms=x['predicted_completion_ms'], margin_ms=x['predicted_margin_ms'],
            status=x['status'])
    return jobs


def validate(costs_path, rules_path):
    costs_path = Path(costs_path); rules_path = Path(rules_path)
    costs = json.loads(costs_path.read_text()); rules = json.loads(rules_path.read_text())
    if costs.get('source', {}).get('result_sha256') != sha(B4_RESULT):
        raise ValueError('cost source result SHA differs from current B4 result')
    if rules.get('model_sha256') != sha(Path(__file__).resolve().parent/'plan_model.py'):
        raise ValueError('model SHA differs from frozen rule')
    data = json.loads(B4_RESULT.read_text())
    rows = []
    summaries = {}
    for plan in CANDIDATES:
        cell = B4_CANDIDATE_CELLS[plan]
        seg = next(s for s in data['segments'] if s['pass_'] == 2 and s['cell'] == cell)
        actual = actual_jobs(seg)
        for kind in ('typical', 'stress'):
            sc = scenario_for(costs, plan, kind)
            pred = evaluate(plan, sc, policy=POLICY, cycles=TARGET['cycles'],
                            period=TARGET['period_ms'], phase=TARGET['phase_ms'],
                            gap_ms=rules['model_constants']['gap_ms'],
                            publish_cost_ms=rules['model_constants']['publish_cost_ms'])
            pjobs = predicted_jobs(pred)
            key = '%s/%s' % (plan, kind)
            errs = []; status_match = 0; false_feas = 0; false_infeas = 0; missing = 0
            scenario_rows = 0
            for jt, jid in sorted(actual, key=lambda x: (x[0], x[1])):
                a = actual[(jt, jid)]; p = pjobs.get((jt, jid))
                scenario_rows += 1
                if p is None:
                    missing += 1
                    rows.append(dict(plan=plan, scenario=kind, segment_id=seg['segment_id'], job_type=jt,
                                     job_id=jid, predicted_status=None, actual_status=a['status'],
                                     match=False, predicted_completion_ms=None, actual_completion_ms=a['completion_ms'],
                                     error_ms=None, predicted_margin_ms=None, actual_margin_ms=a.get('margin_ms'),
                                     classification='UNPREDICTED'))
                    continue
                pc = p.get('completion_ms'); ac = a.get('completion_ms')
                error = None if pc is None or ac is None else round(pc - ac, 6)
                if error is not None: errs.append(abs(error))
                ps = p.get('status'); ass = a.get('status')
                match = ps == ass
                if match: status_match += 1
                cls = 'MATCH' if match else 'MISMATCH'
                if jt in ('Cycle', 'Refresh'):
                    if ps == 'PASS' and ass != 'PASS':
                        false_feas += 1; cls = 'FALSE_FEASIBLE'
                    elif ps == 'FAIL' and ass == 'PASS':
                        false_infeas += 1; cls = 'FALSE_INFEASIBLE'
                rows.append(dict(plan=plan, scenario=kind, segment_id=seg['segment_id'], job_type=jt,
                                 job_id=jid, predicted_status=ps, actual_status=ass, match=match,
                                 predicted_completion_ms=pc, actual_completion_ms=ac, error_ms=error,
                                 predicted_margin_ms=p.get('margin_ms'), actual_margin_ms=a.get('margin_ms'),
                                 classification=cls))
            summaries[key] = dict(plan=plan, scenario=kind, segment_id=seg['segment_id'],
                                  jobs=scenario_rows, predicted_jobs=len(pjobs), actual_jobs=len(actual),
                                  status_match=status_match, missing=missing, false_feasible=false_feas,
                                  false_infeasible=false_infeas,
                                  mean_abs_completion_error_ms=round(statistics.mean(errs), 6) if errs else None,
                                  max_abs_completion_error_ms=round(max(errs), 6) if errs else None,
                                  predicted_feasible=pred['feasible'], model_status=pred['status'],
                                  min_cycle_margin_ms=pred['min_cycle_margin_ms'],
                                  min_expert_margin_ms=pred['min_expert_margin_ms'],
                                  min_refresh_margin_ms=pred['min_refresh_margin_ms'])
    return dict(schema='m3_b2_empirical_plan_selector_validation_v1',
                validation='B4 pass 2 D/B; not used for costs',
                condition=TARGET, rows=rows, summaries=summaries,
                boundary='same-process sequential holdout, not independent repeat or external generalization',
                source=dict(cost_file=str(costs_path), cost_sha256=sha(costs_path),
                            rules_file=str(rules_path), rules_sha256=sha(rules_path),
                            b4_result=str(B4_RESULT), b4_result_sha256=sha(B4_RESULT)))


def write_validation(costs, rules, out_dir):
    import csv
    out_dir = Path(out_dir).resolve(); out_dir.mkdir(parents=True, exist_ok=False)
    v = validate(costs, rules)
    (out_dir/'VALIDATION.json').write_text(json.dumps(v, indent=2, sort_keys=True)+'\n')
    fields = ['plan','scenario','segment_id','job_type','job_id','predicted_status','actual_status','match',
              'predicted_completion_ms','actual_completion_ms','error_ms','predicted_margin_ms',
              'actual_margin_ms','classification']
    with (out_dir/'VALIDATION_JOBS.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for row in v['rows']: w.writerow({k: row.get(k) for k in fields})
    lines = ['# B4 holdout validation', '',
             'Validation = B4 pass 2 D/B. Costs/rules were frozen before this read.', '',
             '| plan | scenario | jobs | status match | false feasible | false infeasible | mean abs ms | max abs ms | model feasible |',
             '|---|---|---:|---:|---:|---:|---:|---:|---|']
    for key, s in sorted(v['summaries'].items()):
        lines.append('| %s | %s | %d | %d | %d | %d | %s | %s | %s |' % (
            s['plan'], s['scenario'], s['jobs'], s['status_match'], s['false_feasible'],
            s['false_infeasible'], s['mean_abs_completion_error_ms'], s['max_abs_completion_error_ms'],
            s['predicted_feasible']))
    lines += ['', 'Same-process sequential holdout; not independent repeat or external generalization. No cost/rule was re-estimated after this read.', '']
    (out_dir/'VALIDATION.md').write_text('\n'.join(lines))
    return v


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--costs', type=Path, required=True)
    ap.add_argument('--rules', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    v = write_validation(a.costs, a.rules, a.out)
    print(json.dumps({'status': 'VALIDATED', 'out': str(a.out), 'summaries': v['summaries']}, indent=2))
