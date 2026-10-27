"""Deterministic predictions and recommendations from the real v2 selector."""
import hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
S=HERE.parent/'credible_plan_selector_v2_r1'
sys.path.insert(0,str(S/'cps2'));sys.path.insert(0,str(HERE/'deployment'))
import core
import run as selector
import m3_b10_plan as plan

def fp(d):return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def rows_for(cell,source,kind):
 scen=core.scenario(source,kind);v=core.traj(cell['plan'],scen,cell['period_ns']/1e6);rows=[]
 for e in v['experts']:
  rows.append(dict(job_type='Expert',**e,response_ms=None if e['completion_ms'] is None else round(e['completion_ms']-e['release_ms'],6)))
 for job,comp in v['blocks'].items():
  q,b=[int(x) for x in job[1:].split('/B')];b-=1
  gi=next(i for i,g in enumerate(plan.PLANS[cell['plan']].groups) if b in g)
  release=q*2*cell['period_ns']/1e6;deadline=(2*q+gi+1)*cell['period_ns']/1e6+15
  op=next(x for x in v['operations'] if x['kind']=='block' and x['refresh']==q and x['block']==b)
  rows.append(dict(job_type='ContextBlock',job_id=job,release_ms=release,deadline_ms=deadline,dispatch_ms=op['start'],completion_ms=comp,response_ms=comp-release,margin_ms=deadline-comp,status='PASS' if comp<=deadline else 'FAIL',obligation_group=gi,version=q+1))
 for c in v['cycles']:rows.append(dict(job_type='Cycle',**c,response_ms=None if c['completion_ms'] is None else c['completion_ms']-c['release_ms']))
 for r in v['refreshes']:rows.append(dict(job_type='Refresh',**r,response_ms=None if r['completion_ms'] is None else r['completion_ms']-r['release_ms'],version=int(r['job_id'][7:])+1))
 return dict(period_ms=cell['period_ns']/1e6,plan=cell['plan'],scenario=kind,margins=v['margins'],order=v['order'],rows=rows,complete=v['complete'],status=v['status'])
def build():
 core.integrity.verify_freeze()
 b9=core.measured_cells(core.load(core.B9_RESULT));b8=core.measured_cells(core.load(core.B8_RESULT))
 predictions=dict(schema='m3_b10_prediction_v2',protocol=plan.PROTOCOL,status='PRE_RUN_EXTRAPOLATION_NOT_TARGET_VALIDATION',segments={},segment_mapping={r['id']:r['cell'] for r in plan.RUN},identity=dict(rule_id=plan.RULE_ID,B9_sha256=core.sha256(core.B9_RESULT),delta_ms=3.5,reserve=dict(RE_ms=10.0,RU_ms=10.0,refresh_reserve=False)))
 choices={}
 for ns in plan.BUDGETS:
  cands,choice=selector.evaluate_budget(b9,b8,ns/1e6)
  choices[str(ns)]=dict(choice,candidates={p:{k:c[k] for k in ('G0','G1','G2','G3','ME','MU','MC','MR','accepted','reason')} for p,c in cands.items()})
 for cell in plan.CELLS:
  cases={}
  for src in (180.0,140.0):
   for kind in ('typical','stress'):
    label='%s|b9@%g|%s'%(cell['id'],src,kind)
    cases[label]=dict(rows_for(cell,b9[(cell['plan'],src)],kind),source='b9@%g'%src)
  predictions['segments'][cell['id']]=cases
 predictions['fingerprint']=fp(predictions)
 selection=dict(schema='m3_b10_selection_freeze_v2',protocol=plan.PROTOCOL,rule_id=plan.RULE_ID,reserve_ms=10.0,reserve=dict(RE_ms=10.0,RU_ms=10.0,refresh_reserve=False),delta_ms=3.5,by_period_ns=choices,note='computed by the real selector; fixed matrix does not execute online selection')
 selection['fingerprint']=fp(selection)
 return predictions,selection
def main():
 pred,sel=build()
 for name,d in [('PREDICTION',pred),('SELECTION_FREEZE',sel)]:
  (HERE/'prediction'/ (name+'.json')).write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
 print('prediction job rows:',sum(len(x['rows']) for c in pred['segments'].values() for x in c.values()))
if __name__=='__main__':main()
