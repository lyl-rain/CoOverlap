"""Plan selection with the minimal B4 applicability/condition checks.

The selector supports exactly the two declared B4 candidates and the declared
B4 condition.  Condition fields are read from ``TRAIN_COSTS.json`` and compared
with the frozen ``RULES.json`` target; a missing or mismatched necessary field
returns INSUFFICIENT_EVIDENCE, and an unrecognised target parameter returns
UNSUPPORTED_INPUT.  This is not a general configuration framework.
"""
from __future__ import annotations

import copy

from evaluator import evaluate

CANDIDATES = ('two_9_9', 'three_prefix_9_9')
POLICY = 'b2_boundary'
TARGET = dict(period_ms=240.0, phase_ms=15.0, cycles=8, policy=POLICY)
SUPPORTED_PERIODS = (180.0, 240.0)
SUPPORTED_PRESSURE = ('quiet', 'fixed_cpu_mem')

TARGET_KEYS = {
    'period_ms', 'phase_ms', 'cycles', 'policy',
    'lead_ms', 'pressure', 'protocol',
    'condition_fingerprint', 'configuration_fingerprint',
    'input_fingerprint', 'version_fingerprint',
    'retention_fingerprint', 'observation_fingerprint', 'hardware_fingerprint',
}
SHARED_CONDITION_PATHS = {
    'lead_ms': ('lead', 'lead_ms'),
    'pressure': ('pressure', 'mode'),
    'protocol': ('protocol',),
    'condition_fingerprint': ('fingerprint',),
    'configuration_fingerprint': ('configuration', 'fingerprint'),
    'input_fingerprint': ('input', 'fingerprint'),
    'version_fingerprint': ('version_consumption', 'fingerprint'),
    'retention_fingerprint': ('retention', 'fingerprint'),
    'observation_fingerprint': ('observation', 'fingerprint'),
    'hardware_fingerprint': ('hardware', 'fingerprint'),
}
SECTION_FINGERPRINTS = ('configuration', 'input', 'version_consumption',
                        'retention', 'observation', 'hardware')
CANDIDATE_FINGERPRINT_PATHS = {
    'layout_fingerprint': ('layout_fingerprint',),
    'obligation_fingerprint': ('obligation_groups', 'fingerprint'),
    'retention_fingerprint': ('retention_observed', 'fingerprint'),
    'condition_fingerprint': ('fingerprint',),
}
CANDIDATE_SECTION_FINGERPRINTS = ('obligation_groups', 'retention_observed')


def scenario_for(costs, plan, kind):
    c = costs['candidates'][plan]
    d = copy.deepcopy(c)
    d['kind'] = kind
    # blocks are already {label: {n, median, max}}; evaluator selects kind.
    return d


def margin_vector(result):
    return dict(min_cycle_margin_ms=result.get('min_cycle_margin_ms'),
                min_expert_margin_ms=result.get('min_expert_margin_ms'),
                min_refresh_margin_ms=result.get('min_refresh_margin_ms'),
                max_refresh_response_ms=result.get('max_refresh_response_ms'),
                max_refresh_completion_offset_ms=result.get('max_refresh_completion_offset_ms'))


def dominates(a, b):
    """a weakly beats b on all three margins and is strictly better on one."""
    if any(a[k] is None or b[k] is None for k in ('min_cycle_margin_ms', 'min_expert_margin_ms', 'min_refresh_margin_ms')):
        return False
    ge = all(a[k] >= b[k] for k in ('min_cycle_margin_ms', 'min_expert_margin_ms', 'min_refresh_margin_ms'))
    gt = any(a[k] > b[k] for k in ('min_cycle_margin_ms', 'min_expert_margin_ms', 'min_refresh_margin_ms'))
    return ge and gt


def _canonical_sha(value):
    # Local copy keeps selection importable without importing the evidence reader.
    import hashlib
    import json
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _get(condition, path):
    current = condition
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return 'MISSING'
        current = current[key]
    return current


def _unknown(value):
    return value is None or value == 'UNKNOWN' or value == 'MISSING'


def _self_fingerprint(condition):
    body = {k: v for k, v in condition.items() if k != 'fingerprint'}
    return _canonical_sha(body)


