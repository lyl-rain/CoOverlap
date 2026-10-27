"""Declared scenarios for the feasibility analysis (analysis-only, no GPU).

Every scenario is either (a) a recomputation of the executed batch from its raw
fields, or (b) a model counterfactual explicitly labelled as such. Nothing here
is implemented in the production scheduler.
"""
from plan_model import TWO, THREE, PLANS, simulate

MEASURED = {  # mean of the 16 even / 16 odd cycles per cell (offline/CELLS.json)
    ('two_9_9', 'serial_context'): dict(cycle_even=185.565, cycle_odd=75.141, expert_even=185.565, vlm_even=65.300, publish=200.587),
    ('two_9_9', 'b2_boundary'): dict(cycle_even=140.893, cycle_odd=75.426, expert_even=140.893, vlm_even=65.286, publish=200.641),
    ('three_prefix_9_9', 'serial_context'): dict(cycle_even=186.214, cycle_odd=75.292, expert_even=186.214, vlm_even=65.818, publish=201.234),
    ('three_prefix_9_9', 'b2_boundary'): dict(cycle_even=141.444, cycle_odd=75.459, expert_even=91.772, vlm_even=141.444, publish=201.208),
}


def b2_slack_arithmetic(tail_start=156.0, tail=44.6, expert=75.6, release=195.0):
    """The review's synthetic case, evaluated by plain arithmetic."""
    boundary = dict(tail_done=tail_start + tail, expert_done=tail_start + tail + expert)
    boundary['expert_response'] = boundary['expert_done'] - release
    boundary['cycle_response'] = boundary['expert_done'] - release
    delayed = dict(tail_done=release + expert + tail, expert_done=release + expert)
    delayed['expert_response'] = delayed['expert_done'] - release
    delayed['cycle_response'] = delayed['tail_done'] - release
    return dict(boundary=boundary, delayed=delayed,
                expert_delta=round(delayed['expert_response'] - boundary['expert_response'], 3),
                cycle_delta=round(delayed['cycle_response'] - boundary['cycle_response'], 3))


def crossing_scenario(tail_ms=120.0):
    """Force the tail to cross the next release WITHOUT moving the release clock.

    The release clock (P=240, +15 ms phase) is kept frozen; only the tail
    duration is lengthened so the tail window of refresh 0 (starting ~156 ms)
    contains the E1 release at 255 ms. This is a constructed counterfactual used
    to expose the ordering trade-off; it is NOT a proposed configuration.
    """
    from plan_model import Plan
    slow = Plan('two_9_9_slow_tail', (TWO.blocks[0], tail_ms), TWO.groups, TWO.kinds)
    base = simulate(slow, 'b2_boundary', cycles=8)
    slack = simulate(slow, 'b2_boundary', cycles=8, tail_rule='delay_to_next_release')
    return base, slack


def ordering_scenarios():
    return dict(
        expert_first=simulate(TWO, 'b2_boundary', cycles=8),
        block_first=simulate(TWO, 'b2_boundary', cycles=8, block_priority=True),
        serial=simulate(TWO, 'serial_context', cycles=8),
    )


def idle_scenario(idle_ms=50.0):
    return simulate(TWO, 'b2_boundary', cycles=8, extra_idle_before_context=idle_ms)


def slow_version_scenario(first_block_ms=600.0):
    """Refresh 0 publishes after E2's release, so E2 must wait for version 1."""
    from plan_model import Plan
    slow = Plan('two_9_9_slow_context', (first_block_ms, TWO.blocks[1]), TWO.groups, TWO.kinds)
    return simulate(slow, 'b2_boundary', cycles=8)


def overrun_scenario(overrun_ms=200.0):
    return simulate(TWO, 'b2_boundary', cycles=8, expert_override=lambda j, d: overrun_ms)


def termination_scenario():
    """A version that never becomes ready: no runnable dependency remains."""
    return simulate(TWO, 'b2_boundary', cycles=2, expert_ready=lambda j, published, now: False)


def lower_bound(plan, cell_expert, period=240.0, phase=15.0):
    """Conditional serial-sum bound: even cycle must complete its VLM unit and one Expert."""
    unit = sum(plan.blocks[i] for i in plan.groups[0])
    even = unit + cell_expert - phase
    odd = cell_expert
    refresh = unit + cell_expert + sum(plan.blocks[i] for i in plan.groups[1])
    return dict(unit_ms=round(unit, 3), even_cycle_ms=round(even, 3), odd_cycle_ms=round(odd, 3),
                refresh_ms=round(refresh, 3))
