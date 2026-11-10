"""Draw the latest full-match suggestions onto a video for a quick look.

This previews unreviewed model output: player boxes, the shuttle, and a label
at every suggested contact (who hit, stroke, forehand/backhand). It is separate
from the app's reviewed-annotation exports.

    python training/render_suggestions.py VIDEO_ID --output preview.mp4
"""

import argparse
import json
from fractions import Fraction
from pathlib import Path

import av
import cv2
from badminton.config import DATA, ROOT
from badminton.pipeline import owned_candidates
from badminton.storage import Store

HOLD_S = 1.2
COLORS = {"far": (0, 200, 255), "near": (80, 80, 255)}


def load(store, video_id):
    job = next(
        j
        for j in store.jobs(video_id)
        if j["kind"] == "analysis" and j["status"] == "completed"
    )
    folder = DATA / video_id
    plan = json.loads(
        (
            folder / "analysis" / job["details"]["analysis_key"] / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    players, shuttle, strokes = {}, {}, []
    for part in plan["parts"]:
        runs = {
            name: json.loads(
                (folder / "runs" / f"{part['stages'][name]['run_id']}.json").read_text(
                    encoding="utf-8"
                )
            )
            for name in ("players", "shuttle", "contacts")
        }
        first = runs["contacts"].get(
            "analysis_core_start_frame", runs["contacts"]["start_frame"]
        )
        last = runs["contacts"].get(
            "analysis_core_end_frame", runs["contacts"]["end_frame"]
        )
        for row in runs["players"]["frames"]:
            if first <= row["frame"] < last:
                players[row["frame"]] = row["players"]
        for row in runs["shuttle"]["frames"]:
            if first <= row["frame"] < last and row["shuttle"].get("visible"):
                shuttle[row["frame"]] = (row["shuttle"]["x"], row["shuttle"]["y"])
        strokes += [c for c in owned_candidates(runs["contacts"]) if "learned" in c]
    return players, shuttle, sorted(strokes, key=lambda c: c["frame"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video_id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = Store(DATA)
    video = store.video(args.video_id)
    players, shuttle, strokes = load(store, args.video_id)
    fps = Fraction(video["fps"]).limit_denominator(1000)
    hold = round(HOLD_S * float(fps))
    source = av.open(str(ROOT / video["path"]))
    sink = av.open(str(args.output), "w")
    stream = sink.add_stream("libx264", rate=fps)
    stream.width, stream.height = video["width"], video["height"]
    stream.pix_fmt = "yuv420p"
    stream.options = {"preset": "veryfast", "crf": "23"}
    pending, count = 0, 0
    for index, frame in enumerate(source.decode(video=0)):
        image = frame.to_ndarray(format="bgr24")
        for person in players.get(index, []):
            x1, y1, x2, y2 = (int(v) for v in person["box"])
            cv2.rectangle(image, (x1, y1), (x2, y2), (200, 200, 200), 1)
        for back in range(8):
            if index - back in shuttle:
                x, y = shuttle[index - back]
                cv2.circle(image, (int(x), int(y)), 5 - back // 2, (0, 255, 255), -1)
        while pending < len(strokes) and strokes[pending]["frame"] + hold < index:
            pending += 1
        for stroke in strokes[pending:]:
            if stroke["frame"] > index:
                break
            info = stroke["learned"]
            color = COLORS[info["court_end"]]
            age = index - stroke["frame"]
            person = next(
                (
                    p
                    for p in players.get(index, [])
                    if p.get("track_id") == info["track_id"]
                ),
                None,
            )
            if person and age < 6:
                x1, y1, x2, y2 = (int(v) for v in person["box"])
                cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)
            name = "serve" if info["kind"] == "serve" else info["family"]
            text = f"{info['court_end']} player: {name}, {info['side']}"
            y = 60 if info["court_end"] == "far" else video["height"] - 40
            cv2.putText(
                image, text, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 6
            )
            cv2.putText(image, text, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 1.1, color, 2)
        cv2.putText(
            image,
            "unreviewed model suggestions",
            (video["width"] - 330, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1,
        )
        for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="bgr24")):
            sink.mux(packet)
        count += 1
    for packet in stream.encode():
        sink.mux(packet)
    sink.close()
    source.close()
    print(f"{count} frames, {len(strokes)} suggested contacts -> {args.output}")


if __name__ == "__main__":
    main()
