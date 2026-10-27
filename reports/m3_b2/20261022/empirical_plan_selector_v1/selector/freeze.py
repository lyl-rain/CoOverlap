#!/usr/bin/env python3
"""Freeze B4 pass-1 costs/rules/model and select on training evidence only."""
import argparse
import json
from pathlib import Path

from evidence import (B4_RESULT, B4_CONFIG, MODEL, MODEL_ENV, MODEL_CONSTANTS,
                      catalog, extract_training, make_train_costs, sha)
from selection import select, CANDIDATES, POLICY
from model_env import EXECUTOR


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
    rules = dict(
        schema='m3_b2_empirical_plan_selector_rules_v1',
        target=dict(period_ms=240.0, phase_ms=15.0, cycles=8, policy=POLICY,
                    candidates=list(CANDIDATES)),
        split=dict(training='B4 pass 1 cells B/D', validation='B4 pass 2 cells D/B',
                   fixed_by='original execution order; validation outcomes not used for costs'),
        scenarios=['typical: per-dimension median of pass-1 samples',
                   'stress: per-dimension sample maximum; analysis construction, never observed jointly, not a formal upper bound'],
        model_constants=MODEL_CONSTANTS,
        model_sha256=sha(MODEL), model_env_sha256=sha(MODEL_ENV),
        executor=dict(path=str(EXECUTOR), sha256=sha(EXECUTOR)),
        source=dict(b4_result=str(B4_RESULT), b4_result_sha256=sha(B4_RESULT),
                    b4_config=str(B4_CONFIG), b4_config_sha256=sha(B4_CONFIG)),
        rules=dict(
            feasibility='all 8 Experts completed, all 8 cycle obligations PASS, all 4 refreshes PASS, all three margins >= 0',
            margin='margin = deadline - predicted_completion; deadline is original release + period (refresh +2P)',
            dominance='weak dominance on minimum cycle/Expert/refresh margins; no weighted score',
            no_evidence='INSUFFICIENT_EVIDENCE when candidate/condition costs are absent',
            no_candidate='NO_EMPIRICALLY_FEASIBLE_PLAN when complete evidence exists but no candidate satisfies all three margins',
        ),
        no_tuning='rules and costs are frozen before B4 pass 2 is read',
        provenance=dict(
            b5=dict(result='reports/m3_b2/20261021/boundary_budget_anchors_v1_r1/gpu_run_01/board/run_01/model/result.json', use='applicability only; two_9_9 only'),
            b6=dict(result='reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/board/run_01/model/result.json', use='applicability only; startup/pressure differs'),
            b7=dict(result='reports/m3_b2/20261021/stage_startup_b7_v1/gpu_run_01/board/run_01/model/result.json', use='startup applicability only; no B6 direct sub-call transfer'),
            b7_correction='reports/m3_b2/20261021/stage_startup_b7_v1/corrections/output/B7_STAGE_INTERVALS.json',
        ),
    )
    sel240 = select(costs, rules=rules)
    sel180 = select(costs, target=dict(period_ms=180.0, phase_ms=15.0, cycles=8), rules=rules)
    cat = catalog(); cat['training_sample_counts'] = {p: training[p]['summary'] for p in training}
    (out/'TRAIN_COSTS.json').write_text(json.dumps(costs, indent=2, sort_keys=True)+'\n')
    (out/'RULES.json').write_text(json.dumps(rules, indent=2, sort_keys=True)+'\n')
    (out/'EVIDENCE_CATALOG.json').write_text(json.dumps(cat, indent=2, sort_keys=True)+'\n')
    (out/'SELECTION_240.json').write_text(json.dumps(sel240, indent=2, sort_keys=True)+'\n')
    (out/'SELECTION_180.json').write_text(json.dumps(sel180, indent=2, sort_keys=True)+'\n')
    freeze = dict(schema='m3_b2_empirical_plan_selector_freeze_v1',
                  status='FROZEN_BEFORE_VALIDATION',
                  costs=dict(path=str(out/'TRAIN_COSTS.json'), sha256=sha(out/'TRAIN_COSTS.json')),
                  rules=dict(path=str(out/'RULES.json'), sha256=sha(out/'RULES.json')),
                  catalog=dict(path=str(out/'EVIDENCE_CATALOG.json'), sha256=sha(out/'EVIDENCE_CATALOG.json')),
                  selection_240=dict(path=str(out/'SELECTION_240.json'), sha256=sha(out/'SELECTION_240.json')),
                  selection_180=dict(path=str(out/'SELECTION_180.json'), sha256=sha(out/'SELECTION_180.json')),
                  model=dict(path=str(MODEL), sha256=sha(MODEL)),
                  model_env=dict(path=str(MODEL_ENV), sha256=sha(MODEL_ENV)),
                  executor=dict(path=str(EXECUTOR), sha256=sha(EXECUTOR)),
                  input=dict(path=str(B4_RESULT), sha256=sha(B4_RESULT)),
                  validation_unread=True)
    (out/'FREEZE.json').write_text(json.dumps(freeze, indent=2, sort_keys=True)+'\n')
    print(json.dumps(dict(status='FROZEN', freeze=str(out/'FREEZE.json'), selection=sel240['status'],
                          cost_sha256=freeze['costs']['sha256'], rules_sha256=freeze['rules']['sha256'],
                          model_sha256=freeze['model']['sha256']), indent=2))


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
