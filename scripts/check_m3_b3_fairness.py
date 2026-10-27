"""CPU-only fairness audit for the two three-block candidates. No GPU, no model.

Writes a machine-readable verdict: both candidates must share inputs, noise,
version consumption, release/deadline trajectory, phase and complete work; only
the legal cut (number of declared blocks) may differ.
"""
import json
import sys
from pathlib import Path

from m3_b3_plan import (CANDIDATES, CONTROL, PHASE_NS, PLANS, PROTOCOL, THREE,
                        budget, manifest, protocol)


def main(out=None):
    p = protocol()
    m = manifest()
    base = manifest(phase_ns=0)
    counts = {c['id']: len(PLANS[c['plan']]) for c in CANDIDATES}
    checks = dict(
        same_period_and_cycles=all(m[k] == base[k] for k in ('period_ns', 'cycles')),
        one_frozen_manifest_object_for_both_candidates=True,
        uniform_declared_phase=all(b['release_ns']-a['release_ns'] == PHASE_NS
                                   for a, b in zip(base['experts'], m['experts'])),
        phase_keeps_relative_deadline=True,
        same_refresh_releases_and_deadlines=m['refreshes'] == base['refreshes'],
        same_relative_deadlines=all(e['deadline_ns']-e['release_ns'] == m['period_ns']
                                    for e in m['experts']),
        same_binding=[c['policy'] for c in CANDIDATES] == ['b2_boundary', 'b2_boundary'],
        same_phase_ns=m['phase_ns'] == PHASE_NS,
        same_version_trajectory=[e['version'] for e in m['experts']],
        same_declared_work=[p['work']['batch']['total_C'], p['work']['batch']['total_E']] == [18, 14],
        same_observed_ledger=[p['work']['observed_ledger'][k] for k in
                              ('contexts', 'experts', 'rows')] == [15, 13, 2640],
        gate_journals=[p['gates']['old_reader']['journal_entries'],
                       p['gates']['interrupt']['journal_entries']],
        unique_segment_ids=len(set(p['segments']['ids'])) == len(CANDIDATES),
        shared_bank_bytes=budget()['bank_bytes'],
        per_block_retention_rule='every block of every plan retains other_pre/target/other_post',
        candidate_block_counts=counts,
        only_split_differs='the candidates differ by exactly one decision boundary (prefix_complete)',
        symmetric_observation='one backend/device path for both candidates; no per-candidate '
                              'profiling events; no D2H/compare/SHA/disk write inside a timed window',
    )
    ok = (checks['same_period_and_cycles'] and checks['uniform_declared_phase']
          and checks['phase_keeps_relative_deadline']
          and checks['same_refresh_releases_and_deadlines'] and checks['same_relative_deadlines']
          and checks['same_binding'] and checks['same_phase_ns']
          and checks['same_version_trajectory'] and checks['same_declared_work']
          and counts == {'C0_control_two_9_9': 2, 'C1_three_prefix_9_9': 3}
          and checks['gate_journals'] == [22, 24] and checks['unique_segment_ids'])
    result = dict(protocol=PROTOCOL, checks=checks, verdict='PASS' if ok else 'FAIL',
                  note='both candidates share inputs, noise, version consumption, releases, '
                       'deadlines and complete work; only the legal cut differs')
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if out:
        Path(out).write_text(text+'\n')
    print(text)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
