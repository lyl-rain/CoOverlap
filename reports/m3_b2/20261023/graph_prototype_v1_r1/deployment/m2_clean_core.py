"""CPU-only frozen protocol, exact retention layout and common replay order.

Reuses the v3 ownership state machine and mathematical work definitions.
The same replay function is used in correctness and performance modes.
"""
from m2_executor import DEFAULT_PLAN, replay_manifest, replay_stats

PROTOCOL = 'm2_clean_serial_v1'
CYCLES = 16
PERIOD_NS = 240_000_000
ORDER = ('serial_adjacent', 'serial_resumed', 'serial_resumed', 'serial_adjacent')
X = 561 * 2048 * 2
KV_LAYER = 561 * 256 * 2
FULL = X + 36 * KV_LAYER
MID = X + 18 * KV_LAYER
IMAGES = 2 * 224 * 224 * 3 * 2
NOISE = 50 * 32 * 2
SIZES = dict(full=FULL, mid=MID, prefix=X, images=IMAGES, noise=NOISE, raw=NOISE)


def tag(version):
    return dict(slot=version % 2, generation=version // 2 + 1,
                version=version, snapshot='S'+str(version % 2))


def retention_layout(cycles=CYCLES, plan=None):
    plan = DEFAULT_PLAN if plan is None else plan
    if cycles < 2 or cycles % 2:
        raise ValueError('finite even cycle count required')
    entries = []; offset = 0
    def add(key, job, version, shape, expected):
        nonlocal offset
        n = SIZES[shape]
        entries.append(dict(key=key, job=job, offset=offset, nbytes=n,
                            shape=shape, expected=expected, **tag(version)))
        offset += n
    for j in range(cycles):
        v=j//2;job='E'+str(j)
        add(job+'/noise',job,v,'noise','noise')
        add(job+'/pre',job,v,'full','ref'+str(v%2))
        add(job+'/raw',job,v,'raw','raw'+str(v%2))
        add(job+'/post',job,v,'full','ref'+str(v%2))
    for q in range(cycles//2):
        v=q+1;job='R'+str(q)
        add(job+'/images',job,v,'images','images')
        add(job+'/noise',job,v,'noise','noise')
        for b in range(len(plan)):
            key=job+'/B'+str(b+1)
            shape=plan.shapes[b]
            add(key+'/other_pre',job,v-1,'full','ref'+str((v-1)%2))
            add(key+'/target',job,v,shape,
                ('pre' if shape=='prefix' else 'mid' if shape=='mid' else 'ref')+str(v%2))
            add(key+'/other_post',job,v-1,'full','ref'+str((v-1)%2))
    return dict(entries=entries, nbytes=offset, count=len(entries))


def gate_retention_layout(cycles=CYCLES, plan=None):
    # The v3 18-journal gate uses E0 and R0 only. Compact, bounded prep bank.
    # The default call stays exactly the frozen zero-argument form.
    if plan is None and cycles==CYCLES:
        source=retention_layout()['entries']
    else:
        source=retention_layout(cycles,plan)['entries']
    entries=[];offset=0
    for e in source:
        if e['job'] not in ('E0','R0'):continue
        e=dict(e,offset=offset);entries.append(e);offset+=e['nbytes']
    return dict(entries=entries,nbytes=offset,count=len(entries))


def protocol():
    layout=retention_layout()
    return dict(id=PROTOCOL, status='PREPARED', modes=list(ORDER), cycles_per_segment=CYCLES,
                manifest=replay_manifest(PERIOD_NS,CYCLES), model_limit=1, retry_limit=0,
                model_timeout_s=180, model_internal_stop_s=170, kill_grace_s=10,
                scope_limit_s=420, scope_internal_s=300, scope_runtime_max_s=340,
                scope_start_s=15, scope_stop_s=60,
                hardware_min_targets={'/sys/devices/system/cpu/cpufreq/policy0/scaling_min_freq':2201600,
                                     '/sys/devices/system/cpu/cpufreq/policy4/scaling_min_freq':2201600,
                                     '/sys/devices/system/cpu/cpufreq/policy8/scaling_min_freq':2201600,
                                     '/sys/class/devfreq/17000000.gpu/min_freq':1300500000,
                                     '/sys/class/devfreq/bwmgr/min_freq':3199000000},
                timed=dict(Contexts=32, Experts=64, Encoder_layers=576, Decoder_layers=11520,Vision_layers=864),
                prep=dict(references=dict(Contexts=2,Experts=2),
                          D1_original_pipeline=dict(Contexts=1,Experts=1),
                          version_gate=dict(Contexts=2,Experts=1),
                          segment_bootstraps=dict(Contexts=4,Experts=0),
                          warmup=dict(Contexts=2,Experts=0),
                          autotune=dict(runners=2,BF16_tune_requests_per_runner=18,total_tune_requests=36,
                                        max_candidates_per_request=16,warmup_matmuls_per_candidate=3,
                                        measured_matmuls_per_candidate=10,source_matmul_attempt_upper_bound=7488,
                                        actual_attempts='opaque binary internals not directly counted; current C++ source bound; per-slot candidate logs retained; no extra full forward')),
                total=dict(Contexts=43,Experts=68,Encoder_layers=774,Decoder_layers=12240,Vision_layers=1161,language=43),
                observed_ledger=dict(Contexts=40,Experts=67,Encoder_layers=720,
                                     Decoder_layers=12060,language=40,vision=40,entries=12860),
                retention=dict(records_per_segment=layout['count'],
                               GPU_capacity_B=layout['nbytes'],Host_pinned_capacity_B=layout['nbytes'],
                               batch_payload_B=4*layout['nbytes'],gate_payload_B=gate_retention_layout()['nbytes'],physical_banks=1,
                               reuse='only after all events, D2H, all comparisons, and persistence succeed',
                               auxiliary_host_budget_B=256*1024**2,
                               timed_restore_D2D_B_per_segment=(CYCLES+CYCLES//2)*NOISE+(CYCLES//2)*IMAGES),
                numeric='D1 same-process byte exact; historical 0.015625/0.01 report only',
                initial='new logical manager; v0/S0/slot0/generation1 published; no readers',
                interpretation='one process/configuration baseline; no k_min, B2 benefit or reliable tail claim')


class RetentionLedger:
    """One preallocated physical bank; generation-bound claims cannot alias jobs."""
    def __init__(self, layout, capacity):
        if capacity < layout['nbytes']:
            raise ValueError('retention capacity insufficient before any launch')
        self.layout=layout;self.capacity=capacity
        self.entries={e['key']:dict(e) for e in layout['entries']}
        self.epoch=-1;self.reusable=True;self.claims={};self.verified=False

    def begin(self, epoch):
        if not self.reusable or epoch<=self.epoch:
            raise RuntimeError('retention bank still owned or stale epoch')
        self.epoch=epoch;self.reusable=False;self.claims={};self.verified=False

    def claim(self,key,handle,snapshot):
        if self.reusable or key in self.claims:
            raise RuntimeError('bank not active or duplicate retention job')
        e=self.entries[key]
        got=dict(slot=handle.slot,generation=handle.generation,version=handle.version,snapshot=snapshot.name)
        if any(got[k]!=e[k] for k in got):
            raise ValueError('retention index has wrong job version/slot/generation/snapshot')
        if e['offset']+e['nbytes']>self.capacity:
            raise ValueError('retention capacity changed')
        self.claims[key]=dict(epoch=self.epoch,key=key,job=e['job'],**got,
                              state_sha=snapshot.state_sha,noise_sha=snapshot.noise_sha,
                              event=None,copied=False)
        return e

    def seal(self,keys,event):
        for key in keys:
            c=self.claims[key]
            if c['copied']:raise RuntimeError('retention already sealed')
            c['event']=event;c['copied']=True

    def complete(self):
        if set(self.claims)!=set(self.entries):raise RuntimeError('missing retained jobs')
        for c in self.claims.values():
            if not c['copied'] or c['event'] is None or not c['event'].query():
                raise RuntimeError('retention event incomplete/unknown')

    def mark_verified(self):
        self.complete();self.verified=True

    def release(self,persisted):
        if not self.verified or not persisted:raise RuntimeError('bank must be fully verified and persisted')
        self.reusable=True

    def metadata(self):
        return [{k:v for k,v in c.items() if k!='event'} for c in self.claims.values()]

    def status(self):
        """Non-raising snapshot for failure attribution (never marks PASS)."""
        rows=[]
        for key,c in self.claims.items():
            e=self.entries[key]
            try:event_ready=bool(c['event'] is not None and c['event'].query())
            except BaseException:event_ready='ERROR'
            rows.append(dict(key=key,job=c['job'],slot=c['slot'],generation=c['generation'],
                             version=c['version'],snapshot=c['snapshot'],
                             offset=e['offset'],nbytes=e['nbytes'],
                             copied=bool(c['copied']),event_ready=event_ready))
        return dict(epoch=self.epoch,verified=bool(self.verified),reusable=bool(self.reusable),
                    claimed=len(self.claims),expected=len(self.entries),
                    missing=sorted(set(self.entries)-set(self.claims)),claims=rows)


def replay_segment(manager,snapshots,mode,backend,record,clock):
    """V3 ordering with 16 fixed releases; all one-time setup precedes t0.

    Backend is shared between correctness/performance modes. The only mode
    difference is observation: eager numerical checks vs deferred bank audit.
    """
    if mode not in ('serial_adjacent','serial_resumed'):
        raise ValueError('unreviewed schedule')
    conf=replay_manifest(PERIOD_NS,CYCLES)
    es={};us={};pubs={}
    jobs=['E'+str(j) for j in range(CYCLES)]
    refreshes=['R'+str(q) for q in range(CYCLES//2)]
    record.update(mode=mode,status='NOT_STARTED',manifest=conf,
                  experts=es,units=us,published=pubs,t0_ns=None)
    backend.prepare(manager,conf,record)
    backend.bootstrap(manager,'bootstrap')
    # This hook drains, materializes/preallocates, validates initial state,
    # initializes/saves the report. Nothing of that kind follows t0.
    record['initial_state']=backend.ready(manager)
    t0=clock()+10_000_000
    record['t0_ns']=t0;record['status']='INCOMPLETE'
    backend.enter_window()
    try:
        for j,job in enumerate(jobs):
            backend.wait_release(t0+j*PERIOD_NS)
            if j%2==0:
                h=manager.bind(job,snapshots[0].noise_sha,version=j//2)
                manager.bind(jobs[j+1],snapshots[0].noise_sha,version=j//2)
            else:h=manager.readers[job].handle
            if h.version!=j//2:raise RuntimeError('fixed consumption trajectory changed')
            es[j]=backend.expert(manager,job,h)
            q=j//2
            if j%2==0:
                slot=1-manager.current.slot
                if manager.slots[slot] is not None:manager.reclaim(manager.slots[slot].handle)
                active=manager.begin(slot,snapshots[slot])
                backend.stage(manager,active,refreshes[q])
                us[q,0]=backend.block(manager,active,0,refreshes[q]+'/B1')
            if (mode=='serial_adjacent' and j%2==0) or (mode=='serial_resumed' and j%2==1):
                us[q,1]=backend.block(manager,active,1,refreshes[q]+'/B2')
                before=clock();manager.publish(active);after=clock();pubs[q]=(before,after)
                # Count the real publication bookkeeping; never deduct it.
                us[q,1]=(us[q,1][0],max(us[q,1][1],after))
        backend.drain()
        record['status']='DRAINED_PENDING_VALIDATION'
    finally:
        record['window_end_ns']=clock()
        backend.leave_window()
        # Numerical comparison, D2H, event elapsed_time, JSON and persistence
        # occur only in the caller AFTER this common driver has returned.
        record['journal']=manager.journal
        record['statistics']=replay_stats(conf,es,us,pubs,t0)
        record['statistics']['quantile_method']='nearest rank Host completion bounds; n=16 per segment; no reliable-tail claim'
