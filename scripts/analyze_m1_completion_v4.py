"""Offline audit of fixed-cycle obligations, completion bounds and backlog."""
import json,csv,math,sys,statistics
from pathlib import Path
from m1_completion_core_v4 import cycle_rows,counts,classify
from m1_run_identity import require_analysis_user
require_analysis_user()
source=Path(sys.argv[1]);r=json.loads((source/'result.json').read_text());root=source/'offline_analysis';root.mkdir(exist_ok=False)
assert r.get('protocol_id')=='m1_completion_20261016_v4'
allcycles=[];allrefresh=[];allexpert=[];allunits=[];summary=[];obs=[];priority=[]
for seg in r.get('segments',[]):
 if 't0_ns' not in seg:continue
 P=int(seg['P_ms']*1_000_000);t0=seg['t0_ns'];common=dict(segment=seg['id'],P_ms=seg['P_ms'],plan=seg['plan'],interference=seg['interference'],role=r['role'],frequency_condition=seg.get('frequency_condition',{}).get('status','UNKNOWN'))
 cs=cycle_rows(seg)
 if 'cycle_obligations' in seg:assert cs==seg['cycle_obligations']
 for v in cs:allcycles.append(dict(**common,**v))
 for u in seg.get('unit_completions',[]):allunits.append(dict(**common,**u))
 for e in seg['experts']:
  assert e['release_ns']==t0+e['id']*P and e['bound_version']=='v0'
  allexpert.append(dict(**common,**e,response_lower_ms=(e['completion_lower_ns']-e['release_ns'])/1e6,response_upper_ms=(e['completion_observed_ns']-e['release_ns'])/1e6,completion_width_ms=(e['completion_observed_ns']-e['completion_lower_ns'])/1e6,discovery_delay_ms=(e['discovered_ns']-e['release_ns'])/1e6,submit_cpu_ms=e['cpu_submit_ns']/1e6,deadline_status=classify(e['completion_lower_ns'],e['completion_observed_ns'],e['deadline_ns'])))
 for e in seg['experts']:
  blockers=[b for b in seg['blocks'] if b['decision_ns']<=e['release_ns']<b['completion_observed_ns']]
  row=next(v for v in allexpert if v['segment']==seg['id'] and v['id']==e['id'])
  row['boundary_wait_lower_ms']=max([0]+[(b['completion_lower_ns']-e['release_ns'])/1e6 for b in blockers])
  row['boundary_wait_upper_ms']=max([0]+[(b['completion_observed_ns']-e['release_ns'])/1e6 for b in blockers])
  row['boundary_wait_method']='Host release inside active nonpreemptive block envelope; bounds include observation; FIFO queue/retention/submit costs separately'
 for b in seg['blocks']:
  pending=[e['id'] for e in seg['experts'] if e['release_ns']<=b['decision_ns']<e['completion_observed_ns']]
  assert not pending,'Context decision violates released Expert priority'
  priority.append(dict(**common,kind=b['kind'],id=b['id'],pending=pending))
 if seg['status']=='PASS':
  assert len(seg['experts'])==seg['cycles'] and len(seg['refreshes'])==seg['cycles']//2 and len(seg['unit_completions'])==seg['cycles']
  assert [e['id'] for e in seg['experts']]==list(range(seg['cycles']))
 for q in seg['refresh_jobs']:
  rel=q['release_ns'];assert rel==t0+q['id']*2*P
  done=next((x for x in seg['refreshes'] if x['id']==q['id']),None)
  lo=done.get('completion_lower_ns') if done else None;hi=done.get('ready_observed_ns') if done else None
  prior=[v for v in seg['refresh_jobs'] if v['id']<q['id']]
  definite_backlog=0;uncertain_backlog=0
  for prev in prior:
   d=next((x for x in seg['refreshes'] if x['id']==prev['id']),None)
   if not d or d['completion_lower_ns']>rel:definite_backlog+=1
   elif d['ready_observed_ns']>rel:uncertain_backlog+=1
  allrefresh.append(dict(**common,id=q['id'],snapshot=q['snapshot'],release_ns=rel,deadline_ns=q['deadline_ns'],discovered_ns=q.get('discovered_ns'),discovery_delay_ms=(q['discovered_ns']-rel)/1e6 if 'discovered_ns' in q else None,target_refresh_periods=2,response_lower_ms=(lo-rel)/1e6 if lo is not None else None,response_upper_ms=(hi-rel)/1e6 if hi is not None else None,k_observed_lower=math.ceil((lo-rel)/P) if lo is not None else None,k_observed_upper=math.ceil((hi-rel)/P) if hi is not None else None,target_status=classify(lo,hi,q['deadline_ns']),definite_prior_refresh_backlog_at_Q=definite_backlog,uncertain_prior_refresh_backlog_at_Q=uncertain_backlog,status=q['status']))
 for u in seg.get('unit_completions',[]):
  if u['unit']=='B1':
   arm=next(x for x in seg['B1_observation'] if x['id']==u['id'])
   obs.append(dict(**common,id=u['id'],record_cpu_ns=arm['event_record_end_ns']-arm['event_record_begin_ns'],arm_cpu_ns=arm['arm_cpu_ns'],query_cpu_ns=u['query_cpu_ns'],polls=u['polls'],completion_width_ms=(u['completion_observed_ns']-u['completion_lower_ns'])/1e6))
 er=[x for x in allexpert if x['segment']==seg['id']];ob=[x for x in obs if x['segment']==seg['id']]
 summary.append(dict(**common,status=seg['status'],cycle=counts([c['cycle_status'] for c in cs]),Expert=counts([c['expert_status'] for c in cs]),VLM=counts([c['VLM_status'] for c in cs]),expert_response_max_ms=max((e['response_upper_ms'] for e in er),default=None),expert_cpu_submit_median_ms=statistics.median([e['submit_cpu_ms'] for e in er]) if er else None,expert_discovery_max_ms=max((e['discovery_delay_ms'] for e in er),default=None),B1_completion_width_max_ms=max((x['completion_width_ms'] for x in ob),default=None),observer_record_arm_query_cpu_sum_ms=sum(x['record_cpu_ns']+x['arm_cpu_ns']+x['query_cpu_ns'] for x in ob)/1e6,retention_event_sum_ms=sum(x['event_elapsed_ms'] for x in seg['retention'])))
def csvout(name,rows):
 if not rows:return
 keys=list(dict.fromkeys(k for row in rows for k in row))
 with (root/name).open('w') as f:w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
for name,rows in [('cycles.csv',allcycles),('refreshes.csv',allrefresh),('experts.csv',allexpert),('units.csv',allunits),('observer_cost.csv',obs)]:csvout(name,rows)
(root/'SUMMARY.json').write_text(json.dumps(dict(run_status=r['status'],combinations=summary,priority_audit=priority,totals={'experts_completed':len(allexpert),'refreshes_completed':sum(len(s['refreshes']) for s in r.get('segments',[])),'cycles_assigned':len(allcycles)},refreshes=allrefresh,missing_configured_segments=[s for i,s in enumerate(json.loads((source/'protocol.json').read_text())['segments']) if i>=len(r.get('segments',[]))]),indent=2)+'\n')
print(json.dumps(summary,indent=2))
