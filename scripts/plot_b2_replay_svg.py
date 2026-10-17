"""Static SVG of real Host release/ack observations, never Kernel busy time."""
import html,json,pathlib
root=pathlib.Path('reports/m1_recovery/b2_observation_retry');r=json.loads((root/'result.preview.json').read_text());a=json.loads((root/'ANALYSIS.json').read_text())
W,H=1450,1450;left,right=200,1220;xmax=1920
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">','<rect width="100%" height="100%" fill="#fbfcfc"/>','<g font-family="Arial, sans-serif" fill="#17202a">']
def txt(x,y,s,size=14,color='#17202a'):svg.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{html.escape(str(s))}</text>')
def line(x1,y1,x2,y2,color,width=1,dash=None):svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"'+(f' stroke-dasharray="{dash}"' if dash else '')+'/>')
def X(ms):return left+ms/xmax*(right-left)
def bar(x1,x2,y,h,color):svg.append(f'<rect x="{x1}" y="{y}" width="{max(1,x2-x1)}" height="{h}" rx="2" fill="{color}"/>')
txt(30,38,'M1: short single-stream boundary opportunity observation',25)
txt(30,66,'48 Experts + 12 complete Context refreshes; all fixed BF16 output / KV checks PASS.',16)
txt(30,91,'Bars = Host submission to CUDA Event completion acknowledgement. Not physical GPU Kernel intervals.',14,'#626567')
txt(30,115,'8 Expert releases/row; refreshes released at r0 and r4. Blue E, orange Context/B1/B2, red response exceeds D=P.',14)
for s,stats in zip(r['segments'],a['summary']):
 y=160+s['id']*125;t0=s['t0_ns'];P=s['P_ms'];plan=s['plan'];txt(28,y+16,f'{P} ms',20);txt(28,y+38,plan,14);txt(28,y+61,f"Expert miss {stats['misses']}/8",14,'#b03a2e' if stats['misses'] else '#2471a3')
 txt(28,y+82,'E / refresh',12,'#626567')
 for j in range(9):
  xx=X(j*P);line(xx,y-8,xx,y+86,'#d5d8dc',1,'3,4');txt(xx-7,y-14,f'{j*P}',11,'#626567')
 for e in s['experts']:
  rel=(e['release_ns']-t0)/1e6;start=(e['submit_start_ns']-t0)/1e6;end=(e['completion_observed_ns']-t0)/1e6;miss=end-rel>P
  line(X(rel),y+7,X(start),y+7,'#b03a2e' if start-rel>0.5 else '#85c1e9',2)
  svg.append(f'<circle cx="{X(rel)}" cy="{y+7}" r="3" fill="#17202a"/>')
  bar(X(start),X(end),y+15,18,'#b03a2e' if miss else '#2471a3');txt(X(start)+3,y+28,'E'+str(e['id']),10,'white')
 for b in s['blocks']:
  start=(b['host_begin_ns']-t0)/1e6;end=(b['completion_observed_ns']-t0)/1e6
  bar(X(start),X(end),y+49,18,'#ca6f1e');txt(X(start)+2,y+62,('C' if b['kind']=='Context' else 'B1' if b['kind']=='Block1' else 'B2')+str(b['id']),10,'white')
 for q in s['refreshes']:
  rel=(q['release_ns']-t0)/1e6;done=(q['ready_observed_ns']-t0)/1e6
  line(X(rel),y+76,X(done),y+76,'#ca6f1e',2);line(X(done),y+71,X(done),y+81,'#ca6f1e',2)
 txt(1234,y+22,f"max E {stats['response_max_ms']:.1f} ms",12)
 txt(1234,y+44,f"wait max {stats['boundary_wait_max_ms']:.1f}",12)
 txt(1234,y+66,'refresh k '+','.join(str(v) for v in stats['refresh_k']),12)
 txt(1234,y+86,f"R: {stats['refresh0_ms']:.1f}/{stats['refresh1_ms']:.1f}",12)
txt(200,930,'ms relative to each segment t0 (common scale)',14)
txt(30,966,'Observed tradeoff: tighter boundary scheduling reduced blocking here, while some full refreshes completed later.',16)
txt(30,992,'One sequential run per combination; frequency/order effects and D2D retention overhead remain. No p99 or speedup claim.',14,'#626567')
txt(30,1018,'Whole Context inner B1 finish is unobserved; orange C bars must not be interpreted as per-layer progress or GPU utilization.',13,'#626567')
svg.append('</g></svg>');(root/'OPPORTUNITY.svg').write_text('\n'.join(svg))
