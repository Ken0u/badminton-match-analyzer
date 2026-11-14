#!/usr/bin/env bash
# Fine-tune OSNet on DShuttleNet's player letters, score the looks-only player
# grouping on the validation matches before and after, then stop the VM.
#   bash reid_finetune.sh SAMPLES CHECK_MATCH...
# SAMPLES: frames per rally for validation scoring. CHECK_MATCH: training
# matches kept out of fine-tuning to pick the epoch. Matches 2 and 5 are left
# out as well (local tuning matches; 5 is S2 Doubles match 1).
# Results: /data/reid_ft/ (weights, history, train.log), /data/identity_ft/*.log
set -uo pipefail
cd /data
source venv/bin/activate
REPO=/data/badminton-match-analyzer
SAMPLES=$1; shift
CHECK="$*"
FEATURES=/data/reid_features
OUT=/data/identity_ft
mkdir -p "$FEATURES" "$OUT"
ln -sf /data/dshuttlenet/w*/features/ds-*.json.gz "$FEATURES/"

# Every match with features and a video, except validation, test and left out
# (the trainer drops those again; crops of closed matches are never written).
CLOSED=$(python - <<'EOF'
import json
s = json.load(open("/data/badminton-match-analyzer/training/dshuttlenet_splits.json"))
print(" ".join(str(m) for m in s["validation"] + s["test"] + s["left_out"] + [2, 5]))
EOF
)
MATCHES=$(ls "$FEATURES" | sed -E 's/^ds-([0-9]+)-.*/\1/' | sort -un)
OPEN=()
for M in $MATCHES; do
  [[ " $CLOSED " == *" $M "* ]] && continue
  ls /data/dshuttlenet/videos/"$M".* > /dev/null 2>&1 && OPEN+=("$M")
done
echo "crop matches: ${OPEN[*]}" > /data/reid_crops.log
WORKERS=7
for ((w = 0; w < WORKERS; w++)); do
  MINE=()
  for ((i = w; i < ${#OPEN[@]}; i += WORKERS)); do MINE+=("${OPEN[$i]}"); done
  [ ${#MINE[@]} -gt 0 ] && python "$REPO/training/reid_crops.py" --features "$FEATURES" \
    --videos /data/dshuttlenet/videos --matches "${MINE[@]}" --out /data/reid_crops \
    --samples 12 >> /data/reid_crops.log 2>&1 &
done
wait
if [ -z "$(ls /data/reid_crops/*/done 2>/dev/null)" ]; then
  echo "no crops written" >> /data/reid_crops.log; sudo shutdown -h now; exit 1
fi

python "$REPO/training/finetune_reid.py" --crops /data/reid_crops \
  --init /data/reid/osnet_x1_0_msmt17.pth --out /data/reid_ft \
  --check $CHECK --leave-out 2 5 > /data/reid_ft.log 2>&1   || { sudo shutdown -h now; exit 1; }

score() {  # name weights samples
  for MATCH in 33 34 35 37 51 52; do
    python "$REPO/training/identity_probe.py" --features "$FEATURES" \
      --videos /data/dshuttlenet/videos --prefix ds --match "$MATCH" \
      --cache "$OUT/cache-$1" --reid "$2" --samples "$3" > "$OUT/$MATCH-$1.log" 2>&1 &
  done
  wait
}
score base8 /data/reid/osnet_x1_0_msmt17.pth 8
score base$SAMPLES /data/reid/osnet_x1_0_msmt17.pth "$SAMPLES"
score ft$SAMPLES /data/reid_ft/osnet_doubles.pth "$SAMPLES"
touch "$OUT/finished"

sudo shutdown -h now
