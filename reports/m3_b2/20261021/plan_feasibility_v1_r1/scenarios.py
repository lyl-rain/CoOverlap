"""Declared scenarios (analysis-only). Every model output is model inference.

Recomputations from raw fields are labelled `rebuild`; counterfactuals are
labelled `model`. Nothing here is implemented in the production scheduler.
"""
import sys
from pathlib import Path

from plan_model import PLANS, THREE, TWO, simulate
from model_env import DEPLOYMENT  # noqa: F401

MEASURED = {
    ('two_9_9', 'serial_context'): dict(cycle_even=185.565, cycle_odd=75.141, publish=200.587, expert_even=185.565, vlm_even=65.300),
    ('two_9_9', 'b2_boundary'): dict(cycle_even=140.893, cycle_odd=75.426, publish=200.641, expert_even=140.893, vlm_even=65.286),
    ('three_prefix_9_9', 'serial_context'): dict(cycle_even=186.214, cycle_odd=75.292, publish=201.234, expert_even=186.214, vlm_even=65.818),
    ('three_prefix_9_9', 'b2_boundary'): dict(cycle_even=141.444, cycle_odd=75.459, publish=201.208, expert_even=91.772, vlm_even=141.444),
}


def b2_slack_arithmetic(tail_start=156.0, tail=44.6, expert=75.6, release=195.0, period=180.0):
    """The review's example; the review's original discussion used P=180 ms.

    Deadlines therefore are: odd cycle 195+180=375 ms, refresh 2*180=360 ms.
    Both variants still meet them; the harm is a later completion, and the
    refresh margin shrinks from 159.4 ms to 44.8 ms.
    """
    cycle_dl = release + period
    refresh_dl = 2 * period
    boundary = dict(tail_done=round(tail_start + tail, 3))
    boundary['expert_done'] = round(boundary['tail_done'] + expert, 3)
    boundary['expert_response'] = round(boundary['expert_done'] - release, 3)
    boundary['cycle_response'] = round(boundary['expert_done'] - release, 3)
    boundary['cycle_margin'] = round(cycle_dl - boundary['expert_done'], 3)
    boundary['refresh_margin'] = round(refresh_dl - boundary['tail_done'], 3)
    delayed = dict(expert_done=round(release + expert, 3))
    delayed['tail_done'] = round(delayed['expert_done'] + tail, 3)
    delayed['expert_response'] = round(delayed['expert_done'] - release, 3)
    delayed['cycle_response'] = round(delayed['tail_done'] - release, 3)
    delayed['cycle_margin'] = round(cycle_dl - delayed['tail_done'], 3)
    delayed['refresh_margin'] = round(refresh_dl - delayed['tail_done'], 3)
    return dict(period=period, cycle_deadline=cycle_dl, refresh_deadline=refresh_dl,
                boundary=boundary, delayed=delayed,
                expert_delta=round(delayed['expert_response'] - boundary['expert_response'], 3),
                cycle_delta=round(delayed['cycle_response'] - boundary['cycle_response'], 3),
                refresh_margin_delta=round(delayed['refresh_margin'] - boundary['refresh_margin'], 3))


def crossing_scenario(tail_ms=120.0):
    """Frozen release clock, only the tail lengthened so it covers release 255."""
    from plan_model import Plan
    slow = Plan('two_9_9_slow_tail', (TWO.durations[0], tail_ms), TWO.blocks, TWO.groups,
                TWO.valid_layers, TWO.kinds)
    return (simulate(slow, 'b2_boundary', cycles=8),
            simulate(slow, 'b2_boundary', cycles=8, tail_rule='delay_to_next_release'))


def ordering_scenarios():
    return dict(expert_first=simulate(TWO, 'b2_boundary', cycles=8),
                block_first=simulate(TWO, 'b2_boundary', cycles=8, block_priority=True),
                serial=simulate(TWO, 'serial_context', cycles=8))


def idle_scenario(idle_ms=50.0):
    return simulate(TWO, 'b2_boundary', cycles=8, extra_idle_before_context=idle_ms)


def slow_version_scenario(first_block_ms=600.0):
    from plan_model import Plan
    slow = Plan('two_9_9_slow_context', (first_block_ms, TWO.durations[1]), TWO.blocks,
                TWO.groups, TWO.valid_layers, TWO.kinds)
    return simulate(slow, 'b2_boundary', cycles=8)


def overrun_scenario(overrun_ms=200.0):
    return simulate(TWO, 'b2_boundary', cycles=8, expert_override=lambda j, d: overrun_ms)


def multi_expert_scenario():
    """A long Context keeps >=2 Experts released while a publication is pending."""
    from plan_model import Plan
    long_ctx = Plan('two_9_9_long_context', (140.0, 120.0), TWO.blocks, TWO.groups,
                    TWO.valid_layers, TWO.kinds)
    return simulate(long_ctx, 'serial_context', cycles=4, period=120.0, phase=10.0, expert=60.0)


def illegal_reclaim_scenario():
    """Expert 1's completion is never observed, so its reader still pins slot 0
    when refresh 1 needs it. The frozen state machine must refuse the reclaim."""
    return simulate(TWO, 'b2_boundary', cycles=8, hold_expert=1)


def termination_scenario():
    return simulate(TWO, 'b2_boundary', cycles=2, expert_ready=lambda j, published, now: False)


def lower_bound(plan, expert_ms, period=240.0, phase=15.0):
    """Conditional serial-sum bound (constant durations, frozen obligations)."""
    unit = sum(plan.durations[i] for i in plan.groups[0])
    return dict(unit_ms=round(unit, 3), even_cycle_ms=round(unit + expert_ms - phase, 3),
                odd_cycle_ms=round(expert_ms, 3),
                refresh_ms=round(unit + expert_ms + sum(plan.durations[i] for i in plan.groups[1]), 3))
