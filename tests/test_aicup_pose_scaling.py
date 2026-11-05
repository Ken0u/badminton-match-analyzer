"""Generated controls for scaling; no private source inputs are opened."""

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
import zlib
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from badminton import aicup_pose_learning as learning
from badminton import aicup_pose_pilot as producer
from badminton import aicup_pose_scaling as scaling
from test_aicup_pose_learning import case


def generated_frame(format="yuv420p", colorspace=1, color_range=1):
    import av

    pixels = np.empty((64, 96, 3), np.uint8)
    y, x = np.indices((64, 96))
    pixels[..., 0] = (x * 7 + y * 3) % 256
    pixels[..., 1] = (x * 2 + y * 11) % 256
    pixels[..., 2] = (x * 13 + y * 5) % 256
    frame = av.VideoFrame.from_ndarray(pixels, "rgb24").reformat(format=format)
    frame.colorspace, frame.color_range = colorspace, color_range
    frame.pts, frame.time_base = 1001, Fraction(1, 30000)
    return frame


@pytest.mark.parametrize(
    "format", ["yuv420p", "yuv422p", "yuv444p", "rgb24", "bgr24", "bgr0", "rgb0"]
)
@pytest.mark.parametrize("colorspace,color_range", [(0, 0), (1, 1), (5, 2)])
def test_native_compressed_frames_preserve_pixels_color_and_source_clock(
    format, colorspace, color_range
):
    frame = generated_frame(format, colorspace, color_range)
    packed = scaling.pack_frame(frame)
    assert isinstance(packed["compressed_pixels"], bytes)
    restored = scaling.unpack_frame(packed)
    assert restored is not frame
    assert restored.format.name == frame.format.name
    assert (restored.width, restored.height) == (frame.width, frame.height)
    assert (restored.pts, restored.time_base) == (frame.pts, frame.time_base)
    assert (restored.colorspace, restored.color_range) == (
        frame.colorspace,
        frame.color_range,
    )
    for representation in (None, "rgb24", "bgr24"):
        if representation is None and "planes" in packed:
            # Plane padding can differ between allocations; native pixel bytes
            # in these packed RGB formats must remain exact as well as RGB/BGR.
            for before, after in zip(frame.planes, restored.planes, strict=True):
                a = np.frombuffer(bytes(before), np.uint8).reshape(
                    before.height, before.line_size
                )
                b = np.frombuffer(bytes(after), np.uint8).reshape(
                    after.height, after.line_size
                )
                np.testing.assert_array_equal(
                    a[:, : frame.width * 4], b[:, : frame.width * 4]
                )
            continue
        kwargs = {} if representation is None else {"format": representation}
        np.testing.assert_array_equal(
            frame.to_ndarray(**kwargs), restored.to_ndarray(**kwargs)
        )


@pytest.mark.parametrize("mutation", ["compressed", "format", "shape", "dtype"])
def test_compressed_frame_corruption_or_layout_changes_are_rejected(mutation):
    packed = scaling.pack_frame(generated_frame())
    if mutation == "compressed":
        packed["compressed_pixels"] = b"not a zlib stream"
    elif mutation == "format":
        packed["format"] = "unsupported-native-layout"
    elif mutation == "shape":
        packed["shape"] = [1, 1]
    else:
        packed["dtype"] = "float64"
    with pytest.raises((ValueError, zlib.error)):
        scaling.unpack_frame(packed)


def test_valid_compression_with_changed_native_pixels_is_rejected():
    packed = scaling.pack_frame(generated_frame())
    raw = bytearray(zlib.decompress(packed["compressed_pixels"]))
    raw[0] ^= 1
    packed["compressed_pixels"] = zlib.compress(raw, 1)
    with pytest.raises(ValueError, match="cache changed"):
        scaling.unpack_frame(packed)


def test_packing_refuses_roundtrip_that_changes_rendered_rgb_or_bgr(monkeypatch):
    frame = generated_frame()
    altered = generated_frame()
    replacement = altered.to_ndarray()
    replacement[:] = 0
    import av

    altered = av.VideoFrame.from_ndarray(replacement, format=altered.format.name)
    monkeypatch.setattr(scaling, "unpack_frame", lambda _: altered)
    with pytest.raises(ValueError, match="RGB and BGR"):
        scaling.pack_frame(frame)


@pytest.fixture
def fake_frame_codec(monkeypatch):
    monkeypatch.setattr(
        scaling,
        "pack_frame",
        lambda frame: {"compressed_pixels": b"generated", "fake_frame": frame},
    )
    monkeypatch.setattr(scaling, "unpack_frame", lambda record: record["fake_frame"])


def test_protocol_is_public_fixed_recipe_and_import_has_no_model_runtime():
    root = Path(scaling.__file__).resolve().parents[2]
    assert scaling.PROTOCOL == producer.read_json(
        root / "data/manifests/aicup_pose_scaling_protocol_v1.json"
    )
    env = dict(os.environ, PYTHONPATH=str(root / "backend"))
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from badminton import aicup_pose_scaling; import sys; "
            "assert 'torch' not in sys.modules; assert 'ultralytics' not in sys.modules",
        ],
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    "grant,commit,deadline",
    [
        (100, 99, 101),
        (0, 101, 102),
        (0, 50, 100),
        (0, 50, 50),
        (0, 50, 28851),
        (0, 20000, 43201),
        (float("nan"), 50, 101),
        (0, float("inf"), 101),
        (0, 50, float("nan")),
        (False, 50, 101),
    ],
)
def test_deadline_keeps_both_grant_and_original_commit_bounds(
    monkeypatch, grant, commit, deadline
):
    monkeypatch.setattr(scaling.time, "time", lambda: 100)
    with pytest.raises(ValueError):
        scaling.check_deadline(grant, commit, deadline)


def test_lease_renewal_does_not_change_original_scientific_clock(monkeypatch):
    monkeypatch.setattr(scaling.time, "time", lambda: 100)
    scaling.check_deadline(0, 50, 101)
    monkeypatch.setattr(scaling.time, "time", lambda: 101)
    with pytest.raises(ValueError):
        scaling.check_deadline(0, 50, 101)


def test_static_center_uses_both_ambiguous_endpoints_and_original_recipe():
    args = case()
    before = copy.deepcopy(args)
    actual = scaling.static_features(*args)
    original = learning.reference_features(*args)
    np.testing.assert_array_equal(actual["static"], original["static"])
    values = np.asarray(actual["static"])
    assert values.shape == (108,)
    assert values[0] == pytest.approx(0.65 / 50)
    assert values[1] == pytest.approx(-40 / 50)
    assert values[2] == pytest.approx(0.8)
    np.testing.assert_array_equal(values[:36], values[36:72])
    assert not values[72:].any()
    assert actual["center_mask"] == [[[True] * 6] * 2] * 2
    assert [clock["frame"] for clock in actual["native_clocks"]] == [6, 7]
    assert actual["observed_joint_slots"] == 24
    assert "temporal" not in actual
    assert args == before


def test_static_features_are_blind_to_outside_contact_motion_and_targets():
    args = case()
    original = scaling.static_features(*args)["static"]
    for index, frame in enumerate(args[2]["frames"]):
        if index not in (6, 7):
            frame["players"] = []
    args[0].update(family="drive", side="backhand", winner="B", landing=[999, 999])
    assert scaling.static_features(*args)["static"] == original


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_player",
        "duplicate_player",
        "invalid_box",
        "invalid_joint",
        "joint_outside_image",
        "low_joint_confidence",
        "camera_change",
        "expired_calibration",
    ],
)
def test_missing_or_bad_center_observations_keep_original_masks(mutation):
    args = case()
    frame = args[2]["frames"][7]
    person = frame["players"][0]
    if mutation == "missing_player":
        frame["players"] = frame["players"][1:]
    elif mutation == "duplicate_player":
        frame["players"].append(copy.deepcopy(person))
    elif mutation == "invalid_box":
        person["box"][3] = person["box"][1]
    elif mutation == "invalid_joint":
        person["keypoints"][5][0] = float("nan")
    elif mutation == "joint_outside_image":
        person["keypoints"][5][0] = args[3]["width"]
    elif mutation == "low_joint_confidence":
        person["keypoints"][5][2] = 0.249
    elif mutation == "camera_change":
        frame["camera_segment_start_frame"] = 7
    else:
        frame["calibration_valid"] = False
    actual = scaling.static_features(*args)
    expected = learning.reference_features(*args)
    np.testing.assert_array_equal(actual["static"], expected["static"])
    assert actual["static"][2] == pytest.approx(0.4)


