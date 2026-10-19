"""Generated source-frame annotation burn-in with immutable video/audio evidence."""

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest
from badminton.ingest import inspect_video
from badminton.rally_export import ExportPlanStore, plan_rally_exports
from badminton.rally_overlay import (
    OVERLAY_CONFIG,
    overlay_context,
    overlay_frame,
    render_annotated_videos,
)
from badminton.schemas import Annotations
from badminton.storage import Store
from badminton.video import iter_frames, timestamps_for
from media_fixtures import write_rotated_video

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def context(tmp_path, mode="singles", audio=False, rotation=None):
    source = tmp_path / "source.mkv"
    if rotation is not None:
        source = write_rotated_video(
            tmp_path / "rotated.mp4",
            rotation,
            timestamps=(7000, 7040, 7100, 7300, 7340, 7600, 7800, 8000),
        )
    else:
        with av.open(str(source), "w") as container:
            stream = container.add_stream("ffv1", rate=25)
            stream.width, stream.height = 641, 361
            stream.pix_fmt = "bgr0"
            stream.time_base = Fraction(1, 1000)
            stream.codec_context.time_base = Fraction(1, 1000)
            audio_stream = None
            if audio:
                audio_stream = container.add_stream("pcm_s16le", rate=48000)
                audio_stream.layout = "mono"
            for index, pts in enumerate(
                (7000, 7040, 7100, 7300, 7340, 7600, 7800, 8000)
            ):
                pixels = np.zeros((361, 641, 3), dtype=np.uint8)
                pixels[:] = (25 + index * 20, 40 + index * 10, 80)
                pixels[230:280, 500:560] = (220, 30, 10)
                pixels[300:340, 560:620] = (10, 220, 30)
                frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                frame.pts, frame.time_base = pts, Fraction(1, 1000)
                for packet in stream.encode(frame):
                    container.mux(packet)
            if audio:
                samples = (
                    12000 * np.sin(np.arange(40000) * 2 * np.pi * 440 / 48000)
                ).astype(np.int16)
                frame = av.AudioFrame.from_ndarray(
                    samples.reshape(1, -1), format="s16", layout="mono"
                )
                frame.sample_rate = 48000
                frame.pts, frame.time_base = 339840, Fraction(1, 48000)  # 7.08s
                for packet in audio_stream.encode(frame):
                    container.mux(packet)
            for selected in (stream, audio_stream):
                if selected is not None:
                    for packet in selected.encode():
                        container.mux(packet)
    store = Store(tmp_path / "data")
    video = inspect_video(source, mode, store, tmp_path)
    doc = store.annotations(video["id"]).model_dump()
    player = doc["players"][0]["id"]
    doc["players"][0]["name"] = "A player"
    doc["events"] = [
        {
            "id": "serve",
            "rally_id": "R1",
            "kind": "serve",
            "frame": 1,
            "side": "forehand",
            "player_id": player,
        },
        {
            "id": "uncertain",
            "rally_id": "R1",
            "kind": "shot",
            "frame": 2,
            "family": "unknown",
            "side": "unknown",
            "contact_start_frame": 1,
            "contact_end_frame": 3,
        },
        {
            "id": "predicted",
            "rally_id": "R1",
            "kind": "shot",
            "frame": 4,
            "family": "smash",
            "side": "forehand",
            "status": "predicted",
        },
        {
            "id": "corrected",
            "rally_id": "R1",
            "kind": "shot",
            "frame": 5,
            "family": "clear",
            "side": "backhand",
            "player_id": player,
            "status": "corrected",
        },
        {
            "id": "end",
            "rally_id": "R1",
            "kind": "rally_end",
            "frame": 6,
            "status": "corrected",
        },
    ]
    doc["scene_ranges"] = [
        {"id": "live", "start_frame": 0, "end_frame": 3, "scene": "live"},
        {"id": "replay", "start_frame": 3, "end_frame": 6, "scene": "replay"},
        {"id": "unknown", "start_frame": 6, "end_frame": 8, "scene": "unknown"},
    ]
    doc["camera_corrections"] = [{"frame": 4, "is_cut": True}]
    doc["calibrations"] = [
        {
            "start_frame": 0,
            "end_frame": 8,
            "corners": [
                {"x": 0.1, "y": 0.2},
                {"x": 0.9, "y": 0.2},
                {"x": 0.9, "y": 0.9},
                {"x": 0.1, "y": 0.9},
            ],
        }
    ]
    doc["shuttle_points"] = [
        {"frame": 2, "visible": True, "x": 0.35, "y": 0.6},
        {"frame": 3, "visible": False},
        {"frame": 6, "visible": True, "x": 0.7, "y": 0.7},
    ]
    saved = store.save_annotations(video["id"], Annotations.model_validate(doc))
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    return store, video, source, saved, plan


