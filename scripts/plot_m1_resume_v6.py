"""Static evidence plot. Reads accepted v4 CSV, never synthesizes v6 timings."""
import csv,html,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
root=Path(__file__).resolve().parents[1];out=root/'reports/m1_acceptance/pair_plain_20261016_v6_resume';v4=root/'reports/m1_acceptance/completion_20261016_v4/summary'
W,H=1400,1010;im=Image.new('RGB',(W,H),'#f5f7fb');d=ImageDraw.Draw(im);svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><rect width="100%" height="100%" fill="#f5f7fb"/>']
font='/System/Library/Fonts/Hiragino Sans GB.ttc'
def rect(x,y,w,h,fill):
 d.rectangle([x,y,x+w,y+h],fill=fill);svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>')
def text(x,y,t,size=20,color='#20324b'):
 d.text((x,y),t,font=ImageFont.truetype(font,size),fill=color);svg.append(f'<text x="{x}" y="{y+size}" font-family="PingFang SC,Arial,sans-serif" font-size="{size}" fill="{color}">{html.escape(t)}</text>')
def dot(x,y,color):
 d.ellipse((x-5,y-5,x+5,y+5),fill=color);svg.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>')
text(35,20,'CoOverlap M1｜第一周有限证据与缺口',32)
text(35,66,'v4已审核数据冻结；v6接续在Context闸门停止。不是共执行收益或最终路线结论。',20)
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
text(740,132,'B  限定Encoder四模式：v4 Host窗口中位',22)
modes=list(csv.DictReader((v4/'PAIR_MODES.csv').open()));names={'serial':'串行','ordinary':'普通双流','fixed':'固定8+8','return':'边界归还'}
for i,r in enumerate(modes):
 y=193+i*57;v=float(r['Host_window_median_ms']);text(740,y,names[r['mode']],18)
 rect(845,y+4,v*1.7,22,'#4286bd');text(1225,y,f'{v:.3f}',18)
text(740,436,'单位ms；每模式n=3，不是Kernel服务时间。',17)
text(740,462,'归还优于固定点，不等于优于串行。',17)
text(50,540,'C  Expert后尾段：有限Event证据与净损失缺口',22)
for i,r in enumerate([r for r in modes if r['mode'] in ('fixed','return')]):
 y=605+i*65;v=float(r['Event_tail_median_ms']);text(50,y,names[r['mode']],18);rect(170,y+4,v*4,24,'#6ca89c');text(490,y,f'{v:.3f} ms',18)
text(50,755,'v4同批尾差27.822–28.322ms，仅Event口径。',18)
text(50,794,'完整边界等待、控制生效成本：UNKNOWN',19,'#b75235')
text(50,833,'正确配对物理重叠、完整净损失：UNKNOWN',19,'#b75235')
text(50,875,'v6新增端点未执行；不补造数字或重复扣成本。',17)
text(740,540,'D  v6接续：托管及恢复通过，数值FAIL',22)
text(740,600,'1模型 / 1scope；20.644s退出1，无重试。',20)
text(740,647,'普通启动Context精确FAIL；Expert未执行',19,'#b75235')
text(740,692,'正常配对 0/12；诊断配对 0/4：NOT_RUN',20)
text(740,737,'采集未启用；物理重叠UNKNOWN，不是测得0。',19)
text(740,785,'自动五min恢复及独立读回PASS；无残留。',20,'#247768')
text(740,838,'M1整体 PARTIAL；建议优先考虑B2，',20)
text(740,870,'最终路线待用户确认，不进入M2。',20)
text(35,943,'来源：v4 CELLS.csv、PAIR_MODES.csv；v6接续 ATTEMPT_AND_WORK_LEDGER.json、OFFLINE_SAVED_REVIEW.json。',17)
text(35,974,'正常与诊断样本不合并；无可靠p99.9、k_min或稳定加速结论。2026-10-16 / AGX Orin 64GB',16)
svg.append('</svg>');(out/'M1_EVIDENCE_OVERVIEW.svg').write_text('\n'.join(svg));im.save(out/'M1_EVIDENCE_OVERVIEW.png')
