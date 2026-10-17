"""Offline Runtime correlation attribution, never CPU-NVTX clipping of kernels."""
import sqlite3,json,sys
from pathlib import Path

def union_ns(intervals):
    total=0;end=None
    for a,b in sorted(intervals):
        if b<a:raise ValueError('negative interval')
        total+=b-max(a,end if end is not None else a) if end is None or b>end else 0
        end=max(b,end) if end is not None else b
    return total

def map_ranges(db):
    con=sqlite3.connect(db);con.row_factory=sqlite3.Row
    names={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    required={'NVTX_EVENTS','CUPTI_ACTIVITY_KIND_RUNTIME','CUPTI_ACTIVITY_KIND_KERNEL'}
    if not required<=names:raise ValueError('missing CUDA/NVTX tables; timeline UNKNOWN')
    strings=dict(con.execute('select id,value from StringIds')) if 'StringIds' in names else {}
    ranges=[]
    for row in con.execute('select * from NVTX_EVENTS where end > start'):
        r=dict(row);text=r.get('text') or strings.get(r.get('textId'),'')
        if text.startswith('M1_SEG_'):r['label']=text;ranges.append(r)
    apis=[dict(x) for x in con.execute('select * from CUPTI_ACTIVITY_KIND_RUNTIME')]
    kernels=[dict(x) for x in con.execute('select * from CUPTI_ACTIVITY_KIND_KERNEL')]
    out=[];attributed=set()
    for r in ranges:
        # CPU submission range selects Runtime calls on its actual thread only.
        calls=[a for a in apis if a['globalTid']==r['globalTid'] and r['start']<=a['start']<r['end']]
        correlations={(a['globalTid']>>24,a['correlationId']) for a in calls}
        # Nsight globalTid packs processId in the high bits; use the SQLite
        # processId field to prevent cross-process correlationId collisions.
        ks=[k for k in kernels if (k['globalPid']>>24,k['correlationId']) in correlations] if kernels and 'globalPid' in kernels[0] else []
        if kernels and 'globalPid' not in kernels[0]:raise ValueError('kernel process field absent; do not guess correlation scope')
        attributed.update((k['globalPid'],k['correlationId'],k['start']) for k in ks)
        intervals=[(k['start'],k['end']) for k in ks];span=max((b for a,b in intervals),default=0)-min((a for a,b in intervals),default=0)
        out.append(dict(label=r['label'],cpu_range_ns=r['end']-r['start'],runtime_calls=len(calls),runtime_sum_ns=sum(a['end']-a['start'] for a in calls),kernels=len(ks),kernel_sum_ns=sum(b-a for a,b in intervals),kernel_union_ns=union_ns(intervals),kernel_span_ns=span,untraced_kernel_gap_ns=span-union_ns(intervals),streams=sorted({k['streamId'] for k in ks}),kernels_raw=ks))
    unmatched=[k for k in kernels if (k['globalPid'],k['correlationId'],k['start']) not in attributed]
    out.append(dict(scope='coverage_metadata',kernel_records=len(kernels),attributed_records=len(attributed),unattributed_records=len(unmatched),unattributed_kernels=unmatched,warning='Unattributed includes outside phase labels or Driver-only correlation; do not claim complete phase coverage. CPU API sums are not GPU busy time. Gaps only mean no attributed traced Kernel, not reclaimable device resources.'))
    return out
if __name__=='__main__':
    from m1_run_identity import require_analysis_user
    require_analysis_user()
    out=Path(sys.argv[2]);out.open('x').write(json.dumps(map_ranges(sys.argv[1]),indent=2))
