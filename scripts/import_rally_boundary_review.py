"""Preview/apply source-verified boundary audit, keeping unresolved intervals."""

import argparse
import json
from pathlib import Path

from badminton.config import DATA, ROOT
from badminton.schemas import Annotations, Event, FrameRange
from badminton.storage import Store
from badminton.video import resolve_source, timestamps_for


def prepare(store, entry, root=ROOT):
    video = store.video(entry["video_id"])
    if video["sha256"] != entry["sha256"]:
        raise ValueError("Boundary review belongs to different source bytes")
    resolve_source(video, root)
    times = timestamps_for(store.data, video["id"])
    view = FrameRange.model_validate(entry["inspected_view"])
    if view.end_frame > len(times):
        raise ValueError("Inspected view exceeds the source video")
    doc = store.annotations(video["id"])
    incoming = [Event.model_validate(e) for e in entry["events"]]
    if len({e.id for e in incoming}) != len(incoming):
        raise ValueError("Boundary review event IDs must be unique")
    merged = {e.id: e for e in doc.events}
    for event in incoming:
        first = event.terminal_start_frame
        if first is None:
            first = event.contact_start_frame
        if first is None:
            first = event.frame
        last = event.terminal_end_frame or event.contact_end_frame or event.frame
        if max(last, event.frame) >= len(times):
            raise ValueError("Boundary review exceeds the source video")
        if first < view.start_frame or last >= view.end_frame:
            raise ValueError("Boundary review exceeds its inspected view")
        event.time_s = times[event.frame]
        if event.id in merged and merged[event.id] != event:
            raise ValueError("Boundary review conflicts with a saved event")
        merged[event.id] = event
    doc.events = list(merged.values())
    # This audit never certifies exhaustive contact coverage, changes existing
    # identities, or turns an unknown scene into a scored live window.
    return Annotations.model_validate(doc.model_dump())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    store = Store(args.data)
    manifest = json.loads(
        (ROOT / "data/manifests/rally_boundary_review.json").read_text(encoding="utf-8")
    )
    prepared = [(e["video_id"], prepare(store, e)) for e in manifest["videos"]]
    for video_id, doc in prepared:
        if doc == store.annotations(video_id):
            print(video_id, "already present", doc.revision)
            continue
        if args.apply:
            doc = store.save_annotations(video_id, doc)
        print(
            video_id,
            "saved" if args.apply else "preview",
            "revision",
            doc.revision,
            "events",
            len(doc.events),
        )


if __name__ == "__main__":
    main()
