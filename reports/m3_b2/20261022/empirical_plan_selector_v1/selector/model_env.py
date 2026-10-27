"""B4 frozen VersionedKV location for the analysis-only selector.

The production executor is not imported by the selector.  The copied plan model
drives the frozen `m2_executor.VersionedKV` from the executed B4 r2 package.
"""
import hashlib
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[5]
DEPLOYMENT = (PROJECT / 'reports/m3_b2/20261021'
              / 'split_priority_ablation_v1_r2' / 'deployment')
if str(DEPLOYMENT) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT))
EXECUTOR = DEPLOYMENT / 'm2_executor.py'


def executor_identity():
    return dict(path=str(EXECUTOR), sha256=hashlib.sha256(EXECUTOR.read_bytes()).hexdigest())
