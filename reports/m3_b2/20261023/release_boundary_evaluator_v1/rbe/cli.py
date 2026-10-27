"""Entry point: trace audit, condition-specific replay, release-crossing sensitivity.

    python3 rbe/cli.py audit          # 32-refresh boundary audit + deadline margins
    python3 rbe/cli.py replay         # B4-source and B8-self cost replays
    python3 rbe/cli.py sensitivity    # per-boundary critical deltas + branch constructions
    python3 rbe/cli.py evaluate       # per-candidate plan evaluation from all of the above
    python3 rbe/cli.py fingerprints   # input/model/source/output SHA256
    python3 rbe/cli.py all

Every subcommand is read-only on the frozen inputs and writes only under
``outputs/``.  No GPU, model, worker, SSH or hardware access.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'rbe'))

import audit            # noqa: E402
import costs            # noqa: E402
import env              # noqa: E402
import evaluation       # noqa: E402
import replay           # noqa: E402
import sensitivity      # noqa: E402

OUT = HERE / 'outputs'
KEY = costs.BLOCK_KEY

CSV_COLUMNS = [
    'side', 'segment_id', 'cell', 'plan', 'period_ms', 'pass_', 'refresh',
    'boundary_key', 'prev_op_kind', 'prev_op_job', 'prev_expert_state',
    'blocks_done_in_refresh', 'blocks_done_total', 'experts_done',
    'decision_ms', 'decision_origin', 'after_idle_arrival',
    'prev_gpu_lower_ms', 'prev_gpu_upper_ms', 'prev_completion_ms', 'confirm_overhead_ms',
    'decision_minus_prev_completion_ms',
    'released_ready_experts', 'released_version_wait_experts',
    'recorded_ready_experts', 'recorded_version_wait_experts', 'ready_matches_record',
    'recorded_active_context', 'recorded_completed_blocks', 'recorded_context_backlog',
    'next_expert_id', 'next_expert_release_ms', 'next_expert_deadline_ms',
    'next_expert_state', 'next_expert_version_ready', 'next_expert_version_evidence',
    'distance_decision_ms', 'distance_completion_upper_ms', 'distance_completion_lower_ms',
    'release_side_interval', 'release_side_at_decision', 'release_interval_uncertain',
    'release_crossed_by_decision',
    'release_during_chosen_op', 'release_offset_into_op_ms',
    'chosen_kind', 'chosen_job', 'chosen_version', 'chosen_block_index', 'chosen_block_kind',
    'competing_kind', 'competing_job', 'competition',
    'expert_job', 'expert_completion_ms', 'expert_deadline_ms', 'expert_margin_ms',
    'expert_status',
    'cycle_id', 'cycle_completion_ms', 'cycle_deadline_ms', 'cycle_margin_ms', 'cycle_status',
    'unit_job', 'unit_block', 'unit_blocks', 'unit_completion_ms', 'unit_deadline_ms',
    'unit_margin_ms', 'unit_status',
    'refresh_publication_ms', 'refresh_deadline_ms', 'refresh_margin_ms', 'refresh_status',
]


# ------------------------------------------------------------------- utilities

def _write_csv(path, rows, columns=None):
    rows = list(rows)
    if not rows:
        path.write_text('')
        return
    columns = columns or list(rows[0])
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow({k: _cell(row.get(k)) for k in columns})


def _cell(value):
    if isinstance(value, (list, tuple)):
        return '|'.join(str(v) for v in value)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return '' if value is None else value


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def load_all(strict=True):
    return dict(inputs=env.fingerprint_inputs(strict=strict),
                result=env.load(env.B8_RESULT),
                prediction=env.load(env.B8_PREDICTION))


def actual_rows(result):
    rows = []
    for segment in result['segments']:
        rows.extend(audit.attach_record(audit.actual_view(segment)))
    return rows


def predicted_rows(prediction):
    out = {}
    for letter, cell in prediction['cells'].items():
        for kind in ('typical', 'stress'):
            out[(letter, kind)] = audit.boundaries(
                audit.predicted_view(cell, kind, cell['scenarios'][kind]))
    return out


# ---------------------------------------------------------------------- audit

def flips_for_segment(segment_row, pred_row):
    ai = {r['boundary_key']: r for r in segment_row}
    pi = {r['boundary_key']: r for r in pred_row}
    out = []
    for key in sorted(set(ai) & set(pi)):
        a, p = ai[key], pi[key]
        if not (a['competition'] and p['competition']):
            continue
        pair_a = sorted([a['chosen_job'], a['competing_job']])
        pair_p = sorted([p['chosen_job'], p['competing_job']])
        if pair_a != pair_p or a['chosen_job'] == p['chosen_job']:
            continue
        out.append(dict(
            segment_id=a['segment_id'], cell=a['cell'], plan=a['plan'],
            period_ms=a['period_ms'], refresh=a['refresh'], boundary_key=key,
            candidates=pair_a, actual_choice=a['chosen_job'], predicted_choice=p['chosen_job'],
            next_expert=a['next_expert_id'], release_ms=a['next_expert_release_ms'],
            actual_decision_ms=a['decision_ms'], predicted_decision_ms=p['decision_ms'],
            actual_distance_ms=a['distance_decision_ms'],
            predicted_distance_ms=p['distance_decision_ms'],
            actual_side=a['release_side_at_decision'],
            predicted_side=p['release_side_at_decision'],
            distance_shift_ms=round(p['distance_decision_ms'] - a['distance_decision_ms'], 6),
            actual_expert_margin_ms=a['expert_margin_ms'],
            predicted_expert_margin_ms=p['expert_margin_ms'],
            actual_cycle_margin_ms=a['cycle_margin_ms'],
            predicted_cycle_margin_ms=p['cycle_margin_ms'],
            actual_refresh_publication_ms=a['refresh_publication_ms'],
            predicted_refresh_publication_ms=p['refresh_publication_ms'],
        ))
    return out


def dispatch_positions(rows):
    """Map refresh -> (tail-block decision, expert 2q+1 decision) from a row list."""
    out = {q: dict(tail=None, expert=None) for q in range(8)}
    for r in rows:
        if r['chosen_kind'] == 'Context':
            if r['chosen_job'] == 'R%d/%s' % (r['refresh'], KEY[r['plan']][-1]):
                out[r['refresh']]['tail'] = r
        elif r['chosen_kind'] == 'Expert':
            j = int(r['chosen_job'][1:])
            out[j // 2]['expert'] = r
    return out


def refresh_coverage(result, actual, predicted):
    """One row per refresh: where the tail-block / next-Expert competition landed."""
    rows = []
    for segment in result['segments']:
        seg_rows = [r for r in actual if r['segment_id'] == segment['segment_id']]
        pos_a = dispatch_positions(seg_rows)
        letter = segment['cell'][0]
        per_kind = {k: dispatch_positions(predicted[(letter, k)])
                    for k in ('typical', 'stress')}
        for q in range(segment['manifest']['cycles'] // 2):
            release = (2 * q + 1) * segment['period_ns'] / 1e6 + env.PHASE_MS
            row = dict(segment_id=segment['segment_id'], cell=segment['cell'],
                       plan=segment['plan'], period_ms=segment['period_ns'] / 1e6,
                       pass_=segment.get('pass_'), refresh=q,
                       tail_block=KEY[segment['plan']][-1], next_expert='E%d' % (2 * q + 1),
                       release_ms=release)
            _competition(row, 'actual', pos_a[q], release)
            for kind in ('typical', 'stress'):
                _competition(row, 'predicted_' + kind, per_kind[kind][q], release)
            row['order_flip_typical'] = _flip(row, 'actual', 'predicted_typical')
            row['order_flip_stress'] = _flip(row, 'actual', 'predicted_stress')
            rows.append(row)
    return rows


def _competition(row, prefix, pos, release):
    tail, expert = pos['tail'], pos['expert']
    row[prefix + '_tail_decision_ms'] = None if tail is None else tail['decision_ms']
    row[prefix + '_expert_decision_ms'] = None if expert is None else expert['decision_ms']
    row[prefix + '_tail_before_expert'] = (
        None if (tail is None or expert is None) else tail['decision_ms'] < expert['decision_ms'])
    decisions = [x for x in (row[prefix + '_tail_decision_ms'],
                             row[prefix + '_expert_decision_ms']) if x is not None]
    row[prefix + '_competition_decision_ms'] = min(decisions) if decisions else None
    row[prefix + '_distance_ms'] = (None if not decisions else round(release - min(decisions), 6))
    row[prefix + '_refresh_publication_ms'] = (None if tail is None
                                               else tail['refresh_publication_ms'])
    row[prefix + '_tail_completion_ms'] = None


def _flip(row, a, b):
    x, y = row.get(a + '_tail_before_expert'), row.get(b + '_tail_before_expert')
    return None if x is None or y is None else x != y


def deadline_margins(result, prediction):
    rows = []
    for segment in result['segments']:
        jobs = replay.actual_job_table(segment)
        for (jt, jid) in sorted(jobs):
            j = jobs[(jt, jid)]
            rows.append(dict(side='actual', segment_id=segment['segment_id'],
                             cell=segment['cell'], plan=segment['plan'],
                             period_ms=segment['period_ns'] / 1e6,
                             job_type=jt, job_id=jid,
                             release_ms=j.get('release_ms'), deadline_ms=j.get('deadline_ms'),
                             completion_ms=j.get('completion_ms'), margin_ms=j.get('margin_ms'),
                             status=j.get('status')))
        cell = prediction['cells'][segment['cell'][0]]
        for kind in ('typical', 'stress'):
            pj = audit._predicted_jobs(cell['scenarios'][kind])
            for (jt, jid) in sorted(pj):
                j = pj[(jt, jid)]
                rows.append(dict(side='predicted_%s' % kind,
                                 segment_id=segment['segment_id'],
                                 cell=segment['cell'], plan=segment['plan'],
                                 period_ms=segment['period_ns'] / 1e6,
                                 job_type=jt, job_id=jid,
                                 release_ms=j.get('release_ms'),
                                 deadline_ms=j.get('deadline_ms'),
                                 completion_ms=j.get('completion_ms'),
                                 margin_ms=j.get('margin_ms'), status=j.get('status')))
    return rows


def summary_margins(rows):
    out = {}
    for row in rows:
        key = (row['side'], row['cell'], row['job_type'])
        cur = out.setdefault(key, dict(n=0, min=None, fails=0, incomplete=0))
        cur['n'] += 1
        if row['status'] == 'INCOMPLETE' or row['margin_ms'] is None:
            cur['incomplete'] += 1
            continue
        cur['min'] = row['margin_ms'] if cur['min'] is None else min(cur['min'], row['margin_ms'])
        if row['margin_ms'] < 0:
            cur['fails'] += 1
    return {'%s|%s|%s' % k: v for k, v in sorted(out.items())}


def identity_check(result, actual):
    """Where the release distance and a cycle deadline margin describe one instant.

    In this manifest deadline(cycle 2q) = deadline(Expert 2q) = release(Expert 2q+1).
    Cycle 2q completes on the operation the boundary follows (Expert 2q for
    two_9_9, block B1 for three_prefix_9_9).  The release distance must then equal
    that cycle's deadline margin minus the Host confirmation cost.
    """
    from replay import actual_job_table
    rows = []
    for segment in result['segments']:
        jobs = actual_job_table(segment)
        seg = [r for r in actual if r['segment_id'] == segment['segment_id']]
        pos = dispatch_positions(seg)
        for q in range(segment['manifest']['cycles'] // 2):
            tail = pos[q]['tail']
            if tail is None or tail['prev_completion_ms'] is None:
                continue
            cyc = jobs.get(('Cycle', 'cycle%d' % (2 * q)))
            if cyc is None or cyc.get('margin_ms') is None:
                continue
            diff = round(cyc['margin_ms'] - tail['distance_decision_ms'], 6)
            confirm = tail['confirm_overhead_ms'] or 0.0
            rows.append(dict(
                segment_id=segment['segment_id'], cell=segment['cell'], refresh=q,
                plan=segment['plan'], cycle_id=2 * q,
                cycle_completion_ms=cyc['completion_ms'],
                boundary_op_completion_ms=tail['prev_completion_ms'],
                cycle_on_boundary_op=abs(cyc['completion_ms']
                                         - tail['prev_completion_ms']) <= 1e-6,
                cycle_margin_ms=cyc['margin_ms'],
                release_distance_ms=tail['distance_decision_ms'],
                difference_ms=diff, confirm_overhead_ms=confirm,
                same_instant=(abs(cyc['completion_ms'] - tail['prev_completion_ms']) <= 1e-6
                              and abs(diff - confirm) <= 0.05)))
    return rows


def run_audit():
    env.prepare_imports()
    data = load_all()
    result, prediction = data['result'], data['prediction']
    actual = actual_rows(result)
    predicted = predicted_rows(prediction)
    flips = []
    for segment in result['segments']:
        letter = segment['cell'][0]
        seg_rows = [r for r in actual if r['segment_id'] == segment['segment_id']]
        for kind in ('typical', 'stress'):
            flips.extend([dict(f, scenario=kind)
                          for f in flips_for_segment(seg_rows, predicted[(letter, kind)])])
    coverage = refresh_coverage(result, actual, predicted)
    margins = deadline_margins(result, prediction)
    identity = identity_check(result, actual)

    ready_checks = [r['ready_matches_record'] for r in actual
                    if r['ready_matches_record'] is not None]
    version_wait_rows = sum(1 for r in actual if r['released_version_wait_experts'])
    uncertain = sum(1 for r in actual if r['release_interval_uncertain'])

    all_rows = list(actual)
    for segment in result['segments']:
        letter = segment['cell'][0]
        for kind in ('typical', 'stress'):
            for r in predicted[(letter, kind)]:
                all_rows.append(dict(r, segment_id=segment['segment_id'],
                                     pass_=segment.get('pass_'), cell=segment['cell']))

    _write_csv(OUT / 'BOUNDARY_AUDIT.csv', all_rows, CSV_COLUMNS)
    _write_csv(OUT / 'ORDER_FLIPS.csv', flips, [
        'scenario', 'segment_id', 'cell', 'plan', 'period_ms', 'refresh', 'boundary_key',
        'candidates', 'actual_choice', 'predicted_choice', 'next_expert', 'release_ms',
        'actual_decision_ms', 'predicted_decision_ms', 'actual_distance_ms',
        'predicted_distance_ms', 'actual_side', 'predicted_side', 'distance_shift_ms',
        'actual_expert_margin_ms', 'predicted_expert_margin_ms',
        'actual_cycle_margin_ms', 'predicted_cycle_margin_ms',
        'actual_refresh_publication_ms', 'predicted_refresh_publication_ms'])
    _write_csv(OUT / 'REFRESH_COVERAGE.csv', coverage, [
        'segment_id', 'cell', 'plan', 'period_ms', 'pass_', 'refresh', 'tail_block',
        'next_expert', 'release_ms',
        'actual_tail_decision_ms', 'actual_expert_decision_ms',
        'actual_competition_decision_ms', 'actual_distance_ms',
        'actual_tail_before_expert', 'actual_refresh_publication_ms',
        'predicted_typical_tail_decision_ms', 'predicted_typical_expert_decision_ms',
        'predicted_typical_competition_decision_ms', 'predicted_typical_distance_ms',
        'predicted_typical_tail_before_expert', 'predicted_typical_refresh_publication_ms',
        'predicted_stress_tail_decision_ms', 'predicted_stress_expert_decision_ms',
        'predicted_stress_competition_decision_ms', 'predicted_stress_distance_ms',
        'predicted_stress_tail_before_expert', 'predicted_stress_refresh_publication_ms',
        'order_flip_typical', 'order_flip_stress'])
    _write_csv(OUT / 'DEADLINE_MARGINS.csv', margins, [
        'side', 'segment_id', 'cell', 'plan', 'period_ms', 'job_type', 'job_id',
        'release_ms', 'deadline_ms', 'completion_ms', 'margin_ms', 'status'])
    _write_csv(OUT / 'MARGIN_IDENTITY.csv', identity, [
        'segment_id', 'cell', 'plan', 'refresh', 'cycle_id', 'cycle_completion_ms',
        'boundary_op_completion_ms', 'cycle_on_boundary_op', 'cycle_margin_ms',
        'release_distance_ms', 'difference_ms', 'confirm_overhead_ms', 'same_instant'])

    payload = dict(
        schema='rbe_boundary_audit_v1',
        status='OFFLINE_ANALYSIS_ONLY',
        inputs=data['inputs'],
        condition=dict(actual=env.condition_identity(result),
                       b4_source=env.CONDITION_LABELS['b4_source'],
                       statement='B4 source costs and B8 runtime configuration differ '
                                 '(CONDITION_MISMATCH); nothing here explains why'),
        frozen_prediction=dict(path=str(env.B8_PREDICTION.relative_to(env.PROJECT)),
                               status=prediction['status'],
                               fingerprint=prediction['prediction_fingerprint'],
                               note='reconstructed from the frozen artifact; never rewritten'),
        counts=dict(actual_rows=len(actual), predicted_rows=len(all_rows) - len(actual),
                    predicted_rows_per_cell=sum(len(v) for v in predicted.values()),
                    refreshes=len(coverage),
                    competition_rows=sum(1 for r in actual if r['competition']),
                    flips=len(flips),
                    flip_segments=len({(f['segment_id'], f['scenario']) for f in flips}),
                    ready_matches_record=sum(1 for x in ready_checks if x),
                    ready_checked=len(ready_checks),
                    version_wait_boundaries=version_wait_rows,
                    interval_uncertain_boundaries=uncertain,
                    margin_identity_rows=len(identity),
                    margin_identity_same_instant=sum(1 for x in identity if x['same_instant'])),
        margins=summary_margins(margins),
        coverage=coverage,
        flips=flips,
        margin_identity=identity,
        notes=[
            'actual decision time is the Host clock after the real completion confirmation',
            'the predicted decision time is a model event time with no Host confirmation term',
            'release-boundary distance = next Expert release - decision time; '
            'positive means the release was still in the future',
            'at the tight boundary the distance equals the cycle deadline margin minus the '
            'Host confirmation cost (see MARGIN_IDENTITY.csv); the new information is the '
            'order branch, not a second headroom number',
            'no threshold is applied: raw distances are reported, and a boundary whose '
            'completion interval spans its release is marked UNCERTAIN_INTERVAL',
        ],
    )
    _write_json(OUT / 'BOUNDARY_AUDIT.json', payload)
    _write_json(OUT / 'REFRESH_COVERAGE.json', dict(rows=coverage))
    return payload


# --------------------------------------------------------------------- replay

def run_replay():
    env.prepare_imports()
    data = load_all()
    result = data['result']
    measured = costs.b8_measured_costs(result)
    b4 = costs.b4_source_costs()
    out = dict(schema='rbe_condition_replays_v1', status='RETROSPECTIVE_ANALYSIS_ONLY',
               inputs=data['inputs'],
               b4=dict(condition=b4['condition_label'], source=b4['source'],
                       note='frozen prediction source; replay reproduces the pre-run prediction',
                       periods={}),
               b8=dict(condition=env.CONDITION_LABELS['b8_actual'],
                       note='this cell own measured costs; retrospective explanation only',
                       cells={}),
               comparisons={})
    for period in (180.0, 140.0):
        rep = replay.replay_b4(period)
        out['b4']['periods']['p%d' % int(period)] = {
            '%s/%s' % k: _compact(v) for k, v in rep['cells'].items()}
    for letter, cell in sorted(measured['cells'].items()):
        rep = replay.replay_b8(cell)
        out['b8']['cells'][letter] = {'%s/%s' % k: _compact(v) for k, v in rep['cells'].items()}
        for segment in result['segments']:
            if segment['cell'] != cell['cell']:
                continue
            comp = replay.compare(rep['cells'], segment)
            out['comparisons'].setdefault(letter, {})[segment['segment_id']] = {
                '%s/%s' % k: v for k, v in comp.items()}
            diff = replay.order_disagreements(segment, rep['cells'][(cell['plan'], 'typical')])
            out['comparisons'][letter][segment['segment_id']]['first_order_disagreement'] = diff
    out['b4_matches_frozen_prediction'] = _b4_matches_prediction(
        out['b4']['periods'], data['prediction'])
    _write_json(OUT / 'REPLAY.json', out)

    rows = []
    for key, cell in sorted(measured['cells'].items()):
        for plan_kind, rep in sorted(out['b8']['cells'][key].items()):
            rows.append(dict(source='b8', cell=key, entry=plan_kind, feasible=rep['feasible'],
                             min_cycle_margin_ms=rep['min_cycle_margin_ms'],
                             min_expert_margin_ms=rep['min_expert_margin_ms'],
                             min_refresh_margin_ms=rep['min_refresh_margin_ms'],
                             order=rep['order']))
    for period, cells in sorted(out['b4']['periods'].items()):
        for plan_kind, rep in sorted(cells.items()):
            rows.append(dict(source='b4', cell=period, entry=plan_kind, feasible=rep['feasible'],
                             min_cycle_margin_ms=rep['min_cycle_margin_ms'],
                             min_expert_margin_ms=rep['min_expert_margin_ms'],
                             min_refresh_margin_ms=rep['min_refresh_margin_ms'],
                             order=rep['order']))
    _write_csv(OUT / 'REPLAY.csv', rows, ['source', 'cell', 'entry', 'feasible',
                                          'min_cycle_margin_ms', 'min_expert_margin_ms',
                                          'min_refresh_margin_ms', 'order'])
    return out


def _b4_matches_prediction(periods, prediction):
    """Does the re-derived B4 replay equal the frozen pre-run prediction?"""
    out = {}
    for period in ('p180', 'p140'):
        letter = {'p180': ('A', 'B'), 'p140': ('C', 'D')}[period]
        ok = True
        detail = {}
        for cell_letter, plan in zip(letter, ('two_9_9', 'three_prefix_9_9')):
            for kind in ('typical', 'stress'):
                rep = periods[period]['%s/%s' % (plan, kind)]
                s = prediction['cells'][cell_letter]['scenarios'][kind]
                checks = dict(
                    feasible=rep['feasible'] == s['feasible'],
                    min_cycle=abs((rep['min_cycle_margin_ms'] or 0)
                                  - (s['min_cycle_margin_ms'] or 0)) < 1e-6,
                    min_expert=abs((rep['min_expert_margin_ms'] or 0)
                                   - (s['min_expert_margin_ms'] or 0)) < 1e-6,
                    min_refresh=abs((rep['min_refresh_margin_ms'] or 0)
                                    - (s['min_refresh_margin_ms'] or 0)) < 1e-6,
                )
                detail['%s/%s' % (plan, kind)] = checks
                ok = ok and all(checks.values())
        out[period] = dict(match=ok, detail=detail)
    return out


def _compact(rep):
    return dict(plan=rep['plan'], scenario=rep['scenario'], period_ms=rep['period_ms'],
                feasible=rep['feasible'], complete=rep['complete'],
                model_status=rep['model_status'],
                min_cycle_margin_ms=rep['min_cycle_margin_ms'],
                min_expert_margin_ms=rep['min_expert_margin_ms'],
                min_refresh_margin_ms=rep['min_refresh_margin_ms'],
                max_refresh_response_ms=rep['max_refresh_response_ms'],
                counts=rep['counts'], order=rep['order'])


# ---------------------------------------------------------------- sensitivity

def run_sensitivity():
    env.prepare_imports()
    data = load_all()
    result = data['result']
    measured = costs.b8_measured_costs(result)
    actual = actual_rows(result)
    record = sensitivity.record_critical(actual)

    constructions = []
    for letter, cell in sorted(measured['cells'].items()):
        for q in range(4):
            try:
                c = sensitivity.construct(cell, q)
            except RuntimeError as exc:
                constructions.append(dict(cell=letter, refresh=q, error=str(exc),
                                          label=sensitivity.NO_CROSS))
                continue
            tail = 'R%d/%s' % (q, KEY[cell['plan']][-1])
            c['empirical'] = [
                dict(segment_id=r['segment_id'], decision_ms=r['decision_ms'],
                     distance_ms=r['distance_decision_ms'], chosen=r['chosen_job'],
                     competing=r['competing_job'], release_ms=r['next_expert_release_ms'])
                for r in actual
                if r['cell'] == cell['cell'] and r['refresh'] == q
                and r['competition'] and r['chosen_kind'] == 'Context'
                and r['chosen_job'] == tail and r['next_expert_id'] == 2 * q + 1]
            constructions.append(c)

    payload = dict(schema='rbe_release_crossing_sensitivity_v1',
                   status='ANALYSIS_CONSTRUCTION_ONLY',
                   inputs=data['inputs'],
                   conditions=dict(b4=env.CONDITION_LABELS['b4_source'],
                                   b8=env.CONDITION_LABELS['b8_actual']),
                   boundary_critical=record,
                   constructions=[_compact_construction(c) for c in constructions],
                   notes=[
                       'boundary_critical is measured: the change needed for the observed '
                       'decision to reach the next Expert release',
                       'constructions are model branches with only the preceding Expert '
                       'duration changed; arrivals, deadlines and workload are fixed',
                       'the 1 ns probe separates the two branches mathematically only',
                       'an out-of-range duration change is labelled SENSITIVITY_CONSTRUCTION',
                       'stress_envelope is the same boundary with every operation at its '
                       'B8-observed maximum: a positive distance means the observed envelope '
                       'itself does not reach the release',
                   ])
    _write_json(OUT / 'SENSITIVITY.json', payload)
    rows = []
    for c in constructions:
        if 'critical' not in c:
            rows.append(dict(cell=c.get('cell'), refresh=c.get('refresh'),
                             label=c.get('label'), error=c.get('error')))
            continue
        rows.append(dict(
            cell=c['cell'], plan=c['plan'], period_ms=c['period_ms'], refresh=c['refresh'],
            boundary=c['boundary']['key'], release_ms=c['boundary']['release_ms'],
            model_decision_ms=c['base']['model_decision_ms'],
            model_distance_ms=c['base']['model_distance_ms'],
            delta_to_release_ms=c['critical']['delta_to_release_ms'],
            direction=c['critical']['direction'],
            base_duration_ms=c['critical']['base_duration_ms'],
            modified_duration_ms=c['critical']['modified_duration_ms'],
            observed_min_ms=c['critical']['observed_expert_min_ms'],
            observed_max_ms=c['critical']['observed_expert_max_ms'],
            within_observed_range=c['critical']['within_observed_range'],
            label=c['critical']['label'],
            stress_distance_ms=c['stress_envelope']['model_distance_ms'],
            stress_crosses=c['stress_envelope']['crosses'],
            pre_tail_first=c['branches']['pre']['tail_block_first'],
            post_tail_first=c['branches']['post']['tail_block_first'],
            order_flipped=c['checks']['order_flipped'],
            pre_checks=c['checks']['pre'], post_checks=c['checks']['post'],
            anomaly=c['anomaly']['is_anomaly'],
            successor_later_in_pre_ms=c['anomaly']['successor_later_in_pre_ms'],
            advanced=c['advanced'], delayed=c['delayed']))
    _write_csv(OUT / 'SENSITIVITY.csv', rows, [
        'cell', 'plan', 'period_ms', 'refresh', 'boundary', 'release_ms',
        'model_decision_ms', 'model_distance_ms', 'delta_to_release_ms', 'direction',
        'base_duration_ms', 'modified_duration_ms', 'observed_min_ms', 'observed_max_ms',
        'within_observed_range', 'label', 'stress_distance_ms', 'stress_crosses',
        'pre_tail_first', 'post_tail_first', 'order_flipped', 'pre_checks', 'post_checks',
        'anomaly', 'successor_later_in_pre_ms', 'advanced', 'delayed'])
    _write_csv(OUT / 'BOUNDARY_CRITICAL.csv', record, [
        'side', 'segment_id', 'cell', 'plan', 'period_ms', 'refresh', 'boundary_key',
        'decision_ms', 'release_ms', 'distance_ms', 'crosses_by_ms', 'short_by_ms',
        'direction', 'chosen_job', 'competing_job'])
    return payload


def _compact_construction(c):
    if 'critical' not in c:
        return c
    return dict(
        cell=c['cell'], plan=c['plan'], period_ms=c['period_ms'], refresh=c['refresh'],
        boundary=c['boundary'], base=c['base'], critical=c['critical'],
        stress_envelope=c['stress_envelope'],
        branches=c['branches'], checks=c['checks'], anomaly=c['anomaly'],
        advanced=c['advanced'], delayed=c['delayed'], empirical=c['empirical'],
        job_changes=c['job_changes'], cycle_changes=c['cycle_changes'],
        pre_expert_margin_ms=c['outcomes']['pre']['expert_margin_ms'],
        post_expert_margin_ms=c['outcomes']['post']['expert_margin_ms'],
        pre_publish_ms={q: v['end'] for q, v in c['outcomes']['pre']['publishes'].items()},
        post_publish_ms={q: v['end'] for q, v in c['outcomes']['post']['publishes'].items()},
        pre_cycles=c['outcomes']['pre']['cycles'],
        post_cycles=c['outcomes']['post']['cycles'])


# ------------------------------------------------------------------ evaluation

def run_evaluate():
    env.prepare_imports()
    audit_payload = _load_or_run('BOUNDARY_AUDIT.json', run_audit)
    replay_payload = _load_or_run('REPLAY.json', run_replay)
    sens_payload = _load_or_run('SENSITIVITY.json', run_sensitivity)
    data = load_all()
    ev = evaluation.plan_evaluation(data['result'], audit_payload, replay_payload, sens_payload)
    _write_json(OUT / 'PLAN_EVALUATION.json', ev)
    _write_csv(OUT / 'PLAN_EVALUATION.csv', ev['rows'], ev['columns'])
    return ev


def _load_or_run(name, fn):
    path = OUT / name
    if path.exists():
        return env.load(path)
    return fn()


# ---------------------------------------------------------------- fingerprints

def run_fingerprints():
    sources = {}
    for name in ('env.py', 'costs.py', 'audit.py', 'replay.py', 'sensitivity.py',
                 'evaluation.py', 'cli.py', 'test_rbe_cpu.py'):
        path = HERE / 'rbe' / name
        if path.exists():
            sources['rbe/' + name] = env.sha(path)
    outputs = {}
    for path in sorted(OUT.glob('*')):
        if path.is_file() and path.name != 'FINGERPRINTS.json':
            outputs[path.name] = env.sha(path)
    payload = dict(
        schema='rbe_fingerprints_v1', tool='release_boundary_evaluator_v1',
        git_head=_git_head(),
        inputs=env.fingerprint_inputs(),
        models=dict(r1_plan_model=env.sha(env.R1_SELECTOR / 'plan_model.py'),
                    r1_evaluator=env.sha(env.R1_SELECTOR / 'evaluator.py'),
                    r1_selection=env.sha(env.R1_SELECTOR / 'selection.py'),
                    r1_validate=env.sha(env.R1_SELECTOR / 'validate.py'),
                    frozen_executor=env.sha(env.FROZEN_EXECUTOR),
                    executor_identity=env.executor_identity()),
        source=sources, outputs=outputs,
        note='outputs are hashed before this manifest is written; the manifest does not '
             'hash itself')
    _write_json(OUT / 'FINGERPRINTS.json', payload)
    return payload


def _git_head():
    import subprocess
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(env.PROJECT),
                              capture_output=True, text=True, timeout=20).stdout.strip() or None
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('what', choices=('audit', 'replay', 'sensitivity', 'evaluate',
                                     'fingerprints', 'all'))
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    if args.what in ('audit', 'all'):
        summary['audit'] = run_audit()['counts']
    if args.what in ('replay', 'all'):
        rep = run_replay()
        summary['replay'] = dict(b4_matches=rep['b4_matches_frozen_prediction'],
                                 b8_cells=list(rep['b8']['cells']))
    if args.what in ('sensitivity', 'all'):
        sens = run_sensitivity()
        summary['sensitivity'] = dict(boundaries=len(sens['boundary_critical']),
                                      constructions=len(sens['constructions']))
    if args.what in ('evaluate', 'all'):
        ev = run_evaluate()
        summary['evaluate'] = dict(rows=len(ev['rows']))
    if args.what in ('fingerprints', 'all'):
        fp = run_fingerprints()
        summary['fingerprints'] = dict(inputs_ok=all(v['match'] for v in fp['inputs'].values()),
                                       outputs=len(fp['outputs']))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
