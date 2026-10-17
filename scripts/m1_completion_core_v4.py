"""CPU-only finite M1 protocol, obligation accounting and budget selection."""
from period_obligation_stats import classify,counts

def jobs(t0,period_ns,cycles):
    if cycles<2 or cycles%2:raise ValueError('even cycle count required')
    e=[dict(id=j,unit_id=f'E{j}',release_ns=t0+j*period_ns,deadline_ns=t0+(j+1)*period_ns,status='NOT_RELEASED',bound_version='v0',snapshot='S0') for j in range(cycles)]
    r=[dict(id=m,unit_id=f'R{m}',release_ns=t0+2*m*period_ns,deadline_ns=t0+(2*m+2)*period_ns,status='NOT_RELEASED',phase=0,snapshot='S1',target_periods=2) for m in range(cycles//2)]
    return e,r

def cycle_rows(s):
    P=s['P_ms']*1_000_000;t0=s['t0_ns'];n=s['cycles'];ee={x['id']:x for x in s['experts']};uu={(x['id'],x['unit']):x for x in s.get('unit_completions',[])};out=[]
    for j in range(n):
        unit='B1' if j%2==0 else 'B2';e=ee.get(j,{});u=uu.get((j//2,unit),{})
        el,eh=e.get('completion_lower_ns'),e.get('completion_observed_ns');ul,uh=u.get('completion_lower_ns'),u.get('completion_observed_ns');rel=t0+j*P;deadline=rel+P
        lo=max(el,ul) if el is not None and ul is not None else None;hi=max(eh,uh) if eh is not None and uh is not None else None
        out.append(dict(cycle=j,Expert_id=f'E{j}',required_unit_id=f'R{j//2}/{unit}',release_ns=rel,deadline_ns=deadline,expert_lower_ns=el,expert_upper_ns=eh,unit_lower_ns=ul,unit_upper_ns=uh,expert_status=classify(el,eh,deadline),VLM_status=classify(ul,uh,deadline),cycle_status=classify(lo,hi,deadline),response_lower_ms=(lo-rel)/1e6 if lo is not None else None,response_upper_ms=(hi-rel)/1e6 if hi is not None else None))
    return out

def base_config(role,cycles,segments,timeout):
    return dict(protocol='m1_completion_20261016_v4',role=role,cycles=cycles,segments=segments,timeout_s=timeout,tail_reserve_s=60,segment_timeout_s=60,poll_sleep_s=0.0001,refresh_interval_cycles=2,target_refresh_periods=2,version_binding='all Experts immutable S0/v0; S1/v1 readiness only',model=dict(checkpoint='/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5',bf16=True,views=2,prompt_tokens=49,encoder_seq=561,encoder_layers=18,action_chunk=50,denoise_steps=10),criterion='byte exact with finite certified references',required_hardware=dict(CPU_minmax_kHz=2201600,GPU_minmax_Hz=1300500000,EMC_minmax_Hz=3199000000,power_mode='MAXN 0 unchanged'),observations=dict(B1_obligation='model_done_event BEFORE midpoint D2D',two_blocks_boundary='Block1 op_end AFTER midpoint D2D, Host query confirmed',whole_context='same-stream B2 submission without internal scheduling/wait',clock_condition='SATISFIED_SAMPLED/NOT_MET/UNKNOWN; preserve every cycle, no retry or filtering',EMC_request='bwmgr min/max/target',EMC_reported_current='bwmgr cur_freq',EMC_independent_readonly='/sys/kernel/debug/bpmp/debug/clk/emc/rate',root_sample_gap_limit_s=2.5),interference=dict(kind='memcpy32MiB',worker_cpu=11,main_cpus=list(range(11)),bytes_per_buffer=33554432,workers=1,worker_entry='m1_memcpy_interference_v4.py',worker_lifetime_s=90,settle_s=2.0),timed_ledger=dict(Experts=cycles*len(segments),Contexts=(cycles//2)*len(segments)),prep_ledger=dict(Contexts=3,Experts=2,Autotune='two original private runners, outside timing'),capture=role=='trace',no_retry=True,numerical_policy={'in_process':'raw bytes exact','cross_process_bf16_max_abs':0.015625,'cross_process_action_f32_max_abs':0.01,'cross_process_conditions':'fixture/noise/effective KV/final x byte exact','relative_tolerance':None,'cause':'UNKNOWN'},release_setup='save/flush and one-time preparation BEFORE t0=now+10ms')

def segment(P,plan,stress):return dict(P_ms=P,plan=plan,interference=stress)

def calibration_config():return base_config('calibration',32,[segment(p,'whole_context','none') for p in [180,240,320]],180)

def select_budgets(result):
    """Independent validation only. Never move formal deadlines in a run."""
    if result.get('status')!='PASS' or result.get('protocol_id')!='m1_completion_20261016_v4':raise ValueError('calibration not fully PASS')
    if result.get('role')!='calibration':raise ValueError('wrong role')
    by={s['P_ms']:s for s in result['segments']}
    if len(result['segments'])!=3 or set(by)!={180,240,320}:raise ValueError('candidate list changed')
    rates={}
    for P,s in by.items():
        if s.get('frequency_condition',{}).get('status')!='SATISFIED_SAMPLED':raise ValueError('calibration actual-frequency condition NOT_MET/UNKNOWN; retain all data, no subsequent run or retry')
        c=s['cycle_statistics']['cycle_status'];q=s['refresh_statistics']
        if s['status']!='PASS' or s['cycles']!=32 or c['denominator']!=32 or c['UNCERTAIN'] or c['INCOMPLETE']:raise ValueError('invalid calibration evidence')
        if any(v['UNCERTAIN'] or v['INCOMPLETE'] for v in list(s['cycle_statistics'].values())+[q]):raise ValueError('uncertain calibration observation: STOP')
        rates[P]=dict(cycle_miss=c['FAIL']/32,refresh_on_time=q['PASS']/16)
    loose=[P for P in [240,320] if rates[P]['cycle_miss']<=.05 and rates[P]['refresh_on_time']>=.95]
    if not loose:raise ValueError('no predeclared loose representative: STOP, no auto expansion')
    L=min(loose)
    candidates=[P for P in [180,240] if P<L and .05<=rates[P]['cycle_miss']<=.95 and rates[P]['refresh_on_time']>=.50]
    if not candidates:raise ValueError('no predeclared tight representative: STOP, no scan')
    return dict(tight_ms=max(candidates),loose_ms=L,calibration_rates=rates,interpretation='exploratory feasibility bands, not deployment specification or exact capacity or tail guarantee')

def formal_configs(selection):
    T,L=selection['tight_ms'],selection['loose_ms']
    cells=[('whole_context','none'),('whole_context','memcpy32MiB'),('two_blocks','none'),('two_blocks','memcpy32MiB')]
    # Frozen balanced process order T1 L1 L2 T2 T3 L3; each budget has three processes.
    process_order=[('tight',T,1),('loose',L,1),('loose',L,2),('tight',T,2),('tight',T,3),('loose',L,3)]
    orders=[[0,1,2,3],[3,2,1,0],[2,3,0,1]]
    return [base_config(f'{band}_repeat{rep}',64,[segment(P,*cells[j]) for j in orders[rep-1]],300) for band,P,rep in process_order]

def trace_config(selection=None):
    return base_config('trace',16,[segment(180,p,s) for p in ['whole_context','two_blocks'] for s in ['none','memcpy32MiB']],180)

def pair_config():
    c=base_config('pair',0,[],180)
    c.update(pair=dict(prefix='Vision27 + norm/projector/bias + language; outside pair window',groups=[list(range(9)),list(range(9,18))],expert='all 10 steps on immutable S0/v0',gate='one ordinary dual-stream pair',formal_order=['serial','ordinary','fixed','return']*3,samples_per_mode=3,quota_SM=[8,8],return_rule='at layer8 boundary query Expert done; ordinary stream only if already done; otherwise submit B2 limited immediately, no artificial wait',kernel_overlap='UNKNOWN unless actual Kernel timeline exists; Event overlap is not physical proof'),timed_ledger=dict(Experts=12,Contexts=12),pair_gate_ledger=dict(Experts=1,Contexts=1),capture=False)
    return c

def validate_config(c):
    if c['role']=='calibration':expected=calibration_config()
    elif c['role']=='trace':expected=trace_config()
    elif c['role']=='pair':expected=pair_config()
    else:
        candidates=[]
        for T,L in ((180,240),(180,320),(240,320)):
            candidates += [x for x in formal_configs(dict(tight_ms=T,loose_ms=L)) if x['role']==c['role']]
        if c not in candidates:raise ValueError('formal config differs from finite manifest')
        expected=c
    if c!=expected:raise ValueError('process config differs from finite manifest')
    return c['timed_ledger']
