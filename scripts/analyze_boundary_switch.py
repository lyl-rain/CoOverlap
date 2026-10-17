"""Offline Host-clock boundary analysis. Never add cross-stream Event intervals."""
import sys,json,csv,statistics
from pathlib import Path
p=Path(sys.argv[1]);r=json.loads((p/'result.preview.json').read_text());checks={x['name']:x['pass_'] for x in r['checks']};rows=[];groups=[];paired=[]
for s in r['samples']:
 h0,h1,h2,h2end,h3=[s[k] for k in ['B1_submit_before_ns','B1_complete_ack_ns','B2_submit_before_ns','B2_submit_return_ns','B2_complete_ack_ns']]
 assert h0<=h1<=h2<=h2end<=h3
 assert abs(s['Host_gap_ms']-(h2-h1)/1e6)<1e-9
 assert abs(s['Host_tail_ms']-(h3-h1)/1e6)<1e-9
 assert abs(s['Host_response_ms']-(h3-h0)/1e6)<1e-9
 req=['_final_byte_exact','_mid_byte_exact','_18_layers_once','_stream_resources','_memory_floor']
 valid='PASS' if all(checks.get(s['name']+k) is True for k in req) else 'FAIL' if any(checks.get(s['name']+k) is False for k in req) else 'INCOMPLETE'
 rows.append({**s,'validation':valid,'routing':json.dumps(s['routing']),'live_memory':json.dumps(s.get('live_memory'))})
formal=[x for x in rows if x['role']=='formal']
expected=[(m,j) for j,ms in enumerate([['A','B','C'],['B','C','A'],['C','A','B']]) for m in ms]
assert [(s['mode'],s['round']) for s in formal]==expected[:len(formal)]
for mode in ['A','B','C']:
 v=[x for x in formal if x['mode']==mode and x['validation']=='PASS'];g=dict(mode=mode,n_PASS=len(v),requested=3)
 for field in ['Host_gap_ms','Host_tail_ms','Host_response_ms','B1_event_ms','B2_event_ms','B1_cpu_submit_ms','B2_cpu_submit_ms','boundary_retention_Host_ms','boundary_retention_event_ms']:
  a=[x[field] for x in v]
  if a:g[field]=dict(samples=a,median=statistics.median(a),min=min(a),max=max(a))
 groups.append(g)
for j in range(3):
 b=next((s for s in formal if s['mode']=='B' and s['round']==j and s['validation']=='PASS'),None);c=next((s for s in formal if s['mode']=='C' and s['round']==j and s['validation']=='PASS'),None)
 if b and c:paired.append(dict(round=j,B_minus_C_Host_tail_ms=b['Host_tail_ms']-c['Host_tail_ms'],B_minus_C_Host_gap_ms=b['Host_gap_ms']-c['Host_gap_ms'],B_minus_C_Host_response_ms=b['Host_response_ms']-c['Host_response_ms']))
if rows:
 fields=list(dict.fromkeys(k for row in rows for k in row))
 with (p/'samples.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
(p/'SUMMARY.json').write_text(json.dumps(dict(run_status=r['status'],groups=groups,paired_by_formal_round=paired,total_saved_samples=len(rows),formal_count=len(formal),failures=[x for x in r['checks'] if not x['pass_']],claim='sequential boundary-controlled paths only; not Expert overlap/net partition loss'),indent=2)+'\n')
print(json.dumps(groups,indent=2))
