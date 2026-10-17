"""Create the M1 single-task/serial structure SVG from saved raw samples."""
import collections
import html
import json
import sqlite3
import statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
raw=ROOT/'reports/m1_recovery/raw/cooverlap_m1_profile_20261014_01/samples.jsonl'
db=ROOT/'reports/m1_recovery/nsys_recovery/cooverlap_nsys_model_20261014_02/trace.sqlite'
out=ROOT/'reports/m1_recovery/OPPORTUNITY_DRAFT.svg'
samples=collections.defaultdict(list)
for line in raw.read_text().splitlines():
    x=json.loads(line)
    if not x['warmup']: samples[x['mode']].append(x)
conn=sqlite3.connect(db)
ranges=[(name,s,e) for name,s,e in conn.execute('select text,start,end from NVTX_EVENTS where end is not null order by start') if name in ('context','expert','serial')]
runtime=list(conn.execute('select start,correlationId from CUPTI_ACTIVITY_KIND_RUNTIME where correlationId is not null'))
kernels=list(conn.execute('select start,end,correlationId from CUPTI_ACTIVITY_KIND_KERNEL'))

def union_length(intervals):
    intervals=sorted(intervals)
    if not intervals:return 0
    a,b=intervals[0]; total=0
    for x,y in intervals[1:]:
        if x>b: total+=b-a; a,b=x,y
        else:b=max(b,y)
    return total+b-a

W,H=1190,840
v=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
   '<rect width="100%" height="100%" fill="#ffffff"/>',
   '<style>text{font-family:Arial,"Noto Sans CJK SC",sans-serif;fill:#17212b} .sm{font-size:13px} .md{font-size:16px} .big{font-size:23px;font-weight:700} .axis{stroke:#b7c2cc;stroke-width:1}</style>',
   '<text x="48" y="38" class="big">单任务与串行执行结构初稿</text>',
   '<text x="48" y="61" class="sm">真实 AGX Orin；未测安全共执行、分区损失或 deadline 改善</text>',
   '<text x="48" y="102" class="md">A  未插桩 CUDA Event：每模式 5 个原始样本（毫秒）</text>']

def line(x1,y1,x2,y2,stroke='#b7c2cc',width=1):v.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}"/>')
def rect(x,y,w,h,fill):v.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{fill}" rx="2"/>')
def txt(x,y,s,cls='sm'):v.append(f'<text x="{x}" y="{y}" class="{cls}">{html.escape(str(s))}</text>')

left,span=210,680
for tick in range(0,251,50):
    x=left+tick/250*span; line(x,120,x,315,'#e1e7ec');txt(x-8,331,tick)
labels=[('block1','Block 1'),('block2','Block 2'),('context','完整 Context'),('expert','Expert 10 步'),('serial','串行总作业')]
for i,(key,label) in enumerate(labels):
    y=137+i*36;vals=[z['gpu_ms'] for z in samples[key]]; med=statistics.median(vals)
    txt(48,y+14,label)
    rect(left,y,med/250*span,17,'#3582b5')
    for q in vals:
        x=left+q/250*span;line(x,y-2,x,y+21,'#123b59',1)
    txt(915,y+14,f'{med:.3f} ms median')
txt(48,355,'短竖线为全部正式样本；蓝条为中位数。各模式独立测量，不相加推断串行。')
txt(48,390,'B  单次 Nsight 诊断：Event 区间内的实际时间结构（毫秒）','md')
for tick in range(0,251,50):
    x=left+tick/250*span;line(x,410,x,539,'#e1e7ec');txt(x-8,557,tick)
for i,(name,s,e) in enumerate(ranges):
    y=425+i*38
    launch_ids={cid for t,cid in runtime if s<=t<e}
    kk=[(a,b) for a,b,cid in kernels if cid in launch_ids]
    busy=union_length(kk)/1e6
    span_ms=(e-s)/1e6
    idle=span_ms-busy
    txt(48,y+14,{'context':'完整 Context','expert':'Expert 10 步','serial':'串行总作业'}[name])
    rect(left,y,busy/250*span,18,'#168a70')
    rect(left+busy/250*span,y,idle/250*span,18,'#e5a43d')
    txt(915,y+14,f'Kernel {busy:.1f} / 其它 {idle:.1f}')
txt(48,584,'绿色：Kernel 时间并集；橙色：区间内未执行所追踪 Kernel 的时间。')
txt(48,620,'C  同一次诊断的 CPU 时间：提交与 Event 等待（毫秒）','md')
cpu={x['mode']:x for x in map(json.loads,(ROOT/'reports/m1_recovery/nsys_recovery/cooverlap_m1_trace_20261014_02/samples.jsonl').read_text().splitlines())}
for i,(key,label) in enumerate([('context','完整 Context'),('expert','Expert 10 步'),('serial','串行总作业')]):
    y=648+i*38;rec=cpu[key];a=rec['cpu_submit_ns']/1e6;b=rec['cpu_event_wait_ns']/1e6
    txt(48,y+14,label);rect(left,y,a/250*span,18,'#7954a8');rect(left+a/250*span,y,b/250*span,18,'#aeb9c4')
    txt(915,y+14,f'提交 {a:.1f} / 等待 {b:.1f}')
txt(48,781,'本次被测 Kernel 全在 stream 13。子块 Kernel 使用 Runtime correlation ID 归属；CPU NVTX 标签不是 GPU 完成边界。')
txt(48,805,'Nsight 插桩与未插桩数据不混算；橙色间隙不等于可回收 GPU 配额。')
v.append('</svg>')
out.write_text('\n'.join(v))
print(out)
