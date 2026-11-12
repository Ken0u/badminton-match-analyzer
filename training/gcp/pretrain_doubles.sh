#!/usr/bin/env bash
# Train the four-player event model on singles only (the starting point for
# doubles), in several variants side by side on the one GPU, then stop the VM
# to end GPU billing. Each line of the variants file is an output folder name
# followed by extra train_doubles.py options, e.g.
#   doubles_pre
#   doubles_pre_j --jitter
# Results stay on the disk under /data/<name> and /data/<name>.log.
#   bash pretrain_doubles.sh variants.txt
set -uo pipefail
cd /data
source venv/bin/activate

while read -r NAME OPTIONS; do
  [ -z "$NAME" ] && continue
  # shellcheck disable=SC2086
  python badminton-match-analyzer/training/train_doubles.py --singles-only     --features /data/features --shuttleset /data/shuttleset/features     --teacher /data/model_v2/events.pt --output "/data/$NAME" --epochs 150     $OPTIONS > "/data/$NAME.log" 2>&1 &
done < "$1"
wait

sudo shutdown -h now
