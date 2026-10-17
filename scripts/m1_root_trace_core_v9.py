"""Only the four missing diagnostic pairs; v4/v7 normal evidence is immutable."""
from m1_pair_capture_core_v8 import pair_config as old_config
from m1_root_trace_identity_v9 import PROTOCOL
def pair_config():
    c=old_config();c['protocol']=PROTOCOL
    c['capture_permission']=dict(uid='root only for frozen diagnostic process',capabilities=['SYS_ADMIN','DAC_OVERRIDE','DAC_READ_SEARCH'],
        explicit_cli_approval='--allow-root-diagnostic',persistent_changes=False,
        normal_source='scoped_equivalence_20261016_v7/NORMAL_SAMPLES.csv',
        normal_source_sha256='4099856a17f0ef17f18431e24778223fbe8d2647ed2b0b58f51915495dd9f3e3',
        scope='four diagnostic pairs + mandatory references/gates; no new normal timing or periodic replay')
    c['permission_smoke']=dict(processes=1,timeout_s=15,models=0,explicit_kernel_launches=0,position='before five-node setting')
    return c
def validate_config(c):
    if c!=pair_config():raise ValueError('differs from frozen root diagnostic exception')
    return c['total_ledger']
