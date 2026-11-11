#!/usr/bin/env bash
# Train several variants of the event model side by side on the one GPU, then
# stop the VM to end GPU billing. Each line of the variants file is an output
# folder name followed by extra train_events.py options, e.g.
#   model_v5a --bucket
#   model_v5b --bucket --norm step
# Results stay on the disk under /data/<name> and /data/<name>.log.
#   bash train_variants.sh variants.txt
set -uo pipefail
cd /data
source venv/bin/activate

while read -r NAME OPTIONS; do
  [ -z "$NAME" ] && continue
  # shellcheck disable=SC2086
  python badminton-match-analyzer/training/train_events.py \
    --features /data/features --shuttleset /data/shuttleset/features \
    --teacher /data/model_v2/events.pt --output "/data/$NAME" --epochs 150 \
    $OPTIONS > "/data/$NAME.log" 2>&1 &
done < "$1"
wait

sudo shutdown -h now
