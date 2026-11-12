#!/usr/bin/env bash
# Run DShuttleNet extraction workers over the match videos in
# /data/dshuttlenet/videos (<match_id>.mp4), then stop the VM to end GPU
# billing. A worker claims one match at a time; workers keep looking for new
# videos until /data/dshuttlenet/videos_done exists and nothing is left. Safe
# to rerun after a spot interruption: finished rallies and matches are skipped.
# Features land in /data/dshuttlenet/w<worker>/features.
# A second call with a first worker number adds workers to a running batch.
#   bash dshuttlenet_workers.sh [workers] [first worker number]
set -uo pipefail
cd /data
source venv/bin/activate
WORKERS="${1:-6}"
FIRST="${2:-1}"
BASE=/data/dshuttlenet
export BADMINTON_WEIGHTS_DIR=/data/work/weights
mkdir -p "$BASE/done"
# Claims left by an interrupted run would hide unfinished matches.
[ "$FIRST" = 1 ] && rm -rf "$BASE/locks"
mkdir -p "$BASE/locks"

worker() {
  while true; do
    last=0
    [ -f "$BASE/videos_done" ] && last=1
    for video in "$BASE"/videos/*.mp4; do
      [ -e "$video" ] || continue
      match="$(basename "$video" .mp4)"
      [ -e "$BASE/done/$match" ] && continue
      mkdir "$BASE/locks/$match" 2>/dev/null || continue
      if python badminton-match-analyzer/training/extract_dshuttlenet.py \
        --work "$BASE/w$1" --source "$BASE/source" --videos "$BASE/videos" \
        --matches "$match" >> "$BASE/worker$1.log" 2>&1; then
        touch "$BASE/done/$match"
      fi
    done
    [ "$last" = 1 ] && break
    sleep 60
  done
}

for i in $(seq "$FIRST" "$((FIRST + WORKERS - 1))"); do
  worker "$i" &
  sleep 7
done
wait
# Workers added later may still be busy.
while pgrep -f '[e]xtract_dshuttlenet.py' >/dev/null; do sleep 30; done
echo "extraction finished: $(ls "$BASE"/w*/features | grep -c json.gz) rallies" \
  | tee -a "$BASE/worker1.log"
sudo shutdown -h now
