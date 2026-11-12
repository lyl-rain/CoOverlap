"""CPU-only same-trace API/kernel gap accounting; no normal/profiler mixing."""
import csv
import json
from pathlib import Path
import sqlite3
import sys
from analyze_trace import merge,length,intersect,sweep


def records(path):
    with path.open() as f:return list(csv.DictReader(f))


def save(path,rows):
    assert rows
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def union_scan(intervals):
    points={}
    for a,b in intervals:points[a]=points.get(a,0)+1;points[b]=points.get(b,0)-1
    last=None;count=0;total=0
    for t,delta in sorted(points.items()):
        if last is not None and count:total+=t-last
        count+=delta;last=t
    assert count==0
    return total


def gaps(intervals):
    merged=merge(intervals)
    return [(a[1],b[0]) for a,b in zip(merged,merged[1:]) if b[0]>a[1]]


def classify(a,b,future):
    # Future = kernels that have not started anywhere inside this no-role-
    # kernel interval. No Graph node is treated as an individual Host launch.
    if not future:return dict(no_API_started_ns=0,API_inflight_ns=0,API_returned_pending_ns=0,unclassified_ns=b-a)
    first_start=min(k['API_start_ns'] for k in future)
    first_end=min(k['API_end_ns'] for k in future)
    not_started=max(0,min(b,first_start)-a)
    pending=max(0,b-max(a,first_end))
    inflight=(b-a)-not_started-pending
    assert inflight>=0 and not_started+inflight+pending==b-a
    return dict(no_API_started_ns=not_started,API_inflight_ns=inflight,API_returned_pending_ns=pending,unclassified_ns=0)


