"""Symbolic CPU fixture, not a B10 measurement or GPU correctness result."""
import copy,json,sys
from pathlib import Path
B=Path(__file__).resolve().parents[1];sys.path.insert(0,str(B/'deployment'));sys.path.insert(0,str(B/'analysis'));sys.path.insert(0,str(B.parent/'credible_plan_selector_v2_r1/cps2'))
import m3_b10_plan as plan
import core
from selection_contract import sha

def result():
 source=core.load(core.B9_RESULT);r=copy.deepcopy(source);config=json.loads((B/'deployment/CONFIG.json').read_text());r.update(fixture=True,status=plan.RESULT_STATUS,protocol=config,config_sha256=sha(B/'deployment/CONFIG.json'),segments=[])
 sel=json.loads((B/'prediction/SELECTION_FREEZE.json').read_text());pred=json.loads((B/'prediction/PREDICTION.json').read_text())
 r['selection_freeze']=dict(fingerprint=sel['fingerprint'],reserve_ms=10.0,rule=sel['rule_id'],by_period_ns=sel['by_period_ns']);r['prediction_identity']=dict(path=plan.PREDICTION_PATH,sha256=plan.PREDICTION_SHA256)
 r['source_config_fingerprints']={line.split(None,1)[1]:line.split(None,1)[0] for line in (B/'deployment/DEPLOY_SHA256.txt').read_text().splitlines()}
 costs=core.measured_cells(source)
 for i,c in enumerate(plan.RUN):
  v=core.traj(c['plan'],core.scenario(costs[(c['plan'],180.0)],'typical'),c['period_ns']/1e6);t0=(i+1)*10_000_000_000
  def bounds(t):return [t0+round(t*1e6),t0+round(t*1e6)]
  blocks={str((int(k[1:].split('/B')[0]),int(k.split('/B')[1])-1)):bounds(t) for k,t in v['blocks'].items()}
  units={str((int(k[1:].split('/U')[0]),int(k.split('/U')[1]))):bounds(t) for k,t in v['units'].items()}
  decisions=[]
  for e in v['operations']:
   if e['kind']=='Expert':decisions.append(dict(kind='Expert',id=e['id'],host_ns=t0+round(e['start']*1e6)))
   elif e['kind']=='block':decisions.append(dict(kind='Context',id=e['refresh'],block=e['block'],host_ns=t0+round(e['start']*1e6)))
  record=dict(index=i,cell=c['cell'],candidate=c['cell'],plan=c['plan'],policy=c['policy'],period_ns=c['period_ns'],segment_id=c['id'],status='PASS',protocol=plan.PROTOCOL,manifest=plan.manifest(c['period_ns']),t0_ns=t0,block_plan=plan.PLANS[c['plan']].summary(),selection=sel['by_period_ns'][str(c['period_ns'])],selection_fingerprint=sel['fingerprint'],reserve_ms=10.0,experts={str(j):bounds(e['completion_ms']) for j,e in enumerate(v['experts'])},blocks=blocks,units=units,published={str(q):bounds(e['completion_ms']) for q,e in enumerate(v['refreshes'])},decisions=decisions,journal=[['bind','E%d'%j,j//2] for j in range(8)],validation=dict(pass_=True,persisted=True,payload_B=plan.budget()['layouts'][c['plan']]['nbytes']),fixture=True)
  r['segments'].append(record)
 return r

def not_started(r,index):
 s=r['segments'][index];r['segments'][index]={k:s[k] for k in ('index','cell','plan','policy','period_ns','segment_id','selection','selection_fingerprint','reserve_ms')};r['segments'][index]['status']='NOT_STARTED'
