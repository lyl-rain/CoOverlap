"""Read-only verification; no self-hash or result-file hash cycle."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[3] # project/reports/m3_b2/date/package
# Resolve formal external inputs even when verifying a temporary staging copy.
FORMAL=Path('/Users/moblumen/Desktop/CoOverlap')

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    spec=json.loads((ROOT/'FINGERPRINTS.json').read_text());issues=[]
    for rel,expected in spec['files'].items():
        p=ROOT/rel
        if not p.is_file() or sha(p)!=expected:issues.append(dict(kind='package',path=rel))
    for rel,expected in spec['external_unchanged'].items():
        p=FORMAL/rel
        if not p.is_file() or sha(p)!=expected:issues.append(dict(kind='external',path=rel))
    coverage=json.loads((ROOT/'outputs/SEARCH_COVERAGE.json').read_text())
    for r in coverage['segments']:
        if r['pruned_nodes']!=0 or r['memoization']!='DISABLED':issues.append(dict(kind='unexpected_pruning',path=r['segment_id']))
        if r['search_complete']!=(r['stop_reason']=='COMPLETE'):issues.append(dict(kind='classification',path=r['segment_id']))
        if r['stop_reason']!='COMPLETE' and r['pending_prefixes']==0:issues.append(dict(kind='missing_frontier',path=r['segment_id']))
    cpu=json.loads((ROOT/'CPU_RESULTS.json').read_text())
    if not cpu['pass_'] or cpu['tests_run']!=19:issues.append(dict(kind='CPU'))
    result=dict(pass_=not issues,package_files=len(spec['files']),external_files=len(spec['external_unchanged']),issues=issues,
                coverage=coverage['summary'],scope='local artifacts and specified external files; not GPU validation, not a full historical archive rehash')
    print(json.dumps(result,indent=2));return 0 if not issues else 1
if __name__=='__main__':sys.exit(main())