@pytest.mark.parametrize("contact", [0, None])
def test_unavailable_and_censored_inputs_are_preserved(contact):
    args = case()
    args[0]["source_contact_frame"] = contact
    args[1]["weak_pair"] = None
    actual = scaling.static_features(*args)
    assert not actual["available"]
    assert actual["static"] == [0.0] * 108


def test_unavailable_pair_is_distinct_from_valid_pair_with_missing_pose():
    args = case()
    for frame in args[2]["frames"]:
        frame["players"] = []
    actual = scaling.static_features(*args)
    assert actual["available"]
    assert actual["static"] == [0.0] * 108


def test_static_invalid_contact_cannot_masquerade_as_available():
    args = case()
    args[0]["source_contact_frame"] = 0
    with pytest.raises(ValueError):
        scaling.static_features(*args)


@pytest.mark.parametrize(
    "kind,family,side,expected_family,expected_side",
    [
        ("shot", "clear", "forehand", 0, 0),
        ("shot", "unknown", "unknown", -1, -1),
        ("serve", None, "backhand", 7, 1),
        ("shot", "other", "backhand", 6, 1),
    ],
)
def test_feature_row_keeps_unknowns_and_labels_separate_from_geometry(
    kind, family, side, expected_family, expected_side
):
    ref, diagnostic, result, video, ledger = case()
    ref.update(kind=kind, family=family, side=side, clip_key="train:00001")
    clip = {"key": "train:00001", "fold": "train", "context": "synthetic-source"}
    row = scaling.feature_row(clip, ref, diagnostic, result, video, ledger)
    assert row["id"] == ref["id"]
    assert row["clip_key"] == clip["key"]
    assert row["fold"] == "train" and row["context"] == "synthetic-source"
    assert row["family"] == expected_family and row["side"] == expected_side
    assert row["training_ready"] is False
    assert row["scene_truth"] == row["actor_truth"] == "unknown"
    assert (
        row["static"]
        == learning.reference_features(ref, diagnostic, result, video, ledger)["static"]
    )
    assert "temporal" not in row


@pytest.fixture
def cohort_case(monkeypatch):
    clips, folds, contexts = [], {}, {}
    for partition, identity, fold, labelled in (
        ("train", "00001", "train", True),
        ("train", "00002", "train", True),
        ("train", "00003", "train", True),
        ("val", "00004", "validation", True),
        ("val", "00005", "validation", True),
        ("train", "00006", "test", True),
        ("train", "00007", "train", False),
    ):
        prefix = f"part1/{partition}/{identity}/{identity}"
        key = f"{partition}:{identity}"
        clip = {
            "source_partition": partition,
            "source_clip_id": identity,
            "media_path": prefix + ".mp4",
            "media_sha256": identity * 12 + "abcd",
            "media_bytes": 20,
        }
        if labelled:
            clip.update(label_path=prefix + "_S2.csv", label_sha256="unbound")
        clips.append(clip)
        folds[key], contexts[key] = fold, fold + "-source"
    old = {
        "clips": [
            {
                "key": key,
                "fold": folds[key],
                "context": contexts[key],
                "folder": f"clip-{i:02d}",
                "source_sha256": clips[index]["media_sha256"],
                "source_label_sha256": clips[index]["label_sha256"],
                "frames": 10,
            }
            for i, (key, index) in enumerate((("train:00001", 0), ("val:00004", 3)))
        ]
    }
    protocol = copy.deepcopy(scaling.PROTOCOL)
    protocol["expected"].update(
        train_clips=3,
        validation_clips=1,
        new_clips=2,
        reused_clips=2,
        train_rows=3,
        validation_rows=1,
        new_rows=2,
        reused_rows=2,
        new_frames=20,
        total_frames=40,
        new_media_bytes=40,
    )
    monkeypatch.setattr(scaling, "PROTOCOL", protocol)
    return clips, folds, contexts, old


def test_cohort_expands_only_labelled_training_and_reuses_exact_validation(cohort_case):
    before = copy.deepcopy(cohort_case)
    cohort = scaling.select_cohort(*cohort_case)
    assert cohort["clip_keys"] == [
        "train:00001",
        "train:00002",
        "train:00003",
        "val:00004",
    ]
    assert cohort["new_keys"] == ["train:00002", "train:00003"]
    assert cohort["reused_keys"] == ["train:00001", "val:00004"]
    assert cohort_case == before


@pytest.mark.parametrize(
    "mutation",
    ["old_validation_fold", "old_context", "missing_old", "duplicate", "budget"],
)
def test_cohort_refuses_changed_original_membership_and_budget(cohort_case, mutation):
    clips, folds, contexts, old = cohort_case
    if mutation == "old_validation_fold":
        folds["val:00004"] = "test"
    elif mutation == "old_context":
        old["clips"][1]["context"] = "different-original-match"
    elif mutation == "missing_old":
        clips.pop(3)
    elif mutation == "duplicate":
        clips.append(copy.deepcopy(clips[0]))
    else:
        clips[1]["media_bytes"] += 1
    with pytest.raises(ValueError):
        scaling.select_cohort(clips, folds, contexts, old)


