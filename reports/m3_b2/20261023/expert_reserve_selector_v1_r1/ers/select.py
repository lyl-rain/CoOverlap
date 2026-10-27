"""The selection rule as a pure function over candidate evidence.

``select`` never reads a measured trajectory: it only sees the per-candidate
scenario summaries.  The retrospective actual-trace evaluation lives in
``ablation`` and is deliberately not fed back into this function, so the rule
cannot be tuned by the outcome it is being checked against.
"""
from __future__ import annotations

import common
import rules


def summarize_candidate(plan, scenario_results, evidence_ok=True, missing=None,
                        lifecycle_ok=True):
    """Collapse the two scenario results of one candidate into MC / ME / MR."""
    scenario_results = scenario_results or {}
    per = {}
    for kind in common.SCENARIOS:
        s = scenario_results.get(kind)
        per[kind] = None if s is None else dict(
            complete=s['complete'], model_status=s['model_status'],
            MC=s['min_cycle_margin_ms'], ME=s['min_expert_margin_ms'],
            MR=s['min_refresh_margin_ms'], counts=s['counts'],
            deferred=s.get('deferred', 0), refusals=s.get('refusals', 0))
    values = [v for v in per.values() if v is not None]
    complete = bool(values) and all(v['complete'] and v['model_status'] == 'DRAINED'
                                    and v['deferred'] == 0 and v['refusals'] == 0
                                    for v in values)
    metrics_ok = bool(values) and all(
        v['MC'] is not None and v['ME'] is not None and v['MR'] is not None for v in values)
    out = dict(plan=plan, blocks=common.BLOCKS[plan], scenarios=per,
               evidence_ok=bool(evidence_ok and metrics_ok and len(values) == 2),
               missing=list(missing or []), complete=complete,
               lifecycle_ok=bool(lifecycle_ok))
    if metrics_ok and len(values) == len(common.SCENARIOS):
        out['MC'] = min(v['MC'] for v in values)
        out['ME'] = min(v['ME'] for v in values)
        out['MR'] = min(v['MR'] for v in values)
        # A candidate whose version/lifecycle state machine failed cannot be
        # called feasible, even if the timing margins happen to be positive.
        out['feasible'] = bool(complete and lifecycle_ok and out['MC'] >= 0
                               and out['ME'] >= 0 and out['MR'] >= 0)
    else:
        out.update(MC=None, ME=None, MR=None, feasible=False)
    out['reserve_ok'] = bool(out['feasible'] and out['ME'] is not None
                             and out['ME'] >= rules.RE_MS)
    out['lifecycle_ok'] = bool(lifecycle_ok)
    return out