def exported_path(output, manifest):
    assert manifest["exports"]
    result = manifest["exports"][0]
    assert result["file"] == Path(result["file"]).name
    path = output / result["file"]
    assert sha(path) == result["sha256"]
    return path, result


def assert_native_media(path, video, times, start, end, duration):
    expected = [t - times[start] for t in times[start:end]]
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        assert stream.codec_context.name == "h264"
        assert stream.start_time == 0
        assert float(stream.duration * stream.time_base) == pytest.approx(
            duration, abs=2e-5
        )
        assert container.duration / 1e6 == pytest.approx(duration, abs=0.0011)
        frames = list(container.decode(stream))
    assert len(frames) == end - start
    assert [float(f.pts * f.time_base) for f in frames] == pytest.approx(
        expected, abs=2e-5
    )
    assert all(f.rotation == 0 for f in frames)
    assert [(f.width, f.height) for f in frames] == [
        (video["width"] + video["width"] % 2, video["height"] + video["height"] % 2)
    ] * len(frames)
    with av.open(str(path)) as container:
        packets = [p for p in container.demux(video=0) if p.pts is not None]
    assert len(packets) == len(frames)
    assert [float(p.duration * p.time_base) for p in packets] == pytest.approx(
        [b - a for a, b in zip(expected, [*expected[1:], duration], strict=True)],
        abs=2e-5,
    )
    return frames


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("scope,start,end", [("full", 0, 8), ("rallies", 1, 7)])
@pytest.mark.parametrize("audio", [False, True])
def test_full_and_rally_modes_preserve_frames_audio_and_immutable_evidence(
    tmp_path, mode, scope, start, end, audio
):
    store, video, source, saved, plan = context(tmp_path, mode, audio)
    before = {p: sha(p) for p in store.data.rglob("*") if p.is_file()}
    original = sha(source)
    output = tmp_path / "annotated"
    manifest = render_annotated_videos(
        ExportPlanStore(store.data), plan, tmp_path, output, scope=scope
    )
    assert json.loads((output / "manifest.json").read_text()) == manifest
    assert manifest["counts"] == plan["counts"]
    assert manifest["annotations"] == plan["annotations"]
    assert manifest["source"] == plan["source"]
    assert manifest["annotation_revision"] == saved.revision
    assert manifest["annotation_sha256"] == plan["annotation_sha256"]
    assert manifest["plan_sha256"] == hashlib.sha256(canonical(plan)).hexdigest()
    assert manifest["overlay_config"] == OVERLAY_CONFIG
    assert (
        manifest["overlay_config_sha256"]
        == hashlib.sha256(canonical(OVERLAY_CONFIG)).hexdigest()
    )
    report = manifest["event_counts"]
    assert (report["total"], report["included"], report["excluded"]) == (5, 4, 1)
    assert {e["id"] for e in report["events"]} == {
        e["id"] for e in plan["annotations"]["events"]
    }
    predicted = next(e for e in report["events"] if e["id"] == "predicted")
    assert (
        not predicted["included"]
        and predicted["reason"] == "predicted_not_reviewed_truth"
    )
    path, receipt = exported_path(output, manifest)
    assert receipt["start_frame"] == start
    assert receipt["end_frame_exclusive"] == end
    times = timestamps_for(store.data, video["id"])
    duration = (times[end] if end < len(times) else video["duration_s"]) - times[start]
    frames = assert_native_media(path, video, times, start, end, duration)
    originals = list(iter_frames(video, tmp_path, times, start, end))
    # A lower-right patch remains outside the documented overlays in this fixture.
    for frame, (_, _, native) in zip(frames, originals, strict=True):
        actual = frame.to_ndarray(format="rgb24")[300:330, 570:610].astype(float)
        expected = native.to_ndarray(format="rgb24")[300:330, 570:610].astype(float)
        assert np.mean(np.abs(actual - expected)) < 10
    with av.open(str(path)) as container:
        assert bool(container.streams.audio) == audio
        if audio:
            decoded = list(container.decode(audio=0))
            onset = []
            for frame in decoded:
                positions = np.flatnonzero(
                    np.abs(frame.to_ndarray()).max(axis=0) > 0.05
                )
                if len(positions):
                    onset.append(
                        float(frame.pts * frame.time_base)
                        + positions[0] / frame.sample_rate
                    )
            assert min(onset) == pytest.approx(0.08 - times[start], abs=0.0011)
    assert sha(source) == original
    assert before == {p: sha(p) for p in store.data.rglob("*") if p.is_file()}
    assert store.annotations(video["id"]) == saved


