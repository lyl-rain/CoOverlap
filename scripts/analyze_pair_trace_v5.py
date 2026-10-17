"""Offline only: Runtime/Driver correlation, task unions, intersection, coverage."""
import bisect,collections,csv,json,sqlite3,sys
from pathlib import Path

def merged(intervals):
    out=[]
    for a,b in sorted(intervals):
        if b<a:raise ValueError('negative GPU interval')
        if out and a<=out[-1][1]:out[-1]=(out[-1][0],max(out[-1][1],b))
        else:out.append((a,b))
    return out

def duration(intervals):return sum(b-a for a,b in merged(intervals))
def intersection(a,b):
    a,b=merged(a),merged(b);out=[];i=j=0
    while i<len(a) and j<len(b):
        lo,hi=max(a[i][0],b[j][0]),min(a[i][1],b[j][1])
        if lo<hi:out.append((lo,hi))
        if a[i][1]<=b[j][1]:i+=1
        else:j+=1
    return out

def analyze(path):
    con=sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
    tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    if not {'NVTX_EVENTS','CUPTI_ACTIVITY_KIND_KERNEL','StringIds'}<=tables:raise ValueError('required tables absent')
    strings=dict(con.execute('select id,value from StringIds'));calls=collections.defaultdict(list)
    for table in ('CUPTI_ACTIVITY_KIND_RUNTIME','CUPTI_ACTIVITY_KIND_DRIVER'):
        if table in tables:
            for row in con.execute('select * from '+table):
                d=dict(row);d['API_table']=table;calls[d['globalTid']].append(d)
    starts={}
    for tid,a in calls.items():a.sort(key=lambda x:x['start']);starts[tid]=[x['start'] for x in a]
    kernels=[dict(r) for r in con.execute('select * from CUPTI_ACTIVITY_KIND_KERNEL')]
    copies=[dict(r) for r in con.execute('select * from CUPTI_ACTIVITY_KIND_MEMCPY')] if 'CUPTI_ACTIVITY_KIND_MEMCPY' in tables else []
    def key(k):return (k['globalPid'],k.get('contextId'),k['streamId'],k['correlationId'],k['start'],k['end'])
    bycorr=collections.defaultdict(list);mbycorr=collections.defaultdict(list)
    for k in kernels:bycorr[k['globalPid']>>24,k['correlationId']].append(k)
    for k in copies:
        if 'globalPid' in k:mbycorr[k['globalPid']>>24,k['correlationId']].append(k)
    phases=[];assigned={}
    for row in con.execute('select * from NVTX_EVENTS where end>start'):
        r=dict(row);label=r.get('text') or strings.get(r.get('textId'),'')
        if not label.startswith('M1P|'):continue
        _,job,phase=label.split('|');tid=r['globalTid'];aa=calls.get(tid,[])
        selected=aa[bisect.bisect_left(starts.get(tid,[]),r['start']):bisect.bisect_left(starts.get(tid,[]),r['end'])]
        corrs={(a['globalTid']>>24,a['correlationId']) for a in selected}
        ks={key(k):k for corr in corrs for k in bycorr.get(corr,[])}
        ms={key(k):k for corr in corrs for k in mbycorr.get(corr,[])}
        for ident,k in ks.items():
            if ident in assigned and assigned[ident]!=(job,phase):raise ValueError('Kernel assigned to multiple task phases')
            assigned[ident]=(job,phase)
        phases.append(dict(job=job,phase=phase,NVTX_CPU_start_ns=r['start'],NVTX_CPU_end_ns=r['end'],calls=selected,kernels=list(ks.values()),copies=list(ms.values())))
    jobs=[]
    for job in sorted({p['job'] for p in phases}):
        pp={p['phase']:p for p in phases if p['job']==job};get=lambda n:pp.get(n,{}).get('kernels',[])
        enc=get('ENC1')+get('ENC2');exp=get('EXPERT');ret=get('RETAIN')
        ei=[(k['start'],k['end']) for k in enc];xi=[(k['start'],k['end']) for k in exp];inter=intersection(ei,xi)
        model=enc+exp;lo=min((k['start'] for k in model),default=0);hi=max((k['end'] for k in model),default=0)
        pid={k['globalPid'] for k in model}
        unassigned=[k for k in kernels if k['globalPid'] in pid and k['start']<hi and k['end']>lo and key(k) not in assigned]
        covered=set(pp)=={'ENC1','ENC2','EXPERT','RETAIN'} and len(exp)==2410 and bool(ei) and not unassigned
        b1end=max((k['end'] for k in get('ENC1')),default=None);eend=max((k['end'] for k in exp),default=None)
        ract=ret+pp.get('RETAIN',{}).get('copies',[]);ready=max([k['end'] for k in ract]+([b1end] if b1end is not None else []),default=None)
        jobs.append(dict(job=job,coverage='PASS_RECORDED_TASK_KERNELS' if covered else 'UNKNOWN',
            coverage_basis='all four labeled submission ranges, Expert2410, no unassigned Kernel inside paired GPU span; not proof about untraced devices',
            counts={n:len(get(n)) for n in pp},unassigned_in_pair_span=len(unassigned),
            Encoder_union_ns=duration(ei),Expert_union_ns=duration(xi),physical_overlap_ns=duration(inter),physical_overlap_intervals=inter,
            actual_pair_Kernel_union_ns=duration(ei+xi),Encoder_Kernel_end_ns=max((k['end'] for k in enc),default=None),Expert_Kernel_end_ns=eend,
            B1_last_math_Kernel_ns=b1end,retention_last_GPU_activity_ns=ready,
            Expert_to_math_Kernel_wait_ns=max(0,b1end-eend) if b1end is not None and eend is not None else None,
            Expert_to_retention_activity_wait_ns=max(0,ready-eend) if ready is not None and eend is not None else None,
            streams_contexts=sorted({(k['globalPid'],k.get('contextId'),k['streamId']) for k in model}),
            note='Kernel and retention activity endpoints differ from Event marker endpoints. No CPU/GPU absolute clock subtraction.'))
    con.close();return dict(status='PASS_OFFLINE_ANALYSIS' if len(jobs)==4 else 'UNKNOWN_MISSING_JOBS',jobs=jobs,phases=phases,
        method='API within CPU NVTX -> process+correlation GPU activities; union per task then intersection. Never crop GPU to CPU NVTX.')
if __name__=='__main__':
    r=analyze(sys.argv[1]);Path(sys.argv[2]).open('x').write(json.dumps(r,separators=(',',':')))
