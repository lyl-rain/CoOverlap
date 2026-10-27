"""CPU-only acceptance of a saved clean batch; no retry or hardware access."""
import argparse,csv,hashlib,json,math,mmap,re
from pathlib import Path
from m2_clean_core import protocol,ORDER


def audit(run,out):
    report=json.loads((run/'model/result.json').read_text());checks=[];summary=[]
    def check(ok,name):checks.append(dict(name=name,pass_=bool(ok)))
    check(report['observation_mode']=='performance','normal_observation_mode')
    check(report['status'] in ('PASS','PASS_IN_PROCESS_DEVIATION'),'D1_and_complete_model_status')
    check(report['in_process_equivalence']['byte_exact'],'D1_byte_exact')
    check(report['protocol']==protocol(),'frozen_contract')
    check(report['observed_call_counts']==dict(encoder=720,decoder=12060,language=40,vision27=40),'whole_observed_call_counts')
    cred=json.loads((run/'PREFLIGHT.json').read_text())
    check(report['source_preflight_sha256']==hashlib.sha256((run/'PREFLIGHT.json').read_bytes()).hexdigest(),'credential_fingerprint')
    check(report['source_config_fingerprints']=={k:v['sha256'] for k,v in cred['package'].items()},'source_config_fingerprints')
    scope=json.loads((run/'SCOPE_RESULT.json').read_text());restore=json.loads((run/'INDEPENDENT_RESTORE_READBACK.json').read_text())
    check(scope['status']=='PASS' and scope['restored'],'scope_and_restoration')
    check(restore['status']=='PASS' and restore['independent_uid']!=0,'independent_restore_readback')
    telemetry=json.loads((run/'ROOT_TELEMETRY.json').read_text())
    model_samples=[r for r in telemetry if r.get('phase')=='model'];check(bool(model_samples),'model_hardware_samples_present')
    check(all(all(x['min']==x['max']==x['cur']==x['target'] for x in r['limits']) and r.get('emc_bpmp_status')=='READ' and r.get('emc_bpmp_rate_hz')==3199000000 for r in model_samples),'all_model_sampled_actual_fixed_frequencies')
    segments=report['segments'];check(len(segments)==4,'all_four_segments')
    # Rebuild same-process reference payloads; no process-external numeric gate.
    base=run/'model';refs={}
    for i in (0,1):
        for label,prefix in [('ref','context'),('mid','mid')]:
            refs[label+str(i)]=b''.join((base/('ref'+str(i)+'_'+prefix+'_'+suffix+'.bin')).read_bytes() for suffix in ('x','K','V'))
        refs['raw'+str(i)]=(base/('ref'+str(i)+'_raw.bin')).read_bytes()
    for number,seg in enumerate(segments):
        check(seg['mode']==ORDER[number] and seg['manifest']==protocol()['manifest'],'segment'+str(number)+'_fair_trajectory')
        check(seg['initial_state']==segments[0]['initial_state'],'segment'+str(number)+'_initial_state')
        check(any(seg['t0_ns']<=r['monotonic_ns']<=seg['window_end_ns'] for r in model_samples),'segment'+str(number)+'_hardware_sample_inside_window')
        check(seg['status']=='PASS' and seg['validation']['records']==128,'segment'+str(number)+'_full_validation')
        index_path=base/('segment'+str(number))/'RETENTION_INDEX.json'
        idx=json.loads(index_path.read_text());layout=idx['layout'];claims={x['key']:x for x in idx['claims']}
        check(layout==__import__('m2_clean_core').retention_layout(),'segment'+str(number)+'_exact_capacity_and_index')
        receipts=idx['capture_receipts']
        check(len(receipts)==128 and sorted(map(tuple,receipts))==sorted((e['key'],e['slot'],e['offset'],e['nbytes']) for e in layout['entries']),'segment'+str(number)+'_every_capture_receipt')
        check(len(idx['comparisons'])==128 and all(x['exact'] for x in idx['comparisons']),'segment'+str(number)+'_all_comparison_records')
        payload=index_path.with_name('RETENTION.bin')
        with payload.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
            check(len(data)==layout['nbytes'] and hashlib.sha256(data).hexdigest()==idx['payload_sha256'],'segment'+str(number)+'_full_payload_sha')
            for e in layout['entries']:
                claim=claims[e['key']]
                check(all(claim[k]==e[k] for k in ('job','slot','generation','version','snapshot')),'segment'+str(number)+'_'+e['key']+'_identity')
                view=memoryview(data)[e['offset']:e['offset']+e['nbytes']]
                expected=refs.get(e['expected'])
                check(view==expected if expected is not None else hashlib.sha256(view).hexdigest()==next(c['reference_sha256'] for c in idx['comparisons'] if c['key']==e['key']),
                      'segment'+str(number)+'_'+e['key']+'_full_bytes')
                view.release()
        for key in ('cycle_counts','refresh_counts'):
            check(seg['statistics'][key]['INCOMPLETE']==0,'segment'+str(number)+'_'+key+'_complete')
        rows=seg['statistics']['cycles'];stats=seg['statistics'];metrics=seg['metrics']
        def quantile(field,q):
            vals=[r.get(field) for r in rows]
            return sorted(vals)[math.ceil(len(vals)*q)-1] if all(v is not None for v in vals) else None
        summary.append(dict(segment=number,mode=seg['mode'],configuration=report['configuration']['label'],
            period_ns=240000000,cycles_denominator=16,Expert_denominator=16,VLM_denominator=16,refresh_denominator=8,
            window_elapsed_ns=seg['window_end_ns']-seg['t0_ns'],cycle_PASS=stats['cycle_counts']['PASS'],cycle_FAIL=stats['cycle_counts']['FAIL'],cycle_UNCERTAIN=stats['cycle_counts']['UNCERTAIN'],cycle_INCOMPLETE=stats['cycle_counts']['INCOMPLETE'],
            Expert_PASS=metrics['expert_counts']['PASS'],Expert_FAIL=metrics['expert_counts']['FAIL'],Expert_UNCERTAIN=metrics['expert_counts']['UNCERTAIN'],Expert_INCOMPLETE=metrics['expert_counts']['INCOMPLETE'],
            VLM_PASS=metrics['VLM_counts']['PASS'],VLM_FAIL=metrics['VLM_counts']['FAIL'],VLM_UNCERTAIN=metrics['VLM_counts']['UNCERTAIN'],VLM_INCOMPLETE=metrics['VLM_counts']['INCOMPLETE'],
            refresh_PASS=stats['refresh_counts']['PASS'],refresh_FAIL=stats['refresh_counts']['FAIL'],refresh_UNCERTAIN=stats['refresh_counts']['UNCERTAIN'],refresh_INCOMPLETE=stats['refresh_counts']['INCOMPLETE'],
            miss_ratio_lower=stats['cycle_counts']['miss_ratio_lower'],miss_ratio_upper=stats['cycle_counts']['miss_ratio_upper'],
            cycle_p99_upper_ns=stats['response_upper_p99_ns'],cycle_p999_upper_ns=stats['response_upper_p999_ns'],
            Expert_p99_upper_ns=quantile('expert_response_upper_ns',.99),VLM_p99_upper_ns=quantile('VLM_response_upper_ns',.99),
            longest_definite_misses=metrics['longest_consecutive_definite_misses'],
            W_assigned_on_time=metrics['W_assigned_on_time'],W_completed_in_window=metrics['W_completed_in_window'],
            completed_Experts=metrics['completed_Experts'],completed_units=metrics['completed_units'],published_refreshes=metrics['published_refreshes'],
            backlog_final=stats['backlog'],max_backlog_at_releases=metrics['max_backlog_at_releases'],k_min='NOT_COMPUTABLE',
            retention_D2D_B=974640128,restore_D2D_B=4893696,
            refresh_ready_bounds_and_k='model/segment'+str(number)+'/refreshes.csv',observations='model/segment'+str(number)+'/operations.csv'))
    out.mkdir(exist_ok=False)
    if summary:
        with (out/'SEGMENTS.csv').open('x',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(summary[0]));writer.writeheader();writer.writerows(summary)
    log=(run/'model.log').read_text() if (run/'model.log').exists() else ''
    slot_logs={}
    for slot in (0,1):
        parts=log.split('M2_CLEAN_AUTOTUNE_BEGIN slot='+str(slot),1)
        body=parts[1].split('M2_CLEAN_AUTOTUNE_END slot='+str(slot),1)[0] if len(parts)==2 else ''
        slot_logs[str(slot)]=dict(available=bool(body),candidate_counts=list(map(int,re.findall(r'autotune: tested (\d+) algos',body))),
                                 zero_candidate_requests=body.count('no algorithms found'),algorithm_identity='NOT_DIRECTLY_OBTAINED')
    result=dict(status='PASS' if all(c['pass_'] for c in checks) else 'FAIL_OR_INCOMPLETE',checks=checks,
                autotune=slot_logs,matmul_attempts='not directly measured; current source upper bound 7488; candidate counts reported',
                configuration=report['configuration'],cross_process_report_only=report['cross_process'],
                limits='one process/configuration; 1s hardware samples; no reliable-tail, k_min or B2 claim')
    (out/'AUDIT.json').write_text(json.dumps(result,indent=2));print(result['status'])
    if result['status']!='PASS':raise AssertionError('saved batch acceptance failed')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--run',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();audit(a.run,a.out)

if __name__=='__main__':main()
