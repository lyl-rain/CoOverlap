#!/usr/bin/env python3
"""Run the bounded action-level DFS on the 12 fixed segments."""
from __future__ import annotations
import csv, json, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'lsg2')); sys.path.insert(0, str(HERE / 'gap'))
import inputs, search  # noqa: E402

OUT = HERE / 'outputs'


def main():
    OUT.mkdir(exist_ok=True)
    rows, schedules, coverage = [], [], []
    for tag, sid in inputs.SEGMENTS:
        result, seg = inputs.load(tag, sid)
        ops, extra = inputs.costs(seg)
        plan, period = seg['plan'], seg['period_ns'] / 1e6
        base_r = search.replay(plan, period, extra, [], stop=False)
        base = inputs.metrics(plan, period, base_r)
        print('START', sid, flush=True)
        stats, best = search.search_segment(plan, period, extra, base)
        print('DONE', sid, stats['stop_reason'], stats['nodes_expanded'], 'nodes',
              round(stats['elapsed_s'], 3), 's', 'improvement', bool(best), flush=True)
        default_trace, dstat = search.default_action_trace(plan, period, extra)
        assert dstat == base_r.status == 'DRAINED'
        entry = dict(segment=tag, segment_id=sid, plan=plan, period_ms=period,
                     baseline=dict(status=base['status'], complete=base['complete'],
                                   cycle_fail=base['cycle_fail'], expert_fail=base['expert_fail'],
                                   refresh_fail=base['refresh_fail'], MC=base['MC'], ME=base['ME'],
                                   MU=base['MU'], MR=base['MR'],
                                   worst_cycle_response=base['worst_cycle_response'],
                                   max_refresh_response=base['max_refresh_response']),
                     search=stats, improvement=None)
        if best:
            div = search.first_divergence(best['prefix'], default_trace)
            playback = search.replay(plan, period, extra, best['prefix'], stop=False)
            pb = inputs.metrics(plan, period, playback)
            entry['improvement'] = dict(verdict=best['verdict'], prefix=best['prefix'],
                                        realization='HINDSIGHT_SEQUENCE_NOT_A_RUNTIME_POLICY',
                                        first_divergence=div, metrics=pb,
                                        replay_consistent=(pb == best['metrics']))
        schedules.append(entry)
        coverage.append(dict(segment=tag, segment_id=sid, **stats,
                             search_complete=(stats['stop_reason'] == 'COMPLETE'),
                             improvement_found=bool(best)))
        for label, m in (('baseline', base), ('best', best['metrics'] if best else None)):
            if m is None:
                continue
            rows.append(dict(segment=tag, segment_id=sid, plan=plan, period_ms=period, which=label,
                             status=m['status'], complete=m['complete'],
                             cycle_fail=m['cycle_fail'], expert_fail=m['expert_fail'],
                             refresh_fail=m['refresh_fail'], MC=m['MC'], ME=m['ME'], MU=m['MU'],
                             MR=m['MR'], worst_cycle_response=m['worst_cycle_response'],
                             max_refresh_response=m['max_refresh_response'],
                             improvement=entry['improvement']['verdict'] if entry['improvement'] else ''))
    with (OUT / 'BASELINE_VS_SEARCH.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (OUT / 'SCHEDULES.json').write_text(json.dumps(dict(schema='lsg_r2_schedules_v1',
        note='action-level E/C/I DFS; NO dedup/pruning; exact in-memory completion times; shared transition core',
        segments=schedules), indent=2, sort_keys=True) + '\n')
    (OUT / 'SEARCH_COVERAGE.json').write_text(json.dumps(dict(schema='lsg_r2_coverage_v1',
        node_cap=search.NODE_CAP, wall_cap_s=search.WALL_CAP_S, segments=coverage,
        summary=dict(complete=sum(1 for c in coverage if c['search_complete']),
                     truncated=sum(1 for c in coverage if not c['search_complete']),
                     improving=sum(1 for c in coverage if c['improvement_found']))),
        indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(segments=len(coverage),
        complete=sum(1 for c in coverage if c['search_complete']),
        truncated=sum(1 for c in coverage if not c['search_complete']),
        improving=sum(1 for c in coverage if c['improvement_found']),
        nodes=sum(c['nodes_expanded'] for c in coverage),
        elapsed=round(sum(c['elapsed_s'] for c in coverage), 2)), indent=2))
    for c in coverage:
        print(c['segment'], c['stop_reason'], 'nodes', c['nodes_expanded'],
              'term', c['terminal_schedules'], 'inv', c['invalid_branches'],
              't %.2f' % c['elapsed_s'], 'improved', c['improvement_found'])


if __name__ == '__main__':
    main()