def test_canonical_rows_fence_unselected_validation_test_and_unlabelled_before_open(
    tmp_path, monkeypatch, cohort_case
):
    clips, folds, contexts, old = cohort_case
    raw = b"ShotSeq,HitFrame,Hitter,Backhand,BallType,Winner\n1,0,A,1,1,X\n"
    archive = tmp_path / "generated.zip"
    with zipfile.ZipFile(archive, "w") as source:
        for clip in clips:
            if "label_path" in clip:
                clip["label_sha256"] = hashlib.sha256(raw).hexdigest()
                source.writestr(clip["label_path"], raw)
    for clip in old["clips"]:
        clip["source_label_sha256"] = hashlib.sha256(raw).hexdigest()
    cohort = scaling.select_cohort(clips, folds, contexts, old)
    original, opened = zipfile.ZipFile.open, []

    def guarded(self, name, *args, **kwargs):
        member = name.filename if isinstance(name, zipfile.ZipInfo) else name
        assert not any(identity in member for identity in ("00005", "00006", "00007"))
        opened.append(member)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", guarded)
    rows = scaling.canonical_reference_rows(archive, clips, folds, cohort)
    assert len(opened) == len(rows) == 4
    assert [r["clip_key"] for r in rows] == cohort["clip_keys"]
    assert all(r["source_contact_frame"] == 0 and r["side"] == "backhand" for r in rows)
    assert all(r["family"] is None for r in rows)
    clips[0]["label_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        scaling.canonical_reference_rows(archive, clips, folds, cohort)


@pytest.fixture
def combined_case(cohort_case):
    cohort = scaling.select_cohort(*cohort_case)
    old, new, refs = [], [], []
    for index, clip in enumerate(cohort["clips"]):
        ref, diagnostic, result, video, ledger = case()
        ref.update(id=f"generated:{index}", clip_key=clip["key"])
        diagnostic["reference_id"] = ref["id"]
        if index == 1:
            ref.update(family="unknown", side="unknown")
            diagnostic["weak_pair"] = None
        refs.append(ref)
        row = scaling.feature_row(clip, ref, diagnostic, result, video, ledger)
        if clip["key"] in cohort["reused_keys"]:
            row.update(
                learning.reference_features(ref, diagnostic, result, video, ledger)
            )
            old.append(row)
        else:
            new.append(row)
    cohort["reference_rows"] = refs
    return cohort, old, new


def test_combination_retains_original_rows_and_exact_source_order(combined_case):
    cohort, old, new = combined_case
    before = copy.deepcopy(combined_case)
    actual = scaling.combined_features(cohort, old, new)
    assert [row["id"] for row in actual] == [
        ref["id"] for ref in cohort["reference_rows"]
    ]
    assert actual[0] is old[0] and actual[-1] is old[-1]
    assert actual[1] is new[0] and actual[2] is new[1]
    assert actual[1]["family"] == actual[1]["side"] == -1
    assert actual[1]["available"] is False
    assert "temporal" in actual[0] and "temporal" not in actual[1]
    assert combined_case == before


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_old",
        "duplicate_new",
        "missing",
        "extra",
        "wrong_target",
        "wrong_fold",
        "new_validation",
        "eligibility",
        "actor_truth",
        "scene_truth",
        "nonfinite",
        "dimensions",
    ],
)
def test_combination_refuses_silent_denominator_or_truth_changes(
    combined_case, mutation
):
    cohort, old, new = combined_case
    if mutation == "duplicate_old":
        old.append(copy.deepcopy(old[0]))
    elif mutation == "duplicate_new":
        new.append(copy.deepcopy(new[0]))
    elif mutation == "missing":
        new.pop()
    elif mutation == "extra":
        extra = copy.deepcopy(new[0])
        extra["id"] = "unreferenced"
        new.append(extra)
    elif mutation == "wrong_target":
        old[0]["family"] = 5
    elif mutation == "wrong_fold":
        old[-1]["fold"] = "train"
    elif mutation == "new_validation":
        new[0]["clip_key"] = old[-1]["clip_key"]
    elif mutation == "eligibility":
        new[0]["training_ready"] = True
    elif mutation == "actor_truth":
        old[0]["actor_truth"] = "verified"
    elif mutation == "scene_truth":
        new[0]["scene_truth"] = "live"
    elif mutation == "nonfinite":
        new[0]["static"][0] = float("nan")
    else:
        new[0]["static"].pop()
    with pytest.raises(ValueError):
        scaling.combined_features(cohort, old, new)


@pytest.mark.parametrize("body_failure", [False, True])
def test_decode_cache_decodes_once_reuses_actual_objects_and_restores_aliases(
    tmp_path, monkeypatch, body_failure, fake_frame_codec
):
    from badminton import court_detection, tracking, video

    original_tracking, original_court = (
        tracking.iter_frames,
        court_detection.iter_frames,
    )
    source = {"id": "generated", "frame_count": 3, "width": 10, "height": 10}
    times, objects, visits = [0.0, 0.03, 0.09], [object(), object(), object()], []

    def decoded(requested, root, requested_times, start, end):
        assert requested is source and Path(root) == tmp_path
        assert requested_times is times and (start, end) == (0, 3)
        for index, frame in enumerate(objects):
            visits.append(index)
            yield index, times[index], frame

    monkeypatch.setattr(video, "iter_frames", decoded)
    source_checks = []
    monkeypatch.setattr(
        video, "resolve_source", lambda *args: source_checks.append(args)
    )
    progress = []
    try:
        with scaling.decode_cache(source, tmp_path, times, progress.append) as count:
            assert count == 3
            full = list(tracking.iter_frames(source, tmp_path, times, 0, 3))
            sample = list(court_detection.iter_frames(source, tmp_path, times, 1, 2))
            assert [row[2] for row in full] == objects
            assert sample[0][2] is objects[1]
            assert visits == [0, 1, 2]
            if body_failure:
                raise RuntimeError("generated consumer failure")
    except RuntimeError:
        assert body_failure
    assert tracking.iter_frames is original_tracking
    assert court_detection.iter_frames is original_court
    assert progress == [1, 2, 3]
    assert bool(source_checks) is not body_failure


@pytest.mark.parametrize("mutation", ["source", "root", "clock", "range", "bool"])
def test_cached_reader_refuses_another_source_or_unbounded_range(
    tmp_path, monkeypatch, mutation, fake_frame_codec
):
    from badminton import tracking, video

    source, times = (
        {"id": "generated", "frame_count": 2, "width": 10, "height": 10},
        [0.0, 0.03],
    )
    monkeypatch.setattr(
        video, "iter_frames", lambda *_: iter([(0, 0.0, object()), (1, 0.03, object())])
    )
    monkeypatch.setattr(video, "resolve_source", lambda *_: None)
    with scaling.decode_cache(source, tmp_path, times, lambda _: None):
        requested, root, clock, start, end = (
            copy.deepcopy(source),
            tmp_path,
            times,
            0,
            1,
        )
        if mutation == "source":
            requested["id"] = "another-source"
        elif mutation == "root":
            root = tmp_path / "another-root"
        elif mutation == "clock":
            clock = [0.0, 0.04]
        elif mutation == "range":
            end = 3
        else:
            start = False
        with pytest.raises(ValueError):
            list(tracking.iter_frames(requested, root, clock, start, end))


@pytest.mark.parametrize("gap", [False, True])
def test_single_pass_clock_and_camera_scan_match_existing_native_tools(tmp_path, gap):
    import av
    from badminton import segments

    media = tmp_path / "generated.mkv"
    with av.open(str(media), "w") as container:
        stream = container.add_stream("ffv1", rate=25)
        stream.width, stream.height, stream.pix_fmt = 96, 64, "bgr0"
        stream.time_base = stream.codec_context.time_base = Fraction(1, 1000)
        pts = 100
        for index in range(65):
            color = (
                [240, 0, 0]
                if index < 20
                else [0, 240, 0]
                if index < 40
                else [0, 0, 240]
            )
            frame = av.VideoFrame.from_ndarray(
                np.full((64, 96, 3), color, np.uint8), "rgb24"
            )
            frame.pts, frame.time_base = pts, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
            pts += 40 if index % 2 else 60
            if gap and index == 29:
                pts += 600
        for packet in stream.encode():
            container.mux(packet)
    progress = []
    ledger, times, video, scan = scaling.clock_and_scan(media, progress.append)
    old_ledger, old_times, old_video = producer.native_clock(media)
    assert ledger == old_ledger and times == old_times and video == old_video
    assert progress == list(range(65))
    assert times[0] == 0 and times[2] - times[1] != times[1] - times[0]
    video["path"] = media.name
    data = tmp_path / "data"
    (data / video["id"]).mkdir(parents=True)
    producer.publish(data / video["id"] / "timestamps.json", times)
    destination = tmp_path / "camera.json"
    segments.scan_video(video, tmp_path, data, lambda _: None, destination)
    existing = producer.read_json(destination)
    assert {k: v for k, v in scan.items() if k != "elapsed_s"} == {
        k: v for k, v in existing.items() if k != "elapsed_s"
    }
    assert scan["decoded_frames"] == 65
    if not gap:
        assert scan["cut_frames"] == [20, 40]
    else:
        assert any(
            b["frame"] == 30 and b["reason"] == "timestamp_discontinuity"
            for b in scan["boundaries"]
        )


