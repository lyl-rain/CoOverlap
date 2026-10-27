"""M3 candidate policy, CPU-safe; frozen M2 work/ownership remain unchanged."""
from m2_executor import replay_manifest, replay_stats
from m2_clean_core import retention_layout

PROTOCOL = 'm3_b2_boundary_profile_v1'
CYCLES = 4
PERIOD_NS = 240_000_000
ORDER = ('serial_context', 'b2_boundary')
BINDING = ('planned v=floor(Expert.id/2); at first dispatch of even Expert, '
           'bind that Expert and reserve its odd partner to the SAME published v; '
           'reservation is ownership only, never early execution; unavailable v waits')


def protocol():
    return dict(id=PROTOCOL, approval_required='new explicit M3 GPU and hardware approval',
                order=list(ORDER), manifest=manifest(), binding=BINDING,
                candidates=[dict(id='C0_context_decision', policy=ORDER[0],
                                 decision_boundaries=['Context_complete'],
                                 note='same B1/B2 calls, fences and retention; no Expert decision between them'),
                            dict(id='C1_existing_9_9', policy=ORDER[1],
                                 decision_boundaries=['stage_complete', 'encoder_8_complete', 'Context_complete'])],
                queue_depth=1, context_fifo=True, full_drain=True,
                retention=retention_layout(CYCLES),
                explicit_work=dict(warmup_C=2, reference_C=2, reference_E=2,
                    D1_C=1, D1_E=1, old_reader_gate_C=2, old_reader_gate_E=1,
                    interrupt_gate_C=2, interrupt_gate_E=1, segment_bootstrap_C=2,
                    timed_C=4, timed_E=8, total_C=15, total_E=13,
                    encoder_layers=270, decoder_layers=2340, vision_layers=405,
                    autotune_requests=36, autotune_separate=True),
                limits=dict(model_processes=1, timeout_s=180, grace_s=10,
                            internal_s=170, scope_count=1, scope_max_s=420, retries=0),
                numerical_admission='D1 same-process byte exact; cross-process report only',
                no_performance_or_k_min_claim=True)


def manifest(period_ns=PERIOD_NS, cycles=CYCLES):
    conf = replay_manifest(period_ns, cycles)
    conf.update(schema=PROTOCOL, binding=BINDING)
    return conf



def finalize_segment_stats(record, conf, t0, plan, clock):
    """Host-side statistics after a segment's execution/window has ended."""
    record['journal'] = record.get('journal', [])
    record['statistics'] = replay_stats(conf, record['experts'], record['units'],
                                         record['published'], t0)
    record['statistics']['quantile_method'] = ('diagnostic n=%d cycles only; no reliable tail/k_min'
                                                % len(conf['experts']))
    record['statistics']['block_plan'] = plan.id
    record['statistics']['blocks_completed'] = len(record.get('blocks', {}))
    record['statistics']['units_are_declared_groups'] = [list(g) for g in plan.groups]
    record['remaining_Expert_ids'] = [e['id'] for e in conf['experts']
                                      if e['id'] not in record['experts']]
    record['remaining_Context_ids'] = [r['id'] for r in conf['refreshes']
                                       if r['id'] not in record['published']]
    return record['statistics']


