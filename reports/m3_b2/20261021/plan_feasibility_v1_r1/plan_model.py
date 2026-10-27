"""Analysis-only single-stream model driving the FROZEN VersionedKV lifecycle.

Not the executor, never imported by it. The version lifecycle (slots,
generations, PUBLISHED/RETIRED, reader reservation, safe reclaim, generation
checks) is NOT re-implemented: it is `m2_executor.VersionedKV` from the frozen r2
deployment package, driven by a discrete-event timing model. Block/Expert
durations are measured GPU Event envelopes; all instants are Host-visible ends
plus a measured inter-operation gap. The model cannot reproduce exact GPU
timestamps, is not a WCET argument, and its mean-envelope inputs are not a
strict lower bound on real work.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from model_env import DEPLOYMENT  # noqa: F401  (adds the frozen package to sys.path)
from m2_executor import DECODER, Snapshot, VersionedKV

S1 = Snapshot('S0', 'a'*64, 'b'*64, 'c'*64, 'd'*64, 'e'*64)
S2 = Snapshot('S1', 'f'*64, 'b'*64, 'c'*64, 'd'*64, 'e'*64)
SNAPSHOTS = (S1, S2)


@dataclass(frozen=True)
class Plan:
    name: str
    durations: tuple          # measured per-block total (ms), sequential order
    blocks: tuple             # legal work vocabulary per block (ints/labels)
    groups: tuple
    valid_layers: tuple
    kinds: tuple

    def __len__(self):
        return len(self.durations)


TWO = Plan('two_9_9', (79.423, 44.583),
           (tuple(range(9)), tuple(range(9, 18))), ((0,), (1,)), (9, 18), ('B1', 'B2'))
THREE = Plan('three_prefix_9_9', (30.324, 49.552, 44.580),
             (('language', 'vision27'), tuple(range(9)), tuple(range(9, 18))),
             ((0, 1), (2,)), (0, 9, 18), ('P', 'B1', 'B2'))
PLANS = {p.name: p for p in (TWO, THREE)}


class Fence:
    """CPU completion event: the only thing VersionedKV queries."""
    __slots__ = ('done',)

    def __init__(self):
        self.done = False

    def query(self):
        return self.done


@dataclass
class Result:
    plan: str
    policy: str
    status: str = 'DRAINED'
    note: str = ''
    cycles: list = field(default_factory=list)
    refreshes: list = field(default_factory=list)
    events: list = field(default_factory=list)
    journal: list = field(default_factory=list)
    deferred: list = field(default_factory=list)
    slot_refusals: list = field(default_factory=list)

    def counts(self):
        c = {'PASS': 0, 'FAIL': 0, 'UNCERTAIN': 0, 'INCOMPLETE': 0}
        for row in self.cycles:
            c[row['status']] += 1
        c['denominator'] = len(self.cycles)
        return c

    def summary(self):
        def mean(xs):
            v = [x for x in xs if x is not None]
            return round(sum(v)/len(v), 3) if v else None
        ev = [c for c in self.cycles if c['cycle'] % 2 == 0]
        od = [c for c in self.cycles if c['cycle'] % 2 == 1]
        return dict(plan=self.plan, policy=self.policy, status=self.status,
                    cycle_even=mean([c['response_ms'] for c in ev]),
                    cycle_odd=mean([c['response_ms'] for c in od]),
                    expert_even=mean([c['expert_response_ms'] for c in ev]),
                    expert_odd=mean([c['expert_response_ms'] for c in od]),
                    vlm_even=mean([c['vlm_response_ms'] for c in ev]),
                    publish=mean([r['ready_ms'] for r in self.refreshes]),
                    counts=self.counts(), note=self.note,
                    deferred=len(self.deferred), slot_refusals=len(self.slot_refusals))


def _domain(plan, cycles, period, phase, durations, expert):
    if not isinstance(plan, Plan) or len(plan.durations) < 2:
        raise ValueError('a declared plan with >=2 blocks is required')
    if not (isinstance(cycles, int) and cycles >= 2 and cycles % 2 == 0):
        raise ValueError('cycles must be a positive even count')
    if not period > 0 or not 0 <= phase < period:
        raise ValueError('phase must satisfy 0 <= phase < period (frozen manifest rule)')
    if any(d <= 0 for d in tuple(durations)+plan.durations+(expert,)):
        raise ValueError('all durations must be positive')


def simulate(plan: Plan, policy='b2_boundary', cycles=8, period=240.0, phase=15.0,
             expert=75.16, stage_first=0.563, stage_later=0.037, gap=0.041,
             publish_cost=0.012, tail_rule=None, expert_ready=None,
             extra_idle_before_context=0.0, expert_override=None, horizon=20_000.0,
             block_priority=False, scheduler='executor', hold_expert=None):
    """Replay one declared trajectory through the frozen ownership state machine.

    scheduler='executor' mirrors `run_segment`'s decision order: publication
    guard first, then any runnable Expert, then the FIFO Context. An illegal slot
    reclaim (readers still pinned) is REFUSED exactly as the executor does: the
    run stops, unfinished cycles stay INCOMPLETE, denominators are kept.
    """
    policy = policy[0] if isinstance(policy, (tuple, list)) else policy
    if policy not in ('serial_context', 'b2_boundary'):
        raise ValueError('unreviewed policy')
    durations = tuple(plan.durations)
    _domain(plan, cycles, period, phase, durations, expert)
    if tail_rule not in (None, 'delay_to_next_release'):
        raise ValueError('unreviewed tail rule')
    if scheduler not in ('executor',):
        raise ValueError('only the executor decision order is modelled')
    nblocks = len(durations)
    tail = nblocks - 1
    tail_group = [gi for gi, g in enumerate(plan.groups) if tail in g][0]
    res = Result(plan.name, policy)
    kv = VersionedKV(plan=plan)
    # The frozen executor bootstraps version 0 before the first replay window;
    # refresh q then allocates version q+1 on slot (q+1)%2.
    h0 = kv.begin(0, SNAPSHOTS[0])
    for b in range(nblocks):
        fence = Fence()
        kv.submit_block(h0, b, SNAPSHOTS[0], plan.blocks[b], fence)
        fence.done = True
        kv.poll_block(h0)
    kv.publish(h0)

    releases = [j * period + phase for j in range(cycles)]
    refresh_rel = [m * 2 * period for m in range(cycles // 2)]
    deadlines = [r + period for r in releases]
    refresh_dl = [r + 2 * period for r in refresh_rel]

    t, next_r = 0.0, 0
    dispatched, done = set(), {}
    units, blocks, pubs = {}, {}, {}
    active = None

    def live(v):
        h = kv.versions.get(v)
        if h is None:
            return None
        slot = kv.slots[h.slot]
        return slot if slot is not None and slot.handle == h else None

    def version_ready(j):
        slot = live(j // 2)
        return slot is not None and slot.phase == 'PUBLISHED'

    def runnable(j, now):
        if j in dispatched or releases[j] > now:
            return False
        if 'E' + str(j) in kv.readers:
            return True
        if expert_ready is not None:
            return bool(expert_ready(j, pub_state(), now))
        return version_ready(j)

    def pub_state():
        out = {}
        for v in kv.versions:
            slot = live(v)
            if slot is not None:
                out[v] = slot.phase
        return out

    def pick(now):
        for j in range(cycles):
            if runnable(j, now):
                return j
        return None

    def dispatch(j, now):
        nonlocal t
        if 'E' + str(j) not in kv.readers:
            v = j // 2
            if v not in kv.versions:
                raise RuntimeError('no version for Expert %d' % j)
            kv.bind('E' + str(j), SNAPSHOTS[0].noise_sha, version=v)
            if j + 1 < cycles and 'E' + str(j + 1) not in kv.readers:
                kv.bind('E' + str(j + 1), SNAPSHOTS[0].noise_sha, version=v)
        h = kv.readers['E' + str(j)].handle
        fence = Fence()
        kv.submit_expert('E' + str(j), h, DECODER, fence)
        dur = expert if expert_override is None else expert_override(j, expert)
        t = now + dur
        fence.done = True
        if hold_expert is None or j != hold_expert:
            kv.poll_expert('E' + str(j))
        # hold_expert: the work is submitted but its completion is not observed,
        # so the reader token stays SUBMITTED (analysis-only knob).
        dispatched.add(j)
        done[j] = t
        res.events.append(dict(kind='Expert', id=j, version=h.version, start=round(now, 3), end=round(t, 3)))

    def run_block(q, b, now):
        nonlocal t
        h = active['h']
        fence = Fence()
        kv.submit_block(h, b, active['snap'], plan.blocks[b], fence)
        t = now + durations[b]
        fence.done = True
        kv.poll_block(h)
        blocks[q, b] = t
        res.events.append(dict(kind='block', refresh=q, block=b, start=round(now, 3), end=round(t, 3)))
        for gi, group in enumerate(plan.groups):
            if b in group and all((q, x) in blocks for x in group):
                units[q, gi] = max(blocks[q, x] for x in group)
        t += gap

    def do_publish(q, now):
        nonlocal t
        h = active['h']
        kv.publish(h)
        after = now + gap + publish_cost
        pubs[q] = after
        units[q, tail_group] = max(units.get((q, tail_group), after), after)
        t = after
        res.events.append(dict(kind='publish', refresh=q, version=h.version, end=round(after, 3)))

    def guard_ok(q):
        retired = h_version(q) - 1
        return (2 * retired) in dispatched

    def h_version(q):
        return q + 1

    while len(pubs) < cycles // 2 or len(done) < cycles:
        if t > horizon:
            res.status = 'HORIZON'
            break
        now = t
        if active is not None and active['awaiting']:
            q = active['q']
            if guard_ok(q):
                do_publish(q, now)
                active = None
                continue
            j = pick(now)
            if j is not None:
                dispatch(j, now)
                continue
            need = 2 * (h_version(q) - 1)
            if need < cycles and releases[need] > now:
                t = releases[need]
                continue
            res.status = 'NO_RUNNABLE_DEPENDENCY'
            res.note = 'publication guard needs an Expert that cannot run'
            break
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
                upcoming = [releases[j] for j in range(cycles)
                            if j not in dispatched and releases[j] > now]
                if upcoming and now < upcoming[0] < now + durations[b]:
                    jj = pick(upcoming[0])
                    if jj is not None:
                        dispatch(jj, upcoming[0])
                        continue
                    t = upcoming[0]
                    continue
            run_block(q, b, now)
            active['index'] += 1
            if active['index'] == nblocks:
                if guard_ok(q):
                    do_publish(q, t)
                    active = None
                else:
                    active['awaiting'] = True
                    res.deferred.append(dict(refresh=q, waiting_for=2 * (h_version(q) - 1)))
            continue
        j = pick(now)
        if j is not None:
            dispatch(j, now)
            continue
        if next_r < len(refresh_rel) and refresh_rel[next_r] <= now:
            q = next_r
            slot = (q + 1) % 2
            owned = kv.slots[slot]
            if owned is not None:
                try:
                    kv.reclaim(owned.handle)
                except RuntimeError as exc:
                    res.status = 'ILLEGAL_RECLAIM'
                    res.note = 'refresh %d refused slot %d: %s' % (q, slot, exc)
                    res.slot_refusals.append(dict(refresh=q, slot=slot, version=owned.handle.version,
                                                  readers=sorted(owned.readers), reason=str(exc)))
                    break
            h = kv.begin(slot, SNAPSHOTS[q % 2])
            if h.version != q + 1:
                res.status = 'VERSION_MISMATCH'
                res.note = 'allocated version %d for refresh %d' % (h.version, q)
                break
            start = max(now, refresh_rel[q] + extra_idle_before_context)
            t = start + (stage_first if q == 0 else stage_later)
            res.events.append(dict(kind='stage', refresh=q, end=round(t, 3)))
            active = dict(q=q, index=0, awaiting=False, h=h, snap=SNAPSHOTS[q % 2])
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
        e, u = done.get(j), units.get((m, b))
        pair = max(e, u) if (e is not None and u is not None) else None
        status = 'INCOMPLETE' if pair is None else ('PASS' if pair <= dl else 'FAIL')
        res.cycles.append(dict(cycle=j, status=status, release_ms=round(rel, 3), deadline_ms=round(dl, 3),
                               expert_response_ms=round(e - rel, 3) if e is not None else None,
                               vlm_response_ms=round(max(0.0, u - rel), 3) if u is not None else None,
                               response_ms=round(pair - rel, 3) if pair is not None else None))
    for m in range(cycles // 2):
        rel = refresh_rel[m]
        p = pubs.get(m)
        status = 'INCOMPLETE' if p is None else ('PASS' if p <= refresh_dl[m] else 'FAIL')
        res.refreshes.append(dict(id=m, status=status, ready_ms=round(p - rel, 3) if p is not None else None,
                                  deadline_ms=round(refresh_dl[m] - rel, 3),
                                  k=max(1, int(math.ceil((p - rel) / period))) if p is not None else None))
    res.journal = list(kv.journal)
    return res
