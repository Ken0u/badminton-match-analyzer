"""Real generated video/audio exports, immutable evidence and failed publication."""

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
from badminton.rally_video import render_rally_videos
from badminton.schemas import Annotations
from badminton.storage import Store
from badminton.video import iter_frames, timestamps_for
from test_rally_export import context

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def saved_range(store, video, start, end, rally="R1", extra=()):
    doc = store.annotations(video["id"]).model_dump()
    doc["events"] = [
        {"id": "serve", "rally_id": rally, "kind": "serve", "frame": start},
        {
            "id": "end",
            "rally_id": rally,
            "kind": "rally_end",
            "frame": end,
            "status": "corrected",
        },
        *extra,
    ]
    return store.save_annotations(video["id"], Annotations.model_validate(doc))


def audio_context(tmp_path):
    source = tmp_path / "odd-audio.mkv"
    with av.open(str(source), "w") as container:
        video_stream = container.add_stream("ffv1", rate=25)
        video_stream.width, video_stream.height = 127, 65
        video_stream.pix_fmt = "bgr0"
        video_stream.time_base = Fraction(1, 1000)
        video_stream.codec_context.time_base = Fraction(1, 1000)
        audio_stream = container.add_stream("pcm_s16le", rate=48000)
        audio_stream.layout = "mono"
        for index, pts in enumerate((3000, 3040, 3080, 3200, 3400, 3600, 3800, 3840)):
            pixels = np.zeros((65, 127, 3), dtype=np.uint8)
            pixels[:, :, index % 3] = 60 + index * 25
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = pts, Fraction(1, 1000)
            for packet in video_stream.encode(frame):
                container.mux(packet)
        # Audible samples begin at source 3.12s, end at3.62s; clip origin differs.
        samples = (12000 * np.sin(np.arange(24000) * 2 * np.pi * 440 / 48000)).astype(
            np.int16
        )
        frame = av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = 48000
        frame.pts, frame.time_base = 149760, Fraction(1, 48000)
        for packet in audio_stream.encode(frame):
            container.mux(packet)
        for stream in (video_stream, audio_stream):
            for packet in stream.encode():
                container.mux(packet)
    store = Store(tmp_path / "data")
    video = inspect_video(source, "doubles", store, tmp_path)
    return store, video, source


def clip_path(output, manifest, index=0):
    clip = manifest["rallies"][index]["clip"]
    assert clip["file"] == Path(clip["file"]).name
    path = output / clip["file"]
    assert clip["sha256"] == digest(path)
    return path


