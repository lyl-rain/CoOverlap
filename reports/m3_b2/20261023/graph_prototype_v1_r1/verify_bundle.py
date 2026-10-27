"""Read-only local bundle/source checks, no imports of torch/model/hardware."""
import ast,hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=Path('/Users/moblumen/Desktop/CoOverlap')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify():
    spec=json.loads((HERE/'FINGERPRINTS.json').read_text());issues=[]
    for rel,want in spec['files'].items():
        p=HERE/rel
        if not p.is_file() or sha(p)!=want:issues.append('bundle:'+rel)
    for rel,want in spec['historical_unchanged'].items():
        p=ROOT/rel
        if not p.is_file() or sha(p)!=want:issues.append('history:'+rel)
    for p in (HERE/'deployment').glob('*.py'):ast.parse(p.read_text(),filename=str(p))
    sys.path.insert(0,str(HERE/'deployment'))
    import graph_control,graph_plan
    payload=graph_control.package_files(HERE/'deployment')
    config=json.loads((HERE/'deployment/CONFIG.json').read_text())
    if config!=graph_plan.protocol():issues.append('CONFIG!=protocol')
    if json.loads((HERE/'DRY_RUN.json').read_text())!=config:issues.append('dry-run stale')
    cpu=json.loads((HERE/'CPU_RESULTS.json').read_text())
    if not cpu['pass_'] or cpu['tests_run']!=30:issues.append('CPU evidence')
    return dict(pass_=not issues,issues=issues,package_artifacts=len(spec['files']),payload_files=len(payload),
                historical_files=len(spec['historical_unchanged']),GPU_capture='NOT_RUN',GPU_numerical='NOT_RUN',GPU_performance='NOT_RUN',
                scope='specified source/metadata files, not an entire historical raw archive rehash')
if __name__=='__main__':
    result=verify();print(json.dumps(result,indent=2));sys.exit(0 if result['pass_'] else 1)
