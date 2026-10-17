"""Offline raw-byte/metadata verification of a saved isolated-limit run."""
from pathlib import Path
import sys,json,hashlib
p=Path(sys.argv[1]);raw=p/'raw/cooverlap_isolated_limit_20261015_01';r=json.loads((raw/'result.json').read_text());rows=[]
for s in r['samples']:
 base='full_Context_reference_0' if s['kind']=='Context' else 'full_Expert_reference_0'
 for field in ['x','K','V'] if s['kind']=='Context' else ['raw']:
  a=raw/(s['name']+'_'+field+'.bin');b=raw/(base+'_'+field+'.bin');v=a.read_bytes();meta=json.loads(a.with_suffix('.json').read_text())
  assert hashlib.sha256(v).hexdigest()==meta['sha256'] and len(v)==meta['nbytes'] and v==b.read_bytes()
  rows.append(dict(actual=a.name,reference=b.name,byte_exact=True,nbytes=len(v)))
print(json.dumps(dict(status='PASS',comparisons=rows,count=len(rows)),indent=2))