def test_historical_inventory_uses_original_revision_and_refuses_changed_seals(
    tmp_path, monkeypatch
):
    root = tmp_path / "repository"
    folder = root / "backend/badminton"
    folder.mkdir(parents=True)
    source = folder / "generated.py"
    source.write_bytes(b"original = True\n")
    (root / ".gitattributes").write_bytes(b"* text eol=lf\n")
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "add", ".gitattributes", "backend/badminton/generated.py"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Generated Test",
            "-c",
            "user.email=generated@example.invalid",
            "commit",
            "-m",
            "Generated original source",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    seal = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(scaling, "__file__", str(folder / "aicup_pose_scaling.py"))
    scaling.git_seals(revision, {"generated.py": seal})
    source.write_bytes(b"later_unrelated_source = True\n")
    scaling.git_seals(revision, {"generated.py": seal})
    with pytest.raises(ValueError):
        scaling.git_seals(
            revision, {"generated.py": hashlib.sha256(source.read_bytes()).hexdigest()}
        )
    with pytest.raises(ValueError):
        scaling.git_seals(revision, {"../generated.py": seal})
    with pytest.raises(ValueError):
        scaling.git_seals("HEAD", {"generated.py": seal})


def test_decoder_memory_denial_happens_before_any_frame_or_adapter_change(
    tmp_path, monkeypatch
):
    import psutil
    from badminton import court_detection, tracking, video

    old_tracking, old_court = tracking.iter_frames, court_detection.iter_frames
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=0))
    monkeypatch.setattr(
        video, "iter_frames", lambda *_: pytest.fail("Decoded without RAM admission")
    )
    with pytest.raises(ValueError):
        with scaling.decode_cache(
            {"frame_count": 2, "width": 10, "height": 10},
            tmp_path,
            [0, 1],
            lambda _: None,
        ):
            pytest.fail("Entered cache without memory")
    assert (
        tracking.iter_frames is old_tracking
        and court_detection.iter_frames is old_court
    )


@pytest.mark.parametrize("failure_at", ["decode", "source_check"])
def test_decoder_and_final_source_errors_preserve_adapter_identity(
    tmp_path, monkeypatch, failure_at, fake_frame_codec
):
    from badminton import court_detection, tracking, video

    old_tracking, old_court = tracking.iter_frames, court_detection.iter_frames
    source = {"id": "generated", "frame_count": 2, "width": 10, "height": 10}

    def decoded(*_):
        yield 0, 0.0, object()
        if failure_at == "decode":
            raise ValueError("generated decode failure")
        yield 1, 0.03, object()

    def check_source(*_):
        raise ValueError("generated source mutation after consumer")

    monkeypatch.setattr(video, "iter_frames", decoded)
    monkeypatch.setattr(video, "resolve_source", check_source)
    with pytest.raises(ValueError):
        with scaling.decode_cache(source, tmp_path, [0.0, 0.03], lambda _: None):
            assert failure_at != "decode"
    assert (
        tracking.iter_frames is old_tracking
        and court_detection.iter_frames is old_court
    )


def test_cumulative_output_budget_counts_freeze_run_and_exclusive_claim_once(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    cache = workspace / ".cache"
    prospective, output = cache / "freeze", cache / "run"
    prospective.mkdir(parents=True)
    output.mkdir()
    plan = {"workspace": str(workspace), "prospective_directory": str(prospective)}
    (prospective / "prospective.json").write_bytes(b"1234")
    (output / "result.json").write_bytes(b"12345")
    claim = scaling.execution_claim(plan)
    claim.write_bytes(b"123")
    protocol = copy.deepcopy(scaling.PROTOCOL)
    protocol["limits"].update(
        output_bytes=13, decoded_frame_visits=4, model_frame_observations=2
    )
    monkeypatch.setattr(scaling, "PROTOCOL", protocol)
    scaling.budget(plan, output, reserve=1, decoded=4, observed=2)
    for kwargs in (
        {"reserve": 2},
        {"decoded": 5},
        {"observed": 3},
        {"reserve": -1},
        {"decoded": True},
    ):
        with pytest.raises(ValueError):
            scaling.budget(plan, output, **kwargs)
    assert claim.read_bytes() == b"123"
    # A new output/freeze cannot change the cohort-bound consumed claim name.
    assert (
        scaling.execution_claim(
            {**plan, "prospective_directory": str(cache / "elsewhere")}
        )
        == claim
    )


@pytest.mark.parametrize(
    "mutation", ["missing_pts", "reverse", "rotation", "rounding", "close_mutation"]
)
def test_clock_scanner_refuses_invalid_native_identity_even_after_decoder_close(
    tmp_path, monkeypatch, mutation
):
    from badminton import av_runtime, orientation, segments

    media = tmp_path / "generated.mp4"
    media.write_bytes(b"generated source")
    frames = [
        SimpleNamespace(pts=p, time_base=Fraction(1, 1000), duration=40, rotation=0)
        for p in (100, 140, 200)
    ]
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000),
        start_time=100,
        average_rate=Fraction(25),
        width=96,
        height=64,
        codec_context=SimpleNamespace(name="generated"),
    )
    if mutation == "missing_pts":
        frames[1].pts = None
    elif mutation == "reverse":
        frames[1].pts = 100
    elif mutation == "rotation":
        frames[1].rotation = 90
    elif mutation == "rounding":
        stream.time_base, stream.start_time = Fraction(1, 10**10), 0
        for i, frame in enumerate(frames):
            frame.pts, frame.time_base = i, stream.time_base

    @contextmanager
    def opened(_):
        yield SimpleNamespace(
            streams=SimpleNamespace(video=[stream]), decode=lambda _: iter(frames)
        )
        if mutation == "close_mutation":
            media.write_bytes(b"changed while closing")

    class Detector:
        gap_threshold = 0.1

        def __init__(self, *_):
            pass

        def process(self, *_):
            return {}

    monkeypatch.setattr(av_runtime, "open_media", opened)
    monkeypatch.setattr(orientation, "frame_rotation", lambda f: f.rotation)
    monkeypatch.setattr(orientation, "orient_frame", lambda f, **_: f)
    monkeypatch.setattr(segments, "BoundaryDetector", Detector)
    with pytest.raises(ValueError):
        scaling.clock_and_scan(media, lambda _: None)


@pytest.mark.parametrize(
    "protected",
    [
        "prepared",
        "native",
        "audit",
        "control",
        "actor_prospective",
        "control_prospective",
        "clock_ledger",
        "prospective_directory",
    ],
)
def test_new_output_cannot_overwrite_or_enclose_original_evidence(tmp_path, protected):
    workspace = tmp_path / "workspace"
    cache = workspace / ".cache"
    cache.mkdir(parents=True)
    plan = {"workspace": str(workspace)}
    for key in ("prepared", "native", "audit", "control", "prospective_directory"):
        plan[key] = str(cache / key)
    for key in ("actor_prospective", "control_prospective", "clock_ledger"):
        plan[key] = str(cache / key / "prospective.json")
    base = Path(plan[protected])
    if protected in ("actor_prospective", "control_prospective", "clock_ledger"):
        base = base.parent
    for output in (base, base / "child", cache):
        with pytest.raises(ValueError):
            scaling.private_output(plan, output)
    assert scaling.private_output(plan, cache / "new-run") == cache / "new-run"


@pytest.fixture
def run_case(tmp_path, monkeypatch):
    import torch
    from badminton.storage import Store

    workspace = tmp_path / "workspace"
    data, weights = workspace / "data/processed", workspace / "models/weights"
    store = Store(data)
    cache = workspace / ".cache"
    cache.mkdir()
    plan = {
        "workspace": str(workspace),
        "granted_at": time.time() - 10,
        "committed_at": time.time() - 5,
        "deadline": time.time() + 120,
        "prospective_directory": str(cache / "freeze"),
    }
    for key in ("prepared", "native", "audit", "control"):
        plan[key] = str(cache / key)
    for key in ("actor_prospective", "control_prospective"):
        plan[key] = str(cache / key / "prospective.json")
    plan["output"] = str(cache / "run")
    Path(plan["native"]).mkdir()
    Path(plan["actor_prospective"]).parent.mkdir()
    producer.publish(
        Path(plan["native"]) / "completion.json", {"shared_data": str(data)}
    )
    producer.publish(Path(plan["actor_prospective"]), {"workspace": str(workspace)})
    producer.publish(
        scaling.execution_claim(plan),
        {
            "prospective_sha256": "generated-hash",
            "output": plan["output"],
            "committed_at": plan["committed_at"],
            "deadline": plan["deadline"],
        },
    )
    monkeypatch.setattr(scaling, "prospective", lambda *_: plan)
    monkeypatch.setattr(
        producer, "configure_workspace", lambda _: (workspace, data, weights)
    )
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    return plan, store


