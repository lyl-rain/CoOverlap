"""CPU-only validation of the prepared M2 reproducibility diagnostic. No GPU, no model.

Checks the script contract, the refusal paths, the wrapper guard, and re-derives
the archived numbers quoted in FORENSICS.md from the raw bytes.
"""
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT/'scripts'
REPORTS = ROOT/'reports/m2_common/20261020'
BOARD = REPORTS/'gpu_run_01/board'
DIAG = SCRIPTS/'pi05_m2_repro_diag.py'
WRAPPER = SCRIPTS/'run_m2_repro_diag.sh'
CHEM = []


def check(name, ok, detail=''):
    CHEM.append(dict(name=name, pass_=bool(ok), detail=detail))
    print(('PASS ' if ok else 'FAIL ')+name+(' :: '+str(detail) if detail else ''))
    return ok


def bf16_words(path):
    data = Path(path).read_bytes()
    return [int.from_bytes(data[i:i+2], 'little') for i in range(0, len(data), 2)]


def bf16_float(word):
    return struct_float((word << 16) & 0xFFFFFFFF)


def struct_float(bits):
    import struct
    return struct.unpack('<f', struct.pack('<I', bits))[0]


def max_abs(a_path, b_path):
    a, b = bf16_words(a_path), bf16_words(b_path)
    assert len(a) == len(b)
    return max(abs(bf16_float(x)-bf16_float(y)) for x, y in zip(a, b))


