"""Offline official counts: declaration denominators survive partial/not-started runs."""
import argparse,json,hashlib,ast
from pathlib import Path
from graph_plan import RUN,manifest
from m2_executor import replay_stats
from period_obligation_stats import counts


def evaluate(report):
    if len(report.get('segments',[]))!=8:raise ValueError('all eight declaration records required')
    out=[]
    for c,r in zip(RUN,report['segments']):
        for key in ('id','cell','plan','engine','policy'):
            if r.get(key)!=c[key]:raise ValueError('segment identity mismatch: '+key)
        started=r.get('t0_ns') is not None
        if not started and any(r.get(k) for k in ('experts','units','published')):
            raise ValueError('jobs without manifest/t0')
        conf=manifest()
        if started and r.get('manifest')!=conf:raise ValueError('manifest changed')
        es={int(k):v for k,v in r.get('experts',{}).items()}
        us={(ast.literal_eval(k) if isinstance(k,str) else k):v for k,v in r.get('units',{}).items()}
        ps={int(k):v for k,v in r.get('published',{}).items()}
        stats=replay_stats(conf,es,us,ps,r.get('t0_ns') or 0)
        # replay_stats also handles stringified tuple keys after JSON load.
        es=counts([x['expert_status'] for x in stats['cycles']]);cs=stats['cycle_counts']
        rs=counts([x['status'] for x in stats['refreshes']])
        if not started:
            for row in stats['cycles']+stats['refreshes']:
                row['time_origin']='DECLARED_RELATIVE_NOT_STARTED'
        out.append(dict(segment_id=c['id'],cell=c['cell'],engine=c['engine'],policy=c['policy'],
                        started=started,Expert=es,Cycle=cs,Refresh=rs,statistics=stats))
    total={}
    for typ in ('Expert','Cycle','Refresh'):
        total[typ]={key:sum(x[typ].get(key,0) for x in out) for key in ('PASS','FAIL','UNCERTAIN','INCOMPLETE','denominator')}
    return dict(scope='official sample outcomes only; correctness and hardware recovery separate',segments=out,totals=total)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--result',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    data=a.result.read_bytes();out=evaluate(json.loads(data));out['result_sha256']=hashlib.sha256(data).hexdigest()
    with a.out.open('x') as f:json.dump(out,f,indent=2)
if __name__=='__main__':main()
