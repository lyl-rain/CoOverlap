"""Trace audit: two independent margins at every legal decision boundary.

For each recorded segment the frozen executor's decision loop is reconstructed
from the raw records (``decisions``, ``blocks``, ``experts``, ``published``,
``journal``, ``operations``, ``progress``).  For each decision it reports

  A. deadline margin            deadline - completion            (Expert / cycle / refresh)
  B. release-boundary distance  next Expert release - decision Host time

and which operation the executor chose when both an Expert and a Context action
were pending.  The same reconstruction is applied to the frozen pre-run
prediction, so actual and predicted choices can be compared boundary by boundary.

The decision instant is the Host time at which the loop chose, i.e. *after* the
real completion confirmation.  The pure GPU Event end is kept only to expose the
confirmation cost; it is never substituted for the decision instant.

Job keys follow the raw-record operation naming: blocks are ``R{q}/B1``,
``R{q}/B2``, ``R{q}/B3`` and a block's declared kind is reported separately
(``P``/``B1``/``B2`` for the three-block plan).  The tail block is therefore B2
for ``two_9_9`` and **B3** for ``three_prefix_9_9``.
"""
from __future__ import annotations

import bisect

import costs

PROBE_EPS_MS = 1e-9

STATE_NOT_RELEASED = 'NOT_RELEASED'
STATE_READY = 'RELEASED_READY'
STATE_VERSION_WAIT = 'RELEASED_VERSION_NOT_READY'
STATE_NONE = 'NO_UNDISPATCHED_EXPERT'
STATE_COMPLETED = 'COMPLETED'


# --------------------------------------------------------------------------- views

def _rel(ns, t0):
    return None if ns is None else round((ns - t0) / 1e6, 6)


def actual_view(segment):
    """Decision sequence and outcome tables of one recorded segment."""
    t0 = segment['t0_ns']
    manifest = segment['manifest']
    period_ms = segment['period_ns'] / 1e6
    plan = segment['plan']
    keys = costs.BLOCK_KEY[plan]
    kinds = costs.BLOCK_KIND[plan]
    ops = {op['key']: op for op in segment.get('operations') or []}
    blocks = segment.get('blocks') or {}
    experts = segment.get('experts') or {}
    published = {int(k): v for k, v in (segment.get('published') or {}).items()}

    events = []
    idle = False
    for d in segment['decisions']:
        if d['kind'] == 'idle_until_arrival':
            idle = True
            continue
        rec = dict(kind=d['kind'], decide_ns=d['host_ns'], decision_ms=_rel(d['host_ns'], t0),
                   refresh=None, block=None, block_kind=None, id=None, job=None, op=None,
                   version=None, after_idle=idle)
        idle = False
        if d['kind'] == 'stage':
            q = d['id']
            rec.update(refresh=q, id=q, job='R%d/stage' % q,
                       op=ops.get('R%d/stage' % q), version=q + 1)
        elif d['kind'] == 'Context':
            q, b = d['id'], d['block']
            rec.update(refresh=q, block=b, block_kind=kinds[b], id=q,
                       job='R%d/%s' % (q, keys[b]),
                       op=ops.get('R%d/B%d' % (q, b + 1)), version=q + 1)
        else:
            j = d['id']
            rec.update(id=j, job='E%d' % j, op=ops.get('E%d' % j))
        events.append(rec)

    block_end = {}
    for key, v in blocks.items():
        q, b = _parse_block_key(key)
        block_end[(q, b)] = None if v is None else _rel(v[1], t0)
    for rec in events:
        if rec['kind'] == 'stage':
            op = rec['op']
            rec['end_ms'] = None if op is None else _rel(op['host_finalization_upper_ns'], t0)
        elif rec['kind'] == 'Context':
            rec['end_ms'] = block_end.get((rec['refresh'], rec['block']))
        else:
            v = experts.get(str(rec['id']))
            rec['end_ms'] = None if v is None else _rel(v[1], t0)
        op = rec['op']
        rec['gpu_lower_ms'] = None if op is None else _rel(op.get('gpu_completion_lower_host_ns'), t0)
        rec['gpu_upper_ms'] = None if op is None else _rel(op.get('gpu_completion_upper_host_ns'), t0)

    version = {}
    for row in segment['journal']:
        if row and row[0] == 'bind' and row[1] not in version:
            version[row[1]] = row[2]
    token_ms = {}
    for rec in events:
        if rec['kind'] != 'Expert':
            continue
        token_ms.setdefault(rec['id'], rec['decision_ms'])
        if rec['id'] + 1 < manifest['cycles']:
            token_ms.setdefault(rec['id'] + 1, rec['decision_ms'])
        rec['version'] = version.get(rec['job'])

    from validate import actual_jobs
    return dict(side='actual', segment_id=segment['segment_id'], cell=segment['cell'],
                plan=plan, period_ms=period_ms, pass_=segment.get('pass_'),
                cycles=manifest['cycles'], releases_ms=_releases(manifest),
                deadlines_ms=_deadlines(manifest), events=events,
                jobs=actual_jobs(segment), block_end=block_end,
                publish_ms={q: _rel(v[1], t0) for q, v in published.items()},
                token_ms=token_ms, version=version, progress=_progress(segment, t0),
                decision_origin='Host clock after real completion confirmation',
                note='the decision instant includes the completion query and scheduler cost')


