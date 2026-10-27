#!/usr/bin/env bash
# PREPARED ONLY. The flag must follow a new explicit human authorization.
set -euo pipefail
base="$(cd "$(dirname "$0")" && pwd)"
py=/home/nvidia/jetson-torch-env/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$base:/home/nvidia/rtvla/cooverlap_diag_20261014_resource/lib:/home/nvidia/rtvla/FlashRT"
if [[ "${1-}" == --dry-run ]]; then
  exec "$py" "$base/pi05_m2_selection_probe.py" --dry-run
fi
if [[ "${1-}" != --approved-m2-selection-probe-01 || "$#" != 1 ]]; then
  echo 'STOP: new explicit M2 selection-probe authorization is required' >&2
  exit 2
fi
if [[ "$(id -u)" == 0 ]]; then
  echo 'STOP: ordinary nvidia user only' >&2
  exit 2
fi
mkdir "$base/ATTEMPT_USED"
cd "$base"
sha256sum -c DEPLOY_SHA256.txt > "$base/ATTEMPT_USED/deploy_sha.log" 2>&1
ps -eo pid,args > "$base/ATTEMPT_USED/processes_before.txt"
if ps -eo args= | grep -E '(pi05_[^ /]+\.py|torchrun|nsys profile)' | grep -v -E '(grep -E|run_m2_selection_probe.sh)' > "$base/ATTEMPT_USED/competing_jobs.txt"; then
  echo 'STOP: known model/profiler detected; preserve attempt' >&2
  exit 2
fi
timeout --signal=TERM --kill-after=10s 300s "$py" "$base/pi05_m2_selection_probe.py" \
  --preflight --reference "$base/reference" --preflight-out "$base/preflight_credential.json" \
  > "$base/ATTEMPT_USED/preflight.log" 2>&1
timeout --signal=TERM --kill-after=10s 240s "$py" "$base/pi05_m2_selection_probe.py" \
  --approved-m2-selection-probe-01 --reference "$base/reference" \
  --credential "$base/preflight_credential.json" --out "$base/run" \
  > "$base/ATTEMPT_USED/model.log" 2>&1
