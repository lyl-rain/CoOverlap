#!/usr/bin/env python3
"""Freeze B4 pass-1 costs/rules/modules/inputs and select on training evidence only."""
import argparse
import json
from pathlib import Path

from evidence import (B4_RESULT, B4_CONFIG, B4_CORE, B4_GPU_PLAN, B4_CHECKPOINT_MANIFEST,
                      B5_RESULT, B6_RESULT, B7_RESULT, B7_CORRECTION, MODEL, MODEL_ENV,
                      MODEL_CONSTANTS, catalog, extract_training, make_train_costs, sha)
from selection import select, CANDIDATES, POLICY
from model_env import EXECUTOR

HERE = Path(__file__).resolve().parent
MODULE_NAMES = ('evidence', 'evaluator', 'selection', 'plan_model', 'model_env', 'validate', 'freeze')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('out', type=Path, help='new freeze directory')
    args = ap.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    data = json.loads(B4_RESULT.read_text())
    training, serial = extract_training(data)
    costs = make_train_costs(training)
    # Serial is a mechanism comparison only; keep it separate and never call it a candidate.
    costs['serial_comparison'] = scenario_from_serial(serial)
    cond = costs['condition']
    rules = dict(
        schema='m3_b2_empirical_plan_selector_rules_v1_r1',
        target=dict(
            period_ms=cond['period_ms'], phase_ms=cond['phase_ms'], cycles=cond['cycles'],
            policy=POLICY, candidates=list(CANDIDATES),
            lead_ms=cond['lead']['lead_ms'],
            pressure=cond['pressure']['mode'],
            protocol=cond['protocol'],
            condition_fingerprint=cond['fingerprint'],
            configuration_fingerprint=cond['configuration']['fingerprint'],
            input_fingerprint=cond['input']['fingerprint'],
            version_fingerprint=cond['version_consumption']['fingerprint'],
            retention_fingerprint=cond['retention']['fingerprint'],
            observation_fingerprint=cond['observation']['fingerprint'],
            hardware_fingerprint=cond['hardware']['fingerprint'],
            candidate_conditions={
                plan: dict(
                    layout_fingerprint=costs['candidates'][plan]['condition']['layout_fingerprint'],
                    obligation_fingerprint=costs['candidates'][plan]['condition']['obligation_groups']['fingerprint'],
                    retention_fingerprint=costs['candidates'][plan]['condition']['retention_observed']['fingerprint'],
                    condition_fingerprint=costs['candidates'][plan]['condition']['fingerprint'],
                ) for plan in CANDIDATES
            },
        ),
        split=dict(training='B4 pass 1 cells B/D', validation='B4 pass 2 cells D/B',
                   fixed_by='original execution order; validation outcomes not used for costs'),
        scenarios=['typical: per-dimension median of pass-1 samples',
                   'stress: per-dimension sample maximum; analysis construction, never observed jointly, not a formal upper bound'],
        model_constants=MODEL_CONSTANTS,
        model_sha256=sha(MODEL), model_env_sha256=sha(MODEL_ENV),
        executor=dict(path=str(EXECUTOR), sha256=sha(EXECUTOR)),
        source=dict(b4_result=str(B4_RESULT), b4_result_sha256=sha(B4_RESULT),
                    b4_config=str(B4_CONFIG), b4_config_sha256=sha(B4_CONFIG)),
        condition_required=[
            'period_ms', 'phase_ms', 'cycles', 'policy', 'protocol',
            'lead.lead_ms', 'pressure.mode', 'configuration.fingerprint',
            'input.fingerprint', 'version_consumption.fingerprint',
            'retention.fingerprint', 'observation.fingerprint', 'hardware.fingerprint',
            'candidates.*.layout_fingerprint', 'candidates.*.obligation_fingerprint',
            'candidates.*.retention_fingerprint', 'candidates.*.condition_fingerprint',
        ],
        condition_unknown_allowed=[
            'pressure.worker_processes (no runtime worker field in result.json)',
            'pressure.runtime_audit (declared condition only)',
            'hardware.device (not recorded)',
            'hardware.temperature (not recorded)',
        ],
        rules=dict(
            feasibility='all 8 Experts completed, all 8 cycle obligations PASS, all 4 refreshes PASS, all three margins >= 0',
            margin='margin = deadline - predicted_completion; deadline is original release + period (refresh +2P)',
            refresh_metrics='refresh_response_ms = publish_time - refresh_release; completion_offset_ms = publish_time - segment_t0; refresh_margin_ms = refresh_deadline - publish_time; max_refresh_response_ms uses only refresh_response_ms',
            dominance='weak dominance on minimum cycle/Expert/refresh margins; no weighted score; max refresh response is informational only',
            no_evidence='INSUFFICIENT_EVIDENCE when a necessary condition field is missing/mismatched or candidate costs are absent',
            no_candidate='NO_EMPIRICALLY_FEASIBLE_PLAN only when all declared candidates have complete evidence and each is infeasible; one infeasible candidate does not remove a feasible one',
            unsupported='UNSUPPORTED_INPUT for out-of-domain phase/cycles/policy/period or an unrecognised target parameter',
        ),
        no_tuning='costs and rules are frozen before this r1 retrospective read of B4 pass 2; B4 pass 2 was already analyzed in v1',
        provenance=dict(
            b5=dict(result='reports/m3_b2/20261021/boundary_budget_anchors_v1_r1/gpu_run_01/board/run_01/model/result.json', use='applicability only; two_9_9 only'),
            b6=dict(result='reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/board/run_01/model/result.json', use='applicability only; startup/pressure differs'),
            b7=dict(result='reports/m3_b2/20261021/stage_startup_b7_v1/gpu_run_01/board/run_01/model/result.json', use='startup applicability only; no B6 direct sub-call transfer'),
            b7_correction='reports/m3_b2/20261021/stage_startup_b7_v1/corrections/output/B7_STAGE_INTERVALS.json',
        ),
    )
    sel240 = select(costs, rules=rules)
    sel180 = select(costs, target=dict(period_ms=180.0, phase_ms=15.0, cycles=8), rules=rules)
    cat = catalog()
    cat['condition'] = cond
    cat['candidate_conditions'] = {p: costs['candidates'][p]['condition'] for p in CANDIDATES}
    cat['training_sample_counts'] = {p: training[p]['summary'] for p in training}
    (out/'TRAIN_COSTS.json').write_text(json.dumps(costs, indent=2, sort_keys=True)+'\n')
    (out/'RULES.json').write_text(json.dumps(rules, indent=2, sort_keys=True)+'\n')
    (out/'EVIDENCE_CATALOG.json').write_text(json.dumps(cat, indent=2, sort_keys=True)+'\n')
    (out/'SELECTION_240.json').write_text(json.dumps(sel240, indent=2, sort_keys=True)+'\n')
    (out/'SELECTION_180.json').write_text(json.dumps(sel180, indent=2, sort_keys=True)+'\n')
    modules = {name: dict(path=str(HERE/(name + '.py')), sha256=sha(HERE/(name + '.py')))
               for name in MODULE_NAMES}
    inputs = [
        dict(role='primary_result', path=str(B4_RESULT), sha256=sha(B4_RESULT)),
        dict(role='primary_config', path=str(B4_CONFIG), sha256=sha(B4_CONFIG)),
        dict(role='lead_source', path=str(B4_CORE), sha256=sha(B4_CORE)),
        dict(role='pressure_source', path=str(B4_GPU_PLAN), sha256=sha(B4_GPU_PLAN)),
        dict(role='checkpoint_source', path=str(B4_CHECKPOINT_MANIFEST), sha256=sha(B4_CHECKPOINT_MANIFEST)),
        dict(role='supplemental_result:b5', path=str(B5_RESULT), sha256=sha(B5_RESULT)),
        dict(role='supplemental_result:b6', path=str(B6_RESULT), sha256=sha(B6_RESULT)),
        dict(role='supplemental_result:b7', path=str(B7_RESULT), sha256=sha(B7_RESULT)),
        dict(role='supplemental_correction:b7', path=str(B7_CORRECTION), sha256=sha(B7_CORRECTION)),
    ]
    freeze = dict(
        schema='m3_b2_empirical_plan_selector_freeze_v1_r1',
        status='FROZEN_BEFORE_R1_RETROSPECTIVE_CHECK',
        validation_identity=dict(
            kind='retrospective_check',
            description='First-pass cost extraction, second-pass separate evaluation (retrospective).',
            b4_pass2_previously_analyzed=True,
            r1_validation_read_before_freeze=False,
            prospective=False,
            previously_unseen=False,
        ),
        manifest_self_hash='not included by design',
        consistency_boundary='Consistency check relative to this specified manifest only; it is not tamper-proof authentication and is not a proof of historical execution order.',
        costs=dict(path=str(out/'TRAIN_COSTS.json'), sha256=sha(out/'TRAIN_COSTS.json')),
        rules=dict(path=str(out/'RULES.json'), sha256=sha(out/'RULES.json')),
        catalog=dict(path=str(out/'EVIDENCE_CATALOG.json'), sha256=sha(out/'EVIDENCE_CATALOG.json')),
        selection_240=dict(path=str(out/'SELECTION_240.json'), sha256=sha(out/'SELECTION_240.json')),
        selection_180=dict(path=str(out/'SELECTION_180.json'), sha256=sha(out/'SELECTION_180.json')),
        modules=modules,
        executor=dict(path=str(EXECUTOR), sha256=sha(EXECUTOR)),
        inputs=inputs,
    )
    (out/'FREEZE.json').write_text(json.dumps(freeze, indent=2, sort_keys=True)+'\n')
    print(json.dumps(dict(status='FROZEN', freeze=str(out/'FREEZE.json'), selection=sel240['status'],
                          cost_sha256=freeze['costs']['sha256'], rules_sha256=freeze['rules']['sha256'],
                          condition_fingerprint=cond['fingerprint'],
                          lead_ms=cond['lead']['lead_ms'], pressure=cond['pressure']['mode'],
                          modules=len(modules), inputs=len(inputs)), indent=2))


def scenario_from_serial(serial):
    out = {}
    for plan, block in serial.items():
        rows = block['rows']
        from evidence import scenario_from_rows
        sc = scenario_from_rows(rows)
        out[plan] = sc.get(plan)
    return out


if __name__ == '__main__':
    main()
