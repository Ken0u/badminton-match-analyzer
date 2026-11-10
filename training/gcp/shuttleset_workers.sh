#!/usr/bin/env bash
# Run ShuttleSet extraction workers over the match videos as they are uploaded
# to /data/shuttleset/videos, until /data/shuttleset/uploads_done exists and a
# pass finds nothing left. Safe to rerun after a spot interruption.
#   bash shuttleset_workers.sh [workers]
set -uo pipefail
cd /data
source venv/bin/activate
WORKERS="${1:-4}"
rm -rf /data/shuttleset/locks
while true; do
  last=0
  [ -f /data/shuttleset/uploads_done ] && last=1
  rm -rf /data/shuttleset/locks
  for i in $(seq 1 "$WORKERS"); do
    python badminton-match-analyzer/training/extract_shuttleset.py \
      --work /data/shuttleset --source /data/shuttleset/source \
      --no-download --claim >> "/data/shuttleset/worker$i.log" 2>&1 &
    sleep 5
  done
  wait
  [ "$last" = 1 ] && break
  sleep 60
done
echo "extraction finished: $(ls /data/shuttleset/features | wc -l) rallies" >> /data/shuttleset/worker1.log
