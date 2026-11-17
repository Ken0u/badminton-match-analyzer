#!/usr/bin/env bash
# Re-run full-match processing of the step 3 validation clips with new code,
# in the stores they were first processed in (/data/step3/w*/processed), so
# unchanged stages (segments, shuttle) are reused and only stages whose code
# changed run again. Then pack the processed stores for the laptop.
#   bash step3_rerun.sh /data/step3/code.tgz OUTDIR clip [clip ...]
set -uo pipefail
BASE=/data/step3
CODE=$1; OUT=$2; shift 2
rm -rf "$OUT/repo" && mkdir -p "$OUT/repo" "$OUT/logs"
tar xzf "$CODE" -C "$OUT/repo"
source /data/venv/bin/activate
export PYTHONPATH="$OUT/repo/backend" BADMINTON_WEIGHTS_DIR="$BASE/weights"

run() {
  local name=$1
  # After a preemption, clips that already finished are not run again.
  grep -q "^$name .* exit 0 " "$OUT/logs/summary.log" 2>/dev/null && return
  local result="$BASE/claims/$name/result.json"
  local id worker
  id=$(python -c "import json; print(json.load(open('$result'))['video_id'])")
  worker=$(for w in "$BASE"/w*; do [ -d "$w/processed/$id" ] && basename "$w"; done | head -1)
  if [ -z "$worker" ]; then echo "$name: no store for $id" >> "$OUT/logs/summary.log"; return; fi
  local began=$(date +%s)
  BADMINTON_ROOT="$BASE/$worker" BADMINTON_DATA_DIR="$BASE/$worker/processed" \
    python -m badminton.cli process "$id" > "$OUT/logs/$name.log" 2>&1
  local code=$?
  echo "$name $id $worker exit $code in $(( ($(date +%s) - began) / 60 )) min" >> "$OUT/logs/summary.log"
}

# A store runs one processing job at a time: clips of one store in turn,
# the stores side by side.
store_of() {
  local id
  id=$(python -c "import json; print(json.load(open('$BASE/claims/$1/result.json'))['video_id'])")
  for w in "$BASE"/w*; do [ -d "$w/processed/$id" ] && basename "$w"; done | head -1
}
declare -A queue
for name in "$@"; do
  w=$(store_of "$name")
  queue[$w]="${queue[$w]:-} $name"
done
for w in "${!queue[@]}"; do
  ( for name in ${queue[$w]}; do run "$name"; done ) &
done
wait
echo "rerun finished $(date -u)" >> "$OUT/logs/summary.log"
touch "$OUT/rerun_done"