def _parse_block_key(key):
    """Raw records store the block interval map as the string '(q, b)'."""
    if isinstance(key, tuple):
        return key
    text = str(key).strip().strip('()')
    q, b = text.split(',')
    return int(q), int(b)


def _releases(manifest):
    return {e['id']: round(e['release_ns'] / 1e6, 6) for e in manifest['experts']}


def _deadlines(manifest):
    return {e['id']: round(e['deadline_ns'] / 1e6, 6) for e in manifest['experts']}


def _progress(segment, t0):
    return [dict(host_ms=_rel(p['host_ns'], t0), ready=list(p.get('ready_experts') or []),
                 version_wait=list(p.get('version_wait_experts') or []),
                 active_context=p.get('active_context'),
                 completed_blocks=p.get('completed_blocks'),
                 context_backlog=p.get('context_backlog'))
            for p in segment.get('progress') or []]


def predicted_view(cell, kind, scenario):
    """Decision sequence and outcome tables of the frozen pre-run prediction."""
    period_ms = cell['period_ms']
    plan = cell['plan']
    keys = costs.BLOCK_KEY[plan]
    kinds = costs.BLOCK_KIND[plan]
    events = []
    block_end = {}
    for b in scenario['blocks']:
        block_end[(b['refresh'], b['block'])] = b['completion_ms']
        if b['start_ms'] is None:
            continue
        events.append(dict(kind='Context', refresh=b['refresh'], block=b['block'],
                           block_kind=kinds[b['block']], id=b['refresh'],
                           job='R%d/%s' % (b['refresh'], keys[b['block']]),
                           decision_ms=b['start_ms'], end_ms=b['completion_ms'],
                           gpu_lower_ms=b['completion_ms'], gpu_upper_ms=b['completion_ms'],
                           op=None, version=b['refresh'] + 1))
    for e in scenario['experts']:
        if e['dispatch_ms'] is None:
            continue
        events.append(dict(kind='Expert', refresh=None, block=None, block_kind=None,
                           id=int(e['job_id'][1:]), job=e['job_id'],
                           decision_ms=e['dispatch_ms'], end_ms=e['completion_ms'],
                           gpu_lower_ms=e['completion_ms'], gpu_upper_ms=e['completion_ms'],
                           op=None, version=e['version']))
    events.sort(key=lambda e: (e['decision_ms'], 0 if e['kind'] == 'Context' else 1, e['job']))
    # the model stages a refresh at its release and starts block 0 after the
    # stage cost; the stage is not a separate predicted job, so it is rebuilt here
    by_refresh = {}
    for e in events:
        if e['kind'] == 'Context' and e['block'] == 0:
            by_refresh[e['refresh']] = e
    stage_events = []
    prev_end = 0.0
    for q in sorted(by_refresh):
        block0 = by_refresh[q]
        release = q * 2 * period_ms
        start = max(release, prev_end)
        stage_events.append(dict(kind='stage', refresh=q, block=None, block_kind=None, id=q,
                                 job='R%d/stage' % q, decision_ms=round(start, 6),
                                 end_ms=block0['decision_ms'], gpu_lower_ms=None,
                                 gpu_upper_ms=None, op=None, version=q + 1))
        prev_end = block0['end_ms']
    events.extend(stage_events)
    events.sort(key=lambda e: (e['decision_ms'], _rank(e), e['job']))
    prev_end = None
    for e in events:
        e['after_idle'] = bool(prev_end is not None and e['decision_ms'] > prev_end + 1e-9)
        prev_end = e['end_ms'] if e['end_ms'] is not None else e['decision_ms']
    token_ms = {}
    for rec in events:
        if rec['kind'] != 'Expert':
            continue
        token_ms.setdefault(rec['id'], rec['decision_ms'])
        token_ms.setdefault(rec['id'] + 1, rec['decision_ms'])
    return dict(side='predicted_%s' % kind, segment_id=None, cell=cell['cell'], plan=plan,
                period_ms=period_ms, pass_=None, cycles=len(scenario['cycles']),
                releases_ms={int(x['job_id'][1:]): x['release_ms'] for x in scenario['experts']},
                deadlines_ms={int(x['job_id'][1:]): x['deadline_ms'] for x in scenario['experts']},
                events=events, jobs=_predicted_jobs(scenario), block_end=block_end,
                publish_ms={x['id']: x['completion_offset_ms'] for x in scenario['refreshes']},
                token_ms=token_ms,
                version={int(e['job_id'][1:]): e['version'] for e in scenario['experts']
                         if e['dispatch_ms'] is not None},
                progress=[],
                decision_origin='model event time (GPU end + declared gap; no Host confirmation term)',
                note='the model decision time is not a measured Host instant')


