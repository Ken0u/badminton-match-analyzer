#!/usr/bin/env bash
# Score the looks-only player grouping (identity_probe.py) on DShuttleNet
# matches it was not tuned on, then stop the VM to end GPU billing. Each match
# is scored with all the evidence and again without the whole-person
# description. Results: /data/identity/<match>.log and <match>-plain.log.
#   bash identity_validation.sh 33 34 35 37 51 52
set -uo pipefail
cd /data
source venv/bin/activate
OUT=/data/identity
REPO=/data/badminton-match-analyzer
mkdir -p "$OUT"

for MATCH in "$@"; do
  (
    # The workers left each match's rallies spread over their own folders.
    mkdir -p "$OUT/features/$MATCH"
    ln -sf /data/dshuttlenet/w*/features/ds-"$MATCH"-*.json.gz "$OUT/features/$MATCH/"
    run() {
      python "$REPO/training/identity_probe.py" \
        --features "$OUT/features/$MATCH" --videos /data/dshuttlenet/videos \
        --prefix ds --match "$MATCH" --cache "$OUT/cache" \
        --reid /data/reid/osnet_x1_0_msmt17.pth "$@"
    }
    run > "$OUT/$MATCH.log" 2>&1
    run --use length shirt shorts legs shoes > "$OUT/$MATCH-plain.log" 2>&1
  ) &
done
wait
touch "$OUT/finished"

sudo shutdown -h now
