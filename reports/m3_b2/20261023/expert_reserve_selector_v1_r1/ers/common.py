"""Shared wiring: reuse the release-boundary evaluator's frozen inputs and model.

Nothing here re-implements costs, the analysis model, the VersionedKV lifecycle or
the deadline statistics.  The two packages stay separate:

``release_boundary_evaluator_v1/rbe``  frozen-input identity, per-cell B8 costs,
                                      replay through the frozen r1 plan model and
                                      the real ``m2_executor.VersionedKV``.
``expert_reserve_selector_v1/ers``    this round only: the reserve rule, the
                                      selection, and the F2/F3/S0/S10 ablation.

Revision r1 fixes two real gaps of v1 (which is kept unchanged):
  * a missing declared candidate is now INSUFFICIENT_EVIDENCE, never SELECTED;
  * a candidate whose lifecycle check failed is never feasible and never selected.
The rule itself (RE = 10 ms, cost source, ordering) is unchanged.

The rule is retrospective: it was written after B8, from B8's own evidence.  It is
not a pre-run rule and it does not change the r1 selector's applicability domain.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DAY = HERE.parent
PROJECT = DAY.parents[2]
RBE = DAY / 'release_boundary_evaluator_v1'
RBE_PKG = RBE / 'rbe'
RECON = DAY / 'reconciliation'
OUT = HERE / 'outputs'

if str(RBE_PKG) not in sys.path:
    sys.path.insert(0, str(RBE_PKG))

import env as rbe_env          # noqa: E402  (frozen-input identity + sys.path wiring)
import costs as rbe_costs      # noqa: E402
import replay as rbe_replay    # noqa: E402

rbe_env.prepare_imports()

CANDIDATES = ('two_9_9', 'three_prefix_9_9')   # stable pre-declared order
BLOCKS = {'two_9_9': 2, 'three_prefix_9_9': 3}
PERIODS_MS = (180.0, 140.0)
SCENARIOS = ('typical', 'stress')

RULE_ID = 'm3_expert_reserve_selector_v1_r1'
RULE_STATUS = 'RETROSPECTIVE_DESIGN_AFTER_B8'


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


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def module_identity():
    out = {}
    for name in ('common.py', 'rules.py', 'select.py', 'ablation.py', 'cli.py',
                 'test_ers_cpu.py'):
        p = Path(__file__).resolve().parent / name
        if p.exists():
            out['ers/' + name] = sha(p)
    for name in ('env.py', 'costs.py', 'replay.py', 'audit.py'):
        p = RBE_PKG / name
        out['rbe/' + name] = sha(p)
    out['r1_plan_model'] = sha(rbe_env.R1_SELECTOR / 'plan_model.py')
    out['r1_evaluator'] = sha(rbe_env.R1_SELECTOR / 'evaluator.py')
    out['frozen_executor'] = sha(rbe_env.FROZEN_EXECUTOR)
    return out


def cell_for(measured, plan, period_ms):
    for cell in measured['cells'].values():
        if cell['plan'] == plan and cell['period_ns'] == int(round(period_ms * 1e6)):
            return cell
    raise KeyError('no B8 cell for %s @ %s ms' % (plan, period_ms))
