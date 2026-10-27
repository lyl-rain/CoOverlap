"""CPU-only fixed-period obligation ledger and bounded Host completion statistics."""
def classify(lo, hi, deadline):
    if lo is None or hi is None:return 'INCOMPLETE'
    if not lo<=hi:raise ValueError('invalid completion bounds')
    if lo>deadline:return 'FAIL'
    if hi<=deadline:return 'PASS'
    return 'UNCERTAIN'

def jobs(t0,period_ns):
    experts=[dict(id=j,unit_id=f'E{j}',release_ns=t0+j*period_ns,deadline_ns=t0+(j+1)*period_ns,status='NOT_RELEASED',bound_version='v0',snapshot='S0') for j in range(8)]
    refreshes=[dict(id=m,unit_id=f'R{m}',release_ns=t0+2*m*period_ns,deadline_ns=t0+(2*m+2)*period_ns,status='NOT_RELEASED',phase=0,snapshot='S1',target_periods=2) for m in range(4)]
    return experts,refreshes

def cycle_rows(segment):
    P=segment['P_ms']*1_000_000;t0=segment['t0_ns']
    experts={e['id']:e for e in segment['experts']}
    units={(b['id'],b['unit']):b for b in segment.get('unit_completions',[])}
    rows=[]
    for j in range(8):
        m=j//2;unit='B1' if j%2==0 else 'B2';e=experts.get(j,{});u=units.get((m,unit),{})
        el,eh=e.get('completion_lower_ns'),e.get('completion_observed_ns')
        ul,uh=u.get('completion_lower_ns'),u.get('completion_observed_ns')
        deadline=t0+(j+1)*P;rel=t0+j*P
        low=max(el,ul) if el is not None and ul is not None else None
        high=max(eh,uh) if eh is not None and uh is not None else None
        rows.append(dict(cycle=j,Expert_id=f'E{j}',required_unit_id=f'R{m}/{unit}',release_ns=rel,deadline_ns=deadline,expert_lower_ns=el,expert_upper_ns=eh,unit_lower_ns=ul,unit_upper_ns=uh,expert_status=classify(el,eh,deadline),VLM_status=classify(ul,uh,deadline),cycle_status=classify(low,high,deadline),response_lower_ms=(low-rel)/1e6 if low is not None else None,response_upper_ms=(high-rel)/1e6 if high is not None else None))
    return rows

def counts(statuses):
    out={k:statuses.count(k) for k in ['PASS','FAIL','UNCERTAIN','INCOMPLETE']};out['denominator']=len(statuses)
    streak=best=0
    for s in statuses:streak=streak+1 if s=='FAIL' else 0;best=max(best,streak)
    out['longest_consecutive_definite_miss']=best
    return out
