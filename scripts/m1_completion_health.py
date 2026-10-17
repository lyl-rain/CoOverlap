"""Read-only batch health guard. No frequency/power writes."""
import json,time
from pathlib import Path
from m1_clock_scope import state

def check_no_models():
    found=[]
    for p in Path('/proc').glob('[0-9]*/cmdline'):
        try:args=p.read_bytes().decode(errors='replace').split('\0')
        except (OSError,PermissionError):continue
        if any(Path(v).name.startswith('pi05_') for v in args) or ('nsys' in [Path(v).name for v in args] and 'profile' in args) or 'torchrun' in [Path(v).name for v in args]:found.append(dict(pid=p.parent.name,args=args))
    if found:raise RuntimeError('other known model/profiler process: '+json.dumps(found))
    return 'no matching known model/profiler; not exhaustive GPU ownership proof'

def check_hardware():
    rows=state()
    if any(v['min']!=v['target'] or v['max']!=v['target'] for v in rows):raise RuntimeError('reviewed clock limits not applied')
    temp=int(Path('/sys/devices/virtual/thermal/thermal_zone0/temp').read_text())
    if temp>=80000:raise RuntimeError('thermal safety stop >=80C; raw data retained')
    mem={l.split(':')[0]:int(l.split()[1]) for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')}
    if mem['MemAvailable']<12*1024**2:raise RuntimeError('available memory below12GiB')
    return dict(monotonic_ns=time.monotonic_ns(),limits=rows,temp_mC=temp,MemAvailable_kB=mem['MemAvailable'])