def test_occupied_shared_store_prevents_all_scientific_callbacks_and_preserves_claim(
    run_case, monkeypatch
):
    from badminton.storage import ConflictError

    plan, store = run_case
    store.claim_job({"id": "existing-owner", "kind": "players", "status": "running"})
    monkeypatch.setattr(
        scaling,
        "original_inputs",
        lambda *_: pytest.fail("Source observation before admission"),
    )
    monkeypatch.setattr(
        scaling, "new_clip", lambda *_: pytest.fail("Inference before admission")
    )
    monkeypatch.setattr(learning, "fit", lambda *_: pytest.fail("Fit before admission"))
    output = Path(plan["workspace"]) / ".cache/run"
    with pytest.raises(ConflictError):
        scaling.run("generated-prospective", "generated-hash", output)
    failure = producer.read_json(output / "failure.json")
    assert failure["real_fits"] == failure["decoded"] == failure["observed"] == 0
    assert failure["reserved_original_run_consumed"]
    assert store.job("existing-owner")["status"] == "running"
    claim = scaling.execution_claim(plan)
    original_claim = claim.read_bytes()
    with pytest.raises(ValueError, match="output"):
        scaling.run(
            "generated-prospective",
            "another-freeze",
            output.with_name("another-output"),
        )
    assert claim.read_bytes() == original_claim


def test_original_input_failure_is_durable_and_cannot_restart_science(
    run_case, monkeypatch
):
    plan, store = run_case

    def inputs(_):
        process = producer.read_json(
            Path(plan["workspace"]) / ".cache/run/process.json"
        )
        assert store.job(process["job_id"])["status"] == "running"
        raise ValueError("generated changed original seal")

    monkeypatch.setattr(scaling, "original_inputs", inputs)
    monkeypatch.setattr(
        learning, "fit", lambda *_: pytest.fail("Fit after input failure")
    )
    output = Path(plan["workspace"]) / ".cache/run"
    with pytest.raises(ValueError, match="changed original seal"):
        scaling.run("generated-prospective", "generated-hash", output)
    process = producer.read_json(output / "process.json")
    assert store.job(process["job_id"])["status"] == "failed"
    assert producer.read_json(output / "failure.json")["real_fits"] == 0
    assert not (output / "completion.json").exists()


def test_cpu_only_host_refuses_before_claim_or_store_dispatch(run_case, monkeypatch):
    import torch

    plan, _ = run_case
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(
        scaling,
        "original_inputs",
        lambda *_: pytest.fail("Input processing without CUDA"),
    )
    output = Path(plan["workspace"]) / ".cache/run"
    with pytest.raises(ValueError, match="CUDA"):
        scaling.run("generated-prospective", "generated-hash", output)
    assert not output.exists() and scaling.execution_claim(plan).is_file()


def test_isolated_workspace_refused_before_any_store_or_scientific_admission(
    run_case, monkeypatch
):
    plan, _ = run_case
    original = Path(plan["native"]) / "completion.json"
    original.write_bytes(
        producer.encoded(
            {"shared_data": str(Path(plan["workspace"]) / "another-store")}
        )
    )
    monkeypatch.setattr(
        producer,
        "configure_workspace",
        lambda *_: pytest.fail("Isolated Store admitted"),
    )
    monkeypatch.setattr(
        scaling,
        "original_inputs",
        lambda *_: pytest.fail("Original source opened before root rejection"),
    )
    with pytest.raises(ValueError, match="real shared Store"):
        scaling.run("generated-prospective", "generated-hash", plan["output"])
    assert not Path(plan["output"]).exists()


@pytest.fixture
def metadata_operation(run_case, cohort_case, combined_case, monkeypatch):
    plan, store = run_case
    _, old_rows, _ = combined_case
    clips, folds, contexts, old_freeze = cohort_case
    keys = {row["clip_key"] for row in old_rows}
    clips = [clip for clip in clips if producer.clip_key(clip) in keys]
    protocol = copy.deepcopy(scaling.PROTOCOL)
    protocol["expected"].update(
        train_clips=1,
        validation_clips=1,
        new_clips=0,
        reused_clips=2,
        train_rows=1,
        validation_rows=1,
        new_rows=0,
        reused_rows=2,
        new_frames=0,
        new_media_bytes=0,
        total_frames=20,
    )
    monkeypatch.setattr(scaling, "PROTOCOL", protocol)
    cohort = scaling.select_cohort(clips, folds, contexts, old_freeze)
    refs = [
        ref for ref in combined_case[0]["reference_rows"] if ref["clip_key"] in keys
    ]
    plan.update(
        cohort=cohort,
        clock_ledger=str(
            Path(plan["workspace"]) / ".cache/original-ledger/clocks.jsonl"
        ),
    )
    prepared = Path(plan["prepared"])
    prepared.mkdir()
    producer.publish(prepared / "freeze.json", old_freeze)
    directory = Path(plan["workspace"]) / ".cache/generated-metadata"
    directory.mkdir()
    paths = {
        name: directory / (name + ".json") for name in ("clips", "groups", "archive")
    }
    producer.publish(paths["clips"], clips)
    producer.publish(
        paths["groups"],
        {
            "source_groups": [
                {"id": contexts[key], "fold": folds[key], "members": [key]}
                for key in [producer.clip_key(c) for c in clips]
            ]
        },
    )
    monkeypatch.setattr(scaling, "original_inputs", lambda *_: ([], [], old_rows))
    monkeypatch.setattr(scaling, "input_sources", lambda *_: paths)
    monkeypatch.setattr(scaling, "canonical_reference_rows", lambda *_: refs)
    monkeypatch.setattr(scaling, "clock_index", lambda *_: {})
    monkeypatch.setattr(
        scaling,
        "new_clip",
        lambda *_: pytest.fail("Metadata fixture started video processing"),
    )
    data = learning.arrays(old_rows, "static")
    predictions = [data[name].copy() for name in ("family", "side")]
    result = {
        "parameter_count": 9386,
        "selection": {"epoch": 5, "key": [1.0, 1.0]},
        "train": learning.evaluate(data, predictions, data["train"]),
        "validation": learning.evaluate(data, predictions, data["validation"]),
    }
    control = Path(plan["control"]) / "static"
    control.mkdir(parents=True)
    producer.publish(control / "result.json", result)
    producer.publish(control / "predictions.json", [p.tolist() for p in predictions])
    return plan, store, result, predictions


def test_one_fit_failure_keeps_partial_artifacts_and_forbids_retry(
    metadata_operation, monkeypatch
):
    plan, store, _, _ = metadata_operation
    fits = []

    def fit(data, output, progress):
        fits.append(output)
        output.mkdir()
        (output / "partial-model.pt").write_bytes(b"generated partial weights")
        raise ValueError("generated fit failure")

    monkeypatch.setattr(learning, "fit", fit)
    output = Path(plan["output"])
    with pytest.raises(ValueError, match="fit failure"):
        scaling.run("generated-prospective", "generated-hash", output)
    assert len(fits) == 1
    assert producer.read_json(output / "fit-start.json")["real_fits"] == 1
    assert producer.read_json(output / "failure.json")["real_fits"] == 1
    assert (
        output / "candidate/partial-model.pt"
    ).read_bytes() == b"generated partial weights"
    process = producer.read_json(output / "process.json")
    assert store.job(process["job_id"])["status"] == "failed"
    with pytest.raises(FileExistsError):
        scaling.run("generated-prospective", "generated-hash", output)
    assert len(fits) == 1