def run_segment(manager, snapshots, policy, backend, record, clock, conf=None, expect=None,
                window=None):
    """One outstanding fenced operation; decisions occur AFTER its real completion.

    Blocked-on-version Experts retain original arrivals/deadlines; FIFO Context
    is allowed to produce their dependency. No latest-version substitution.
    This is shared by the serial control, B2 and every declared block plan; an
    alternative reviewed protocol passes its own frozen ``expect`` manifest.
    The plan comes from the manager/backend, so publish state and block work can
    never disagree with the ownership state machine.
    """
    if policy not in ORDER:
        raise ValueError('unreviewed policy')
    conf = manifest() if conf is None else conf
    reference = manifest(conf['period_ns'], conf['cycles']) if expect is None else expect
    if conf != reference:
        raise ValueError('changed fixed arrivals/work/binding')
    # The segment records the protocol declared by THIS batch's frozen manifest
    # (never an inherited module constant), and refuses a mismatched manifest.
    session_protocol = conf.get('schema')
    declared_protocol = (expect or {}).get('id') or (expect or {}).get('schema')
    if not session_protocol:
        raise ValueError('manifest carries no protocol identity')
    if declared_protocol and session_protocol != declared_protocol:
        raise ValueError('manifest protocol %r != frozen protocol %r'
                         % (session_protocol, declared_protocol))
    plan = manager.plan
    if getattr(backend, 'plan', plan) is not plan:
        raise ValueError('backend/manager block plan mismatch')
    nblocks = len(plan)
    es, units, pubs, blocks = {}, {}, {}, {}
    record.update(protocol=session_protocol, mode=policy, manifest=conf, experts=es,
                  units=units, blocks=blocks, published=pubs, status='NOT_STARTED',
                  decisions=[], arrivals=[], progress=[], t0_ns=None,
                  block_plan=plan.summary())
    backend.prepare(manager, conf, record)
    backend.bootstrap(manager, 'bootstrap')
    record['initial_state'] = backend.ready(manager)
    if window is None:
        t0 = clock() + 10_000_000
    else:
        # The shared driver asks the coordinator for the ONE t0 after all
        # preparation/report work; it never takes a second time base.
        try:
            t0 = window.open(clock(), conf)
        except BaseException:
            try:
                record['interference'] = window.abort('window_open_failed')
            except BaseException:
                record['interference_abort_error'] = True
            record['status'] = 'INCOMPLETE_WINDOW'
            raise
        record['window_plan'] = window.plan.as_dict()
        record['window_t0_ns'] = t0
    record.update(t0_ns=t0, status='INCOMPLETE')
    next_e = next_r = 0
    released_e, released_r = [], []
    active = None
    if window is not None:
        try:
            window.await_start()
        except BaseException:
            try:
                record['interference'] = window.abort('window_start_failed')
            except BaseException:
                record['interference_abort_error'] = True
            record['status'] = 'INCOMPLETE_WINDOW'
            raise
        record['window_start_observed_ns'] = window.start_observed_ns
        record['window_start_lateness_ns'] = window.start_lateness_ns
    record['replay_start_ns'] = clock()
    backend.enter_window()
    try:
        while len(es) < len(conf['experts']) or len(pubs) < len(conf['refreshes']):
            now = clock()
            while next_e < len(conf['experts']) and t0 + conf['experts'][next_e]['release_ns'] <= now:
                e = conf['experts'][next_e]; released_e.append(e['id']); next_e += 1
                record['arrivals'].append(dict(kind='Expert', id=e['id'],
                    release_ns=t0+e['release_ns'], observed_host_ns=now))
            while next_r < len(conf['refreshes']) and t0 + conf['refreshes'][next_r]['release_ns'] <= now:
                r = conf['refreshes'][next_r]; released_r.append(r['id']); next_r += 1
                record['arrivals'].append(dict(kind='Context', id=r['id'],
                    release_ns=t0+r['release_ns'], observed_host_ns=now))
            ready = []
            blocked = []
            for j in released_e:
                if j in es: continue
                token = manager.readers.get('E'+str(j))
                h = token.handle if token is not None else manager.versions.get(j//2)
                if token is not None or (h is not None and manager.get(h).phase == 'PUBLISHED'):
                    ready.append(j)
                else:
                    blocked.append(j)
            backlog = [q for q in released_r if q not in pubs]
            record['progress'].append(dict(host_ns=now, context_backlog=len(backlog),
                active_context=None if active is None else active['q'],
                completed_blocks=0 if active is None else active['index'],
                ready_experts=list(ready), version_wait_experts=blocked))
            # A refresh may only publish once the even consumer of the version it
            # retires has been dispatched: that dispatch is what reserves the odd
            # partner on the same version (ownership token), so the fixed version
            # trajectory survives the publication. Without it the predecessor's
            # unexecuted Experts would be stranded on a reclaimed slot.
            def retiring_ready():
                current = manager.current
                if current is None:
                    return True
                j0 = 2*current.version
                if j0 >= len(conf['experts']):
                    return True
                return j0 in es or ('E'+str(j0)) in manager.readers
            if active is not None and active.get('awaiting'):
                if retiring_ready():
                    h = active['h']; q = active['q']
                    before = clock(); manager.publish(h); after = clock()
                    pubs[q] = (before, after)
                    last = [gi for gi, g in enumerate(plan.groups) if (nblocks-1) in g][0]
                    units[q,last] = (units[q,last][0], max(units[q,last][1], after))
                    record.setdefault('published_valid_layers', {})[q] = manager.get(h).valid_layers
                    active = None
                    continue
            # serial_context guarantees that Context *execution* is never
            # interleaved with an Expert. It must NOT block the Expert that the
            # publication guard needs: once every declared block has completed,
            # the build only waits for the predecessor's even consumer to be
            # dispatched (which reserves the odd partner). That Expert is already
            # released, so running it now releases a dependency rather than
            # preempting a running block or executing unreleased work.
            awaiting_publication = active is not None and bool(active.get('awaiting'))
            atomic_context = (policy == 'serial_context' and active is not None
                              and not awaiting_publication)
            if ready and not atomic_context:
                j = ready[0]; job = 'E'+str(j)
                if awaiting_publication:
                    record.setdefault('publication_unblocking_experts', []).append(j)
                if job not in manager.readers:
                    if j % 2: raise RuntimeError('missing even-partner reservation')
                    h = manager.bind(job, snapshots[0].noise_sha, version=j//2)
                    if j+1 < len(conf['experts']):
                        manager.bind('E'+str(j+1), snapshots[0].noise_sha, version=j//2)
                else: h = manager.readers[job].handle
                if h.version != j//2: raise RuntimeError('consumption trajectory changed')
                record['decisions'].append(dict(host_ns=clock(), kind='Expert', id=j,
                    release_ns=t0+conf['experts'][j]['release_ns'], handle=vars(h)))
                es[j] = backend.expert(manager, job, h)
                continue
            if active is None and backlog:
                q = backlog[0]; slot = (q+1) % 2
                owned = manager.slots[slot]
                if owned is not None:
                    # Never reclaim a reader pin or unknown/in-flight fence.
                    manager.reclaim(owned.handle)
                h = manager.begin(slot, snapshots[slot])
                if h.version != q+1: raise RuntimeError('Context FIFO/version changed')
                active = dict(q=q, h=h, index=0, staged=False)
            if active is not None and not active.get('awaiting'):
                q, h = active['q'], active['h']; job = 'R'+str(q)
                if not active['staged']:
                    record['decisions'].append(dict(host_ns=clock(), kind='stage', id=q,
                        release_ns=t0+conf['refreshes'][q]['release_ns'], handle=vars(h)))
                    backend.stage(manager, h, job)
                    active['staged'] = True
                    continue  # Stage is also a real fence, never an enqueue-only claim.
                b = active['index']
                record['decisions'].append(dict(host_ns=clock(), kind='Context', id=q,
                    block=b, block_kind=plan.kinds[b], plan=plan.id,
                    valid_layers_expected=plan.valid_layers[b],
                    release_ns=t0+conf['refreshes'][q]['release_ns'], handle=vars(h)))
                blocks[q,b] = backend.block(manager, h, b, job+'/B'+str(b+1))
                active['index'] += 1
                # Pre-declared obligation groups (two per refresh in every plan),
                # so a third block can never be hidden by a j%2 convention.
                for gi, group in enumerate(plan.groups):
                    if b in group and all((q,x) in blocks for x in group):
                        units[q,gi] = (max(blocks[q,x][0] for x in group),
                                       max(blocks[q,x][1] for x in group))
                if active['index'] == nblocks:
                    if retiring_ready():
                        before = clock(); manager.publish(h); after = clock()
                        pubs[q] = (before, after)
                        last = [gi for gi, g in enumerate(plan.groups) if (nblocks-1) in g][0]
                        units[q,last] = (units[q,last][0], max(units[q,last][1], after))
                        record.setdefault('published_valid_layers', {})[q] = manager.get(h).valid_layers
                        active = None
                    else:
                        active['awaiting'] = True
                        record.setdefault('publication_deferred', []).append(
                            dict(refresh=q, waiting_for=2*manager.current.version,
                                 reason='fixed version trajectory: even consumer not dispatched yet'))
                continue
            future = ([t0+conf['experts'][next_e]['release_ns']] if next_e<len(conf['experts']) else [])
            future += ([t0+conf['refreshes'][next_r]['release_ns']] if next_r<len(conf['refreshes']) else [])
            if not future:
                raise RuntimeError('no runnable dependency or future arrival; keep INCOMPLETE')
            record['decisions'].append(dict(host_ns=now, kind='idle_until_arrival', until_ns=min(future)))
            backend.wait_release(min(future))
        backend.drain()
        record['replay_end_ns'] = clock()
        record['status'] = 'DRAINED_PENDING_VALIDATION'
    finally:
        record['window_end_ns'] = clock()
        record.setdefault('replay_end_ns', record['window_end_ns'])
        backend.leave_window()
        record['journal'] = manager.journal
        if window is None:
            finalize_segment_stats(record, conf, t0, plan, clock)
        else:
            # b6 ordering: statistics after worker_end/exit confirmation. Keep
            # the pending inputs in memory; run_candidates finalizes them after
            # window.finish(), before augmentation/D2H/write.
            record['_stats_pending'] = dict(conf=conf, t0=t0, plan=plan)
