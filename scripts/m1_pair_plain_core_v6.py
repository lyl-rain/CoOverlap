"""Plain v4 startup + observation-only pair protocol, one model attempt."""
from m1_completion_core_v4 import pair_config as old_pair_config
PROTOCOL='m1_pair_plain_20261016_v6'
MODES=['serial','ordinary','fixed','return']
NORMAL_ORDER=MODES+MODES[1:]+MODES[:1]+MODES[2:]+MODES[:2]
def pair_config():
    c=old_pair_config();c['protocol']=PROTOCOL
    c['pair'].update(formal_order=NORMAL_ORDER,diagnostic_order=MODES,
        observation='generation-bound conservative Host brackets; independent timed mathematical/retention Events',
        normal_capture='no activity collector; ordinary Python startup, no nsys wrapper',
        diagnostic_capture='late in-process concurrent activity collection only after normal samples',
        collector_reference='one full sequential S0 Context + Expert after collector enable; exact against pre-enable process reference')
    c['diagnostic_ledger']=dict(Experts=4,Contexts=4)
    c['collector_reference_ledger']=dict(Experts=1,Contexts=1)
    c['total_ledger']=dict(Experts=20,Contexts=21,SM_probe_kernels=2,
        Autotune='two original per-slot runners; no recapture or second Autotune after collector enable')
    c['scope_timeout_s']=420;c['maximum_model_processes']=1
    c['pre_Expert_Context_check']='same v4 readback, frozen x/K/V exact before Decoder launch'
    return c
def validate_config(c):
    if c!=pair_config():raise ValueError('configuration differs from frozen plain-start protocol')
    return c['total_ledger']
