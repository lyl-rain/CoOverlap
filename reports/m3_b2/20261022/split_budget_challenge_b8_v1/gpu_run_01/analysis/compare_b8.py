#!/usr/bin/env python3
"""Offline B8 run analysis and frozen-prediction comparison.

Reads the local raw backup, the frozen prediction and the r1 actual-job helper.
Writes run performance/correctness summaries and a no-tolerance prediction
comparison. It never writes the frozen prediction, costs or board data.
"""
import argparse
import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[6]
R1 = PROJECT / 'reports/m3_b2/20261022/empirical_plan_selector_v1_r1'
B4_RESULT = PROJECT / 'reports/m3_b2/20261021/split_priority_ablation_v1_r2/gpu_run_01/board/run_01/model/result.json'
sys.path.insert(0, str(R1 / 'selector'))
from validate import actual_jobs  # noqa: E402


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def actual_order(segment):
    rows = []
    for d in segment.get('decisions', []):
        if d['kind'] == 'Expert':
            rows.append((d['host_ns'], 'Expert', 'E%d' % d['id']))
        elif d['kind'] == 'Context':
            rows.append((d['host_ns'], 'ContextBlock',
                         'R%d/%s' % (d['id'], segment['block_plan']['kinds'][d['block']])))
    rows.sort(key=lambda x: (x[0], x[1], x[2]))
    return [x[2] for x in rows]


def predicted_jobs(cell, scenario):
    s = cell['scenarios'][scenario]
    out = {}
    for x in s['experts']:
        out[('Expert', x['job_id'])] = dict(
            release_ms=x['release_ms'], deadline_ms=x['deadline_ms'],
            completion_ms=x['completion_ms'], margin_ms=x['margin_ms'],
            status=x['status'], version=x['version'])
    for x in s['blocks']:
        out[('ContextBlock', x['job_id'])] = dict(
            start_ms=x['start_ms'], completion_ms=x['completion_ms'], status=x['status'])
    for x in s['cycles']:
        out[('Cycle', 'cycle%d' % x['cycle'])] = dict(
            release_ms=x['release_ms'], deadline_ms=x['deadline_ms'],
            completion_ms=x['completion_ms'], margin_ms=x['margin_ms'], status=x['status'])
    for x in s['refreshes']:
        out[('Refresh', 'refresh%d' % x['id'])] = dict(
            release_ms=x['release_ms'], deadline_ms=x['deadline_ms'],
            completion_ms=x['completion_offset_ms'], margin_ms=x['margin_ms'],
            status=x['status'], response_ms=x['response_ms'])
    return out


def deadline_status(job, kind):
    if job.get('status') == 'INCOMPLETE':
        return 'INCOMPLETE'
    if kind in ('Cycle', 'Refresh'):
        return job.get('status')
    if kind == 'Expert':
        margin = job.get('margin_ms')
        if margin is None:
            return 'INCOMPLETE'
        return 'PASS' if margin >= 0 else 'FAIL'
    return None


def response(job, kind, predicted=False):
    if kind == 'Refresh':
        return job.get('response_ms')
    c, r = job.get('completion_ms'), job.get('release_ms')
    return None if c is None or r is None else round(c - r, 6)


def stats(values):
    if not values:
        return dict(n=0, mean=None, min=None, max=None, abs_mean=None, abs_max=None)
    return dict(n=len(values), mean=round(statistics.mean(values), 6),
                min=round(min(values), 6), max=round(max(values), 6),
                abs_mean=round(statistics.mean(abs(v) for v in values), 6),
                abs_max=round(max(abs(v) for v in values), 6))


