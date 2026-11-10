#!/usr/bin/env bash
# Run ShuttleSet extraction workers over the match videos as they are uploaded
# to /data/shuttleset/videos. Each worker keeps taking unclaimed matches until
# /data/shuttleset/uploads_done exists and a pass finds nothing left. Safe to
# rerun after a spot interruption: finished rallies are skipped.
#   bash shuttleset_workers.sh [workers]
set -uo pipefail
cd /data
source venv/bin/activate
WORKERS="${1:-4}"
export BADMINTON_WEIGHTS_DIR=/data/work/weights
# Claims left by an interrupted run would hide unfinished matches.
rm -rf /data/shuttleset/locks

worker() {
  while true; do
    last=0
    [ -f /data/shuttleset/uploads_done ] && last=1
    python badminton-match-analyzer/training/extract_shuttleset.py \
      --work "/data/shuttleset/w$1" --shared /data/shuttleset \
      --source /data/shuttleset/source --no-download --claim \
      >> "/data/shuttleset/worker$1.log" 2>&1
    [ "$last" = 1 ] && break
    sleep 45
  done
}

for i in $(seq 1 "$WORKERS"); do
  worker "$i" &
  sleep 7
done
wait
echo "extraction finished: $(ls /data/shuttleset/features | wc -l) rallies" \
  | tee -a /data/shuttleset/worker1.log
