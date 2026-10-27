"""Offline only: verify every saved byte, replay ownership journal, report bounds."""
import argparse,ast,csv,hashlib,json,math,mmap,statistics,struct,sys
from pathlib import Path
from collections import Counter
sys.dont_write_bytecode=True

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
 return h.hexdigest()
def stats(a):
 return dict(n=len(a),min=min(a),median=statistics.median(a),max=max(a)) if a else dict(n=0,min=None,median=None,max=None)
def csvwrite(p,rows):
 if not rows:return
 with p.open('x',newline='') as f:
  w=csv.DictWriter(f,fieldnames=sorted({k for row in rows for k in row}));w.writeheader();w.writerows(rows)
def load(p):return json.loads(p.read_text())
ap=argparse.ArgumentParser();ap.add_argument('--board',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
sys.path.insert(0,str(a.board))
from m2_executor import VersionedKV,BLOCKS,DECODER,replay_stats,Snapshot
from m2_clean_core import retention_layout,gate_retention_layout
from m3_b2_core import protocol
a.out.mkdir(exist_ok=False)
checks=[]
def check(v,name):
 checks.append(dict(name=name,pass_=bool(v)))
 if not v:raise AssertionError(name)
b=a.board;run=b/'run_01';model=run/'model';r=load(model/'result.json');mf=load(b/'BOARD_MANIFEST.json')
check(sha(b/'BOARD_MANIFEST.json')=='aa103f067a752844da636c79fa729ac6d8b87bc21d0b8dfeb7c3a620f517d5b3','remote_manifest_sha')
for name,row in mf['files'].items():
 p=b/name;check(p.stat().st_size==row['nbytes'],'backup_size:'+name);check(sha(p)==row['sha256'],'backup_sha:'+name)
check({str(p.relative_to(b)) for p in b.rglob('*') if p.is_file()}==set(mf['files'])|{'BOARD_MANIFEST.json'},'backup_exact_file_set')
for v in mf['protected']:check(sha(b/v['export'])==v['sha256'],'protected_snapshot_export_sha')
check(load(b/'CONFIG.json')==protocol(),'frozen_config')
check(r['config_sha256']==sha(b/'CONFIG.json'),'executed_config_sha')
for line in (b/'DEPLOY_SHA256.txt').read_text().splitlines():
 s,name=line.split('  ',1);check(sha(b/name)==s,'deployed_source:'+name)
for name,digest in r['source_config_fingerprints'].items():check(sha(b/name)==digest,'executed_source_fingerprint:'+name)
check(r['source_preflight_sha256']==sha(run/'PREFLIGHT.json'),'executed_preflight_sha')
check(all(x['pass_'] for x in r['checks']),'all_114_internal_check_records')
check(r['status']=='PASS_IN_PROCESS_PROFILE_ONLY','model_status')
check(r['in_process_equivalence']['byte_exact'],'D1_record')
for suffix,ref in [('context_x','context_x'),('context_K','context_K'),('context_V','context_V'),('raw','raw'),('actions','actions')]:
 check((model/('equivalence_pipeline_'+suffix+'.bin')).read_bytes()==(model/('ref0_'+ref+'.bin')).read_bytes(),'D1_saved_bytes:'+suffix)
expected={}
for slot in (0,1):
 expected['ref'+str(slot)]=b''.join((model/('ref'+str(slot)+'_context_'+k+'.bin')).read_bytes() for k in ('x','K','V'))
 expected['mid'+str(slot)]=b''.join((model/('ref'+str(slot)+'_mid_'+k+'.bin')).read_bytes() for k in ('x','K','V'))
 expected['raw'+str(slot)]=(model/('ref'+str(slot)+'_raw.bin')).read_bytes()
for cross in r['cross_process']:
 slot=0 if 'S0' in cross['name'] else 1
 actual=(model/('ref'+str(slot)+('_raw.bin' if 'raw_bf16' in cross['name'] else '_actions.bin'))).read_bytes()
 historical=(b/'reference'/cross['name']).read_bytes()
 def values(data,bf16):
  return ([struct.unpack('<f',struct.pack('<I',x<<16))[0] for x, in struct.iter_unpack('<H',data)] if bf16 else [x for x, in struct.iter_unpack('<f',data)])
 aa=values(actual,'raw_bf16' in cross['name']);bb=values(historical,'raw_bf16' in cross['name'])
 maximum=max(abs(x-y) for x,y in zip(aa,bb))
 check(all(math.isfinite(x) for x in aa+bb),'cross_process_finite:'+cross['name'])
 check(math.isclose(maximum,cross['max_abs'],rel_tol=0,abs_tol=1e-12),'cross_process_original_metric:'+cross['name'])
 threshold=0.015625 if 'raw_bf16' in cross['name'] else 0.01
 check(cross['threshold']==threshold and cross['pass_']==(maximum<=threshold),'cross_process_report_only_definition:'+cross['name'])
 check(not r['cross_process_gate']['admission'],'D1_not_cross_process_admission')
snaps=[Snapshot(**s) for s in r['snapshots']]
image_sha=load(b/'reference/MANIFEST.json')['preprocessed_image_sha256']
class Event:
 def __init__(self):self.done=False
 def query(self):return self.done

def journal_verify(rows):
 m=VersionedKV();pending={};read={}
 for x in rows:
  kind=x[0]
  if kind=='begin':
   h=m.begin(x[2],snaps[x[2]]);check((h.version,h.generation)==(x[1],x[3]),'journal_begin_generation')
  elif kind=='block_submit':
   h=m.versions[x[1]];e=Event();pending[x[1]]=e;m.submit_block(h,x[2],m.get(h).snapshot,BLOCKS[x[2]],e)
  elif kind=='block_done':pending[x[1]].done=True;check(m.poll_block(m.versions[x[1]]),'journal_block_event')
  elif kind=='publish':m.publish(m.versions[x[1]])
  elif kind=='bind':check(m.bind(x[1],snaps[0].noise_sha,version=x[2]).version==x[2],'journal_binding')
  elif kind=='expert_submit':
   e=Event();read[x[1]]=e;m.submit_expert(x[1],m.readers[x[1]].handle,DECODER,e);check(x[3]==180,'journal_180_calls')
  elif kind=='expert_done':read[x[1]].done=True;check(m.poll_expert(x[1]),'journal_reader_event_release')
  elif kind=='cancel_unsubmitted':m.cancel_unsubmitted(x[1])
  elif kind=='reclaim':m.reclaim(m.versions[x[1]])
  else:raise AssertionError('unknown journal row '+repr(x))
 check([list(x) for x in m.journal]==rows,'journal_exact_semantic_replay')
 return m
banks=['gate0','interrupt_gate0','segment0','segment1'];allops=[];retchecks=[];payload=0
for bank in banks:
 path=model/bank;idx=load(path/'RETENTION_INDEX.json');layout=idx['layout'];blob=path/'RETENTION.bin'
 want=gate_retention_layout() if 'gate' in bank else retention_layout(4)
 check(layout==want,'retention_layout:'+bank);check(blob.stat().st_size==layout['nbytes'],'payload_size:'+bank)
 check(sha(blob)==idx['payload_sha256'],'payload_sha:'+bank);payload+=layout['nbytes']
 claims={x['key']:x for x in idx['claims']};comp={x['key']:x for x in idx['comparisons']}
 check(len(claims)==len(idx['claims'])==layout['count'],'all_unique_claims:'+bank)
 check(len(comp)==layout['count'],'all_comparisons:'+bank)
 check({tuple(x) for x in idx['capture_receipts']}=={(e['key'],e['slot'],e['offset'],e['nbytes']) for e in layout['entries']},'capture_receipts:'+bank)
 with blob.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm:
  view=memoryview(mm)
  for e in layout['entries']:
   v=view[e['offset']:e['offset']+e['nbytes']];digest=hashlib.sha256(v).hexdigest();c=claims[e['key']];z=comp[e['key']]
   check(all(c[k]==e[k] for k in ('key','job','slot','version','generation','snapshot')),'claim_identity:'+bank+'/'+e['key'])
   check(c['copied'] and c['state_sha']==snaps[e['slot']].state_sha and c['noise_sha']==snaps[e['slot']].noise_sha,'claim_copy_inputs:'+bank+'/'+e['key'])
   if e['shape']=='images':equal=digest==image_sha
   elif e['shape']=='noise':equal=digest==snaps[e['slot']].noise_sha
   else:equal=v==expected[e['expected']]
   check(equal,'complete_payload_exact:'+bank+'/'+e['key'])
   check(z['exact'] and z['sha256']==digest,'saved_comparison_matches:'+bank+'/'+e['key'])
   if e['shape']=='raw':
    vals=[struct.unpack('<f',struct.pack('<I',n<<16))[0] for n, in struct.iter_unpack('<H',v)]
    check(len(vals)==1600 and all(math.isfinite(x) for x in vals),'full_1600_raw_finite:'+bank+'/'+e['key'])
    check(z['actions_exact'] and z['actions_sha256']==sha(model/('ref'+str(e['slot'])+'_actions.bin')),'full_action_reference_sha:'+bank+'/'+e['key'])
   retchecks.append(dict(bank=bank,key=e['key'],nbytes=e['nbytes'],slot=e['slot'],version=e['version'],generation=e['generation'],sha256=digest,exact=True))
   v.release()
  view.release()
 check(idx['call_sequence_pass'] and all(c['exact'] for c in idx['comparisons']),'internal_sequence_numerical:'+bank)
 for op in idx['operations']:
  check(op['completed'] and op['gpu_event_confirmed'],'actual_tail_confirmed:'+bank+'/'+op['key'])
  check(op['last_false_or_record_begin_host_ns']<=op['first_true_query_before_host_ns']<=op['first_true_query_after_host_ns']<=op['gpu_done_observed_host_ns']<=op['host_finalization_upper_ns'],'completion_timing_order:'+bank+'/'+op['key'])
  check(op['gpu_completion_lower_host_ns']<=op['gpu_completion_upper_host_ns'] and op['host_finalization_lower_ns']<=op['host_finalization_upper_ns'],'separate_Host_GPU_intervals:'+bank+'/'+op['key'])
  allops.append(dict(bank=bank,**op))
 role='interrupt_gate' if bank=='interrupt_gate0' else 'gate' if bank=='gate0' else None
 if role:
  g=r[role];journal_verify(g['journal']);check(len(g['journal'])==(20 if role=='interrupt_gate' else 18),'gate_journal_count:'+role)
  seq=[(x[0],x[1:]) for x in g['journal']]
  b1=next(i for i,x in enumerate(g['journal']) if x[:3]==['block_done',1,0]);b2=next(i for i,x in enumerate(g['journal']) if x[:3]==['block_submit',1,1]);ee=next(i for i,x in enumerate(g['journal']) if x[:2]==['expert_done','E0'])
  check((b1<ee<b2) if role=='interrupt_gate' else ee>b2,'manual_vs_old_reader_order:'+role)
check(len(retchecks)==88 and payload==680414464,'full_retention_88_payload')
check(sum(x['kind']=='stage' for x in allops)==6 and len(allops)==28,'all_6_stages_28_operations_real_event')
counts=dict(Counter(x[2] for x in r['call_ledger']));check(counts==dict(encoder=216,decoder=2160,language=12,vision27=12) and len(r['call_ledger'])==2400,'complete_observed_work_2400')
segments=[];control=[];boundary=[];arrivals=[];operations=[]
for s in r['segments']:
 n=s['index'];conf=s['manifest'];t0=s['t0_ns'];journal_verify(s['journal'])
 check(conf==r['protocol']['manifest'],'fair_fixed_manifest:'+str(n));check(s['initial_state']==r['segments'][0]['initial_state'],'same_initial_state:'+str(n))
 check([x[2] for x in s['journal'] if x[0]=='bind']==[0,0,1,1],'fixed_consumption_vq:'+str(n))
 es={int(k):tuple(v) for k,v in s['experts'].items()};us={ast.literal_eval(k):tuple(v) for k,v in s['units'].items()};pubs={int(k):tuple(v) for k,v in s['published'].items()}
 new=replay_stats(conf,es,us,pubs,t0)
 for k in ('cycle_counts','refresh_counts','response_upper_p99_ns','response_upper_p999_ns','k_min','backlog'):check(new[k]==s['statistics'][k],'recomputed_'+k+':'+str(n))
 for aa,bb in zip(new['cycles'],s['statistics']['cycles']):check(all(bb[k]==v for k,v in aa.items()),'recomputed_cycle:'+str(n)+'/'+str(aa['cycle']))
 for aa,bb in zip(new['refreshes'],s['statistics']['refreshes']):check(aa==bb,'recomputed_refresh:'+str(n)+'/'+str(aa['id']))
 for d in s['decisions']:
  if d['kind']!='idle_until_arrival':check(d['host_ns']>=d['release_ns'],'not_before_release:'+str(n)+'/'+str(d.get('id')))
  prev=max(x['host_ns'] for x in s['progress'] if x['host_ns']<=d['host_ns'])
  if d['kind']!='idle_until_arrival':
   control.append(dict(segment=n,policy=s['mode'],kind=d['kind'],id=d['id'],block=d.get('block'),iteration_to_decision_us=(d['host_ns']-prev)/1000,decision_host_ns=d['host_ns']))
 for op in s['operations']:
  operations.append(dict(segment=n,policy=s['mode'],key=op['key'],kind=op['kind'],
   math_submit_Host_ms=(op['math_submit_return_host_ns']-op['math_submit_begin_host_ns'])/1e6 if 'math_submit_return_host_ns' in op else None,
   wait_first_true_Host_ms=(op['first_true_query_after_host_ns']-op['event_wait_begin_host_ns'])/1e6,
   post_first_true_Host_us=(op['host_finalization_upper_ns']-op['first_true_query_after_host_ns'])/1000,
   GPU_completion_bracket_us=(op['first_true_query_after_host_ns']-op['last_false_or_record_begin_host_ns'])/1000,
   stored_last_confirmation_bracket_us=(op['gpu_completion_upper_host_ns']-op['gpu_completion_lower_host_ns'])/1000,
   polls=op['event_poll_count'],GPU_total_envelope_ms=op['GPU_total_envelope_ms'],
   GPU_pre_D2D_ms=op['GPU_pre_D2D_envelope_ms'],GPU_math_ms=op.get('GPU_math_envelope_ms'),GPU_post_retention_ms=op.get('GPU_post_retention_envelope_ms')))
 for q in (0,1):
  b1=next(x for x in s['operations'] if x['key']=='R'+str(q)+'/B1');b2=next(x for x in s['operations'] if x['key']=='R'+str(q)+'/B2');st=next(x for x in s['operations'] if x['key']=='R'+str(q)+'/stage');d=next(x for x in s['decisions'] if x['kind']=='Context' and x['id']==q and x['block']==1)
  boundary.append(dict(segment=n,policy=s['mode'],refresh=q,
   B1_Host_ack_to_B2_decision_us=(d['host_ns']-b1['upper_ns'])/1000,
   decision_to_operation_submit_us=(b2['operation_submit_begin_host_ns']-d['host_ns'])/1000,
   B1_Host_ack_to_B2_math_submit_us=(b2['math_submit_begin_host_ns']-b1['upper_ns'])/1000,
   stage_Host_ack_to_B1_operation_submit_us=(b1['operation_submit_begin_host_ns']-st['upper_ns'])/1000,
   publication_Host_us=(pubs[q][1]-pubs[q][0])/1000,
   Context_release_to_stage_start_ms=(st['operation_submit_begin_host_ns']-(t0+2*q*240000000))/1e6))
 natural_inside=uncertain=version_wait=multiple_queue=0
 for e in conf['experts']:
  rel=t0+e['release_ns'];d=next(x for x in s['decisions'] if x['kind']=='Expert' and x['id']==e['id'])
  occupied=[];ambiguous=[]
  for op in s['operations']:
   if op['kind']=='Expert':continue
   if op['operation_submit_begin_host_ns']<=rel<op['last_false_or_record_begin_host_ns']:occupied.append(op['key'])
   elif op['operation_submit_begin_host_ns']<=rel<=op['first_true_query_after_host_ns']:ambiguous.append(op['key'])
  natural_inside+=bool(occupied);uncertain+=bool(ambiguous)
  v=e['version'];version_ready=t0-1 if v==0 else pubs[v-1][1]
  version_wait+=version_ready>rel
  previous=[j for j,iv in es.items() if j<e['id'] and iv[1]>rel]
  multiple_queue+=bool(previous)
  arrivals.append(dict(segment=n,policy=s['mode'],expert=e['id'],release_ns=rel,dispatch_ns=d['host_ns'],
   release_to_dispatch_us=(d['host_ns']-rel)/1000,active_Context_block=';'.join(occupied),uncertain_Context_overlap=';'.join(ambiguous),
   version_ready_before_release=version_ready<=rel,earlier_unfinished_Experts=';'.join(map(str,previous)),
   boundary_blocking='NOT_OBSERVED' if not occupied and not ambiguous else 'OBSERVED'))
 segments.append(dict(index=n,policy=s['mode'],cycle_counts=s['statistics']['cycle_counts'],expert_counts=s['metrics']['expert_counts'],VLM_counts=s['metrics']['VLM_counts'],refresh_counts=s['statistics']['refresh_counts'],
  cycle_upper_max_ms=max(x['response_upper_ns'] for x in s['statistics']['cycles'])/1e6,
  expert_upper_max_ms=max(x['expert_response_upper_ns'] for x in s['statistics']['cycles'])/1e6,
  refresh_lower_ms=[x['ready_lower_ns']/1e6 for x in s['statistics']['refreshes']],refresh_upper_ms=[x['ready_upper_ns']/1e6 for x in s['statistics']['refreshes']],
  k=[x['k_upper'] for x in s['statistics']['refreshes']],W_assigned=s['metrics']['W_assigned_on_time'],W_physical=s['metrics']['W_completed_in_window'],
  final_backlog=s['statistics']['backlog'],max_release_backlog=s['metrics']['max_backlog_at_releases'],
  natural_Context_inside_arrivals=natural_inside,uncertain_overlap_arrivals=uncertain,
  version_dependency_wait_scenarios=version_wait,earlier_unfinished_Expert_scenarios=multiple_queue,
  window_elapsed_ms=(s['window_end_ns']-t0)/1e6,k_min=None))
profiles=[];layers=[]
for p in r['profiles']:
 check(p['complete'] and len(p['encoder_layers_event_ms'])==18,'complete_profile:'+str(p['index']))
 role='window' if p['key'].startswith('segment') and '/bootstrap' not in p['key'] else 'bootstrap' if '/bootstrap' in p['key'] else 'intrusive_gate'
 profiles.append(dict(index=p['index'],key=p['key'],slot=p['slot'],role=role,**p['event_envelopes_ms']))
 for i,v in enumerate(p['encoder_layers_event_ms']):layers.append(dict(profile=p['index'],key=p['key'],role=role,layer=i,event_ms=v))
check(len(profiles)==10 and sum(p['role']=='window' for p in profiles)==4,'exact_ten_profiles')
log=(run/'model.log').read_text();import re
matches=re.findall(r'autotune: tested (\d+) algos, best=(\d+) \(([^ ]+) us\)',log)
check(len(matches)==36,'autotune_36_requests');tunes=[dict(request=i+1,slot=i//18,slot_request=i%18+1,candidates=int(x[0]),best_candidate=int(x[1]),best_us=float(x[2])) for i,x in enumerate(matches)]
scope=load(run/'SCOPE_RESULT.json');restore=load(run/'INDEPENDENT_RESTORE_READBACK.json');residual=load(run/'NO_RESIDUAL.json');tele=load(run/'ROOT_TELEMETRY.json')
check(scope['status']=='PASS' and scope['restored'],'scope_restore_pass');check(restore['status']=='PASS' and restore['independent_uid']==1001,'independent_restore_uid');check(residual['status']=='PASS' and not residual['residual'],'no_residual')
check((run/'SCOPE_ATTEMPT_USED').is_dir() and (run/'MODEL_ATTEMPT_USED').is_dir(),'single_attempt_claims')
for row in tele:
 check(all(x['min']==x['max']==x['cur']==x['target'] for x in row['limits']),'telemetry_all_five_fixed')
 check(row['emc_bpmp_rate_hz']==3199000000 and row['temp_mC']<80000 and row['MemAvailable_B']>=12*1024**3,'telemetry_safety')
j=(run/'SERVICE_JOURNAL.txt').read_text();apply=[];rest=[];readback=[]
for line in j.splitlines():
 pos=line.find('{')
 if pos<0:continue
 try:d=json.loads(line[pos:])
 except ValueError:continue
 if d.get('event')=='MIN_WRITE_BEGIN':(apply if d['phase']=='apply' else rest).append(d)
 if d.get('event')=='MIN_READBACK_PASS':readback.append(d)
check(len(apply)==5 and len(rest)==5 and len(readback)==10,'exact_5_apply_5_restore_10_readback')
old=load(run/'CLOCK_BEFORE_EXPORT.json');check(sha(run/'CLOCK_BEFORE_EXPORT.json')==load(run/'ROOT_EVIDENCE_EXPORT.json')['source_sha256'],'root_snapshot_sha')
for oldnode,after in zip(old['nodes'],restore['nodes']):check(oldnode['path']==after['path'] and oldnode['min']==after['min'],'restored_true_snapshot')
summary=dict(status='PASS_LIMITED_CORRECTNESS_AND_PROFILING',internal_checks=dict(records=len(r['checks']),failures=0),offline_check_records=len(checks),
 backup=dict(files=mf['total_files'],bytes=mf['total_bytes'],files_with_manifest=mf['total_files']+1,bytes_with_manifest=mf['total_bytes']+(b/'BOARD_MANIFEST.json').stat().st_size,manifest_sha256=sha(b/'BOARD_MANIFEST.json'),protected=mf['protected']),
 model_elapsed_s=r['elapsed_s'],scope_elapsed_s=scope['elapsed_s'],configuration=r['configuration'],cross_process=r['cross_process'],
 retention=dict(entries=len(retchecks),payload_B=payload,raw_outputs=10,all_bytes_exact=True,actions_internal_full_checks=True,offline_actions='reference SHA consistency; no independent unnormalization recomputation',stages_with_actual_event=6,completed_operations=28),
 explicit_work=protocol()['explicit_work'],observed_counts=counts,segments=segments,
 profile_window_summary={k:stats([p[k] for p in profiles if p['role']=='window']) for k in r['profiles'][0]['event_envelopes_ms']},
 operation_window_summary={kind:{key:stats([p[key] for p in operations if p['kind']==kind and p[key] is not None]) for key in ('math_submit_Host_ms','wait_first_true_Host_ms','post_first_true_Host_us','GPU_completion_bracket_us','polls','GPU_total_envelope_ms','GPU_pre_D2D_ms','GPU_math_ms','GPU_post_retention_ms')} for kind in ('stage','B1','B2','Expert')},
 boundary_summary={k:stats([p[k] for p in boundary]) for k in boundary[0] if k not in ('segment','policy','refresh')},
 dispatch_summary={kind:stats([p['iteration_to_decision_us'] for p in control if p['kind']==kind]) for kind in ('stage','Context','Expert')},
 release_to_dispatch_us=stats([p['release_to_dispatch_us'] for p in arrivals]),
 telemetry=dict(samples=len(tele),model_samples=sum(x['phase']=='model' for x in tele),maximum_temp_mC=max(x['temp_mC'] for x in tele),minimum_MemAvailable_B=min(x['MemAvailable_B'] for x in tele),
  samples_per_window=[sum(s['t0_ns']<=x.get('monotonic_ns',-1)<=s['window_end_ns'] for x in tele) for s in r['segments']]),
 autotune=dict(requests=len(tunes),candidate_rows=sum(x['candidates'] for x in tunes),algorithm_identity='NOT_OBTAINED'),
 caveats=['finite diagnostic; no net benefit/reliable tail/k_min/final split','natural Context blocking NOT_OBSERVED; do not substitute zero','manual interleaving gate intrusive; not natural policy coverage','Event envelopes include instrumentation/Host submission gaps','Vision and projection remain unpreemptible'],
 checks=checks)
for name,data in [('OFFLINE_ACCEPTANCE.json',summary)]: (a.out/name).write_text(json.dumps(data,indent=2)+'\n')
for name,rows in [('RETENTION_AUDIT.csv',retchecks),('PROFILE_BLOCKS.csv',profiles),('PROFILE_LAYERS.csv',layers),('CONTROL_COSTS.csv',control),('BOUNDARY_COSTS.csv',boundary),('OPERATION_COSTS.csv',operations),('NATURAL_ARRIVALS.csv',arrivals),('AUTOTUNE.csv',tunes),('ALL_OPERATIONS.csv',allops)]:csvwrite(a.out/name,rows)
print(json.dumps({k:v for k,v in summary.items() if k in ('status','internal_checks','offline_check_records','backup','segments','profile_window_summary','boundary_summary','dispatch_summary','release_to_dispatch_us','telemetry')},indent=2))