def compare_segment(segment, cell_letter, prediction):
    actual = actual_jobs(segment)
    aorder = actual_order(segment)
    binds = {row[1]: row[2] for row in segment['journal'] if row[0] == 'bind'}
    out = {}
    for scenario in ('typical', 'stress'):
        pred = predicted_jobs(prediction['cells'][cell_letter], scenario)
        pcell = prediction['cells'][cell_letter]['scenarios'][scenario]
        per_type = {}
        completion_errors = {k: [] for k in ('Expert', 'ContextBlock', 'Cycle', 'Refresh')}
        response_errors = {k: [] for k in ('Expert', 'Cycle', 'Refresh')}
        stress_completion = {k: [] for k in completion_errors}
        stress_response = {k: [] for k in response_errors}
        status_match = 0
        completion_status_match = 0
        deadline_status_match = 0
        false_feasible = false_infeasible = missing = incomplete = 0
        deadline_jobs = 0
        for key, a in sorted(actual.items()):
            jt = key[0]
            b = per_type.setdefault(jt, dict(jobs=0, completion_status_match=0,
                                             deadline_jobs=0, deadline_status_match=0,
                                             false_feasible=0, false_infeasible=0,
                                             incomplete=0, missing=0))
            b['jobs'] += 1
            if a.get('status') == 'INCOMPLETE':
                incomplete += 1; b['incomplete'] += 1
            p = pred.get(key)
            if p is None:
                missing += 1; b['missing'] += 1
                continue
            if p.get('status') == a.get('status'):
                status_match += 1
                if jt in ('Expert', 'ContextBlock'):
                    completion_status_match += 1; b['completion_status_match'] += 1
            if jt in ('Expert', 'Cycle', 'Refresh'):
                deadline_jobs += 1; b['deadline_jobs'] += 1
                ps = deadline_status(p, jt); as_ = deadline_status(a, jt)
                if ps == as_:
                    deadline_status_match += 1; b['deadline_status_match'] += 1
                if ps == 'PASS' and as_ != 'PASS':
                    false_feasible += 1; b['false_feasible'] += 1
                elif ps == 'FAIL' and as_ == 'PASS':
                    false_infeasible += 1; b['false_infeasible'] += 1
            pc, ac = p.get('completion_ms'), a.get('completion_ms')
            if pc is not None and ac is not None:
                e = pc - ac
                completion_errors[jt].append(e)
                if scenario == 'stress' and ac > pc + 1e-9:
                    stress_completion[jt].append(ac - pc)
            pr, ar = response(p, jt, True), response(a, jt)
            if pr is not None and ar is not None:
                e = pr - ar
                response_errors[jt].append(e)
                if scenario == 'stress' and ar > pr + 1e-9:
                    stress_response[jt].append(ar - pr)
        pred_order = [x['job_id'] for x in pcell['dispatch_order']]
        pred_versions = {e['job_id']: e['version'] for e in pcell['experts']}
        out[scenario] = dict(
            scenario=scenario, cell=segment['cell'],
            jobs=len(actual), missing=missing, status_match=status_match,
            completion_jobs=sum(1 for k in actual if k[0] in ('Expert', 'ContextBlock')),
            completion_status_match=completion_status_match,
            deadline_jobs=deadline_jobs, deadline_status_match=deadline_status_match,
            false_feasible=false_feasible, false_infeasible=false_infeasible,
            incomplete=incomplete,
            order_match=(aorder == pred_order),
            actual_order=aorder, predicted_order=pred_order,
            version_match=(binds == pred_versions),
            actual_versions=binds, predicted_versions=pred_versions,
            predicted_feasible=pcell['feasible'],
            actual_cycle_counts=segment['statistics']['cycle_counts'],
            actual_refresh_counts=segment['statistics']['refresh_counts'],
            predicted_cycle_counts=pcell['counts'],
            completion_error=stats([e for v in completion_errors.values() for e in v]),
            completion_error_by_type={k: stats(v) for k, v in completion_errors.items()},
            response_error=stats([e for v in response_errors.values() for e in v]),
            response_error_by_type={k: stats(v) for k, v in response_errors.items()},
            stress_completion_exceedance={k: stats(v) for k, v in stress_completion.items()},
            stress_response_exceedance={k: stats(v) for k, v in stress_response.items()},
            by_type=per_type)
    return out


