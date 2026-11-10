#!/usr/bin/env bash
# One-time setup on the training VM: code, Python environment, pinned model
# weights and the AI CUP rally archive. Safe to rerun; finished steps are skipped.
#   bash setup_vm.sh <branch>
set -euo pipefail

BRANCH="${1:-training/cloud-l4}"
WORK=/data/work
REPO=/data/badminton-match-analyzer
sudo mkdir -p /data && sudo chown "$USER" /data
mkdir -p "$WORK/weights"

if [ ! -d "$REPO/.git" ]; then
  git clone --depth 1 --branch "$BRANCH" \
    https://github.com/Ken0u/badminton-match-analyzer.git "$REPO"
else
  git -C "$REPO" fetch --depth 1 origin "$BRANCH" && git -C "$REPO" checkout -q FETCH_HEAD
fi

if [ ! -f /data/venv/bin/activate ]; then
  rm -rf /data/venv
  # The image's apt state cannot install python3-venv; virtualenv needs no apt.
  python3 -m venv /data/venv 2>/dev/null || {
    rm -rf /data/venv
    python3 -m pip install -q --user virtualenv
    python3 -m virtualenv -q /data/venv
  }
fi
source /data/venv/bin/activate
pip install -q --upgrade pip
pip install -q torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu126
pip install -q -e "$REPO[tracking,download]"

export BADMINTON_ROOT="$WORK" BADMINTON_DATA_DIR="$WORK/processed" BADMINTON_WEIGHTS_DIR="$WORK/weights"
python "$REPO/scripts/download_models.py" --kind player --player-model small
python "$REPO/scripts/download_models.py" --kind shuttle

# AI CUP 2023 part1: 800 labelled singles rallies (CC-BY-4.0, Zenodo 14677727).
if [ ! -f /data/part1.zip ]; then
  if [ ! -f /data/assets.zip ]; then
    wget -q --show-progress -c -O /data/assets.zip.part \
      "https://zenodo.org/records/14677727/files/assets.zip?download=1"
    mv /data/assets.zip.part /data/assets.zip
  fi
  unzip -p /data/assets.zip datasets/part1.zip > /data/part1.zip.part
  mv /data/part1.zip.part /data/part1.zip
  echo "1f14bb969a2a23fef58de76b22bd418d5848dc4f9f8ae6a364d365c1b4c9a07b  /data/part1.zip" | sha256sum -c -
  rm /data/assets.zip
fi

python -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0))"
echo "setup complete"
