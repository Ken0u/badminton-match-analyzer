#!/usr/bin/env bash
# Process the rally evaluation clips (training/rally_clips.py) on the VM, then
# stop the VM. DShuttleNet clips are cut here from /data/dshuttlenet/videos;
# ShuttleSet clips are uploaded into /data/step3/clips by the laptop, which
# touches /data/step3/uploads_done when it has finished. Workers take clips in
# spec order (validation first). Safe to rerun: claimed clips are skipped, so
# remove a failed clip's folder under claims/ to retry it.
#   bash rally_clips.sh [workers]
set -uo pipefail
BASE=/data/step3
WORKERS="${1:-3}"
source /data/venv/bin/activate
export PYTHONPATH="$BASE/repo/backend" BADMINTON_WEIGHTS_DIR="$BASE/weights"
SCRIPT="$BASE/repo/training/rally_clips.py"
cd "$BASE"
TOTAL=$(python -c "import json; print(len(json.load(open('$BASE/clips.json'))))")

( python "$SCRIPT" cut "$BASE/clips.json" --dataset dshuttlenet \
    --videos /data/dshuttlenet/videos --output "$BASE/clips" \
    >> "$BASE/logs/cut.log" 2>&1; touch "$BASE/cut_done" ) &

worker() {
  while true; do
    inputs_done=0
    [ -f "$BASE/uploads_done" ] && [ -f "$BASE/cut_done" ] && inputs_done=1
    python "$SCRIPT" process "$BASE/clips.json" --clips "$BASE/clips" \
      --work "$BASE/w$1" --claims "$BASE/claims" --log "$BASE/logs/worker$1.log"
    [ "$(ls "$BASE/claims" | wc -l)" -ge "$TOTAL" ] && break
    # Every input was present before that pass, so nothing is left to claim.
    [ "$inputs_done" = 1 ] && break
    sleep 60
  done
}

for i in $(seq 1 "$WORKERS"); do
  worker "$i" &
  sleep 20
done
wait
echo "finished $(date -u)" >> "$BASE/logs/finished.log"
sudo shutdown -h now
