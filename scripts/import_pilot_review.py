"""Merge the visually inspected development pilot without overwriting edits."""

import argparse
import json

from badminton.config import DATA, ROOT
from badminton.schemas import (
    Annotations,
    Event,
    ReviewWindow,
    ShuttlePoint,
    TrackAssignment,
)
from badminton.storage import Store
from badminton.video import resolve_source, timestamps_for


def merge_records(existing, incoming, key):
    result = list(existing)
    lookup = {key(item): item for item in existing}
    for item in incoming:
        identity = key(item)
        if identity in lookup:
            if lookup[identity] != item:
                raise ValueError(f"Pilot conflicts with a saved label: {identity}")
            continue
        result.append(item)
        lookup[identity] = item
    return result


def prepare(store, entry, accept_inferred_live=False):
    video_id = entry["video_id"]
    video = store.video(video_id)
    if video["sha256"] != entry["sha256"]:
        raise ValueError("Pilot labels belong to a different source video")
    resolve_source(video, ROOT)
    times = timestamps_for(store.data, video_id)
    doc = store.annotations(video_id)
    events = [Event.model_validate(e) for e in entry.get("events", [])]
    for event in events:
        event.time_s = times[event.frame]
    windows = [ReviewWindow.model_validate(w) for w in entry.get("review_windows", [])]
    assessment = entry.get("scene_assessment", {})
    if accept_inferred_live and assessment.get("likely_scene") == "live":
        for window in windows:
            window.scene = "live"
            window.notes += " Live status inferred from context: " + assessment["basis"]
    doc.events = merge_records(doc.events, events, lambda e: e.id)
    doc.review_windows = merge_records(doc.review_windows, windows, lambda w: w.id)
    doc.shuttle_points = merge_records(
        doc.shuttle_points,
        [ShuttlePoint.model_validate(p) for p in entry.get("shuttle_points", [])],
        lambda p: p.frame,
    )
    doc.track_assignments = merge_records(
        doc.track_assignments,
        [TrackAssignment.model_validate(a) for a in entry.get("track_assignments", [])],
        lambda a: (a.run_id, a.track_id, a.start_frame, a.end_frame),
    )
    return Annotations.model_validate(doc.model_dump())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Save append-only annotation revisions"
    )
    parser.add_argument(
        "--accept-inferred-live",
        action="store_true",
        help="Use the documented contextual live-play assessment where available",
    )
    args = parser.parse_args()
    manifest = json.loads(
        (ROOT / "data/manifests/pilot_review.json").read_text(encoding="utf-8")
    )
    store = Store(DATA)
    # Preflight every source and schema before writing any annotation revision.
    prepared = [
        (e["video_id"], prepare(store, e, args.accept_inferred_live))
        for e in manifest["videos"]
    ]
    for video_id, doc in prepared:
        current = store.annotations(video_id)
        if current == doc:
            print(f"{video_id}: pilot already present at revision {doc.revision}")
            continue
        if args.apply:
            doc = store.save_annotations(video_id, doc)
        print(
            f"{video_id}: {'saved' if args.apply else 'preview'} revision {doc.revision}, {len(doc.events)} contacts, {len(doc.shuttle_points)} shuttle labels, {len(doc.track_assignments)} identities"
        )


if __name__ == "__main__":
    main()
