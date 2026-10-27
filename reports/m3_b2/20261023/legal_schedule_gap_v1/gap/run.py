#!/usr/bin/env python3
"""Bounded legal-schedule comparison (global action policies) on 12 fixed segments."""
from __future__ import annotations
import csv, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'gap'))
import inputs  # noqa: E402

POLICIES = {
    'P0_default': dict(block_priority=False, tail_rule=None),
    'P1_context_first': dict(block_priority=True, tail_rule=None),
    'P2_delay_tail': dict(block_priority=False, tail_rule='delay_to_next_release'),
    'P3_context_first_delay': dict(block_priority=True, tail_rule='delay_to_next_release'),
}


def improves(base, cand):
    """Rule A: fewer confirmed cycle FAILs, no worse Expert/Refresh FAILs.
    Rule B: all official pass, worst cycle response and max refresh not worse,
    at least one strictly better."""
    if not cand['complete']:
        return None
    a = (cand['cycle_fail'] < base['cycle_fail']
         and cand['expert_fail'] <= base['expert_fail']
         and cand['refresh_fail'] <= base['refresh_fail'])
    b = (base['cycle_fail'] == 0 and cand['cycle_fail'] == 0
         and cand['worst_cycle_response'] <= base['worst_cycle_response']
         and cand['max_refresh_response'] <= base['max_refresh_response']
         and (cand['worst_cycle_response'] < base['worst_cycle_response']
              or cand['max_refresh_response'] < base['max_refresh_response'])
         and cand['expert_fail'] == 0)
    return 'A' if a else ('B' if b else None)


def main():
    out = HERE / 'outputs'; out.mkdir(exist_ok=True)
    rows, schedules, coverage = [], [], []
    for tag, sid in inputs.SEGMENTS:
        result, seg = inputs.load(tag, sid)
        ops, extra = inputs.costs(seg)
        plan, period = seg['plan'], seg['period_ns'] / 1e6
        base = inputs.metrics(plan, period, inputs.run(plan, period, extra))
        variants = {}
        for name, pol in POLICIES.items():
            m = inputs.metrics(plan, period, inputs.run(plan, period, extra, **pol))
            variants[name] = m
        best = None
        for name, m in variants.items():
            verdict = improves(base, m) if name != 'P0_default' else None
            rows.append(dict(segment=tag, segment_id=sid, plan=plan, period_ms=period,
                             policy=name, status=m['status'], complete=m['complete'],
                             cycle_fail=m['cycle_fail'], refresh_fail=m['refresh_fail'],
                             expert_fail=m['expert_fail'],
                             MC=m['MC'], ME=m['ME'], MU=m['MU'], MR=m['MR'],
                             worst_cycle_response=m['worst_cycle_response'],
                             max_refresh_response=m['max_refresh_response'],
                             improvement=verdict or ''))
            if verdict:
                best = best or dict(policy=name, verdict=verdict, metrics=m)
        schedules.append(dict(segment=tag, segment_id=sid, plan=plan, period_ms=period,
                              baseline=dict(policy='P0_default', **{k: base[k] for k in
                                            ('status','complete','cycle_fail','refresh_fail',
                                             'expert_fail','MC','ME','MU','MR',
                                             'worst_cycle_response','max_refresh_response')}),
                              best_improving=best))
        coverage.append(dict(segment=tag, segment_id=sid, policies=len(POLICIES),
                             nodes=len(POLICIES), elapsed_s=None,
                             truncated=False, complete_search=True,
                             action_level_dfs='NOT_IMPLEMENTED'))
    with (out / 'BASELINE_VS_SEARCH.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    (out / 'SCHEDULES.json').write_text(json.dumps(dict(
        schema='lsg_schedules_v1', note='global action policies on the frozen state-transition core; '
        'action-level E/C/I DFS not implemented', segments=schedules), indent=2, sort_keys=True) + '\n')
    (out / 'SEARCH_COVERAGE.json').write_text(json.dumps(dict(
        schema='lsg_coverage_v1', segments=len(coverage), policies=list(POLICIES),
        node_cap=100000, wall_cap_s=10, nodes_used=len(POLICIES), action_level_dfs='NOT_IMPLEMENTED',
        detail=coverage), indent=2, sort_keys=True) + '\n')
    imp = [r for r in rows if r['improvement']]
    print(json.dumps(dict(segments=len(inputs.SEGMENTS), rows=len(rows),
                          improving=len(imp), policies=list(POLICIES)), indent=1))
    for r in rows:
        if r['improvement']:
            print('IMPROVE', r['segment'], r['policy'], r['improvement'], r['worst_cycle_response'], r['max_refresh_response'])


if __name__ == '__main__':
    main()