def test_overlay_context_preserves_unknowns_intervals_predictions_and_expiry(tmp_path):
    _, _, _, saved, _ = context(tmp_path)
    snapshot = saved.model_dump()
    contexts = [overlay_context(snapshot, index) for index in range(8)]
    assert [c["scene"] for c in contexts] == ["live"] * 3 + ["replay"] * 3 + [
        "unknown"
    ] * 2
    assert contexts[4]["camera_cut"] is True
    assert contexts[3]["calibration"] is not None
    assert contexts[4]["calibration"] is None
    assert contexts[7]["calibration"] is None
    for frame in (1, 2, 3):
        events = contexts[frame]["events"]
        uncertain = next(e for e in events if e["id"] == "uncertain")
        assert uncertain["uncertain"] is True
        assert "unknown" in json.dumps(uncertain)
    assert all("predicted" not in [e["id"] for e in c["events"]] for c in contexts)
    assert not contexts[0]["events"]
    assert [e["id"] for e in contexts[5]["events"]] == ["corrected"]
    assert not contexts[5]["shuttle_points"]
    assert contexts[2]["shuttle_points"][0]["x"] == 0.35
    assert not contexts[3]["shuttle_points"]
    assert not contexts[4]["shuttle_points"]


def test_overlay_frame_has_bounded_mask_and_preserves_unmasked_pixels(tmp_path):
    store, video, _, saved, _ = context(tmp_path)
    times = timestamps_for(store.data, video["id"])
    _, _, source = next(iter_frames(video, tmp_path, times, 2, 3))
    original = source.to_ndarray(format="rgb24")
    frame, mask, ctx = overlay_frame(source, saved.model_dump(), 2)
    actual = frame.to_ndarray(format="rgb24")
    assert mask.shape == original.shape[:2] and mask.dtype == np.bool_
    assert mask.any() and (~mask).sum() > original.shape[0] * original.shape[1] // 4
    assert np.array_equal(actual[~mask], original[~mask])
    assert np.any(actual[mask] != original[mask])
    assert frame.pts == source.pts and frame.time_base == source.time_base
    assert ctx == overlay_context(saved.model_dump(), 2)
    assert isinstance(OVERLAY_CONFIG, dict)


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_annotated_rotation_has_native_display_frame_identity(tmp_path, rotation):
    store, video, _, _, plan = context(tmp_path, rotation=rotation)
    output = tmp_path / "rotated"
    manifest = render_annotated_videos(store, plan, tmp_path, output, scope="full")
    path, _ = exported_path(output, manifest)
    times = timestamps_for(store.data, video["id"])
    assert_native_media(path, video, times, 0, 8, video["duration_s"])


def test_full_video_remains_full_when_all_rally_boundaries_are_ineligible(tmp_path):
    store, video, _, saved, _ = context(tmp_path)
    doc = saved.model_dump()
    doc["events"][0]["status"] = "predicted"
    saved = store.save_annotations(video["id"], Annotations.model_validate(doc))
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    output = tmp_path / "full"
    manifest = render_annotated_videos(store, plan, tmp_path, output, scope="full")
    path, _ = exported_path(output, manifest)
    assert manifest["counts"] == {"total": 1, "eligible": 0, "ineligible": 1}
    assert_native_media(
        path, video, timestamps_for(store.data, video["id"]), 0, 8, video["duration_s"]
    )
    rally_output = tmp_path / "rallies"
    rally_manifest = render_annotated_videos(
        store, plan, tmp_path, rally_output, scope="rallies"
    )
    assert rally_manifest["exports"] == []
    assert not list(rally_output.glob("*.mp4"))


