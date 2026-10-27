# -*- coding: utf-8 -*-
"""Read-only raw reconstruction and the r1 objective-collision witness."""
import csv,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE/'gap'),str(HERE/'lsg2')]
import inputs,search

def put(name,obj):
    (HERE/name).write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')

rows=[];case=None
for tag,sid in inputs.SEGMENTS:
    _,s=inputs.load(tag,sid);_,extra=inputs.costs(s)
    P=s['period_ns']/1e6;plan=s['plan']
    r=search.replay(plan,P,extra,[],False)
    m=inputs.metrics(plan,P,r)
    actual=[]
    for j in range(8):
        e=s['experts'][str(j)][1];u=s['units'][str((j//2,j%2))][1]
        dl=s['t0_ns']+(j+1)*s['period_ns']+s['manifest']['phase_ns']
        actual.append(dict(cycle=j,E=(dl-e)/1e6,U=(dl-u)/1e6,C=(dl-max(e,u))/1e6,
                           official_status=s['statistics']['cycles'][j]['status']))
    row=dict(segment=tag,segment_id=sid,plan=plan,period_ms=P,
             actual_PASS=sum(x['official_status']=='PASS' for x in actual),
             actual_FAIL=sum(x['official_status']=='FAIL' for x in actual),
             actual_UNCERTAIN=sum(x['official_status']=='UNCERTAIN' for x in actual))
    for lab,f in [('MC','C'),('ME','E'),('MU','U')]:
        row['model_'+lab]=m[lab];row['actual_'+lab]=min(x[f] for x in actual)
        row['res_'+lab]=m[lab]-row['actual_'+lab]
    rows.append(row)
    if sid==inputs.SEGMENTS[0][1]:
        case=dict(segment_id=sid,rows=[dict(actual=a,model=m['cycles'][j]) for j,a in enumerate(actual)],
                  model_events=r.events,model_exact_publications=r.exact_times['publications'],
                  measured_operations=[dict(key=o['key'],lower_ns=o.get('lower_ns'),upper_ns=o.get('upper_ns')) for o in s['operations']])
with (HERE/'outputs/RESIDUALS.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
put('outputs/RESIDUAL_DETAILS.json',case)
_,s=inputs.load(*inputs.SEGMENTS[0]);_,ex=inputs.costs(s);P=s['period_ns']/1e6
w=[]
for prefix in [['I']*11+['C','C','C'],['I']*11+['C','C','E','C']]:
    r=search.replay(s['plan'],P,ex,prefix,True);m=inputs.metrics(s['plan'],P,r)
    w.append(dict(prefix=prefix,legacy_key=search.legacy_state_key(r.search_state),
                  decision_state=r.search_state,exact_completed_experts=r.exact_times['experts'],
                  metrics={k:m[k] for k in ['cycle_fail','expert_fail','refresh_fail','worst_cycle_response','max_refresh_response']}))
put('COLLISION_REGRESSION.json',dict(same_legacy_key=w[0]['legacy_key']==w[1]['legacy_key'],
    history2_has_lower_worst_response=w[1]['metrics']['worst_cycle_response']<w[0]['metrics']['worst_cycle_response'],
    paths=w,note='Proves r1 merging did not preserve objectives; not proof that an A/B improvement was missed. r2 never merges states.'))
print('12 baseline residuals and real objective collision rebuilt')