def _condition_defaults(rules):
    target = (rules or {}).get('target') or {}
    return {key: target[key] for key in TARGET_KEYS if key in target}


def _unsupported(reason, target, **extra):
    out = dict(status='UNSUPPORTED_INPUT', target=target, candidates={}, reason=reason)
    out.update(extra)
    return out


def _insufficient(reason, target, fields, **extra):
    out = dict(status='INSUFFICIENT_EVIDENCE', target=target, candidates={},
               missing_or_mismatched=sorted(set(fields)), reason=reason)
    out.update(extra)
    return out


def _rules_target_problems(costs, rules_target):
    """Check that the frozen target itself is compatible with the cost evidence.

    This is separate from the caller's target: a caller override must not be
    able to hide an inconsistent frozen rule file.
    """
    problems = []
    condition = costs.get('condition') or {}
    for field, path in SHARED_CONDITION_PATHS.items():
        if field not in rules_target:
            problems.append('rules.' + field)
            continue
        expected = rules_target[field]
        actual = _get(condition, path)
        if _unknown(expected) or _unknown(actual) or actual != expected:
            problems.append('rules.' + field)
    candidate_rules = rules_target.get('candidate_conditions') or {}
    for plan in CANDIDATES:
        expected = candidate_rules.get(plan)
        if not expected:
            problems.append('rules.candidates.' + plan)
            continue
        candidate_condition = ((costs.get('candidates') or {}).get(plan) or {}).get('condition') or {}
        for field, path in CANDIDATE_FINGERPRINT_PATHS.items():
            if field not in expected:
                problems.append('rules.candidates.%s.%s' % (plan, field))
                continue
            actual = _get(candidate_condition, path)
            if _unknown(expected[field]) or _unknown(actual) or actual != expected[field]:
                problems.append('rules.candidates.%s.%s' % (plan, field))
    return problems