def _rank(e):
    # a Context/stage op that ends exactly when another starts is the earlier one
    return {'stage': 0, 'Context': 0, 'Expert': 1}[e['kind']]


def _predicted_jobs(scenario):
    jobs = {}
    for x in scenario['experts']:
        jobs[('Expert', x['job_id'])] = x
    for x in scenario['blocks']:
        jobs[('ContextBlock', x['job_id'])] = x
    for x in scenario['cycles']:
        jobs[('Cycle', 'cycle%d' % x['cycle'])] = dict(
            release_ms=x['release_ms'], deadline_ms=x['deadline_ms'],
            completion_ms=x['completion_ms'], margin_ms=x['margin_ms'], status=x['status'])
    for x in scenario['refreshes']:
        jobs[('Refresh', 'refresh%d' % x['id'])] = dict(
            release_ms=x['release_ms'], deadline_ms=x['deadline_ms'],
            completion_ms=x['completion_offset_ms'], margin_ms=x['margin_ms'],
            response_ms=x['response_ms'], status=x['status'])
    return jobs


# ----------------------------------------------------------------------- boundary

def boundaries(view):
    """One row per legal decision, with both margins and the chosen operation."""
    nblocks = len(costs.BLOCK_KEY[view['plan']])
    keys = costs.BLOCK_KEY[view['plan']]
    dispatched = set()
    active = None            # (refresh, next block index) while a build runs
    started = None           # last refresh whose stage decision happened
    done = {}
    out = []
    for i, ev in enumerate(view['events']):
        now = ev['decision_ms']
        prev = view['events'][i - 1] if i else None
        if ev['kind'] == 'stage':
            started = ev['refresh']
            active = (ev['refresh'], 0)
            action = ('stage', ev['refresh'], None)
        elif ev['kind'] == 'Context':
            started = ev['refresh']
            action = ('Context', ev['refresh'], ev['block'])
        else:
            action = ('Expert', ev['id'], None)

        released = [j for j in range(view['cycles'])
                    if view['releases_ms'][j] <= now and j not in dispatched]
        ready = [j for j in released if _ready(view, j, now)]
        version_wait = [j for j in released if j not in ready]
        und = [j for j in range(view['cycles']) if j not in dispatched]
        next_expert = min(und) if und else None

        pending_context = None
        if active is not None:
            q, b = active
            pending_context = ('Context', q, b)
        else:
            q = _pending_stage(view, started, now)
            if q is not None:
                pending_context = ('stage', q, None)

        if action[0] == 'Expert':
            expert_of_interest = action[1]
            competing = pending_context
        else:
            expert_of_interest = next_expert
            competing = None if next_expert is None else ('Expert', next_expert, None)
        if (competing is not None and competing[0] == 'Expert'
                and competing[1] == expert_of_interest and action[0] == 'Expert'):
            competing = None

        distance = None if expert_of_interest is None else round(
            view['releases_ms'][expert_of_interest] - now, 6)
        if distance is None:
            side_iv = None
        elif prev is None or prev.get('gpu_lower_ms') is None:
            side_iv = _side(distance)
        else:
            rel = view['releases_ms'][expert_of_interest]
            side_iv = _side_interval(rel - prev['gpu_lower_ms'], rel - prev['gpu_upper_ms'])

        if ev['kind'] == 'Context':
            done[ev['refresh']] = max(done.get(ev['refresh'], 0), ev['block'])
        refresh_tag = ev['refresh'] if ev['refresh'] is not None else started
        evidence = None if expert_of_interest is None else _ready_evidence(
            view, expert_of_interest, now)
        row = dict(
            side=view['side'], segment_id=view['segment_id'], cell=view['cell'],
            plan=view['plan'], period_ms=view['period_ms'], pass_=view['pass_'],
            refresh=refresh_tag,
            boundary_key=('start' if prev is None else 'after:%s' % prev['job']),
            prev_op_kind=None if prev is None else prev['kind'],
            prev_op_job=None if prev is None else prev['job'],
            prev_expert_state=(None if prev is None or prev['kind'] != 'Expert'
                               else STATE_COMPLETED),
            blocks_done_in_refresh=done.get(refresh_tag, 0),
            blocks_done_total=sum(done.values()), experts_done=len(dispatched),
            decision_ms=round(now, 6), decision_origin=view['decision_origin'],
            after_idle_arrival=bool(ev.get('after_idle')),
            prev_gpu_lower_ms=None if prev is None else prev.get('gpu_lower_ms'),
            prev_gpu_upper_ms=None if prev is None else prev.get('gpu_upper_ms'),
            prev_completion_ms=None if prev is None else prev.get('end_ms'),
            confirm_overhead_ms=(None if ev.get('after_idle') or prev is None
                                 or prev.get('gpu_upper_ms') is None
                                 else round(now - prev['gpu_upper_ms'], 6)),
            decision_minus_prev_completion_ms=(None if prev is None or prev.get('end_ms') is None
                                               else round(now - prev['end_ms'], 6)),
            released_ready_experts=list(ready),
            released_version_wait_experts=list(version_wait),
            next_expert_id=expert_of_interest,
            next_expert_release_ms=(None if expert_of_interest is None
                                    else view['releases_ms'][expert_of_interest]),
            next_expert_deadline_ms=(None if expert_of_interest is None
                                     else view['deadlines_ms'][expert_of_interest]),
            next_expert_state=_state(expert_of_interest, ready, version_wait),
            next_expert_version_ready=(None if expert_of_interest is None
                                       else evidence is not None),
            next_expert_version_evidence=evidence,
            distance_decision_ms=distance,
            distance_completion_upper_ms=(None if expert_of_interest is None or prev is None
                                          or prev.get('gpu_upper_ms') is None else round(
                                              view['releases_ms'][expert_of_interest]
                                              - prev['gpu_upper_ms'], 6)),
            distance_completion_lower_ms=(None if expert_of_interest is None or prev is None
                                          or prev.get('gpu_lower_ms') is None else round(
                                              view['releases_ms'][expert_of_interest]
                                              - prev['gpu_lower_ms'], 6)),
            release_side_interval=side_iv,
            release_side_at_decision=_side(distance),
            release_interval_uncertain=(side_iv == 'UNCERTAIN_INTERVAL'),
            release_crossed_by_decision=(None if distance is None else distance <= PROBE_EPS_MS),
            chosen_kind=action[0], chosen_job=ev['job'], chosen_version=ev.get('version'),
            chosen_block_index=ev.get('block'), chosen_block_kind=ev.get('block_kind'),
            competing_job=(None if competing is None else
                           ('E%d' % competing[1] if competing[0] == 'Expert' else
                            'R%d/%s' % (competing[1], keys[competing[2]]))),
            competing_kind=None if competing is None else competing[0],
            competition=competing is not None,
            release_during_chosen_op=False, release_offset_into_op_ms=None,
        )
        if (expert_of_interest is not None and ev['kind'] != 'Expert'
                and ev.get('end_ms') is not None):
            rel = view['releases_ms'][expert_of_interest]
            if now < rel < ev['end_ms']:
                row['release_during_chosen_op'] = True
                row['release_offset_into_op_ms'] = round(rel - now, 6)
        row.update(_outcomes(view, expert_of_interest, pending_context, keys, refresh_tag))
        row['recorded_ready_experts'] = None
        row['recorded_version_wait_experts'] = None
        row['ready_matches_record'] = None
        out.append(row)
        if action[0] == 'Expert':
            dispatched.add(action[1])
        elif action[0] == 'Context':
            if action[2] + 1 >= nblocks:
                active = None
            else:
                active = (action[1], action[2] + 1)
        else:
            active = (action[1], 0)
    return out


