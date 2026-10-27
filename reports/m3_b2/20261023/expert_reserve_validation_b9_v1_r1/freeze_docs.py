#!/usr/bin/env python3
"""Fill the approval SHA table from the final files and write FREEZE.json.

Run LAST: it reads every artifact, replaces the ``<!--SHA_TABLE-->`` marker in
APPROVAL_CHECKLIST.md with the full digests, then writes FREEZE.json.  The table
does not list the checklist itself (that would be circular); FREEZE.json records
the checklist SHA after the table is in place.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DAY = HERE.parent

ITEMS = {
 'config': 'deployment/CONFIG.json',
 'deploy_manifest': 'deployment/DEPLOY_SHA256.txt',
 'plan_module': 'deployment/m3_b9_plan.py',
 'entry': 'deployment/pi05_m3_b9_validation.py',
 'controller': 'deployment/m3_b9_control.py',
 'structural_cpu_validator': 'deployment/validate_m3_b9_cpu.py',
 'manifest_builder': 'deployment/build_manifests.py',
 'budget': 'deployment/BUDGET.json',
 'fairness': 'deployment/FAIRNESS_CHECK.json',
 'compatibility': 'deployment/COMPATIBILITY.json',
 'prediction': 'prediction/PREDICTION.json',
 'selection_freeze': 'prediction/SELECTION_FREEZE.json',
 'prediction_model': 'prediction/prediction_model.py',
 'prediction_builder': 'prediction/build_b9_prediction.py',
 'evaluator': 'analysis/evaluate_b9.py',
 'cpu_runner': 'tests/run_cpu.py',
 'evaluation_tests': 'tests/test_evaluate_b9_cpu.py',
 'fixture_builder': 'tests/fixture_b9.py',
 'cpu_results': 'CPU_RESULTS.json',
 'gpu_plan': 'GPU_PLAN.md',
 'readme': 'README.md',
 'revision': 'REVISION.md',
 'results_template': 'RESULTS_TEMPLATE.json',
 'minimal_diff': 'MINIMAL_DIFF.patch',
 'rules': '../expert_reserve_selector_v1_r1/RULES.json',
 'costs': '../expert_reserve_selector_v1_r1/COSTS.json',
 'b8_result': '../../20261022/split_budget_challenge_b8_v1/gpu_run_01/board/run_01/model/result.json',
 'b8_prediction': '../../20261022/split_budget_challenge_b8_v1/prediction/PREDICTION.json',
 'r1_plan_model': '../../20261022/empirical_plan_selector_v1_r1/selector/plan_model.py',
 'frozen_executor': '../../20261022/split_budget_challenge_b8_v1/deployment/m2_executor.py',
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    records = {}
    for key, rel in ITEMS.items():
        path = Path(rel)
        if not path.exists():
            raise SystemExit('missing artifact: %s' % rel)
        records[key] = dict(path=rel, sha256=sha(path))

    rows = ['| artifact | path | SHA256 |', '|---|---|---|']
    for key, rec in records.items():
        rows.append('| %s | `%s` | `%s` |' % (key, rec['path'], rec['sha256']))
    table = '\n'.join(rows)

    checklist = HERE / 'APPROVAL_CHECKLIST.md'
    text = checklist.read_text()
    head = '## 7. 冻结身份（完整 SHA256，由脚本从最终文件生成）'
    tail = '## 8. 批准语（请用户确认其一）'
    if head in text and tail in text:
        # idempotent: rebuild the table block on every run
        before, rest = text.split(head, 1)
        _, after = rest.split(tail, 1)
        text = before + head + '\n\n<!--SHA_TABLE-->\n\n' + tail + after
    if '<!--SHA_TABLE-->' not in text:
        raise SystemExit('approval checklist has no SHA table marker')
    checklist.write_text(text.replace('<!--SHA_TABLE-->', table))

    freeze = dict(
        schema='m3_b9_freeze_v2', protocol='m3_b9_expert_reserve_validation_v1',
        revision='r1', status='PREPARED', approval='NOT_APPROVED', run='NOT_RUN',
        note='all entries are frozen before execution; the run may not rewrite them; '
             'the SHA table in APPROVAL_CHECKLIST.md is generated from these files',
        rule_revision='expert_reserve_selector_v1_r1',
        files=records,
        approval_checklist=dict(path='APPROVAL_CHECKLIST.md',
                                sha256=sha(checklist)))
    (HERE / 'FREEZE.json').write_text(json.dumps(freeze, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: v['sha256'] for k, v in records.items()}, indent=2))
    print('checklist', freeze['approval_checklist']['sha256'])


if __name__ == '__main__':
    main()
