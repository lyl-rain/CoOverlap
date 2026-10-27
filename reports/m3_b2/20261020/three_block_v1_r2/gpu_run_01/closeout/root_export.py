"""Read-only capsule: user invokes this code with interactive sudo over SSH."""
import base64
import hashlib
import json
import os
import socket
import stat
import subprocess
from pathlib import Path

run = Path('/home/nvidia/rtvla/cooverlap_m3_b3_20261021/run_01')
assert os.geteuid() == 0 and socket.gethostname() == 'jyh-orin'
snapshot = run / 'clock_before.json'
st = snapshot.stat()
assert stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o600
data = snapshot.read_bytes()
obj = json.loads(data)
assert obj['schema'] == 'm1_clock_minima_v1' and obj['host'] == 'jyh-orin'
pref = json.loads((run / 'PREFLIGHT.json').read_text())
assert pref['protocol'] == 'm3_b3_three_block_v1'
assert all(all(a[k] == b[k] for k in ('path', 'min', 'max', 'target', 'available'))
           for a, b in zip(obj['nodes'], pref['hardware_before']['nodes']))
rows = []
for p in sorted(run.rglob('*')):
    if not p.is_file():
        continue
    before = p.stat()
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(chunk)
    after = p.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns)
    rows.append(dict(path=p.relative_to(run).as_posix(), bytes=before.st_size, sha256=h.hexdigest()))
try:
    journal = subprocess.run(['/usr/bin/journalctl', '-u', 'cooverlap-m3-b3-three-block-20261021-run01.service',
                              '--no-pager', '-o', 'short-iso'], capture_output=True, timeout=15)
    log = dict(returncode=journal.returncode, stdout_b64=base64.b64encode(journal.stdout).decode(),
               stderr_b64=base64.b64encode(journal.stderr).decode())
except subprocess.TimeoutExpired:
    log = dict(status='UNAVAILABLE_TIMEOUT')
packet = dict(schema='cooverlap_root_readonly_capsule_v1', host=socket.gethostname(), uid=os.geteuid(),
              run=str(run), no_model=True, no_hardware_write=True, no_scope=True,
              snapshot=dict(path='clock_before.json', bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                            mode=oct(stat.S_IMODE(st.st_mode)), uid=st.st_uid, gid=st.st_gid,
                            content_b64=base64.b64encode(data).decode()), files=rows, journal=log)
print('ROOT_EVIDENCE_EXPORT_BEGIN', flush=True)
print(json.dumps(packet, sort_keys=True), flush=True)
print('ROOT_EVIDENCE_EXPORT_COMPLETE', flush=True)
