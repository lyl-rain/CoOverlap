"""Offline CUPTI adapter records: correlation, task union/intersection, coverage."""
import collections,json,sys
from pathlib import Path
from analyze_pair_trace_v5 import merged,duration,intersection

def analyze(records,phase_ids):
    reverse={v:k for k,v in phase_ids.items()};extern=collections.defaultdict(set);apis=collections.defaultdict(list)
    for r in records:
        if r['type']=='external':extern[r['pid'],r['correlation']].add(r['external_id'])
        elif r['type']=='api':apis[r['pid'],r['correlation']].append(r)
    summaries=[r for r in records if r['type']=='summary'];summary=summaries[-1] if summaries else {}
    healthy=bool(summary) and all(summary.get(k)!=None and summary[k]==0 for k in ('dropped','invalid_GPU_timestamps','parse_errors','callback_errors','adapter_overflow','stop_rc'))
    healthy=healthy and summary.get('outstanding_CUPTI_owned_buffers')==0
    phases=collections.defaultdict(list);unassigned=[]
    for r in records:
        if r['type'] not in ('kernel','memcpy'):continue
        key=(r['pid'],r['correlation']);labels={reverse.get(x) for x in extern[key]}-{None}
        if len(labels)!=1 or not apis[key]:unassigned.append(r);continue
        label=next(iter(labels))
        if not label.startswith('M1P|'):unassigned.append(r);continue
        _,job,phase=label.split('|',2);phases[job,phase].append(r)
    rows=[]
    for job in sorted({j for j,p in phases if j.startswith('pair_diagnostic_')}):
        get=lambda p:[r for r in phases[job,p] if r['type']=='kernel']
        b1,b2,e=get('ENC1'),get('ENC2'),get('EXPERT');enc=b1+b2
        ei=[(r['start'],r['end']) for r in enc];xi=[(r['start'],r['end']) for r in e];ks=enc+e
        lo=min((k['start'] for k in ks),default=0);hi=max((k['end'] for k in ks),default=0)
        missing=[r for r in unassigned if r['type']=='kernel' and r['start']<hi and r['end']>lo]
        valid=healthy and len(e)==2410 and bool(b1) and bool(b2) and not missing
        eend=max((r['end'] for r in e),default=None);b1end=max((r['end'] for r in b1),default=None)
        retained=phases[job,'RETAIN'];ready=max([r['end'] for r in retained]+([b1end] if b1end is not None else []),default=None)
        union=merged(ei+xi);overlap=intersection(ei,xi)
        rows.append(dict(job=job,coverage='PASS_RECORDED_TASK_KERNELS' if valid else 'UNKNOWN',
            physical_overlap_ns=duration(overlap) if valid else None,observed_intersection_ns=duration(overlap),overlap_intervals=overlap,
            Encoder_kernel_union_ns=duration(ei),Expert_kernel_union_ns=duration(xi),pair_kernel_union_ns=duration(union),
            phase_kernel_counts=dict(ENC1=len(b1),ENC2=len(b2),EXPERT=len(e)),unassigned_inside_pair=len(missing),
            Expert_last_kernel_ns=eend,B1_last_math_kernel_ns=b1end,retention_last_activity_ns=ready,
            Expert_to_math_activity_wait_ns=max(0,b1end-eend) if b1end is not None and eend is not None else None,
            Expert_to_schedulable_activity_wait_ns=max(0,ready-eend) if ready is not None and eend is not None else None,
            B2_first_kernel_ns=min((r['start'] for r in b2),default=None),Context_last_kernel_ns=max((r['end'] for r in enc),default=None),
            context_streams={p:sorted({(k['pid'],k['context'],k['stream']) for k in get(p)}) for p in ('ENC1','ENC2','EXPERT')},
            warning='Kernel/retention-activity endpoints differ from CUDA Event markers. Never subtract Host absolute times. Zero overlap needs full coverage; partial intersection is not a complete result.'))
    return dict(status='PASS_AVAILABLE_CORRELATED_TIMELINE' if len(rows)==4 and all(r['coverage'].startswith('PASS') for r in rows) else 'UNKNOWN_INCOMPLETE_COVERAGE',summary=summary,rows=rows,
        unassigned=unassigned,assigned_activity_records=sum(len(v) for v in phases.values()),total_records=len(records),method='external job/phase -> CUDA API process/correlation -> GPU records; task interval unions then intersection; no CPU NVTX clipping')
if __name__=='__main__':
    root=Path(sys.argv[1]);records=[json.loads(l) for l in (root/'activity.jsonl').read_text().splitlines()];ids=json.loads((root/'PHASE_IDS.json').read_text());r=analyze(records,ids)
    Path(sys.argv[2]).open('x').write(json.dumps(r,indent=2))
