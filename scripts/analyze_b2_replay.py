"""Offline finite replay analysis. Host observations and CUDA Event remain separate."""
import argparse,collections,csv,hashlib,json,pathlib,statistics
ap=argparse.ArgumentParser();ap.add_argument('root');a=ap.parse_args();root=pathlib.Path(a.root)
r=json.loads((root/'result.preview.json').read_text());assert r['status']=='PASS' and len(r['segments'])==6
samples=[];refreshes=[];cycles=[];summary=[];audits=[]
for s in r['segments']:
 P=s['P_ms'];period=P*1_000_000;t0=s['t0_ns'];plan=s['plan'];current=[]
 event_index={(v['kind'],v['id']):v for v in s['model_events']}
 for b in s['blocks']:
  ready=[e['id'] for e in s['experts'] if e['release_ns']<=b['decision_ns']<e['completion_observed_ns']]
  audits.append(dict(segment=s['id'],kind=b['kind'],refresh_id=b['id'],decision_ns=b['decision_ns'],unfinished_released_Experts=ready))
  assert not ready,'Context launched with pending released Expert'
 assert [e['id'] for e in s['experts']]==list(range(8))
 for e in s['experts']:
  low,hi=e['completion_lower_ns'],e['completion_observed_ns'];rel=e['release_ns'];deadline=rel+period
  assert rel==t0+e['id']*period and rel<=e['discovered_ns']<=e['submit_start_ns']<=e['submit_end_ns']<=hi
  blockers=[b for b in s['blocks'] if b['decision_ns']<=rel<b['completion_observed_ns']]
  assert len(blockers)<=1
  blocker=blockers[0] if blockers else None
  item=dict(segment=s['id'],P_ms=P,plan=plan,id=e['id'],release_ns=rel,discovered_ns=e['discovered_ns'],submit_start_ns=e['submit_start_ns'],submit_end_ns=e['submit_end_ns'],completion_lower_ns=low,completion_observed_ns=hi,response_lower_ms=(low-rel)/1e6,response_ms=(hi-rel)/1e6,discover_delay_ms=(e['discovered_ns']-rel)/1e6,release_to_submit_ms=(e['submit_start_ns']-rel)/1e6,discovery_to_submit_ms=(e['submit_start_ns']-e['discovered_ns'])/1e6,cpu_submit_ms=e['cpu_submit_ns']/1e6,event_poll_wait_ms=e['cpu_poll_wait_ns']/1e6,completion_uncertainty_ms=(hi-low)/1e6,event_elapsed_ms=event_index['Expert',e['id']]['event_elapsed_ms'],blocking_kind=blocker['kind'] if blocker else 'none',boundary_wait_lower_ms=max(0,(blocker['completion_lower_ns']-rel)/1e6) if blocker else 0,boundary_wait_ms=(blocker['completion_observed_ns']-rel)/1e6 if blocker else 0,miss_observed=hi>deadline,miss_definite=low>deadline,miss_ambiguous=low<=deadline<hi,bound_version=e['bound_version'])
  assert item['bound_version']=='v0';samples.append(item);current.append(item)
 for q in s['refreshes']:
  rel=q['release_ns'];hi=q['ready_observed_ns'];low=q['completion_lower_ns'];assert rel==t0+[0,4][q['id']]*period
  refreshes.append(dict(segment=s['id'],P_ms=P,plan=plan,id=q['id'],release_ns=rel,ready_observed_ns=hi,response_ms=(hi-rel)/1e6,response_lower_ms=(low-rel)/1e6,k_observed=(hi-t0)//period-[0,4][q['id']]+1,k_lower=(low-t0)//period-[0,4][q['id']]+1,snapshot='S1',reader_switch='NOT_TESTED'))
 credits=[]
 for b in s['blocks']:
  units=['B1','B2'] if b['kind']=='Context' else ['B1' if b['kind']=='Block1' else 'B2']
  for unit in units:credits.append(dict(refresh=b['id'],unit=unit,retired_ns=b['completion_observed_ns'],lower_ns=b['completion_lower_ns']))
 for j in range(max(8,max((c['retired_ns']-t0)//period+1 for c in credits))):
  lo,hi=t0+j*period,t0+(j+1)*period;cc=[c for c in credits if lo<=c['retired_ns']<hi]
  cycles.append(dict(segment=s['id'],P_ms=P,plan=plan,cycle=j,start_ns=lo,end_ns=hi,B1_retired_units=sum(c['unit']=='B1' for c in cc),B2_retired_units=sum(c['unit']=='B2' for c in cc),units=json.dumps(cc),periodic_VLM_requirement='NOT_DEFINED',whole_context_credit='both units retired at Context acknowledgement; inner B1 Host finish unobserved'))
 longest=streak=0
 for e in current:streak=streak+1 if e['miss_observed'] else 0;longest=max(longest,streak)
 q=[v for v in refreshes if v['segment']==s['id']]
 summary.append(dict(segment=s['id'],P_ms=P,plan=plan,n=8,misses=sum(v['miss_observed'] for v in current),definite_misses=sum(v['miss_definite'] for v in current),ambiguous_misses=sum(v['miss_ambiguous'] for v in current),longest_consecutive=longest,response_median_ms=statistics.median(v['response_ms'] for v in current),response_max_ms=max(v['response_ms'] for v in current),boundary_wait_max_ms=max(v['boundary_wait_ms'] for v in current),discover_delay_max_ms=max(v['discover_delay_ms'] for v in current),cpu_submit_median_ms=statistics.median(v['cpu_submit_ms'] for v in current),completion_uncertainty_max_ms=max(v['completion_uncertainty_ms'] for v in current),refresh0_ms=q[0]['response_ms'],refresh1_ms=q[1]['response_ms'],refresh_k=[v['k_observed'] for v in q],retention_event_sum_ms=sum(v['event_elapsed_ms'] for v in s['retention']),cycle_miss_rate='NOT_DEFINED',numerical=s['status']))
for name,data in [('expert_samples.csv',samples),('refresh_samples.csv',refreshes),('cycle_progress.csv',cycles),('COMBINATIONS.csv',summary)]:
 with (root/name).open('w') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
(root/'ANALYSIS.json').write_text(json.dumps(dict(summary=summary,priority_audit=audits,totals={'experts':len(samples),'refreshes':len(refreshes)},clock_policy='Host completion acknowledgement upper/lower bounds; CUDA elapsed only durations'),indent=2)+'\n')
print(json.dumps(summary,indent=2))
