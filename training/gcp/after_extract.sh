#!/usr/bin/env bash
# Wait for the extraction workers, train, publish the validation report to the
# serial console (readable after shutdown) and stop the VM to end GPU billing.
set -uo pipefail
cd /data
source venv/bin/activate

while pgrep -f extract_aicup.py >/dev/null; do sleep 60; done

mkdir -p /data/features
ln -sf /data/shards/s*/features/*.json.gz /data/features/
{
  echo "===BADMINTON-REPORT-BEGIN==="
  echo "feature files: $(ls /data/features | wc -l)"
  tail -qn 1 /data/shards/s*.log
  python badminton-match-analyzer/training/train_events.py \
    --features /data/features --output /data/model --epochs 150 2>&1 | tail -n 60
  echo "===BADMINTON-REPORT-END==="
} 2>&1 | tee /data/after.log | sudo tee /dev/ttyS0 >/dev/null

sudo shutdown -h now
