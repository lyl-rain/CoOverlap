#!/usr/bin/env bash
set -u
HOST=jyh-orin
ROOT=/home/nvidia/rtvla/cooverlap_m3_b10_credible_selector_20261023_r1
RUN="$ROOT/deployment/run_01"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$SRC/gpu_run_01/collect.log"
say(){ echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*" | tee -a "$LOG"; }
: > "$LOG"
say "collector start; waiting for $RUN/model/result.json"
for i in $(seq 1 240); do
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "test -s $RUN/model/result.json" 2>/dev/null && break
  sleep 15
done
ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "test -s $RUN/model/result.json" 2>/dev/null || { say "NO_RESULT"; exit 0; }
say "result detected; independent readback"
ssh -o BatchMode=yes "$HOST" "cd $ROOT/deployment && python3 m3_b10_control.py verify-restored --base . --run run_01" 2>&1 | tee -a "$LOG"
mkdir -p "$SRC/gpu_run_01/board"
rsync -a --exclude=clock_before.json -e "ssh -o BatchMode=yes" "$HOST:$RUN/" "$SRC/gpu_run_01/board/run_01/" || say "RSYNC_PARTIAL"
( cd "$SRC/gpu_run_01/board" && find run_01 -type f -exec shasum -a 256 {} \; | sort ) > "$SRC/gpu_run_01/LOCAL_SHA256.txt"
say "collected $(find "$SRC/gpu_run_01/board/run_01" -type f | wc -l | tr -d ' ') files"
say DONE
