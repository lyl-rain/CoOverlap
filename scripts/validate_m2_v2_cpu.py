"""CPU-only validation of the prepared M2 v2 entry (warm autotune + Context SHA gate)."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT/'scripts'
REPORTS = ROOT/'reports/m2_common/20261020'
V1 = SCRIPTS/'pi05_m2_correctness.py'
V2 = SCRIPTS/'pi05_m2_correctness_v2.py'
WRAPPER = SCRIPTS/'run_m2_v2_once.sh'
BUNDLE = REPORTS/'m2_v2/deployment'
V1_DEPLOY = REPORTS/'deployment'
RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append(dict(name=name, pass_=bool(ok)))
    print(('PASS ' if ok else 'FAIL ')+name+(' :: '+str(detail) if detail else ''))


def main():
    a, b = V1.read_text(), V2.read_text()
    check('v2_has_no_top_level_torch_import',
          not [l for l in b.splitlines() if re.match(r'^(import|from)\s+(torch|flash_rt|numpy)', l)])
    blocker = REPORTS/'.v2_blocker.py'
    blocker.write_text(
        "import sys, runpy\n"
        "class B:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('torch','flash_rt','numpy'):\n"
        "            raise ImportError('blocked '+name)\n"
        "sys.meta_path.insert(0, B())\n"
        "sys.argv=['pi05_m2_correctness_v2.py','--dry-run']\n"
        "runpy.run_path(%r, run_name='__main__')\n" % str(V2))
    try:
        import os
        env = dict(os.environ, PYTHONPATH=str(SCRIPTS))
        out = subprocess.run([sys.executable, str(blocker)], capture_output=True, text=True,
                             cwd=str(SCRIPTS), env=env)
    finally:
        blocker.unlink()
    proto = {}
    try:
        proto = json.loads(out.stdout)
    except Exception:
        pass
    check('v2_dry_run_without_torch', out.returncode == 0 and proto.get('id') == 'm2_common_v2',
          out.stderr.strip()[:200])
    check('v2_declares_the_two_math_neutral_changes',
          len(proto.get('changes_from_v1', [])) == 2
          and proto.get('warmup_work', {}).get('Contexts_max') == 8
          and 'byte exact' in str(proto.get('numeric_precondition', '')), proto.get('changes_from_v1'))
    check('v2_keeps_unchanged_work_ledger',
          proto.get('measured_work') == dict(Contexts=8, Experts=16)
          and proto.get('total_explicit_work', {}).get('Contexts') == 14
          and proto.get('total_explicit_work', {}).get('Experts') == 19,
          proto.get('total_explicit_work'))
    # The numeric policy must be untouched and still applied to the output only.
    check('v2_uses_unchanged_dual_gate_policy',
          'from m1_dual_gate import evaluate' in b
          and b.count('evaluate(data,olddata,kind,shape,shape)') == 1
          and 'POLICY=' not in b and '0.015625' not in b and '0.01' not in b)
    check('v2_policy_file_identical_to_frozen_v1',
          (BUNDLE/'m1_dual_gate.py').read_bytes() == (V1_DEPLOY/'m1_dual_gate.py').read_bytes())
    check('v2_adds_only_the_documented_gates',
          'gpu_frequency_at_max_before_autotune' in b
          and 'autotune_ran_at_max_frequency' in b
          and "_context_'+key+'_byte_exact'" in b
          and b.count('autotune_gemms()') == 1)
    check('v2_keeps_the_replay_and_ledger_contract',
          "from m2_replay_driver import replay" in b
          and "require(sum(r[2]=='encoder' for r in ledger.calls)==252" in b
          and "require(sum(r[2]=='decoder' for r in ledger.calls)==3420" in b
          and "require(sum(r[2]=='vision27' for r in ledger.calls)==14" in b)
    # Diff must stay inside the documented regions (insertion-insensitive).
    import difflib
    diff = list(difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm='', n=0))
    added = [l for l in diff if l.startswith('+') and not l.startswith('+++')]
    removed = [l for l in diff if l.startswith('-') and not l.startswith('---')]
    check('v2_diff_is_small_and_local', len(added) <= 50 and len(removed) <= 12,
          dict(added=len(added), removed=len(removed)))
    # Refusals
    tmp = REPORTS/'.v2_refusal'
    tmp.mkdir(exist_ok=True)
    try:
        r1 = subprocess.run([sys.executable, str(V2), '--reference', str(tmp), '--out', str(tmp/'run')],
                            capture_output=True, text=True)
        check('v2_refuses_without_authorization',
              r1.returncode != 0 and 'authorization' in (r1.stderr+r1.stdout))
    finally:
        if (tmp/'run').exists():
            import shutil
            shutil.rmtree(tmp/'run')
        tmp.rmdir()
    r2 = subprocess.run(['bash', str(WRAPPER)], capture_output=True, text=True)
    check('v2_wrapper_refuses_without_flag', r2.returncode == 2 and 'STOP' in r2.stderr)
    w = WRAPPER.read_text()
    check('v2_wrapper_targets_v2_and_bounds_the_process',
          'pi05_m2_correctness_v2.py' in w and '--approved-m2-common-v2' in w
          and 'kill-after=10s 240s' in w)
    # Frozen CPU contracts of the shared modules still pass.
    # The frozen v1 CPU contract suite resolves repo paths relative to scripts/.
    r3 = subprocess.run([sys.executable, str(SCRIPTS/'validate_m2_cpu.py')], capture_output=True,
                        text=True, cwd=str(SCRIPTS))
    check('shared_cpu_contracts_still_pass', r3.returncode == 0,
          (r3.stderr.strip().splitlines() or [''])[-1][:120])
    same = all((BUNDLE/n).read_bytes() == (V1_DEPLOY/n).read_bytes()
               for n in ('m2_executor.py', 'm2_pi05_ops.py', 'm2_replay_driver.py',
                         'period_obligation_stats.py', 'pi05_dual_slot_adapter.py', 'm1_dual_gate.py'))
    check('shared_modules_identical_to_frozen_v1', same)
    # Bundle integrity
    import hashlib
    listed = {}
    ok = True
    for line in (BUNDLE/'DEPLOY_SHA256.txt').read_text().splitlines():
        d, name = line.split()
        listed[name.lstrip('*')] = d
        p = BUNDLE/name
        ok = ok and p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == d
    check('deployment_sha_manifest_consistent', ok, len(listed))
    for name in ('pi05_m2_correctness_v2.py', 'm2_pi05_ops.py', 'm2_executor.py',
                 'm2_replay_driver.py', 'period_obligation_stats.py',
                 'pi05_dual_slot_adapter.py', 'm1_dual_gate.py', 'run_m2_v2_once.sh'):
        check('deployment_copy_current_'+name,
              (BUNDLE/name).read_bytes() == (SCRIPTS/name).read_bytes())
    failed = [r for r in RESULTS if not r['pass_']]
    print(json.dumps(dict(status='PASS' if not failed else 'FAIL', checks=len(RESULTS),
                          failed=[r['name'] for r in failed]), indent=1))
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
