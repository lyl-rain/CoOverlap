"""Fixed symmetric Graph experiment. Pure CPU configuration and budget."""
from m2_executor import DEFAULT_PLAN,replay_manifest
from m2_clean_core import retention_layout,gate_retention_layout,FULL,MID,X
from m3_b2_core import BINDING
PROTOCOL='m3_symmetric_graph_prototype_v1_r1'
CYCLES=8
P=180_000_000
CELLS={'A':dict(engine='eager',policy='serial_context'),
       'B':dict(engine='eager',policy='b2_boundary'),
       'C':dict(engine='graph',policy='serial_context'),
       'D':dict(engine='graph',policy='b2_boundary')}
RUN=[dict(id='p%d_%s'%(1 if i<4 else 2,c),cell=c,plan=DEFAULT_PLAN.id,**CELLS[c])
     for i,c in enumerate('ABCDDCBA')]


def manifest():
    x=replay_manifest(P,CYCLES)
    for e in x['experts']:
        e['release_ns']+=15_000_000;e['deadline_ns']+=15_000_000
    x.update(schema=PROTOCOL,phase_ns=15_000_000,binding=BINDING,
             block_plans={DEFAULT_PLAN.id:DEFAULT_PLAN.summary()})
    return x


def budget():
    l=retention_layout(CYCLES);g=gate_retention_layout(CYCLES,DEFAULT_PLAN)
    # Full GPU forward work, exclusive of capture host invocations/autotune.
    phases=[dict(id='warmup',C=2,E=0),dict(id='references',C=2,E=2),
            dict(id='D1_original_pipeline',C=1,E=1),
            dict(id='stream_eager_gates',C=2,E=2),dict(id='graph_numerical_gates',C=2,E=2),
            dict(id='version_gates_with_bootstrap',C=4,E=2),
            dict(id='segment_bootstraps',C=8,E=0),dict(id='timed',C=32,E=64)]
    # Each persisted snapshot is one x+effective K/V, NEVER add a binary total
    # together with its already included components.
    components=dict(timed_retention=8*l['nbytes'],version_gate_retention=2*g['nbytes'],
                    initial_snapshots=10*2*FULL,bootstrap_snapshots=10*FULL,
                    preparation_reference_snapshots=2*(FULL+MID)+FULL,
                    graph_stream_gate_snapshots=4*(MID+FULL),
                    prep_raw_actions=3*(3200+1400),
                    metadata_logs_allowance=32*1024**2,
                    temporary_partial_retention=l['nbytes'])
    subtotal=sum(components.values());headroom=(subtotal+9)//10
    return dict(phase_work=phases,total_C=sum(x['C'] for x in phases),total_E=sum(x['E'] for x in phases),
                observed_python_calls=dict(language=32,vision27=32,encoder=576,decoder=6840,rows=7480,
                                           capture_host_rows=400,direct_GPU_forward_rows=7080),
                graph_replay_launches=76,
                capture=dict(instances=6,host_context_equivalents=2,host_Expert10_equivalents=2,
                             GPU_forward_equivalents=0,note='capture records GPU work; forward launches counted separately; no hidden warmups'),
                autotune=dict(runners=2,requests=36,source_bound_matmul_attempts=7488,
                              observed_request_logs='retained; internal attempts not directly counted'),
                bank_bytes=l['nbytes'],pinned_bytes=l['nbytes'],entries=l['count'],
                gate_bank_bytes=g['nbytes'],gate_entries=g['count'],
                static_buffers='existing model slots reused, no additional input/KV copies allocated for Graph',
                graph_extra_memory_cap_bytes=2*1024**3,graph_pool_bytes=None,graph_pool_status='UNKNOWN until capture; free-memory floor checked after each unit',
                disk=dict(components=components,subtotal=subtotal,headroom_10_percent=headroom,
                          estimate_bytes=subtotal+headroom,admission_bytes=12*1024**3),
                time=dict(period_span_sum_s=8*CYCLES*P/1e9,last_release_offset_s=((CYCLES-1)*P+15_000_000)/1e9,
                          last_deadline_offset_s=(CYCLES*P+15_000_000)/1e9,declared_deadline_span_sum_s=8*(CYCLES*P+15_000_000)/1e9,internal_s=170,outer_s=180,grace_s=10,
                          scope_runtime_s=340,scope_start_s=15,scope_stop_s=60,scope_max_s=420,
                          model_processes=1,scope_count=1,retries=0))


def protocol():
    return dict(id=PROTOCOL,status='PREPARED_NOT_APPROVED_NOT_RUN',candidates=RUN,manifest=manifest(),
                plan=DEFAULT_PLAN.summary(),lead_ns=10_000_000,quiet=True,workers=0,
                queue_depth=1,graph_instances=6,stream='one explicit stream shared by Eager and Graph',
                budget=budget(),numerical='D1 strict; all Graph gates byte exact; cross-process report only')
