#!/usr/bin/env bash
# Out-of-fold doubles event models for the last-hit work, then final models on
# every training match, several side by side on the one GPU; stops the VM at
# the end unless KEEP_VM=1. Each line of the configs file is a name followed by
# train_doubles.py options added to the v4 recipe (the installed model):
#   B --last-weight 3 --after-weight 3
# The line "A" alone is the v4 recipe itself. Every config is trained on five
# folds of the DShuttleNet training matches (--holdout 5 i), writing
# predictions on the left-out fold, and once on all of them ("all"). Safe to
# rerun after a preemption: finished models are kept.
#   bash last_hit_folds.sh REPO configs.txt OUTDIR [parallel]
set -uo pipefail
REPO=$1; CONFIGS=$2; OUT=$3; PARALLEL=${4:-6}
cd /data
source venv/bin/activate
export PYTHONPATH="$REPO/backend:$REPO/training"
RECIPE="--dshuttlenet /data/dshuttlenet/w*/features --doubles /data/s2doubles/features \
  --init /data/doubles_pre_j/events.pt --lr 5e-4 --jitter --vary-ends --epochs 120 \
  --fixed-threshold 0.7"
mkdir -p "$OUT"
jobs_file="$OUT/jobs.txt"
: > "$jobs_file"
while read -r NAME OPTIONS; do
  [ -z "$NAME" ] && continue
  for fold in 0 1 2 3 4; do
    echo "$NAME/fold$fold $OPTIONS --holdout 5 $fold" >> "$jobs_file"
  done
  echo "$NAME/all $OPTIONS" >> "$jobs_file"
done < "$CONFIGS"

run_one() {
  local name=$1; shift
  # Spot VMs are preempted: a rerun skips models that already finished.
  [ -f "$OUT/$name/validation_report.json" ] && return
  mkdir -p "$OUT/$name"
  local began=$(date +%s)
  # shellcheck disable=SC2086
  python "$REPO/training/train_doubles.py" $RECIPE "$@" --output "$OUT/$name" \
    >> "$OUT/$name/train.log" 2>&1
  echo "$name exit $? in $(( ($(date +%s) - began) / 60 )) min" >> "$OUT/summary.log"
}
export -f run_one
export OUT REPO RECIPE
# One job per line (a line may end in a space); its words become arguments.
# shellcheck disable=SC2016
xargs -d '\n' -P "$PARALLEL" -n 1 bash -c 'run_one $1' _ < "$jobs_file"
echo "all finished $(date -u)" >> "$OUT/summary.log"
touch "$OUT/done"
# A few minutes for a watcher on the laptop to see the done marker.
[ "${KEEP_VM:-0}" = 1 ] || { sleep 240; sudo shutdown -h now; }