def _pending_stage(view, started, now):
    if started is None:
        return 0 if now >= 0 else None
    q = started + 1
    if q >= view['cycles'] // 2:
        return None
    if q * 2 * view['period_ms'] <= now + PROBE_EPS_MS:
        return q
    return None


def _state(j, ready, version_wait):
    if j is None:
        return STATE_NONE
    if j in ready:
        return STATE_READY
    if j in version_wait:
        return STATE_VERSION_WAIT
    return STATE_NOT_RELEASED


def _side(distance):
    if distance is None:
        return None
    if distance > PROBE_EPS_MS:
        return 'BEFORE_RELEASE'
    if distance < -PROBE_EPS_MS:
        return 'AFTER_RELEASE'
    return 'AT_RELEASE'


def _side_interval(lo, hi):
    """Side of the release relative to the previous op's completion interval.

    ``lo``/``hi`` are release - completion_lower / release - completion_upper and
    hi <= lo.  A release inside the interval resolves to UNCERTAIN: the record
    cannot say whether it happened before or after the true completion.
    """
    if lo < -PROBE_EPS_MS:
        return 'AFTER_RELEASE'
    if hi > PROBE_EPS_MS:
        return 'BEFORE_RELEASE'
    return 'UNCERTAIN_INTERVAL'


