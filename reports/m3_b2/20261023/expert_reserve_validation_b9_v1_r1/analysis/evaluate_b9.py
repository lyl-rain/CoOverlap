#!/usr/bin/env python3
"""Offline evaluation of one B9 run: correctness, official performance, selection.

Repairs over v1:
  * official statistics reuse the frozen ``replay_stats``/``classify`` interval
    semantics; Expert completion and Expert deadline are separate;
  * Refresh jobs have a status again (32 real PASS no longer counted as 0);
  * a missing ``response_upper_ns`` yields None, never a crash or a zero;
  * an interval that straddles the deadline is UNCERTAIN, not forced FAIL;
  * denominators come from the declared obligations (64 Expert / 64 Cycle /
    32 Refresh across 8 segments), including unstarted / partially recorded runs;
  * malformed or duplicate job ids and illegal intervals are INVALID_EVIDENCE;
  * the frozen prediction is actually compared with the run (order, versions,
    completion/response errors, deadline status, false feasible/infeasible,
    stress exceedance, reserve mismatch);
  * the condition check covers every necessary field, not only the label;
  * the frozen inputs are verified before any verdict is produced.

    python3 analysis/evaluate_b9.py --result <run>/model/result.json --out <run>/analysis [--config ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
B9 = HERE.parent
DAY = B9.parent
DEPLOY = B9 / 'deployment'
for path in (str(DEPLOY), str(B9 / 'prediction'),
             str(DAY / 'expert_reserve_selector_v1_r1' / 'ers')):
    if path not in sys.path:
        sys.path.insert(0, path)

from m2_executor import replay_stats              # noqa: E402
from period_obligation_stats import classify      # noqa: E402
import prediction_model as pm                     # noqa: E402

PROTOCOL = 'm3_b9_expert_reserve_validation_v1'
RESERVE_MS = 10.0
DECLARED_CYCLES = 8
DECLARED_SEGMENTS = 8
JOB_TYPES = ('Expert', 'ContextBlock', 'Cycle', 'Refresh')
STATUS_ORDER = ('PASS', 'FAIL', 'UNCERTAIN', 'INCOMPLETE', 'INVALID')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def protocol_id(result):
    proto = result.get('protocol')
    return proto.get('id') if isinstance(proto, dict) else proto


def _protocol_work(result):
    proto = result.get('protocol')
    return (proto.get('work') or {}).get('batch') if isinstance(proto, dict) else None


def _ms(ns):
    return None if ns is None else round(ns / 1e6, 6)


# --------------------------------------------------------------- frozen identity

def verify_frozen(config_path, rules_path, costs_path, prediction_path,
                  selection_path, analysis_paths):
    """Compare every frozen input with the identity recorded in the config."""
    checks = []

    def add(name, expected, actual):
        checks.append(dict(name=name, expected=expected, actual=actual,
                           ok=bool(expected) and expected == actual))

    config = load(config_path)
    add('config.protocol', PROTOCOL, config.get('id'))
    add('config.prediction.sha256', config['prediction']['sha256'], sha(prediction_path))
    add('config.selection.sha256', config['selection']['sha256'], sha(selection_path))
    add('config.rules.sha256', config['selection']['rule_sha256'], sha(rules_path))
    add('config.costs.sha256', config['selection']['costs_sha256'], sha(costs_path))
    for name, path in sorted(analysis_paths.items()):
        recorded = (config.get('analysis_modules') or {}).get(name)
        if recorded:
            add('analysis.' + name, recorded, sha(path))
    return dict(checks=checks,
                ok=all(c['ok'] for c in checks),
                failed=[c['name'] for c in checks if not c['ok']])


# ------------------------------------------------------------------ conditions

def _expected_condition(config):
    return dict(
        protocol=config['id'],
        period_ns=sorted({c['period_ns'] for c in config['run']}),
        cycles=config['cycles'],
        phase_ns=config['phase_ns'],
        cells={c['cell']: dict(plan=c['plan'], policy=c['policy'],
                               period_ns=c['period_ns']) for c in config['run']},
        segments=list(config['segment_ids']),
        lead_ms=10,
        pressure='quiet, 0 workers',
        reserve_ms=config['reserve']['value_ms'],
    )


def condition_check(result, config, config_path, deployment_manifest_path=None):
    """Every necessary field, with an explicit verdict per field."""
    exp = _expected_condition(config)
    fields = []

    def norm(value):
        if isinstance(value, (set, frozenset)):
            return sorted(value)
        if isinstance(value, tuple):
            return [norm(x) for x in value]
        if isinstance(value, list):
            return [norm(x) for x in value]
        return value

    def add(name, expected, actual, verdict=None):
        expected, actual = norm(expected), norm(actual)
        if verdict is None:
            if actual is None:
                verdict = 'UNKNOWN'
            elif expected == actual:
                verdict = 'MATCH'
            else:
                verdict = 'MISMATCH'
        fields.append(dict(field=name, expected=expected, actual=actual, verdict=verdict))

    add('result.protocol', exp['protocol'], protocol_id(result))
    add('result.config_sha256', sha(config_path), result.get('config_sha256'))
    segs = result.get('segments') or []
    add('segments.count', DECLARED_SEGMENTS, len(segs))
    add('segments.ids', exp['segments'], [s.get('segment_id') for s in segs])
    periods = sorted({s.get('period_ns') for s in segs})
    add('segments.periods', exp['period_ns'], periods)
    phases = sorted({(s.get('manifest') or {}).get('phase_ns') for s in segs})
    add('segments.phase_ns', [exp['phase_ns']], phases)
    cycles = sorted({(s.get('manifest') or {}).get('cycles') for s in segs})
    add('segments.cycles', [exp['cycles']], cycles)
    plans = [(s.get('segment_id'), s.get('plan'), s.get('mode')) for s in segs]
    want = [(sid, exp['cells'][c['cell']]['plan'], exp['cells'][c['cell']]['policy'])
            for sid, c in zip(exp['segments'], config['run'])]
    add('segments.plan_policy', want, plans)
    bindings = {(s.get('manifest') or {}).get('binding') for s in segs}
    add('manifest.binding', {config['binding']}, bindings)
    blocks = {s.get('segment_id'): (s.get('block_plan') or {}).get('id') for s in segs}
    add('segments.block_plan', {sid: exp['cells'][c['cell']]['plan']
                                for sid, c in zip(exp['segments'], config['run'])}, blocks)
    cfg = result.get('configuration') or {}
    add('configuration.label', 'H_frozen', cfg.get('label'))
    add('configuration.matches_frozen_context', True, cfg.get('matches_frozen_context'))
    add('configuration.s0_context_sha256',
        ['ea62dc726393626b26de570d3e66a8d00a8a7145d5d240398b350c0ddb3eec4f',
         '7ff20f0d73d9db1cb8cd1cf1ddf435314ad2cd42cf8f644f41d4a7dd7bb7974b',
         '4357374f84765b337d2633aa3cae5dd08003333691acad3e710223de29edfe93'],
        cfg.get('S0_context_sha256'))
    add('observation.mode', 'performance', result.get('observation_mode'))
    add('result.prediction.path', config['prediction']['path'],
        (result.get('prediction_identity') or {}).get('path'))
    add('result.prediction.sha256', config['prediction']['sha256'],
        (result.get('prediction_identity') or {}).get('sha256'))
    add('result.selection_fingerprint', config['selection']['fingerprint'],
        (result.get('selection_freeze') or {}).get('fingerprint'))
    add('result.reserve_ms', exp['reserve_ms'],
        (result.get('selection_freeze') or {}).get('reserve_ms'))
    # lead / quiet are declared by the frozen config and enforced by the entry
    # (it refuses any other CONFIG.json and any injection/pressure environment).
    design = config.get('design') or {}
    lead = design.get('lead_ms')
    pressure = None
    if design.get('pressure_mode') is not None and design.get('pressure_workers') is not None:
        pressure = '%s, %s workers' % (design['pressure_mode'],
                                       design['pressure_workers'])
    add('lead_ms', exp['lead_ms'], lead)
    add('pressure', exp['pressure'], pressure)
    # fixed inputs / checkpoint / precision: recorded as source fingerprints
    add('source_config_fingerprints', 'non-empty',
        'non-empty' if result.get('source_config_fingerprints') else None)
    # retention per plan (design difference, checked against that plan's layout)
    retention = []
    for s in segs:
        plan = s.get('plan')
        want_bytes = None
        if deployment_manifest_path is not None or True:
            from m2_clean_core import retention_layout
            from m3_b9_plan import PLANS
            want_bytes = retention_layout(exp['cycles'], PLANS[plan])['nbytes']
        got = (s.get('validation') or {}).get('payload_B')
        retention.append((s.get('segment_id'), want_bytes, got))
    add('retention.payload_per_plan', 'plan layout',
        'ok' if all(w == g for _sid, w, g in retention) else retention,
        verdict='MATCH' if all(w == g for _sid, w, g in retention) else 'MISMATCH')
    add('initial_clock_limits', 'recorded', 'recorded'
        if result.get('initial_clock_limits') else None)
    mismatches = [f['field'] for f in fields if f['verdict'] == 'MISMATCH']
    unknown = [f['field'] for f in fields if f['verdict'] == 'UNKNOWN']
    status = ('CONDITION_MISMATCH' if mismatches
              else ('INSUFFICIENT_EVIDENCE' if unknown else 'MATCH'))
    return dict(status=status, fields=fields, mismatches=mismatches, unknown=unknown,
                note='new and old protocol ids are independent; equality is not required')


# ------------------------------------------------------------ official jobs/status

def _parse_units(raw):
    out = {}
    for key, value in (raw or {}).items():
        if isinstance(key, tuple):
            out[key] = value
            continue
        text = str(key).strip().strip('()')
        m, b = text.split(',')
        out[(int(m), int(b))] = value
    return out


def segment_official(segment, declared, reserve_ms=RESERVE_MS):
    """Official job rows of one segment, frozen classification, explicit issues."""
    issues = []
    seg_id = segment.get('segment_id')
    manifest = segment.get('manifest')
    if not isinstance(manifest, dict) or segment.get('t0_ns') is None:
        return dict(segment_id=seg_id, plan=None, period_ns=None, issues=['missing manifest/t0'],
                    experts=[], cycles=[], refreshes=[], blocks=[],
                    status='INVALID_EVIDENCE')
    t0 = segment['t0_ns']
    m = manifest
    exp_ids = [e['id'] for e in m['experts']]
    ref_ids = [r['id'] for r in m['refreshes']]
    raw_experts = segment.get('experts') or {}
    raw_pub = segment.get('published') or {}
    raw_blocks = segment.get('blocks') or {}
    raw_units = _parse_units(segment.get('units'))
    extra = (set(raw_experts) - {str(j) for j in exp_ids}
             | set(raw_pub) - {str(q) for q in ref_ids})
    if extra:
        issues.append('unexpected job ids: %s' % sorted(extra))
    for key, value in list(raw_experts.items()) + list(raw_pub.items()) + \
            [(str(k), v) for k, v in raw_units.items()] + list(raw_blocks.items()):
        if not (isinstance(value, (list, tuple)) and len(value) == 2):
            issues.append('job %s is not a (lower, upper) pair' % (key,))
            continue
        lo, hi = value
        if not (isinstance(lo, int) and isinstance(hi, int) and lo <= hi):
            issues.append('job %s has an illegal interval %r' % (key, value))
    experts, cycles, refreshes, blocks = [], [], [], []
    if issues:
        stats = None
    else:
        try:
            stats = replay_stats(m, {int(k): tuple(v) for k, v in raw_experts.items()},
                                 raw_units, {int(k): tuple(v) for k, v in raw_pub.items()},
                                 t0=t0)
        except ValueError as exc:
            issues.append('replay_stats refused the record: %s' % exc)
            stats = None
    cycle_by = {}
    if stats is not None:
        for row in stats['cycles']:
            j = row['cycle']
            margin = (None if row['response_upper_ns'] is None else
                      round((row['deadline_ns'] - row['release_ns']
                             - row['response_upper_ns']) / 1e6, 6))
            cycle_by[j] = dict(
                job_id='cycle%d' % j, release_ms=_ms(row['release_ns'] - t0),
                deadline_ms=_ms(row['deadline_ns'] - t0),
                completion_ms=(None if row['response_upper_ns'] is None else
                               _ms(row['release_ns'] + row['response_upper_ns'] - t0)),
                response_ms=(None if row['response_upper_ns'] is None else
                             _ms(row['response_upper_ns'])),
                response_interval_ms=[None if row['response_lower_ns'] is None else
                                      _ms(row['response_lower_ns']),
                                      None if row['response_upper_ns'] is None else
                                      _ms(row['response_upper_ns'])],
                margin_ms=margin, status=row['status'],
                expert_status=row['expert_status'], unit_status=row['unit_status'])
            cycles.append(cycle_by[j])
        for row in stats['refreshes']:
            q = row['id']
            margin = (None if row['ready_upper_ns'] is None else
                      round((row['deadline_ms'] if 'deadline_ms' in row else 2 * m['period_ns'] / 1e6)
                            - row['ready_upper_ns'] / 1e6, 6))
            refreshes.append(dict(
                job_id='refresh%d' % q, release_ms=_ms(q * 2 * m['period_ns']),
                deadline_ms=_ms(q * 2 * m['period_ns'] + 2 * m['period_ns']),
                completion_ms=(None if row['ready_upper_ns'] is None else
                               _ms(q * 2 * m['period_ns'] + row['ready_upper_ns'])),
                response_ms=(None if row['ready_upper_ns'] is None else
                             _ms(row['ready_upper_ns'])),
                response_interval_ms=[None if row['ready_lower_ns'] is None else
                                      _ms(row['ready_lower_ns']),
                                      None if row['ready_upper_ns'] is None else
                                      _ms(row['ready_upper_ns'])],
                margin_ms=margin, status=row['status'], k_lower=row['k_lower'],
                k_upper=row['k_upper']))
    for e in m['experts']:
        j = e['id']
        rel = t0 + e['release_ns']
        dl = t0 + e['deadline_ns']
        rec = raw_experts.get(str(j))
        if rec is None:
            experts.append(dict(job_id='E%d' % j, release_ms=_ms(e['release_ns']),
                                deadline_ms=_ms(e['deadline_ns']), dispatch_ms=None,
                                completion_ms=None, response_ms=None, margin_ms=None,
                                completion_status='INCOMPLETE', deadline_status='INCOMPLETE'))
            continue
        lo, hi = rec
        if not (isinstance(lo, int) and isinstance(hi, int) and lo <= hi and lo >= rel):
            experts.append(dict(job_id='E%d' % j, release_ms=_ms(e['release_ns']),
                                deadline_ms=_ms(e['deadline_ns']), dispatch_ms=None,
                                completion_ms=None, response_ms=None, margin_ms=None,
                                completion_status='INVALID', deadline_status='INVALID'))
            continue
        completion_status = 'COMPLETE'
        deadline_status = classify(lo, hi, dl)
        experts.append(dict(
            job_id='E%d' % j, release_ms=_ms(e['release_ns']),
            deadline_ms=_ms(e['deadline_ns']), dispatch_ms=None,
            completion_ms=_ms(hi - t0), response_ms=_ms(hi - rel),
            response_interval_ms=[_ms(lo - rel), _ms(hi - rel)],
            margin_ms=_ms(dl - hi), completion_status=completion_status,
            deadline_status=deadline_status))
    blocks_plan = {b['refresh'] * 100 + b['block']: (b['start_ms'], b['completion_ms'])
                   for b in ((stats or {}).get('blocks') or [])}
    for key, (lo, hi) in sorted(raw_blocks.items()):
        q, b = key.strip('()').split(',')
        q, b = int(q), int(b)
        gi = pm._group_of(segment['plan'], b) if segment.get('plan') in pm.GROUPS else 0
        cyc = cycle_by.get(2 * q + gi)
        blocks.append(dict(job_id='R%d/B%d' % (q, b + 1), refresh=q, block=b,
                           obligation_group=gi,
                           release_ms=_ms(q * 2 * m['period_ns']),
                           dispatch_ms=None, completion_ms=_ms(hi - t0),
                           response_ms=_ms(hi - t0 - q * 2 * m['period_ns']),
                           margin_ms=(None if cyc is None or cyc['margin_ms'] is None
                                      else round(cyc['deadline_ms'] - _ms(hi - t0), 6)),
                           status=(None if cyc is None else cyc['status'])))
    status = 'INVALID_EVIDENCE' if issues else 'OK'
    return dict(segment_id=seg_id, cell=segment.get('cell'), plan=segment.get('plan'),
                period_ns=segment.get('period_ns'),
                period_ms=None if segment.get('period_ns') is None else
                segment['period_ns'] / 1e6, issues=issues, status=status,
                experts=experts, cycles=cycles, refreshes=refreshes, blocks=blocks,
                declared=dict(experts=len(exp_ids), cycles=len(exp_ids),
                              refreshes=len(ref_ids),
                              blocks=len(raw_blocks) if raw_blocks else None))


def official_summary(result, config):
    """Per-segment official statistics with declared denominators preserved."""
    by_id = {s.get('segment_id'): s for s in (result.get('segments') or [])}
    rows = []
    totals = {jt: {k: 0 for k in STATUS_ORDER} for jt in ('Expert', 'Cycle', 'Refresh')}
    declared = {jt: 0 for jt in ('Expert', 'Cycle', 'Refresh')}
    for sid, cell in zip(config['segment_ids'], config['run']):
        segment = by_id.get(sid)
        n_exp, n_cyc, n_ref = DECLARED_CYCLES, DECLARED_CYCLES, DECLARED_CYCLES // 2
        declared['Expert'] += n_exp
        declared['Cycle'] += n_cyc
        declared['Refresh'] += n_ref
        if segment is None:
            row = dict(segment_id=sid, cell=cell['cell'], plan=cell['plan'],
                       period_ms=cell['period_ns'] / 1e6, status='MISSING',
                       issues=['segment not recorded'], experts=[], cycles=[], refreshes=[],
                       blocks=[], declared=dict(experts=n_exp, cycles=n_cyc, refreshes=n_ref))
            rows.append(row)
            for jt, n in (('Expert', n_exp), ('Cycle', n_cyc), ('Refresh', n_ref)):
                totals[jt]['INCOMPLETE'] += n
            continue
        row = segment_official(segment, cell)
        rows.append(row)
        if row['status'] == 'INVALID_EVIDENCE':
            for jt, n in (('Expert', n_exp), ('Cycle', n_cyc), ('Refresh', n_ref)):
                totals[jt]['INVALID'] += n
            continue
        for e in row['experts']:
            totals['Expert'][e['deadline_status']
                             if e['completion_status'] == 'COMPLETE' else 'INCOMPLETE'] += 1
        for c in row['cycles']:
            totals['Cycle'][c['status']] += 1
        for r in row['refreshes']:
            totals['Refresh'][r['status']] += 1
    per_cell = {}
    for row in rows:
        key = '%s@p%d' % (row['cell'], int(row['period_ms']))
        bucket = per_cell.setdefault(key, dict(plan=row['plan'], period_ms=row['period_ms'],
                                               cycles={k: 0 for k in STATUS_ORDER},
                                               refreshes={k: 0 for k in STATUS_ORDER},
                                               experts={k: 0 for k in STATUS_ORDER},
                                               segments=[]))
        bucket['segments'].append(row['segment_id'])
        for jt, key2 in (('Cycle', 'cycles'), ('Refresh', 'refreshes'), ('Expert', 'experts')):
            for x in row[key2]:
                st = x.get('status') if jt != 'Expert' else (
                    x['deadline_status'] if x['completion_status'] == 'COMPLETE' else 'INCOMPLETE')
                bucket[keys(jt)][st] = bucket[keys(jt)].get(st, 0) + 1
    return dict(segments=rows, totals=totals, declared=declared, per_cell=per_cell,
                note='official deadlines only; denominators are the declared obligations; '
                     'INCOMPLETE/INVALID are never counted as PASS')


def keys(jt):
    return {'Cycle': 'cycles', 'Refresh': 'refreshes', 'Expert': 'experts'}[jt]


# ------------------------------------------------------------------ prediction

def load_prediction(path, result, rules_doc, costs_doc):
    """Load the frozen prediction;补齐 missing job kinds from the frozen B8 costs."""
    pred = load(path)
    problems = pm.completeness(pred)
    completed = []
    if problems:
        rebuilt = pm.build(result_frozen_b8(), rules_doc, costs_doc, None, RESERVE_MS)
        existing = {(r['budget_ms'], r['plan'], r['scenario'], r['job_type'])
                    for r in pred.get('jobs') or []}
        added = [r for r in rebuilt['jobs']
                 if (r['budget_ms'], r['plan'], r['scenario'], r['job_type']) not in existing]
        pred.setdefault('jobs', []).extend(added)
        for k in ('order', 'budgets', 'selection', 'boundary'):
            if k not in pred:
                pred[k] = rebuilt[k]
        completed = sorted({p.split()[0] for p in problems})
        problems = pm.completeness(pred)
    return pred, dict(source='frozen prediction file', completed_fields=completed,
                      problems=problems)


def result_frozen_b8():
    import common as ers_common
    return ers_common.rbe_env.load(ers_common.rbe_env.B8_RESULT)


def compare_segment(row, pred, scenario, reserve_ms=RESERVE_MS):
    """Prediction vs the recorded trajectory of one segment."""
    period = row['period_ms']
    plan = row['plan']
    pj = [r for r in pred.get('jobs') or []
          if r.get('budget_ms') == period and r.get('plan') == plan
          and r.get('scenario') == scenario]
    if not pj:
        return dict(segment_id=row['segment_id'], scenario=scenario,
                    status='MISSING_PREDICTION', predicted_missing=[],
                    actual_missing=[], predicted_jobs=0, actual_jobs=0)
    pred_by = {(r['job_type'], r['job_id']): r for r in pj}
    actual_by = {}
    for e in row['experts']:
        actual_by[('Expert', e['job_id'])] = e
    for c in row['cycles']:
        actual_by[('Cycle', c['job_id'])] = c
    for r in row['refreshes']:
        actual_by[('Refresh', r['job_id'])] = r
    for b in row['blocks']:
        actual_by[('ContextBlock', b['job_id'])] = b
    predicted_missing = sorted('%s:%s' % k for k in actual_by if k not in pred_by)
    jobs = []
    errors = {'completion': [], 'response': []}
    status_rows = {'Expert': [0, 0], 'Cycle': [0, 0], 'Refresh': [0, 0]}
    missing = 0
    for key in sorted(pred_by):
        p = pred_by[key]
        a = actual_by.get(key)
        if a is None:
            missing += 1
            jobs.append(dict(job_type=key[0], job_id=key[1], status='MISSING_ACTUAL'))
            continue
        e_comp = None
        if p.get('completion_ms') is not None and a.get('completion_ms') is not None:
            e_comp = round(p['completion_ms'] - a['completion_ms'], 6)
            errors['completion'].append(e_comp)
        e_resp = None
        if p.get('response_ms') is not None and a.get('response_ms') is not None:
            e_resp = round(p['response_ms'] - a['response_ms'], 6)
            errors['response'].append(e_resp)
        p_status = p.get('status')
        if key[0] == 'Expert':
            p_status = p.get('status') if p.get('status') in ('PASS', 'FAIL', 'UNCERTAIN',
                                                              'INCOMPLETE') else p.get('status')
            a_status = (a['deadline_status'] if a.get('completion_status') == 'COMPLETE'
                        else 'INCOMPLETE')
        else:
            a_status = a.get('status')
        if key[0] in status_rows:
            status_rows[key[0]][1] += 1
            if p_status == a_status:
                status_rows[key[0]][0] += 1
        jobs.append(dict(job_type=key[0], job_id=key[1], predicted_status=p_status,
                         actual_status=a_status,
                         status_match=(p_status == a_status),
                         completion_error_ms=e_comp, response_error_ms=e_resp,
                         predicted_margin_ms=p.get('margin_ms'),
                         actual_margin_ms=a.get('margin_ms'),
                         reserve_predicted_pass=(p.get('margin_ms') is not None
                                                 and p['margin_ms'] >= reserve_ms),
                         reserve_actual_short=(a.get('margin_ms') is not None
                                               and a['margin_ms'] < reserve_ms),
                         version_predicted=p.get('version'),
                         version_actual=(a.get('version'))))
    order_pred = ((pred.get('order') or {}).get('p%d' % int(period), {})
                  .get(plan, {}).get(scenario))
    order_actual = [x.split('/')[0] for x in []]  # filled by caller when available
    def stats(values):
        if not values:
            return dict(n=0, mean=None, abs_mean=None, abs_max=None, max=None, min=None)
        ab = [abs(v) for v in values]
        return dict(n=len(values), mean=round(sum(values) / len(values), 6),
                    abs_mean=round(sum(ab) / len(ab), 6), abs_max=round(max(ab), 6),
                    max=round(max(values), 6), min=round(min(values), 6))
    return dict(segment_id=row['segment_id'], scenario=scenario,
                status=('OK' if not predicted_missing and not missing else 'INCOMPLETE'),
                predicted_jobs=len(pred_by), actual_jobs=len(actual_by),
                missing_actual=missing, predicted_missing=predicted_missing,
                completion_error=stats(errors['completion']),
                response_error=stats(errors['response']),
                status_match={k: dict(match=v[0], total=v[1]) for k, v in status_rows.items()},
                reserve_predicted_pass_actual_short=[j['job_id'] for j in jobs
                                                     if j.get('reserve_predicted_pass')
                                                     and j.get('reserve_actual_short')],
                jobs=jobs)


def order_and_versions(segment, pred, scenario):
    period = segment['period_ns'] / 1e6
    plan = segment['plan']
    pred_order = ((pred.get('order') or {}).get('p%d' % int(period), {})
                  .get(plan, {}).get(scenario))
    actual = []
    for d in segment.get('decisions') or []:
        if d['kind'] == 'Expert':
            actual.append('E%d' % d['id'])
        elif d['kind'] == 'Context':
            actual.append('R%d/B%d' % (d['id'], d['block'] + 1))
    first = None
    if pred_order is not None:
        for i in range(min(len(pred_order), len(actual))):
            if pred_order[i] != actual[i]:
                first = dict(index=i, predicted=pred_order[i], actual=actual[i])
                break
    binds = {}
    for row in segment.get('journal') or []:
        if row and row[0] == 'bind' and row[1] not in binds:
            binds[row[1]] = row[2]
    pred_version = {}
    for r in pred.get('jobs') or []:
        if (r.get('budget_ms') == period and r.get('plan') == plan
                and r.get('scenario') == scenario and r.get('job_type') == 'Expert'):
            pred_version[r['job_id']] = r.get('version')
    mismatched = [j for j, v in pred_version.items() if binds.get(j) != v]
    return dict(predicted_order=pred_order, actual_order=actual, first_divergence=first,
                order_match=(pred_order == actual) if pred_order is not None else None,
                predicted_versions=pred_version, actual_versions=binds,
                version_match=not mismatched, version_mismatched=mismatched)


def selection_mapping(pred, period_ms):
    key = 'p%d' % int(period_ms)
    sel = (pred.get('selection') or {}).get(key) or {}
    out = {}
    for scheme in ('S0', 'S10'):
        chosen = (sel.get(scheme) or {}).get('selected')
        out[scheme] = dict(selected=chosen, status=(sel.get(scheme) or {}).get('status'),
                           reused_from=('F2' if chosen == 'two_9_9' else
                                        ('F3' if chosen == 'three_prefix_9_9' else None)))
    return out


# ----------------------------------------------------------------------- main

def evaluate(result_path, config_path, rules_path, costs_path, prediction_path,
             selection_path, analysis_paths):
    result = load(result_path)
    config = load(config_path)
    config['_path'] = str(config_path)
    frozen = verify_frozen(config_path, rules_path, costs_path, prediction_path,
                           selection_path, analysis_paths)
    condition = condition_check(result, config, config_path)
    official = official_summary(result, config)
    rules_doc = load(rules_path)
    costs_doc = load(costs_path)
    pred, pred_info = load_prediction(prediction_path, result, rules_doc, costs_doc)

    comparisons = []
    order_rows = []
    for row, cell in zip(official['segments'], config['run']):
        segment = next((s for s in result.get('segments') or []
                        if s.get('segment_id') == row['segment_id']), None)
        if segment is None:
            continue
        for scenario in ('typical', 'stress'):
            comparisons.append(compare_segment(row, pred, scenario))
        order_rows.append(dict(segment_id=row['segment_id'],
                               typical=order_and_versions(segment, pred, 'typical'),
                               stress=order_and_versions(segment, pred, 'stress')))
    totals = dict(completion_n=sum(c['completion_error']['n'] for c in comparisons
                                   if c.get('completion_error')),
                  response_n=sum(c['response_error']['n'] for c in comparisons
                                 if c.get('response_error')))
    stress = []
    for c in comparisons:
        if c['scenario'] != 'stress':
            continue
        for j in c['jobs']:
            e = j.get('completion_error_ms')
            if e is not None and e > 0:
                stress.append(dict(segment_id=c['segment_id'], job=j['job_id'],
                                   exceed_ms=e))
    false_feasible = 0
    false_infeasible = 0
    for c in comparisons:
        jobs = c['jobs']
        pred_pass = all(j.get('predicted_status') == 'PASS' for j in jobs)
        act_pass = all(j.get('actual_status') == 'PASS' for j in jobs)
        if pred_pass and not act_pass:
            false_feasible += 1
        if act_pass and not pred_pass:
            false_infeasible += 1
    invalid = []
    if not frozen['ok']:
        invalid.append(dict(kind='FROZEN_INPUT', detail=frozen['failed']))
    for row in official['segments']:
        if row['status'] == 'INVALID_EVIDENCE':
            invalid.append(dict(kind='SEGMENT_EVIDENCE', segment_id=row['segment_id'],
                                detail=row['issues']))
    part_c = dict(
        condition=condition,
        selector_domain=('EVALUATED_IN_DOMAIN' if condition['status'] == 'MATCH'
                         else 'INSUFFICIENT_EVIDENCE'),
        prediction_status=('EVALUATED' if condition['status'] == 'MATCH'
                           else 'CONDITION_MISMATCH'),
        prediction=pred_info,
        selection={row['segment_id']: selection_mapping(pred, row['period_ms'])
                   for row in official['segments']},
        comparison=dict(per_segment=comparisons, totals=totals,
                        false_feasible_segments=false_feasible,
                        false_infeasible_segments=false_infeasible,
                        stress_exceed=stress),
        order=order_rows,
        reserve=dict(
            short=sum(1 for r in official['segments'] for e in r['experts']
                      if e.get('margin_ms') is not None and e['margin_ms'] < RESERVE_MS),
            total=sum(len(r['experts']) for r in official['segments']),
            predicted_pass_actual_short=[dict(segment_id=c['segment_id'], job=j)
                                         for c in comparisons
                                         for j in c.get('reserve_predicted_pass_actual_short') or []],
            reserve_ms=RESERVE_MS),
        note='a declined domain is never reported as an in-domain SELECTED or prediction PASS; '
             'reserve shortfall is auxiliary and never an official deadline miss')
    return dict(
        schema='m3_b9_evaluation_v2', protocol=config['id'],
        source=dict(result=dict(path=str(result_path), sha256=sha(result_path)),
                    config=dict(path=str(config_path), sha256=sha(config_path)),
                    rules=dict(path=str(rules_path), sha256=sha(rules_path)),
                    costs=dict(path=str(costs_path), sha256=sha(costs_path)),
                    prediction=dict(path=str(prediction_path), sha256=sha(prediction_path)),
                    selection=dict(path=str(selection_path), sha256=sha(selection_path)),
                    analysis={k: sha(v) for k, v in sorted(analysis_paths.items())}),
        frozen=frozen,
        invalid_evidence=invalid,
        part_a_correctness=dict(
            status=result.get('status'),
            checks=(lambda c: dict(total=len(c), passed=sum(1 for x in c if x.get('pass_'))))(
                result.get('checks') or []),
            d1=result.get('in_process_equivalence'),
            gates={k: v.get('status') for k, v in (result.get('gates') or {}).items()},
            retention=[dict(segment_id=s.get('segment_id'),
                            records=(s.get('validation') or {}).get('records'),
                            payload_B=(s.get('validation') or {}).get('payload_B'))
                       for s in result.get('segments') or []],
            observed_call_counts=result.get('observed_call_counts'),
            ledger_rows=len(result.get('call_ledger') or []),
            work=_protocol_work(result)),
        part_b_official_performance=official,
        part_c_selection=part_c,
        verdict=('INVALID_EVIDENCE' if invalid else
                 ('CONDITION_MISMATCH' if condition['status'] == 'CONDITION_MISMATCH'
                  else ('INSUFFICIENT_EVIDENCE' if condition['status'] == 'INSUFFICIENT_EVIDENCE'
                        else 'EVALUATED'))))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--result', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--config', type=Path, default=B9 / 'deployment' / 'CONFIG.json')
    ap.add_argument('--rules', type=Path,
                    default=DAY / 'expert_reserve_selector_v1_r1' / 'RULES.json')
    ap.add_argument('--costs', type=Path,
                    default=DAY / 'expert_reserve_selector_v1_r1' / 'COSTS.json')
    ap.add_argument('--prediction', type=Path, default=B9 / 'prediction' / 'PREDICTION.json')
    ap.add_argument('--selection', type=Path,
                    default=B9 / 'prediction' / 'SELECTION_FREEZE.json')
    ap.add_argument('--analysis', type=Path, nargs='*', default=[HERE / 'evaluate_b9.py',
                                                                B9 / 'prediction' / 'prediction_model.py'])
    args = ap.parse_args(argv)
    analysis = {Path(p).name: Path(p) for p in args.analysis}
    out = evaluate(args.result, args.config, args.rules, args.costs, args.prediction,
                   args.selection, analysis)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'EVALUATION.json').write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')
    summary = dict(verdict=out['verdict'],
                   condition=out['part_c_selection']['condition']['status'],
                   totals=out['part_b_official_performance']['totals'],
                   invalid=len(out['invalid_evidence']))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 2 if out['invalid_evidence'] else 0


if __name__ == '__main__':
    sys.exit(main())
