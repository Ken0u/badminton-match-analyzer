#!/usr/bin/env bash
# Wait for the ShuttleSet extraction workers, train on AI CUP plus ShuttleSet
# and stop the VM to end GPU billing. Results stay on the disk under
# /data/<output> (events.pt, validation_report.json) and /data/<output>.log.
#   bash after_shuttleset.sh [output folder name, default model_v3]
set -uo pipefail
cd /data
OUTPUT="${1:-model_v3}"
source venv/bin/activate

while pgrep -f '[s]huttleset_workers.sh' >/dev/null; do sleep 60; done

python badminton-match-analyzer/training/train_events.py \
  --features /data/features --shuttleset /data/shuttleset/features \
  --teacher /data/model_v2/events.pt --output "/data/$OUTPUT" --epochs 150 \
  > "/data/$OUTPUT.log" 2>&1

sudo shutdown -h now
