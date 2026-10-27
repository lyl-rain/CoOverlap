"""Where the revised model takes its frozen semantics from.

The version lifecycle is NOT re-implemented here: the analysis model drives the
frozen `m2_executor.VersionedKV` (same class the executor uses) from the r2
deployment package. The path and SHA are recorded in EVIDENCE_INDEX.json.
"""
import hashlib
import sys
from pathlib import Path

DEPLOYMENT = (Path(__file__).resolve().parents[1]
              / 'split_priority_ablation_v1_r2' / 'deployment')
if str(DEPLOYMENT) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT))

EXECUTOR = DEPLOYMENT / 'm2_executor.py'


def executor_identity():
    return dict(path=str(EXECUTOR), sha256=hashlib.sha256(EXECUTOR.read_bytes()).hexdigest())
