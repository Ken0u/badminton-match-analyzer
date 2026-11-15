#!/usr/bin/env bash
# Score the looks-only grouping on the DShuttleNet validation matches with one
# set of OSNet weights, then stop the VM.
#   bash identity_score.sh NAME WEIGHTS SAMPLES
# Results: /data/identity_ft/<match>-NAME.log
set -uo pipefail
cd /data
source venv/bin/activate
REPO=/data/badminton-match-analyzer
OUT=/data/identity_ft
mkdir -p "$OUT"
for MATCH in 33 34 35 37 51 52; do
  python "$REPO/training/identity_probe.py" --features /data/reid_features \
    --videos /data/dshuttlenet/videos --prefix ds --match "$MATCH" \
    --cache "$OUT/cache-$1" --reid "$2" --samples "$3" > "$OUT/$MATCH-$1.log" 2>&1 &
done
wait
touch "$OUT/finished-$1"
sudo shutdown -h now
