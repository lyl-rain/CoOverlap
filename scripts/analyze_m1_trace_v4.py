"""Offline CUDA Runtime correlation for noise wrappers, not Host=GPU claims."""
import json,sqlite3,sys
from pathlib import Path
from m1_completion_trace_map import map_ranges
def analyze(path):
    con=sqlite3.connect(path);con.row_factory=sqlite3.Row
    tables={v[0] for v in con.execute("select name from sqlite_master where type='table'")}
    strings=dict(con.execute('select id,value from StringIds')) if 'StringIds' in tables else {}
    required={'NVTX_EVENTS','CUPTI_ACTIVITY_KIND_RUNTIME','CUPTI_ACTIVITY_KIND_KERNEL'}
    if not required<=tables:return dict(status='UNKNOWN',missing=sorted(required-tables))
    apis=[dict(v) for v in con.execute('select * from CUPTI_ACTIVITY_KIND_RUNTIME')]
    kernels=[dict(v) for v in con.execute('select * from CUPTI_ACTIVITY_KIND_KERNEL')]
    copies=[dict(v) for v in con.execute('select * from CUPTI_ACTIVITY_KIND_MEMCPY')] if 'CUPTI_ACTIVITY_KIND_MEMCPY' in tables else []
    rows=[]
    for row in con.execute('select * from NVTX_EVENTS where end>start'):
        r=dict(row);name=r.get('text') or strings.get(r.get('textId'),'')
        if not name.startswith('M1_NOISE_RECOVERY_'):continue
        calls=[v for v in apis if v['globalTid']==r['globalTid'] and r['start']<=v['start']<r['end']]
        corr={(v['globalTid']>>24,v['correlationId']) for v in calls}
        def matching(v):return (v.get('globalPid',-1)>>24,v.get('correlationId',-1)) in corr
        cc=[v for v in copies if matching(v)];kk=[v for v in kernels if matching(v)]
        for v in calls:v['api_name']=strings.get(v.get('nameId'),'UNKNOWN')
        preceding=sorted((v for v in kernels if v['start']<r['end'] and v['end']>=r['start']-100_000_000),key=lambda v:v['start'])
        rows.append(dict(label=name,Host_NVTX_ns=r['end']-r['start'],runtime=calls,correlated_copies=cc,correlated_kernels=kk,nearby_kernel_records=preceding,warning='Nearby is temporal context only; not a dependency/cause proof. Copy duration uses correlated GPU records, not Host wrapper duration.'))
    return dict(status='PASS_AVAILABLE_TIMELINE',noise_wrappers=rows,phase_kernel_map=map_ranges(path),causal_root='UNKNOWN',one_time_preparation_error='NOT_ESTABLISHED_BY_AUTOMATIC_ANALYSIS')
if __name__=='__main__':
    out=Path(sys.argv[2]);out.open('x').write(json.dumps(analyze(sys.argv[1]),separators=(',',':')))