def _condition_problems(costs, target, rules):
    """Return the fields that are missing, UNKNOWN or incompatible.

    Only the two declared candidates and this batch's condition are checked.
    """
    condition = costs.get('condition') or {}
    rules_target = (rules or {}).get('target') or {}
    problems = _rules_target_problems(costs, rules_target)

    for field, path in SHARED_CONDITION_PATHS.items():
        expected = target.get(field, 'MISSING')
        if expected == 'MISSING':
            continue
        actual = _get(condition, path)
        if _unknown(expected) or _unknown(actual):
            problems.append(field)
        elif actual != expected:
            problems.append(field)

    stored = condition.get('fingerprint')
    if _unknown(stored) or stored != _self_fingerprint(condition):
        problems.append('condition_fingerprint_self')
    frozen = rules_target.get('condition_fingerprint')
    if frozen and stored != frozen:
        problems.append('condition_fingerprint')

    for section in SECTION_FINGERPRINTS:
        body = condition.get(section) or {}
        stored_section = body.get('fingerprint')
        if (_unknown(stored_section)
                or stored_section != _canonical_sha({k: v for k, v in body.items() if k != 'fingerprint'})):
            problems.append(section + '_fingerprint_self')

    # Necessary evidence must not be merely present as a hash: the recorded
    # consistency flags and numeric identities must also be usable.
    version = condition.get('version_consumption') or {}
    if version.get('consistent') is not True:
        problems.append('version_consumption.consistent')
    inputs = condition.get('input') or {}
    if _unknown(inputs.get('precision')):
        problems.append('input.precision')
    if not isinstance(inputs.get('snapshots'), list) or not inputs.get('snapshots'):
        problems.append('input.snapshots')
    checkpoint = inputs.get('checkpoint') or {}
    if _unknown(checkpoint.get('checksum_manifest_sha256')):
        problems.append('input.checkpoint.checksum_manifest_sha256')
    if _unknown(checkpoint.get('model_safetensors_sha256')):
        problems.append('input.checkpoint.model_safetensors_sha256')
    retention = condition.get('retention') or {}
    if _unknown(retention.get('capacity_B')) or _unknown(retention.get('bank_bytes')):
        problems.append('retention.capacity')
    if retention.get('all_job_actions_exact') is not True:
        problems.append('retention.all_job_actions_exact')
    observation = condition.get('observation') or {}
    if _unknown(observation.get('mode')):
        problems.append('observation.mode')
    hardware = condition.get('hardware') or {}
    if not isinstance(hardware.get('clock_limits'), dict) or not hardware.get('clock_limits'):
        problems.append('hardware.clock_limits')
    numeric = (condition.get('configuration') or {}).get('numeric') or {}
    if not numeric.get('work') or not numeric.get('expert_steps') or not numeric.get('expert_layers'):
        problems.append('configuration.numeric')

    candidate_rules = rules_target.get('candidate_conditions') or {}
    for plan in CANDIDATES:
        candidate = (costs.get('candidates') or {}).get(plan)
        if candidate is None:
            problems.append('candidates.' + plan)
            continue
        candidate_condition = candidate.get('condition') or {}
        expected = candidate_rules.get(plan) or {}
        for field, path in CANDIDATE_FINGERPRINT_PATHS.items():
            actual = _get(candidate_condition, path)
            if (_unknown(actual)
                    or _unknown(expected.get(field))
                    or actual != expected.get(field)):
                problems.append('candidates.%s.%s' % (plan, field))
        for section in CANDIDATE_SECTION_FINGERPRINTS:
            body = candidate_condition.get(section) or {}
            stored_section = body.get('fingerprint')
            if (_unknown(stored_section)
                    or stored_section != _canonical_sha({k: v for k, v in body.items() if k != 'fingerprint'})):
                problems.append('candidates.%s.%s_fingerprint_self' % (plan, section))
        stored_candidate = candidate_condition.get('fingerprint')
        if (_unknown(stored_candidate)
                or stored_candidate != _canonical_sha({k: v for k, v in candidate_condition.items() if k != 'fingerprint'})):
            problems.append('candidates.%s.condition_fingerprint_self' % plan)
        if candidate_condition.get('plan') != plan:
            problems.append('candidates.%s.plan' % plan)
        if candidate_condition.get('policy') != target.get('policy'):
            problems.append('candidates.%s.policy' % plan)
        obligations = candidate_condition.get('obligation_groups') or {}
        if obligations.get('consistent') is not True:
            problems.append('candidates.%s.obligation_groups.consistent' % plan)
        retention_observed = candidate_condition.get('retention_observed') or {}
        for field in ('records', 'payload_B', 'expert_outputs', 'refreshes'):
            if _unknown(retention_observed.get(field)):
                problems.append('candidates.%s.retention_observed.%s' % (plan, field))
    return sorted(set(problems))


