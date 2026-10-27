"""Analysis-only timing model for the frozen M3 single-stream plan (no GPU).

This module is NOT the executor and is never imported by it. It replays the
declared release clock, legal block boundaries, the fixed-version Expert
trajectory, FIFO Context, the publication guard and safe reclaim, using only
measured per-operation envelopes as durations. It exists to
  (a) recompute the 64 cycles / 32 refreshes of the executed batch and compare
      them with the measured statistics, and
  (b) run declared counterfactual orderings (e.g. delaying a tail block) that
      are NOT implemented in the production scheduler.

Time is in milliseconds from the refresh t0 (the release clock origin).
Host and GPU quantities are kept separate: `*_envelope` inputs come from CUDA
Event envelopes (which include submission gaps), while completion instants in
this model are the Host-visible end of an operation plus an inter-operation
gap. The model never claims to reproduce exact GPU timestamps.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Plan:
    name: str
    blocks: tuple            # sequential block durations (ms), order = key order
    groups: tuple            # ((0,1),(2,)) or ((0,),(1,))
    kinds: tuple             # mathematical names, for reporting only


TWO = Plan('two_9_9', (79.423, 44.583), ((0,), (1,)), ('B1', 'B2'))
THREE = Plan('three_prefix_9_9', (30.324, 49.552, 44.580), ((0, 1), (2,)),
             ('P', 'B1', 'B2'))
PLANS = {p.name: p for p in (TWO, THREE)}


@dataclass
class Result:
    plan: str
    policy: str
    cycles: list = field(default_factory=list)
    refreshes: list = field(default_factory=list)
    events: list = field(default_factory=list)
    status: str = 'DRAINED'
    note: str = ''

    def cycle_counts(self):
        counts = {'PASS': 0, 'FAIL': 0, 'UNCERTAIN': 0, 'INCOMPLETE': 0}
        for c in self.cycles:
            counts[c['status']] += 1
        counts['denominator'] = len(self.cycles)
        return counts

    def summary(self):
        ev = [c for c in self.cycles if c['cycle'] % 2 == 0]
        od = [c for c in self.cycles if c['cycle'] % 2 == 1]
        def mean(xs):
            vals = [x for x in xs if x is not None]
            return round(sum(vals) / len(vals), 3) if vals else None
        return dict(plan=self.plan, policy=self.policy, status=self.status,
                    cycle_even=mean([c['response_ms'] for c in ev]),
                    cycle_odd=mean([c['response_ms'] for c in od]),
                    expert_even=mean([c['expert_response_ms'] for c in ev]),
                    expert_odd=mean([c['expert_response_ms'] for c in od]),
                    vlm_even=mean([c['vlm_response_ms'] for c in ev]),
                    vlm_odd=mean([c['vlm_response_ms'] for c in od]),
                    publish=mean([r['ready_ms'] for r in self.refreshes]),
                    counts=self.cycle_counts(), note=self.note)


def simulate(plan: Plan, policies='b2_boundary', cycles=8, period=240.0, phase=15.0,
             expert=75.16, stage_first=0.563, stage_later=0.037, gap=0.041,
             publish_cost=0.012, tail_rule=None, expert_ready=None,
             extra_idle_before_context=0.0, expert_override=None, horizon=5_000.0,
             block_priority=False):
    """One declared trajectory. `tail_rule` is an analysis-only ordering knob.

    tail_rule='delay_to_next_release': if the tail block (the last block of the
    refresh, which is the NEXT cycle's obligation group) would overlap the next
    Expert release, hold it until that release, serve the Expert first, then the
    tail. This is the b2_slack proposal; it is not implemented in the executor.
    """
    import math
    policy = policies if isinstance(policies, str) else policies[0]
    if policy not in ('serial_context', 'b2_boundary'):
        raise ValueError('unreviewed policy')
    nblocks = len(plan.blocks)
    tail = nblocks - 1
    tail_group = [gi for gi, g in enumerate(plan.groups) if tail in g][0]
    res = Result(plan.name, policy)

    releases = [j * period + phase for j in range(cycles)]
    refresh_rel = [m * 2 * period for m in range(cycles // 2)]
    deadlines = [r + period for r in releases]
    refresh_dl = [r + 2 * period for r in refresh_rel]

    t = 0.0
    published = {0: 0.0}
    dispatched, done_expert = set(), {}
    units, blocks, pubs = {}, {}, {}
    active = None
    next_r = 0
    guard_waits = 0

    def version_published(j):
        v = j // 2
        return v in published

    def can_run(j, now):
        if j in dispatched or releases[j] > now:
            return False
        if expert_ready is not None:
            return bool(expert_ready(j, published, now))
        return version_published(j)

    def pick(now):
        ready = [j for j in range(cycles) if can_run(j, now)]
        return ready[0] if ready else None

    def dispatch(j, now):
        nonlocal t
        dur = expert if expert_override is None else expert_override(j, expert)
        start = now
        t = start + dur
        dispatched.add(j)
        done_expert[j] = t
        res.events.append(dict(kind='Expert', id=j, start=round(start, 3), end=round(t, 3)))

    def run_block(q, b, now):
        nonlocal t
        t = now + plan.blocks[b]
        blocks[q, b] = t
        res.events.append(dict(kind='block', refresh=q, block=b, start=round(now, 3), end=round(t, 3)))
        for gi, group in enumerate(plan.groups):
            if b in group and all((q, x) in blocks for x in group):
                units[q, gi] = max(blocks[q, x] for x in group)
        t += gap

    def publish(q, now):
        nonlocal t
        v = q + 1
        after = now + gap + publish_cost
        pubs[q] = after
        published[v] = after
        units[q, tail_group] = max(units.get((q, tail_group), after), after)
        t = after
        res.events.append(dict(kind='publish', refresh=q, version=v, end=round(after, 3)))

    def guard_ok(retired):
        return (2 * retired) in dispatched

    while len(pubs) < cycles // 2 or len(done_expert) < cycles:
        if t > horizon:
            res.status = 'HORIZON'
            break
        now = t
        if active is not None and active['awaiting']:
            q = active['q']
            if guard_ok(q):
                publish(q, now)
                active = None
                continue
            j0 = 2 * q
            if j0 < cycles and can_run(j0, now):
                dispatch(j0, now)
                continue
            if j0 >= cycles:
                publish(q, now)
                active = None
                continue
            if releases[j0] <= now:
                res.status = 'NO_RUNNABLE_DEPENDENCY'
                res.note = 'publication guard needs an Expert that cannot run'
                break
            t = releases[j0]
            guard_waits += 1
            continue
        if active is not None:
            q, b = active['q'], active['index']
            j = pick(now)
            if j is not None and policy != 'serial_context' and not block_priority:
                dispatch(j, now)
                continue
            if block_priority and j is not None and policy != 'serial_context' and b < tail:
                run_block(q, b, now)
                active['index'] += 1
                continue
            if tail_rule == 'delay_to_next_release' and b == tail:
                upcoming = [releases[j] for j in range(cycles) if j not in dispatched and releases[j] > now]
                if upcoming:
                    nxt = upcoming[0]
                    if now < nxt < now + plan.blocks[b]:
                        jj = pick(nxt)
                        if jj is not None:
                            dispatch(jj, nxt)
                            continue
                        t = nxt
                        continue
            run_block(q, b, now)
            active['index'] += 1
            if active['index'] == nblocks:
                retired = (q + 1) - 1
                if guard_ok(retired):
                    publish(q, t)
                    active = None
                else:
                    active['awaiting'] = True
                    res.events.append(dict(kind='deferred', refresh=q, waiting_for=2 * retired))
            continue
        j = pick(now)
        if j is not None:
            dispatch(j, now)
            continue
        if next_r < len(refresh_rel) and refresh_rel[next_r] <= now:
            q = next_r
            if q >= 2 and (q - 2) not in pubs:
                res.status = 'BACKLOG'
                res.note = 'refresh %d cannot start: slot still owned by refresh %d' % (q, q - 2)
                break
            start = max(now, refresh_rel[q] + extra_idle_before_context)
            t = start + (stage_first if q == 0 else stage_later)
            res.events.append(dict(kind='stage', refresh=q, end=round(t, 3)))
            active = dict(q=q, index=0, awaiting=False)
            next_r += 1
            continue
        future = [releases[j] for j in range(cycles) if j not in dispatched]
        future += [refresh_rel[q] for q in range(next_r, len(refresh_rel))]
        future = [x for x in future if x > now]
        if not future:
            res.status = 'NO_RUNNABLE_DEPENDENCY'
            res.note = 'no future arrival and no runnable dependency'
            break
        t = min(future)

    for j in range(cycles):
        rel, dl = releases[j], deadlines[j]
        m, b = j // 2, j % 2
        e = done_expert.get(j)
        u = units.get((m, b))
        pair = max(e, u) if (e is not None and u is not None) else None
        status = 'INCOMPLETE' if pair is None else ('PASS' if pair <= dl else 'FAIL')
        res.cycles.append(dict(cycle=j, status=status, release_ms=round(rel, 3),
            deadline_ms=round(dl, 3),
            expert_response_ms=round(e - rel, 3) if e is not None else None,
            vlm_response_ms=round(max(0.0, u - rel), 3) if u is not None else None,
            response_ms=round(pair - rel, 3) if pair is not None else None))
    for m in range(cycles // 2):
        rel = refresh_rel[m]
        p = pubs.get(m)
        status = 'INCOMPLETE' if p is None else ('PASS' if p <= refresh_dl[m] else 'FAIL')
        res.refreshes.append(dict(id=m, status=status,
            ready_ms=round(p - rel, 3) if p is not None else None,
            deadline_ms=round(refresh_dl[m] - rel, 3),
            k=max(1, int(math.ceil((p - rel) / period))) if p is not None else None))
    if res.status == 'DRAINED' and (len(pubs) < cycles // 2 or len(done_expert) < cycles):
        res.status = 'INCOMPLETE'
    return res


def measured_constants(path):
    return json.load(open(path))
