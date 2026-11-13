#!/usr/bin/env bash
# Train the four-player event model on the doubles sets in several variants
# side by side on the one GPU, then stop the VM to end GPU billing. Each line
# of the variants file is an output folder name followed by train_doubles.py
# options, e.g.
#   doubles_v2 --init /data/doubles_pre_j/events.pt --lr 5e-4 --jitter
# Every variant gets DShuttleNet and S2 Doubles; the word SINGLES in a line is
# replaced by the options that mix the singles sets in.
# Results stay on the disk under /data/<name> and /data/<name>.log.
#   bash train_doubles_variants.sh variants.txt
set -uo pipefail
cd /data
source venv/bin/activate
SINGLES="--features /data/features --shuttleset /data/shuttleset/features --teacher /data/model_v2/events.pt"

while read -r NAME OPTIONS; do
  [ -z "$NAME" ] && continue
  OPTIONS="${OPTIONS//SINGLES/$SINGLES}"
  # shellcheck disable=SC2086
  python badminton-match-analyzer/training/train_doubles.py \
    --dshuttlenet /data/dshuttlenet/w*/features \
    --doubles /data/s2doubles/features --output "/data/$NAME" \
    $OPTIONS > "/data/$NAME.log" 2>&1 &
done < "$1"
wait

sudo shutdown -h now
