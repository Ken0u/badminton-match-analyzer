"""Draw who is who through a processed doubles video, for a quick look.

The app follows a player only within one camera view. This groups every
view's four player tracks into the same four people by their looks alone
(identity_probe.py: clothing and shoe colour, body length, a whole-person
description), with no use of the order of rallies, and draws each person in
one colour with one number through the whole video. Nothing is stored: it is
a preview of an experiment, for judging by eye where no labels exist.

    python training/identity_preview.py VIDEO_ID --output preview.mp4
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

import av
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import identity_probe as probe
import osnet
from badminton.config import DATA, ROOT
from badminton.storage import Store

COLORS = ((60, 60, 255), (0, 200, 255), (255, 140, 40), (80, 220, 80))
UNSURE = (200, 200, 200)
# Below this many noise units between the two ways round, a view's partners
# are drawn as unsure.
SURE = 3.0


def load(store, video_id):
    """Per frame the tracked players, each with its joined track and end."""
    job = next(
        j
        for j in store.jobs(video_id)
        if j["kind"] == "analysis" and j["status"] == "completed"
    )
    folder = DATA / video_id

    def run(run_id):
        return json.loads((folder / "runs" / f"{run_id}.json").read_text("utf-8"))

    plan = json.loads(
        (
            folder / "analysis" / job["details"]["analysis_key"] / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    chains = {
        (t["run_id"], t["track_id"]): (
            (t["camera_segment_start_frame"], t["continuity_id"]),
            t.get("court_end"),
        )
        for t in run(plan["identities"]["run_id"])["tracks"]
    }
    rows = {}
    for part in plan["parts"]:
        contacts = run(part["stages"]["contacts"]["run_id"])
        first = contacts.get("analysis_core_start_frame", contacts["start_frame"])
        last = contacts.get("analysis_core_end_frame", contacts["end_frame"])
        run_id = part["stages"]["players"]["run_id"]
        for row in run(run_id)["frames"]:
            if not first <= row["frame"] < last:
                continue
            people = []
            for person in row["players"]:
                chain, end = chains.get((run_id, person.get("track_id")), (None, None))
                if chain and end:
                    people.append(person | {"chain": chain, "end": end})
            rows[row["frame"]] = {"frame": row["frame"], "players": people}
    return rows


def views(rows):
    """Camera views with players at both ends, two slots per end."""
    by_view = defaultdict(list)
    for frame in sorted(rows):
        for view in {p["chain"][0] for p in rows[frame]["players"]}:
            by_view[view].append(rows[frame])
    found = []
    for view, own in sorted(by_view.items()):
        seen = Counter(
            (p["end"], p["chain"])
            for row in own
            for p in row["players"]
            if p["chain"][0] == view
        )
        slots = {}
        for number, end in enumerate(("far", "near")):
            # An official or a stray detection is shorter-lived than a player.
            longest = sorted(
                ((n, chain) for (e, chain), n in seen.items() if e == end),
                reverse=True,
            )[:2]
            for place, (_, chain) in enumerate(longest):
                slots[chain] = number * 2 + place
        if len(own) >= probe.SAMPLES and {s // 2 for s in slots.values()} == {0, 1}:
            found.append({"view": view, "rows": own, "slots": slots})
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video_id")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--reid", type=Path, default=Path("models/weights/reid/osnet_x1_0_msmt17.pth")
    )
    args = parser.parse_args()
    store = Store(DATA)
    video = store.video(args.video_id)
    rows = load(store, args.video_id)
    found = views(rows)
    model = osnet.load(args.reid) if args.reid.exists() else None
    capture = probe.Video(ROOT / video["path"])
    rallies = []
    for view in found:
        slots, own = view["slots"], view["rows"]
        tracks = probe.looks_of(
            own,
            list(range(len(own))),
            lambda index, own=own: own[index]["frame"],
            lambda row, person, slots=slots: slots.get(person["chain"]),
            capture,
            model,
        )
        by_slot = {slot: chain for chain, slot in slots.items()}
        for track in tracks:
            track["chain"] = by_slot[track["slot"]]
        rallies.append({"clip": view["view"], "tracks": tracks})
    capture.release()
    probe.vectors(rallies, ["length", *probe.PATCHES, "reid"])
    probe.group(rallies)

    people, margins, whole = {}, [], 0
    for rally in rallies:
        named = [t for t in rally["tracks"] if "person" in t]
        whole += len(named) == probe.SLOTS
        for track in rally["tracks"]:
            sure = track.get("margin", 0.0) >= SURE
            people[track["chain"]] = (track.get("person"), track.get("team"), sure)
        margins += [t["margin"] for t in named[::2]]
    print(
        f"{len(rallies)} views with players at both ends, {whole} with four "
        f"players named; partner margin median {np.median(margins):.1f}, "
        f"{np.mean(np.array(margins) >= SURE):.0%} of pairs sure"
    )

    fps = Fraction(video["fps"]).limit_denominator(1000)
    source = av.open(str(ROOT / video["path"]))
    sink = av.open(str(args.output), "w")
    stream = sink.add_stream("libx264", rate=fps)
    stream.width, stream.height = video["width"], video["height"]
    stream.pix_fmt = "yuv420p"
    stream.options = {"preset": "veryfast", "crf": "23"}
    count = 0
    for index, frame in enumerate(source.decode(video=0)):
        image = frame.to_ndarray(format="bgr24")
        for person in rows.get(index, {"players": []})["players"]:
            who, team, sure = people.get(person["chain"], (None, None, False))
            if team is None:
                continue
            x1, y1, x2, y2 = (int(v) for v in person["box"])
            if who is None:
                color, text = UNSURE, f"pair {team + 1}"
            else:
                color = COLORS[who]
                text = f"P{who + 1}" + ("" if sure else " ?")
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                image,
                text,
                (x1, max(18, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                color,
                2,
            )
        cv2.putText(
            image,
            "experimental: players grouped by looks, unreviewed",
            (video["width"] - 520, 24),
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
    print(f"{count} frames -> {args.output}")


if __name__ == "__main__":
    main()
