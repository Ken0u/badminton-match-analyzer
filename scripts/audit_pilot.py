"""Render exact source-frame contact sheets without prediction overlays.

This read-only aid writes images, never annotations. Inspect the source before
using model proposals to avoid mistaking a predicted trajectory change for a hit.
"""

import argparse
import json
from pathlib import Path

from badminton.config import DATA, ROOT
from badminton.video import iter_frames, timestamps_for
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id")
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--tile-width", type=int, default=384)
    parser.add_argument("--columns", type=int, default=5)
    parser.add_argument("--rows", type=int, default=5)
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/pilot-review")
    args = parser.parse_args()
    if min(args.step, args.tile_width, args.columns, args.rows) < 1:
        parser.error("Rendering sizes and frame step must be positive")
    metadata = json.loads((DATA / args.video_id / "metadata.json").read_text())
    times = timestamps_for(DATA, args.video_id)
    if not 0 <= args.start < args.end <= len(times):
        parser.error("Choose a nonempty source-frame range within the video")
    args.output.mkdir(parents=True, exist_ok=True)
    selected = []
    for index, timestamp, frame in iter_frames(
        metadata, ROOT, times, args.start, args.end
    ):
        if (index - args.start) % args.step:
            continue
        source = frame.to_image()
        height = round(source.height * args.tile_width / source.width)
        tile = Image.new("RGB", (args.tile_width, height + 24), "#101010")
        tile.paste(source.resize((args.tile_width, height)), (0, 24))
        ImageDraw.Draw(tile).text(
            (6, 5), f"frame {index} | {timestamp:.3f}s", fill="white"
        )
        selected.append((index, tile))
    page_size = args.columns * args.rows
    for offset in range(0, len(selected), page_size):
        page = selected[offset : offset + page_size]
        width, height = page[0][1].size
        canvas = Image.new("RGB", (width * args.columns, height * args.rows), "black")
        for number, (_, tile) in enumerate(page):
            canvas.paste(
                tile,
                ((number % args.columns) * width, (number // args.columns) * height),
            )
        target = args.output / f"{metadata['mode']}-{page[0][0]}-{page[-1][0]}.jpg"
        canvas.save(target, quality=95)
        print(target)


if __name__ == "__main__":
    main()
