"""Saved v4 periodic and v7 normal samples; no synthetic GPU timeline."""
import csv,html,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
root=Path(__file__).resolve().parents[1];out=root/'reports/m1_acceptance/scoped_equivalence_20261016_v7';v4=root/'reports/m1_acceptance/completion_20261016_v4/summary'
W,H=1400,1010;im=Image.new('RGB',(W,H),'#f5f7fb');d=ImageDraw.Draw(im);svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><rect width="100%" height="100%" fill="#f5f7fb"/>']
font='/System/Library/Fonts/Hiragino Sans GB.ttc'
def rect(x,y,w,h,fill):
 d.rectangle([x,y,x+w,y+h],fill=fill);svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>')
def text(x,y,t,size=20,color='#20324b'):
 d.text((x,y),t,font=ImageFont.truetype(font,size),fill=color);svg.append(f'<text x="{x}" y="{y+size}" font-family="PingFang SC,Arial,sans-serif" font-size="{size}" fill="{color}">{html.escape(t)}</text>')
def dot(x,y,color):
 d.ellipse((x-5,y-5,x+5,y+5),fill=color);svg.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>')
text(35,20,'CoOverlap M1｜第一周有限证据与缺口',32)
text(35,66,'v4周期数据冻结；v7四模式正常数值通过。Event区间不是Kernel忙碌或物理重叠证据。',20)
for x,y in [(30,115),(720,115),(30,520),(720,520)]:rect(x,y,650,380,'#ffffff')
text(50,132,'A  完整周期违约：每格三独立进程，每次64周期',22)
cells=list(csv.DictReader((v4/'CELLS.csv').open()));colors=['#1a77bd','#e58b29']
labels=[('whole_context','none','whole 无干扰'),('whole_context','memcpy32MiB','whole 访存'),('two_blocks','none','双块 无干扰'),('two_blocks','memcpy32MiB','双块 访存')]
for n,(plan,stress,label) in enumerate(labels):
 y=190+n*65;text(50,y,label,17)
 for j,P in enumerate([180,240]):
  rows=sorted((r for r in cells if r['plan']==plan and r['interference']==stress and int(r['P_ms'])==P),key=lambda r:int(r['repeat']))
  counts=[int(r['cycle_miss']) for r in rows];x=255+j*195
  text(x,y,f'{P}ms: '+ '/'.join(map(str,counts)),18,colors[j])
  for k,c in enumerate(counts):dot(x+10+k*45,y+45-c*3,colors[j])
text(50,458,'保留周期0和迟到作业；双块未显示稳定改善。',17)
text(740,132,'B  v7限定Encoder四模式：Host窗口中位',22)
modes=list(csv.DictReader((out/'MODE_SUMMARY.csv').open()));names={'serial':'串行','ordinary':'普通双流','fixed':'固定8+8','return':'边界归还'}
for i,r in enumerate(modes):
 y=193+i*57;v=float(r['window_Host_ms_median']);text(740,y,names[r['mode']],18)
 rect(845,y+4,v*1.7,22,'#4286bd');text(1225,y,f'{v:.3f}',18)
text(740,436,'单位ms；每模式n=3，不是Kernel服务时间。',17)
text(740,462,'归还优于固定点，不等于优于串行。',17)
text(50,540,'C  Expert完成至Context就绪：Event尾段',22)
for i,r in enumerate([r for r in modes if r['mode'] in ('fixed','return')]):
 y=605+i*65;v=float(r['Expert_to_Context_tail_ms_median']);text(50,y,names[r['mode']],18);rect(170,y+4,v*4,24,'#6ca89c');text(490,y,f'{v:.3f} ms',18)
text(50,750,'同轮固定−归还尾差：28.212 / 28.352 / 28.421 ms',17)
text(50,790,'数学边界等待：本次全部0 ms（Event口径）',18)
text(50,829,'D2D后可调度边界等待：0.297–0.405 ms',18)
text(50,870,'已含控制成本，不再重复扣减；尚无Kernel佐证。',17)
text(740,540,'D  控制成本已留证；活动采集权限阻断',22)
text(740,597,'资源创建准备：11.625 ms（一次性）',20)
text(740,641,'归还判断→B2提交前：0.054–0.056 ms',19)
text(740,685,'归还判断→B2提交返回：6.313–6.460 ms',19)
text(740,729,'正常样本12/12数值PASS；诊断0/4 NOT_RUN',19)
text(740,773,'CUPTI注册回调返回35：权限不足',20,'#b75235')
text(740,817,'物理Kernel重叠 UNKNOWN；M1仍PARTIAL',20)
text(740,861,'自动恢复 + 独立读回PASS；路线待用户确认',18)
text(35,943,'来源：v4 CELLS.csv；v7 NORMAL_SAMPLES.csv、MODE_SUMMARY.csv及活动启用失败日志。',17)
text(35,974,'每模式n=3；无可靠p99.9、k_min、稳定加速或已选B2结论。2026-10-16 / AGX Orin 64GB',16)
svg.append('</svg>');(out/'M1_EVIDENCE_OVERVIEW.svg').write_text('\n'.join(svg));im.save(out/'M1_EVIDENCE_OVERVIEW.png')
