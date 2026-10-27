#!/usr/bin/env bash
# Bounded watcher for the single approved B9-r2 run.
# It waits for the board to become reachable, then: identity check -> deploy ->
# SHA verify -> ordinary-user preflight -> (only if passwordless sudo) ONE submit
# -> verify-restored -> collect.  If sudo needs a password it stops before submit.
set -u
HOST=jyh-orin
ROOT=/home/nvidia/rtvla/cooverlap_m3_b9_expert_reserve_20261023
SRC="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$SRC/gpu_run_01/execution.log"
CONFIG_SHA=6af4210da8df42b004c50169823ba4ba94d42cc7bbad283839ac6d2e44a04cc3
DEPLOY_SHA=f3b4f1b0742721a0af1b45cb5fbde177910059ef50d0f7bf73d4684f7ec591c0
PRED_SHA=301726555eeefa43337d447803365778fe7fd3f0388d03cade7539fb99a53c49
SEL_SHA=6503989f40577b358749b3cc01d0b0c774dc84220354e2d780738035fb31ffdf
say(){ echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*" | tee -a "$LOG"; }
: > "$LOG"
say "watcher start; source=$SRC"
REACHABLE=0
for i in $(seq 1 120); do
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" true 2>/dev/null; then REACHABLE=1; break; fi
  sleep 15
done
if [ "$REACHABLE" != 1 ]; then say "NOT_REACHABLE after 30 min; nothing executed"; exit 0; fi
say "board reachable"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" 'hostname; id -un' 2>&1 | tee -a "$LOG"
HOSTNAME_B=$(ssh -o BatchMode=yes "$HOST" hostname 2>/dev/null)
USER_B=$(ssh -o BatchMode=yes "$HOST" id -un 2>/dev/null)
if [ "$HOSTNAME_B" != "jyh-orin" ] || [ "$USER_B" != "nvidia" ]; then
  say "IDENTITY_MISMATCH host=$HOSTNAME_B user=$USER_B; stop"; exit 1
fi
say "checking for a consumed attempt"
if ssh -o BatchMode=yes "$HOST" "test -e $ROOT/run_01/SCOPE_ATTEMPT_USED || test -e $ROOT/run_01/MODEL_ATTEMPT_USED"; then
  say "ATTEMPT_ALREADY_USED under $ROOT/run_01; stop without submitting"; exit 1
fi
say "deploying deployment/ and prediction/"
ssh -o BatchMode=yes "$HOST" "mkdir -p $ROOT" || { say "MKDIR_FAILED"; exit 1; }
rsync -a -e "ssh -o BatchMode=yes" "$SRC/deployment" "$SRC/prediction" "$HOST:$ROOT/" || { say "RSYNC_FAILED"; exit 1; }
say "verifying frozen identities on the board"
OUT=$(ssh -o BatchMode=yes "$HOST" "cd $ROOT && sha256sum deployment/CONFIG.json deployment/DEPLOY_SHA256.txt prediction/PREDICTION.json prediction/SELECTION_FREEZE.json && sha256sum -c deployment/DEPLOY_SHA256.txt 2>&1 | tail -1")
echo "$OUT" | tee -a "$LOG"
echo "$OUT" | grep -q "$CONFIG_SHA" || { say "CONFIG_SHA_MISMATCH; stop"; exit 1; }
echo "$OUT" | grep -q "$DEPLOY_SHA" || { say "DEPLOY_SHA_MISMATCH; stop"; exit 1; }
echo "$OUT" | grep -q "$PRED_SHA" || { say "PRED_SHA_MISMATCH; stop"; exit 1; }
echo "$OUT" | grep -q "$SEL_SHA" || { say "SEL_SHA_MISMATCH; stop"; exit 1; }
say "running ordinary-user preflight"
ssh -o BatchMode=yes "$HOST" "cd $ROOT && python3 deployment/m3_b9_control.py preflight --base deployment --run run_01" 2>&1 | tee -a "$LOG"
if ! ssh -o BatchMode=yes "$HOST" "test -s $ROOT/run_01/PREFLIGHT.json"; then say "PREFLIGHT_MISSING; stop"; exit 1; fi
CRED=$(ssh -o BatchMode=yes "$HOST" "sha256sum $ROOT/run_01/PREFLIGHT.json | cut -d' ' -f1")
say "preflight credential $CRED"
if ! ssh -o BatchMode=yes "$HOST" "sudo -n true" 2>/dev/null; then
  say "SUDO_REQUIRES_PASSWORD: staged; run the one submit on the board and tell the operator"
  say "cd $ROOT && sudo python3 deployment/m3_b9_control.py submit --base deployment --run run_01 --credential-sha $CRED --approved-m3-b9-expert-reserve-validation-v1"
  exit 0
fi
say "passwordless sudo available; submitting ONCE"
ssh -o BatchMode=yes "$HOST" "cd $ROOT && sudo -n python3 deployment/m3_b9_control.py submit --base deployment --run run_01 --credential-sha $CRED --approved-m3-b9-expert-reserve-validation-v1" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
say "submit exit $RC"
if [ "$RC" != 0 ]; then say "SUBMIT_FAILED; not retrying"; exit 1; fi
say "independent readback"
ssh -o BatchMode=yes "$HOST" "cd $ROOT && python3 deployment/m3_b9_control.py verify-restored --base deployment --run run_01" 2>&1 | tee -a "$LOG"
say "collecting run_01"
mkdir -p "$SRC/gpu_run_01/board"
scp -r -q "$HOST:$ROOT/run_01" "$SRC/gpu_run_01/board/" || say "SCP_PARTIAL (root-only files are expected to be unreadable)"
if [ ! -s "$SRC/gpu_run_01/board/run_01/model/result.json" ]; then say "RESULT_MISSING_AFTER_COPY; stop"; exit 1; fi
( cd "$SRC/gpu_run_01/board" && find run_01 -type f ! -perm -004 -print ) > "$SRC/gpu_run_01/root_only_files.txt" 2>/dev/null || true
( cd "$SRC/gpu_run_01/board" && find run_01 -type f -exec shasum -a 256 {} \; | sort ) > "$SRC/gpu_run_01/LOCAL_SHA256.txt"
say "collected; files=$(find "$SRC/gpu_run_01/board/run_01" -type f | wc -l | tr -d ' ')"
say "DONE"
