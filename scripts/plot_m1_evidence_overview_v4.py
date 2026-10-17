"""Three taskbook panels, keeping historical isolated and new paired data apart."""
import html,json,sys
from pathlib import Path
root=Path(sys.argv[1]);old=json.loads((root/'HISTORICAL_ISOLATED_POINTS.json').read_text());new=json.loads((root/'summary/PAIR_MODES.json').read_text())
W,H=1650,650;svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">','<rect width="100%" height="100%" fill="white"/>']
def text(x,y,s,size=17):svg.append(f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-size="{size}">{html.escape(str(s))}</text>')
def bar(x,y,value,color,scale=1.6):
    svg.append(f'<rect x="{x}" y="{y}" width="{value*scale}" height="28" fill="{color}"/>');text(x+value*scale+8,y+21,f'{value:.3f}ms',15)
text(30,35,'M1 evidence overview: isolated quotas, bounded pairing and remaining-work tail',25)
text(30,68,'Measured intervals, not pure Kernel service. Different batches are separated; no historical/new speed ratio.',17)
text(30,118,'A. Historical isolated (2026-10-15)',19);text(30,145,'Original same-batch Event samples, n=3 each.',15)
for j,x in enumerate(old):
    yy=195+j*83;text(30,yy-10,x['kind']+' / '+x['config'],16);bar(30,yy,x['event_median_ms'],'#4775a8' if x['config']=='full' else '#d58235')
text(570,118,'B. New Encoder-only pairing',19);text(570,145,'Host window, n=3/mode. Vision prefix serial.',15)
for j,x in enumerate(new):
    yy=195+j*83;text(570,yy-10,x['mode'],16);bar(570,yy,x['Host_window_median_ms'],'#4775a8' if x['mode'] in ('serial','ordinary') else '#d58235')
text(1120,118,'C. New same remaining B2 tail',19);text(1120,145,'Expert-done -> Context-done GPU Events.',15)
for j,mode in enumerate(('fixed','return')):
    x=next(m for m in new if m['mode']==mode);yy=210+j*115;text(1120,yy-12,mode,16);bar(1120,yy,x['Event_tail_median_ms'],'#d58235' if mode=='fixed' else '#4775a8',3.5)
text(1120,420,'Fixed - return by round:',16);text(1120,450,'28.322 / 28.287 / 27.822ms',18)
text(30,560,'Physical paired Kernel overlap UNKNOWN. Historical Vision concurrent FAIL retained. n=3 does not establish stable gains.',17)
text(30,590,'Pair Host completion lower-bound audit FAIL; that field is excluded. Complete setup/effect cost and fair quota tuning remain PARTIAL.',16)
text(30,620,'Periodic 64-cycle x 24-cell evidence is in OPPORTUNITY.svg and CELLS.csv. M1 not fully accepted; route not selected.',16)
svg.append('</svg>');(root/'summary/EVIDENCE_OVERVIEW.svg').open('x').write('\n'.join(svg))
