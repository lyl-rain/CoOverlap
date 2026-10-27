"""Single CPU-only deterministic build path. No deployment or model execution."""
import hashlib,json,os,re,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
S=HERE.parent/'credible_plan_selector_v2_r1'
D=HERE/'deployment'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,d):p.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
def freeze(root,paths):
 files={}
 for p in sorted(set(paths),key=str):
  original=Path('/Users/moblumen/Desktop/CoOverlap')
  if p.is_relative_to(original):p=S.parents[3]/p.relative_to(original)
  files[os.path.relpath(p,root)]=dict(path=os.path.relpath(p,root),sha256=sha(p))
 dump(root/'FREEZE.json',dict(schema='local_consistency_manifest_v1',status='PREPARED_NOT_APPROVED_NOT_RUN',files=files,note='consistency relative to this manifest, not authentication or historical ordering proof'))
def call(p):subprocess.run([sys.executable,'-B',str(p)],check=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
def main():
 selector_files=list((S/'cps2').glob('*.py'))+[S/'SOURCE_CONDITIONS.json',S/'outputs/RULES.json',S/'outputs/COSTS.json',S.parent/'expert_reserve_validation_b9_v1_r2/gpu_run_01/board_small/model/result.json',S.parent.parent/'20261022/split_budget_challenge_b8_v1/gpu_run_01/board/run_01/model/result.json',S.parent.parent/'20261022/empirical_plan_selector_v1_r1/selector/plan_model.py']
 selector_files+=list((S.parent/'release_boundary_evaluator_v1/rbe').glob('*.py'))+list((S.parent.parent/'20261022/empirical_plan_selector_v1_r1/selector').glob('*.py'))
 sys.path.insert(0,str(S/'cps2'))
 import core
 import inspect
 selector_files += [Path(inspect.getfile(core.hooked.VersionedKV))]
 import period_obligation_stats
 selector_files += [Path(period_obligation_stats.__file__)]
 freeze(S,selector_files)
 call(S/'cps2/run.py')
 # Publish source checks explicitly. Never infer target validation from source match.
 sys.path.insert(0,str(S/'cps2'))
 import core
 costs=json.loads((S/'outputs/COSTS.json').read_text())
 costs['mapping']['source_checks']={name:core.integrity.source_check(core.load(path),name) for name,path in [('B9',core.B9_RESULT),('B8',core.B8_RESULT)]}
 costs['mapping']['source_match']['b9']='MATCH against frozen B9 source identity and field conditions; not target-budget validation'
 dump(S/'outputs/COSTS.json',costs)
 freeze(S,selector_files+list((S/'outputs').glob('*.json'))+list((S/'outputs').glob('*.csv')))
 call(HERE/'analysis/build_b10_prediction.py')
 sys.path.insert(0,str(D))
 import m3_b10_plan as plan
 pred=json.loads((HERE/'prediction/PREDICTION.json').read_text());sel=json.loads((HERE/'prediction/SELECTION_FREEZE.json').read_text())
 updates=dict(PREDICTION_SHA256=sha(HERE/'prediction/PREDICTION.json'),PREDICTION_FINGERPRINT=pred['fingerprint'],SELECTION_SHA256=sha(HERE/'prediction/SELECTION_FREEZE.json'),SELECTION_FINGERPRINT=sel['fingerprint'],RULE_SHA256=sha(S/'outputs/RULES.json'),COSTS_SHA256=sha(S/'outputs/COSTS.json'),SELECTION_BY_PERIOD=sel['by_period_ns'],ANALYSIS_MODULES={p.name:sha(p) for p in list((HERE/'analysis').glob('*.py'))+list((S/'cps2').glob('*.py'))})
 path=D/'m3_b10_plan.py';text=path.read_text()
 for name,value in updates.items():
  text,n=re.subn(r'^'+name+r' = .*$',name+' = '+repr(value),text,flags=re.M)
  assert n==1,name
  setattr(plan,name,value)
 path.write_text(text)
 config=plan.protocol();dump(D/'CONFIG.json',config)
 budget=plan.budget();dump(D/'BUDGET.json',dict(schema='m3_b10_budget_v1',protocol=plan.PROTOCOL,work=config['work'],retention=budget,limits=config['limits']))
 dump(D/'FAIRNESS_CHECK.json',dict(status='CPU_CONFIGURATION_CHECK',order=[r['cell'][0] for r in plan.RUN],shared_manifest_per_budget=True,phase_ns=config['phase_ns'],fixed_matrix=True,plans={p.id:p.summary() for p in plan.PLANS.values()}))
 dump(D/'COMPATIBILITY.json',config['compatibility'])
 paths=[p for p in D.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='DEPLOY_SHA256.txt']
 (D/'DEPLOY_SHA256.txt').write_text(''.join(sha(p)+'  '+str(p.relative_to(D))+'\n' for p in sorted(paths)))
 allpaths=paths+[D/'DEPLOY_SHA256.txt']+list((HERE/'analysis').glob('*.py'))+list((HERE/'prediction').glob('*.json'))+list((HERE/'tests').glob('*.py'))+[HERE/'freeze_package.py',HERE/'run_cpu_checks.py']
 sf=json.loads((S/'FREEZE.json').read_text())
 allpaths+= [S/row['path'] for row in sf['files'].values()]+[S/'FREEZE.json']
 freeze(HERE,allpaths)
 rows=sum(len(x['rows']) for cases in pred['segments'].values() for x in cases.values())
 report=dict(status='CPU_FREEZE_CONSISTENCY_ONLY',deployment_entries=len(paths),config_sha256=sha(D/'CONFIG.json'),deployment_manifest_sha256=sha(D/'DEPLOY_SHA256.txt'),prediction_job_rows=rows,segment_comparison_rows=rows*2,segment_mapping=pred['segment_mapping'],work=config['work'],budget=budget,selection={k:dict(status=v['status'],selected=v['selected']) for k,v in sel['by_period_ns'].items()})
 dump(HERE/'FREEZE_VERIFICATION.json',report)
 text='# B10 r1 审批身份（自动生成，未批准、未运行）\n\n'
 text+='仅在用户另行明确批准后执行唯一 submit；本轮 GPU/SSH/硬件操作均为0。\n\n'
 text+='部署清单、入口和评价器已按本批重新生成；预测480作业行，映射8段为960次比较，非960个GPU作业。\n\n'
 text+='|文件|SHA256|\n|---|---|\n'
 for p in sorted(allpaths,key=str):text+='|`'+os.path.relpath(p,HERE)+'`|`'+sha(p)+'`|\n'
 (HERE/'APPROVAL_CHECKLIST.md').write_text(text+'\n准确命令见GPU_PLAN.md；1普通模型+1五节点scope；内部170s、外层180s+10s、scope420s；0重试。\n')
 print(json.dumps({k:report[k] for k in ('deployment_entries','config_sha256','prediction_job_rows','selection')},indent=2))
if __name__=='__main__':main()
