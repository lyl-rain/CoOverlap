"""One-shot nvidia process capability. No persistent file/user/driver changes."""
import argparse, ctypes, json, os, sys
from pathlib import Path
ADMIN=1<<21
FIELDS=('CapInh','CapPrm','CapEff','CapBnd','CapAmb')

def parse_status(text):
    rows=dict(line.split(':',1) for line in text.splitlines() if ':' in line)
    return {**{k:int(rows[k].strip(),16) for k in FIELDS},
            'NoNewPrivs':int(rows['NoNewPrivs'].strip()),
            'Uid':list(map(int,rows['Uid'].split())), 'Gid':list(map(int,rows['Gid'].split()))}

def check_profile(state,uid,gid):
    if uid==0 or state['Uid']!=[uid]*4 or state['Gid']!=[gid]*4:
        raise PermissionError('real/effective/saved/fs uid/gid must all be nvidia, never root')
    if any(state[k]!=ADMIN for k in FIELDS) or state['NoNewPrivs']!=1:
        raise PermissionError('only scoped CAP_SYS_ADMIN and no-new-privileges required')
    return state

def require_scoped_permission():
    import pwd
    n=pwd.getpwnam('nvidia')
    s=check_profile(parse_status(Path('/proc/self/status').read_text()),n.pw_uid,n.pw_gid)
    return dict(pid=os.getpid(),uid=os.getresuid(),gid=os.getresgid(),capabilities=s,
        policy='temporary process-tree CAP_SYS_ADMIN only; no file capability, group or driver modification')

def launch_prefix():
    return ['/usr/bin/setpriv','--reuid=nvidia','--regid=nvidia','--init-groups',
        '--inh-caps=-all,+sys_admin','--ambient-caps=-all,+sys_admin',
        '--bounding-set=-all,+sys_admin','--no-new-privs']

def drop_all_exec(argv):
    # Self-revocation needs no CAP_SETPCAP; clearing permitted also clears ambient.
    class Header(ctypes.Structure):_fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int)]
    class Data(ctypes.Structure):_fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
    lib=ctypes.CDLL(None,use_errno=True);h=Header(0x20080522,0);d=(Data*2)()
    if lib.capset(ctypes.byref(h),ctypes.byref(d))!=0:raise OSError(ctypes.get_errno(),'capset self revoke')
    if lib.prctl(47,4,0,0,0)!=0:raise OSError(ctypes.get_errno(),'ambient clear')
    s=parse_status(Path('/proc/self/status').read_text())
    if any(s[k] for k in ('CapInh','CapPrm','CapEff','CapAmb')) or s['NoNewPrivs']!=1:
        raise PermissionError('monitor failed to revoke capabilities')
    print('MONITOR_CAPABILITIES_DROPPED '+json.dumps(s),file=sys.stderr,flush=True)
    if not argv or not Path(argv[0]).is_absolute():raise ValueError('absolute executable required')
    os.execv(argv[0],argv)

if __name__=='__main__':
    if '--drop-all-exec' in sys.argv:drop_all_exec(sys.argv[sys.argv.index('--drop-all-exec')+1:])
    elif sys.argv[1:]==['--check']:print(json.dumps(require_scoped_permission()))
    else:raise SystemExit('use --check or --drop-all-exec ABSOLUTE_COMMAND ...')
