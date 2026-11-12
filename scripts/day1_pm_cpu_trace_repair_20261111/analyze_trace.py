"""CPU-only actual kernel unions, independent endpoint overlap and launch attribution."""
import csv,json,sqlite3,sys
from pathlib import Path
from collections import defaultdict
from html import escape

def merge(xs):
 o=[]
 for a,b in sorted(xs):
  if o and a<=o[-1][1]:o[-1][1]=max(o[-1][1],b)
  else:o.append([a,b])
 return o
def length(xs):return sum(b-a for a,b in merge(xs))
def intersect(xs,ys):
 xs=merge(xs);ys=merge(ys);i=j=0;o=[]
 while i<len(xs) and j<len(ys):
  a=max(xs[i][0],ys[j][0]);b=min(xs[i][1],ys[j][1])
  if b>a:o.append((a,b))
  if xs[i][1]<ys[j][1]:i+=1
  else:j+=1
 return o
def sweep(xs,ys):
 endpoints=defaultdict(lambda:[0,0])
 for role,v in enumerate((xs,ys)):
  for a,b in v:endpoints[a][role]+=1;endpoints[b][role]-=1
 counts=[0,0];last=None;total=0
 for t,delta in sorted(endpoints.items()):
  if last is not None and counts[0]>0 and counts[1]>0:total+=t-last
  counts=[a+b for a,b in zip(counts,delta)];last=t
 return total
def write(path,rows):
 if not rows:return
 fields=list(dict.fromkeys(k for r in rows for k in r))
 with path.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def category(name):
 n=name.lower()
 return 'GEMM' if any(x in n for x in ('gemm','gemv','matmul')) else 'Attention' if any(x in n for x in ('flash','attention','splitkv')) else 'LayerNorm' if any(x in n for x in ('layer_norm','layernorm','rms_norm')) else 'Other'
