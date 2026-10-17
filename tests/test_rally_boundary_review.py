"""Source-verified boundary imports must not invent exhaustive shot truth."""

import hashlib

import pytest
from badminton.schemas import Event
from badminton.storage import Store
from badminton.video import write_json

from scripts.import_rally_boundary_review import prepare


@pytest.fixture
def source(tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"boundary-import-contract")
    video = {
        "id": "boundary-video",
        "sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
        "path": media.name,
        "mode": "singles",
        "frame_count": 6,
    }
    store = Store(tmp_path / "processed")
    store.register(video)
    write_json(
        store.data / video["id"] / "timestamps.json", [0, 0.04, 0.12, 0.16, 0.24, 0.28]
    )
    doc = store.annotations(video["id"])
    doc.events = [
        Event(
            id="original",
            rally_id="R1",
            kind="shot",
            frame=2,
            family="unknown",
            side="unknown",
        )
    ]
    store.save_annotations(video["id"], doc)
    entry = {
        "video_id": video["id"],
        "sha256": video["sha256"],
        "inspected_view": {"start_frame": 0, "end_frame": 6},
        "events": [
            {
                "id": "opening",
                "rally_id": "R1",
                "kind": "serve",
                "frame": 1,
                "contact_start_frame": 0,
                "contact_end_frame": 1,
            },
            {
                "id": "terminal",
                "rally_id": "R1",
                "kind": "rally_end",
                "frame": 4,
                "terminal_start_frame": 3,
                "terminal_end_frame": 5,
            },
        ],
    }
    return tmp_path, store, video, entry


def test_boundary_import_preserves_labels_and_is_idempotent(source):
    root, store, video, entry = source
    before = store.annotations(video["id"])
    doc = prepare(store, entry, root)
    assert doc.events[0] == before.events[0]
    assert doc.events[1].time_s == 0.04 and doc.events[2].time_s == 0.24
    assert doc.review_windows == before.review_windows == []
    assert doc.scene_ranges == before.scene_ranges == []
    saved = store.save_annotations(video["id"], doc)
    assert prepare(store, entry, root) == saved
    assert store.annotations(video["id"], 1) == before
    assert saved.events[-1].terminal_start_frame == 3
    assert saved.events[-1].terminal_end_frame == 5
    with pytest.raises(ValueError, match="conflicts"):
        prepare(
            store,
            entry | {"events": [entry["events"][1] | {"notes": "different review"}]},
            root,
        )


def test_boundary_import_rejects_wrong_source_range_and_duplicate_ids(source):
    root, store, video, entry = source
    before = store.annotations(video["id"])
    with pytest.raises(ValueError, match="source bytes"):
        prepare(store, entry | {"sha256": "wrong"}, root)
    with pytest.raises(ValueError, match="exceeds"):
        prepare(
            store,
            entry | {"events": [entry["events"][1] | {"terminal_end_frame": 6}]},
            root,
        )
    with pytest.raises(ValueError, match="unique"):
        prepare(store, entry | {"events": [entry["events"][0]] * 2}, root)
    with pytest.raises(ValueError, match="inspected view"):
        prepare(
            store, entry | {"inspected_view": {"start_frame": 1, "end_frame": 6}}, root
        )
    assert store.annotations(video["id"]) == before
    (root / video["path"]).write_bytes(b"replaced source")
    with pytest.raises(ValueError, match="changed"):
        prepare(store, entry, root)
