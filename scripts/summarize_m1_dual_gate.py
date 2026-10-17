"""CPU offline report tables; never pool independent repeats into a claim."""
import json,csv,math,statistics,sys
from pathlib import Path

def main():
    root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(exist_ok=False)
    repeats=[];processes=[];phases=[]
    for role in ('calibration','repeat1','repeat2','repeat3','trace'):
        p=root/role/'result.json'
        if not p.exists():
            processes.append(dict(role=role,status='NOT_RUN_OR_MISSING'))
            if role.startswith('repeat'):
                from m1_completion_core_v3 import formal_configs
                selected=json.loads((root/'SELECTION.json').read_text())
                planned=formal_configs(selected)[int(role[-1])-1]
                repeats.extend(dict(role=role,order=i,**v,status='NOT_RUN') for i,v in enumerate(planned['segments']))
            continue
        r=json.loads(p.read_text());processes.append(dict(role=role,status=r['status'],gate=r.get('gate'),cross=r.get('cross_process_comparisons'),failed_checks=[v for v in r['checks'] if not v['pass_']],runtime_checks=len(r['checks']),exact_comparisons=len(r.get('comparisons',[])),norm_stats_sha256=r.get('norm_stats_sha256'),Expert_static_conditions=r.get('Expert_static_conditions')))
        completed={}
        for line in (root/role/'progress.jsonl').read_text().splitlines():
            v=json.loads(line)
            if v['event']=='segment_validated':completed[v['segment']]=v['host_ns']
        for s in r.get('segments',[]):
            if 't0_ns' in s:
                phases.append(dict(role=role,segment=s['id'],timed_s=(s.get('timed_window_end_ns',s['t0_ns'])-s['t0_ns'])/1e9,post_validation_s=(completed[s['id']]-s['timed_window_end_ns'])/1e9 if s['id'] in completed else None))
        if role not in ('repeat1','repeat2','repeat3'):continue
        config=json.loads((root/(role+'.json')).read_text())
        for i,item in enumerate(config['segments']):
            s=next((x for x in r.get('segments',[]) if x['id']==i),None)
            rec=dict(role=role,order=i,**item,status=s['status'] if s else 'NOT_RUN')
            if s and 'cycle_statistics' in s:
                c=s['cycle_statistics'];e=s['experts'];q=s['refreshes'];P=s['P_ms']*1e6
                rec.update(denominator=c['cycle_status']['denominator'],cycle_fail=c['cycle_status']['FAIL'],cycle_pass=c['cycle_status']['PASS'],cycle_uncertain=c['cycle_status']['UNCERTAIN'],cycle_incomplete=c['cycle_status']['INCOMPLETE'],expert_fail=c['expert_status']['FAIL'],VLM_fail=c['VLM_status']['FAIL'],longest_miss=c['cycle_status']['longest_consecutive_definite_miss'],expert_max_ms=max((v['completion_observed_ns']-v['release_ns'])/1e6 for v in e),refresh_max_ms=max((v['ready_observed_ns']-v['release_ns'])/1e6 for v in q),refresh_miss=s['refresh_statistics']['FAIL'],refresh_denominator=s['refresh_statistics']['denominator'],k_upper_max=max(math.ceil((v['ready_observed_ns']-v['release_ns'])/P) for v in q),frequency=s.get('frequency_condition',{}).get('status','UNKNOWN'))
                analysis=json.loads((root/role/'offline_analysis/SUMMARY.json').read_text());qq=[v for v in analysis['refreshes'] if v['segment']==i]
                rec.update(backlog_max=max(v['definite_prior_refresh_backlog_at_Q'] for v in qq),uncertain_backlog_max=max(v['uncertain_prior_refresh_backlog_at_Q'] for v in qq))
            repeats.append(rec)
    (out/'PROCESS_GATES.json').write_text(json.dumps(processes,indent=2));(out/'PHASE_TIMES.json').write_text(json.dumps(phases,indent=2));(out/'REPEAT_CELLS.json').write_text(json.dumps(repeats,indent=2))
    fields=list(dict.fromkeys(k for v in repeats for k in v))
    with (out/'REPEAT_CELLS.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(repeats)
    lines=['# Three independent repeats: separate counts, no pooling','','|P ms|Plan|Interference|Run|Status / clocks|Cycle misses / N|Expert misses|VLM misses|Uncertain / incomplete|Longest miss|Expert max ms|Refresh max ms|Refresh misses / N|Max observed k|Max backlog|','|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for v in sorted(repeats,key=lambda v:(v['P_ms'],v['plan'],v['interference'],v['role'])):
        if 'denominator' not in v:lines.append(f"|{v['P_ms']}|{v['plan']}|{v['interference']}|{v['role']}|{v['status']}|||||||||||");continue
        lines.append(f"|{v['P_ms']}|{v['plan']}|{v['interference']}|{v['role']}|{v['status']} / {v['frequency']}|{v['cycle_fail']}/{v['denominator']}|{v['expert_fail']}|{v['VLM_fail']}|{v['cycle_uncertain']} / {v['cycle_incomplete']}|{v['longest_miss']}|{v['expert_max_ms']:.3f}|{v['refresh_max_ms']:.3f}|{v['refresh_miss']}/{v['refresh_denominator']}|{v['k_upper_max']}|{v['backlog_max']}|")
    (out/'REPEAT_CELLS.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(processes=[(v['role'],v['status'],v.get('gate')) for v in processes],cells=len(repeats))))
if __name__=='__main__':main()
