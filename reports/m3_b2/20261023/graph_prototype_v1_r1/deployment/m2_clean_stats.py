"""Offline-only detailed rows and summary; never called in a timed window."""
import csv
from pathlib import Path
from period_obligation_stats import classify,counts


def augment(segment):
    conf=segment['manifest'];t0=segment['t0_ns'];P=conf['period_ns']
    if t0 is None:return dict(status='NOT_RUN',planned_cycles=conf['cycles'],k_min=None)
    es=segment['experts'];units=segment['units'];pubs=segment['published']
    rows=segment['statistics']['cycles']
    def get(mapping,key):
        return mapping.get(key,mapping.get(str(key)))
    for row in rows:
        j=row['cycle'];e=get(es,j);u=units.get((j//2,j%2))
        if u is None:u=units.get(str((j//2,j%2)))
        row.update(expert_completion_lower_ns=e[0] if e else None,expert_completion_upper_ns=e[1] if e else None,
                   VLM_completion_lower_ns=u[0] if u else None,VLM_completion_upper_ns=u[1] if u else None,
                   expert_response_lower_ns=e[0]-row['release_ns'] if e else None,
                   expert_response_upper_ns=e[1]-row['release_ns'] if e else None,
                   VLM_response_lower_ns=max(0,u[0]-row['release_ns']) if u else None,
                   VLM_response_upper_ns=max(0,u[1]-row['release_ns']) if u else None,
                   VLM_already_ready_at_release=bool(u and u[1]<=row['release_ns']))
    longest=0;streak=0
    for row in rows:
        streak=streak+1 if row['status']=='FAIL' else 0;longest=max(longest,streak)
    backlog=[]
    for row in rows:
        release=row['release_ns']
        arrived=[x for x in conf['refreshes'] if t0+x['release_ns']<=release]
        pending=sum(get(pubs,x['id']) is None or get(pubs,x['id'])[1]>release for x in arrived)
        backlog.append(dict(cycle=row['cycle'],at_release_pending_refreshes=pending))
    return dict(status='AVAILABLE',longest_consecutive_definite_misses=longest,
                backlog_at_releases=backlog,max_backlog_at_releases=max(x['at_release_pending_refreshes'] for x in backlog),expert_counts=counts([x['expert_status'] for x in rows]),
                VLM_counts=counts([x['unit_status'] for x in rows]),
                completed_Experts=len(es),completed_units=len(units),published_refreshes=len(pubs),
                W_assigned_on_time=sum(x['W_assigned_on_time'] for x in rows),
                W_completed_in_window=sum(x['W_completed_in_window'] for x in rows),
                k_min=None,note='early B2 has VLM obligation response zero; raw completion times retained')


def write_tables(segment,out):
    path=Path(out);path.mkdir(exist_ok=True)
    for name,rows in [('cycles',segment['statistics']['cycles']),('refreshes',segment['statistics']['refreshes']),('operations',segment.get('operations',[]))]:
        if not rows:continue
        fields=sorted({k for row in rows for k in row})
        with (path/(name+'.csv')).open('x',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
