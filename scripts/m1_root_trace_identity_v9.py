"""Explicit root exception for one diagnostic process; never a normal benchmark."""
import argparse, json, os, sys
from pathlib import Path
from m1_capture_permissions_v8 import parse_status
PROTOCOL='m1_tegra_root_trace_20261017_v9'
ROOT_MASK=(1<<21)|(1<<1)|(1<<2)  # SYS_ADMIN, DAC_OVERRIDE, DAC_READ_SEARCH

def root_prefix():
    return ['/usr/bin/setpriv','--reuid=0','--regid=0','--clear-groups',
        '--inh-caps=-all','--ambient-caps=-all',
        '--bounding-set=-all,+sys_admin,+dac_override,+dac_read_search','--no-new-privs']

def monitor_prefix():
    return ['/usr/bin/setpriv','--reuid=nvidia','--regid=nvidia','--init-groups',
        '--inh-caps=-all','--ambient-caps=-all','--bounding-set=-all','--no-new-privs']

def check_diagnostic_state(state,approval):
    if approval!=PROTOCOL:raise PermissionError('explicit root diagnostic approval token required')
    if state['Uid']!=[0]*4 or state['Gid']!=[0]*4:raise PermissionError('Tegra diagnostic root identities required')
    if any(state[k]!=ROOT_MASK for k in ('CapEff','CapPrm','CapBnd')) or state['CapInh'] or state['CapAmb'] or state['NoNewPrivs']!=1:
        raise PermissionError('unexpected diagnostic capability profile')
    return state

def require_diagnostic_root():
    s=check_diagnostic_state(parse_status(Path('/proc/self/status').read_text()),os.environ.get('COOVERLAP_ROOT_DIAGNOSTIC'))
    return dict(user='root_diagnostic_exception',uid=os.getresuid(),gid=os.getresgid(),pid=os.getpid(),capabilities=s,
        scope='only frozen same-process reference/gates and four diagnostic pairs; not normal performance samples')

def require_root_launcher():
    if os.getresuid()!=(0,0,0) or os.getresgid()!=(0,0,0) or os.environ.get('COOVERLAP_ROOT_DIAGNOSTIC')!=PROTOCOL:
        raise PermissionError('explicit one-shot root diagnostic supervisor required')
    return dict(user='root_diagnostic_supervisor',uid=os.getresuid(),gid=os.getresgid(),pid=os.getpid())

def permission_smoke(out):
    """Same adapter activation, no Torch/checkpoint/model or explicit CUDA work."""
    from delayed_activity_v6 import Collector
    out=Path(out);out.mkdir(exist_ok=False)
    identity=require_diagnostic_root();collector=None
    r=dict(identity=identity,model_processes=0,checkpoint_loaded=False,explicit_kernel_launches=0,status='INCOMPLETE')
    try:
        collector=Collector(os.environ['COOVERLAP_ACTIVITY_ADAPTER'],os.environ['COOVERLAP_ACTIVITY_SHA256'],out/'activity')
        collector.start();collector.stop();r['status']='PASS_REGISTER_ENABLE_FLUSH_ONLY'
    except BaseException as e:r.update(status='FAIL',error=repr(e));raise
    finally:
        (out/'SMOKE_RESULT.json').write_text(json.dumps(r,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--permission-smoke',required=True);a=p.parse_args()
    permission_smoke(a.permission_smoke)