def test_completed_metadata_verification_never_decodes_or_refits(
    metadata_operation, monkeypatch
):
    plan, store, result, predictions = metadata_operation
    fits, verifications = [], []

    def fit(data, output, progress):
        fits.append(output)
        output.mkdir()
        producer.publish(output / "predictions.json", [p.tolist() for p in predictions])
        return result

    monkeypatch.setattr(learning, "fit", fit)
    output = Path(plan["output"])
    summary = scaling.run("generated-prospective", "generated-hash", output)
    assert summary["real_fits"] == len(fits) == 1
    process = producer.read_json(output / "process.json")
    assert store.job(process["job_id"])["status"] == "completed"
    monkeypatch.setattr(
        learning, "fit", lambda *_: pytest.fail("Verifier refitted model")
    )
    monkeypatch.setattr(
        scaling, "clock_and_scan", lambda *_: pytest.fail("Verifier decoded media")
    )
    monkeypatch.setattr(
        scaling, "decode_cache", lambda *_: pytest.fail("Verifier repeated inference")
    )

    def verify_arm(data, directory):
        verifications.append(directory)
        return result, predictions

    monkeypatch.setattr(learning, "verify_arm", verify_arm)
    verified = scaling.verify("generated-prospective", "generated-hash", output)
    assert verified["verified_references"] == 2
    assert verified["real_fits"] == 1 and verified["new_native_frames"] == 0
    assert verified["independent_accuracy_established"] is False
    assert verifications == [output / "candidate", Path(plan["control"]) / "static"]


@pytest.mark.parametrize("mutation", [None, "shape", "count", "cpu"])
def test_new_clip_has_two_real_generated_decodes_and_preserves_missing_inputs(
    tmp_path, monkeypatch, mutation
):
    import av
    from badminton import av_runtime, court_detection, tracking
    from badminton import video as video_tools

    media = tmp_path / "generated.mkv"
    with av.open(str(media), "w") as container:
        stream = container.add_stream("ffv1", rate=25)
        stream.width, stream.height, stream.pix_fmt = 96, 64, "bgr0"
        stream.time_base = stream.codec_context.time_base = Fraction(1, 1000)
        for pts in (100, 140, 200):
            frame = av.VideoFrame.from_ndarray(np.zeros((64, 96, 3), np.uint8), "rgb24")
            frame.pts, frame.time_base = pts, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    raw = media.read_bytes()
    archive = tmp_path / "generated.zip"
    member = "part1/train/00001/00001.mp4"
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr(member, raw)
    original_open, visits, tracker_calls = av_runtime.open_media, [], []

    @contextmanager
    def counted(path):
        with original_open(path) as container:
            pass_number = len(visits)
            visits.append([])

            class Proxy:
                streams = container.streams

                def seek(self, *args, **kwargs):
                    return container.seek(*args, **kwargs)

                def decode(self, stream):
                    for frame in container.decode(stream):
                        visits[pass_number].append(frame.pts)
                        yield frame

            yield Proxy()

    def observe(
        video, root, data, annotations, start, end, stride, progress, output, **kwargs
    ):
        tracker_calls.append(video)
        assert (start, end, stride) == (0, 3, 1)
        assert kwargs["player_model"] == "small" and kwargs["auto_calibrate"] is True
        times = producer.read_json(data / video["id"] / "timestamps.json")
        rows = list(tracking.iter_frames(video, root, times, 0, 3))
        samples = list(court_detection.iter_frames(video, root, times, 1, 2))
        assert samples[0][2] is rows[1][2]
        scan = kwargs["camera_scan"]
        producer.publish(
            output,
            {
                "stage": "players",
                "video_id": video["id"],
                "video_sha256": video["sha256"],
                "checkpoint_sha256": producer.PROTOCOL["sources"]["model"],
                "model_variant": "small",
                "image_size": 1280,
                "tracking_recipe": tracking.TRACKING_RECIPE,
                "stride": 1,
                "auto_calibrate": True,
                "start_frame": 0,
                "end_frame": 3,
                "processed_frames": 3,
                "cut_frames": scan["cut_frames"],
                "camera_ranges": scan["camera_ranges"],
                "automatic_calibrations": [],
                "court_context_version": 1,
                "device": "cpu" if mutation == "cpu" else "cuda:0",
                "frames": [
                    {
                        "frame": index,
                        "time_s": timestamp,
                        "players": [],
                        "motion_players": [],
                        "camera_segment_start_frame": 0,
                        "calibration_valid": False,
                    }
                    for index, timestamp, _ in rows
                ],
            },
        )

    monkeypatch.setattr(av_runtime, "open_media", counted)
    monkeypatch.setattr(video_tools, "open_media", counted)
    monkeypatch.setattr(tracking, "track_players", observe)
    clip = {
        "key": "train:00001",
        "fold": "train",
        "context": "generated-source",
        "media_path": member,
        "media_sha256": hashlib.sha256(raw).hexdigest(),
        "media_bytes": len(raw),
    }
    reference = {
        "id": "generated:1",
        "clip_key": clip["key"],
        "source_contact_frame": 0,
        "kind": "shot",
        "family": "unknown",
        "side": "unknown",
        "raw": {},
    }
    expected = {
        "decoded_frames": 4 if mutation == "count" else 3,
        "media_sha256": clip["media_sha256"],
        "shape": [97, 64] if mutation == "shape" else [96, 64],
        "first_pts": 0,
        "last_pts": 0.1,
    }
    output, checks = tmp_path / "run", []
    args = (
        {"sources": {"archive": {"path": str(archive)}}},
        clip,
        [reference],
        expected,
        output,
        lambda **kwargs: checks.append(kwargs),
        lambda _: None,
    )
    if mutation:
        with pytest.raises(ValueError):
            scaling.new_clip(*args)
        assert len(visits) == (2 if mutation == "cpu" else 1)
        assert not (output / "receipt.json").exists()
        return
    features, receipt = scaling.new_clip(*args)
    assert visits == [[100, 140, 200], [100, 140, 200]]
    assert len(tracker_calls) == 1
    assert (
        receipt["decoded_frame_visits"] == 6
        and receipt["model_frame_observations"] == 3
    )
    assert receipt["frames"] == 3 and receipt["references"] == 1
    assert features[0]["family"] == features[0]["side"] == -1
    assert not features[0]["available"] and features[0]["static"] == [0.0] * 108
    assert features[0]["training_ready"] is False
    assert max(item.get("decoded", 0) for item in checks) == 6


def test_integrity_freeze_publishes_fresh_claim_without_any_science(
    metadata_operation, monkeypatch
):
    plan, _, _, _ = metadata_operation
    claim = scaling.execution_claim(plan)
    claim.unlink()
    paths = scaling.input_sources(plan)
    producer.publish(paths["archive"], {"generated_archive_placeholder": True})
    old_freeze = producer.read_json(Path(plan["prepared"]) / "freeze.json")
    observations = [(clip, {}, {}, []) for clip in old_freeze["clips"]]
    monkeypatch.setattr(scaling, "original_inputs", lambda *_: (observations, [], []))
    monkeypatch.setattr(scaling, "code_seals", lambda: {"generated": "source-hash"})
    monkeypatch.setattr(scaling, "tested_commit", lambda: "a" * 40)
    monkeypatch.setattr(producer, "runtime", lambda: {"generated": "runtime"})
    monkeypatch.setattr(
        scaling, "clock_and_scan", lambda *_: pytest.fail("Decoded during freeze")
    )
    monkeypatch.setattr(
        scaling, "new_clip", lambda *_: pytest.fail("Inference during freeze")
    )
    monkeypatch.setattr(learning, "fit", lambda *_: pytest.fail("Fit during freeze"))
    protocol = Path(plan["workspace"]) / ".cache/protocol.json"
    producer.publish(protocol, scaling.PROTOCOL)
    args = {
        key: plan[key]
        for key in (
            "workspace",
            "prepared",
            "native",
            "actor_prospective",
            "audit",
            "control",
            "control_prospective",
            "clock_ledger",
            "granted_at",
            "committed_at",
            "deadline",
        )
    }
    output, run_output = Path(plan["prospective_directory"]), Path(plan["output"])
    result = scaling.freeze(
        **args, protocol=protocol, output=output, run_output=run_output
    )
    assert result["new_decodes"] == result["real_fits"] == 0
    frozen = producer.read_json(output / "prospective.json")
    assert frozen["output"] == str(run_output) and not run_output.exists()
    assert producer.read_json(claim) == {
        "prospective_sha256": result["prospective_sha256"],
        "output": str(run_output),
        "committed_at": plan["committed_at"],
        "deadline": plan["deadline"],
    }
    original_claim = claim.read_bytes()
    with pytest.raises(FileExistsError):
        scaling.freeze(
            **args,
            protocol=protocol,
            output=output.with_name("another-freeze"),
            run_output=run_output.with_name("another-run"),
        )
    assert claim.read_bytes() == original_claim


