"""Offline saved-evidence audit. No Torch/CUDA import or device access."""
import csv, hashlib, json, statistics, sys
from pathlib import Path
from m1_frequency_condition import assess, read_root_samples

def sha(b): return hashlib.sha256(b).hexdigest()
def csvout(path, rows):
    with path.open('w', newline='') as f:
        w=csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def main(base):
    base=Path(base); board=base/'board'; p=board/'pair'
    r=json.loads((p/'result.json').read_text()); pair=r['pair']
    integrity=[]
    for path in sorted(p.glob('*.json')):
        meta=json.loads(path.read_text())
        if isinstance(meta,dict) and {'sha256','nbytes','shape','storage_dtype'}<=meta.keys():
            b=path.with_suffix('.bin').read_bytes()
            integrity.append(dict(name=path.stem,match=len(b)==meta['nbytes'] and sha(b)==meta['sha256']))
    required=[]
    for s in pair['samples']:
        checks=[]
        for kind,ref in [('boundary','reference_S1_boundary'),('final','reference_S1'),('old','reference_S0')]:
            for k in ['x','K','V']:
                a=(p/(s['name']+'_'+kind+'_'+k+'.bin')).read_bytes()
                b=(p/(ref+'_'+k+'.bin')).read_bytes()
                checks.append(dict(tensor=kind+'_'+k,byte_exact=a==b))
        for k in ['raw_bf16','actions']:
            checks.append(dict(tensor='Expert_'+k,byte_exact=(p/(s['name']+'_Expert_'+k+'.bin')).read_bytes()==(p/('reference_S0_'+k+'.bin')).read_bytes()))
        required.append(dict(name=s['name'],role=s['role'],checks=checks,pass_=all(c['byte_exact'] for c in checks)))
    rows=[]
    for s in pair['samples']:
        if s['role']!='normal':continue
        ep=s['GPU_endpoints_ms']; c=s['control']; b=s['Expert_completion_bracket']
        row=dict(name=s['name'],mode=s['mode'],round=int(s['name'].rsplit('_',1)[1]),status=s['status'],
            window_Host_ms=s['window_Host_ms'],prefix_to_Context_ready_Host_ms=s['full_refresh_prefix_to_ready_Host_ms'],
            prefix_Event_ms=s['prefix']['event_ms'],Expert_Event_ms=s['Expert_event_ms'],
            Encoder_B1_Event_ms=s['Encoder_B1_event_ms'],Encoder_B2_Event_ms=s['Encoder_B2_event_ms'],
            Expert_submit_Host_ms=(s['Expert_submit_return_ns']-s['Expert_submit_begin_ns'])/1e6,
            B1_submit_Host_ms=(s['B1_submit_return_ns']-s['B1_submit_begin_ns'])/1e6,
            B1_completion_sync_API_Host_ms=(s['boundary_confirmed_ns']-s['boundary_wait_begin_ns'])/1e6,
            Expert_Host_completion_bracket_width_ms=(b['upper_ns']-b['lower_ns'])/1e6,
            initial_Expert_detection_Host_ms=s['initial_Expert_detection_Host_ns']/1e6,
            retention_submit_Host_ms=s['retention_submit_Host_ns']/1e6,
            return_judgment_Host_ms=c['judgment_Host_ns']/1e6,
            path_choice_Host_ms=c['path_choice_Host_ns']/1e6,
            routing_dependencies_Host_ms=c['routing_dependencies_Host_ns']/1e6,
            judgment_to_B2_submit_begin_Host_ms=c['judgment_through_submit_begin_ns']/1e6,
            judgment_to_B2_submit_return_Host_ms=c['judgment_through_submit_return_ns']/1e6,
            Context_final_sync_Host_ms=s['Context_final_sync_Host_ns']/1e6,
            returned=s['returned'],B1_stream=s['B1_stream'],Expert_stream=s['Expert_stream'],B2_stream=s['B2_stream'],cuda_last_error=s['cuda_last_error'])
        row.update({'GPU_'+k+'_ms':v for k,v in ep.items()})
        row.update(s['GPU_Event_derived']);rows.append(row)
    csvout(base/'NORMAL_SAMPLES.csv',rows)
    numeric=[k for k,v in rows[0].items() if k.endswith('_ms')]
    modes=[]
    for mode in ['serial','ordinary','fixed','return']:
        ss=[s for s in rows if s['mode']==mode]
        row=dict(mode=mode,n=len(ss),all_numerics_PASS=all(x['status']=='PASS' for x in ss))
        for k in numeric:
            vals=[s[k] for s in ss];row[k+'_median']=statistics.median(vals);row[k+'_min']=min(vals);row[k+'_max']=max(vals)
        modes.append(row)
    csvout(base/'MODE_SUMMARY.csv',modes)
    differences=[]
    for i in range(3):
        a=next(x for x in rows if x['mode']=='fixed' and x['round']==i);b=next(x for x in rows if x['mode']=='return' and x['round']==i)
        differences.append(dict(round=i,fixed_minus_return_Host_window_ms=a['window_Host_ms']-b['window_Host_ms'],
            fixed_minus_return_Event_tail_ms=a['Expert_to_Context_tail_ms']-b['Expert_to_Context_tail_ms'],
            fixed_minus_return_B2_Event_ms=a['Encoder_B2_Event_ms']-b['Encoder_B2_Event_ms'],
            note='separate runs, same frozen input and remaining B2; endpoint difference already includes control costs, no second subtraction'))
    csvout(base/'FIXED_RETURN_DIFFERENCES.csv',differences)
    attempts=json.loads((board/'ATTEMPTS.json').read_text());a=attempts[0]
    hw=[json.loads(l) for l in (board/'hardware.jsonl').read_text().splitlines()]
    frequency=assess(hw,read_root_samples(board/'clock.telemetry.jsonl'),a['started_ns'],a['ended_ns'])
    ledger=r['ledger']; enc=[i for x in ledger.values() for v in x.values() for i in v.get('encoder',[])]; dec=[i for x in ledger.values() for v in x.values() for i in v.get('decoder',[])]
    work=dict(actual_Contexts=len(enc)//18,actual_Experts=len(dec)//180,encoder_layer_calls=len(enc),decoder_layer_calls=len(dec),
        preparation=dict(Contexts=3,Experts=3),ordinary_pair_gate=dict(Contexts=1,Experts=1),normal=dict(Contexts=12,Experts=12),
        not_run=dict(Contexts=5,Experts=5,collector_reference=1,diagnostic_pairs=4),SM_probes=2,original_runner_Autotune=2)
    assert len(enc)==16*18 and len(dec)==16*180
    api=pair['resource_API_Host'];csvout(base/'RESOURCE_API_HOST.csv',[dict(**x,duration_ms=(x['end_ns']-x['begin_ns'])/1e6) for x in api])
    activity=board/'pair/activity_trace/activity_start_failure.jsonl'
    ar=[json.loads(l) for l in activity.read_text().splitlines()] if activity.exists() else []
    summary=dict(normal_status='PASS' if all(x['pass_'] for x in required) else 'FAIL',
        integrity=integrity,integrity_PASS=all(x['match'] for x in integrity),required_saved_comparisons=required,
        comparison_count=sum(len(x['checks']) for x in required),recorded_comparisons=len(r['comparisons']),recorded_checks=len(r['checks']),
        all_recorded_checks_PASS=all(x['pass_'] for x in r['checks']),all_recorded_comparisons_exact=all(x['exact'] for x in r['comparisons']),
        cross_process=r['cross_process_comparisons'],historical_intermediates=r['historical_intermediate_diagnostics'],
        attempts=attempts,workload=work,frequency=frequency,
        hardware=dict(samples=len(hw),temp_min_mC=min(x['temp_mC'] for x in hw),temp_max_mC=max(x['temp_mC'] for x in hw),available_min_kB=min(x['MemAvailable_kB'] for x in hw)),
        resource_setup_Host_ms=(pair['one_time_resource_preparation']['end_ns']-pair['one_time_resource_preparation']['begin_ns'])/1e6,
        probe=pair['probes'],resource_interval_overlaps_before=pair['addresses_before']['overlaps'],resource_interval_overlaps_after=pair['addresses_after']['overlaps'],
        cleanup=pair['cleanup'],memory=r['memory'],collector_failed_activity=ar,
        physical_kernel_overlap='UNKNOWN: collection activation failed; no task kernel intervals',
        conclusion='PARTIAL: numerical/normal Event-Host evidence delivered, diagnostic trace blocked; no retry',
        independent_restore=json.loads((board/'INDEPENDENT_RESTORE.json').read_text()))
    (base/'OFFLINE_SAVED_REVIEW.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:summary[k] for k in ['normal_status','integrity_PASS','comparison_count','recorded_checks','recorded_comparisons','frequency','hardware','resource_setup_Host_ms','workload','collector_failed_activity']},indent=2))

if __name__=='__main__':main(sys.argv[1])
