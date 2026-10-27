"""Freeze-first retrospective check on B4 pass 2 (candidate cells D/B only).

The explicit freeze manifest is verified before any cost/rule/result is read:
cost/rule/catalog/selection files, the analysis modules that affect the result,
the frozen executor and the declared inputs.  A mismatch raises immediately and
no normal validation output is produced.  This is a consistency check relative
to the specified manifest, not tamper-proof authentication or a proof of
historical execution order; the manifest does not contain its own SHA and is
never rewritten here.  B4 pass 2 was already analyzed in v1, so this is a
retrospective check, not a prospective holdout.
"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

FREEZE_SCHEMA = 'm3_b2_empirical_plan_selector_freeze_v1_r1'
FREEZE_ENTRIES = ('costs', 'rules', 'catalog', 'selection_240', 'selection_180')
REQUIRED_MODULES = ('evidence', 'evaluator', 'selection', 'plan_model', 'model_env', 'validate', 'freeze')
REQUIRED_INPUT_ROLES = ('primary_result', 'primary_config', 'lead_source',
                        'pressure_source', 'checkpoint_source',
                        'supplemental_result:b5', 'supplemental_result:b6',
                        'supplemental_result:b7', 'supplemental_correction:b7')


class FreezeMismatch(ValueError):
    """The specified manifest does not match the current files."""


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _check_entry(entry, label):
    path = Path((entry or {}).get('path') or '')
    expected = (entry or {}).get('sha256')
    if not path or not expected:
        raise FreezeMismatch('%s: path/sha256 missing from freeze manifest' % label)
    if not path.is_file():
        raise FreezeMismatch('%s: file does not exist: %s' % (label, path))
    actual = _sha(path)
    if actual != expected:
        raise FreezeMismatch('%s: sha256 %s != frozen %s (%s)' % (label, actual, expected, path))
    return path.resolve()


def verify_freeze(freeze_path):
    """Verify the explicit freeze manifest and return it.

    The manifest does not contain its own SHA.  This function only checks the
    current files against the manifest; it cannot prove how or when they were
    produced.
    """
    freeze_path = Path(freeze_path)
    if not freeze_path.is_file():
        raise FreezeMismatch('freeze manifest does not exist: %s' % freeze_path)
    freeze = json.loads(freeze_path.read_text())
    if freeze.get('schema') != FREEZE_SCHEMA:
        raise FreezeMismatch('unexpected freeze schema: %r' % (freeze.get('schema'),))
    if freeze.get('manifest_self_hash') != 'not included by design':
        raise FreezeMismatch('freeze manifest must state that it does not hash itself')
    if 'self_sha256' in freeze or 'manifest_sha256' in freeze:
        raise FreezeMismatch('freeze manifest must not contain its own SHA')
    for key in FREEZE_ENTRIES:
        _check_entry(freeze.get(key), key)
    modules = freeze.get('modules') or {}
    missing = sorted(set(REQUIRED_MODULES) - set(modules))
    extra = sorted(set(modules) - set(REQUIRED_MODULES))
    if missing or extra:
        raise FreezeMismatch('module set mismatch: missing=%s extra=%s' % (missing, extra))
    for name in REQUIRED_MODULES:
        _check_entry(modules[name], 'module:' + name)
    _check_entry(freeze.get('executor'), 'executor')
    inputs = freeze.get('inputs') or []
    roles = [x.get('role') for x in inputs]
    if roles != list(REQUIRED_INPUT_ROLES):
        raise FreezeMismatch('input role set/order mismatch: %r' % (roles,))
    for entry in inputs:
        _check_entry(entry, 'input:' + str(entry.get('role')))
    return freeze


def _require_frozen_args(costs_path, rules_path, freeze):
    costs = Path(costs_path).resolve()
    rules = Path(rules_path).resolve()
    frozen_costs = Path(freeze['costs']['path']).resolve()
    frozen_rules = Path(freeze['rules']['path']).resolve()
    if costs != frozen_costs:
        raise FreezeMismatch('--costs %s is not the frozen manifest path %s' % (costs, frozen_costs))
    if rules != frozen_rules:
        raise FreezeMismatch('--rules %s is not the frozen manifest path %s' % (rules, frozen_rules))


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
        response = r['ready_upper_ns'] / 1e6
        completion = rel + response
        actual[('Refresh', 'refresh%d' % r['id'])] = dict(
            release_ms=round(rel, 6), deadline_ms=round(deadline, 6),
            completion_ms=round(completion, 6), status=r['status'],
            margin_ms=round(deadline - completion, 6),
            response_ms=round(response, 6))
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
            completion_ms=x['completion_offset_ms'], margin_ms=x['refresh_margin_ms'],
            response_ms=x['refresh_response_ms'], status=x['status'])
    return jobs


BLOCK_LABELS = {'two_9_9': ('B1', 'B2'), 'three_prefix_9_9': ('P', 'B1', 'B2')}
COMPLETION_TYPES = ('Expert', 'ContextBlock')
DEADLINE_TYPES = ('Cycle', 'Refresh')


def validate(costs_path, rules_path, freeze_path):
    freeze = verify_freeze(freeze_path)
    _require_frozen_args(costs_path, rules_path, freeze)
    # Import only after the manifest has verified these modules.
    from evidence import B4_RESULT, B4_CANDIDATE_CELLS, sha
    from evaluator import evaluate
    from selection import CANDIDATES, POLICY, TARGET, scenario_for

    costs_path = Path(costs_path); rules_path = Path(rules_path)
    costs = json.loads(costs_path.read_text()); rules = json.loads(rules_path.read_text())
    if costs.get('source', {}).get('result_sha256') != sha(B4_RESULT):
        raise FreezeMismatch('cost source result SHA differs from current B4 result')
    if rules.get('model_sha256') != sha(Path(__file__).resolve().parent/'plan_model.py'):
        raise FreezeMismatch('model SHA differs from frozen rule')
    data = json.loads(B4_RESULT.read_text())
    rows = []
    summaries = {}
    for plan in CANDIDATES:
        cell = B4_CANDIDATE_CELLS[plan]
        seg = next(s for s in data['segments'] if s['pass_'] == 2 and s['cell'] == cell)
        actual = actual_jobs(seg)
        actual_cycle = {'PASS': 0, 'FAIL': 0, 'INCOMPLETE': 0}
        actual_refresh = {'PASS': 0, 'FAIL': 0, 'INCOMPLETE': 0}
        for (jt, _), a in actual.items():
            if jt == 'Cycle': actual_cycle[a['status']] = actual_cycle.get(a['status'], 0) + 1
            if jt == 'Refresh': actual_refresh[a['status']] = actual_refresh.get(a['status'], 0) + 1
        for kind in ('typical', 'stress'):
            sc = scenario_for(costs, plan, kind)
            pred = evaluate(plan, sc, policy=POLICY, cycles=TARGET['cycles'],
                            period=TARGET['period_ms'], phase=TARGET['phase_ms'],
                            gap_ms=rules['model_constants']['gap_ms'],
                            publish_cost_ms=rules['model_constants']['publish_cost_ms'])
            pjobs = predicted_jobs(pred)
            key = '%s/%s' % (plan, kind)
            errs = []; response_errs = []
            status_match = 0; missing = 0
            completion_jobs = completion_match = completion_missing = 0
            deadline_jobs = deadline_match = deadline_missing = 0
            expert_deadline_jobs = expert_deadline_match = 0
            false_feas = 0; false_infeas = 0
            scenario_rows = 0
            for jt, jid in sorted(actual, key=lambda x: (x[0], x[1])):
                a = actual[(jt, jid)]; p = pjobs.get((jt, jid))
                job_class = 'completion' if jt in COMPLETION_TYPES else 'deadline'
                scenario_rows += 1
                if p is None:
                    missing += 1
                    if job_class == 'completion':
                        completion_jobs += 1; completion_missing += 1
                    else:
                        deadline_jobs += 1; deadline_missing += 1
                    rows.append(dict(plan=plan, scenario=kind, segment_id=seg['segment_id'], job_type=jt,
                                     job_id=jid, job_class=job_class,
                                     predicted_status=None, actual_status=a['status'],
                                     match=False, predicted_completion_ms=None, actual_completion_ms=a['completion_ms'],
                                     error_ms=None, predicted_margin_ms=None, actual_margin_ms=a.get('margin_ms'),
                                     predicted_refresh_response_ms=None,
                                     actual_refresh_response_ms=a.get('response_ms'),
                                     refresh_response_error_ms=None,
                                     classification='UNPREDICTED'))
                    continue
                if job_class == 'completion':
                    completion_jobs += 1
                else:
                    deadline_jobs += 1
                pc = p.get('completion_ms'); ac = a.get('completion_ms')
                error = None if pc is None or ac is None else round(pc - ac, 6)
                if error is not None: errs.append(abs(error))
                pre = p.get('response_ms'); are = a.get('response_ms')
                rerr = None if pre is None or are is None else round(pre - are, 6)
                if rerr is not None: response_errs.append(abs(rerr))
                ps = p.get('status'); ass = a.get('status')
                match = ps == ass
                if match: status_match += 1
                cls = 'MATCH' if match else 'MISMATCH'
                if job_class == 'completion':
                    if match: completion_match += 1
                    if jt == 'Expert':
                        expert_deadline_jobs += 1
                        pm = p.get('margin_ms'); am = a.get('margin_ms')
                        pd = 'PASS' if pm is not None and pm >= 0 else ('FAIL' if pm is not None else 'INCOMPLETE')
                        ad = 'PASS' if am is not None and am >= 0 else ('FAIL' if am is not None else 'INCOMPLETE')
                        if pd == ad: expert_deadline_match += 1
                else:
                    if match: deadline_match += 1
                    if ps == 'PASS' and ass != 'PASS':
                        false_feas += 1; cls = 'FALSE_FEASIBLE'
                    elif ps == 'FAIL' and ass == 'PASS':
                        false_infeas += 1; cls = 'FALSE_INFEASIBLE'
                rows.append(dict(plan=plan, scenario=kind, segment_id=seg['segment_id'], job_type=jt,
                                 job_id=jid, job_class=job_class,
                                 predicted_status=ps, actual_status=ass, match=match,
                                 predicted_completion_ms=pc, actual_completion_ms=ac, error_ms=error,
                                 predicted_margin_ms=p.get('margin_ms'), actual_margin_ms=a.get('margin_ms'),
                                 predicted_refresh_response_ms=pre, actual_refresh_response_ms=are,
                                 refresh_response_error_ms=rerr,
                                 classification=cls))
            summaries[key] = dict(
                plan=plan, scenario=kind, segment_id=seg['segment_id'],
                jobs=scenario_rows, predicted_jobs=len(pjobs), actual_jobs=len(actual),
                status_match=status_match, missing=missing,
                completion_jobs=completion_jobs, completion_match=completion_match,
                completion_missing=completion_missing,
                deadline_jobs=deadline_jobs, deadline_match=deadline_match,
                deadline_missing=deadline_missing,
                expert_deadline_jobs=expert_deadline_jobs,
                expert_deadline_status_match=expert_deadline_match,
                false_feasible=false_feas, false_infeasible=false_infeas,
                actual_cycle_counts=dict(actual_cycle, denominator=sum(actual_cycle.values())),
                actual_refresh_counts=dict(actual_refresh, denominator=sum(actual_refresh.values())),
                mean_abs_completion_error_ms=round(statistics.mean(errs), 6) if errs else None,
                max_abs_completion_error_ms=round(max(errs), 6) if errs else None,
                mean_abs_refresh_response_error_ms=round(statistics.mean(response_errs), 6) if response_errs else None,
                max_abs_refresh_response_error_ms=round(max(response_errs), 6) if response_errs else None,
                predicted_feasible=pred['feasible'], model_status=pred['status'],
                min_cycle_margin_ms=pred['min_cycle_margin_ms'],
                min_expert_margin_ms=pred['min_expert_margin_ms'],
                min_refresh_margin_ms=pred['min_refresh_margin_ms'],
                max_refresh_response_ms=pred['max_refresh_response_ms'],
                max_refresh_completion_offset_ms=pred['max_refresh_completion_offset_ms'])
    return dict(schema='m3_b2_empirical_plan_selector_validation_v1_r1',
                validation='B4 pass 2 D/B; retrospective: pass-1 cost extraction, pass-2 separate evaluation',
                identity=dict(
                    kind='retrospective_check',
                    label='first-pass cost extraction, second-pass separate evaluation',
                    prospective=False,
                    previously_unseen=False,
                    note='B4 pass 2 was already analyzed in v1; cost extraction did not use it, but this is not a prospective holdout.'),
                condition=TARGET, condition_fingerprint=costs['condition']['fingerprint'],
                candidate_condition_fingerprints={p: costs['candidates'][p]['condition']['fingerprint'] for p in CANDIDATES},
                rows=rows, summaries=summaries,
                boundary='retrospective same-process sequential check, not an independent repeat, not external generalization, and not previously unseen data',
                freeze=dict(path=str(Path(freeze_path).resolve()), sha256=_sha(freeze_path),
                            modules_checked=sorted(freeze['modules']),
                            inputs_checked=[x['role'] for x in freeze['inputs']],
                            boundary='consistency relative to the specified manifest; not tamper-proof authentication or historical execution-order proof'),
                source=dict(cost_file=str(costs_path), cost_sha256=_sha(costs_path),
                            rules_file=str(rules_path), rules_sha256=_sha(rules_path),
                            b4_result=str(B4_RESULT), b4_result_sha256=_sha(B4_RESULT)))


def write_validation(costs, rules, out_dir, freeze_path):
    # Verify and evaluate before creating the output directory: a mismatch
    # leaves no partial "normal" validation result behind.
    v = validate(costs, rules, freeze_path)
    out_dir = Path(out_dir).resolve()
    if out_dir.exists():
        raise FileExistsError('output directory already exists: %s' % out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir/'VALIDATION.json').write_text(json.dumps(v, indent=2, sort_keys=True)+'\n')
    fields = ['plan','scenario','segment_id','job_type','job_id','job_class','predicted_status',
              'actual_status','match','predicted_completion_ms','actual_completion_ms','error_ms',
              'predicted_margin_ms','actual_margin_ms','predicted_refresh_response_ms',
              'actual_refresh_response_ms','refresh_response_error_ms','classification']
    with (out_dir/'VALIDATION_JOBS.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for row in v['rows']: w.writerow({k: row.get(k) for k in fields})
    lines = ['# B4 retrospective check (r1)', '',
             'Identity: first-pass cost extraction, second-pass separate evaluation (第一遍成本提取、第二遍分离评价的回顾性检验). B4 pass 2 was already analyzed in v1; this is not prospective and not previously unseen data.', '',
             'Freeze: the specified manifest was verified for costs/rules/catalog/selection, analysis modules, executor and declared inputs before this read. This is consistency relative to the manifest, not tamper-proof authentication or a proof of execution timing.', '',
             '| plan | scenario | completion jobs | completion match | deadline jobs | deadline match | false feasible | false infeasible | actual cycle PASS | actual refresh PASS | mean/max abs offset ms | max abs response ms |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key, s in sorted(v['summaries'].items()):
        lines.append('| %s | %s | %d | %d | %d | %d | %d | %d | %d/%d | %d/%d | %s / %s | %s |' % (
            s['plan'], s['scenario'], s['completion_jobs'], s['completion_match'],
            s['deadline_jobs'], s['deadline_match'], s['false_feasible'], s['false_infeasible'],
            s['actual_cycle_counts']['PASS'], s['actual_cycle_counts']['denominator'],
            s['actual_refresh_counts']['PASS'], s['actual_refresh_counts']['denominator'],
            s['mean_abs_completion_error_ms'], s['max_abs_completion_error_ms'],
            s['max_abs_refresh_response_error_ms']))
    lines += ['', 'Completion status (Expert/block) and deadline status (cycle/refresh) are separate and are not merged into one classification accuracy. The zero false-feasible/false-infeasible count applies only to these B4 samples; it does not establish critical-failure discrimination. No cost/rule was re-estimated after this read.', '']
    (out_dir/'VALIDATION.md').write_text('\n'.join(lines))
    return v


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--costs', type=Path, required=True)
    ap.add_argument('--rules', type=Path, required=True)
    ap.add_argument('--freeze', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    v = write_validation(a.costs, a.rules, a.out, a.freeze)
    print(json.dumps({'status': 'VALIDATED', 'out': str(a.out), 'summaries': v['summaries']}, indent=2))
