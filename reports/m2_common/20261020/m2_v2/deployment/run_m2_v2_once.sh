#!/usr/bin/env bash
# PREPARED ONLY. The flag must follow a new explicit human authorization.
set -euo pipefail
base="$(cd "$(dirname "$0")" && pwd)"
py=/home/nvidia/jetson-torch-env/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$base:/home/nvidia/rtvla/cooverlap_diag_20261014_resource/lib:/home/nvidia/rtvla/FlashRT"
if [[ "${1-}" == --dry-run ]]; then
  exec "$py" "$base/pi05_m2_correctness_v2.py" --dry-run
fi
if [[ "${1-}" != --approved-m2-common-v2 || "$#" != 1 ]]; then
  echo 'STOP: new explicit M2 authorization is required' >&2
  exit 2
fi
if [[ "$(id -u)" == 0 ]]; then
  echo 'STOP: ordinary nvidia user only' >&2
  exit 2
fi
# Atomic one-shot attempt marker, including preflight failure; never auto-remove.
mkdir "$base/ATTEMPT_USED"
cd "$base"
sha256sum -c DEPLOY_SHA256.txt > "$base/ATTEMPT_USED/deploy_sha.log" 2>&1
# Refuse known competing model/profiler jobs before the model process exists.
ps -eo pid,args > "$base/ATTEMPT_USED/processes_before.txt"
if ps -eo args= | grep -E '(pi05_[^ /]+\.py|torchrun|nsys profile)' | grep -v -E '(grep -E|run_m2_v2_once.sh)' > "$base/ATTEMPT_USED/competing_jobs.txt"; then
  echo 'STOP: known model/profiler detected; preserve attempt' >&2
  exit 2
fi
timeout --signal=TERM --kill-after=10s 300s "$py" "$base/pi05_m2_correctness_v2.py" \
  --preflight --reference "$base/reference" --source-preflight "$base/source_preflight.json" \
  > "$base/ATTEMPT_USED/preflight.log" 2>&1
# Exactly one ordinary model process, no retries and no hardware scope.
timeout --signal=TERM --kill-after=10s 240s "$py" "$base/pi05_m2_correctness_v2.py" \
  --approved-m2-common-v2 --reference "$base/reference" \
  --source-preflight "$base/source_preflight.json" --out "$base/run" \
  > "$base/ATTEMPT_USED/model.log" 2>&1
