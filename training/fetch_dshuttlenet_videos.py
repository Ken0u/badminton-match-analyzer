"""Download the BWF TV broadcasts DShuttleNet's labels refer to.

The dataset names each match's video but ships none. videos.json lists the
YouTube upload found for each match by title (players, tournament, round).
Files are saved as <match_id>.mp4 at 720p and at most 30 fps, the form the
labels' frame numbers were checked against. Existing files are kept.

    python training/fetch_dshuttlenet_videos.py
"""

import argparse
import json
import sys
from pathlib import Path

import yt_dlp

LIST = Path(__file__).with_name("dshuttlenet_videos.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--videos", type=Path, default=Path("data/datasets/dshuttlenet/videos")
    )
    parser.add_argument("--matches", type=int, nargs="*")
    args = parser.parse_args()
    args.videos.mkdir(parents=True, exist_ok=True)
    failed = []
    for match, video in json.loads(LIST.read_text(encoding="utf-8")).items():
        if args.matches and int(match) not in args.matches:
            continue
        target = args.videos / f"{match}.mp4"
        if target.exists():
            continue
        options = {
            "format": "bv*[height=720][fps<=30][ext=mp4]/bv*[height=720][fps<=30]",
            "outtmpl": str(target),
            "quiet": True,
            "noprogress": True,
            "retries": 5,
        }
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([f"https://www.youtube.com/watch?v={video['id']}"])
            print(f"match {match}: saved {target.stat().st_size >> 20} MB", flush=True)
        except Exception as error:
            failed.append(match)
            print(f"match {match} FAILED: {error}", flush=True)
    print(f"finished; failed: {failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