@pytest.mark.parametrize(
    "available,raises", [(True, False), (True, True), (False, False)]
)
def test_required_cuda_refuses_fallback_and_restores_runtime_probe(
    monkeypatch, available, raises
):
    import torch

    def probe():
        return available

    monkeypatch.setattr(torch.cuda, "is_available", probe)
    try:
        with scaling.required_cuda():
            if not available:
                with pytest.raises(ValueError, match="CPU fallback"):
                    torch.cuda.is_available()
            else:
                assert torch.cuda.is_available() is True
                if raises:
                    raise RuntimeError("generated tracker failure")
    except RuntimeError:
        assert raises
    assert torch.cuda.is_available is probe


@pytest.mark.parametrize("mutation", ["protocol", "overlap", "deadline", "input"])
def test_freeze_rejects_bad_scope_before_claim_or_science(
    metadata_operation, monkeypatch, mutation
):
    plan, _, _, _ = metadata_operation
    claim = scaling.execution_claim(plan)
    claim.unlink()
    monkeypatch.setattr(scaling, "code_seals", lambda: {"generated": "source"})
    monkeypatch.setattr(scaling, "tested_commit", lambda: "a" * 40)
    monkeypatch.setattr(producer, "runtime", lambda: {"generated": "runtime"})
    monkeypatch.setattr(
        scaling, "new_clip", lambda *_: pytest.fail("Science in failed freeze")
    )
    monkeypatch.setattr(learning, "fit", lambda *_: pytest.fail("Fit in failed freeze"))
    args = {
        key: plan[key]
        for key in (
            "workspace",
            "prepared",
            "native",
            "actor_prospective",
            "audit",
            "control",
            "control_prospective",
            "clock_ledger",
            "granted_at",
            "committed_at",
            "deadline",
        )
    }
    protocol = Path(plan["workspace"]) / ".cache/generated-protocol.json"
    fixed = copy.deepcopy(scaling.PROTOCOL)
    if mutation == "protocol":
        fixed["limits"]["real_fits"] = 2
    elif mutation == "deadline":
        args["deadline"] = args["committed_at"] + 28801
    producer.publish(protocol, fixed)
    output, run_output = Path(plan["prospective_directory"]), Path(plan["output"])
    if mutation == "overlap":
        run_output = output / "nested"
    elif mutation == "input":

        def reject(_):
            raise ValueError("generated original seal changed")

        monkeypatch.setattr(scaling, "original_inputs", reject)
    with pytest.raises(ValueError):
        scaling.freeze(**args, protocol=protocol, output=output, run_output=run_output)
    assert not claim.exists() and not output.exists() and not run_output.exists()