def _published_ms(view, version):
    if version <= 0:
        return float('-inf')
    return view['publish_ms'].get(version - 1)


def _ready_evidence(view, j, now):
    """Why an Expert is (or is not) runnable: ownership token or published version.

    The executor accepts either an existing reader token or a currently published
    version; a release alone is never enough.  ``None`` means "released but the
    version is not ready" and is reported as RELEASED_VERSION_NOT_READY.
    """
    token = view['token_ms'].get(j)
    if token is not None and token <= now:
        return 'ownership_token'
    published = _published_ms(view, j // 2)
    if published is not None and published <= now:
        return 'published_version'
    return None


def _ready(view, j, now):
    return _ready_evidence(view, j, now) is not None


def _outcomes(view, expert_id, pending_context, keys, refresh_tag):
    """Deadline margins of the jobs a flip at this boundary would move."""
    out = dict(expert_job=None, expert_completion_ms=None, expert_deadline_ms=None,
               expert_margin_ms=None, expert_status=None,
               cycle_id=None, cycle_completion_ms=None, cycle_deadline_ms=None,
               cycle_margin_ms=None, cycle_status=None,
               unit_job=None, unit_block=None, unit_blocks=None,
               unit_completion_ms=None, unit_deadline_ms=None,
               unit_margin_ms=None, unit_status=None,
               refresh_publication_ms=None, refresh_deadline_ms=None,
               refresh_margin_ms=None, refresh_status=None)
    if expert_id is not None:
        key = ('Expert', 'E%d' % expert_id)
        j = view['jobs'].get(key)
        if j is not None:
            out.update(expert_job=key[1], expert_completion_ms=j['completion_ms'],
                       expert_deadline_ms=j['deadline_ms'], expert_margin_ms=j['margin_ms'],
                       expert_status=j.get('status'))
        c = view['jobs'].get(('Cycle', 'cycle%d' % expert_id))
        if c is not None:
            out.update(cycle_id=expert_id, cycle_completion_ms=c['completion_ms'],
                       cycle_deadline_ms=c['deadline_ms'], cycle_margin_ms=c['margin_ms'],
                       cycle_status=c.get('status'))
    if pending_context is not None and pending_context[0] == 'Context':
        q, b = pending_context[1], pending_context[2]
        group = _group_of(view['plan'], b)
        group_blocks = _group_blocks(view['plan'], group)
        ends = []
        complete = True
        for gb in group_blocks:
            end = view['block_end'].get((q, gb))
            if end is None:
                complete = False
                break
            ends.append(end)
        cycle = 2 * q + group
        c = view['jobs'].get(('Cycle', 'cycle%d' % cycle))
        deadline = None if c is None else c['deadline_ms']
        completion = None
        if complete:
            completion = max(ends)
            if group == _tail_group(view['plan']):
                pub = view['publish_ms'].get(q)
                if pub is not None:
                    completion = max(completion, pub)
        out.update(unit_job='R%d/group%d' % (q, group), unit_block=keys[b],
                   unit_blocks=[keys[x] for x in group_blocks],
                   unit_completion_ms=None if completion is None else round(completion, 6),
                   unit_deadline_ms=deadline,
                   unit_margin_ms=(None if completion is None or deadline is None
                                   else round(deadline - completion, 6)),
                   unit_status=(None if completion is None or deadline is None
                                else ('PASS' if completion <= deadline else 'FAIL')))
    if refresh_tag is not None:
        r = view['jobs'].get(('Refresh', 'refresh%d' % refresh_tag))
        if r is not None:
            out.update(refresh_publication_ms=r['completion_ms'],
                       refresh_deadline_ms=r['deadline_ms'],
                       refresh_margin_ms=r['margin_ms'], refresh_status=r.get('status'))
    return out


def _groups(plan):
    return ((0,), (1,)) if plan == 'two_9_9' else ((0, 1), (2,))


def _group_of(plan, block):
    for gi, g in enumerate(_groups(plan)):
        if block in g:
            return gi
    raise ValueError('block outside plan: %r' % (block,))


def _group_blocks(plan, group):
    return _groups(plan)[group]


def _tail_group(plan):
    return len(_groups(plan)) - 1


# ------------------------------------------------------------------ cross-checking

def attach_record(view):
    """Attach the executor's own ready/version-wait observation where it exists."""
    rows = boundaries(view)
    prog = view.get('progress') or []
    if not prog:
        return rows
    keys = [p['host_ms'] for p in prog]
    for row in rows:
        idx = bisect.bisect_right(keys, row['decision_ms']) - 1
        if idx < 0:
            continue
        p = prog[idx]
        row['recorded_ready_experts'] = p['ready']
        row['recorded_version_wait_experts'] = p['version_wait']
        row['recorded_active_context'] = p['active_context']
        row['recorded_completed_blocks'] = p['completed_blocks']
        row['recorded_context_backlog'] = p['context_backlog']
        row['ready_matches_record'] = (
            sorted(p['ready']) == sorted(row['released_ready_experts'])
            and sorted(p['version_wait']) == sorted(row['released_version_wait_experts']))
    return rows


def actual_order(segment):
    """Dispatch order of one segment in raw-record job naming."""
    rows = []
    for d in segment.get('decisions') or []:
        if d['kind'] == 'Expert':
            rows.append((d['host_ns'], 'Expert', 'E%d' % d['id']))
        elif d['kind'] == 'Context':
            rows.append((d['host_ns'], 'ContextBlock', 'R%d/B%d' % (d['id'], d['block'] + 1)))
    rows.sort(key=lambda x: (x[0], x[1], x[2]))
    return [x[2] for x in rows]