def main():
    text = DIAG.read_text()
    # 1. No top-level torch/CUDA import: dry-run must be CPU-safe.
    top_level = [line for line in text.splitlines()
                 if re.match(r'^(import|from)\s+(torch|flash_rt|numpy)', line)]
    check('no_top_level_torch_import', not top_level, top_level)
    # 2. Dry-run must not even be able to import torch.
    blocker = Path(ROOT/'reports/m2_common/20261020/.torch_blocker_probe.py')
    blocker.write_text(
        "import sys, runpy\n"
        "class B:\n"
        "    def find_module(self, name, path=None):\n"
        "        return self if name.split('.')[0] in ('torch','flash_rt','numpy') else None\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('torch','flash_rt','numpy'):\n"
        "            raise ImportError('blocked '+name)\n"
        "sys.meta_path.insert(0, B())\n"
        "sys.argv=['pi05_m2_repro_diag.py','--dry-run']\n"
        "runpy.run_path(%r, run_name='__main__')\n" % str(DIAG))
    try:
        out = subprocess.run([sys.executable, str(blocker)], capture_output=True, text=True)
    finally:
        blocker.unlink()
    ok = out.returncode == 0
    try:
        proto = json.loads(out.stdout)
    except Exception:
        proto = {}
    check('dry_run_without_torch', ok and proto.get('id') == 'm2_repro_diag_01',
          out.stderr.strip()[:200])
    # 3. Work ledger declared consistently with the phase design.
    work = proto.get('work', {})
    check('declared_work_matches_phases',
          work.get('Contexts') == 4 and work.get('Experts') == 3
          and work.get('full_pipelines') == 1 and work.get('warmup_contexts') == 1,
          work)
    check('single_process_zero_retry',
          proto.get('model_process_limit') == 1 and proto.get('retry_limit') == 0,
          [proto.get('model_process_limit'), proto.get('retry_limit')])
    check('no_numeric_gate_inside_process',
          'none in-process' in str(proto.get('numeric_gate', '')),
          proto.get('numeric_gate'))
    # 4. Refusals: no authorization flag; missing credential.
    tmp = ROOT/'reports/m2_common/20261020/.refusal_probe'
    tmp.mkdir(exist_ok=True)
    try:
        r1 = subprocess.run([sys.executable, str(DIAG), '--reference', str(tmp), '--out',
                             str(tmp/'run')], capture_output=True, text=True)
        check('refuses_without_authorization',
              r1.returncode != 0 and 'authorization' in (r1.stderr+r1.stdout),
              (r1.stderr.strip().splitlines() or [''])[-1][:160])
        r2 = subprocess.run([sys.executable, str(DIAG), '--approved-m2-repro-diag-01',
                             '--reference', str(tmp), '--out', str(tmp/'run2')],
                            capture_output=True, text=True)
        check('refuses_without_credential',
              r2.returncode != 0 and 'credential' in (r2.stderr+r2.stdout),
              (r2.stderr.strip().splitlines() or [''])[-1][:160])
    finally:
        for leftover in (tmp/'run', tmp/'run2'):
            if leftover.exists():
                import shutil
                shutil.rmtree(leftover)
        tmp.rmdir()
    # 5. Wrapper refuses without the specific flag.
    r3 = subprocess.run(['bash', str(WRAPPER)], capture_output=True, text=True)
    check('wrapper_refuses_without_flag', r3.returncode == 2 and 'STOP' in r3.stderr,
          r3.stderr.strip()[:120])
    check('wrapper_declares_one_process_and_bound',
          'approved-m2-repro-diag-01' in WRAPPER.read_text()
          and 'timeout --signal=TERM --kill-after=10s 300s' in WRAPPER.read_text(), '')
    # 6. Re-derive the archived numbers quoted in FORENSICS.md.
    actual = max_abs(BOARD/'run/ref0_raw.bin', BOARD/'reference/reference_S0_raw_bf16.bin')
    check('archived_S0_gate_max_abs_0.2041015625', actual == 0.2041015625, repr(actual))
    import numpy as np
    ref = np.load(ROOT/'data/fixtures/pi05_candidate/reference.npz', allow_pickle=False)
    day2b = ROOT/'reports/m2_common/20261020/.day2b_raw.bin'
    day2b.write_bytes(ref['reference_raw_bf16_bytes'].tobytes())
    try:
        hist = max_abs(BOARD/'reference/reference_S0_raw_bf16.bin', day2b)
    finally:
        day2b.unlink()
    check('historical_cross_reference_max_abs_0.015625', hist == 0.015625, repr(hist))
    # mean_abs ratio 7.4x quoted in F2
    def mean_abs(a_path, b_path):
        a, b = bf16_words(a_path), bf16_words(b_path)
        return sum(abs(bf16_float(x)-bf16_float(y)) for x, y in zip(a, b))/len(a)
    d2b = ROOT/'reports/m2_common/20261020/.day2b_raw2.bin'
    d2b.write_bytes(ref['reference_raw_bf16_bytes'].tobytes())
    try:
        hist_mean = mean_abs(BOARD/'reference/reference_S0_raw_bf16.bin', d2b)
    finally:
        d2b.unlink()
    ours_mean = mean_abs(BOARD/'run/ref0_raw.bin', BOARD/'reference/reference_S0_raw_bf16.bin')
    ratio = ours_mean/hist_mean
    check('drift_ratio_about_7.4', 7.2 < ratio < 7.6, round(ratio, 3))
    # 7. Autotune evidence quoted in F3/F4.
    log = (BOARD/'ATTEMPT_USED/model.log').read_text(errors='replace')
    best = [int(x) for x in re.findall(r'best=(\d+) \(', log)]
    times = [float(x) for x in re.findall(r'best=\d+ \(([\d.]+) us\)', log)]
    check('run01_has_36_autotune_items', len(best) == 36 and len(times) == 36, len(best))
    check('run01_item1_anomaly_208us_best7', best[0] == 7 and times[0] > 200,
          [best[0], times[0]])
    check('run01_second_runner_item1_about_66us', best[18] == 0 and 60 < times[18] < 70,
          [best[18], times[18]])
    v4log = (ROOT/'reports/m1_acceptance/completion_20261016_v4/board/archive/'
             'results_20261016T054314Z_770131/calibration.log').read_text(errors='replace')
    v4best = [int(x) for x in re.findall(r'best=(\d+) \(', v4log)]
    v4time = [float(x) for x in re.findall(r'best=\d+ \(([\d.]+) us\)', v4log)]
    check('historical_item1_best0_about_66us', v4best[0] == 0 and 60 < v4time[0] < 70,
          [v4best[0], v4time[0]])
    check('item3_differs_from_all_history', best[2] == 1 and best[20] == 1 and v4best[2] == 2,
          [best[2], best[20], v4best[2]])
    # 8. Frozen deployment bundle, when prepared, must be self-consistent.
    deploy = REPORTS/'repro_diag_01/deployment'
    if deploy.exists():
        manifest = deploy/'DEPLOY_SHA256.txt'
        ok = manifest.exists()
        listed = {}
        if ok:
            for line in manifest.read_text().splitlines():
                digest, name = line.split()
                listed[name.lstrip('*')] = digest
            import hashlib
            for name, digest in listed.items():
                p = deploy/name
                ok = ok and p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == digest
        check('deployment_sha_manifest_consistent', ok, len(listed))
        for name in ('pi05_m2_repro_diag.py', 'm2_pi05_ops.py', 'm2_executor.py',
                     'period_obligation_stats.py', 'pi05_dual_slot_adapter.py',
                     'run_m2_repro_diag.sh'):
            src = SCRIPTS/name
            dst = deploy/name
            check('deployment_copy_current_'+name,
                  dst.exists() and src.read_bytes() == dst.read_bytes(), '')
    failed = [c for c in CHEM if not c['pass_']]
    print(json.dumps(dict(status='PASS' if not failed else 'FAIL', checks=len(CHEM),
                          failed=[c['name'] for c in failed]), indent=1))
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
