"""One immutable observation-only pair protocol; CPU import has no CUDA calls."""
from m1_completion_core_v4 import pair_config as old_pair_config
PROTOCOL='m1_pair_close_20261016_v5'
MODES=['serial','ordinary','fixed','return']
NORMAL_ORDER=MODES+MODES[1:]+MODES[:1]+MODES[2:]+MODES[:2]
def pair_config():
    c=old_pair_config();c['protocol']=PROTOCOL
    c['pair'].update(formal_order=NORMAL_ORDER,diagnostic_order=MODES,
        observation='independent timed events; generation-bound conservative Host brackets',
        normal_capture='collection OFF in a Nsight-launched process; inactive instrumentation overhead UNKNOWN',
        diagnostic_capture='single M1_PAIR_TRACE range, never pooled with normal samples')
    c['diagnostic_ledger']=dict(Experts=4,Contexts=4)
    c['total_ledger']=dict(Experts=19,Contexts=20,SM_probe_kernels=2,
        Autotune='two original per-slot runners; internal calibration kernels separately logged')
    c['scope_timeout_s']=420;c['maximum_model_processes']=1
    return c
def validate_config(c):
    if c!=pair_config():raise ValueError('configuration differs from frozen one-process protocol')
    return c['total_ledger']
