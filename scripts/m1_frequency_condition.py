"""CPU-only classification of sampled limits versus reported current rates."""
import json
from pathlib import Path
def assess(driver_samples,root_samples,start_ns,end_ns):
    actual=[s for s in driver_samples if start_ns<=s['monotonic_ns']<=end_ns]
    privileged=[s for s in root_samples if start_ns<=s['monotonic_ns']<=end_ns]
    issues=[]
    for s in actual:
        for r in s['limits']:
            if r['min']!=r['target'] or r['max']!=r['target']:issues.append('REQUEST_LIMIT_MISMATCH:'+r['name'])
            if r['cur']!=r['target']:issues.append('REPORTED_CURRENT_MISMATCH:'+r['name'])
    bpmp=[s for s in privileged if s.get('emc_bpmp_status')=='READ']
    if any(s['emc_bpmp_rate_hz']!=3199000000 for s in bpmp):issues.append('BPMP_EMC_RATE_MISMATCH')
    stamps=sorted(s['monotonic_ns'] for s in privileged)
    gaps=[b-a for a,b in zip([start_ns]+stamps,stamps+[end_ns])]
    ds=sorted(s['monotonic_ns'] for s in actual);dgaps=[b-a for a,b in zip([start_ns]+ds,ds+[end_ns])]
    missing=not actual or not privileged or len(bpmp)!=len(privileged) or max(gaps+dgaps,default=end_ns-start_ns)>2_500_000_000
    status='NOT_MET' if issues else 'UNKNOWN' if missing else 'SATISFIED_SAMPLED'
    return dict(status=status,issues=sorted(set(issues)),driver_samples=len(actual),root_samples=len(privileged),bpmp_samples=len(bpmp),missing_or_sparse=missing,scope='only sampled timestamps; no continuous physical-clock guarantee',driver_current_source='cpufreq/devfreq cur; separate from min/max and bwmgr target_freq',independent_EMC_source='read-only BPMP clk/emc/rate; UNKNOWN if absent or denied')

def read_root_samples(path):
    if not path:return []
    try:lines=Path(path).read_text().splitlines()
    except OSError:return []
    rows=[]
    for line in lines:
        try:rows.append(json.loads(line))
        except json.JSONDecodeError:pass # concurrent final partial line not a sample
    return rows
