"""The frozen selection rule: reserve-constrained, fewest blocks.

The rule is fixed for this round and is not tuned by any result:

1. drop candidates whose complete obligations or official deadlines are not met;
2. drop candidates whose minimum Expert margin is below the reserve RE;
3. among the rest take the fewest blocks;
4. tie -> larger minimum cycle margin MC;
5. tie -> the pre-declared stable candidate order.

RE = 10 ms is an **engineering parameter introduced on 2026-10-23, after B8**, from
B8's own evidence.  It is not in the task book, not a WCET, not a validated safety
bound, and not a claim that 10 ms of interference can be absorbed.  The official
release times, deadlines and violation definitions are unchanged.
"""
from __future__ import annotations

import common

RE_MS = 10.0

STATUSES = ('SELECTED', 'RESERVE_UNSATISFIED', 'NO_EMPIRICALLY_FEASIBLE_PLAN',
            'INSUFFICIENT_EVIDENCE', 'UNSUPPORTED_INPUT')

RESERVE_IDENTITY = dict(
    value_ms=RE_MS,
    proposed_on='2026-10-23',
    proposed_after='B8 split x budget challenge (2026-10-22)',
    is_task_book_requirement=False,
    is_wcet=False,
    is_validated_safety_bound=False,
    implies_interference_tolerance=False,
    official_deadline_unchanged=True,
    adjustable_within_round=False,
    note='reserve shortfall is an auxiliary indicator, never an official deadline miss',
)


def rules_document():
    return dict(
        schema='m3_expert_reserve_rules_v1',
        id=common.RULE_ID,
        status=common.RULE_STATUS,
        status_note='the reserve value was chosen after B8 was observed; this is a '
                    'retrospective design, not a pre-registered rule',
        reserve=dict(RESERVE_IDENTITY),
        candidates=[dict(id=p, plan=p, policy='b2_boundary', blocks=common.BLOCKS[p])
                    for p in common.CANDIDATES],
        scenarios=list(common.SCENARIOS),
        cost_source=dict(
            kind='B8 own measured operations, per condition',
            extraction='GPU_total_envelope_ms per operation key, per cell',
            retrospective=True,
            not_pooled=['B4 source costs', '180 ms and 140 ms cells',
                        'two-block and three-block cells'],
            not_layer_divided=True,
            host_event_not_summed=True,
        ),
        metrics=dict(
            MC='min cycle deadline margin over all scenarios and all cycles',
            ME='min Expert deadline margin over all scenarios and all Experts',
            MR='min refresh deadline margin over all scenarios and all refreshes',
            margin_definition='deadline - completion (upper completion bound for the '
                              'recorded traces; model completion for the scenarios)',
        ),
        preconditions=['complete declared work', 'no missing block',
                       'no version or lifecycle error', 'MC >= 0', 'ME >= 0', 'MR >= 0'],
        selection_order=[
            'exclude candidates that do not satisfy complete obligations or official deadlines',
            'exclude candidates with ME < RE',
            'choose the fewest blocks',
            'tie: larger MC',
            'tie: pre-declared stable candidate order (%s)' % ', '.join(common.CANDIDATES),
        ],
        statuses=list(STATUSES),
        status_meaning=dict(
            SELECTED='a candidate satisfying the reserve exists',
            RESERVE_UNSATISFIED='official-deadline feasible candidates exist but none meets RE',
            NO_EMPIRICALLY_FEASIBLE_PLAN='evidence is complete and no candidate meets the '
                                         'complete obligations or official deadlines',
            INSUFFICIENT_EVIDENCE='required conditions or candidate evidence are incomplete',
            UNSUPPORTED_INPUT='the input is outside this module declared scope',
        ),
        scope=dict(periods_ms=list(common.PERIODS_MS), plans=list(common.CANDIDATES),
                   policies=['b2_boundary']),
        non_goals=['no online waiting', 'no in-block preemption', 'no latest-published',
                   'no obligation reassignment', 'no budget change',
                   'no per-result tuning of RE'],
    )


def validate_rules(doc):
    if doc.get('schema') != 'm3_expert_reserve_rules_v1':
        raise ValueError('unexpected rules schema')
    if doc['reserve']['value_ms'] != RE_MS:
        raise ValueError('reserve value changed')
    if doc['reserve']['is_task_book_requirement'] or doc['reserve']['is_wcet']:
        raise ValueError('reserve identity must stay an engineering parameter')
    if doc['scope']['periods_ms'] != list(common.PERIODS_MS):
        raise ValueError('scope periods changed')
    if doc['scope']['plans'] != list(common.CANDIDATES):
        raise ValueError('scope plans changed')
    return doc