@pytest.mark.parametrize("change", ["source", "timestamps", "plan", "snapshot"])
def test_stale_or_edited_input_rejected_without_output(tmp_path, change):
    store, video, source, _, plan = context(tmp_path)
    if change == "source":
        source.write_bytes(b"changed")
    elif change == "timestamps":
        (store.data / video["id"] / "timestamps.json").write_text(
            "[0,.04,.10,.30,.34,.6,.8,1.1]"
        )
    elif change == "plan":
        plan = copy.deepcopy(plan)
        plan["rallies"][0]["source_range"]["start_frame"] = 0
    else:
        plan = copy.deepcopy(plan)
        plan["annotations"]["events"][0]["status"] = "predicted"
    output = tmp_path / "rejected"
    with pytest.raises((ValueError, OSError)):
        render_annotated_videos(store, plan, tmp_path, output, scope="full")
    assert not output.exists()


@pytest.mark.parametrize("target", ["data", "existing", "symlink", "traversal"])
def test_output_boundaries_refuse_overwrite_or_escape(tmp_path, target):
    store, _, source, _, plan = context(tmp_path)
    output = tmp_path / "output"
    if target == "data":
        output = store.data / "export"
    elif target == "existing":
        output.mkdir()
        (output / "keep").write_text("keep")
    elif target == "symlink":
        output.symlink_to(store.data, target_is_directory=True)
    else:
        output = tmp_path / ".." / "escaped"
    before = sha(source)
    with pytest.raises((ValueError, FileExistsError)):
        render_annotated_videos(store, plan, tmp_path, output, scope="full")
    assert sha(source) == before
    if target == "existing":
        assert (output / "keep").read_text() == "keep"


@pytest.mark.parametrize("final", [False, True])
def test_cancellation_leaves_no_completed_or_partial_export(tmp_path, final):
    store, _, source, saved, plan = context(tmp_path)
    output = tmp_path / "cancelled"
    before = sha(source)

    def cancel(value):
        if value > 0 and (not final or value == 1):
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        render_annotated_videos(
            store, plan, tmp_path, output, scope="full", progress=cancel
        )
    assert not output.exists()
    assert sha(source) == before
    assert store.annotations(plan["source"]["id"]) == saved


def test_newer_revision_keeps_older_annotations_and_previous_export_immutable(tmp_path):
    store, video, _, saved, plan = context(tmp_path)
    doc = saved.model_dump()
    doc["players"][0]["name"] = "New name"
    store.save_annotations(video["id"], Annotations.model_validate(doc))
    output = tmp_path / "older"
    manifest = render_annotated_videos(store, plan, tmp_path, output, scope="full")
    assert manifest["annotations"] == plan["annotations"]
    before = {p.name: sha(p) for p in output.iterdir()}
    with pytest.raises((ValueError, FileExistsError)):
        render_annotated_videos(store, plan, tmp_path, output, scope="full")
    assert before == {p.name: sha(p) for p in output.iterdir()}


