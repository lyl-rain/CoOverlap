"""Shared state-transition core for the action-level legal-schedule search.

Verbatim copy of the frozen analysis scheduler (as used by the v2 selector's
``cps2/model.py``) plus two optional knobs:
  * ``extra_ms(key)``  per-operation duration delta (existing behaviour);
  * ``policy_fn(state)`` an action hook returning 'E', 'C', 'I', 'STOP' or None.
With both hooks unused the code path is the frozen default.  The lifecycle is the
frozen ``m2_executor.VersionedKV``; no KV state machine is re-implemented.
"""
from __future__ import annotations

import math

from plan_model import (DECODER, Fence, Result, SNAPSHOTS, VersionedKV, _domain)


def simulate(plan: Plan, policy='b2_boundary', cycles=8, period=240.0, phase=15.0,
             expert=75.16, stage_first=0.563, stage_later=0.037, gap=0.041,
             publish_cost=0.012, tail_rule=None, expert_ready=None,
             extra_idle_before_context=0.0, expert_override=None, horizon=20_000.0,
             block_priority=False, scheduler='executor', hold_expert=None,
             extra_ms=None, policy_fn=None):
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
        if extra_ms is not None:
            dur += extra_ms(('Expert', j))
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
        t = now + durations[b] + (extra_ms(('block', q, b)) if extra_ms is not None else 0.0)
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
        if policy_fn is not None and not (active is not None and active['awaiting']):
            ready = [j for j in range(cycles) if runnable(j, now)]
            future = [releases[j] for j in range(cycles)
                      if j not in dispatched and releases[j] > now]
            future += [refresh_rel[q] for q in range(next_r, len(refresh_rel))
                       if refresh_rel[q] > now]
            legal = []
            if ready:
                legal.append('E')
            if ((active is not None and active['index'] < nblocks)
                    or (active is None and next_r < len(refresh_rel)
                        and refresh_rel[next_r] <= now)):
                legal.append('C')
            if future:
                legal.append('I')
            state = dict(now=now, runnable=ready, legal=legal,
                         active=None if active is None else dict(q=active['q'], index=active['index'],
                                                                 awaiting=active['awaiting']),
                         next_refresh=next_r, released_refreshes=[q for q in range(next_r)
                                                                  if refresh_rel[q] <= now],
                         dispatched=sorted(dispatched), done=sorted(done),
                         pubs=dict(pubs), next_event=min(future) if future else None,
                         versions={v: (h.version,
                                        next((s.phase for s in kv.slots
                                              if s is not None and s.handle == h), None))
                                   for v, h in kv.versions.items()},
                         readers={k: h.handle.version for k, h in kv.readers.items()})
            action = policy_fn(state)
            if action == 'STOP':
                res.status = 'STOPPED_FOR_SEARCH'
                res.note = repr(state)
                res.search_state = state
                break
            if action == 'E':
                j = pick(now)
                if j is None:
                    res.status = 'ILLEGAL_ACTION'
                    res.note = 'E without runnable Expert'
                    break
                dispatch(j, now)
                continue
            if action == 'C':
                if active is not None:
                    q, b = active['q'], active['index']
                    if b >= nblocks:
                        res.status = 'ILLEGAL_ACTION'
                        res.note = 'C past the last block'
                        break
                    run_block(q, b, now)
                    active['index'] += 1
                    if active['index'] == nblocks:
                        if guard_ok(q):
                            do_publish(q, t)
                            active = None
                        else:
                            active['awaiting'] = True
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
                            res.slot_refusals.append(dict(refresh=q, slot=slot,
                                                          version=owned.handle.version,
                                                          readers=sorted(owned.readers),
                                                          reason=str(exc)))
                            break
                    h = kv.begin(slot, SNAPSHOTS[q % 2])
                    if h.version != q + 1:
                        res.status = 'VERSION_MISMATCH'
                        res.note = 'allocated version %d for refresh %d' % (h.version, q)
                        break
                    start = max(now, refresh_rel[q] + extra_idle_before_context)
                    t = start + (stage_first if q == 0 else stage_later) + \
                        (extra_ms(('stage', q)) if extra_ms is not None else 0.0)
                    res.events.append(dict(kind='stage', refresh=q, end=round(t, 3)))
                    active = dict(q=q, index=0, awaiting=False, h=h, snap=SNAPSHOTS[q % 2])
                    next_r += 1
                    continue
                res.status = 'ILLEGAL_ACTION'
                res.note = 'C without Context or released refresh'
                break
            if action == 'I':
                if not future:
                    res.status = 'ILLEGAL_ACTION'
                    res.note = 'I without a future release'
                    break
                t = min(future)
                continue
            if action is not None:
                res.status = 'ILLEGAL_ACTION'
                res.note = 'unknown action %r' % (action,)
                break
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
            t = start + (stage_first if q == 0 else stage_later) + (extra_ms(('stage', q)) if extra_ms is not None else 0.0)
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
