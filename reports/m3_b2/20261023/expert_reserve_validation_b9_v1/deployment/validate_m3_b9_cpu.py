#!/usr/bin/env python3
"""Targeted CPU checks for the B9 Expert-reserve validation batch (no GPU, no hardware).

Covers only the new risks of this batch: the new protocol identity and credential,
the fixed 8-segment matrix, the frozen pre-segment selection record, the
no-double-counting of S0/S10, condition-mismatch handling, the stop rules, the
fairness/retention configuration, failure attribution and missing-evidence
accounting.  Historical suites are not re-run.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
B9 = HERE.parent
sys.path.insert(0, str(HERE))

import m3_b9_plan as b9                     # noqa: E402
from m3_b3_orchestrate import describe_active, mark_active  # noqa: E402
from m2_executor import replay_manifest, replay_stats      # noqa: E402

CHECKS = []


def check(name, ok, detail=None):
    CHECKS.append(dict(name=name, pass_=bool(ok), detail=detail))
    return bool(ok)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class FakeBank:
    capacity = 1


class FakeBackend:
    layout = {'nbytes': 1, 'schema': 'm3_b9_retention_v1'}
    bank = FakeBank()


def main():
    protocol = b9.protocol()
    config = json.loads((HERE / 'CONFIG.json').read_text())
    check('config_equals_protocol', config == protocol,
          'CONFIG.json must equal m3_b9_plan.protocol()')
    check('protocol_id', b9.PROTOCOL == 'm3_b9_expert_reserve_validation_v1', b9.PROTOCOL)
    check('result_status', protocol['id'] == b9.PROTOCOL
          and b9.RESULT_STATUS == 'PASS_IN_PROCESS_EXPERT_RESERVE_VALIDATION')

    # 1. the fixed matrix
    check('eight_segments', len(b9.RUN) == 8 and len(b9.SEGMENT_IDS) == 8)
    check('unique_segment_ids', len(set(b9.SEGMENT_IDS)) == 8)
    check('declared_order', [c['cell'][0] for c in b9.RUN] == ['A', 'B', 'C', 'D', 'D', 'C', 'B', 'A'])
    check('both_plans_at_both_budgets',
          {(c['period_ns'], c['plan']) for c in b9.RUN}
          == {(180_000_000, 'two_9_9'), (180_000_000, 'three_prefix_9_9'),
              (140_000_000, 'two_9_9'), (140_000_000, 'three_prefix_9_9')})
    check('cycles_and_phase', all(c['period_ns'] in b9.BUDGETS for c in b9.RUN)
          and b9.CYCLES == 8 and protocol['phase_ns'] == 15_000_000)
    check('manifest_per_budget', set(b9.manifests()) == set(b9.BUDGETS))
    check('manifest_drives_releases',
          all(len(b9.manifests()[ns]['experts']) == 8
              and len(b9.manifests()[ns]['refreshes']) == 4 for ns in b9.BUDGETS))

    # 2. work/resource projection computed from this batch's code path
    batch = protocol['work']['batch']
    observed = protocol['work']['observed_ledger']
    check('complete_work_52C_70E', (batch['total_C'], batch['total_E']) == (52, 70),
          (batch['total_C'], batch['total_E']))
    check('timed_32C_64E', (batch['timed_C'], batch['timed_E']) == (32, 64))
    check('observed_ledger_13400', observed['rows'] == 13_400
          and observed['rows'] == observed['contexts'] * 20 + observed['experts'] * 180)
    check('autotune_36_separate', protocol['work']['autotune_requests'] == 36)
    budget = b9.budget()
    check('bank_597617152', budget['bank_bytes'] == 597_617_152)
    check('payload_4339748864', budget['batch_payload_bytes'] == 4_339_748_864)
    check('disk_under_12GiB', budget['disk']['estimate_bytes'] < 12 * 1024**3
          and budget['disk']['admission_bytes'] == 12 * 1024**3)
    check('selection_record_adds_no_work',
          protocol['selection']['note'].startswith('recorded before each segment')
          and batch['timed_C'] == len(b9.RUN) * b9.CYCLES // 2)

    # 3. frozen selection record
    freeze_path = B9 / 'prediction' / 'SELECTION_FREEZE.json'
    pred_path = B9 / 'prediction' / 'PREDICTION.json'
    freeze = json.loads(freeze_path.read_text())
    check('selection_sha_matches_plan', sha(freeze_path) == b9.SELECTION_SHA256)
    check('prediction_sha_matches_plan', sha(pred_path) == b9.PREDICTION_SHA256)
    check('selection_fingerprint', freeze['fingerprint'] == b9.SELECTION_FINGERPRINT)
    check('selection_reserve_identity', freeze['reserve_ms'] == b9.RESERVE_MS == 10.0
          and freeze['rule_id'] == b9.RULE_ID)
    check('selection_covers_every_segment',
          all(str(c['period_ns']) in freeze['by_period_ns'] for c in b9.RUN))
    check('selection_matches_plan_constants',
          {k: v['selected'] for k, v in freeze['by_period_ns'][str(180_000_000)].items()}
          == b9.SELECTION_180
          and {k: v['selected'] for k, v in freeze['by_period_ns'][str(140_000_000)].items()}
          == b9.SELECTION_140)
    # the frozen recommendation must be reproducible from the frozen rule + B8 costs
    r1 = B9.parent / 'expert_reserve_selector_v1_r1' / 'ers'
    sys.path.insert(0, str(r1))
    import ablation
    import common as ers_common
    import rules as ers_rules
    import select as ers_select
    result = ers_common.rbe_env.load(ers_common.rbe_env.B8_RESULT)
    recomputed = {}
    for period in ers_common.PERIODS_MS:
        cands, _ = ablation.build_candidates(result, period)
        recomputed[str(int(period * 1e6))] = dict(
            S0=ers_select.select(cands, 0.0)['selected'],
            S10=ers_select.select(cands, ers_rules.RE_MS)['selected'])
    frozen_selected = {k: {s: v['selected'] for s, v in d.items()}
                       for k, d in freeze['by_period_ns'].items()}
    check('selection_recomputed_from_rule_and_costs', recomputed == frozen_selected,
          recomputed)

    # 4. entry/controller identity, credential and no result->rule write-back
    entry = (HERE / 'pi05_m3_b9_validation.py').read_text()
    control = (HERE / 'm3_b9_control.py').read_text()
    check('entry_uses_b9_plan', 'from m3_b9_plan import' in entry and 'm3_b8_plan' not in entry)
    check('entry_requires_new_flag', '--approved-m3-b9-expert-reserve-validation-v1' in entry)
    check('entry_requires_env_token', "os.environ.get('COOVERLAP_APPROVED_BATCH') != PROTOCOL" in entry)
    check('controller_requires_new_flag', 'approved-m3-b9-expert-reserve-validation-v1' in control
          and 'm3_b8' not in control)
    check('controller_one_submit', 'SCOPE_ATTEMPT_USED' in control
          and 'mkdir(exist_ok=False)' in control)
    check('entry_records_selection_before_window',
          "selection=by_period[str(c['period_ns'])]" in entry
          and 'pre_segment_selection_recorded_' in entry)
    check('entry_does_not_rewrite_costs',
          'COSTS' not in entry and 'RULES.json' not in entry and 'RE_MS =' not in entry)
    check('entry_checks_selection_sha', 'SELECTION_SHA256' in entry and 'frozen' in entry)
    check('no_extra_candidate_run', entry.count('run_candidates(') == 1
          and 'for i, c in enumerate(RUN)' in entry)

    # 5. condition mismatch is not faked into SELECTED (offline evaluator contract)
    evaluator = (B9 / 'analysis' / 'evaluate_b9.py').read_text()
    check('evaluator_has_condition_mismatch', 'CONDITION_MISMATCH' in evaluator)
    check('evaluator_reports_domain', 'INSUFFICIENT_EVIDENCE' in evaluator)
    check('evaluator_never_filters_or_restarts',
          'restart' not in evaluator and 'filter(' not in evaluator)
    import importlib.util
    spec = importlib.util.spec_from_file_location('_b9eval', B9 / 'analysis' / 'evaluate_b9.py')
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    check('condition_match_helper',
          ev.condition_status('H_frozen') == 'MATCH'
          and ev.condition_status('OTHER_S0_0c63ddfb1c91') == 'CONDITION_MISMATCH'
          and ev.condition_status(None) == 'UNKNOWN')

    # 6. stop rules: correctness/resource/time stop; performance does not
    check('internal_cutoff', '170_000_000_000' in entry and 'TimeoutError' in entry)
    check('thermal_guard', "'/sys/devices/virtual/thermal/thermal_zone0/temp'" in entry)
    body = entry.split('def main')[1]
    check('no_performance_stop',
          'FAIL' not in body.replace('FAIL_OR_INCOMPLETE', ''))

    # 7. fairness / retention configuration
    fair = json.loads((HERE / 'FAIRNESS_CHECK.json').read_text())
    compat = json.loads((HERE / 'COMPATIBILITY.json').read_text())
    check('fairness_same_manifest_per_budget',
          all(v['cycles'] == 8 and v['phase_ns'] == 15_000_000
              for v in fair['by_budget'].values()))
    check('cross_budget_not_matched', fair['cross_budget']['matched'] is False)
    check('compat_manifests_equal_after_schema', compat['manifests']['equal_after_schema'] is True)
    check('compat_declares_new_protocol', compat['protocol_identity']['equal'] is False)
    check('compat_no_unchanged_assumption', 'does not assume' in compat['not_claimed'])
    from m2_clean_core import retention_layout
    two = retention_layout(b9.CYCLES, b9.PLANS['two_9_9'])
    three = retention_layout(b9.CYCLES, b9.PLANS['three_prefix_9_9'])
    check('retention_differs_by_plan_by_design', two['nbytes'] < three['nbytes'])
    check('retention_is_per_plan_not_per_budget',
          b9.budget()['per_cell_segment_bytes']['A_p180_two_b2_boundary']
          == b9.budget()['per_cell_segment_bytes']['C_p140_two_b2_boundary'])

    # 8. failure attribution names the active phase only
    active = {}
    mark_active(active, 'segment', b9.SEGMENT_IDS[3], 'three_prefix_9_9',
                FakeBackend(), object(), {})
    seen = describe_active(active)
    check('attribution_names_segment',
          seen['segment_id'] == b9.SEGMENT_IDS[3] and seen['plan'] == 'three_prefix_9_9'
          and seen['kind'] == 'segment' and 'backend' not in seen and 'record' not in seen)
    check('attribution_without_active', describe_active({})['kind'] is None)

    # 9. missing work is INCOMPLETE with the denominator kept, never zero/PASS
    P = 180_000_000
    conf = replay_manifest(P, 8)
    units = {(m, b): (2 * m * P + 10_000_000, 2 * m * P + 20_000_000)
             for m in range(4) for b in (0, 1)}
    ontime = {j: (j * P + 10_000_000, j * P + 20_000_000) for j in range(7)}  # E7 missing
    stats = replay_stats(conf, ontime, units, {}, t0=0)
    check('missing_expert_incomplete',
          stats['cycles'][7]['status'] == 'INCOMPLETE'
          and stats['cycle_counts']['denominator'] == 8
          and stats['cycle_counts']['INCOMPLETE'] == 1)
    check('present_jobs_still_classified',
          stats['cycles'][0]['status'] == 'PASS'
          and stats['cycles'][6]['status'] == 'PASS'
          and stats['cycles'][7]['status'] == 'INCOMPLETE')
    late = dict(ontime)
    late[0] = (P + 20_000_000, P + 30_000_000)   # 200-210 ms, wholly after the 180 ms deadline
    check('late_job_kept',
          replay_stats(conf, late, units, {}, t0=0)['cycles'][0]['status'] == 'FAIL')

    # 10. the four executed modules compile (syntax only; no import side effects)
    compiled = []
    for name in ('m3_b9_plan.py', 'pi05_m3_b9_validation.py', 'm3_b9_control.py',
                 'm3_b3_orchestrate.py'):
        try:
            compile((HERE / name).read_text(), name, 'exec')   # syntax only, writes nothing
            compiled.append(name)
        except SyntaxError:
            pass
    check('modules_compile', len(compiled) == 4, compiled)

    # 11. deployment manifest covers the package
    manifest = (HERE / 'DEPLOY_SHA256.txt').read_text().splitlines()
    listed = {}
    for line in manifest:
        digest, name = line.split(None, 1)
        listed[name.strip()] = digest
    files = [p for p in HERE.rglob('*')
             if p.is_file() and p.name != 'DEPLOY_SHA256.txt'
             and '__pycache__' not in p.parts]
    check('deployment_manifest_covers_package',
          {p.relative_to(HERE).as_posix() for p in files} == set(listed))
    check('deployment_manifest_hashes',
          all(sha(HERE / name) == digest for name, digest in listed.items()))
    check('config_in_manifest', 'CONFIG.json' in listed and 'm3_b9_plan.py' in listed
          and 'pi05_m3_b9_validation.py' in listed)

    passed = sum(1 for c in CHECKS if c['pass_'])
    print(json.dumps(dict(passed=passed, total=len(CHECKS),
                          failures=[c for c in CHECKS if not c['pass_']][:5]), indent=2))
    (B9 / 'CPU_RESULTS.json').write_text(json.dumps(
        dict(schema='m3_b9_cpu_v1', protocol=b9.PROTOCOL, passed=passed,
             total=len(CHECKS), checks=CHECKS), indent=2) + '\n')
    return 0 if passed == len(CHECKS) else 1


if __name__ == '__main__':
    sys.exit(main())
