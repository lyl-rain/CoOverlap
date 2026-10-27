"""CPU-only validation of the prepared selection probe. No GPU, no model."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT/'scripts'
REPORTS = ROOT/'reports/m2_common/20261020'
PROBE = SCRIPTS/'pi05_m2_selection_probe.py'
WRAPPER = SCRIPTS/'run_m2_selection_probe.sh'
BUNDLE = REPORTS/'selection_probe_01/deployment'
RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append(dict(name=name, pass_=bool(ok)))
    print(('PASS ' if ok else 'FAIL ')+name+(' :: '+str(detail) if detail else ''))


def main():
    text = PROBE.read_text()
    check('no_top_level_torch_import',
          not [l for l in text.splitlines() if re.match(r'^(import|from)\s+(torch|flash_rt|numpy)', l)])
    blocker = REPORTS/'.probe_blocker.py'
    blocker.write_text(
        "import sys, runpy\n"
        "class B:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('torch','flash_rt','numpy'):\n"
        "            raise ImportError('blocked '+name)\n"
        "sys.meta_path.insert(0, B())\n"
        "sys.argv=['pi05_m2_selection_probe.py','--dry-run']\n"
        "runpy.run_path(%r, run_name='__main__')\n" % str(PROBE))
    try:
        out = subprocess.run([sys.executable, str(blocker)], capture_output=True, text=True)
    finally:
        blocker.unlink()
    proto = {}
    try:
        proto = json.loads(out.stdout)
    except Exception:
        pass
    check('dry_run_without_torch', out.returncode == 0 and proto.get('id') == 'm2_selection_probe_01',
          out.stderr.strip()[:200])
    check('declared_work_3C_2E',
          proto.get('work') == dict(Contexts=3, Experts=2, encoder_layers=54, decoder_layers=360,
                                    autotune_passes=2), proto.get('work'))
    check('single_process_zero_retry',
          proto.get('model_process_limit') == 1 and proto.get('retry_limit') == 0)
    check('no_numeric_gate_inside_process',
          'none in-process' in str(proto.get('numeric_gate', '')))
    tmp = REPORTS/'.probe_refusal'
    tmp.mkdir(exist_ok=True)
    try:
        r1 = subprocess.run([sys.executable, str(PROBE), '--reference', str(tmp)], capture_output=True, text=True)
        check('refuses_without_authorization', r1.returncode != 0 and 'authorization' in (r1.stderr+r1.stdout))
        r2 = subprocess.run([sys.executable, str(PROBE), '--approved-m2-selection-probe-01',
                             '--reference', str(tmp), '--out', str(tmp/'run')], capture_output=True, text=True)
        check('refuses_without_credential', r2.returncode != 0 and 'credential' in (r2.stderr+r2.stdout))
    finally:
        if (tmp/'run').exists():
            import shutil
            shutil.rmtree(tmp/'run')
        tmp.rmdir()
    r3 = subprocess.run(['bash', str(WRAPPER)], capture_output=True, text=True)
    check('wrapper_refuses_without_flag', r3.returncode == 2 and 'STOP' in r3.stderr)
    # Historical constants must match the frozen manifests.
    ref = REPORTS/'gpu_run_01/board/reference'
    meta = json.loads((ref/'MANIFEST.json').read_text())['tensor_metadata']
    expected = {
        'S0': {k: meta['reference_S0_'+k]['sha256'] for k in ('x', 'K', 'V')},
        'S1': {k: meta['reference_S1_'+k]['sha256'] for k in ('x', 'K', 'V')},
    }
    boundary = {k: meta['reference_S1_boundary_'+k]['sha256'] for k in ('x', 'K', 'V')}
    language = {s: meta[s+'_language']['sha256'] for s in ('S0', 'S1')}
    ns = {}
    exec(compile(PROBE.read_text().split('def protocol()')[0], str(PROBE), 'exec'), ns)
    check('historical_constants_match_manifest',
          ns['HIST'] == expected and ns['HIST_BOUNDARY_S1'] == boundary
          and ns['HIST_LANGUAGE'] == language,
          'mismatch' if (ns['HIST'] != expected or ns['HIST_BOUNDARY_S1'] != boundary
                         or ns['HIST_LANGUAGE'] != language) else '')
    if BUNDLE.exists():
        import hashlib
        listed = {}
        manifest = (BUNDLE/'DEPLOY_SHA256.txt').read_text().splitlines()
        ok = True
        for line in manifest:
            digest, name = line.split()
            listed[name.lstrip('*')] = digest
            p = BUNDLE/name
            ok = ok and p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == digest
        check('deployment_sha_manifest_consistent', ok, len(listed))
        for name in ('pi05_m2_selection_probe.py', 'm2_pi05_ops.py', 'm2_executor.py',
                     'period_obligation_stats.py', 'pi05_dual_slot_adapter.py',
                     'run_m2_selection_probe.sh'):
            check('deployment_copy_current_'+name,
                  (BUNDLE/name).exists() and (BUNDLE/name).read_bytes() == (SCRIPTS/name).read_bytes())
    failed = [r for r in RESULTS if not r['pass_']]
    print(json.dumps(dict(status='PASS' if not failed else 'FAIL', checks=len(RESULTS),
                          failed=[r['name'] for r in failed]), indent=1))
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
