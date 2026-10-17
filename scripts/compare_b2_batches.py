"""Offline comparison of two finite actual replay batches. No GPU calls."""
from pathlib import Path
import json,csv,html
root=Path('reports/m1_recovery');out=root/'b2_observation_reverse'
batches=[('forward',root/'b2_observation_retry'),('reverse',out)]
rows=[];by={};runs={}
for name,d in batches:
 r=json.loads((d/'result.preview.json').read_text());a=json.loads((d/'ANALYSIS.json').read_text());runs[name]=r
 assert r['status']=='PASS' and len(r['segments'])==6
 assert all(c['pass_'] for c in r['checks']) and all(c['exact'] and c['finite'] for c in r['comparisons'])
 for st in a['summary']:
  rows.append(dict(batch=name,**st));by[name,st['P_ms'],st['plan']]=st
assert runs['forward']['inputs']==runs['reverse']['inputs']
assert runs['forward']['config']==runs['reverse']['config']
assert runs['forward']['preprocessed_image_sha256']==runs['reverse']['preprocessed_image_sha256']
assert [(s['P_ms'],s['plan']) for s in runs['forward']['segments']][::-1]==[(s['P_ms'],s['plan']) for s in runs['reverse']['segments']]
with (out/'BOTH_BATCHES.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
md=['|P|计划|批次/实际序号|违约/8；最长连续|响应中位/最大 ms|边界阻塞最大 ms|刷新0/1响应 ms|观测k|不确定违约|','|---:|---|---|---|---|---|---|---|---|']
for p in [150,180,240]:
 for plan in ['whole_context','two_blocks']:
  for name in ['forward','reverse']:
   s=by[name,p,plan];md.append(f"|{p}|{plan}|{name}/{s['segment']+1}|{s['misses']}/8；{s['longest_consecutive']}|{s['response_median_ms']:.3f}/{s['response_max_ms']:.3f}|{s['boundary_wait_max_ms']:.3f}|{s['refresh0_ms']:.3f}/{s['refresh1_ms']:.3f}|{s['refresh_k']}|{s['ambiguous_misses']}|")
(out/'COMPARISON_TABLE.md').write_text('\n'.join(md)+'\n')
# Real release/ack timeline, 12 aligned rows. Never infer physical Kernel time.
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1800" viewBox="0 0 1800 1800">','<rect width="1800" height="1800" fill="#fbfcfc"/>','<g font-family="Arial,sans-serif">']
def text(x,y,t,size=13,color='#202830'):svg.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{html.escape(str(t))}</text>')
def line(x,y,u,v,color='#d0d5d9',width=1):svg.append(f'<line x1="{x}" y1="{y}" x2="{u}" y2="{v}" stroke="{color}" stroke-width="{width}"/>')
def bar(x,y,w,h,c):svg.append(f'<rect x="{x}" y="{y}" width="{max(1,w)}" height="{h}" fill="{c}"/>')
def X(ms):return 215+ms/2000*1000
text(25,35,'M1 finite single-stream opportunity: forward vs reverse order',24)
text(25,62,'Host submission -> CUDA Event acknowledgement; black = fixed releases, blue/red = Expert, orange = VLM.',14)
text(25,85,'Red = response exceeds P=D; refresh lines show real release -> ready. NOT physical Kernel busy intervals.',14)
text(25,108,'Each batch: 48 Experts / 12 complete Contexts; BF16 byte-exact checks PASS. No partition/concurrency results.',14)
idx=0
for p in [150,180,240]:
 for plan in ['whole_context','two_blocks']:
  for name in ['forward','reverse']:
   st=by[name,p,plan];s=runs[name]['segments'][st['segment']];t0=s['t0_ns'];y=155+idx*118;idx+=1
   text(22,y+12,f'{p}ms {plan}',14);text(22,y+34,f"{name} order#{st['segment']+1}",13)
   for j in range(9):
    xx=X(j*p);line(xx,y-9,xx,y+82);text(xx-4,y-13,j*p,9)
   for e in s['experts']:
    rel=(e['release_ns']-t0)/1e6;start=(e['submit_start_ns']-t0)/1e6;end=(e['completion_observed_ns']-t0)/1e6
    line(X(rel),y+2,X(start),y+2,'#869ba9',2);bar(X(rel)-2,y,4,4,'#18232c');bar(X(start),y+9,X(end)-X(start),18,'#b73336' if end-rel>p else '#2476a6');text(X(start)+2,y+22,'E'+str(e['id']),9,'white')
   for b in s['blocks']:
    start=(b['host_begin_ns']-t0)/1e6;end=(b['completion_observed_ns']-t0)/1e6
    bar(X(start),y+40,X(end)-X(start),18,'#c87422');text(X(start)+2,y+53,('C' if b['kind']=='Context' else 'B1' if b['kind']=='Block1' else 'B2')+str(b['id']),9,'white')
   for q in s['refreshes']:
    rel=(q['release_ns']-t0)/1e6;end=(q['ready_observed_ns']-t0)/1e6;line(X(rel),y+69,X(end),y+69,'#a96319',2);line(X(end),y+65,X(end),y+73,'#a96319',2)
   text(1230,y+13,f"miss {st['misses']}/8; max E {st['response_max_ms']:.1f}")
   text(1230,y+34,f"wait max {st['boundary_wait_max_ms']:.1f} ms")
   text(1230,y+55,f"R {st['refresh0_ms']:.1f}/{st['refresh1_ms']:.1f}")
   text(1230,y+76,f"k {st['refresh_k']}")
text(25,1600,'Time axis: ms relative to each segment t0. Each row has its own actual release clock; scale is shared.',14)
text(25,1625,'150/180ms: reduced maximum blocking in both batches, with refresh-delay tradeoffs. 240ms: both plans 0/8 misses.',14)
text(25,1650,'Refresh k at 180ms split changed 2,3 -> 2,2. Absolute timing/progress depend on order/device state; no third batch.',14)
text(25,1675,'Inner B1 completion is unobserved in whole_context. D2D retention stays in Host timeline; costs differ by plan.',14)
text(25,1700,'No p99, k_min, stable speedup, full-cycle miss rate or B1/B2 selection claim. Current full-cycle rate NOT_DEFINED.',14)
svg.append('</g></svg>');(out/'OPPORTUNITY_BOTH.svg').write_text('\n'.join(svg))
print('offline cross-batch inputs/config/order and numeric audit PASS; 12 aligned rows')
