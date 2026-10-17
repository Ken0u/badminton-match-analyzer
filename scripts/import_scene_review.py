"""Preview/apply source-verified scene review; preserve other annotations."""

import argparse
import json
from pathlib import Path

from badminton.config import DATA, ROOT
from badminton.schemas import Annotations
from badminton.storage import Store
from badminton.video import resolve_source


def prepare(store, entry, root=ROOT):
    video = store.video(entry["video_id"])
    if video["sha256"] != entry["sha256"]:
        raise ValueError("Scene review belongs to different source bytes")
    resolve_source(video, root)
    current = store.annotations(video["id"])
    doc = current.model_dump()
    existing = {item["id"]: item for item in doc["scene_ranges"]}
    for scene in entry["scene_ranges"]:
        if scene["id"] in existing and existing[scene["id"]] != scene:
            raise ValueError(
                "Scene ID conflicts with an existing reviewed range; resolve it explicitly"
            )
        existing[scene["id"]] = scene
    doc["scene_ranges"] = sorted(existing.values(), key=lambda r: r["start_frame"])
    result = Annotations.model_validate(doc)
    if any(r.end_frame > video["frame_count"] for r in result.scene_ranges):
        raise ValueError("Reviewed scene exceeds the source video")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    store = Store(args.data)
    manifest = json.loads((ROOT / "data/manifests/scene_review.json").read_text())
    prepared = [
        (entry["video_id"], prepare(store, entry)) for entry in manifest["videos"]
    ]
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
            "scene ranges",
            len(doc.scene_ranges),
        )


if __name__ == "__main__":
    main()
