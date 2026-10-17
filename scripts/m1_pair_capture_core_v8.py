"""Fill only missing four-mode trace; accepted v7 normal timings stay frozen."""
from m1_pair_scoped_core_v7 import pair_config as old_config
PROTOCOL='m1_pair_permission_capture_20261016_v8'
def pair_config():
    c=old_config();c['protocol']=PROTOCOL
    c['pair']['formal_order']=[];c['pair']['samples_per_mode']=0
    c['pair']['normal_capture']='reuse accepted v7 normal12; no new normal timing samples'
    c['pair']['diagnostic_capture']='late unchanged CUPTI concurrent activity adapter, one four-mode capture'
    c['timed_ledger']={'Contexts':4,'Experts':4}
    c['total_ledger']={'Contexts':9,'Experts':9,'SM_probe_kernels':2,
        'Autotune':'same original two private runners, no algorithm pinning'}
    c['capture_permission']={'uid':'nvidia','capability':'CAP_SYS_ADMIN process tree only',
        'persistent_changes':False,'normal_source_sha256':'4099856a17f0ef17f18431e24778223fbe8d2647ed2b0b58f51915495dd9f3e3','normal_source':'scoped_equivalence_20261016_v7/NORMAL_SAMPLES.csv'}
    return c
def validate_config(c):
    if c!=pair_config():raise ValueError('differs from frozen one-shot trace protocol')
    return c['total_ledger']