@pytest.fixture
def arithmetic_case(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    root = tmp_path / "arithmetic"
    output, original, prepared, native, audit = [
        root / name for name in ("run", "control", "prepared", "native", "audit")
    ]
    for directory in (output, original, prepared, native, audit):
        directory.mkdir(parents=True)
    ref, diagnostic, result, video, ledger = case()
    old_rows, rows, refs = [], [], []
    original_clips = []
    raw_diagnostics = []
    for index, fold in enumerate(("train", "validation")):
        clip = {
            "key": f"{fold}:00001",
            "fold": fold,
            "context": fold,
            "folder": f"clip-{index:02d}",
        }
        original_clips.append(clip)
        folder = prepared / clip["folder"]
        folder.mkdir()
        (native / clip["folder"]).mkdir()
        producer.publish(folder / "video.json", video)
        producer.publish(native / clip["folder"] / "players.json", result)
        for target in range(4):
            reference = {
                **ref,
                "id": f"{fold}:{target}",
                "clip_key": clip["key"],
                "family": "clear" if target % 2 == 0 else "lift",
                "side": "forehand" if target % 2 == 0 else "backhand",
            }
            d = {**diagnostic, "reference_id": reference["id"]}
            raw_diagnostics.append(d)
            row = scaling.target_fields(clip, reference) | learning.reference_features(
                reference, d, result, video, ledger
            )
            if target == 3:
                row.update(available=False)
                row["static"] = [0.0] * 108
                d["weak_pair"] = None
            old_rows.append(row)
            refs.append(reference)
    rows = copy.deepcopy(old_rows)
    protocol = copy.deepcopy(learning.PROTOCOL)
    protocol["training"].update(epochs=5, selection_every=5)
    monkeypatch.setattr(learning, "PROTOCOL", protocol)
    data = learning.arrays(rows, "static")
    learning.fit(data, original / "static", lambda *_: None)
    learning.fit(data, output / "candidate", lambda *_: None)
    producer.publish(original / "features.json", old_rows)
    producer.publish(output / "features.json", rows)
    producer.publish(
        output / "cohort.json",
        {
            "reference_rows": refs,
            "new_keys": [],
            "reused_keys": [c["key"] for c in original_clips],
        },
    )
    producer.publish(prepared / "freeze.json", {"clips": original_clips})
    producer.publish(audit / "diagnostics.json", raw_diagnostics)
    scaling_protocol = copy.deepcopy(scaling.PROTOCOL)
    scaling_protocol["expected"].update(
        train_rows=4,
        validation_rows=4,
        reused_rows=8,
        new_clips=0,
        reused_clips=2,
        new_frames=0,
    )
    scaling_protocol["original"].update(
        control_features=producer.digest(original / "features.json"),
        control_model=producer.digest(original / "static/model.pt"),
        control_statistics=producer.digest(original / "static/statistics.json"),
    )
    prospective = root / "prospective.json"
    producer.publish(
        prospective,
        {
            "output": str(output.resolve()),
            "control": str(original),
            "prepared": str(prepared),
            "native": str(native),
            "audit": str(audit),
            "protocol": scaling_protocol,
        },
    )
    producer.publish(
        output / "completion.json",
        {"prospective_sha256": producer.digest(prospective), "receipts": []},
    )
    return prospective, output


def test_independent_arithmetic_cli_reproduces_generated_fit_without_producer_import(
    arithmetic_case,
):
    prospective, output = arithmetic_case
    script = (
        Path(scaling.__file__).resolve().parents[2]
        / "scripts/scale_aicup_pose_learning.py"
    )
    receipt = output.parent / "arithmetic.json"
    command = [
        sys.executable,
        str(script),
        "arithmetic",
        "--prospective",
        str(prospective),
        "--prospective-sha256",
        producer.digest(prospective),
        "--output",
        str(output),
        "--receipt",
        str(receipt),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    checked = json.loads(result.stdout)
    assert checked["verified_rows"] == 8 and checked["reused_rows"] == 8
    assert checked["raw_pose_samples"] >= 2
    assert checked["feature_producer_imported"] is checked["refitted"] is False
    statistics = output / "candidate/statistics.json"
    altered = producer.read_json(statistics)
    altered["mean"][0] += 1
    statistics.write_bytes(producer.encoded(altered))
    changed = subprocess.run(
        [*command[:-1], str(receipt.with_name("mutated.json"))],
        capture_output=True,
        text=True,
    )
    assert changed.returncode != 0
    assert not receipt.with_name("mutated.json").exists()


def test_compressed_cache_reconstructs_exact_native_frames_and_bounds_live_lru(
    tmp_path, monkeypatch
):
    from badminton import court_detection, tracking, video

    originals = [generated_frame() for _ in range(20)]
    for index, frame in enumerate(originals):
        frame.pts = 1001 + index * 2
    source = {"id": "generated", "frame_count": 20, "width": 96, "height": 64}
    times, visits, packed, unpacked = [index / 30 for index in range(20)], [], [], []
    original_tracking, original_court = (
        tracking.iter_frames,
        court_detection.iter_frames,
    )
    pack, unpack = scaling.pack_frame, scaling.unpack_frame

    def decoded(*_):
        for index, frame in enumerate(originals):
            visits.append(index)
            yield index, times[index], frame

    def observed_pack(frame):
        packed.append(frame.pts)
        return pack(frame)

    def observed_unpack(record):
        unpacked.append(record["pts"])
        return unpack(record)

    monkeypatch.setattr(video, "iter_frames", decoded)
    monkeypatch.setattr(video, "resolve_source", lambda *_: None)
    monkeypatch.setattr(scaling, "pack_frame", observed_pack)
    monkeypatch.setattr(scaling, "unpack_frame", observed_unpack)
    assert scaling.CACHE_LRU_FRAMES == 16
    with scaling.decode_cache(source, tmp_path, times, lambda _: None) as count:
        assert count == 20 and visits == list(range(20))
        assert packed == [frame.pts for frame in originals]
        unpacked.clear()  # Packing verifies a reconstruction before retaining bytes.
        first = list(tracking.iter_frames(source, tmp_path, times, 0, 20))
        assert len(unpacked) == 20
        for index, (ordinal, timestamp, restored) in enumerate(first):
            original = originals[index]
            assert (ordinal, timestamp) == (index, times[index])
            assert restored is not original
            assert (restored.pts, restored.time_base) == (
                original.pts,
                original.time_base,
            )
            for representation in ("rgb24", "bgr24"):
                np.testing.assert_array_equal(
                    original.to_ndarray(format=representation),
                    restored.to_ndarray(format=representation),
                )
        newest = list(court_detection.iter_frames(source, tmp_path, times, 19, 20))
        assert newest[0][2] is first[19][2] and len(unpacked) == 20
        refreshed = list(tracking.iter_frames(source, tmp_path, times, 4, 5))
        assert refreshed[0][2] is first[4][2] and len(unpacked) == 20
        evicted = list(court_detection.iter_frames(source, tmp_path, times, 0, 1))
        assert evicted[0][2] is not first[0][2] and len(unpacked) == 21
        repeated = list(tracking.iter_frames(source, tmp_path, times, 0, 1))
        assert repeated[0][2] is evicted[0][2] and len(unpacked) == 21
        retained = list(tracking.iter_frames(source, tmp_path, times, 4, 5))
        assert retained[0][2] is refreshed[0][2] and len(unpacked) == 21
        next_evicted = list(tracking.iter_frames(source, tmp_path, times, 5, 6))
        assert next_evicted[0][2] is not first[5][2] and len(unpacked) == 22
        assert visits == list(range(20))
    assert tracking.iter_frames is original_tracking
    assert court_detection.iter_frames is original_court
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["initial", "compressed_cap", "free_memory"])
def test_compressed_cache_enforces_small_generated_memory_limits_without_disk_outputs(
    tmp_path, monkeypatch, fake_frame_codec, failure
):
    import psutil
    from badminton import court_detection, tracking, video

    original_tracking, original_court = (
        tracking.iter_frames,
        court_detection.iter_frames,
    )
    visits = []
    source = {"id": "generated", "frame_count": 2, "width": 10, "height": 10}
    monkeypatch.setattr(scaling, "CACHE_MIN_FREE_BYTES", 100)
    monkeypatch.setattr(scaling, "CACHE_INITIAL_EXTRA_BYTES", 20)
    monkeypatch.setattr(
        scaling, "CACHE_MAX_BYTES", 15 if failure == "compressed_cap" else 100
    )

    def available_memory():
        if failure == "initial":
            available = 119
        elif failure == "free_memory" and len(visits) >= 2:
            available = 99
        else:
            available = 1000
        return SimpleNamespace(available=available)

    def decoded(*_):
        for index in range(2):
            visits.append(index)
            yield index, index / 30, object()

    monkeypatch.setattr(psutil, "virtual_memory", available_memory)
    monkeypatch.setattr(video, "iter_frames", decoded)
    monkeypatch.setattr(video, "resolve_source", lambda *_: None)
    with pytest.raises(ValueError):
        with scaling.decode_cache(source, tmp_path, [0.0, 1 / 30], lambda _: None):
            pytest.fail("Entered cache beyond its bounded memory allowance")
    assert visits == ([] if failure == "initial" else [0, 1])
    assert tracking.iter_frames is original_tracking
    assert court_detection.iter_frames is original_court
    assert list(tmp_path.iterdir()) == []


def test_compressed_cache_caps_half_of_initial_free_memory(
    tmp_path, monkeypatch, fake_frame_codec
):
    import psutil
    from badminton import court_detection, tracking, video

    original_tracking, original_court = (
        tracking.iter_frames,
        court_detection.iter_frames,
    )
    monkeypatch.setattr(scaling, "CACHE_MIN_FREE_BYTES", 1)
    monkeypatch.setattr(scaling, "CACHE_INITIAL_EXTRA_BYTES", 1)
    monkeypatch.setattr(scaling, "CACHE_MAX_BYTES", 100)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=25))
    monkeypatch.setattr(
        video, "iter_frames", lambda *_: iter([(0, 0.0, object()), (1, 0.03, object())])
    )
    monkeypatch.setattr(video, "resolve_source", lambda *_: None)
    source = {"id": "generated", "frame_count": 2, "width": 10, "height": 10}
    with pytest.raises(ValueError):
        with scaling.decode_cache(source, tmp_path, [0.0, 0.03], lambda _: None):
            pytest.fail("Retained eighteen generated bytes under a twelve-byte cap")
    assert tracking.iter_frames is original_tracking
    assert court_detection.iter_frames is original_court
    assert list(tmp_path.iterdir()) == []


def test_compressed_cache_accepts_exact_reserve_and_compressed_byte_boundaries(
    tmp_path, monkeypatch, fake_frame_codec
):
    import psutil
    from badminton import tracking, video

    probes = []
    monkeypatch.setattr(scaling, "CACHE_MIN_FREE_BYTES", 100)
    monkeypatch.setattr(scaling, "CACHE_INITIAL_EXTRA_BYTES", 20)
    monkeypatch.setattr(scaling, "CACHE_MAX_BYTES", 18)

    def memory():
        available = 120 if not probes else 100
        probes.append(available)
        return SimpleNamespace(available=available)

    objects = [object(), object()]
    monkeypatch.setattr(psutil, "virtual_memory", memory)
    monkeypatch.setattr(
        video,
        "iter_frames",
        lambda *_: iter([(0, 0.0, objects[0]), (1, 0.03, objects[1])]),
    )
    monkeypatch.setattr(video, "resolve_source", lambda *_: None)
    source = {"id": "generated", "frame_count": 2, "width": 10, "height": 10}
    with scaling.decode_cache(source, tmp_path, [0.0, 0.03], lambda _: None) as count:
        assert count == 2
        assert [
            row[2] for row in tracking.iter_frames(source, tmp_path, [0.0, 0.03], 0, 2)
        ] == objects
    assert len(probes) >= 3
    assert list(tmp_path.iterdir()) == []
