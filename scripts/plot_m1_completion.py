"""Offline Host release/completion opportunity figure; never invent GPU busy time."""
import json,sys,html
from pathlib import Path
def main():
    from m1_run_identity import require_analysis_user
    require_analysis_user()
    root=Path(sys.argv[1]);r=json.loads((root/'result.json').read_text());assert r['protocol_id']=='m1_completion_batch_v1'
    segs=r.get('segments',[]);W=1900;H=100+180*len(segs);svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">','<rect width="100%" height="100%" fill="white"/>']
    def text(x,y,s):svg.append(f'<text x="{x}" y="{y}" font-size="13">{html.escape(str(s))}</text>')
    text(20,24,'M1 单Stream固定义务机会观察；Host释放/完成观测，不是Kernel忙碌时间或安全共执行收益')
    text(20,48,f"{r['role']} / {r['status']}; 各重复独立报告；真实配对/净分区损失 BLOCKED、未测")
    for i,s in enumerate(segs):
        y=80+180*i;text(20,y,f"{s['P_ms']}ms {s['plan']} {s['interference']} {s['status']} frequency={s.get('frequency_condition',{}).get('status','UNKNOWN')}")
        if 't0_ns' not in s:continue
        t=s['t0_ns'];P=s['P_ms']*1e6;end=max([t+s['cycles']*P]+[v.get('completion_observed_ns',t) for v in s.get('experts',[])]+[v.get('ready_observed_ns',t) for v in s.get('refreshes',[])])
        def x(v):return 160+1700*(v-t)/max(1,end-t)
        for j in range(s['cycles']):
            v=x(t+j*P);svg.append(f'<line x1="{v}" x2="{v}" y1="{y+15}" y2="{y+120}" stroke="#ddd"/>');text(v,y+140,j)
        text(20,y+40,'Expert');text(20,y+80,'B1');text(20,y+115,'B2/就绪')
        for e in s.get('experts',[]):
            a=x(e['release_ns']);b=x(e['completion_observed_ns']);color='#c43c39' if e['completion_lower_ns']>e['deadline_ns'] else '#297a4b' if e['completion_observed_ns']<=e['deadline_ns'] else '#b8860b'
            svg.append(f'<line x1="{a}" x2="{b}" y1="{y+35}" y2="{y+35}" stroke="{color}" stroke-width="3"/>')
        for u in s.get('unit_completions',[]):
            a=x(t+u['id']*2*P);b=x(u['completion_observed_ns']);yy=y+(75 if u['unit']=='B1' else 110)
            svg.append(f'<line x1="{a}" x2="{b}" y1="{yy}" y2="{yy}" stroke="#4775ac" stroke-width="2"/>');svg.append(f'<circle cx="{b}" cy="{yy}" r="3" fill="#23476c"/>')
    svg.append('</svg>');(root/'OPPORTUNITY.svg').open('x').write('\n'.join(svg))
if __name__=='__main__':main()
