"""Offline truthful summaries/partial figure; never fabricate missing completion."""
import csv,hashlib,json,pathlib,html
base=pathlib.Path('reports/m1_recovery/b2_observation');raw=base/'raw/cooverlap_b2_opportunity_20261014_01';r=json.loads((raw/'result.json').read_text());cfg=json.loads((base/'PROTOCOL.json').read_text());hs=json.loads((base/'raw/cooverlap_b2_opportunity_sha.json').read_text());assert all(hashlib.sha256((raw/n).read_bytes()).hexdigest()==h for n,h in hs.items())
rows=[]
for i,(P,plan) in enumerate((P,pl) for P in cfg['budgets_ms'] for pl in cfg['plans']):
 s=next((s for s in r.get('segments',[]) if s['id']==i),None)
 rows.append(dict(P_ms=P,plan=plan,status='INCOMPLETE_LOGGING_ERROR' if s else 'NOT_RUN',experts_submitted=1 if s else 0,experts_output_verified=0,refreshes_completed=0,expert_responses_ms='UNKNOWN' if s else 'NOT_RUN',expert_misses_over_8='UNKNOWN/8' if s else 'NOT_RUN',longest_consecutive_misses='UNKNOWN' if s else 'NOT_RUN',boundary_wait='UNKNOWN' if s else 'NOT_RUN',refresh_response_and_k='UNKNOWN' if s else 'NOT_RUN',cycle_miss_rate='NOT_DEFINED'))
with (base/'COMBINATIONS.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
progress=[json.loads(l) for l in (raw/'progress.jsonl').read_text().splitlines()]
t0=progress[0]['t0_ns'];submit=progress[1]['host_ns'];delta=(submit-t0)/1e6
(base/'OFFLINE_SUMMARY.json').write_text(json.dumps(dict(raw_files_verified=len(hs),gate=r.get('gate'),gate_comparisons=len(r['comparisons']),execution={'model_processes':1,'segments_started':1,'segments_completed':0,'timed_Expert_layer_calls':len(r['ledger'].get('seg0_E0',{}).get('v0',{}).get('decoder',[])),'timed_contexts_completed':0},t0_host_monotonic_ns=t0,Expert0_submit_log_ns=submit,release_to_submit_log_ms=delta,completion_timestamp='NOT_PERSISTED; cannot derive response or wait',combinations=rows),indent=2)+'\n')
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1180" height="690" viewBox="0 0 1180 690">','<rect width="1180" height="690" fill="#fafafa"/>','<g font-family="Arial, sans-serif" fill="#17202a">']
def text(x,y,s,size=15,color='#17202a'):svg.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{html.escape(s)}</text>')
text(32,40,'M1 单 Stream 机会观察 — 本批 INCOMPLETE',25)
text(32,70,'数值闸门 PASS；首段 Expert0 后日志异常停止。没有完成响应样本或刷新进度曲线。',16,'#a93226')
text(32,100,f'唯一已持久化提交记录：E0，r0 后 {delta:.6f} ms（Host 日志时刻，非 GPU 开始）。')
left,right=260,1110
for idx,row in enumerate(rows):
 y=155+idx*65;P=row['P_ms'];plan=row['plan'];text(32,y+5,f'{P} ms / {plan}',14)
 svg.append(f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="#d6dbdf"/>')
 if idx==0:
  for j in range(8):
   x=left+(right-left)*j/7;col='#2471a3' if j==0 else '#aab7b8'
   svg.append(f'<line x1="{x}" y1="{y-9}" x2="{x}" y2="{y+9}" stroke="{col}" stroke-dasharray="{0 if j==0 else 3}"/>');text(x-10,y+28,str(j*P),12,col)
  svg.append(f'<circle cx="{left+delta/(7*P)*(right-left)}" cy="{y}" r="5" fill="#2471a3"/>')
  text(32,y+27,'仅 r0 释放 / E0 提交',12,'#2471a3');text(left,y-18,'R0 已释放，未执行；R1=r4 仅为计划。刷新完成 0/2。',13)
 else:text(left,y+5,'NOT_RUN — 不填零违约，不推算缺失响应',14,'#7b7d7d')
text(left,565,'首段轴：相对 r0 的 ms；灰色虚线为未来计划释放，非实际执行证据。',14)
text(32,607,'完成时刻未持久化：不能绘制 Expert 响应、边界等待、k 或收益。',16,'#a93226')
text(32,637,'无 Nsight / Graph / 并发 / 分区；G4 双流 FAIL 保留；本图仅记录此次采集缺口。',14)
svg.append('</g></svg>');(base/'OPPORTUNITY_INCOMPLETE.svg').write_text('\n'.join(svg))
print(json.dumps(dict(verified_files=len(hs),gate=r.get('gate'),completed_segments=0,submit_log_delay_ms=delta)))
