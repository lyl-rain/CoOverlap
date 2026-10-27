"""CPU-only manifest builder; no model, CUDA, SSH or hardware calls."""
from pathlib import Path
import hashlib,json,sys
HERE=Path(__file__).resolve().parent;D=HERE/'deployment'
sys.path.insert(0,str(D))
from graph_plan import protocol,budget
for n,v in [('CONFIG.json',protocol()),('BUDGET.json',budget())]:
 (D/n).write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
files=sorted(f for f in D.rglob('*') if f.is_file() and f.name!='DEPLOY_SHA256.txt' and '__pycache__' not in f.parts and 'run_01' not in f.parts)
(D/'DEPLOY_SHA256.txt').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+str(f.relative_to(D))+'\n' for f in files))
print('deployment payload files',len(files))
