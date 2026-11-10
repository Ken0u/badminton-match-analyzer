#!/usr/bin/env bash
# Wait for the ShuttleSet extraction workers, train on AI CUP plus ShuttleSet
# and stop the VM to end GPU billing. Results stay on the disk under
# /data/model_v3 (events.pt, validation_report.json) and /data/model_v3.log.
set -uo pipefail
cd /data
source venv/bin/activate

while pgrep -f '[s]huttleset_workers.sh' >/dev/null; do sleep 60; done

python badminton-match-analyzer/training/train_events.py \
  --features /data/features --shuttleset /data/shuttleset/features \
  --teacher /data/model_v2/events.pt --output /data/model_v3 --epochs 150 \
  > /data/model_v3.log 2>&1

sudo shutdown -h now
