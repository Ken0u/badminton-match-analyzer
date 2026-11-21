"""Prepare silent native-frame training review excerpts, with opaque IDs and no labels."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import av
from badminton.av_runtime import open_media


def digest(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        while b := f.read(4 << 20):
            h.update(b)
    return h.hexdigest()


def run(packet):
    out = packet / "blinded-clips-v1"
    out.mkdir(exist_ok=False)
    rows = list(
        csv.DictReader((packet / "training-contacts.csv").open(encoding="utf8"))
    )
    verified = {}
    manifest = []
    for r in rows:
        src = Path(r["native_video"])
        hint = int(r["published_frame_hint"])
        key = r["example"]
        dst = out / (key + ".mp4")
        assert key == f"T{len(manifest) + 1:03}"
        if src not in verified:
            verified[src] = digest(src)
        assert verified[src] == r["video_sha256"]
        with open_media(str(src)) as media:
            video = media.streams.video[0]
            fps = video.average_rate
            tb = video.time_base
            origin = next(media.decode(video)).pts
            lo = max(0, hint - round(float(fps) * 1.5))
            hi = hint + round(float(fps) * 1.5)
            media.seek(max(0, origin + int((lo / fps) / tb) - 1), stream=video)
            timeline = []
            with av.open(str(dst), "w") as output:
                stream = output.add_stream("libx264", rate=fps)
                stream.width = video.width
                stream.height = video.height
                stream.pix_fmt = "yuv420p"
                stream.options = {"crf": "18", "preset": "veryfast"}
                for frame in media.decode(video):
                    assert frame.pts is not None
                    stamp = frame.pts
                    ordinal = round((stamp - origin) * tb * fps)
                    if ordinal < lo:
                        continue
                    if ordinal > hi:
                        break
                    assert (
                        ordinal == lo + len(timeline)
                        and abs(float((stamp - origin) * tb - ordinal / fps)) < 0.0011
                        and getattr(frame, "rotation", 0) == 0
                    )
                    timeline.append(stamp)
                    frame.pts = len(timeline) - 1
                    frame.time_base = 1 / fps
                    for pkt in stream.encode(frame):
                        output.mux(pkt)
                for pkt in stream.encode(None):
                    output.mux(pkt)
            assert len(timeline) == hi - lo + 1
        with open_media(str(dst)) as check:
            assert sum(1 for _ in check.decode(video=0)) == len(timeline)
        manifest.append(
            {
                "example": key,
                "source_sha256": verified[src],
                "source_time_base": str(tb),
                "source_frame_span": [lo, hi],
                "hint_in_excerpt": hint - lo,
                "source_pts": timeline,
                "proxy_sha256": digest(dst),
            }
        )
    (out / "source-index.json").write_text(json.dumps(manifest, indent=2))
    print(len(rows), "verified excerpts")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("packet", type=Path)
    run(p.parse_args().packet)
