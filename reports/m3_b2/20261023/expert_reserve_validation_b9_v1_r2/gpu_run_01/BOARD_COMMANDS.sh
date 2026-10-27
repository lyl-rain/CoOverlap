#!/usr/bin/env bash
# One-shot B9-r2 execution, mirroring GPU_PLAN.md. Run from a host that can reach the board.
# Approved identities (do not substitute):
CONFIG_SHA=6af4210da8df42b004c50169823ba4ba94d42cc7bbad283839ac6d2e44a04cc3
DEPLOY_SHA=f3b4f1b0742721a0af1b45cb5fbde177910059ef50d0f7bf73d4684f7ec591c0
PRED_SHA=301726555eeefa43337d447803365778fe7fd3f0388d03cade7539fb99a53c49
SEL_SHA=6503989f40577b358749b3cc01d0b0c774dc84220354e2d780738035fb31ffdf
HOST=jyh-orin
ROOT=/home/nvidia/rtvla/cooverlap_m3_b9_expert_reserve_20261023
SRC=$(cd "$(dirname "$0")/.." && pwd)

set -e
echo "== 0. local identity check"
shasum -a 256 "$SRC/deployment/CONFIG.json" "$SRC/deployment/DEPLOY_SHA256.txt" \
              "$SRC/prediction/PREDICTION.json" "$SRC/prediction/SELECTION_FREEZE.json"
test "$(shasum -a 256 "$SRC/deployment/CONFIG.json" | cut -d' ' -f1)" = "$CONFIG_SHA"
test "$(shasum -a 256 "$SRC/deployment/DEPLOY_SHA256.txt" | cut -d' ' -f1)" = "$DEPLOY_SHA"
test "$(shasum -a 256 "$SRC/prediction/PREDICTION.json" | cut -d' ' -f1)" = "$PRED_SHA"
test "$(shasum -a 256 "$SRC/prediction/SELECTION_FREEZE.json" | cut -d' ' -f1)" = "$SEL_SHA"

echo "== 1. deploy (deployment/ and prediction/ must be siblings)"
ssh "$HOST" "mkdir -p $ROOT"
rsync -a "$SRC/deployment" "$SRC/prediction" "$HOST:$ROOT/"
ssh "$HOST" "cd $ROOT && sha256sum -c deployment/DEPLOY_SHA256.txt | tail -2 && \
  sha256sum deployment/CONFIG.json prediction/PREDICTION.json prediction/SELECTION_FREEZE.json"

echo "== 2. ordinary-user preflight (read-only; writes the credential)"
ssh "$HOST" "cd $ROOT && python3 deployment/m3_b9_control.py preflight --base deployment --run run_01"

echo "== 3. ONE interactive sudo submit (user types the password on the board)"
echo "   run on the board:  cd $ROOT && sudo python3 deployment/m3_b9_control.py submit \\"
echo "     --base deployment --run run_01 \\"
echo "     --credential-sha \$(sha256sum run_01/PREFLIGHT.json | cut -d' ' -f1) \\"
echo "     --approved-m3-b9-expert-reserve-validation-v1"
read -r -p "press enter after the submit finished: " _

echo "== 4. independent readback (ordinary user)"
ssh "$HOST" "cd $ROOT && python3 deployment/m3_b9_control.py verify-restored --base deployment --run run_01"

echo "== 5. collect"
mkdir -p "$SRC/gpu_run_01/board"
scp -r "$HOST:$ROOT/run_01" "$SRC/gpu_run_01/board/"
ssh "$HOST" "cd $ROOT/run_01 && find . -type f ! -perm -004 -print" > "$SRC/gpu_run_01/root_only_files.txt" || true
(cd "$SRC/gpu_run_01/board" && find run_01 -type f -exec shasum -a 256 {} \; | sort) > "$SRC/gpu_run_01/LOCAL_SHA256.txt"
echo "done; now run: python3 analysis/evaluate_b9.py --result gpu_run_01/board/run_01/model/result.json --out gpu_run_01/analysis"
