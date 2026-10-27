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


def run_segment(manager, snapshots, policy, backend, record, clock, conf=None):
    """One outstanding fenced operation; decisions occur AFTER its real completion.

    Blocked-on-version Experts retain original arrivals/deadlines; FIFO Context
    is allowed to produce their dependency. No latest-version substitution.
    This is shared by the serial control and B2, in both observation modes.
    """
    if policy not in ORDER:
        raise ValueError('unreviewed policy')
    conf = manifest() if conf is None else conf
    if conf != manifest(conf['period_ns'], conf['cycles']):
        raise ValueError('changed fixed arrivals/work/binding')
    es, units, pubs = {}, {}, {}
    record.update(protocol=PROTOCOL, mode=policy, manifest=conf, experts=es,
                  units=units, published=pubs, status='NOT_STARTED', decisions=[],
                  arrivals=[], progress=[], t0_ns=None)
    backend.prepare(manager, conf, record)
    backend.bootstrap(manager, 'bootstrap')
    record['initial_state'] = backend.ready(manager)
    t0 = clock() + 10_000_000
    record.update(t0_ns=t0, status='INCOMPLETE')
    next_e = next_r = 0
    released_e, released_r = [], []
    active = None
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
            atomic_context = policy == 'serial_context' and active is not None
            if ready and not atomic_context:
                j = ready[0]; job = 'E'+str(j)
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
            if active is not None:
                q, h = active['q'], active['h']; job = 'R'+str(q)
                if not active['staged']:
                    record['decisions'].append(dict(host_ns=clock(), kind='stage', id=q,
                        release_ns=t0+conf['refreshes'][q]['release_ns'], handle=vars(h)))
                    backend.stage(manager, h, job)
                    active['staged'] = True
                    continue  # Stage is also a real fence, never an enqueue-only claim.
                b = active['index']
                record['decisions'].append(dict(host_ns=clock(), kind='Context', id=q,
                    block=b, release_ns=t0+conf['refreshes'][q]['release_ns'], handle=vars(h)))
                units[q,b] = backend.block(manager, h, b, job+'/B'+str(b+1))
                active['index'] += 1
                if active['index'] == 2:
                    before = clock(); manager.publish(h); after = clock()
                    pubs[q] = (before, after)
                    units[q,b] = (units[q,b][0], max(units[q,b][1],after))
                    active = None
                continue
            future = ([t0+conf['experts'][next_e]['release_ns']] if next_e<len(conf['experts']) else [])
            future += ([t0+conf['refreshes'][next_r]['release_ns']] if next_r<len(conf['refreshes']) else [])
            if not future:
                raise RuntimeError('no runnable dependency or future arrival; keep INCOMPLETE')
            record['decisions'].append(dict(host_ns=now, kind='idle_until_arrival', until_ns=min(future)))
            backend.wait_release(min(future))
        backend.drain()
        record['status'] = 'DRAINED_PENDING_VALIDATION'
    finally:
        record['window_end_ns'] = clock()
        backend.leave_window()
        record['journal'] = manager.journal
        record['statistics'] = replay_stats(conf, es, units, pubs, t0)
        record['statistics']['quantile_method'] = 'diagnostic n=4 only; no reliable tail/k_min'
        record['remaining_Expert_ids'] = [e['id'] for e in conf['experts'] if e['id'] not in es]
        record['remaining_Context_ids'] = [r['id'] for r in conf['refreshes'] if r['id'] not in pubs]
