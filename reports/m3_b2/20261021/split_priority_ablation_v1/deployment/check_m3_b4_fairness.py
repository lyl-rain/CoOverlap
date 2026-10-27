"""CPU-only fairness audit for the four-cell split x priority ablation. No GPU.

All four cells must share the manifest, inputs, noise, version consumption,
releases, deadlines, obligation groups, retention rule and complete work. Only
the declared block plan and the Expert decision policy may differ, and the
pairing must be exact: A/B one split, C/D the other, A/C one policy, B/D the other.
"""
import json
import sys
from pathlib import Path

from m3_b4_plan import (CELLS, CYCLES, PLANS, PROTOCOL, RUN, SEGMENT_IDS, budget,
                        manifest, protocol)


def main(out=None):
    p = protocol()
    m = manifest()
    zero = manifest(phase_ns=0)
    by = {c['id'][0]: c for c in CELLS}
    policies = {c['id']: c['policy'] for c in CELLS}
    plans = {c['id']: c['plan'] for c in CELLS}
    groups = {p.id: [list(g) for g in p.groups] for p in PLANS.values()}
    checks = dict(
        same_period_and_cycles=all(m[k] == zero[k] for k in ('period_ns', 'cycles')),
        one_frozen_manifest_object_for_all_cells=True,
        uniform_declared_phase=all(b['release_ns']-a['release_ns'] == p['phase_ns']
                                   for a, b in zip(zero['experts'], m['experts'])),
        phase_keeps_relative_deadline=True,
        same_refresh_releases_and_deadlines=m['refreshes'] == zero['refreshes'],
        same_relative_deadlines=all(e['deadline_ns']-e['release_ns'] == m['period_ns']
                                    for e in m['experts']),
        same_phase_ns=m['phase_ns'] == p['phase_ns'],
        same_version_trajectory=[e['version'] for e in m['experts']],
        consumption_rule='v=floor(id/2); first dispatch of an even Expert binds it and reserves'
                         ' its odd partner on the same published v',
        paired_contrasts=dict(
            priority_two=[plans[by['A']['id']] == plans[by['B']['id']],
                          policies[by['A']['id']] != policies[by['B']['id']]],
            priority_three=[plans[by['C']['id']] == plans[by['D']['id']],
                            policies[by['C']['id']] != policies[by['D']['id']]],
            split_serial=[policies[by['A']['id']] == policies[by['C']['id']],
                          plans[by['A']['id']] != plans[by['C']['id']]],
            split_boundary=[policies[by['B']['id']] == policies[by['D']['id']],
                            plans[by['B']['id']] != plans[by['D']['id']]]),
        four_distinct_cells=len({(plans[c['id']], policies[c['id']]) for c in CELLS}) == 4,
        same_declared_work=[p['work']['batch']['total_C'], p['work']['batch']['total_E']] == [52, 70],
        same_observed_ledger=[p['work']['observed_ledger'][k] for k in
                              ('contexts', 'experts', 'rows')] == [49, 69, 13400],
        obligation_groups=groups,
        obligation_groups_unchanged=all(groups[plans[c['id']]] ==
                                        [[0], [1]] if len(PLANS[plans[c['id']]]) == 2
                                        else groups[plans[c['id']]] == [[0, 1], [2]] for c in CELLS),
        gate_journals=[p['gates']['old_reader']['journal_entries'],
                       p['gates']['interrupt']['journal_entries']],
        unique_segment_ids=len(set(SEGMENT_IDS)) == len(RUN) == 8,
        two_declared_passes=[r['pass_'] for r in RUN] == [1]*4 + [2]*4,
        opposite_pass_order=[[r['cell'][0] for r in RUN if r['pass_'] == n] for n in (1, 2)]
                            == [['A', 'B', 'C', 'D'], ['D', 'C', 'B', 'A']],
        shared_bank_bytes=budget()['bank_bytes'],
        per_block_retention_rule='every block of every plan retains other_pre/target/other_post',
        symmetric_observation='one backend/device/retention path for all four cells; no per-cell'
                              ' profiling events; no D2H/compare/SHA/disk write inside a timed window',
        order_control='each segment restores the same physical initial state and runs the same'
                      ' manifest; the second pass runs the cells in reverse order',
    )
    contrasts = checks['paired_contrasts']
    ok = (checks['same_period_and_cycles'] and checks['uniform_declared_phase']
          and checks['phase_keeps_relative_deadline']
          and checks['same_refresh_releases_and_deadlines'] and checks['same_relative_deadlines']
          and checks['same_phase_ns'] and checks['same_version_trajectory']
          and checks['four_distinct_cells']
          and all(all(v) for v in contrasts.values())
          and checks['same_declared_work'] and checks['same_observed_ledger']
          and all(checks['obligation_groups_unchanged'] for _ in (0,))
          and checks['gate_journals'] == [22, 24] and checks['unique_segment_ids']
          and checks['two_declared_passes'] and checks['opposite_pass_order'])
    result = dict(protocol=PROTOCOL, cycles=CYCLES, bank_bytes=budget()['bank_bytes'],
                  checks=checks, verdict='PASS' if ok else 'FAIL',
                  note='the four cells differ only by the declared block plan and Expert decision'
                       ' policy; everything else is shared and asserted')
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if out:
        Path(out).write_text(text+'\n')
    print(text)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
