"""Shared real replay entry orchestration; scheduler is the frozen run_segment."""
from m2_executor import DEFAULT_PLAN,VersionedKV
from m2_clean_core import retention_layout,gate_retention_layout
from m2_clean_stats import augment,write_tables
from m3_b2_core import run_segment
from m3_b3_orchestrate import mark_active
from graph_backend import GraphBoundaryBackend
from graph_plan import RUN,manifest


def run_segments(device,snaps,records,out,clock,require,active):
    summary=[]
    for c,r in zip(RUN,records):
        device.select_engine(c['engine']);device.set_segment_id(c['id'])
        b=GraphBoundaryBackend(device,snaps,'performance',layout=retention_layout(8),plan=DEFAULT_PLAN)
        m=VersionedKV(DEFAULT_PLAN)
        mark_active(active,'segment',c['id'],DEFAULT_PLAN.id,b,m,r)
        conf=manifest()
        try:
            run_segment(m,snaps,c['policy'],b,r,clock,conf=conf,expect=manifest())
        finally:
            if r.get('t0_ns') is not None:r['metrics']=augment(r)
        result=b.validate_and_persist()
        require(result['pass_'],'complete_deferred_numerical_version_work_'+c['id'])
        require(len(r['experts'])==8 and len(r['units'])==8 and len(r['published'])==4,'full_obligations_'+c['id'])
        require(r['engine']==c['engine'] and r['mode']==c['policy'],'config_drives_engine_policy_'+c['id'])
        write_tables(r,out/c['id'])
        summary.append(dict(segment_id=c['id'],engine=c['engine'],policy=c['policy'],
                            statistics=r['statistics'],metrics=r['metrics'],validation=result))
    return summary


def version_gate(device,snaps,interleave,record,require,active):
    name='gate_interrupt' if interleave else 'gate_old_reader'
    device.select_engine('graph');device.set_segment_id(name)
    b=GraphBoundaryBackend(device,snaps,'correctness',layout=gate_retention_layout(8,DEFAULT_PLAN),plan=DEFAULT_PLAN)
    m=VersionedKV(DEFAULT_PLAN)
    mark_active(active,'gate',name,DEFAULT_PLAN.id,b,m,record)
    b.prepare(m,None,record);b.bootstrap(m,'bootstrap');b.ready(m)
    old=m.bind('E0',snaps[0].noise_sha)
    new=m.begin(1,snaps[1])
    if interleave:m.bind('hold',snaps[0].noise_sha)
    b.enter_window()
    try:
        b.stage(m,new,'R0');b.block(m,new,0,'R0/B1')
        try:m.publish(new)
        except RuntimeError:require(True,'partial_9_layer_publish_rejected')
        else:raise AssertionError('partial KV published')
        if interleave:b.expert(m,'E0',old)
        b.block(m,new,1,'R0/B2');m.publish(new)
        require(m.bind('latest',snaps[0].noise_sha)==new,'latest_published_gate')
        m.cancel_unsubmitted('latest')
        try:m.reclaim(old)
        except RuntimeError:require(True,'old_reader_reclaim_rejected')
        else:raise AssertionError('old pinned version reclaimed')
        if interleave:m.cancel_unsubmitted('hold')
        else:b.expert(m,'E0',old)
        m.reclaim(old);b.drain()
    finally:b.leave_window()
    require(len(m.journal)==(20 if interleave else 18),'two_block_gate_journal_count')
    result=b.validate_and_persist();record.update(status='PASS',journal=m.journal,validation=result)
    return result