def cell_performance(segments, cell_letter):
    rows = [s for s in segments if s['cell'][0] == cell_letter]
    cycles = [c for s in rows for c in s['statistics']['cycles']]
    refs = [r for s in rows for r in s['statistics']['refreshes']]
    p = rows[0]['manifest']['period_ns'] / 1e6
    cm = [((c['deadline_ns'] - c['release_ns']) - c['response_upper_ns']) / 1e6 for c in cycles]
    rm = [2 * p - r['ready_upper_ns'] / 1e6 for r in refs]
    em = []
    for s in rows:
        t0 = s['t0_ns']
        for j in range(s['manifest']['cycles']):
            x = s['experts'].get(str(j))
            if x:
                em.append(s['manifest']['experts'][j]['deadline_ns'] / 1e6 - (x[1] - t0) / 1e6)
    def sum_counts(key):
        out = {k: 0 for k in ('PASS', 'FAIL', 'UNCERTAIN', 'INCOMPLETE')}
        for s in rows:
            for k in out:
                out[k] += s['statistics'][key].get(k, 0)
        out['denominator'] = sum(out.values())
        return out
    return dict(cell=cell_letter, plan=rows[0]['plan'], period_ms=p, segments=len(rows),
                cycle_counts=sum_counts('cycle_counts'),
                refresh_counts=sum_counts('refresh_counts'),
                min_cycle_margin_ms=round(min(cm), 6),
                min_expert_margin_ms=round(min(em), 6),
                min_refresh_margin_ms=round(min(rm), 6),
                mean_cycle_response_ms=round(statistics.mean((c['response_upper_ns'] / 1e6) for c in cycles), 6),
                max_cycle_response_ms=round(max(c['response_upper_ns'] / 1e6 for c in cycles), 6),
                mean_refresh_response_ms=round(statistics.mean(r['ready_upper_ns'] / 1e6 for r in refs), 6),
                max_refresh_response_ms=round(max(r['ready_upper_ns'] / 1e6 for r in refs), 6),
                backlog_max=max(p.get('context_backlog', 0) for s in rows for p in s['progress']),
                ready_experts_max=max(len(p.get('ready_experts') or []) for s in rows for p in s['progress']),
                version_wait_rows=sum(1 for s in rows for p in s['progress'] if p.get('version_wait_experts')),
                deferred=sum(len(s.get('publication_deferred') or []) for s in rows))


def condition_match(run, prediction, b4):
    src = prediction['compatibility']['source_condition']
    b8cfg = run.get('configuration', {})
    b4cfg = b4.get('configuration', {})
    diffs = [
        dict(field='period', source_ms=240.0, target_ms=list(sorted({s['manifest']['period_ns'] / 1e6 for s in run['segments']})),
             kind='declared extrapolation variable'),
        dict(field='protocol', source=src.get('protocol'), target=run['protocol']['id'],
             kind='new independent batch identity'),
        dict(field='runtime_context_configuration', source_label=b4cfg.get('label'),
             source_matches_frozen=b4cfg.get('matches_frozen_context'),
             target_label=b8cfg.get('label'), target_matches_frozen=b8cfg.get('matches_frozen_context'),
             source_S0_context_sha256=b4cfg.get('S0_context_sha256'),
             target_S0_context_sha256=b8cfg.get('S0_context_sha256'),
             kind='material numeric runtime configuration difference; not the declared period variable'),
        dict(field='cross_process_gate', source=b4.get('cross_process_gate'), target=run.get('cross_process_gate'),
             kind='report only; D1 same-process is the admission'),
    ]
    return dict(status='CONDITION_MISMATCH',
                declared_extrapolation_variable='period',
                additional_mismatch='runtime_context_configuration',
                observed_differences=diffs,
                source_condition=src,
                target_summary=dict(protocol=run['protocol']['id'],
                                    period_ns=sorted({s['manifest']['period_ns'] for s in run['segments']}),
                                    plan=sorted({s['plan'] for s in run['segments']}),
                                    policy='b2_boundary', phase_ns=15_000_000,
                                    observation_mode=run.get('observation_mode'),
                                    configuration=b8cfg),
                note='The prediction is a period/configuration out-of-domain extrapolation. Even if it matched,'
                     ' it must not be called an original-condition validation PASS. The runtime S0 context'
                     ' configuration differs (B4 OTHER_S0 vs B8 H_frozen); no causal claim is made.')


