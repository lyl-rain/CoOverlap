"""Frozen-input identity and import wiring for the release-boundary evaluator.

This package is analysis-only.  It imports the copied r1 plan model (which drives
the real frozen ``m2_executor.VersionedKV``) and the frozen r1 costs; it never
imports or edits the production executor, the B8 raw data, or the frozen
prediction.  Every path below is read-only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PROJECT = HERE.parents[3]
REPORTS_DAY = PROJECT / 'reports/m3_b2/20261022'
R1 = REPORTS_DAY / 'empirical_plan_selector_v1_r1'
B8 = REPORTS_DAY / 'split_budget_challenge_b8_v1'
B4 = PROJECT / 'reports/m3_b2/20261021/split_priority_ablation_v1_r2'

R1_SELECTOR = R1 / 'selector'
B4_DEPLOYMENT = B4 / 'deployment'
B8_DEPLOYMENT = B8 / 'deployment'

TRAIN_COSTS = R1 / 'freeze/TRAIN_COSTS.json'
RULES = R1 / 'freeze/RULES.json'
FREEZE = R1 / 'freeze/FREEZE.json'
B4_RESULT = B4 / 'gpu_run_01/board/run_01/model/result.json'
FROZEN_EXECUTOR = B4_DEPLOYMENT / 'm2_executor.py'
B8_RESULT = B8 / 'gpu_run_01/board/run_01/model/result.json'
B8_PREDICTION = B8 / 'prediction/PREDICTION.json'
B8_PREDICTION_RECEIPT = B8 / 'prediction/PREDICTION_RECEIPT.json'
B8_COMPARISON = B8 / 'gpu_run_01/analysis/PREDICTION_COMPARISON.json'
B8_RUN_SUMMARY = B8 / 'gpu_run_01/analysis/RUN_SUMMARY.json'
B8_REPORT = B8 / 'gpu_run_01/RUN_REPORT.md'
B8_PLAN = B8_DEPLOYMENT / 'm3_b8_plan.py'

OUT = HERE / 'outputs'

# Frozen identities recorded by the batches that produced them.  A mismatch is a
# hard error: this round must not evaluate a changed prediction or raw record.
FROZEN_SHA256 = {
    'b8_result_json': '1d48e537ca7d74397bf226cff0e48b9189f800e288b085c69dcb9b8d5f5729fd',
    'b8_prediction_json': 'd7b417754b2da51ad5f05a9c65ec1622f33d03916acc2ded9db2b6c140abb9e0',
    'r1_train_costs': '5b9df9782c71981959008203f1d4a129fa6f9f5c71d359d7690f43abfae5a948',
    'r1_rules': '8c3eb365e5f23c7c36fbd78cd0013090443a1d2524e934e066cbb24fa10e3712',
    'r1_freeze': '72228b75075e0475fc6ccc5e0066351c1efe5021a56429a015dadb53d4efd211',
    'r1_plan_model': '2ee21ef17d6cd03eb5dc21336ad7c2b2c370544f6091b1193ff7894669552237',
    'frozen_executor': '7890fa54896dd65635be741fddc50771bbc1b42b120abd6122c75170c6841654',
}

CONDITION_LABELS = {
    'b8_actual': 'H_frozen (B8 runtime S0/S1 context tags)',
    'b4_source': 'OTHER_S0_0c63ddfb1c91 (frozen r1 cost source, B4 r2 batch)',
}

PHASE_MS = 15.0
CYCLES = 8
PROBE_NS = 1


class FrozenInputMismatch(RuntimeError):
    pass


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def fingerprint_inputs(strict=True):
    """SHA256 of every frozen input; refuse to run on a changed record."""
    paths = {
        'b8_result_json': B8_RESULT,
        'b8_prediction_json': B8_PREDICTION,
        'r1_train_costs': TRAIN_COSTS,
        'r1_rules': RULES,
        'r1_freeze': FREEZE,
        'r1_plan_model': R1_SELECTOR / 'plan_model.py',
        'frozen_executor': FROZEN_EXECUTOR,
    }
    out = {}
    for key, path in paths.items():
        actual = sha(path)
        recorded = FROZEN_SHA256[key]
        out[key] = dict(path=str(path.relative_to(PROJECT)), sha256=actual,
                        expected=recorded, match=actual == recorded)
    if strict and not all(v['match'] for v in out.values()):
        bad = [k for k, v in out.items() if not v['match']]
        raise FrozenInputMismatch('frozen input changed: %s' % ', '.join(bad))
    return out


def prepare_imports():
    """Put the frozen r1 model and the frozen VersionedKV package on sys.path."""
    for path in (str(R1_SELECTOR), str(B4_DEPLOYMENT)):
        if path not in sys.path:
            sys.path.insert(0, path)


def executor_identity():
    return dict(path=str(FROZEN_EXECUTOR.relative_to(PROJECT)),
                sha256=sha(FROZEN_EXECUTOR),
                note='identical bytes to scripts/m2_executor.py and the B8 deployment copy')


def condition_identity(result):
    cfg = result.get('configuration') or {}
    return dict(
        label=cfg.get('label'),
        matches_frozen_context=cfg.get('matches_frozen_context'),
        s0_context_sha256=cfg.get('S0_context_sha256'),
        s1_context_sha256=cfg.get('S1_context_sha256'),
        cross_process_gate=result.get('cross_process_gate'),
        note='runtime numeric configuration is recorded, not explained; no causal claim',
    )
