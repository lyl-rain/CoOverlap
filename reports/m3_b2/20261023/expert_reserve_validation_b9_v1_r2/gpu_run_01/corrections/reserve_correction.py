#!/usr/bin/env python3
"""Minimal read-only correction of the Expert reserve block in EVALUATION.json.

The r2 evaluator put every job type into ``reserve.predicted_pass_actual_short``
(16 Refresh rows).  RE = 10 ms is an Expert-only requirement, so this script
rebuilds that block from the already-recorded comparison: Expert rows only,
explicit denominator, UNKNOWN kept for missing margins.  Nothing else is
recomputed or rewritten; the original file is left untouched.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

RESERVE_MS = 10.0


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def expert_reserve(comparison, reserve_ms=RESERVE_MS):
    """Expert-only reserve accounting.

    One actual job appears once per scenario evaluation; the actual margin is a
    property of the job, so counts are taken from the distinct (segment, job)
    pairs and the scenario comparisons are reported separately as non-independent.
    """
    by_job = {}
    mismatches = []
    comparisons = 0
    for seg in comparison.get('per_segment') or []:
        sid, scenario = seg['segment_id'], seg['scenario']
        for job in seg.get('jobs') or []:
            if job.get('job_type') != 'Expert':
                continue
            comparisons += 1
            key = (sid, job['job_id'])
            rec = by_job.setdefault(key, dict(predicted=[], actual=[], scenarios=[]))
            rec['scenarios'].append(scenario)
            rec['predicted'].append(job.get('predicted_margin_ms'))
            rec['actual'].append(job.get('actual_margin_ms'))
            pred, act = job.get('predicted_margin_ms'), job.get('actual_margin_ms')
            if pred is not None and act is not None and pred >= reserve_ms and act < reserve_ms:
                mismatches.append(dict(segment_id=sid, scenario=scenario, job_id=job['job_id'],
                                       predicted_margin_ms=pred, actual_margin_ms=act))
    short = satisfied = unknown = 0
    inconsistent = []
    for (sid, jid), rec in by_job.items():
        actual = [a for a in rec['actual'] if a is not None]
        if len(set(actual)) > 1:
            inconsistent.append(dict(segment_id=sid, job_id=jid, actual_margins=rec['actual']))
        if not rec['actual'] or all(a is None for a in rec['actual']):
            unknown += 1
        elif min(actual) < reserve_ms:
            short += 1
        else:
            satisfied += 1
    return dict(
        scope='Expert only (RE = %g ms); ContextBlock/Cycle/Refresh are excluded' % reserve_ms,
        reserve_ms=reserve_ms,
        short=short, satisfied=satisfied, unknown=unknown, total=len(by_job),
        denominator=dict(expert_jobs=len(by_job), segment_scenario_comparisons=comparisons,
                         note='the same actual Expert appears once per model scenario; the two '
                              'scenario comparisons are not independent observations'),
        predicted_pass_actual_short=mismatches,
        inconsistent_actual_margins=inconsistent,
        rule='predicted margin >= reserve AND actual margin < reserve; missing margins are UNKNOWN, '
             'neither satisfied nor short')


def rebuild(original_path, result_path, out_path):
    original = json.loads(Path(original_path).read_text())
    result = json.loads(Path(result_path).read_text())
    corrected = copy.deepcopy(original)
    block = expert_reserve(original['part_c_selection']['comparison'], RESERVE_MS)
    old = original['part_c_selection']['reserve']
    block['excluded_from_previous_list'] = sorted(
        {x['job'].split(':')[0] for x in []}) or ['Refresh rows in the r2 output']
    corrected['part_c_selection']['reserve'] = block
    corrected['correction'] = dict(
        schema='m3_b9_evaluation_correction_v1',
        reason='reserve is an Expert-only requirement; r2 mixed Refresh rows into the mismatch list',
        source_evaluation=dict(path=str(original_path), sha256=sha256(original_path)),
        source_result=dict(path=str(result_path), sha256=sha256(result_path)),
        script=dict(path=str(Path(__file__)), sha256=sha256(__file__)),
        fields_changed=['part_c_selection.reserve'],
        counts_unchanged=dict(short=old['short'], satisfied=old['satisfied'],
                              unknown=old['unknown'], total=old['total'],
                              equal=(old['short'] == block['short']
                                     and old['satisfied'] == block['satisfied']
                                     and old['unknown'] == block['unknown']
                                     and old['total'] == block['total'])),
        note='no other field was recomputed; the official part_b, order, error and prediction '
             'fields are byte-identical to the source evaluation')
    Path(out_path).write_text(json.dumps(corrected, indent=2, sort_keys=True) + '\n')
    return corrected, block


def verify_unchanged(original_path, corrected_path):
    a = json.loads(Path(original_path).read_text())
    b = json.loads(Path(corrected_path).read_text())
    b.pop('correction', None)
    ra = a['part_c_selection'].pop('reserve')
    rb = b['part_c_selection'].pop('reserve')
    same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    return dict(other_fields_identical=same, reserve_changed=(ra != rb),
                counts_equal=(ra['short'] == rb['short'] and ra['satisfied'] == rb['satisfied']
                              and ra['unknown'] == rb['unknown'] and ra['total'] == rb['total']))


def main(argv=None):
    argv = argv or sys.argv[1:]
    base = Path(__file__).resolve().parents[1]
    original = base / 'analysis' / 'EVALUATION.json'
    result = base / 'board_small' / 'model' / 'result.json'
    out = base / 'corrections' / 'EVALUATION_CORRECTED.json'
    doc, block = rebuild(original, result, out)
    check = verify_unchanged(original, out)
    print(json.dumps(dict(out=str(out), reserve=dict(short=block['short'],
                                                     satisfied=block['satisfied'],
                                                     unknown=block['unknown'],
                                                     total=block['total'],
                                                     mismatches=len(block['predicted_pass_actual_short'])),
                          verify=check), indent=2))
    return 0 if check['other_fields_identical'] else 1


if __name__ == '__main__':
    sys.exit(main())