def select(costs, target=None, rules=None):
    if target is None:
        caller_target = dict(TARGET)
    elif not isinstance(target, dict):
        return _unsupported('target must be an object', target)
    else:
        caller_target = dict(target)
    unknown = sorted(set(caller_target) - TARGET_KEYS)
    if unknown:
        return _unsupported('unrecognised target parameter(s): ' + ','.join(unknown),
                            caller_target, unrecognized=unknown)
    if not isinstance(rules, dict) or not rules.get('target'):
        return _insufficient('frozen RULES.json target/condition was not supplied; compatibility is unverified',
                             caller_target, ['rules'])
    effective = _condition_defaults(rules)
    effective.update(caller_target)

    if effective.get('cycles') != 8:
        return _unsupported('the frozen selector supports cycles=8 only', effective)
    if effective.get('phase_ms') != 15.0:
        return _unsupported('the frozen selector supports phase=+15 ms only', effective)
    if effective.get('policy') != POLICY:
        return _unsupported('the frozen selector supports the b2_boundary policy only', effective)
    if effective.get('pressure') not in SUPPORTED_PRESSURE:
        return _unsupported('unrecognised pressure condition: %r' % (effective.get('pressure'),), effective)
    period = effective.get('period_ms')
    if period not in SUPPORTED_PERIODS:
        return _unsupported('no measured two-vs-three split condition at this period', effective)
    if period == 180.0:
        return _insufficient(
            'B4 split evidence is fixed at P=240 ms; B5/B6/B7 are two_9_9-only and cannot supply three-plan 180 ms evidence.',
            effective, ['period_ms', 'three_prefix_9_9'], no_evidence_for_three=True)

    missing = [p for p in CANDIDATES if p not in (costs.get('candidates') or {})]
    if missing:
        return _insufficient('missing training costs for: ' + ','.join(missing),
                             effective, ['candidates.' + p for p in missing])

    problems = _condition_problems(costs, effective, rules)
    if problems:
        return _insufficient(
            'required condition evidence is missing or incompatible: ' + ','.join(problems),
            effective, problems, condition=costs.get('condition'),
            candidate_conditions={p: (costs['candidates'][p] or {}).get('condition') for p in CANDIDATES})

    results = {}
    for plan in CANDIDATES:
        results[plan] = {}
        for kind in ('typical', 'stress'):
            results[plan][kind] = evaluate(plan, scenario_for(costs, plan, kind), policy=POLICY,
                                           cycles=effective['cycles'], period=effective['period_ms'],
                                           phase=effective['phase_ms'],
                                           gap_ms=float(rules.get('model_constants', {}).get('gap_ms', 0.041)),
                                           publish_cost_ms=float(rules.get('model_constants', {}).get('publish_cost_ms', 0.012)))
    feasible = {p: all(results[p][k]['feasible'] for k in ('typical', 'stress')) for p in CANDIDATES}
    # worst-case margin by metric across scenarios
    agg = {}
    for p in CANDIDATES:
        vec = {}
        for key in ('min_cycle_margin_ms', 'min_expert_margin_ms', 'min_refresh_margin_ms'):
            vals = [results[p][k][key] for k in ('typical', 'stress')]
            vec[key] = None if any(v is None for v in vals) else min(vals)
        for key in ('max_refresh_response_ms', 'max_refresh_completion_offset_ms'):
            vals = [results[p][k][key] for k in ('typical', 'stress')]
            vec[key] = None if any(v is None for v in vals) else max(vals)
        agg[p] = vec
    serial = {}
    for plan, sc in (costs.get('serial_comparison') or {}).items():
        if not sc:
            continue
        d = copy.deepcopy(sc); d['kind'] = 'typical'
        serial[plan] = evaluate(plan, d, policy='serial_context', cycles=effective['cycles'],
                                period=effective['period_ms'], phase=effective['phase_ms'],
                                gap_ms=float(rules.get('model_constants', {}).get('gap_ms', 0.041)),
                                publish_cost_ms=float(rules.get('model_constants', {}).get('publish_cost_ms', 0.012)))
    candidate_status = {p: ('FEASIBLE' if feasible[p] else 'INFEASIBLE') for p in CANDIDATES}
    common = dict(target=effective, condition=costs.get('condition'),
                  candidate_conditions={p: costs['candidates'][p].get('condition') for p in CANDIDATES},
                  complete_evidence=True)
    if not any(feasible.values()):
        return dict(status='NO_EMPIRICALLY_FEASIBLE_PLAN', **common,
                    results=results, feasible=feasible, candidate_status=candidate_status,
                    margins=agg, serial_comparison=serial,
                    reason='all declared candidates have complete evidence and are infeasible: each has an incomplete obligation or a negative margin in at least one scenario')
    feasible_plans = [p for p in CANDIDATES if feasible[p]]
    nondominated = [p for p in feasible_plans
                    if not any(dominates(agg[q], agg[p]) for q in feasible_plans if q != p)]
    return dict(status='EMPIRICALLY_FEASIBLE', **common,
                results=results, feasible=feasible, candidate_status=candidate_status,
                margins=agg, serial_comparison=serial, feasible_plans=feasible_plans,
                infeasible_plans=[p for p in CANDIDATES if not feasible[p]],
                all_candidates_feasible=all(feasible.values()),
                nondominated=nondominated,
                selected=nondominated if len(nondominated) != 1 else nondominated[:1],
                reason='status means at least one declared candidate is feasible, not all; margins are worst over typical and stress; no weighted score is used',
                two_is_engineering_default='not proven performance-optimal; retain only as the lower-boundary-count default when evidence does not distinguish')
