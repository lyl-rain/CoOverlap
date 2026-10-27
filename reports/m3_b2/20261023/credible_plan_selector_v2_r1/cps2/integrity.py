"""Frozen source identity and field-level condition checks; no CUDA imports."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def projection(r):
 p=r.get('protocol') or {}
 return dict(protocol=p.get('id'),configuration=r.get('configuration'),observation_mode=r.get('observation_mode'),design={k:(p.get('design') or {}).get(k) for k in ('lead_ms','pressure_mode','pressure_workers')},snapshots=r.get('snapshots'),source_config_fingerprints=r.get('source_config_fingerprints'),clock_limits=r.get('initial_clock_limits'),segments=[{k:s.get(k) for k in ('segment_id','plan','policy','period_ns','manifest','block_plan','observation_mode','initial_state','validation','published_valid_layers')} for s in r.get('segments',[])])
def source_check(result,label):
 expected=json.loads((HERE/'SOURCE_CONDITIONS.json').read_text()).get(label)
 if expected is None:return dict(status='INSUFFICIENT_EVIDENCE',fields=[],missing=['unknown cost source'])
 actual=projection(result);fields=[]
 for k,want in expected['condition'].items():
  got=actual.get(k);fields.append(dict(field=k,expected=want,actual=got,verdict='UNKNOWN' if got is None else ('MATCH' if got==want else 'MISMATCH')))
 canonical=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 identity=canonical==expected['canonical_sha256']
 fields.append(dict(field='source.canonical_sha256',expected=expected['canonical_sha256'],actual=canonical,verdict='MATCH' if identity else 'MISMATCH'))
 bad=[x['field'] for x in fields if x['verdict']=='MISMATCH'];missing=[x['field'] for x in fields if x['verdict']=='UNKNOWN']
 return dict(status='INVALID_EVIDENCE' if not identity else ('CONDITION_MISMATCH' if bad else ('INSUFFICIENT_EVIDENCE' if missing else 'MATCH')),fields=fields,missing=missing,mismatches=bad)
def verify_freeze(path=None):
 path=Path(path or HERE/'FREEZE.json');doc=json.loads(path.read_text());bad=[]
 for row in doc['files'].values():
  p=path.parent/row['path']
  if not p.is_file() or digest(p)!=row['sha256']:bad.append(row['path'])
 if bad:raise ValueError('INVALID_EVIDENCE: frozen files changed: '+repr(bad))
 return doc
