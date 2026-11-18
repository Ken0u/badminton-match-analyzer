"""Copy one processed match into design/prototypes/data/ for the UI prototypes.

Usage: python design/prototypes/prepare_data.py [video id ...]
Writes data/<name>/analysis.json, stats.json, poster.jpg, players/P1.jpg..,
and video.mp4 (a copy of the source video). The data folder is git-ignored.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
OUT = Path(__file__).resolve().parent / "data"
DEFAULT = ["c406a1187130b845", "970dbd8adfe548d8"]


def prepare(video_id):
    src = PROCESSED / video_id
    analysis = json.loads((src / "match_analysis.json").read_text(encoding="utf-8"))
    name = Path(analysis["video"]["name"]).stem
    out = OUT / name
    (out / "players").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src / "match_analysis.json", out / "analysis.json")
    subprocess.run(
        [sys.executable, "-m", "badminton.cli", "clip-stats", video_id,
         "--output", str(out / "stats.json")],
        check=True, cwd=ROOT,
    )
    if (src / "poster.jpg").exists():
        shutil.copyfile(src / "poster.jpg", out / "poster.jpg")
    for player in analysis["players"]:
        if player.get("thumbnail"):
            shutil.copyfile(src / player["thumbnail"], out / "players" / f"{player['id']}.jpg")
    video = ROOT / analysis["video"]["name"]
    if video.exists() and not (out / "video.mp4").exists():
        shutil.copyfile(video, out / "video.mp4")
    print(name, "->", out)


if __name__ == "__main__":
    for vid in sys.argv[1:] or DEFAULT:
        prepare(vid)
