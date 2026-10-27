#!/usr/bin/env python3
"""Offline evaluation of one B9 run: correctness, official performance, selection.

Reads the run's ``result.json`` plus the frozen selection/prediction and writes the
three separately reported parts.  It never changes the run, the costs, the rule or
the reserve value, and it never turns a condition mismatch into a SELECTED verdict.

    python3 analysis/evaluate_b9.py --result <run>/result.json --out <run>/analysis
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
B9 = HERE.parent
DECLARED_CONFIGURATION = 'H_frozen'      # the B8 condition the costs were taken from
RESERVE_MS = 10.0


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def condition_status(actual_label, expected=DECLARED_CONFIGURATION):
    """MATCH / CONDITION_MISMATCH / UNKNOWN from the recorded numeric configuration."""
    if actual_label is None:
        return 'UNKNOWN'
    return 'MATCH' if actual_label == expected else 'CONDITION_MISMATCH'


def _load(path):
    return json.loads(Path(path).read_text())


def _job(segment):
    """Official jobs of one segment with Host upper completion and deadlines."""
    manifest = segment['manifest']
    t0 = segment['t0_ns']
    out = []
    for e in manifest['experts']:
        rec = segment.get('experts', {}).get(str(e['id']))
        comp = None if rec is None else rec[1]
        out.append(dict(job_type='Expert', job_id='E%d' % e['id'],
                        release_ns=t0 + e['release_ns'],
                        deadline_ns=t0 + e['deadline_ns'],
                        completion_ns=comp,
                        margin_ms=None if comp is None else
                        round((t0 + e['deadline_ns'] - comp) / 1e6, 6)))
    for r in manifest['refreshes']:
        rec = segment.get('published', {}).get(str(r['id']))
        comp = None if rec is None else rec[1]
        out.append(dict(job_type='Refresh', job_id='R%d' % r['id'],
                        release_ns=t0 + r['release_ns'],
                        deadline_ns=t0 + r['deadline_ns'],
                        completion_ns=comp,
                        margin_ms=None if comp is None else
                        round((t0 + r['deadline_ns'] - comp) / 1e6, 6)))
    for c in segment['statistics']['cycles']:
        out.append(dict(job_type='Cycle', job_id='C%d' % c['cycle'],
                        release_ns=c['release_ns'], deadline_ns=c['deadline_ns'],
                        completion_ns=c['release_ns'] + c['response_upper_ns'],
                        margin_ms=round((c['deadline_ns'] - c['release_ns']
                                         - c['response_upper_ns']) / 1e6, 6),
                        status=c['status']))
    return out


def part_a(result):
    checks = result.get('checks') or []
    segments = result.get('segments') or []
    return dict(
        status=result.get('status'),
        checks=dict(total=len(checks), passed=sum(1 for c in checks if c['pass_'])),
        d1=result.get('in_process_equivalence'),
        gates={k: v.get('status') for k, v in (result.get('gates') or {}).items()},
        retention=[dict(segment_id=s['segment_id'],
                        records=(s.get('validation') or {}).get('records'),
                        bytes=(s.get('validation') or {}).get('payload_B'),
                        all_job_actions_exact=(s.get('validation') or {}).get(
                            'all_job_actions_exact'))
                   for s in segments],
        observed_call_counts=result.get('observed_call_counts'),
        ledger_rows=len(result.get('call_ledger') or []),
        work=result.get('protocol', {}).get('work', {}).get('batch'),
        note='correctness only; performance/reserve/prediction failures are not correctness failures')


def part_b(result):
    rows = []
    totals = dict(cycles_PASS=0, cycles_FAIL=0, cycles_INCOMPLETE=0,
                  refreshes_PASS=0, refreshes_FAIL=0, refreshes_INCOMPLETE=0)
    for segment in result.get('segments') or []:
        jobs = _job(segment)
        cyc = [j for j in jobs if j['job_type'] == 'Cycle']
        ref = [j for j in jobs if j['job_type'] == 'Refresh']
        counts_c = {k: sum(1 for j in cyc if j.get('status') == k)
                    for k in ('PASS', 'FAIL', 'INCOMPLETE')}
        counts_r = {k: sum(1 for j in ref if j.get('status') == k)
                    for k in ('PASS', 'FAIL', 'INCOMPLETE')}
        for k in ('PASS', 'FAIL', 'INCOMPLETE'):
            totals['cycles_' + k] += counts_c[k]
            totals['refreshes_' + k] += counts_r[k]
        rows.append(dict(
            segment_id=segment['segment_id'], cell=segment['cell'], plan=segment['plan'],
            period_ms=segment['period_ns'] / 1e6, pass_=segment.get('pass_'),
            cycles=counts_c, cycles_denominator=len(cyc),
            refreshes=counts_r, refreshes_denominator=len(ref),
            min_cycle_margin_ms=min((j['margin_ms'] for j in cyc
                                     if j['margin_ms'] is not None), default=None),
            min_expert_margin_ms=min((j['margin_ms'] for j in jobs
                                      if j['job_type'] == 'Expert'
                                      and j['margin_ms'] is not None), default=None),
            min_refresh_margin_ms=min((j['margin_ms'] for j in ref
                                       if j['margin_ms'] is not None), default=None),
            refresh_ready_ms=[None if j['completion_ns'] is None else
                              round((j['completion_ns'] - j['release_ns']) / 1e6, 6)
                              for j in ref],
            metrics=segment.get('metrics')))
    return dict(rows=rows, totals=totals,
                note='official deadlines only; denominators kept; INCOMPLETE never counted as PASS')


def part_c(result, freeze, prediction):
    configured = (result.get('configuration') or {}).get('label')
    status = condition_status(configured)
    rows = []
    for segment in result.get('segments') or []:
        period = segment['period_ns']
        frozen = freeze['by_period_ns'].get(str(period))
        jobs = [j for j in _job(segment) if j['job_type'] == 'Expert']
        short = [j for j in jobs if j['margin_ms'] is not None and j['margin_ms'] < RESERVE_MS]
        rows.append(dict(segment_id=segment['segment_id'], plan=segment['plan'],
                         period_ms=period / 1e6, selection=frozen,
                         experts=len(jobs), reserve_short=len(short),
                         reserve_short_jobs=[j['job_id'] for j in short],
                         min_expert_margin_ms=min((j['margin_ms'] for j in jobs
                                                   if j['margin_ms'] is not None),
                                                  default=None)))
    domain = 'EVALUATED_IN_DOMAIN' if status == 'MATCH' else 'INSUFFICIENT_EVIDENCE'
    return dict(
        condition=dict(configured_label=configured, declared=DECLARED_CONFIGURATION,
                       status=status),
        selector_domain=domain,
        prediction_status=('EVALUATED' if status == 'MATCH' else 'CONDITION_MISMATCH'),
        reserve_ms=RESERVE_MS,
        selection_freeze=dict(rule=freeze['rule_id'], reserve_ms=freeze['reserve_ms'],
                              by_period_ns=freeze['by_period_ns']),
        rows=rows,
        note='the frozen recommendation is reported even when the domain is declined; '
             'a declined domain never becomes SELECTED')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--result', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--freeze', type=Path, default=B9 / 'prediction' / 'SELECTION_FREEZE.json')
    ap.add_argument('--prediction', type=Path, default=B9 / 'prediction' / 'PREDICTION.json')
    args = ap.parse_args()
    result = _load(args.result)
    freeze = _load(args.freeze)
    prediction = _load(args.prediction)
    out = dict(schema='m3_b9_evaluation_v1', protocol=result.get('protocol'),
               source=dict(result=dict(path=str(args.result), sha256=sha(args.result)),
                           freeze=dict(path=str(args.freeze), sha256=sha(args.freeze),
                                       fingerprint=freeze.get('fingerprint')),
                           prediction=dict(path=str(args.prediction),
                                           sha256=sha(args.prediction),
                                           fingerprint=prediction.get('fingerprint'))),
               part_a_correctness=part_a(result),
               part_b_official_performance=part_b(result),
               part_c_selection=part_c(result, freeze, prediction))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'EVALUATION.json').write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(status=out['part_c_selection']['condition']['status'],
                          domain=out['part_c_selection']['selector_domain'],
                          cycles=out['part_b_official_performance']['totals']), indent=2))


if __name__ == '__main__':
    main()
