"""Source-only packets preserve native identity and every unknown review case."""

import copy
import hashlib
import io
import itertools
import json
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
import pytest
from badminton import shuttle_sources as sources
from media_fixtures import write_rotated_video
from PIL import Image

FLAGS = (
    "training_allowed",
    "independent_test_allowed",
    "model_deployment_allowed",
    "dataset_redistribution_allowed",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clock(count=65):
    return {
        "frame_count": count,
        "frames": [
            {
                "frame": i,
                "pts": 200 + i * 40 + (i // 2) * 20,
                "time_base": "1/1000",
                "time_s": (200 + i * 40 + (i // 2) * 20) / 1000,
                "rotation": 0,
                "source_size": [64, 32],
                "display_size": [64, 32],
                "corrupt": False,
            }
            for i in range(count)
        ],
        "origin_s": 0.2,
        "complete": True,
        "issues": [],
    }


@pytest.fixture
def vfr_source(tmp_path):
    path = tmp_path / "vfr.mkv"
    timestamps = [200 + i * 40 + (i // 2) * 20 for i in range(65)]
    with av.open(str(path), "w") as container:
        stream = container.add_stream("ffv1", rate=25)
        stream.width, stream.height, stream.pix_fmt = 64, 32, "bgr0"
        stream.time_base = stream.codec_context.time_base = Fraction(1, 1000)
        for index, timestamp in enumerate(timestamps):
            pixels = np.empty((32, 64, 3), dtype=np.uint8)
            pixels[:, :32] = [index * 3, 10, 220]
            pixels[:, 32:] = [230, index * 3, 30]
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = timestamp, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


def test_uniform_selection_keeps_native_ordinals_and_all_edge_memberships():
    native = clock(203)
    cases = sources.sample_memberships(native)
    assert len(cases) == 64
    assert [row["center_frame"] for row in cases] == [j * 202 // 63 for j in range(64)]
    assert len({row["case_id"] for row in cases}) == 64
    assert sum(len(row["context"]) for row in cases) == 320
    assert [item["frame"] for item in cases[0]["context"]] == [0, 0, 0, 1, 2]
    assert [item["frame"] for item in cases[-1]["context"]] == [200, 201, 202, 202, 202]
    assert [item["clamped"] for item in cases[0]["context"]] == [
        True,
        True,
        False,
        False,
        False,
    ]


def test_short_source_cannot_silently_shrink_requested_case_denominator():
    with pytest.raises(ValueError):
        sources.sample_memberships(clock(63))


def test_incomplete_clock_cannot_be_presented_as_a_complete_packet():
    native = clock(64)
    native["frames"][17].update(pts=None, time_base=None, time_s=None, corrupt=True)
    native["issues"] = ["missing_pts", "corrupt_frame"]
    native["complete"] = False
    with pytest.raises(ValueError, match=r"unavailable|complete"):
        sources.sample_memberships(native)
    assert native["frames"][17]["pts"] is None
    assert native["frames"][17]["corrupt"] is True


def test_original_shared_store_roots_are_required_before_any_acquisition(
    tmp_path, monkeypatch
):
    from badminton import config
    from badminton.storage import Store

    shared = tmp_path / "data/processed"
    Store(shared)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path / "isolated")
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    with patch("yt_dlp.YoutubeDL") as downloader:
        with pytest.raises(ValueError, match=r"original|real shared|roots"):
            sources.run_preparation(
                tmp_path,
                tmp_path / ".cache/output",
                sources_path=tmp_path / "sources.json",
                protocol_path=tmp_path / "protocol.json",
            )
        downloader.assert_not_called()
    assert not (tmp_path / ".cache/output").exists()


@pytest.mark.parametrize("changed", ["ROOT", "WEIGHTS"])
def test_copied_root_or_experimental_weights_do_not_admit_work(
    tmp_path, monkeypatch, changed
):
    from badminton import config
    from badminton.storage import Store

    shared = tmp_path / "data/processed"
    Store(shared)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", shared)
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    monkeypatch.setattr(config, changed, tmp_path / "other")
    with patch("yt_dlp.YoutubeDL") as downloader:
        with pytest.raises(ValueError, match=r"original|real shared|roots"):
            sources.run_preparation(
                tmp_path,
                tmp_path / ".cache/output",
                sources_path=tmp_path / "sources.json",
                protocol_path=tmp_path / "protocol.json",
            )
        downloader.assert_not_called()
    assert not (tmp_path / ".cache/output").exists()


def budget(output, **changes):
    return sources.Budget(
        output,
        {
            "source_bytes": 1024**2,
            "download_bytes": 2 * 1024**2,
            "output_bytes": 8 * 1024**2,
            "worker_seconds": 60,
            "max_frames_per_source": 300000,
            **changes,
        },
    )


def test_native_vfr_census_matches_every_real_decoded_pts_and_origin(
    vfr_source, tmp_path
):
    actual = sources.native_clock(vfr_source, budget(tmp_path / "out"))
    with av.open(str(vfr_source)) as container:
        expected = list(container.decode(container.streams.video[0]))
    assert actual["frame_count"] == len(expected) == 65
    assert actual["complete"] is True and actual["issues"] == []
    assert actual["origin_s"] == float(expected[0].pts * expected[0].time_base)
    assert [item["frame"] for item in actual["frames"]] == list(range(65))
    assert [item["pts"] for item in actual["frames"]] == [
        frame.pts for frame in expected
    ]
    assert [item["time_base"] for item in actual["frames"]] == [
        str(frame.time_base) for frame in expected
    ]
    assert [item["time_s"] for item in actual["frames"]] == [
        float(frame.pts * frame.time_base) for frame in expected
    ]
    assert len({b.pts - a.pts for a, b in itertools.pairwise(expected)}) == 2
    assert all(item["source_size"] == [64, 32] for item in actual["frames"])
    assert all(item["display_size"] == [64, 32] for item in actual["frames"])
    assert all(
        item["rotation"] == 0 and not item["corrupt"] for item in actual["frames"]
    )


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_native_census_retains_real_display_matrix_orientation(tmp_path, rotation):
    source = write_rotated_video(tmp_path / "oriented.mp4", rotation)
    actual = sources.native_clock(source, budget(tmp_path / "out"))
    assert actual["frame_count"] == 4
    assert actual["complete"] is True
    size = [64, 128] if rotation in (90, 270) else [128, 64]
    assert all(row["rotation"] == rotation for row in actual["frames"])
    assert all(row["source_size"] == [128, 64] for row in actual["frames"])
    assert all(row["display_size"] == size for row in actual["frames"])


def test_full_decode_bound_fails_instead_of_reporting_a_truncated_stream(
    vfr_source, tmp_path
):
    with pytest.raises(ValueError, match=r"frame|bound"):
        sources.native_clock(vfr_source, budget(tmp_path / "out"), max_frames=64)


def test_output_publication_is_exclusive_and_accounts_for_existing_bytes(tmp_path):
    output = tmp_path / "out"
    limits = budget(output, output_bytes=10)
    target = output / "a.bin"
    limits.publish(target, b"original")
    with pytest.raises(FileExistsError):
        limits.publish(target, b"new")
    assert target.read_bytes() == b"original"
    with pytest.raises(ValueError, match=r"bound|budget|output"):
        limits.publish(output / "b.bin", b"123")
    assert not (output / "b.bin").exists()
    assert target.read_bytes() == b"original"


def test_stream_failure_preserves_partial_attempt_without_publishing_final(tmp_path):
    output = tmp_path / "out"
    limits = budget(output)
    final = output / "source.mp4"

    class Interrupted:
        def __init__(self):
            self.reads = 0

        def read(self, _size):
            self.reads += 1
            if self.reads == 1:
                return b"partial"
            raise OSError("generated interrupted source")

    with pytest.raises(OSError, match=r"interrupted"):
        limits.stream(final, Interrupted(), limit=100)
    assert not final.exists()
    pending = [path for path in output.rglob("*") if path.is_file()]
    assert pending and any(path.read_bytes() == b"partial" for path in pending)
    snapshot = {path: path.read_bytes() for path in pending}
    limits.stream(final, io.BytesIO(b"complete"), limit=100, expected_bytes=8)
    assert final.read_bytes() == b"complete"
    assert all(path.read_bytes() == raw for path, raw in snapshot.items())


def test_stream_rejects_oversize_and_incomplete_content_without_final(tmp_path):
    output = tmp_path / "out"
    limits = budget(output)
    with pytest.raises(ValueError, match=r"bound|budget|size|byte"):
        limits.stream(output / "too-large", io.BytesIO(b"12345"), limit=4)
    with pytest.raises(ValueError, match=r"length|size|byte|incomplete"):
        limits.stream(output / "short", io.BytesIO(b"123"), limit=9, expected_bytes=8)
    assert not (output / "too-large").exists()
    assert not (output / "short").exists()


def test_worker_budget_cannot_be_bypassed_between_operations(tmp_path):
    with pytest.raises(ValueError, match=r"wall|time|budget|bound"):
        budget(tmp_path / "out", worker_seconds=0).check()


def packet_inputs(vfr_source, tmp_path):
    output = tmp_path / "out"
    limits = budget(output)
    native = sources.native_clock(vfr_source, limits)
    clock_path = tmp_path / "clock.json"
    clock_path.write_text(json.dumps(native), encoding="utf-8")
    return output, limits, clock_path


def test_packet_deduplicates_images_only_and_preserves_pixels_and_unknowns(
    vfr_source, tmp_path
):
    output, limits, clock_path = packet_inputs(vfr_source, tmp_path)
    packet = sources.extract_packet(
        vfr_source,
        clock_path,
        sha(clock_path),
        sha(vfr_source),
        output,
        limits,
        "generated",
    )
    assert packet["case_count"] == 64
    assert packet["requested_context_memberships"] == 320
    assert len(packet["cases"]) == 64
    assert sum(len(case["context"]) for case in packet["cases"]) == 320
    assert len(packet["images"]) == 65
    assert len(list(output.rglob("*.png"))) == 65
    with av.open(str(vfr_source)) as container:
        original = list(container.decode(container.streams.video[0]))
    for index, frame in enumerate(original):
        identity = packet["images"][str(index)]
        assert identity["frame"] == index
        assert identity["pts"] == frame.pts
        assert identity["time_base"] == str(frame.time_base)
        assert identity["time_s"] == float(frame.pts * frame.time_base)
        assert identity["available"] is True
        image_path = output / identity["image"]["path"]
        assert sha(image_path) == identity["image"]["sha256"]
        with Image.open(image_path) as image:
            assert np.array_equal(np.asarray(image), frame.to_ndarray(format="rgb24"))
    before = copy.deepcopy(packet)
    template = sources.review_template(packet)
    assert packet == before
    assert len(template["cases"]) == 64
    for row in template["cases"]:
        assert row["visibility"] == row["difficulty"] == row["scene"] == "unknown"
        assert row["x"] is None and row["y"] is None and row["reviewed"] is False
    assert (
        template["eligibility"] == packet["eligibility"] == dict.fromkeys(FLAGS, False)
    )
    assert not any("visibility" in row for row in packet["cases"])
    original_hashes = {path: sha(path) for path in output.rglob("*.png")}
    with pytest.raises(FileExistsError):
        sources.extract_packet(
            vfr_source,
            clock_path,
            sha(clock_path),
            sha(vfr_source),
            output,
            limits,
            "generated",
        )
    assert {path: sha(path) for path in output.rglob("*.png")} == original_hashes


@pytest.mark.parametrize("changed", ["source", "clock"])
def test_changed_frozen_input_fails_before_any_packet_image(
    vfr_source, tmp_path, changed
):
    output, limits, clock_path = packet_inputs(vfr_source, tmp_path)
    source_sha, clock_sha = sha(vfr_source), sha(clock_path)
    target = vfr_source if changed == "source" else clock_path
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError, match=r"hash|changed"):
        sources.extract_packet(
            vfr_source, clock_path, clock_sha, source_sha, output, limits, "generated"
        )
    assert not list(output.rglob("*.png"))


def test_resealed_but_false_clock_cannot_change_native_identity(vfr_source, tmp_path):
    output, limits, clock_path = packet_inputs(vfr_source, tmp_path)
    native = json.loads(clock_path.read_text())
    native["frames"][0]["pts"] += 1
    clock_path.write_text(json.dumps(native), encoding="utf-8")
    with pytest.raises(ValueError, match=r"identity|changed"):
        sources.extract_packet(
            vfr_source,
            clock_path,
            sha(clock_path),
            sha(vfr_source),
            output,
            limits,
            "generated",
        )
    assert not list(output.rglob("*.png"))


def shared_setup(tmp_path, monkeypatch):
    from badminton import config
    from badminton.storage import Store

    shared = tmp_path / "data/processed"
    store = Store(shared)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", shared)
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    monkeypatch.setattr(
        sources,
        "load_inputs",
        lambda *_args: ({"sources": [{"id": "generated"}]}, {"limits": sources.LIMITS}),
    )
    monkeypatch.setattr(sources, "_freeze", lambda *_args: ({}, {}, "c" * 64))
    return store


def test_real_occupied_shared_store_blocks_before_downloader(tmp_path, monkeypatch):
    from badminton.storage import ConflictError

    store = shared_setup(tmp_path, monkeypatch)
    store.claim_job(
        {
            "id": "existing",
            "kind": "research",
            "video_id": None,
            "status": "running",
            "progress": 0,
        }
    )
    with patch.object(sources, "acquire_source") as acquire:
        with pytest.raises(ConflictError):
            sources.run_preparation(
                tmp_path,
                tmp_path / ".cache/out",
                sources_path=tmp_path / "sources",
                protocol_path=tmp_path / "protocol",
            )
        acquire.assert_not_called()
    assert [job["id"] for job in store.jobs()] == ["existing"]
    assert not (tmp_path / ".cache/out/admission.json").exists()
    assert not (tmp_path / ".cache/out/terminal.json").exists()


def test_failure_has_actual_running_job_process_and_terminal_proof(
    tmp_path, monkeypatch
):
    import os

    import psutil

    store = shared_setup(tmp_path, monkeypatch)
    output = tmp_path / ".cache/out"

    def fail_after_admission(*_args):
        admission = json.loads((output / "admission.json").read_text())
        process = psutil.Process()
        assert admission["process"]["pid"] == os.getpid()
        assert admission["process"]["creation_time"] == process.create_time()
        assert Path(admission["process"]["cwd"]) == Path.cwd()
        assert admission["process"]["command"]
        assert admission["context_sha256"] == "c" * 64
        matching = [job for job in store.jobs() if job["id"] == admission["job_id"]]
        assert len(matching) == 1 and matching[0]["status"] == "running"
        raise RuntimeError("generated acquisition failure")

    monkeypatch.setattr(sources, "acquire_source", fail_after_admission)
    with pytest.raises(RuntimeError, match=r"generated acquisition failure"):
        sources.run_preparation(
            tmp_path,
            output,
            sources_path=tmp_path / "sources",
            protocol_path=tmp_path / "protocol",
        )
    admission = json.loads((output / "admission.json").read_text())
    terminal = json.loads((output / "terminal.json").read_text())
    assert terminal["job_id"] == admission["job_id"]
    assert terminal["status"] == store.jobs()[0]["status"] == "failed"
    assert terminal["error_type"] == "RuntimeError"
    assert not (output / "result.json").exists()
    original = (output / "terminal.json").read_bytes()
    with patch.object(sources, "acquire_source") as acquire:
        with pytest.raises(ValueError, match=r"new|exclusive|restart"):
            sources.run_preparation(
                tmp_path,
                output,
                sources_path=tmp_path / "sources",
                protocol_path=tmp_path / "protocol",
            )
        acquire.assert_not_called()
    assert (output / "terminal.json").read_bytes() == original


def mocked_native_decode(monkeypatch, frames, *, interrupted=False):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from badminton import av_runtime

    stream = SimpleNamespace(codec_context=SimpleNamespace(thread_count=0))

    def decode(_stream):
        yield from frames
        if interrupted:
            raise OSError("generated unavailable final decode")

    container = SimpleNamespace(
        streams=SimpleNamespace(video=[stream], audio=[]), decode=decode
    )
    monkeypatch.setattr(sources, "_threaded", lambda: False)
    monkeypatch.setattr(av_runtime, "open_media", lambda _path: nullcontext(container))


def native_fixture_frames():
    from types import SimpleNamespace

    return [
        SimpleNamespace(
            pts=index * 40,
            time_base=Fraction(1, 1000),
            rotation=0,
            side_data={},
            width=64,
            height=32,
            is_corrupt=False,
            to_image=lambda: Image.new("RGB", (64, 32), (30, 80, 100)),
        )
        for index in range(65)
    ]


def test_missing_nonmonotonic_and_corrupt_rows_remain_explicit_packet_members(
    tmp_path, monkeypatch
):
    source = tmp_path / "generated-input.bin"
    source.write_bytes(b"generated native decoder fixture")
    frames = native_fixture_frames()
    frames[17].pts = None
    frames[18].is_corrupt = True
    frames[20].pts = frames[19].pts
    mocked_native_decode(monkeypatch, frames)
    output = tmp_path / "out"
    limits = budget(output)
    native = sources.native_clock(source, limits)
    assert native["complete"] is True and native["frame_count"] == 65
    assert set(native["issues"]) >= {
        "unavailable_native_time",
        "corrupt_native_frame",
        "nonincreasing_native_time",
    }
    assert native["frames"][17]["pts"] is None
    assert native["frames"][17]["time_s"] is None
    assert native["frames"][18]["corrupt"] is True
    assert native["frames"][20]["pts"] == native["frames"][19]["pts"]
    clock_path = tmp_path / "clock.json"
    clock_path.write_text(json.dumps(native), encoding="utf-8")
    packet = sources.extract_packet(
        source, clock_path, sha(clock_path), sha(source), output, limits, "generated"
    )
    assert packet["case_count"] == 64 and packet["requested_context_memberships"] == 320
    assert len(packet["images"]) == 65
    assert packet["images"]["17"]["time_s"] is None
    assert packet["images"]["18"]["available"] is False
    assert packet["images"]["18"]["image"] is None
    assert len(list(output.rglob("*.png"))) == 64
    assert any(m["frame"] == 18 for c in packet["cases"] for m in c["context"])


def test_decode_failure_retains_prefix_but_cannot_claim_complete_stream(
    tmp_path, monkeypatch
):
    source = tmp_path / "generated-input.bin"
    source.write_bytes(b"generated decoder fixture")
    mocked_native_decode(monkeypatch, native_fixture_frames(), interrupted=True)
    native = sources.native_clock(source, budget(tmp_path / "out"))
    assert native["frame_count"] == 65
    assert native["complete"] is False
    assert "decode_unavailable:OSError" in native["issues"]
    with pytest.raises(ValueError, match=r"unavailable|complete"):
        sources.sample_memberships(native)


@pytest.mark.parametrize("bad_id", ["../outside", "nested/path", "", "a\\b"])
def test_packet_source_identifier_cannot_escape_output(vfr_source, tmp_path, bad_id):
    output, limits, clock_path = packet_inputs(vfr_source, tmp_path)
    with pytest.raises(ValueError, match=r"identifier|source"):
        sources.extract_packet(
            vfr_source,
            clock_path,
            sha(clock_path),
            sha(vfr_source),
            output,
            limits,
            bad_id,
        )
    assert not list(output.rglob("*.png"))


def test_combined_download_budget_includes_failed_stream_bytes(tmp_path):
    output = tmp_path / "out"
    limits = budget(output, download_bytes=8)
    with pytest.raises(ValueError, match=r"byte|count|declaration"):
        limits.stream(
            output / "failed",
            io.BytesIO(b"1234"),
            limit=8,
            expected_bytes=5,
            download=True,
        )
    assert limits.downloaded_bytes == 4
    with pytest.raises(ValueError, match=r"download|budget"):
        limits.stream(output / "second", io.BytesIO(b"12345"), limit=8, download=True)
    assert not (output / "failed").exists()
    assert not (output / "second").exists()
    assert any(
        path.read_bytes() == b"1234" for path in output.rglob("*") if path.is_file()
    )


def test_clock_mutated_during_extraction_is_not_accepted(
    vfr_source, tmp_path, monkeypatch
):
    output, limits, clock_path = packet_inputs(vfr_source, tmp_path)
    source_sha, clock_sha = sha(vfr_source), sha(clock_path)
    publish = limits.publish
    changed = False

    def mutate_after_image(path, raw):
        nonlocal changed
        result = publish(path, raw)
        if Path(path).suffix == ".png" and not changed:
            clock_path.write_bytes(clock_path.read_bytes() + b" ")
            changed = True
        return result

    monkeypatch.setattr(limits, "publish", mutate_after_image)
    with pytest.raises(ValueError, match=r"changed"):
        sources.extract_packet(
            vfr_source, clock_path, clock_sha, source_sha, output, limits, "generated"
        )
    assert changed and list(output.rglob("*.png"))
    assert not (output / "result.json").exists()


def test_portable_manifests_freeze_sources_format_selection_and_false_eligibility():
    root = Path(__file__).resolve().parents[1]
    declaration, protocol = sources.load_inputs(
        root / "data/manifests/shuttle_review_sources_v1.json",
        root / "data/manifests/shuttle_review_packet_protocol_v1.json",
    )
    assert {row["id"] for row in declaration["sources"]} == {
        "go2uajSiBnE",
        "H1setLK1tig",
    }
    assert {row["category"] for row in declaration["sources"]} == {"singles", "doubles"}
    assert protocol["centers_per_source"] == 64
    assert protocol["context_offsets"] == [-2, -1, 0, 1, 2]
    assert protocol["eligibility"] == dict.fromkeys(FLAGS, False)
    assert all(row["format_id"] == "137" for row in declaration["sources"])
    assert all(
        row["eligibility"] == dict.fromkeys(FLAGS, False)
        for row in declaration["sources"]
    )


class FakeResponse(io.BytesIO):
    def __init__(self, raw, status, headers):
        super().__init__(raw)
        self.status = status
        self.headers = headers


def fake_request(url, *, headers):
    from types import SimpleNamespace

    return SimpleNamespace(url=url, headers=headers)


def read_stream(stream, chunk_size=1024 * 1024):
    chunks = []
    while chunk := stream.read(chunk_size):
        chunks.append(chunk)
    return b"".join(chunks)


def test_range_reader_joins_contiguous_ranges_once_and_closes_responses():
    from types import SimpleNamespace

    body = b"a" * (10 * 1024**2) + b"last-segment"
    requests, responses = [], []

    def fetch(request):
        requests.append(request)
        start, end = map(
            int, request.headers["Range"].removeprefix("bytes=").split("-")
        )
        response = FakeResponse(
            body[start : end + 1],
            206,
            {
                "Content-Range": f"bytes {start}-{end}/{len(body)}",
                "Content-Length": str(end - start + 1),
            },
        )
        responses.append(response)
        return response

    stream = sources._RangeStream(
        SimpleNamespace(urlopen=fetch),
        fake_request,
        "https://generated.invalid/video",
        {"X-Test": "ok"},
        len(body),
    )
    try:
        assert read_stream(stream) == body
        assert [request.headers["Range"] for request in requests] == [
            f"bytes=0-{10 * 1024**2 - 1}",
            f"bytes={10 * 1024**2}-{len(body) - 1}",
        ]
        assert all(request.headers["X-Test"] == "ok" for request in requests)
        assert stream.read(1) == b""
    finally:
        stream.close()
    assert all(response.closed for response in responses)


@pytest.mark.parametrize(
    "status,headers,raw",
    [
        (206, {"Content-Range": "bytes 1-5/5", "Content-Length": "5"}, b"12345"),
        (206, {"Content-Range": "bytes 0-4/6", "Content-Length": "5"}, b"12345"),
        (206, {"Content-Range": "bytes 0-3/5", "Content-Length": "4"}, b"1234"),
        (206, {"Content-Range": "bytes 0-4/5", "Content-Length": "4"}, b"12345"),
        (206, {"Content-Range": "bytes 0-4/5", "Content-Length": "5"}, b"123"),
        (206, {"Content-Range": "bytes 0-4/5", "Content-Length": "5"}, b"123456"),
        (403, {"Content-Length": "5"}, b"12345"),
    ],
)
def test_range_reader_rejects_wrong_identity_length_truncated_and_excess(
    status, headers, raw
):
    from types import SimpleNamespace

    response = FakeResponse(raw, status, headers)
    stream = sources._RangeStream(
        SimpleNamespace(urlopen=lambda _request: response),
        fake_request,
        "https://generated.invalid/video",
        {},
        5,
    )
    try:
        with pytest.raises(ValueError, match=r"range|length|truncated|excess"):
            read_stream(stream, 2)
    finally:
        stream.close()
    assert response.closed


def test_server_may_ignore_initial_range_only_for_complete_200_body():
    from types import SimpleNamespace

    body = b"a" * (10 * 1024**2 + 1)
    response = FakeResponse(body, 200, {"Content-Length": str(len(body))})
    calls = []

    def fetch(request):
        calls.append(request)
        return response

    stream = sources._RangeStream(
        SimpleNamespace(urlopen=fetch),
        fake_request,
        "https://generated.invalid/video",
        {},
        len(body),
    )
    try:
        assert read_stream(stream) == body
        assert len(calls) == 1
    finally:
        stream.close()
    assert response.closed


def test_200_response_cannot_restart_source_at_later_range():
    from types import SimpleNamespace

    first_size = 10 * 1024**2
    size = first_size + 5
    responses = [
        FakeResponse(
            b"a" * first_size,
            206,
            {
                "Content-Range": f"bytes 0-{first_size - 1}/{size}",
                "Content-Length": str(first_size),
            },
        ),
        FakeResponse(b"12345", 200, {"Content-Length": "5"}),
    ]
    pending = iter(responses)
    stream = sources._RangeStream(
        SimpleNamespace(urlopen=lambda _request: next(pending)),
        fake_request,
        "https://generated.invalid/video",
        {},
        size,
    )
    try:
        with pytest.raises(ValueError, match=r"identity"):
            read_stream(stream)
    finally:
        stream.close()
    assert all(response.closed for response in responses)


def metadata_for_source():
    return {
        "id": "go2uajSiBnE",
        "channel_id": sources.CHANNEL,
        "format_id": "137",
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "acodec": "none",
        "vcodec": "avc1.640028",
        "availability": "public",
        "live_status": "not_live",
        "protocol": "https",
        "filesize": 5,
        "url": "https://generated.invalid/video?delivery=ephemeral",
        "http_headers": {"X-Private-Transport": "synthetic-value"},
    }


def fake_youtube(monkeypatch, metadata, *, fetch):
    import yt_dlp

    options_seen = []

    class FakeDownloader:
        def __init__(self, options):
            options_seen.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, *, download):
            assert url == "https://www.youtube.com/watch?v=go2uajSiBnE"
            assert download is False
            return copy.deepcopy(metadata)

        def urlopen(self, request):
            return fetch(request)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeDownloader)
    return options_seen


@pytest.mark.parametrize(
    "field,value",
    [
        ("format_id", "136"),
        ("channel_id", "other"),
        ("acodec", "aac"),
        ("availability", "private"),
    ],
)
def test_changed_source_metadata_never_requests_media(
    tmp_path, monkeypatch, field, value
):
    metadata = metadata_for_source()
    metadata[field] = value
    requests = []
    fake_youtube(monkeypatch, metadata, fetch=requests.append)
    declaration = {
        "id": "go2uajSiBnE",
        "url": "https://www.youtube.com/watch?v=go2uajSiBnE",
    }
    output = tmp_path / "out"
    with pytest.raises(ValueError, match=r"unavailable|changed"):
        sources.acquire_source(declaration, output, budget(output))
    assert requests == []
    assert not list(output.rglob("source.mp4"))
    assert list(output.rglob("returned-metadata.json"))


def test_successful_acquisition_retains_safe_metadata_and_complete_selected_bytes(
    tmp_path, monkeypatch
):
    metadata = metadata_for_source()
    response = FakeResponse(b"12345", 200, {"Content-Length": "5"})
    requests = []

    def fetch(request):
        requests.append(request)
        return response

    options_seen = fake_youtube(monkeypatch, metadata, fetch=fetch)
    declaration = {
        "id": "go2uajSiBnE",
        "url": "https://www.youtube.com/watch?v=go2uajSiBnE",
    }
    output = tmp_path / "out"
    limits = budget(output)
    path, seal = sources.acquire_source(declaration, output, limits)
    assert path.read_bytes() == b"12345"
    assert seal == {"bytes": 5, "sha256": sha(path)}
    assert limits.downloaded_bytes == 5
    assert len(requests) == 1 and response.closed
    options = options_seen[0]
    assert options["format"] == "137" and options["skip_download"] is True
    assert options["retries"] == options["extractor_retries"] == 0
    assert not set(options) & {
        "cookiefile",
        "cookiesfrombrowser",
        "username",
        "password",
    }
    for receipt in output.rglob("*.json"):
        raw = receipt.read_text()
        assert "delivery=ephemeral" not in raw and "X-Private-Transport" not in raw
        record = json.loads(raw)
        safe = record.get("metadata", record)
        assert safe["id"] == "go2uajSiBnE" and safe["format_id"] == "137"
        assert "url" not in safe and "http_headers" not in safe


def test_unsupported_orientation_is_retained_as_unavailable_without_dropping_rows(
    tmp_path, monkeypatch
):
    source = tmp_path / "native-fixture"
    source.write_bytes(b"generated decoder fixture")
    frames = native_fixture_frames()
    frames[18].rotation = 45
    mocked_native_decode(monkeypatch, frames)
    limits = budget(tmp_path / "out")
    native = sources.native_clock(source, limits)
    assert native["frame_count"] == 65 and native["complete"] is True
    invalid = native["frames"][18]
    assert invalid["rotation"] is None and invalid["display_size"] is None
    assert invalid["orientation_error"]
    clock_path = tmp_path / "clock.json"
    clock_path.write_text(json.dumps(native), encoding="utf-8")
    packet = sources.extract_packet(
        source,
        clock_path,
        sha(clock_path),
        sha(source),
        tmp_path / "out",
        limits,
        "generated",
    )
    assert len(packet["images"]) == 65
    assert packet["images"]["18"]["available"] is False
    assert packet["images"]["18"]["image"] is None
    assert packet["requested_context_memberships"] == 320
