"""Indexed offline analysis of the same saved trace; never recollects GPU data."""
import bisect,collections,json,sqlite3,sys,time
from pathlib import Path

def union_ns(intervals):
    total=0;end=None
    for a,b in sorted(intervals):
        total+=max(0,b-max(a,end if end is not None else a));end=max(b,end) if end is not None else b
    return total

def analyze(path):
    began=time.monotonic();con=sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
    tables={v[0] for v in con.execute("select name from sqlite_master where type='table'")}
    need={'NVTX_EVENTS','CUPTI_ACTIVITY_KIND_RUNTIME','CUPTI_ACTIVITY_KIND_KERNEL'}
    if not need<=tables:raise ValueError('required trace tables missing '+str(need-tables))
    strings=dict(con.execute('select id,value from StringIds'))
    apis=[dict(v) for v in con.execute('select * from CUPTI_ACTIVITY_KIND_RUNTIME')]
    kernels=[dict(v) for v in con.execute('select * from CUPTI_ACTIVITY_KIND_KERNEL')]
    copies=[dict(v) for v in con.execute('select * from CUPTI_ACTIVITY_KIND_MEMCPY')] if 'CUPTI_ACTIVITY_KIND_MEMCPY' in tables else []
    by_tid=collections.defaultdict(list);by_kcorr=collections.defaultdict(list);by_mcorr=collections.defaultdict(list)
    for a in apis:by_tid[a['globalTid']].append(a)
    starts={}
    for k,v in by_tid.items():v.sort(key=lambda x:x['start']);starts[k]=[x['start'] for x in v]
    for k in kernels:
        if 'globalPid' not in k:raise ValueError('kernel process identity missing: no guessed correlation')
        by_kcorr[k['globalPid']>>24,k['correlationId']].append(k)
    for m in copies:
        if 'globalPid' in m:by_mcorr[m['globalPid']>>24,m['correlationId']].append(m)
    ranges=[];noise=[];outside=[];attributed=set()
    for row in con.execute('select * from NVTX_EVENTS where end>start'):
        r=dict(row);name=r.get('text') or strings.get(r.get('textId'),'')
        if not name.startswith(('M1_SEG_','M1_NOISE_RECOVERY_','M1_OUTSIDE_VALIDATION_')):continue
        tid=r['globalTid'];a=bisect.bisect_left(starts.get(tid,[]),r['start']);b=bisect.bisect_left(starts.get(tid,[]),r['end']);calls=by_tid.get(tid,[])[a:b]
        corrs={(c['globalTid']>>24,c['correlationId']) for c in calls}
        ks=[k for corr in corrs for k in by_kcorr.get(corr,[])];ms=[m for corr in corrs for m in by_mcorr.get(corr,[])]
        intervals=[(k['start'],k['end']) for k in ks];span=max((y for x,y in intervals),default=0)-min((x for x,y in intervals),default=0);busy=union_ns(intervals)
        rec=dict(label=name,cpu_start_ns=r['start'],cpu_end_ns=r['end'],cpu_NVTX_ns=r['end']-r['start'],runtime_calls=len(calls),runtime_sum_ns=sum(c['end']-c['start'] for c in calls),kernels=len(ks),kernel_sum_ns=sum(y-x for x,y in intervals),kernel_union_ns=busy,kernel_span_ns=span,no_attributed_kernel_ns=span-busy,streams=sorted({k['streamId'] for k in ks}),copies=len(ms),copy_GPU_sum_ns=sum(m['end']-m['start'] for m in ms))
        if name.startswith('M1_NOISE_RECOVERY_'):
            rec['runtime']=[dict(**c,api_name=strings.get(c.get('nameId'),'UNKNOWN')) for c in calls];rec['correlated_copies']=ms;rec['copy_process_identity_available']=not copies or 'globalPid' in copies[0];noise.append(rec)
        elif name.startswith('M1_SEG_'):
            rec['kernels_raw']=ks;ranges.append(rec);attributed.update((k['globalPid'],k['correlationId'],k['start']) for k in ks)
        else:outside.append(rec)
    con.close()
    return dict(status='PASS_AVAILABLE_CORRELATED_TIMELINE',analysis_wall_s=time.monotonic()-began,phase_ranges=ranges,noise_wrappers=noise,outside_validation=outside,total_kernel_records=len(kernels),attributed_phase_kernel_records=len(attributed),all_trace_kernel_union_ns=union_ns([(k['start'],k['end']) for k in kernels]),root_cause='UNKNOWN',warning='Phase assignment uses Runtime process+correlation ID, not GPU clipping to CPU NVTX. CPU API duration, Event envelope, GPU copy duration and Kernel union are separate; absence of attributed Kernel is not proof of reclaimable resources. Host monotonic and Nsight absolute origins are not subtracted.')

if __name__=='__main__':
    out=Path(sys.argv[2]);r=analyze(sys.argv[1]);out.open('x').write(json.dumps(r,separators=(',',':')))
