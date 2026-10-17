"""Execute the actual journal callback extracted by AST, without importing CUDA."""
import ast,json,pathlib,tempfile,time
src=pathlib.Path('scripts/pi05_b2_opportunity.py').read_text()
tree=ast.parse(src);f=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='journal')
with tempfile.TemporaryDirectory() as tmp:
 p=pathlib.Path(tmp)/'progress.jsonl'
 with p.open('w',buffering=1) as progress:
  env=dict(progress=progress,json=json,time=time)
  exec(compile(ast.fix_missing_locations(ast.Module(body=[f],type_ignores=[])),'actual_journal_callback','exec'),env)
  env['journal']('segment_start',segment=0,t0_ns=123)
  env['journal']('submit',segment=0,work='Expert',id=0)
  env['journal']('completed_event',segment=0,kind='Expert',id=0,completion_observed_ns=456)
  env['journal']('segment_validated',segment=0)
 rows=[json.loads(l) for l in p.read_text().splitlines()]
 assert len(rows)==4 and rows[2]['event']=='completed_event' and rows[2]['kind']=='Expert' and rows[2]['completion_observed_ns']==456
 print(json.dumps(dict(status='PASS',scope='CPU-only actual journal callback; no model or CUDA',records=rows),indent=2))
