#!/usr/bin/env bash
# Wait for the operator's single sudo submit to finish, then read back and collect.
set -u
HOST=jyh-orin
ROOT=/home/nvidia/rtvla/cooverlap_m3_b9_expert_reserve_20261023
RUN="$ROOT/deployment/run_01"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$SRC/gpu_run_01/collect.log"
say(){ echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*" | tee -a "$LOG"; }
: > "$LOG"
say "collector start; waiting for $RUN/model/result.json (up to 60 min)"
FOUND=0
for i in $(seq 1 240); do
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "test -s $RUN/model/result.json" 2>/dev/null; then FOUND=1; break; fi
  sleep 15
done
if [ "$FOUND" != 1 ]; then say "NO_RESULT after 60 min; nothing collected"; exit 0; fi
say "result detected"
ssh -o BatchMode=yes "$HOST" "cd $ROOT && python3 deployment/m3_b9_control.py verify-restored --base deployment --run run_01" 2>&1 | tee -a "$LOG"
say "collecting run_01"
mkdir -p "$SRC/gpu_run_01/board"
scp -r -q "$HOST:$RUN" "$SRC/gpu_run_01/board/" || say "SCP_PARTIAL (root-only files expected unreadable)"
if [ ! -s "$SRC/gpu_run_01/board/run_01/model/result.json" ]; then say "RESULT_MISSING_AFTER_COPY"; exit 1; fi
( cd "$SRC/gpu_run_01/board" && find run_01 -type f ! -perm -004 -print ) > "$SRC/gpu_run_01/root_only_files.txt" 2>/dev/null || true
( cd "$SRC/gpu_run_01/board" && find run_01 -type f -exec shasum -a 256 {} \; | sort ) > "$SRC/gpu_run_01/LOCAL_SHA256.txt"
say "collected $(find "$SRC/gpu_run_01/board/run_01" -type f | wc -l | tr -d ' ') files"
python3 - "$SRC/gpu_run_01/board/run_01/model/result.json" <<'PY' 2>&1 | tee -a "$LOG"
import json,sys
d=json.load(open(sys.argv[1]))
print('model status:',d.get('status'))
print('segments:',len(d.get('segments') or []),'checks:',len(d.get('checks') or []))
print('elapsed:',(d.get('protocol') or {}).get('limits') if isinstance(d.get('protocol'),dict) else None)
PY
say "DONE"
