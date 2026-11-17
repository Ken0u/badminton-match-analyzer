"""How far apart two fits of the same still court fall (court_detection noise).

Fits frames a short step apart (default 3 frames, 0.1 s at 30 fps: a broadcast
camera does not move in that time except at a cut) and reports the largest
corner distance between the two fits, in the normalized units of
court_detection.AGREEMENT. Pairs straddling a camera cut show up as large
outliers; they are few and only affect the top tail.

    python training/court_jitter.py video.mp4 [more.mp4 ...] --pairs 300 --output out.json
"""

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
from badminton.court_detection import detect_court


def pair_at(capture, start, step):
    """Two RGB frames `step` apart from about frame `start` (one seek)."""
    capture.set(cv2.CAP_PROP_POS_FRAMES, start)
    ok, first = capture.read()
    for _ in range(step - 1):
        ok = ok and capture.grab()
    ok2, second = capture.read()
    if not (ok and ok2):
        return None, None
    return (
        cv2.cvtColor(first, cv2.COLOR_BGR2RGB),
        cv2.cvtColor(second, cv2.COLOR_BGR2RGB),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("videos", type=Path, nargs="+")
    parser.add_argument("--pairs", type=int, default=300, help="per video")
    parser.add_argument("--step", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    random.seed(args.seed)
    rows = []
    for path in args.videos:
        capture = cv2.VideoCapture(str(path))
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if count < 100:
            continue
        starts = sorted(
            random.sample(range(count - args.step - 1), min(args.pairs, count // 10))
        )
        for start in starts:
            a, b = pair_at(capture, start, args.step)
            if a is None:
                continue
            fa, fb = detect_court(a), detect_court(b)
            if fa["status"] != "detected" or fb["status"] != "detected":
                rows.append(
                    {
                        "video": path.name,
                        "frame": start,
                        "distance": None,
                        "status": [fa["status"], fb["status"]],
                    }
                )
                continue
            gap = np.asarray(fa["corners"]) - np.asarray(fb["corners"])
            rows.append(
                {
                    "video": path.name,
                    "frame": start,
                    "distance": float(np.linalg.norm(gap, axis=1).max()),
                    "height": int(a.shape[0]),
                }
            )
        print(
            path.name,
            sum(r["video"] == path.name and r["distance"] is not None for r in rows),
            flush=True,
        )
    values = np.array([r["distance"] for r in rows if r["distance"] is not None])
    summary = {"pairs_both_detected": len(values)}
    if len(values):
        summary.update(
            {
                f"p{q}": float(np.percentile(values, q))
                for q in (50, 75, 90, 95, 98, 99, 99.5)
            }
        )
        summary["share_over"] = {
            str(t): float((values > t).mean())
            for t in (0.012, 0.016, 0.02, 0.025, 0.03, 0.04, 0.05)
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=1) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