def analyze(root):
 root=Path(root);out=root/'analysis';out.mkdir(exist_ok=True);c=sqlite3.connect('file:'+str(root/'diagnostic.sqlite')+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
 tables={x[0] for x in c.execute('select name from sqlite_master where type="table"')}
 def rows(t):return [dict(x) for x in c.execute('select * from '+t)] if t in tables else []
 strings={x['id']:x['value'] for x in rows('StringIds')}
 nvtx=rows('NVTX_EVENTS')
 for n in nvtx:n['label']=n.get('text') or strings.get(n.get('textId'),'')
 submits=[n for n in nvtx if n['label'].startswith('SUBMIT|') and n.get('end')]
 cycles=[n for n in nvtx if n['label'].startswith(('CYCLE|','SAMPLE|')) and n.get('end')]
 assert submits and cycles,'no captured target NVTX ranges'
 apis=[];corr=defaultdict(list)
 for t in ('CUPTI_ACTIVITY_KIND_RUNTIME','CUPTI_ACTIVITY_KIND_DRIVER'):
  for a in rows(t):
   a['name']=strings.get(a.get('nameId'),'');a['table']=t;apis.append(a)
   if 'Launch' in a['name']:corr[a.get('correlationId')].append(a)
 records=[];other=0;unassigned_inside=[]
 for k in rows('CUPTI_ACTIVITY_KIND_KERNEL'):
  candidates=[]
  for a in corr[k.get('correlationId')]:
   for n in submits:
    if n['start']<=a['start']<n['end'] and a.get('globalTid')==n.get('globalTid'):candidates.append((a,n))
  preferred=[x for x in candidates if x[0]['table'].endswith('RUNTIME')];candidates=preferred or candidates
  if not candidates:
   other+=1
   if any(v['start']<=k['start'] and k['end']<=v['end'] for v in cycles):unassigned_inside.append(dict(start=k['start'],end=k['end'],correlation=k.get('correlationId')))
   continue
  assert len(candidates)==1,('ambiguous target attribution',k,candidates)
  a,n=candidates[0];parents=[v for v in cycles if v['start']<=n['start']<n['end']<=v['end']];assert len(parents)==1,(n,parents)
  sample=parents[0]['label'];name=strings.get(k.get('demangledName')) or strings.get(k.get('mangledName'),'')
  records.append(dict(sample=sample,role=n['label'].split('|')[-1],start_ns=k['start'],end_ns=k['end'],duration_ms=(k['end']-k['start'])/1e6,stream=k['streamId'],Context=k['contextId'],green_Context=k.get('greenContextId'),graphNodeId=k.get('graphNodeId'),correlationId=k.get('correlationId'),API=a['name'],API_start_ns=a['start'],API_end_ns=a['end'],start_minus_API_end_ms=(k['start']-a['end'])/1e6,API_scope='parent graph launch' if k.get('graphNodeId') is not None else 'individual launch',name=name,category=category(name),grid=str([k.get('gridX'),k.get('gridY'),k.get('gridZ')]),block=str([k.get('blockX'),k.get('blockY'),k.get('blockZ')]),shared=k.get('staticSharedMemory',0)+k.get('dynamicSharedMemory',0)))
 assert not unassigned_inside,('unassigned kernels inside target samples',unassigned_inside[:5])
 report=json.loads((root/'run_01/result.json').read_text());assert report['status']=='COMPLETED_SAFE'
 offsets=[];hostspans=defaultdict(list)
 for h in report['spans']:hostspans[h['label']].append(h)
 for label,host in hostspans.items():
  hits=sorted([n for n in nvtx if n['label']==label and n.get('end')],key=lambda n:n['start'])
  if not hits:continue
  assert len(hits)==len(host),('Host/NVTX occurrence mismatch',label,len(hits),len(host))
  for h,n in zip(sorted(host,key=lambda h:h['start_lower']),hits):
   offsets.extend([(n['start']-h['start_upper'],n['start']-h['start_lower']),(n['end']-h['end_upper'],n['end']-h['end_lower'])])
 lo=max(x[0] for x in offsets);hi=min(x[1] for x in offsets);strict_offset=lo<=hi;offset_violation=max(0,lo-hi)
 if not strict_offset:lo=min(x[0] for x in offsets);hi=max(x[1] for x in offsets)
 summary=[];gaps=[];queue=[];copies=rows('CUPTI_ACTIVITY_KIND_MEMCPY');panels=[]
 for parent in cycles:
  label=parent['label'];sel=[k for k in records if k['sample']==label]
  if not sel:continue
  by={role:[(k['start_ns'],k['end_ns']) for k in sel if k['role']==role] for role in ('Expert','VLM')};exp=by['Expert'];vlm=by['VLM'];joint=merge(exp+vlm);over=length(intersect(exp,vlm));assert over==sweep(exp,vlm)
  row=dict(sample=label,profiler=True,kernels=len(sel),overlap_ms=over/1e6,joint_kernel_union_ms=length(joint)/1e6,Host_trace_offset_lower_ns=lo,Host_trace_offset_upper_ns=hi)
  for role,v in by.items():
   kr=[k for k in sel if k['role']==role]
   if not v:continue
   first=min(a for a,b in v);last=max(b for a,b in v)
   row.update({role+'_kernels':len(v),role+'_GPU_first_ms':(first-parent['start'])/1e6,role+'_GPU_last_ms':(last-parent['start'])/1e6,role+'_kernel_union_ms':length(v)/1e6,role+'_envelope_no_target_kernel_ms':(last-first-length(v))/1e6,role+'_first_API_ms':(min(k['API_start_ns'] for k in kr)-parent['start'])/1e6})
   for cat in ('GEMM','Attention','LayerNorm','Other'):row[role+'_'+cat+'_union_ms']=length([(k['start_ns'],k['end_ns']) for k in kr if k['category']==cat])/1e6
   for k in kr:
    if k['start_ns']>k['API_end_ns']:queue.append(dict(sample=label,role=role,start_ns=k['API_end_ns'],end_ns=k['start_ns'],ms=(k['start_ns']-k['API_end_ns'])/1e6,scope=k['API_scope'],name=k['name']))
  if exp and vlm:row['VLM_first_API_minus_Expert_last_kernel_ms']=(min(k['API_start_ns'] for k in sel if k['role']=='VLM')-max(b for a,b in exp))/1e6
  for a,b in zip(joint,joint[1:]):
   following=[k for k in sel if k['start_ns']>=b[0]];first_future=min(k['API_start_ns'] for k in following)
   gaps.append(dict(sample=label,start_ns=a[1],end_ns=b[0],duration_ms=(b[0]-a[1])/1e6,no_future_target_launch_API_started_ms=max(0,min(b[0],first_future)-a[1])/1e6,description='no Expert/VLM target kernel; other kernels/memcpy/engines may be active'))
  submitv=next((n for n in submits if n['label'].endswith('|VLM') and parent['start']<=n['start']<parent['end']),None)
  if submitv:
   ret=submitv['end'];last=max(b for a,b in exp+vlm)
   row.update(VLM_NVTX_return_to_last_kernel_ms=max(0,last-ret)/1e6,kernel_union_after_VLM_NVTX_return_ms=length(intersect(joint,[(ret,last)]))/1e6,after_VLM_return_no_target_kernel_ms=(max(0,last-ret)-length(intersect(joint,[(ret,last)])))/1e6)
   if label.startswith('CYCLE|'):
    _,mode,j=label.split('|');j=int(j);phase=report['phases'][mode];rawrow=phase['record']['rows'][j]
    vh=next(h for h in phase['host_submissions'] if h['key']==rawrow['unit_key']+'/B'+str(j%8))
    row.update(Host_callback_return_to_pair_ms=(rawrow['pair_upper']-vh['end_ns'])/1e6,last_kernel_to_pair_lower_ms=(rawrow['pair_upper']+lo-last)/1e6,last_kernel_to_pair_upper_ms=(rawrow['pair_upper']+hi-last)/1e6)
    pointlo=vh['end_ns']+lo;pointhi=vh['end_ns']+hi
    row['callback_return_after_kernel_union_lower_ms']=length(intersect(joint,[(pointhi,last)]))/1e6;row['callback_return_after_kernel_union_upper_ms']=length(intersect(joint,[(pointlo,last)]))/1e6
    action=next(n for n in nvtx if n['label']==f'ACTION|{mode}|{j}' and n.get('end'))
    row['Host_action_delivery_relative_ms']=(action['end']-parent['start'])/1e6
    row['action_boundary']='NVTX ACTION end, includes wrapper tail; all in trace clock'
    row['last_kernel_to_cycle_NVTX_end_ms']=(parent['end']-last)/1e6
  if label.startswith('SAMPLE|'):
   action=next((n for n in nvtx if n['label']=='ACTION|'+label.split('|',1)[1] and n.get('end')),None)
   if action:row['Host_action_delivery_relative_ms']=(action['end']-parent['start'])/1e6;row['action_boundary']='NVTX ACTION end, includes wrapper tail; trace clock'
  row['last_kernel_to_cycle_NVTX_end_ms']=(parent['end']-max(k['end_ns'] for k in sel))/1e6
  csel=[v for v in copies if parent['start']<=v['start']<parent['end']]
  row['D2H_union_ms']=length([(v['start'],v['end']) for v in csel if v.get('copyKind')==2])/1e6
  summary.append(row);panels.append((parent,sel,row,csel))
 write(out/'kernel_records.csv',records);write(out/'kernel_activity.csv',summary);write(out/'kernel_gaps.csv',gaps);write(out/'queued_intervals.csv',queue)
 write(out/'CUDA_API.csv',[dict(name=a['name'],start_ns=a['start'],end_ns=a['end'],correlationId=a.get('correlationId'),table=a['table'],returnValue=a.get('returnValue')) for a in apis]);write(out/'memcpy.csv',copies)
 diag={t:rows(t) for t in tables if 'DIAGNOSTIC' in t.upper() or 'ERROR' in t.upper()}
 coverage=dict(status='PASS',samples=len(summary),target_kernels=len(records),outside_target_submission_kernels=other,unassigned_inside_target_samples=unassigned_inside,independent_endpoint_overlap_check=True,offset_bounds_ns=[lo,hi],strict_constant_Host_trace_offset=strict_offset,constant_offset_nonintersection_ns=offset_violation,offset_scope='constant-offset interval if feasible; otherwise observed-offset envelope only. Action/cycle NVTX bounds use trace clock without conversion',diagnostics=diag,trace=str(root/'diagnostic.nsys-rep'))
 (out/'coverage.json').write_text(json.dumps(coverage,indent=2))
 plot_span=max([240_000_000]+[max([p['end']]+[k['end_ns'] for k in sel])-p['start'] for p,sel,row,cs in panels])
 svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="'+str(100+270*len(panels))+'">','<rect width="100%" height="100%" fill="white"/>','<text x="24" y="25" font-family="sans-serif" font-size="16">2026-11-11 · Nsight profiler diagnostic · '+escape(root.name)+'</text>','<text x="24" y="48" font-size="12">CPU API = grey · Expert = blue · VLM = green · memcpy = orange · no target kernel does not mean device idle</text>']
 for idx,(parent,sel,row,csel) in enumerate(panels):
  y=85+idx*270;origin=parent['start'];end=max([parent['end']]+[k['end_ns'] for k in sel]);scale=1000/plot_span
  def rect(a,b,yy,color,hh=14):svg.append(f'<rect x="{195+(a-origin)*scale:.3f}" y="{yy}" width="{max(.08,(b-a)*scale):.3f}" height="{hh}" fill="{color}"/>')
  svg.append(f'<rect x="{195+(end-origin)*scale:.3f}" y="{y+8}" width="{max(0,1000-(end-origin)*scale):.3f}" height="153" fill="#f0f2f4"/>')
  svg.append(f'<text x="24" y="{y}" font-size="13">{escape(parent["label"])} overlap={row["overlap_ms"]:.6f} ms</text>')
  for q,name in enumerate(('CPU submit/API','Expert GPU','VLM GPU','Memcpy','Queued target')):svg.append(f'<text x="24" y="{y+30+q*30}" font-size="12">{name}</text>')
  for n in submits:
   if origin<=n['start']<end:rect(n['start'],n['end'],y+10,'#bbd2ec' if n['label'].endswith('|Expert') else '#b6dfcf',6)
  for a in apis:
   if a['table'].endswith('RUNTIME') and origin<=a['start']<end:rect(a['start'],a['end'],y+18,'#89939d',12)
  for k in sel:rect(k['start_ns'],k['end_ns'],y+48 if k['role']=='Expert' else y+78,'#3676bf' if k['role']=='Expert' else '#2e9870')
  for cp in csel:rect(cp['start'],cp['end'],y+108,'#df9b2e')
  for q in queue:
   if q['sample']==parent['label']:rect(q['start_ns'],q['end_ns'],y+138,'#d0dbe5',6)
  if 'Host_action_delivery_relative_ms' in row:
   x=195+row['Host_action_delivery_relative_ms']*1e6*scale;svg.append(f'<line x1="{x}" x2="{x}" y1="{y+10}" y2="{y+160}" stroke="#c34a53"/><text x="{x-30}" y="{y+180}" font-size="11">action delivery</text>')
  for tick in range(6):
   xx=195+tick*200;value=plot_span*tick/5/1e6;svg.append(f'<text x="{xx}" y="{y+210}" font-size="11">{value:.2f} ms</text>')
 svg.append('</svg>');(out/'timeline.svg').write_text('\n'.join(svg));c.close();return summary
if __name__=='__main__':
 for arg in sys.argv[1:]:print(arg,json.dumps(analyze(arg)))
