"""Offline static figures from frozen raw observations; no inferred GPU service."""
import csv,json,html,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
R=Path(__file__).resolve().parents[1];B=R/'reports/m1_acceptance/tegra_root_trace_20261017_v9';V7=B.parent/'scoped_equivalence_20261016_v7';V4=B.parent/'completion_20261016_v4/summary'
FONT='/System/Library/Fonts/Hiragino Sans GB.ttc'
class Canvas:
 def __init__(self,w,h):
  self.w=w;self.h=h;self.im=Image.new('RGB',(w,h),'#f5f7fb');self.d=ImageDraw.Draw(self.im);self.s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="#f5f7fb"/>']
 def rect(self,x,y,w,h,c):
  self.d.rectangle([x,y,x+w,y+h],fill=c);self.s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"/>')
 def text(self,x,y,t,size=20,c='#23324a'):
  self.d.text((x,y),t,font=ImageFont.truetype(FONT,size),fill=c);self.s.append(f'<text x="{x}" y="{y+size}" font-family="PingFang SC,Arial,sans-serif" font-size="{size}" fill="{c}">{html.escape(str(t))}</text>')
 def line(self,x,y,x2,y2,c='#aab5c4',w=1):
  self.d.line((x,y,x2,y2),fill=c,width=w);self.s.append(f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="{w}"/>')
 def save(self,name):
  (B/(name+'.svg')).write_text('\n'.join(self.s+['</svg>']));self.im.save(B/(name+'.png'))
def rows(p):return list(csv.DictReader(p.open()))
names={'serial':'串行','ordinary':'普通双流','fixed':'固定 8+8','return':'合法边界归还'}
normal=rows(V7/'MODE_SUMMARY.csv');trace=rows(B/'KERNEL_SUMMARY.csv');review=json.loads((B/'OFFLINE_REVIEW.json').read_text());cells=rows(V4/'CELLS.csv')
c=Canvas(1600,1320);c.text(35,20,'CoOverlap M1｜真实负载机会观察与负面结果',32)
c.text(35,66,'固定 BF16 / 双视角 / 18层 Encoder / 10步 Expert；四个数据批次分别展示，不混合估计收益。',21)
for y in [110,490,870]:
 for x in [30,815]:c.rect(x,y,755,350,'#ffffff')
c.text(50,125,'A  孤立限额响应｜10月15日，同批各 n=3',23)
for i,(title,a,b) in enumerate([('完整 Context',122.790,199.718),('完整 Expert',80.417,81.892)]):
 y=182+i*105;c.text(50,y,title,20)
 for j,(lbl,v,col) in enumerate([('16 SM',a,'#2585ba'),('8 SM',b,'#e39537')]):
  yy=y+35+j*29;c.text(50,yy,lbl,16);c.rect(140,yy+3,v*2.1,17,col);c.text(590,yy,f'{v:.3f} ms',18)
c.text(50,415,'CUDA Event包围区间；非Kernel服务时间，不与后批求速度比。',16)
c.text(835,125,'B  四模式正常计时｜v7 普通用户，各 n=3',23)
for i,r in enumerate(normal):
 y=183+i*51;v=float(r['window_Host_ms_median']);lo=float(r['window_Host_ms_min']);hi=float(r['window_Host_ms_max'])
 c.text(835,y,names[r['mode']],19);c.rect(1015,y+4,v*1.65,22,'#4187b4');c.text(1400,y,f'{v:.3f}',19)
 c.line(1015+lo*1.65,y+14,1015+hi*1.65,y+14,'#18364d',2)
c.text(835,407,'Host窗口：Encoder+Expert及控制；Vision前缀另计。',17)
c.text(835,434,'归还优于固定点，未优于串行；细线为样本 min–max。',17)
c.text(50,505,'C  Expert后尾段｜v7 正常 Event 端点',23)
for i,r in enumerate([x for x in normal if x['mode'] in ['fixed','return']]):
 y=565+i*65;v=float(r['Expert_to_Context_tail_ms_median']);c.text(50,y,names[r['mode']],20);c.rect(215,y+4,v*4.5,24,'#59a591');c.text(580,y,f'{v:.3f} ms',19)
c.text(50,719,'同轮固定−归还：28.212 / 28.352 / 28.421 ms',18)
c.text(50,759,'窗口差：31.098 / 28.384 / 28.221 ms，成本已包含。',17)
c.text(50,802,'同一剩余B2、状态逐位相同；不再次扣除控制开销。',17)
c.text(835,505,'D  Kernel物理重叠｜v9 root诊断，各 n=1',23)
for i,r in enumerate(trace):
 y=562+i*49;v=float(r['overlap_ms']);c.text(835,y,names[r['mode']],19);c.rect(1015,y+4,v*7,20,'#8b70bb');c.text(1400,y,f'{v:.3f} ms',19)
c.text(835,780,'correlation归属 → 各任务区间并集 → 两者交集。',17)
c.text(835,811,'每模式 108 + 99 + 2410 Kernel；丢失0，非性能统计。',17)
c.text(50,885,'E  完整周期违约｜v4，每项三进程×64周期',23)
c.text(50,930,'计划 / 固定干扰            180 ms：C；E             240 ms：C；E',17)
labels=[('whole_context','none','whole / 无'),('whole_context','memcpy32MiB','whole / 访存'),('two_blocks','none','双块 / 无'),('two_blocks','memcpy32MiB','双块 / 访存')]
for i,(plan,stress,lbl) in enumerate(labels):
 y=973+i*42;c.text(50,y,lbl,18)
 for j,P in enumerate([180,240]):
  rr=sorted([r for r in cells if r['plan']==plan and r['interference']==stress and int(r['P_ms'])==P],key=lambda r:int(r['repeat']))
  vals='/'.join(r['cycle_miss'] for r in rr)+'；'+'/'.join(r['Expert_miss'] for r in rr);c.text(285+j*225,y,vals,18)
c.text(50,1163,'C=完整周期，E=Expert；各分母64；双块无稳定改善。',16)
c.text(835,885,'F  边界与控制成本｜v7 正常测量',23)
for i,t in enumerate(['Expert→数学边界：0 ms（本次均已完成）','→D2D后可调度边界：0.297–0.405 ms','资源创建：11.625 ms（一次性）','归还判断→B2提交前：0.054–0.056 ms','归还判断→B2提交返回：6.313–6.460 ms','v9已关联首次B2 Kernel；未扩容运行中Kernel。']):c.text(835,942+i*37,t,18)
c.text(35,1251,'首周测量可提交验收；限定Encoder路径正确且有物理重叠，尚无相对串行净优势。B1/B2待用户选择。',21)
c.text(35,1290,'数据：isolated_limit_20261015；v4 CELLS.csv；v7 NORMAL_SAMPLES.csv；v9 KERNEL_SUMMARY.csv。',16)
c.save('M1_OPPORTUNITY_OVERVIEW')
# Actual correlated GPU activity: each window relative to its first Encoder Kernel.
t=Canvas(1600,1050);t.text(35,18,'限定Encoder四模式｜v9 实际 Kernel 活动时间线',30)
t.text(35,64,'root + CUPTI CONCURRENT_KERNEL诊断，每模式一次；不与v7正常样本合并。空白仅表示无该任务已追踪Kernel。',18)
intervals=rows(B/'TIMELINE_INTERVALS.csv');analysis=json.loads((B/'KERNEL_ANALYSIS.json').read_text());X0=390;scale=3.3
colors={'PREFIX':'#b5c5cf','ENC1':'#2479b5','ENC2':'#55a18a','EXPERT':'#de9839','RETAIN':'#b276b2'}
for i,mode in enumerate(['serial','ordinary','fixed','return']):
 y=125+i*205;rr=next(x for x in analysis['rows'] if '_'+mode+'_' in x['job']);xs=[x for x in intervals if x['mode']==mode];origin=min(int(x['start_ns']) for x in xs if x['phase']=='ENC1')
 t.rect(25,y-8,1545,190,'#ffffff');t.text(40,y,names[mode],22);t.text(40,y+36,f'交集 {rr["physical_overlap_ns"]/1e6:.3f} ms',17)
 for ms in range(-40,301,20):
  x=X0+ms*scale;t.line(x,y+33,x,y+112,'#e2e6eb');t.text(x-8,y+120,str(ms),13)
 for x in xs:
  s=(int(x['start_ns'])-origin)/1e6;e=(int(x['end_ns'])-origin)/1e6;yy=y+38 if x['phase']!='EXPERT' else y+80
  t.rect(X0+s*scale,yy,max(.1,(e-s)*scale),20,colors[x['phase']])
 for key,col,lab in [('B1_last_math_kernel_ns','#2479b5','B1末'),('Expert_last_kernel_ns','#bf7116','E末'),('retention_last_activity_ns','#9a4ca1','留存末'),('B2_first_kernel_ns','#347b68','B2首'),('Context_last_kernel_ns','#20324b','就绪末')]:
  x=X0+(rr[key]-origin)/1e6*scale;t.line(x,y+30,x,y+110,col,2)
 t.text(240,y+150,'Encoder: 灰=Vision/投影前缀，蓝=0–8，绿=9–17；橙=Expert；紫=D2D。',15)
 t.text(240,y+174,f'Expert末→数学末等待 0；→留存末 {rr["Expert_to_schedulable_activity_wait_ns"]/1e6:.3f} ms；三条右侧线依次 E末/留存末/B2首。',14)
t.text(35,963,'横轴ms，相对各窗口首个Encoder Kernel；原始公共GPU时间戳、context/stream/correlation及全部端点见CSV。',18)
t.text(35,1002,'统计先求Kernel区间并集再交集；不以CPU NVTX或Event剪裁归属。细小Kernel在PNG按像素显示，数值来自原始区间。',16)
t.save('CORRELATED_PAIR_TIMELINE')