def test_cli_requires_explicit_scope_and_writes_annotated_video(tmp_path):
    store, _, _, _, plan = context(tmp_path)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    output = tmp_path / "cli"
    env = os.environ | {
        "BADMINTON_ROOT": str(tmp_path),
        "BADMINTON_DATA_DIR": str(store.data),
    }
    command = [
        sys.executable,
        "-m",
        "badminton.cli",
        "export-annotated-videos",
        str(path),
        "--output",
        str(output),
    ]
    missing = subprocess.run(
        command, env=env, text=True, capture_output=True, timeout=30
    )
    assert missing.returncode != 0 and not output.exists()
    result = subprocess.run(
        [*command, "--scope", "full"],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    exported_path(output, json.loads(result.stdout))


def test_full_video_cannot_invent_an_unavailable_final_sample_endpoint(tmp_path):
    from unittest.mock import patch

    from badminton.rally_export import _audit_source

    store, video, _, saved, _ = context(tmp_path)

    def unavailable(*args):
        pts, _ = _audit_source(*args)
        return pts, None

    with patch("badminton.rally_export._audit_source", side_effect=unavailable):
        plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
        assert plan["rallies"][0]["eligible"]  # its next native PTS is available
        output = tmp_path / "no-final-end"
        with pytest.raises(ValueError):
            render_annotated_videos(store, plan, tmp_path, output, scope="full")
        assert not output.exists()


def test_final_input_change_invalidates_entire_annotated_export(tmp_path):
    store, video, _, _, plan = context(tmp_path)
    output = tmp_path / "changed"

    def change(value):
        if value == 1:
            (store.data / video["id"] / "timestamps.json").write_text(
                "[0,0.04,0.10,0.30,0.34,0.6,0.8,1.1]"
            )

    with pytest.raises(ValueError):
        render_annotated_videos(
            store, plan, tmp_path, output, scope="full", progress=change
        )
    assert not output.exists()


def test_unsupported_scope_is_not_silently_replaced_with_full_or_rallies(tmp_path):
    store, _, _, _, plan = context(tmp_path)
    output = tmp_path / "bad-scope"
    with pytest.raises(ValueError):
        render_annotated_videos(store, plan, tmp_path, output, scope="highlights")
    assert not output.exists()


def test_terminal_uncertainty_stays_interval_in_full_video_and_ineligible_rally(
    tmp_path,
):
    store, video, _, saved, _ = context(tmp_path)
    doc = saved.model_dump()
    doc["events"][-1].update(terminal_start_frame=6, terminal_end_frame=7)
    saved = store.save_annotations(video["id"], Annotations.model_validate(doc))
    snapshot = saved.model_dump()
    for index in (6, 7):
        record = next(
            e for e in overlay_context(snapshot, index)["events"] if e["id"] == "end"
        )
        assert record["uncertain"] is True
        assert (record["start_frame"], record["end_frame_inclusive"]) == (6, 7)
        assert "uncertain interval" in record["text"]
        assert "exact frame" not in record["text"]
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    assert plan["rallies"][0]["reasons"] == ["uncertain_end"]
    manifest = render_annotated_videos(
        store, plan, tmp_path, tmp_path / "uncertain-full", scope="full"
    )
    assert manifest["exports"][0]["frame_count"] == 8
    assert manifest["counts"]["ineligible"] == 1


def test_saved_calibration_range_and_new_after_cut_calibration_are_respected(tmp_path):
    _, _, _, saved, _ = context(tmp_path)
    snapshot = saved.model_dump()
    first = snapshot["calibrations"][0]
    first["end_frame"] = 3
    snapshot["calibrations"].append(
        copy.deepcopy(first) | {"start_frame": 5, "end_frame": 7}
    )
    snapshot = Annotations.model_validate(snapshot).model_dump()
    assert overlay_context(snapshot, 2)["calibration"] is not None
    assert overlay_context(snapshot, 3)["calibration"] is None
    assert overlay_context(snapshot, 4)["calibration"] is None
    assert overlay_context(snapshot, 5)["calibration"] is not None
    assert overlay_context(snapshot, 6)["calibration"] is not None
    assert overlay_context(snapshot, 7)["calibration"] is None


def test_long_and_unicode_saved_names_are_retained_in_wrapped_burn_in(tmp_path):
    from unittest.mock import patch

    import cv2

    store, video, _, saved, _ = context(tmp_path)
    snapshot = saved.model_dump()
    snapshot["players"][0]["name"] = "A" * 80 + "名"
    snapshot = Annotations.model_validate(snapshot).model_dump()
    times = timestamps_for(store.data, video["id"])
    _, _, frame = next(iter_frames(video, tmp_path, times, 5, 6))
    labels = []
    draw = cv2.putText

    def record(image, text, *args, **kwargs):
        labels.append(text)
        return draw(image, text, *args, **kwargs)

    with patch("badminton.rally_overlay.cv2.putText", side_effect=record):
        overlay_frame(frame, snapshot, 5)
    rendered = "".join("".join(labels).split())
    expected = "".join(
        " ".join(overlay_context(snapshot, 5)["text"])
        .encode("ascii", "backslashreplace")
        .decode("ascii")
        .split()
    )
    assert rendered == expected
    assert "A" * 80 + "\\u540d" in rendered
