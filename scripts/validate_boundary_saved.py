"""Offline SHA/byte validation; no model or CUDA execution."""
from pathlib import Path
import json,hashlib,sys
p=Path(sys.argv[1]);raw=p/'raw/cooverlap_boundary_switch_20261015_01';r=json.loads((raw/'result.json').read_text());rows=[]
names=['full_reference']+[s['name'] for s in r['samples']]
for name in names:
 for tag in ['mid','final']:
  for k in ['x','K','V']:
   actual=raw/(name+'_'+tag+'_'+k+'.bin');ref=raw/('full_reference_'+tag+'_'+k+'.bin');b=actual.read_bytes();meta=json.loads(actual.with_suffix('.json').read_text());assert len(b)==meta['nbytes'] and hashlib.sha256(b).hexdigest()==meta['sha256'] and b==ref.read_bytes()
   rows.append(dict(actual=actual.name,reference=ref.name,byte_exact=True,nbytes=len(b)))
print(json.dumps(dict(status='PASS',count=len(rows),comparisons=rows),indent=2))
