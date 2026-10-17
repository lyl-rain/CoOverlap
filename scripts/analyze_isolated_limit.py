"""CPU-only same-batch summaries; no historical ratios or Kernel-busy claims."""
from pathlib import Path
import json,csv,statistics,sys
p=Path(sys.argv[1]);r=json.loads((p/'result.preview.json').read_text());checks={v['name']:v['pass_'] for v in r['checks']}
rows=[];summary=[]
for s in r['samples']:
 required=[s['name']+'_full_context_byte_exact',s['name']+'_18_layers'] if s['kind']=='Context' else [s['name']+'_raw_byte_exact',s['name']+'_old_KV_unchanged',s['name']+'_10_steps']
 required += [s['name']+'_resource_still_bound']
 valid='PASS' if all(checks.get(k) is True for k in required) else 'FAIL' if any(checks.get(k) is False for k in required) else 'INCOMPLETE'
 rows.append({**s,'numeric_and_stream_checks':valid,'routing':json.dumps(s.get('routing',{}))})
for cfg in ['full','green8']:
 for kind in ['Context','Expert']:
  v=[x for x in rows if x['config']==cfg and x['kind']==kind and x['role']=='formal']
  item=dict(config=cfg,kind=kind,n_saved=len(v),n_PASS=sum(x['numeric_and_stream_checks']=='PASS' for x in v),requested=3)
  for metric in ['host_response_ms','event_ms','B1_event_ms','B2_event_ms','cpu_submit_ms','cpu_wait_ms','input_prepare_ms']:
   q=[x[metric] for x in v if metric in x and x['numeric_and_stream_checks']=='PASS']
   if q:item[metric]={'samples':q,'median':statistics.median(q),'min':min(q),'max':max(q)}
  summary.append(item)
if rows:
 fields=list(dict.fromkeys(k for row in rows for k in row))
 with (p/'samples.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
(p/'SUMMARY.json').write_text(json.dumps({'run_status':r['status'],'groups':summary,'all_call_counts':{kind:sum(x['kind']==kind for x in rows) for kind in ['Context','Expert']},'failures':[v for v in r['checks'] if not v['pass_']],'physical_all_kernel_SM_verification':'NOT_ACCEPTED_WITHOUT_INDIVIDUAL_OBSERVATIONS'},indent=2)+'\n')
print(json.dumps(summary,indent=2))
