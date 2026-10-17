"""Offline M1 tables from every completed cell; no pooled tail claims."""
import csv,hashlib,html,json,math,statistics,sys
from pathlib import Path
def put(path,v):path.open('x').write(json.dumps(v,indent=2))
def csvout(path,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('x') as f:w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def main():
    root,out=map(Path,sys.argv[1:3]);out.mkdir(exist_ok=False)
    rows=[];gates=[];progress=[];attempts=json.loads((root/'ATTEMPTS.json').read_text())
    for a in attempts:
        role=a['role'];r=json.loads((root/role/'result.json').read_text());cross=r['cross_process_comparisons']
        gates.append(dict(role=role,exit_code=a['exit_code'],wall_s=a['wall_s'],status=r['status'],script_sha256=a['script_sha256'],cross_bf16_max_abs=cross[0]['max_abs'],cross_bf16_different_elements=cross[0]['mismatch_elements'],cross_action_max_abs=cross[1]['max_abs'],cross_action_different_elements=cross[1]['mismatch_elements'],cross_pass=all(x['pass_'] for x in cross),in_process_all_checks=all(x['pass_'] for x in r['checks']),in_process_all_comparisons=all(x['exact'] and x['finite'] for x in r['comparisons']),runtime_checks=len(r['checks']),runtime_comparisons=len(r['comparisons'])))
        if 'repeat' not in role:continue
        ss=json.loads((root/role/'offline_analysis/SUMMARY.json').read_text())
        for s in r['segments']:
            q=next(x for x in ss['combinations'] if x['segment']==s['id']);rs=[x for x in ss['refreshes'] if x['segment']==s['id']];stats=s['cycle_statistics']
            row=dict(role=role,repeat=int(role[-1]),P_ms=s['P_ms'],plan=s['plan'],interference=s['interference'],status=s['status'],cycles=64,Experts_completed=len(s['experts']),Contexts_completed=len(s['refreshes']),frequency=s['frequency_condition']['status'],cycle_miss=stats['cycle_status']['FAIL'],Expert_miss=stats['expert_status']['FAIL'],VLM_miss=stats['VLM_status']['FAIL'],cycle_uncertain=stats['cycle_status']['UNCERTAIN'],cycle_incomplete=stats['cycle_status']['INCOMPLETE'],longest_cycle_miss=stats['cycle_status']['longest_consecutive_definite_miss'],refresh_miss=s['refresh_statistics']['FAIL'],refresh_denominator=32,refresh_response_max_ms=max(x['response_upper_ms'] for x in rs),k_upper_max=max(x['k_observed_upper'] for x in rs),refresh_backlog_max=max(x['definite_prior_refresh_backlog_at_Q'] for x in rs),refresh_backlog_uncertain_max=max(x['uncertain_prior_refresh_backlog_at_Q'] for x in rs),Expert_response_max_ms=q['expert_response_max_ms'],Expert_submit_median_ms=q['expert_cpu_submit_median_ms'],first_noise_wrapper_ms=s['experts'][0]['input_submit_ns']/1e6,later_noise_wrapper_median_ms=statistics.median(e['input_submit_ns']/1e6 for e in s['experts'][1:]),window_wall_s=(s['timed_window_end_ns']-s['t0_ns'])/1e9,validation_wall_s=s['validation_wall_ns']/1e9)
            for key,v in s['off_window_costs'].items():row['validation_'+key+'_s']=v['ns']/1e9
            rows.append(row)
            P=int(s['P_ms']*1e6);t0=s['t0_ns']
            for j in range(64):
                lo,hi=t0+j*P,t0+(j+1)*P;units=s['unit_completions']
                definite=[u['unit_id'] for u in units if lo<=u['completion_lower_ns'] and u['completion_observed_ns']<hi]
                uncertain=[u['unit_id'] for u in units if u['completion_lower_ns']<hi and u['completion_observed_ns']>=lo and u['unit_id'] not in definite]
                progress.append(dict(role=role,segment=s['id'],P_ms=s['P_ms'],plan=s['plan'],interference=s['interference'],cycle=j,window_start_ns=lo,window_end_ns=hi,unit='one complete B1 or B2; IDs cannot substitute for other obligations',definite_units=definite,completion_window_uncertain_units=uncertain,assigned_unit=f'R{j//2}/'+('B1' if j%2==0 else 'B2')))
    csvout(out/'CELLS.csv',rows);csvout(out/'PROCESS_GATES.csv',gates);csvout(out/'PER_CYCLE_PROGRESS.csv',progress)
    put(out/'CELLS.json',rows);put(out/'PROCESS_GATES.json',gates)
    pair=json.loads((root/'pair/result.json').read_text())['pair'];samples=[dict(s,Event_tail_ms=s['Context_done_GPU_event_since_anchor_ms']-s['Expert_done_GPU_event_since_anchor_ms']) for s in pair['samples'] if s['role']=='formal']
    csvout(out/'PAIR_SAMPLES.csv',samples)
    modes=[]
    for mode in ('serial','ordinary','fixed','return'):
        a=[s for s in samples if s['mode']==mode]
        modes.append(dict(mode=mode,n=len(a),Host_window_median_ms=statistics.median(s['window_Host_ms'] for s in a),Expert_Event_median_ms=statistics.median(s['Expert_event_ms'] for s in a),Event_tail_median_ms=statistics.median(s['Event_tail_ms'] for s in a),boundary_Host_wait_median_ms=statistics.median((s['boundary_confirmed_ns']-s['boundary_wait_begin_ns'])/1e6 for s in a),path_Host_setup_median_ms=statistics.median(s['path_setup_Host_ns']/1e6 for s in a),return_count=sum(s['returned'] for s in a)))
    csvout(out/'PAIR_MODES.csv',modes);put(out/'PAIR_MODES.json',modes)
    diffs=[]
    for j in range(3):
        b=next(x for x in samples if x['mode']=='fixed' and x['name'].endswith('_'+str(j)));c=next(x for x in samples if x['mode']=='return' and x['name'].endswith('_'+str(j)))
        diffs.append(dict(round=j,fixed_minus_return_Host_window_ms=b['window_Host_ms']-c['window_Host_ms'],fixed_minus_return_Event_tail_ms=b['Event_tail_ms']-c['Event_tail_ms'],return_used=c['returned'],warning='separate runs n=3; includes actual control/submission costs; no double subtraction or physical Kernel overlap claim'))
    csvout(out/'PAIR_DIFFERENCES.csv',diffs)
    summaries={a['role']:json.loads((root/a['role']/'result.json').read_text()) for a in attempts}
    full=dict(model_attempts=len(attempts),model_exit_nonzero=sum(a['exit_code']!=0 for a in attempts),formal_cells=len(rows),formal_Experts=sum(x['Experts_completed'] for x in rows),formal_Contexts=sum(x['Contexts_completed'] for x in rows),sequence_timed_Experts=sum(len(s['experts']) for r in summaries.values() for s in r.get('segments',[])),sequence_timed_Contexts=sum(len(s['refreshes']) for r in summaries.values() for s in r.get('segments',[])),pair_formal_Experts=12,pair_formal_Contexts=12,pair_gate_Experts=1,pair_gate_Contexts=1,prep_Experts=18,prep_Contexts=27,Autotune='18 original runner passes, not full jobs',runtime_checks=sum(x['runtime_checks'] for x in gates),runtime_comparisons=sum(x['runtime_comparisons'] for x in gates),in_process_exact=all(x['in_process_all_checks'] and x['in_process_all_comparisons'] for x in gates),cross_absolute=all(x['cross_pass'] for x in gates),frequency_cells={v:sum(x['frequency']==v for x in rows) for v in ['SATISFIED_SAMPLED','NOT_MET','UNKNOWN']},missing_formal_cells=24-len(rows),missing_model_roles=[] if len(attempts)==9 else 'see RUN_PLAN.json')
    put(out/'SUMMARY.json',full)
    # Standalone figure: rates remain separate by budget/plan/repeat, no pooling.
    W,H=1400,950;svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">','<rect width="100%" height="100%" fill="white"/>']
    def text(x,y,s,size=16):svg.append(f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-size="{size}">{html.escape(str(s))}</text>')
    text(35,35,'M1 limited opportunity: single-stream obligations + Encoder-only pairing',24)
    text(35,65,'New protocol, AGX Orin; 64 cycles/cell; Event/Host measurements. Physical paired Kernel overlap UNKNOWN.',16)
    colors={'whole_context':'#3769a3','two_blocks':'#d27b29'}
    for band,P in enumerate((180,240)):
        y0=110+band*260;text(35,y0,f'P=D={P}ms | complete-cycle deadline misses /64 (E + assigned B1/B2)')
        group=[x for x in rows if x['P_ms']==P]
        for j,x in enumerate(sorted(group,key=lambda x:(x['repeat'],x['interference'],x['plan']))):
            xx=60+j*108;hh=x['cycle_miss']*12;yy=y0+145-hh
            svg.append(f'<rect x="{xx}" y="{yy}" width="55" height="{hh}" fill="{colors[x["plan"]]}"/>')
            text(xx,yy-7,x['cycle_miss']);text(xx,y0+170,f'R{x["repeat"]} '+('W' if x['plan']=='whole_context' else 'B'),13);text(xx,y0+190,'mem' if x['interference']!='none' else 'none',12)
        text(35,y0+230,'W=whole_context; B=two_blocks; mem=safe 32MiB CPU11 worker. All repeats remain separate.',14)
    text(35,660,'Pairing: Vision/projector prefix serial; Encoder0-8 /9-17 + full10-step Expert; n=3/mode.',17)
    for i,m in enumerate(modes):
        x=60+330*i;text(x,700,m['mode'],18);text(x,730,f'Host window: {m["Host_window_median_ms"]:.3f}ms');text(x,760,f'Expert Event: {m["Expert_Event_median_ms"]:.3f}ms');text(x,790,f'Event tail: {m["Event_tail_median_ms"]:.3f}ms')
    text(35,850,'Tail = same-anchor Context-done Event minus Expert-done Event; not pure Kernel service or isolated-tail substitution.',14)
    text(35,880,'No stable speedup, reliable p99.9, k_min, route choice or full M1 completion claim. Historical Vision concurrent FAIL retained.',14)
    svg.append('</svg>');(out/'OPPORTUNITY.svg').open('x').write('\n'.join(svg))
if __name__=='__main__':main()
