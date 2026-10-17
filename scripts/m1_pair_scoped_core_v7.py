"""Same four-mode work; scoped numerical contract, independent S0/S1 outputs."""
from m1_pair_plain_core_v6 import pair_config as v6_pair_config
PROTOCOL='m1_pair_scoped_equivalence_20261016_v7'
def pair_config():
    c=v6_pair_config();c['protocol']=PROTOCOL
    c['pre_Expert_Context_check']='save actual pre-Expert x/K/V, shape and finite check; historical cross-process intermediate hashes diagnostic only'
    c['cross_process_policy']={'inputs':'fixture/images/states/language/actual-noise exact','intermediates':'shape/finite required; old byte and float differences preserved as diagnostics','outputs':'frozen independent S0 old-calibration and S1 Day2D full-reference; BF16 abs<=0.015625, FP32 abs<=0.01; no rtol/epsilon','within_process':'raw bytes exact; full/split/pair/old-KV and collector equivalence'}
    c['frozen_normalization_sha256']='4e1c8ac9120bdff33835b2dbced67a5353739f3cdf07a89e15f6239c8dec0aeb'
    c['extra_reference_ledger']={'Contexts':0,'Experts':1,'reason':'S1 full independent historical output gate; outside timing'}
    c['total_ledger']=dict(Experts=21,Contexts=21,SM_probe_kernels=2,Autotune='same original two per-slot runners; no algorithm pinning or second autotune')
    return c
def validate_config(c):
    if c!=pair_config():raise ValueError('configuration differs from scoped v7 contract')
    return c['total_ledger']