def assert_media(path, video, source_frames, expected_times, duration):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        assert stream.codec_context.name == "h264"
        assert stream.codec_context.format.name == "yuv420p"
        assert float(stream.start_time * stream.time_base) == 0
        assert float(stream.duration * stream.time_base) == pytest.approx(
            duration, abs=2e-5
        )
        assert container.duration / 1e6 == pytest.approx(duration, abs=0.0011)
        frames = list(container.decode(stream))
    assert len(frames) == len(expected_times) == len(source_frames)
    assert [float(f.pts * f.time_base) for f in frames] == pytest.approx(
        expected_times, abs=2e-5
    )
    width, height = video["width"], video["height"]
    for actual, original in zip(frames, source_frames, strict=True):
        assert actual.rotation == 0
        assert (actual.width, actual.height) == (width + width % 2, height + height % 2)
        expected = original.to_ndarray(format="rgb24").astype(float)
        decoded = actual.to_ndarray(format="rgb24")[:height, :width].astype(float)
        assert np.mean(np.abs(expected - decoded)) < 10
    with av.open(str(path)) as container:
        packets = [p for p in container.demux(video=0) if p.pts is not None]
        assert all(p.dts == p.pts for p in packets)
        assert [float(p.pts * p.time_base) for p in packets] == pytest.approx(
            expected_times, abs=2e-5
        )
        assert [float(p.duration * p.time_base) for p in packets] == pytest.approx(
            [
                b - a
                for a, b in zip(
                    expected_times, [*expected_times[1:], duration], strict=True
                )
            ],
            abs=2e-5,
        )


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("origin", [0, 3000])
@pytest.mark.parametrize("start,end", [(0, 3), (1, 2), (2, 3)])
def test_native_range_pts_final_sample_pixels_and_original_evidence(
    tmp_path, mode, origin, start, end
):
    store, video, source, _ = context(tmp_path, mode, origin)
    saved = saved_range(store, video, start, end)
    prediction = store.data / video["id"] / "predictions.json"
    prediction.write_bytes(b'{"unknown":true}')
    before = {p: digest(p) for p in store.data.rglob("*") if p.is_file()}
    original_hash = digest(source)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    output = tmp_path / "clips"
    manifest = render_rally_videos(ExportPlanStore(store.data), plan, tmp_path, output)
    assert json.loads((output / "manifest.json").read_text()) == manifest
    assert manifest["counts"] == plan["counts"]
    canonical_plan = json.dumps(
        plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    assert manifest["plan_sha256"] == hashlib.sha256(canonical_plan).hexdigest()
    assert manifest["source"] == plan["source"]
    assert manifest["annotations"] == plan["annotations"]
    assert manifest["rallies"][0]["clip"]["audio"]["source_available"] is False
    assert manifest["annotation_sha256"] == plan["annotation_sha256"]
    assert manifest["annotation_revision"] == saved.revision
    for field, value in plan["rallies"][0].items():
        assert manifest["rallies"][0][field] == value
    times = timestamps_for(store.data, video["id"])
    expected = [t - times[start] for t in times[start : end + 1]]
    exclusive = times[end + 1] if end + 1 < len(times) else video["duration_s"]
    originals = [
        frame for _, _, frame in iter_frames(video, tmp_path, times, start, end + 1)
    ]
    assert_media(
        clip_path(output, manifest),
        video,
        originals,
        expected,
        exclusive - times[start],
    )
    assert digest(source) == original_hash
    assert before == {p: digest(p) for p in store.data.rglob("*") if p.is_file()}
    assert store.annotations(video["id"]) == saved


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_pixels_and_display_dimensions(tmp_path, rotation):
    store, video, _, saved = context(tmp_path, rotation=rotation)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    output = tmp_path / "clips"
    manifest = render_rally_videos(store, plan, tmp_path, output)
    times = timestamps_for(store.data, video["id"])
    originals = [f for _, _, f in iter_frames(video, tmp_path, times, 0, 4)]
    assert_media(
        clip_path(output, manifest), video, originals, times, video["duration_s"]
    )


@pytest.mark.parametrize("start,end,offset", [(1, 3, 0.08), (3, 4, 0.0), (6, 7, None)])
def test_odd_dimensions_delayed_audio_native_origin_and_no_overlap(
    tmp_path, start, end, offset
):
    store, video, _ = audio_context(tmp_path)
    saved = saved_range(store, video, start, end)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    output = tmp_path / "clips"
    manifest = render_rally_videos(store, plan, tmp_path, output)
    path = clip_path(output, manifest)
    times = timestamps_for(store.data, video["id"])
    exclusive = times[end + 1] if end + 1 < len(times) else video["duration_s"]
    originals = [f for _, _, f in iter_frames(video, tmp_path, times, start, end + 1)]
    assert_media(
        path,
        video,
        originals,
        [t - times[start] for t in times[start : end + 1]],
        exclusive - times[start],
    )
    audio_receipt = manifest["rallies"][0]["clip"]["audio"]
    assert audio_receipt["source_available"] is True
    with av.open(str(path)) as container:
        assert bool(container.streams.audio) == (offset is not None)
        if offset is not None:
            frames = list(container.decode(audio=0))
            assert frames
            assert audio_receipt["expected_start_s"] == pytest.approx(
                offset, abs=0.0011
            )
            assert audio_receipt["stream_start_s"] <= offset + 0.0011
            # AAC priming can precede the first audible source sample. Compare
            # actual waveform onset, not the first decoded padding frame's PTS.
            audible = []
            for frame in frames:
                samples = np.abs(frame.to_ndarray()).max(axis=0)
                indices = np.flatnonzero(samples > 0.05)
                if len(indices):
                    audible.append(
                        float(frame.pts * frame.time_base)
                        + indices[0] / frame.sample_rate
                    )
            assert audible
            assert min(audible) == pytest.approx(offset, abs=0.0011)
    if offset is None:
        assert audio_receipt["reason"] == "no_audio_overlap"


def test_ineligible_rallies_ids_context_and_unknowns_retained(tmp_path):
    store, video, _, _ = context(tmp_path, mode="doubles")
    saved = saved_range(
        store,
        video,
        0,
        1,
        rally="../../escape",
        extra=[
            {
                "id": "partial",
                "kind": "rally_end",
                "frame": 3,
                "rally_id": "missing-start",
            }
        ],
    )
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    output = tmp_path / "clips"
    manifest = render_rally_videos(store, plan, tmp_path, output)
    assert manifest["counts"] == {"total": 2, "eligible": 1, "ineligible": 1}
    for original, exported in zip(plan["rallies"], manifest["rallies"], strict=True):
        for key, value in original.items():
            assert exported[key] == value
        if original["eligible"]:
            clip_path(output, manifest, manifest["rallies"].index(exported))
        else:
            assert exported["clip"] is None
    assert not (tmp_path / "escape").exists()
    assert len(list(output.glob("*.mp4"))) == 1


@pytest.mark.parametrize(
    "field", ["range", "source", "revision", "annotation", "counts", "eligible"]
)
def test_edited_plan_is_rejected_before_output_or_encoding(tmp_path, field):
    store, video, _, saved = context(tmp_path)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    edited = copy.deepcopy(plan)
    if field == "range":
        edited["rallies"][0]["source_range"]["start_frame"] = 1
    elif field == "source":
        edited["source"]["sha256"] = "0" * 64
    elif field == "revision":
        edited["annotation_revision"] = 0
    elif field == "annotation":
        edited["annotations"]["events"][0]["notes"] = "changed"
    elif field == "counts":
        edited["counts"]["total"] += 1
    else:
        edited["rallies"][0]["eligible"] = False
    output = tmp_path / "clips"
    with pytest.raises((KeyError, ValueError)):
        render_rally_videos(store, edited, tmp_path, output)
    assert not output.exists()


@pytest.mark.parametrize("changed", ["source", "timestamps", "revision"])
def test_changed_input_or_missing_revision_does_not_publish(tmp_path, changed):
    store, video, source, saved = context(tmp_path)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    if changed == "source":
        source.write_bytes(b"changed")
    elif changed == "timestamps":
        (store.data / video["id"] / "timestamps.json").write_text("[0,0.04,0.08,0.60]")
    else:
        with store.connect() as db:
            db.execute("DELETE FROM annotations WHERE video_id=?", (video["id"],))
    output = tmp_path / "clips"
    with pytest.raises((KeyError, ValueError, OSError)):
        render_rally_videos(store, plan, tmp_path, output)
    assert not output.exists()


def test_newer_revision_keeps_saved_plan_reproducible_and_existing_export_immutable(
    tmp_path,
):
    store, video, _, saved = context(tmp_path)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    saved_range(store, video, 1, 2)
    output = tmp_path / "clips"
    manifest = render_rally_videos(store, plan, tmp_path, output)
    before = {p.name: digest(p) for p in output.iterdir()}
    with pytest.raises((ValueError, FileExistsError)):
        render_rally_videos(store, plan, tmp_path, output)
    assert before == {p.name: digest(p) for p in output.iterdir()}
    assert manifest["annotation_revision"] == saved.revision


@pytest.mark.parametrize("target", ["data", "existing", "symlink"])
def test_unsafe_or_existing_output_is_refused(tmp_path, target):
    store, video, _, saved = context(tmp_path)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    output = tmp_path / "clips"
    if target == "data":
        output = store.data / "export"
    elif target == "existing":
        output.mkdir()
        (output / "keep").write_text("existing")
    else:
        output.symlink_to(store.data, target_is_directory=True)
    with pytest.raises((ValueError, FileExistsError)):
        render_rally_videos(store, plan, tmp_path, output)
    if target == "existing":
        assert (output / "keep").read_text() == "existing"
    assert not (store.data / "export").exists()


@pytest.mark.parametrize("error", [RuntimeError("cancelled"), KeyboardInterrupt()])
def test_progress_cancellation_cleans_all_incomplete_outputs(tmp_path, error):
    store, video, source, saved = context(tmp_path)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    before = digest(source)
    output = tmp_path / "clips"

    def cancel(value):
        raise error

    with pytest.raises(type(error)):
        render_rally_videos(store, plan, tmp_path, output, progress=cancel)
    assert not output.exists()
    assert digest(source) == before
    assert store.annotations(video["id"]) == saved


@pytest.mark.parametrize("final_only", [False, True])
def test_input_changed_while_encoding_invalidates_whole_export(tmp_path, final_only):
    store, video, _, saved = context(tmp_path)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    timeline = store.data / video["id"] / "timestamps.json"
    output = tmp_path / "clips"

    def change(value):
        if value > 0 and (not final_only or value == 1):
            timeline.write_text("[0,0.04,0.08,0.6]")

    with pytest.raises(ValueError):
        render_rally_videos(store, plan, tmp_path, output, progress=change)
    assert not output.exists()


def test_cli_consumes_saved_plan_and_cannot_overwrite(tmp_path):
    store, video, _, saved = context(tmp_path)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    output = tmp_path / "cli-clips"
    env = os.environ | {
        "BADMINTON_ROOT": str(tmp_path),
        "BADMINTON_DATA_DIR": str(store.data),
    }
    command = [
        sys.executable,
        "-m",
        "badminton.cli",
        "export-rally-videos",
        str(plan_path),
        "--output",
        str(output),
    ]
    result = subprocess.run(
        command, env=env, text=True, capture_output=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    clip_path(output, manifest)
    repeated = subprocess.run(
        command, env=env, text=True, capture_output=True, timeout=30
    )
    assert repeated.returncode != 0


def test_all_ineligible_rallies_have_manifest_without_encoding(tmp_path):
    from unittest.mock import patch

    store, video, _, saved = context(tmp_path)
    doc = saved.model_dump()
    doc["events"][0]["status"] = "predicted"
    saved = store.save_annotations(video["id"], Annotations.model_validate(doc))
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    output = tmp_path / "clips"
    with patch("badminton.rally_video.subprocess.Popen") as encoder:
        manifest = render_rally_videos(store, plan, tmp_path, output)
        encoder.assert_not_called()
    assert manifest["counts"] == {"total": 1, "eligible": 0, "ineligible": 1}
    assert manifest["rallies"][0]["reasons"] == ["unreviewed_start"]
    assert manifest["rallies"][0]["clip"] is None
    assert manifest["annotations"] == plan["annotations"]
    assert list(output.iterdir()) == [output / "manifest.json"]


def test_encoder_launch_failure_cleans_staging_without_source_changes(tmp_path):
    from unittest.mock import patch

    store, video, source, saved = context(tmp_path)
    plan = plan_rally_exports(store, video["id"], saved.revision, tmp_path)
    before = digest(source)
    output = tmp_path / "clips"
    with patch(
        "badminton.rally_video.subprocess.Popen",
        side_effect=OSError("encoder unavailable"),
    ):
        with pytest.raises(OSError, match="encoder unavailable"):
            render_rally_videos(store, plan, tmp_path, output)
    assert not output.exists()
    assert digest(source) == before
    assert store.annotations(video["id"]) == saved
