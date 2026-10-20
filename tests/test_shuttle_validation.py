"""Source identity and uncertainty must survive an immutable review packet."""

import copy
import json

import av
import numpy as np
import pytest
from badminton import shuttle_validation as audit
from badminton.ingest import inspect_video
from badminton.storage import Store
from media_fixtures import write_rotated_video
from PIL import Image


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    sources, inventory = [], {"schema_version": 1, "sources": []}
    for rotation in (0, 90):
        path = write_rotated_video(tmp_path / f"source-{rotation}.mp4", rotation)
        store = Store(tmp_path / "processed")
        meta = inspect_video(path, "singles", store, tmp_path)
        entries = {
            "video": path,
            "metadata": store.data / meta["id"] / "metadata.json",
            "timestamps": store.data / meta["id"] / "timestamps.json",
        }
        inventory["sources"].append(
            {
                "video_id": meta["id"],
                "frame_count": meta["frame_count"],
                "inputs": {k: audit.seal(tmp_path, p) for k, p in entries.items()},
            }
        )
        sources.append(
            {
                "id": meta["id"],
                "sha256": meta["sha256"],
                "frame_count": meta["frame_count"],
            }
        )
    raw = audit.encoded(inventory)
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_bytes(raw)
    protocol = copy.deepcopy(audit.PROTOCOL)
    protocol.update(
        sources=sources,
        inventory_sha256=audit.digest(raw),
        grid_points_per_source=2,
        extra_frames={sources[0]["id"]: [0]},
    )
    monkeypatch.setattr(audit, "PROTOCOL", protocol)
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_bytes(audit.encoded(protocol))
    return tmp_path, inventory_path, protocol_path, tmp_path / ".cache/packet"


def create(corpus):
    root, inventory, protocol, output = corpus
    return audit.make_packet(
        root, inventory, audit.PROTOCOL["inventory_sha256"], protocol, output
    )


def load(corpus):
    output = corpus[3]
    raw = (output / "packet.json").read_bytes()
    return audit.validate_packet(output, raw, audit.digest(raw))[0]


def reseal_inventory(corpus, change):
    root, path, protocol, _ = corpus
    document = audit.read_json(path.read_bytes())
    change(document, root)
    path.write_bytes(audit.encoded(document))
    audit.PROTOCOL["inventory_sha256"] = audit.file_hash(path)
    protocol.write_bytes(audit.encoded(audit.PROTOCOL))


def test_production_protocol_and_fixed_selection():
    from pathlib import Path

    spec = (
        Path(__file__).resolve().parents[1]
        / "data/manifests/shuttle_visibility_protocol_v1.json"
    )
    assert audit.read_json(spec.read_bytes()) == audit.PROTOCOL
    selections = [audit.selection(s) for s in audit.PROTOCOL["sources"]]
    assert [len(values) for values in selections] == [35, 25]
    assert audit.selection(audit.PROTOCOL["sources"][0]) == sorted(set(selections[0]))
    assert all(f in selections[0] for f in (2039, 2043, 2047, 2048, 2077, 2079))


def test_packet_preserves_real_vfr_pts_and_original_oriented_pixels(corpus):
    result = create(corpus)
    assert result["cases"] == 5 and result["images"] == 8
    packet = load(corpus)
    root = corpus[0]
    for rotation in (0, 90):
        with av.open(str(root / f"source-{rotation}.mp4")) as container:
            frames = list(container.decode(container.streams.video[0]))
        cases = [c for c in packet["cases"] if c["rotation"] == rotation]
        for case in cases:
            for item in case["context"]:
                original = frames[item["frame"]]
                assert item["time_s"] == float(original.pts * original.time_base)
                with Image.open(corpus[3] / item["image"]["path"]) as image:
                    expected = np.rot90(
                        original.to_ndarray(format="rgb24"), rotation // 90
                    )
                    assert np.array_equal(np.asarray(image), expected)
    original = audit.file_hash(corpus[3] / "packet.json")
    with pytest.raises(FileExistsError):
        create(corpus)
    assert audit.file_hash(corpus[3] / "packet.json") == original


@pytest.mark.parametrize("key", ["video", "metadata", "timestamps"])
def test_changed_original_bytes_prevent_any_packet(corpus, key):
    root, path, _, output = corpus
    entry = audit.read_json(path.read_bytes())["sources"][0]["inputs"][key]
    target = root / entry["path"]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Changed sealed input"):
        create(corpus)
    assert not output.exists()