def select(candidates, reserve_ms=None, order=None):
    """Apply the frozen rule to a mapping of candidate-id -> summary."""
    reserve = rules.RE_MS if reserve_ms is None else float(reserve_ms)
    order = list(common.CANDIDATES if order is None else order)
    present = [c for c in order if c in candidates]
    unknown = sorted(set(candidates) - set(order))
    trace = []
    out = dict(rule=common.RULE_ID, reserve_ms=reserve, order=order,
               considered=list(present), status=None, selected=None, reason='',
               evidence={}, trace=trace)

    if unknown:
        out['status'] = 'UNSUPPORTED_INPUT'
        out['reason'] = 'candidate outside the declared scope: %s' % ', '.join(unknown)
        return out

    # This module declares a comparison of BOTH candidates.  A decision made from
    # a subset is not the declared rule, so a missing candidate is missing
    # evidence -- never silently "the only candidate is selected".
    missing_candidates = [c for c in order if c not in candidates]
    if missing_candidates:
        out['status'] = 'INSUFFICIENT_EVIDENCE'
        out['reason'] = 'declared candidate evidence missing: %s' % ', '.join(
            missing_candidates)
        out['missing'] = list(missing_candidates)
        return out

    missing_evidence = [c for c in present if not candidates[c].get('evidence_ok')]
    if not present:
        out['status'] = 'INSUFFICIENT_EVIDENCE'
        out['reason'] = 'no candidate evidence supplied'
        return out
    if missing_evidence:
        out['status'] = 'INSUFFICIENT_EVIDENCE'
        out['reason'] = 'incomplete candidate evidence: %s' % ', '.join(
            '%s(%s)' % (c, ','.join(candidates[c].get('missing') or ['unknown']))
            for c in missing_evidence)
        out['missing'] = sorted(missing_evidence)
        return out

    trace.append(dict(step='preconditions', passed=[c for c in present
                                                    if candidates[c]['feasible']],
                      failed=[c for c in present if not candidates[c]['feasible']]))
    feasible = [c for c in present if candidates[c]['feasible']]
    if not feasible:
        out['status'] = 'NO_EMPIRICALLY_FEASIBLE_PLAN'
        out['reason'] = 'all candidates fail complete obligations or official deadlines'
        out['evidence'] = {c: _evidence(candidates[c], reserve) for c in present}
        return out

    def meets(c):
        # the reserve must be evaluated against THIS decision's RE, never against a
        # summary precomputed at another reserve value
        me = candidates[c]['ME']
        return me is not None and me >= reserve

    reserved = [c for c in feasible if meets(c)]
    trace.append(dict(step='reserve', reserve_ms=reserve, passed=reserved,
                      failed=[c for c in feasible if c not in reserved]))
    if not reserved:
        out['status'] = 'RESERVE_UNSATISFIED'
        out['reason'] = ('official-deadline feasible candidates exist but none meets '
                         'ME >= %g ms' % reserve)
        out['evidence'] = {c: _evidence(candidates[c], reserve) for c in present}
        return out

    def key(c):
        cand = candidates[c]
        return (cand['blocks'], -cand['MC'], order.index(c))

    ranking = sorted(reserved, key=key)
    trace.append(dict(step='choose', ranking=[dict(candidate=c,
                                                   blocks=candidates[c]['blocks'],
                                                   MC=candidates[c]['MC'],
                                                   ME=candidates[c]['ME'])
                                              for c in ranking]))
    out['status'] = 'SELECTED'
    out['selected'] = ranking[0]
    out['reason'] = 'fewest blocks among reserve-satisfying candidates (%s)' % (
        'tie broken by MC' if len(ranking) > 1
        and candidates[ranking[0]]['blocks'] == candidates[ranking[1]]['blocks'] else 'unique')
    out['evidence'] = {c: _evidence(candidates[c], reserve) for c in present}
    return out


def _evidence(cand, reserve=None):
    reserve_ok = cand['reserve_ok'] if reserve is None else bool(
        cand['feasible'] and cand['ME'] is not None and cand['ME'] >= reserve)
    return dict(plan=cand['plan'], blocks=cand['blocks'], MC=cand['MC'], ME=cand['ME'],
                MR=cand['MR'], feasible=cand['feasible'], reserve_ok=reserve_ok,
                reserve_ms=reserve,
                complete=cand['complete'], evidence_ok=cand['evidence_ok'],
                scenarios={k: None if v is None else dict(MC=v['MC'], ME=v['ME'],
                                                          MR=v['MR'], complete=v['complete'])
                           for k, v in cand['scenarios'].items()})


def fixed(candidate_id, candidates, reserve_ms=None):
    """A fixed plan, evaluated under the same reserve indicator as the rule.

    ``fixed`` is not a selection: it reports whether that plan meets the official
    deadlines and whether its Expert margin meets the reserve.
    """
    reserve = rules.RE_MS if reserve_ms is None else float(reserve_ms)
    cand = candidates.get(candidate_id)
    if cand is None or not cand['evidence_ok']:
        return dict(rule=common.RULE_ID, scheme='fixed', reserve_ms=reserve,
                    status='INSUFFICIENT_EVIDENCE', selected=candidate_id,
                    feasible=False, reserve_ok=False,
                    reason='fixed candidate evidence incomplete', evidence={})
    return dict(rule=common.RULE_ID, scheme='fixed', reserve_ms=reserve,
                status='FIXED_PLAN', selected=candidate_id,
                feasible=bool(cand['feasible']),
                reserve_ok=bool(cand['feasible'] and cand['ME'] is not None
                                and cand['ME'] >= reserve),
                reason='fixed plan; official %s, reserve %s' % (
                    'feasible' if cand['feasible'] else 'not feasible',
                    'met' if cand['reserve_ok'] else 'not met'),
                evidence={candidate_id: _evidence(cand, reserve)})