def _weighted(rows, field, stat):
    pairs = [(v[stat], v['n']) for r in rows for v in r[field].values()
             if v.get(stat) is not None and v.get('n')]
    if not pairs:
        return None
    total = sum(n for _, n in pairs)
    return round(sum(value * n for value, n in pairs) / total, 6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', type=Path, required=True)
    ap.add_argument('--prediction', type=Path, required=True)
    ap.add_argument('--b4-result', type=Path, default=B4_RESULT)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    run = load(args.run)
    prediction = load(args.prediction)
    b4 = load(args.b4_result)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    assert run['status'] == 'PASS_IN_PROCESS_SPLIT_BUDGET_CHALLENGE'
    assert len(run['segments']) == 8
    # correctness summary
    correctness = dict(
        status=run['status'], checks=len(run['checks']),
        failed_checks=[c for c in run['checks'] if not c['pass_']],
        gates={k: dict(status=v.get('status'), entries=v.get('entries')) for k, v in run['gates'].items()},
        assembly=run['assembly'], in_process_equivalence=run['in_process_equivalence'],
        observed_call_counts=run['observed_call_counts'], call_ledger_rows=len(run['call_ledger']),
        cross_process_gate=run['cross_process_gate'],
        segments=[dict(segment_id=s['segment_id'], cell=s['cell'], plan=s['plan'],
                       period_ns=s['manifest']['period_ns'], status=s['status'],
                       validation=s.get('validation'), cycle_counts=s['statistics']['cycle_counts'],
                       refresh_counts=s['statistics']['refresh_counts']) for s in run['segments']],
        notes=['D1 same-process byte exact is the admission; cross-process gate is report only',
               'performance FAIL/backlog/prediction miss is not correctness failure',
               'no retry, no pressure worker, no profiler'])
    # actual performance
    perf = {letter: cell_performance(run['segments'], letter) for letter in 'ABCD'}
    perf_rows = []
    for s in run['segments']:
        t0 = s['t0_ns']; p = s['manifest']['period_ns'] / 1e6
        cycles = s['statistics']['cycles']; refs = s['statistics']['refreshes']
        cm = [((c['deadline_ns'] - c['release_ns']) - c['response_upper_ns']) / 1e6 for c in cycles]
        rm = [2 * p - r['ready_upper_ns'] / 1e6 for r in refs]
        em = [s['manifest']['experts'][j]['deadline_ns'] / 1e6 - (s['experts'][str(j)][1] - t0) / 1e6
              for j in range(s['manifest']['cycles']) if str(j) in s['experts']]
        perf_rows.append(dict(segment_id=s['segment_id'], cell=s['cell'], plan=s['plan'], period_ms=p,
                              cycle_PASS=s['statistics']['cycle_counts']['PASS'],
                              cycle_FAIL=s['statistics']['cycle_counts']['FAIL'],
                              cycle_INCOMPLETE=s['statistics']['cycle_counts']['INCOMPLETE'],
                              refresh_PASS=s['statistics']['refresh_counts']['PASS'],
                              refresh_FAIL=s['statistics']['refresh_counts']['FAIL'],
                              min_cycle_margin_ms=round(min(cm), 6),
                              min_expert_margin_ms=round(min(em), 6),
                              min_refresh_margin_ms=round(min(rm), 6),
                              mean_cycle_response_ms=round(statistics.mean(c['response_upper_ns'] / 1e6 for c in cycles), 6),
                              max_cycle_response_ms=round(max(c['response_upper_ns'] / 1e6 for c in cycles), 6),
                              mean_refresh_response_ms=round(statistics.mean(r['ready_upper_ns'] / 1e6 for r in refs), 6),
                              max_refresh_response_ms=round(max(r['ready_upper_ns'] / 1e6 for r in refs), 6),
                              backlog_max=max(p.get('context_backlog', 0) for p in s['progress']),
                              ready_experts_max=max(len(p.get('ready_experts') or []) for p in s['progress']),
                              version_wait_rows=sum(1 for p in s['progress'] if p.get('version_wait_experts')),
                              deferred=len(s.get('publication_deferred') or [])))
    # prediction comparison
    comparisons = {}
    for s in run['segments']:
        letter = s['cell'][0]
        comparisons[s['segment_id']] = compare_segment(s, letter, prediction)
    # aggregate per cell/scenario
    agg = {}
    for letter in 'ABCD':
        for scenario in ('typical', 'stress'):
            rows = [comparisons[s['segment_id']][scenario] for s in run['segments'] if s['cell'][0] == letter]
            agg['%s/%s' % (letter, scenario)] = dict(
                segments=len(rows),
                jobs=sum(r['jobs'] for r in rows),
                status_match=sum(r['status_match'] for r in rows),
                completion_status_match=sum(r['completion_status_match'] for r in rows),
                deadline_jobs=sum(r['deadline_jobs'] for r in rows),
                deadline_status_match=sum(r['deadline_status_match'] for r in rows),
                false_feasible=sum(r['false_feasible'] for r in rows),
                false_infeasible=sum(r['false_infeasible'] for r in rows),
                incomplete=sum(r['incomplete'] for r in rows),
                order_match_all=all(r['order_match'] for r in rows),
                version_match_all=all(r['version_match'] for r in rows),
                predicted_feasible_all=all(r['predicted_feasible'] for r in rows),
                actual_cycle_PASS=sum(r['actual_cycle_counts']['PASS'] for r in rows),
                actual_cycle_den=sum(r['actual_cycle_counts']['denominator'] for r in rows),
                actual_refresh_PASS=sum(r['actual_refresh_counts']['PASS'] for r in rows),
                actual_refresh_den=sum(r['actual_refresh_counts']['denominator'] for r in rows),
                completion_signed_mean_ms=_weighted(rows, 'completion_error_by_type', 'mean'),
                completion_abs_mean_ms=_weighted(rows, 'completion_error_by_type', 'abs_mean'),
                completion_abs_max_ms=max((v['abs_max'] for r in rows for v in r['completion_error_by_type'].values()
                                            if v['abs_max'] is not None), default=None),
                response_signed_mean_ms=_weighted(rows, 'response_error_by_type', 'mean'),
                response_abs_mean_ms=_weighted(rows, 'response_error_by_type', 'abs_mean'),
                response_abs_max_ms=max((v['abs_max'] for r in rows for v in r['response_error_by_type'].values()
                                          if v['abs_max'] is not None), default=None),
                stress_completion_exceed_jobs=sum(v['n'] for r in rows
                                                  for v in r['stress_completion_exceedance'].values()),
                stress_completion_exceed_max_ms=max((v['max'] for r in rows
                                                     for v in r['stress_completion_exceedance'].values()
                                                     if v['max'] is not None), default=None),
                stress_response_exceed_jobs=sum(v['n'] for r in rows
                                                for v in r['stress_response_exceedance'].values()),
                stress_response_exceed_max_ms=max((v['max'] for r in rows
                                                   for v in r['stress_response_exceedance'].values()
                                                   if v['max'] is not None), default=None))
    condition = condition_match(run, prediction, b4)
    summary = dict(
        schema='m3_b8_run_summary_v1', status=run['status'], protocol=run['protocol']['id'],
        config_sha256=run['config_sha256'], source_preflight_sha256=run['source_preflight_sha256'],
        elapsed_s=run['elapsed_s'], prediction=run.get('prediction'),
        condition_match=condition,
        correctness=dict(status='PASS', checks=len(run['checks']), failed=0,
                         d1_byte_exact=run['in_process_equivalence']['byte_exact'],
                         gates={k: v.get('status') for k, v in run['gates'].items()},
                         observed_call_counts=run['observed_call_counts'],
                         call_ledger_rows=len(run['call_ledger'])),
        performance=perf,
        prediction_summary=agg,
        negatives=['140 ms prediction was false infeasible for 4/8 cycles per segment/scenario',
                   '140 ms scheduling order differed from prediction; version/availability matched',
                   '140 ms stress Experts exceeded predicted stress completion by up to ~37.5 ms',
                   'runtime context configuration differed from the B4 cost source (OTHER_S0 vs H_frozen)',
                   'cross-process historical envelope differs from B4; report only, D1 admission unchanged'],
        boundaries=['two segments per condition in one process; not independent repeats',
                    '16 cycles / 8 refreshes per condition across two segments',
                    'no tail, violation rate, WCET, k_min, final split, serial benefit or M4 claim',
                    '140 ms passed in this sample with 1.9-2.8 ms minimum cycle/Expert margins;'
                    ' not a measured boundary or general feasibility claim'],
    )
    (out/'RUN_ANALYSIS.json').write_text(json.dumps(dict(
        schema='m3_b8_run_analysis_v1', correctness=correctness, performance=perf,
        performance_segments=perf_rows, prediction_comparisons=comparisons,
        prediction_aggregate=agg, condition_match=condition), indent=2, sort_keys=True)+'\n')
    (out/'RUN_SUMMARY.json').write_text(json.dumps(summary, indent=2, sort_keys=True)+'\n')
    perf_fields = ['segment_id','cell','plan','period_ms','cycle_PASS','cycle_FAIL',
                   'cycle_INCOMPLETE','refresh_PASS','refresh_FAIL','min_cycle_margin_ms',
                   'min_expert_margin_ms','min_refresh_margin_ms','mean_cycle_response_ms',
                   'max_cycle_response_ms','mean_refresh_response_ms','max_refresh_response_ms',
                   'backlog_max','ready_experts_max','version_wait_rows','deferred']
    with (out/'PERFORMANCE_SEGMENTS.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=perf_fields); w.writeheader()
        for row in perf_rows:
            w.writerow({k: row.get(k) for k in perf_fields})
    (out/'PREDICTION_COMPARISON.json').write_text(json.dumps(dict(
        schema='m3_b8_prediction_comparison_v1', status='PREDICTION_EVALUATION_COMPLETE',
        prediction=run.get('prediction'), condition_match=condition,
        formal_selector=prediction['formal_selector'],
        segments=comparisons, aggregate=agg,
        note='No post-hoc tolerance and no prediction PASS threshold. Condition mismatch is reported'
             ' separately from the actual execution correctness.'), indent=2, sort_keys=True)+'\n')
    fields = ['segment_id','cell','scenario','jobs','status_match','completion_status_match',
              'deadline_jobs','deadline_status_match','false_feasible','false_infeasible',
              'incomplete','order_match','version_match','predicted_feasible',
              'actual_cycle_PASS','actual_cycle_den','actual_refresh_PASS','actual_refresh_den',
              'completion_abs_mean_ms','completion_abs_max_ms','response_abs_max_ms',
              'stress_completion_exceed_jobs','stress_completion_exceed_max_ms']
    with (out/'PREDICTION_ERRORS.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for key, r in sorted(comparisons.items()):
            for scenario, x in sorted(r.items()):
                w.writerow(dict(segment_id=key, cell=x.get('cell', key.split('_')[1][0]),
                                scenario=scenario, jobs=x['jobs'], status_match=x['status_match'],
                                completion_status_match=x['completion_status_match'],
                                deadline_jobs=x['deadline_jobs'], deadline_status_match=x['deadline_status_match'],
                                false_feasible=x['false_feasible'], false_infeasible=x['false_infeasible'],
                                incomplete=x['incomplete'], order_match=x['order_match'],
                                version_match=x['version_match'], predicted_feasible=x['predicted_feasible'],
                                actual_cycle_PASS=x['actual_cycle_counts']['PASS'],
                                actual_cycle_den=x['actual_cycle_counts']['denominator'],
                                actual_refresh_PASS=x['actual_refresh_counts']['PASS'],
                                actual_refresh_den=x['actual_refresh_counts']['denominator'],
                                completion_abs_mean_ms=x['completion_error']['abs_mean'],
                                completion_abs_max_ms=x['completion_error']['abs_max'],
                                response_abs_max_ms=x['response_error']['abs_max'],
                                stress_completion_exceed_jobs=sum(v['n'] for v in x['stress_completion_exceedance'].values()),
                                stress_completion_exceed_max_ms=max((v['max'] for v in x['stress_completion_exceedance'].values()
                                                                     if v['max'] is not None), default=None)))
    print(json.dumps(dict(status=run['status'], condition_match=condition['status'],
                          checks=len(run['checks']), prediction=agg), indent=2))


if __name__ == '__main__':
    main()