def test_resealed_but_incorrect_clock_fails_native_decode_without_completion(corpus):
    def alter(document, root):
        item = document["sources"][0]["inputs"]["timestamps"]
        path = root / item["path"]
        times = audit.read_json(path.read_bytes())
        times[1] += 0.005
        path.write_bytes(audit.encoded(times))
        document["sources"][0]["inputs"]["timestamps"] = audit.seal(root, path)

    reseal_inventory(corpus, alter)
    with pytest.raises(ValueError, match="Native source frame clock"):
        create(corpus)
    assert (corpus[3] / "attempt.json").is_file()
    assert not (corpus[3] / "packet.json").exists()
    with pytest.raises(FileExistsError):
        create(corpus)


@pytest.mark.parametrize(
    "relative", ["../escape.mp4", "/absolute.mp4", "C:/source.mp4", "source\\video.mp4"]
)
def test_resealed_paths_cannot_escape_source_root(corpus, relative):
    reseal_inventory(
        corpus,
        lambda document, _root: document["sources"][0]["inputs"]["video"].update(
            path=relative
        ),
    )
    with pytest.raises(ValueError, match=r"relative POSIX|escapes"):
        create(corpus)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["cases"].reverse(),
        lambda p: p["cases"][0].update(frame=p["cases"][0]["frame"] + 1),
        lambda p: p["cases"][0]["context"][0].update(pts=99999),
        lambda p: p["cases"][0]["context"].pop(),
        lambda p: p["cases"][0].update(rotation=90),
        lambda p: p["cases"][0].update(predictions=[{"x": 1, "y": 2}]),
    ],
)
def test_resealed_packet_cannot_substitute_rows_context_pts_or_geometry(
    corpus, mutation
):
    create(corpus)
    packet = audit.read_json((corpus[3] / "packet.json").read_bytes())
    mutation(packet)
    raw = audit.encoded(packet)
    with pytest.raises(ValueError):
        audit.validate_packet(corpus[3], raw, audit.digest(raw))


def test_packet_image_and_original_clock_copies_are_sealed(corpus):
    create(corpus)
    packet = load(corpus)
    image_path = corpus[3] / packet["cases"][0]["context"][0]["image"]["path"]
    image_path.write_bytes(image_path.read_bytes() + b"altered")
    with pytest.raises(ValueError, match="Changed sealed input"):
        load(corpus)


def label(case, **changes):
    return {
        "id": case["id"],
        "state": "unknown",
        "x": None,
        "y": None,
        "uncertainty_px": None,
        "reason": "Tiny white features cannot be distinguished from shuttle on the source image",
        "difficulty": ["unresolved"],
        "context_cut": False,
        **changes,
    }


def test_unknown_unlocalizable_and_invisible_truth_remain_distinct(corpus):
    create(corpus)
    packet = load(corpus)
    for state in audit.PROTOCOL["states"]:
        value = label(packet["cases"][0], state=state)
        if state == "visible":
            value.update(x=12.0, y=21.0, uncertainty_px=3)
        audit.validate_label(value, packet["cases"][0])
    document = {
        "schema_version": 1,
        "packet_sha256": "frozen",
        "assessor_session": "actual-source-review-A",
        "method": "source-only original-size inspection",
        "cases": [label(c) for c in packet["cases"]],
    }
    audit.validate_assessment(document, packet, "frozen")
    document["cases"].reverse()
    with pytest.raises(ValueError, match="assessment label"):
        audit.validate_assessment(document, packet, "frozen")


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": "TODO"},
        {"x": 5},
        {"context_cut": None},
        {"state": "visible", "x": float("nan"), "y": 10, "uncertainty_px": 2},
        {"state": "visible", "x": 10, "y": 10, "uncertainty_px": 0},
        {"difficulty": []},
    ],
)
def test_assessments_reject_invented_nonfinite_or_unassessed_truth(corpus, changes):
    create(corpus)
    case = load(corpus)["cases"][0]
    with pytest.raises(ValueError):
        audit.validate_label(label(case, **changes), case)


def test_duplicate_and_nonfinite_json_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        audit.read_json(b'{"state":"unknown","state":"not_visible"}')
    with pytest.raises(ValueError, match="Nonfinite"):
        audit.read_json(b'{"x":NaN}')
    assert json.loads(audit.encoded({"unknown": None})) == {"unknown": None}
