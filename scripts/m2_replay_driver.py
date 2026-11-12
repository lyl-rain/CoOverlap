"""Shared finite replay order, independent of numerical backend and B1/B2 route.

Callbacks are identical in both validation orders. They return conservative
completion intervals and perform all real event, model and ownership checks.
Odd jobs reserve the fixed version with the even job, without running early.
"""
from m2_executor import replay_manifest, replay_stats


def replay(m, snapshots, mode, bootstrap, stage, block, expert, wait_release,
           clock, period_ns=240_000_000, record=None):
    if mode not in ('serial_adjacent', 'serial_resumed'):
        raise ValueError('unreviewed execution order')
    bootstrap(m, mode+'_bootstrap')
    conf=replay_manifest(period_ns);es={};us={};pubs={};active=None
    t0=clock()+10_000_000
    rec = record if record is not None else {}
    rec.update(mode=mode,status='INCOMPLETE',t0_ns=t0,manifest=conf)
    try:
        for j in range(conf['cycles']):
            wait_release(t0+conf['experts'][j]['release_ns'])
            job=mode+'_E'+str(j)
            if j%2==0:
                h=m.bind(job,snapshots[0].noise_sha,version=j//2)
                m.bind(mode+'_E'+str(j+1),snapshots[0].noise_sha,version=j//2)
            else:h=m.readers[job].handle
            if h.version!=j//2:raise RuntimeError('version trajectory changed')
            es[j]=expert(m,job,h)
            q=j//2
            if j%2==0:
                slot=1-m.current.slot
                if m.slots[slot] is not None:m.reclaim(m.slots[slot].handle)
                active=m.begin(slot,snapshots[slot]);stage(slot)
                us[q,0]=block(m,active,0,mode+'_R'+str(q)+'_B1')
            if (mode=='serial_adjacent' and j%2==0) or (mode=='serial_resumed' and j%2==1):
                us[q,1]=block(m,active,1,mode+'_R'+str(q)+'_B2')
                before=clock();m.publish(active);after=clock();pubs[q]=(before,after)
        rec['status']='PASS'
    finally:
        rec.update(journal=m.journal,statistics=replay_stats(conf,es,us,pubs,t0))
    return rec
