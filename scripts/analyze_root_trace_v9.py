"""Offline-only v9 evidence review. No CUDA/Torch import or board mutation.
Usage: python scripts/analyze_root_trace_v9.py reports/m1_acceptance/tegra_root_trace_20261017_v9
"""
import collections,csv,hashlib,json,re,sys
from pathlib import Path
import numpy as np
from analyze_activity_v6 import analyze
from analyze_pair_trace_v5 import merged,duration,intersection
from m1_frequency_condition import assess,read_root_samples

def csvout(p,rows):
    if not rows:return
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def write(p,r):p.write_text(json.dumps(r,indent=2))
def sha(b):return hashlib.sha256(b).hexdigest()

def main(base):
    base=Path(base);board=base/'board';p=board/'pair'
    r=json.loads((p/'result.json').read_text());pair=r['pair']
    recs=[json.loads(l) for l in (p/'activity_trace/activity.jsonl').read_text().splitlines()]
    ids=json.loads((p/'activity_trace/PHASE_IDS.json').read_text());timeline=analyze(recs,ids)
    write(base/'KERNEL_ANALYSIS.json',timeline)
    integrity=[]
    for f in sorted(p.glob('*.json')):
        m=json.loads(f.read_text())
        if isinstance(m,dict) and {'sha256','nbytes','shape','storage_dtype'}<=m.keys():
            b=f.with_suffix('.bin').read_bytes();integrity.append(dict(name=f.stem,pass_=len(b)==m['nbytes'] and sha(b)==m['sha256']))
    checks=[]
    for s in pair['samples']:
        for kind,ref in [('boundary','reference_S1_boundary'),('final','reference_S1'),('old','reference_S0')]:
            for k in ['x','K','V']:
                f=p/(s['name']+'_'+kind+'_'+k+'.bin');rr=p/(ref+'_'+k+'.bin')
                checks.append(dict(sample=s['name'],tensor=kind+'_'+k,byte_exact=f.read_bytes()==rr.read_bytes()))
        for k in ['raw_bf16','actions']:
            checks.append(dict(sample=s['name'],tensor='Expert_'+k,byte_exact=(p/(s['name']+'_Expert_'+k+'.bin')).read_bytes()==(p/('reference_S0_'+k+'.bin')).read_bytes()))
    collector=[]
    for k in ['x','K','V','raw_bf16','actions']:
        a=p/('collector_reference_S0_'+k+'.bin');b=p/('reference_S0_'+k+'.bin')
        collector.append(dict(tensor=k,byte_exact=a.read_bytes()==b.read_bytes()))
    workloads=[]
    for job,slots in r['ledger'].items():
        for slot,v in slots.items():
            enc=v.get('encoder',[]);dec=v.get('decoder',[])
            want_enc=list(range(9)) if job.endswith('_enc0_8') or job=='gate_B1' else list(range(9,18)) if job.endswith('_enc9_17') or job=='gate_B2' else list(range(18)) if enc else []
            want_dec=[[s,i] for s in range(10) for i in range(18)] if dec else []
            workloads.append(dict(job=job,slot=slot,Encoder_layers=len(enc),Decoder_layer_calls=len(dec),sequence_exact=enc==want_enc and dec==want_dec))
    en=sum(x['Encoder_layers'] for x in workloads);de=sum(x['Decoder_layer_calls'] for x in workloads)
    assert en==162 and de==1620 and all(x['sequence_exact'] for x in workloads)
    csvout(base/'WORK_LEDGER.csv',workloads)
    reverse={v:k for k,v in ids.items()};ext=collections.defaultdict(set);apis=collections.defaultdict(list)
    for x in recs:
        if x['type']=='external':ext[x['pid'],x['correlation']].add(x['external_id'])
        if x['type']=='api':apis[x['pid'],x['correlation']].append(x)
    mapped=[];byphase=collections.defaultdict(list)
    for x in recs:
        if x['type'] not in ('kernel','memcpy'):continue
        key=x['pid'],x['correlation'];labels={reverse.get(v) for v in ext[key]}-{None}
        label=next(iter(labels)) if len(labels)==1 and apis[key] else 'UNASSIGNED'
        byphase[label].append(x)
        mapped.append(dict(type=x['type'],pid=x['pid'],context=x['context'],stream=x['stream'],correlation=x['correlation'],phase=label,start_ns=x['start'],end_ns=x['end'],name=x.get('name','memcpy'),API_names=';'.join(sorted({z['name'] for z in apis[key]}))))
    csvout(base/'CORRELATED_GPU_ACTIVITY.csv',mapped)
    endpoints=[];summaries=[];kernel_tuples=[]
    for s in pair['samples']:
        if s['role']!='diagnostic':continue
        j=s['name'];a=next(x for x in timeline['rows'] if x['job']==j)
        k1=[x for x in byphase['M1P|'+j+'|ENC1'] if x['type']=='kernel'];k2=[x for x in byphase['M1P|'+j+'|ENC2'] if x['type']=='kernel'];e=[x for x in byphase['M1P|'+j+'|EXPERT'] if x['type']=='kernel']
        allk=k1+k2+e;lo=min(x['start'] for x in allk);hi=max(x['end'] for x in allk)
        first2=min(k2,key=lambda x:x['start']);launch=[x for x in apis[first2['pid'],first2['correlation']] if 'Launch' in x['name']]
        first_api=min(launch or apis[first2['pid'],first2['correlation']],key=lambda x:x['start'])
        xu=duration([(x['start'],x['end']) for x in e]);eu=duration([(x['start'],x['end']) for x in k1+k2]);uu=duration([(x['start'],x['end']) for x in allk]);ov=duration(intersection([(x['start'],x['end']) for x in e],[(x['start'],x['end']) for x in k1+k2]))
        assert eu+xu-ov==uu
        # Check each of the ten denoise iterations has the same ordered Kernel names.
        enames=[x['name'] for x in sorted(e,key=lambda x:x['start'])]
        repeated10=len(enames)==2410 and all(enames[t*241:(t+1)*241]==enames[:241] for t in range(10))
        summaries.append(dict(mode=s['mode'],coverage=a['coverage'],Encoder_B1_kernels=len(k1),Encoder_B2_kernels=len(k2),Expert_kernels=len(e),Expert_10_repeated_sequences=repeated10,
            overlap_ms=ov/1e6,Encoder_union_ms=eu/1e6,Expert_union_ms=xu/1e6,all_kernel_union_ms=uu/1e6,
            sum_kernel_durations_ms=sum(x['end']-x['start'] for x in allk)/1e6,first_last_span_ms=(hi-lo)/1e6,
            no_task_kernel_in_span_ms=(hi-lo-uu)/1e6,math_wait_ms=a['Expert_to_math_activity_wait_ns']/1e6,
            schedulable_activity_wait_ms=a['Expert_to_schedulable_activity_wait_ns']/1e6,
            Expert_to_Context_kernel_tail_ms=(a['Context_last_kernel_ns']-a['Expert_last_kernel_ns'])/1e6,
            retention_to_B2_first_kernel_ms=(first2['start']-a['retention_last_activity_ns'])/1e6,
            B2_first_launch_API=first_api['name'],B2_first_launch_API_start_ns=first_api['start'],B2_first_launch_API_end_ns=first_api['end'],
            B2_first_kernel_ns=first2['start'],API_start_to_B2_kernel_ms=(first2['start']-first_api['start'])/1e6,
            API_return_to_B2_kernel_signed_ms=(first2['start']-first_api['end'])/1e6,
            B2_context=first2['context'],B2_stream=first2['stream'],unassigned_pair_kernels=a['unassigned_inside_pair']))
        row=dict(name=j,mode=s['mode'],role=s['role'],window_Host_ms=s['window_Host_ms'],prefix_to_ready_Host_ms=s['full_refresh_prefix_to_ready_Host_ms'],prefix_Event_ms=s['prefix']['event_ms'],Expert_Event_ms=s['Expert_event_ms'],B1_Event_ms=s['Encoder_B1_event_ms'],B2_Event_ms=s['Encoder_B2_event_ms'],initial_detection_Host_ms=s['initial_Expert_detection_Host_ns']/1e6,retention_submit_Host_ms=s['retention_submit_Host_ns']/1e6,
            judgment_to_submit_begin_Host_ms=s['control']['judgment_through_submit_begin_ns']/1e6,judgment_to_submit_return_Host_ms=s['control']['judgment_through_submit_return_ns']/1e6,
            Expert_complete_Host_lower_ns=s['Expert_complete_lower_ns'],Expert_complete_Host_upper_ns=s['Expert_complete_upper_ns'],Context_ready_Host_ns=s['Context_complete_ack_ns'],returned=s['returned'])
        row.update({'Event_'+k+'_ms':v for k,v in s['GPU_endpoints_ms'].items()});row.update(s['GPU_Event_derived']);endpoints.append(row)
        for phase in ['ENC1','ENC2','EXPERT','RETAIN','PREFIX']:
            for x in byphase['M1P|'+j+'|'+phase]:kernel_tuples.append(dict(job=j,mode=s['mode'],phase=phase,type=x['type'],start_ns=x['start'],end_ns=x['end'],context=x['context'],stream=x['stream']))
    csvout(base/'KERNEL_SUMMARY.csv',summaries);csvout(base/'DIAGNOSTIC_ENDPOINTS.csv',endpoints);csvout(base/'TIMELINE_INTERVALS.csv',kernel_tuples)
    attempt=json.loads((board/'ATTEMPTS.json').read_text())[0];hw=[json.loads(l) for l in (board/'hardware.jsonl').read_text().splitlines()]
    frequency=assess(hw,read_root_samples(board/'clock.telemetry.jsonl'),attempt['started_ns'],attempt['ended_ns'])
    apinonzero=collections.Counter((x['name'],x['return_value']) for x in recs if x['type']=='api' and x['return_value'])
    abnormal=[dict(API=k[0],code=k[1],count=v) for k,v in apinonzero.items() if k!=('cudaEventQuery_v3020',600)]
    autotune=[dict(algorithms=int(a),best=int(b),observed_us=float(c)) for a,b,c in re.findall(r'autotune: tested (\d+) algos, best=(\d+) \(([\d.]+) us\)',(board/'pair.log').read_text())]
    write(base/'AUTOTUNE_OBSERVED.json',autotune)
    review=dict(status='PASS' if all(x['pass_'] for x in integrity) and all(x['byte_exact'] for x in checks+collector) and all(x['pass_'] for x in r['checks']) and all(x['exact'] for x in r['comparisons']) and not abnormal else 'FAIL',
        integrity=integrity,saved_pair_comparisons=checks,collector_reference_comparisons=collector,recorded_checks=len(r['checks']),recorded_comparisons=len(r['comparisons']),
        cross_process=r['cross_process_comparisons'],historical_intermediates=r['historical_intermediate_diagnostics'],workload=dict(Contexts=en//18,Experts=de//180,Encoder_layer_calls=en,Decoder_layer_calls=de,SM_probes=2,original_runner_Autotune=2),
        frequency=frequency,hardware=dict(samples=len(hw),temp_min_mC=min(x['temp_mC'] for x in hw),temp_max_mC=max(x['temp_mC'] for x in hw),MemAvailable_min_kB=min(x['MemAvailable_kB'] for x in hw)),
        actual_attempt=attempt,memory=r['memory'],resource_setup_Host_ms=(pair['one_time_resource_preparation']['end_ns']-pair['one_time_resource_preparation']['begin_ns'])/1e6,
        probes=pair['probes'],resources=pair['resources'],addresses_before_overlaps=pair['addresses_before']['overlaps'],addresses_after_overlaps=pair['addresses_after']['overlaps'],cleanup=pair['cleanup'],
        trace_status=timeline['status'],activity_counts=dict(collections.Counter(x['type'] for x in recs)),API_nonzero=[dict(API=k[0],code=k[1],count=v) for k,v in apinonzero.items()],abnormal_API=abnormal,
        unassigned_outside_pair=dict(collections.Counter(x['type'] for x in timeline['unassigned'])),warning='unassigned Torch BF16 direct-copy/readback activity outside diagnostic pair windows does not enter task unions; raw records retained; no continuous hardware/closed-library guarantee',
        normal_source_sha256=sha((base.parent/'scoped_equivalence_20261016_v7/NORMAL_SAMPLES.csv').read_bytes()),independent_restore=json.loads((base/'INDEPENDENT_RESTORE.json').read_text()))
    write(base/'OFFLINE_REVIEW.json',review)
    print(json.dumps(dict(status=review['status'],integrity_files=len(integrity),pair_byte_checks=len(checks),collector_byte_checks=len(collector),checks=review['recorded_checks'],comparisons=review['recorded_comparisons'],work=review['workload'],frequency=frequency,hardware=review['hardware'],trace=timeline['status'],ten_steps=[x['Expert_10_repeated_sequences'] for x in summaries]),indent=2))
if __name__=='__main__':main(sys.argv[1])
