"""Local-only M3 evidence review. No GPU imports or remote/hardware calls."""
from pathlib import Path
import ast,collections,csv,hashlib,importlib.util,json,sys,zipfile,xml.etree.ElementTree as ET
PROJECT=Path('/Users/moblumen/Desktop/CoOverlap')
OUT=Path(__file__).resolve().parent
BATCHES={'B4':'20261021/split_priority_ablation_v1_r2','B5':'20261021/boundary_budget_anchors_v1_r1','B6':'20261021/controlled_interference_b6_v1_r1','B7':'20261021/stage_startup_b7_v1','B8':'20261022/split_budget_challenge_b8_v1','B9':'20261023/expert_reserve_validation_b9_v1_r2','B10':'20261023/credible_selector_validation_b10_v1_r1'}
STATS=PROJECT/'reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/deployment'
sys.path.insert(0,str(STATS))
from m2_executor import replay_stats
from period_obligation_stats import classify

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def states(rows,key):return {s:sum(1 for x in rows if x[key]==s) for s in ('PASS','FAIL','UNCERTAIN','INCOMPLETE')}

def main():
 catalog={};totals=[];segments=[];issues=[]
 for label,rel in BATCHES.items():
  root=PROJECT/'reports/m3_b2'/rel;raw=root/'gpu_run_01/board/run_01/model/result.json'
  if not raw.exists():raise FileNotFoundError(raw)
  r=json.loads(raw.read_text());catalog[label]=dict(path=str(raw.relative_to(PROJECT)),sha256=sha(raw),configuration=r.get('configuration'),model_status=r.get('status'),checks=len(r.get('checks',[])),checks_failed=sum(not x.get('pass_') for x in r.get('checks',[])),call_ledger_rows=len(r.get('call_ledger',[])))
  groups=collections.defaultdict(list)
  for s in r['segments']:
   m=s['manifest'];t0=s['t0_ns'];ex={int(k):tuple(v) for k,v in s['experts'].items()};u={ast.literal_eval(k):tuple(v) for k,v in s['units'].items()};pub={int(k):tuple(v) for k,v in s['published'].items()}
   stat=replay_stats(m,ex,u,pub,t0=t0)
   if [{k:x.get(k) for k in y} for x,y in zip(s['statistics']['cycles'],stat['cycles'])]!=stat['cycles'] or len(s['statistics']['cycles'])!=len(stat['cycles']):issues.append(label+'/'+s['segment_id']+': core stored cycles differ')
   if stat['refreshes']!=s['statistics']['refreshes']:issues.append(label+'/'+s['segment_id']+': stored refreshes differ')
   es=[];us=[]
   for e in m['experts']:
    j=e['id'];dl=t0+e['deadline_ns'];lo,hi=ex.get(j,(None,None));ul,uh=u.get((j//2,j%2),(None,None))
    es.append(dict(status=classify(lo,hi,dl),margin_ms=None if hi is None else (dl-hi)/1e6))
    us.append(dict(status=classify(ul,uh,dl),margin_ms=None if uh is None else (dl-uh)/1e6))
   rows=dict(batch=label,segment_id=s['segment_id'],cell=s.get('cell',s.get('candidate',s.get('mode'))),plan=s.get('plan',(s.get('block_plan') or {}).get('id')),policy=s.get('policy',s.get('mode')),period_ms=m['period_ns']/1e6,experts=es,units=us,cycles=stat['cycles'],refreshes=stat['refreshes'])
   groups[(rows['cell'],rows['plan'],rows['policy'],rows['period_ms'])].append(rows);segments.append(rows)
  for (cell,plan,policy,period),ss in groups.items():
   row=dict(batch=label,cell=cell,plan=plan,policy=policy,period_ms=period,segments=len(ss))
   for name,key in [('Expert','experts'),('VLMUnit','units'),('Cycle','cycles'),('Refresh','refreshes')]:
    allrows=[x for s in ss for x in s[key]];cs=states(allrows,'status');row[name+'_denominator']=len(allrows)
    for st,n in cs.items():row[name+'_'+st]=n
   row['min_Expert_margin_ms']=min(x['margin_ms'] for s in ss for x in s['experts'] if x['margin_ms'] is not None)
   row['min_VLM_margin_ms']=min(x['margin_ms'] for s in ss for x in s['units'] if x['margin_ms'] is not None)
   row['min_Cycle_margin_ms']=min((x['deadline_ns']-x['release_ns']-x['response_upper_ns'])/1e6 for s in ss for x in s['cycles'] if x['response_upper_ns'] is not None)
   row['min_Refresh_margin_ms']=min(2*period-x['ready_upper_ns']/1e6 for s in ss for x in s['refreshes'] if x['ready_upper_ns'] is not None)
   totals.append(row)
 # Preserve original taskbook text for explicit requirement-vs-interpretation mapping.
 task=PROJECT/'Student_B_CoOverlap_Revised.docx';ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
 with zipfile.ZipFile(task) as z:xml=ET.fromstring(z.read('word/document.xml'))
 paras=[''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in xml.findall('.//w:body/w:p',ns)]
 keep=[];section=None
 for p in paras:
  if p and p[0].isdigit() and (p.startswith(('4.','5.','7.','8.','9.'))):section=p
  if section and section.startswith(('4.','5.','7.','8.')):keep.append(dict(section=section,text=p))
 tables=[]
 for table in xml.findall('.//w:tbl',ns):
  rows=[[''.join(t.text or '' for t in c.findall('.//w:t',ns)) for c in tr.findall('w:tc',ns)] for tr in table.findall('w:tr',ns)]
  if any(any(k in c for k in ('M3','边界 Expert','边界Expert','干扰条件化','计划余量')) for r in rows for c in r):tables.append(rows)
 dump('TASK_REQUIREMENTS.json',dict(source=str(task.relative_to(PROJECT)),sha256=sha(task),paragraphs=keep,tables=tables))
 catalog['taskbook']=dict(path=str(task.relative_to(PROJECT)),sha256=sha(task))
 extra=['reports/m3_b2/20261020/three_block_v1_r2/gpu_run_01/COSTS.md','reports/m3_b2/20261020/three_block_v1_r2/gpu_run_01/closeout/CLOSEOUT_REPORT.md','reports/m3_b2/20261020/boundary_profile_v1/gpu_run_01/CONTROL_COSTS.md','reports/m3_b2/20261021/stage_startup_b7_v1/corrections/output/B7_STAGE_INTERVALS.md','reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/B9_CLOSEOUT.md','reports/m3_b2/20261023/credible_plan_selector_v2_r1/outputs/SELECTION.json','reports/m3_b2/20261023/credible_plan_selector_v2_r1/outputs/ABLATION.csv','reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/B10_CLOSEOUT.md','reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/gpu_run_01/closeout_eval/EVALUATION.json','reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/gpu_run_01/recovery_readback_codex_20261023/INDEPENDENT_RESTORE_READBACK.json','reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/gpu_run_01/recovery_readback_codex_20261023/INDEPENDENT_RESTORE_READBACK_FOLLOWUP_CODEX_20261023_01.json','reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/gpu_run_01/BACKUP_VERIFICATION.json']
 extra += ['reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/gpu_run_01/board/run_01/SCOPE_RESULT.json','reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/gpu_run_01/board/run_01/PREFLIGHT.json']
 for rel in extra:catalog[rel]=dict(path=rel,sha256=sha(PROJECT/rel))
 for label,rel in BATCHES.items():
  candidates=[PROJECT/'reports/m3_b2'/rel/'gpu_run_01/RUN_REPORT.md',PROJECT/'reports/m3_b2'/rel/'B7_RUN_REPORT.md']
  for p in candidates:
   if p.exists():catalog[label+'_report']=dict(path=str(p.relative_to(PROJECT)),sha256=sha(p))
 for p in [STATS/'m2_executor.py',STATS/'period_obligation_stats.py']:
  catalog[p.name]=dict(path=str(p.relative_to(PROJECT)),sha256=sha(p))
 with (OUT/'METRICS_BY_CELL.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(totals[0]));w.writeheader();w.writerows(totals)
 dump('METRICS_BY_SEGMENT.json',segments)
 dump('EVIDENCE_INDEX.json',dict(schema='m3_stage_review_sources_v1',inputs=catalog,note='read-only local review; no remote re-hash or full payload re-hash claimed'))
 e=json.loads((PROJECT/extra[8]).read_text());pred=PROJECT/'reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/prediction/PREDICTION.json';p=json.loads(pred.read_text())
 dump('VERIFY_RESULT.json',dict(status='PASS' if not issues else 'MISMATCH',batches=len(BATCHES),segments=len(segments),cycles=sum(len(s['cycles']) for s in segments),refreshes=sum(len(s['refreshes']) for s in segments),stored_statistics_mismatches=issues,B10_prediction_rows=sum(len(x['rows']) for c in p['segments'].values() for x in c.values()),B10_comparison_groups=sum(len(s['comparisons']) for s in e['E_prediction']),B10_job_comparisons=sum(len(c['jobs']) for s in e['E_prediction'] for c in s['comparisons']),scope='Verification totals describe coverage only; do not pool batches into a performance rate'))
 if issues:raise SystemExit('stored statistics mismatch')
 print(json.dumps(json.loads((OUT/'VERIFY_RESULT.json').read_text()),ensure_ascii=False))
if __name__=='__main__':main()
