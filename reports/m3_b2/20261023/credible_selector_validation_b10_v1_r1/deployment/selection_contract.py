"""CPU-only common contract used by both controller and model entry."""
import hashlib,json
from pathlib import Path
import m3_b10_plan as plan

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def fingerprint(d):return hashlib.sha256(json.dumps({k:v for k,v in d.items() if k!='fingerprint'},sort_keys=True,separators=(',',':')).encode()).hexdigest()
def load_identity(base):
 root=Path(base).resolve().parent
 docs=[]
 for rel,digest,fp in [(plan.SELECTION_PATH,plan.SELECTION_SHA256,plan.SELECTION_FINGERPRINT),(plan.PREDICTION_PATH,plan.PREDICTION_SHA256,plan.PREDICTION_FINGERPRINT)]:
  p=root/rel
  if sha(p)!=digest:raise ValueError('frozen identity SHA changed: '+rel)
  d=json.loads(p.read_text())
  if d.get('protocol')!=plan.PROTOCOL or d.get('fingerprint')!=fp or fingerprint(d)!=fp:raise ValueError('invalid frozen identity: '+rel)
  docs.append(d)
 s,p=docs
 if s.get('reserve_ms')!=plan.RESERVE_MS or s.get('reserve')!={'RE_ms':10.0,'RU_ms':10.0,'refresh_reserve':False} or s.get('rule_id')!=plan.RULE_ID:raise ValueError('selection rule/reserve mismatch')
 if set(s.get('by_period_ns',{}))!={str(x) for x in plan.BUDGETS}:raise ValueError('selection budgets mismatch')
 if s['by_period_ns']!=plan.SELECTION_BY_PERIOD:raise ValueError('selection differs from CONFIG identity')
 if p.get('segment_mapping')!={r['id']:r['cell'] for r in plan.RUN}:raise ValueError('prediction segment mapping mismatch')
 expected=set(c['id'] for c in plan.CELLS)
 if set(p.get('segments',{}))!=expected:raise ValueError('prediction cells mismatch')
 for cell in plan.CELLS:
  cases=p['segments'][cell['id']]
  want={cell['id']+'|b9@'+str(src)+'|'+kind for src in (180,140) for kind in ('typical','stress')}
  if set(cases)!=want:raise ValueError('prediction source/scenario coverage mismatch')
  for case in cases.values():
   rows=case['rows'];blocks=len(plan.PLANS[cell['plan']]);cycles=plan.CYCLES
   keys={(x['job_type'],x['job_id']) for x in rows}
   expected_keys={('Expert','E%d'%j) for j in range(cycles)}|{('Cycle','cycle%d'%j) for j in range(cycles)}|{('Refresh','refresh%d'%q) for q in range(cycles//2)}|{('ContextBlock','R%d/B%d'%(q,b+1)) for q in range(cycles//2) for b in range(blocks)}
   if keys!=expected_keys or len(keys)!=len(rows):raise ValueError('prediction job coverage mismatch')
 return s,p