def analyze(root):
    root=Path(root);point=root.name;out=root/'analysis'
    ks=records(out/'kernel_records.csv')
    for k in ks:
        for field in ('start_ns','end_ns','API_start_ns','API_end_ns'):k[field]=int(k[field])
        k['duration_ms']=(k['end_ns']-k['start_ns'])/1e6
        scope='parent Graph launch, not per-node Host launch' if 'GraphLaunch' in k['API'] else 'individual kernel launch'
        k['actual_API_scope']=scope;k['point']=point
    c=sqlite3.connect('file:'+str(root/'diagnostic.sqlite')+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
    strings={x['id']:x['value'] for x in c.execute('select * from StringIds')}
    nv=[]
    for n in c.execute('select * from NVTX_EVENTS'):
        v=dict(n);v['label']=v.get('text') or strings.get(v.get('textId'),'')
        if v.get('end'):nv.append(v)
    frames={n['label']:n for n in nv if n['label'].startswith('SAMPLE|')}
    r=json.loads((root/'run_01/result.json').read_text())
    host={x['label']:x for x in r['samples'] if x['sample_kind']=='trace'}
    assert len(frames)==4
    summary=[];hole_rows=[];launch_rows=[];api_rows=[]
    raw_apis=[]
    for table in ('CUPTI_ACTIVITY_KIND_RUNTIME','CUPTI_ACTIVITY_KIND_DRIVER'):
        present=c.execute('select count(*) from sqlite_master where name=?',(table,)).fetchone()[0]
        if present:
            for a in c.execute('select * from '+table):
                d=dict(a);d['table']=table;d['name']=strings.get(d.get('nameId'),'');raw_apis.append(d)
    for label,frame in frames.items():
        _,payload=label.split('|',1);_,path,block,_=payload.split('/');sel=[k for k in ks if k['sample']==label]
        row=dict(point=point,Expert_path=path,block=block,profiler=True,frame_start_ns=frame['start'],frame_end_ns=frame['end'],
                 source=str(root/'diagnostic.nsys-rep'),sample=label)
        normal_host=host[payload]
        row.update(Expert_Host_submit_ms=normal_host['Expert_Host_submit_ms'],VLM_Host_submit_ms=normal_host['VLM_Host_submit_ms'],
                   Host_pair_wall_ms=normal_host['Host_wall_ms'],Expert_Event_ms=normal_host['Expert_Event_ms'],VLM_Event_ms=normal_host['VLM_Event_ms'])
        for role in ('Expert','VLM','Both'):
            chosen=[k for k in sel if role=='Both' or k['role']==role]
            intervals=[(k['start_ns'],k['end_ns']) for k in chosen]
            union=length(intervals);assert union==union_scan(intervals)
            first=min(a for a,b in intervals);last=max(b for a,b in intervals)
            hs=gaps(intervals);assert sum(b-a for a,b in hs)==last-first-union
            row.update({role+'_kernel_count':len(chosen),role+'_GPU_first_ns':first,role+'_GPU_last_ns':last,
                role+'_GPU_first_relative_ms':(first-frame['start'])/1e6,role+'_GPU_last_relative_ms':(last-frame['start'])/1e6,
                role+'_kernel_union_ms':union/1e6,role+'_GPU_envelope_ms':(last-first)/1e6,role+'_no_target_kernel_ms':sum(b-a for a,b in hs)/1e6})
            sums={name:0 for name in ('no_API_started_ns','API_inflight_ns','API_returned_pending_ns','unclassified_ns')}
            for idx,(a,b) in enumerate(hs):
                future=[k for k in chosen if k['start_ns']>=b]
                values=classify(a,b,future)
                for name,value in values.items():sums[name]+=value
                other=[(k['start_ns'],k['end_ns']) for k in sel if role!='Both' and k['role']!=role]
                hole_rows.append(dict(point=point,Expert_path=path,block=block,sample=label,gap_role=role,index=idx,start_ns=a,end_ns=b,
                    start_relative_ms=(a-frame['start'])/1e6,end_relative_ms=(b-frame['start'])/1e6,gap_ms=(b-a)/1e6,
                    **{name.replace('_ns','_ms'):value/1e6 for name,value in values.items()},
                    other_branch_active_ms=length(intersect(other,[(a,b)]))/1e6,
                    graph_parent_API_scope=any('GraphLaunch' in k['API'] for k in future),
                    meaning='role absent within its first/last kernel envelope; API-returned pending does not establish device readiness; no target kernel does not establish whole-device idle'))
            row.update({role+'_'+name.replace('_ns','_ms'):value/1e6 for name,value in sums.items()})
            assert abs(sum(sums.values())-sum(b-a for a,b in hs))==0
            if role!='Both':
                launches=sorted({(k['API_start_ns'],k['API_end_ns'],k['API'],k['correlationId']) for k in chosen})
                row[role+'_unique_launch_API_count']=len(launches)
                for idx,(start,end,name,correlation) in enumerate(launches):
                    previous=launches[idx-1] if idx else None
                    launch_rows.append(dict(point=point,Expert_path=path,block=block,sample=label,role=role,index=idx,
                        name=name,API_start_ns=start,API_end_ns=end,duration_ms=(end-start)/1e6,
                        start_to_previous_start_ms=(start-previous[0])/1e6 if previous else None,
                        start_minus_previous_end_ms=(start-previous[1])/1e6 if previous else None,
                        correlationId=correlation,scope='one parent Graph launch' if 'GraphLaunch' in name else 'individual launch'))
                sub=next(n for n in nv if n['label']=='SUBMIT|'+payload+'|'+role)
                row[role+'_NVTX_submit_start_ns']=sub['start'];row[role+'_NVTX_submit_end_ns']=sub['end']
                row[role+'_NVTX_submit_ms']=(sub['end']-sub['start'])/1e6
        exp=[(k['start_ns'],k['end_ns']) for k in sel if k['role']=='Expert'];vlm=[(k['start_ns'],k['end_ns']) for k in sel if k['role']=='VLM']
        overlap=length(intersect(exp,vlm));assert overlap==sweep(exp,vlm)
        row['overlap_ms']=overlap/1e6
        row['VLM_first_API_minus_Expert_last_kernel_ms']=(min(k['API_start_ns'] for k in sel if k['role']=='VLM')-max(b for a,b in exp))/1e6
        row['last_target_kernel_to_frame_end_ms']=(frame['end']-max(k['end_ns'] for k in sel))/1e6
        action=next(n for n in nv if n['label']=='ACTION|'+payload)
        row['action_delivery_NVTX_end_relative_ms']=(action['end']-frame['start'])/1e6
        for a in raw_apis:
            if frame['start']<=a['start']<frame['end']:
                api_rows.append(dict(point=point,Expert_path=path,block=block,sample=label,table=a['table'],name=a['name'],start_ns=a['start'],end_ns=a['end'],duration_ms=(a['end']-a['start'])/1e6,correlationId=a.get('correlationId'),returnValue=a.get('returnValue')))
        if path=='Eager':assert row['Expert_unique_launch_API_count']==2410
        else:assert row['Expert_unique_launch_API_count']==1
        summary.append(row)
    save(out/'cpu_trace_kernel_activity.csv',summary);save(out/'cpu_trace_api_gaps.csv',hole_rows)
    save(out/'cpu_trace_launch_apis.csv',launch_rows);save(out/'cpu_trace_all_APIs.csv',api_rows)
    save(out/'kernel_records_scoped.csv',ks)
    (out/'gap_accounting_verification.json').write_text(json.dumps(dict(status='PASS',windows=4,
        unions='merged intervals independently checked by endpoint union scan',overlap='two-pointer intersection independently checked by endpoint sweep',
        gap_accounting='each no-role-kernel gap exactly partitions no API started / API inflight / returned pending / unclassified',
        limitation='API-returned pending does not prove readiness; Graph parent API never counted as per-node launch; no target kernel is not full GPU idle'),indent=2))
    c.close();return summary


if __name__=='__main__':
    for arg in sys.argv[1:]:print(json.dumps(dict(root=arg,windows=len(analyze(arg)))))
