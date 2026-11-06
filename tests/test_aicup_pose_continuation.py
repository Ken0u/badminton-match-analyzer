"""Generated native storage controls; never open private media or fit a model."""

import copy
import json
import zlib
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from badminton import aicup_pose_continuation as continuation
from badminton import aicup_pose_scaling as scaling
from test_aicup_pose_scaling import generated_frame


@pytest.fixture(autouse=True)
def generous_resources(monkeypatch):
    import psutil

    monkeypatch.setattr(
        psutil, "virtual_memory", lambda: SimpleNamespace(available=8 * 1024**3)
    )
    monkeypatch.setattr(
        psutil, "disk_usage", lambda _: SimpleNamespace(free=32 * 1024**3)
    )


@pytest.mark.parametrize("format", continuation.PROTOCOL["frame_storage"]["formats"])
@pytest.mark.parametrize("color", [(0, 0), (1, 1), (5, 2)])
def test_spool_repeated_out_of_order_reads_keep_exact_native_pixels_and_clocks(
    tmp_path, format, color
):
    frames = [generated_frame(format, *color) for _ in range(4)]
    for i, frame in enumerate(frames):
        frame.pts = 1001 + i * 1003
        frame.time_base = Fraction(1, 30000)
    times = [0.0, 0.031, 0.081, 0.16]
    spool = continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)
    for i, frame in enumerate(frames):
        spool.append(i, times[i], frame)
    spool.seal()
    first = spool.frame(2)[2]
    assert spool.frame(2)[2] is first
    for index in [3, 0, 2, 1, 3, 0]:
        ordinal, timestamp, restored = spool.frame(index)
        assert (ordinal, timestamp) == (index, times[index])
        assert (restored.pts, restored.time_base) == (
            frames[index].pts,
            frames[index].time_base,
        )
        assert (restored.colorspace, restored.color_range) == color
        assert restored.format.name == frames[index].format.name
        assert len(spool.live) <= 2
        for layout in ("rgb24", "bgr24"):
            np.testing.assert_array_equal(
                restored.to_ndarray(format=layout),
                frames[index].to_ndarray(format=layout),
            )
    spool.close()
    spool.cleanup()
    assert not spool.directory.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "excess",
        "short",
        "truncated",
        "trailing",
        "concatenated",
        "hash",
        "shape",
        "dtype",
        "plane",
        "huge",
    ],
)
def test_record_corruption_and_expansion_are_fenced_before_reconstruction(
    monkeypatch, mutation
):
    record = scaling.pack_frame(
        generated_frame("bgr0" if mutation == "plane" else "rgb24")
    )
    if mutation == "excess":
        raw = b"x" * (64 * 96 * 3 + 1)
        record["compressed_pixels"] = zlib.compress(raw)
    elif mutation == "short":
        record["compressed_pixels"] = zlib.compress(b"x")
    elif mutation == "truncated":
        record["compressed_pixels"] = record["compressed_pixels"][:-1]
    elif mutation == "trailing":
        record["compressed_pixels"] += b"ignored data"
    elif mutation == "concatenated":
        record["compressed_pixels"] += zlib.compress(b"other stream")
    elif mutation == "hash":
        record["raw_sha256"] = "0" * 64
    elif mutation == "shape":
        record["shape"] = [True, 96, 3]
    elif mutation == "dtype":
        record["dtype"] = "object"
    elif mutation == "plane":
        record["planes"][0]["line_size"] += 1
    else:
        record["shape"] = [2**63, 2**63, 3]
    monkeypatch.setattr(
        scaling,
        "unpack_frame",
        lambda _: pytest.fail("Reconstruction before validation"),
    )
    with pytest.raises((ValueError, zlib.error)):
        continuation.bounded_record(record)


def test_high_expansion_is_limited_before_full_allocation(monkeypatch):
    record = scaling.pack_frame(generated_frame("rgb24"))
    record["compressed_pixels"] = zlib.compress(b"x" * (2 * 1024**2))
    original = zlib.decompressobj
    limits = []

    class Observed:
        def __init__(self):
            self.inner = original()

        def decompress(self, data, max_length):
            limits.append(max_length)
            return self.inner.decompress(data, max_length)

        def __getattr__(self, key):
            return getattr(self.inner, key)

    monkeypatch.setattr(zlib, "decompressobj", Observed)
    with pytest.raises(ValueError, match="expansion"):
        continuation.bounded_record(record)
    assert limits == [64 * 96 * 3 + 1]


@pytest.mark.parametrize(
    "mutation", ["truncate", "extend", "pixels", "manifest", "big_manifest"]
)
def test_changed_disk_records_are_rejected_even_with_warm_lru(tmp_path, mutation):
    spool = continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)
    spool.append(0, 0.0, generated_frame())
    spool.seal()
    spool.frame(0)
    path = spool.path
    if mutation == "manifest":
        (spool.directory / "manifest.json").write_bytes(b"{}")
    elif mutation == "big_manifest":
        (spool.directory / "manifest.json").write_bytes(b"x" * (1024**2 + 1))
    else:
        raw = path.read_bytes()
        if mutation == "truncate":
            raw = raw[:-1]
        elif mutation == "extend":
            raw += b"x"
        else:
            raw = raw[:-1] + bytes([raw[-1] ^ 1])
        with path.open("r+b") as stream:
            stream.write(raw)
            stream.truncate()
    with pytest.raises(ValueError, match="Spool"):
        spool.frame(0)
    spool.close()
    assert spool.directory.exists()


@pytest.mark.parametrize("failure", ["body", "source", "decode", "clock"])
def test_decoder_failures_restore_adapters_and_preserve_spool(
    tmp_path, monkeypatch, failure
):
    from badminton import court_detection, tracking, video

    video_doc = {"id": "generated", "frame_count": 3}
    times = [0.0, 0.04, 0.12]
    calls = []
    old_tracking, old_court = tracking.iter_frames, court_detection.iter_frames

    def decoded(*_):
        for index in range(3):
            if failure == "decode" and index == 1:
                raise ValueError("decode failed")
            calls.append(index)
            yield (
                index,
                times[index] + (0.1 if failure == "clock" else 0),
                generated_frame(),
            )

    def resolve(*_):
        if failure == "source":
            raise ValueError("source changed")

    monkeypatch.setattr(video, "iter_frames", decoded)
    monkeypatch.setattr(video, "resolve_source", resolve)
    with pytest.raises(ValueError):
        with continuation.decode_spool(
            video_doc,
            tmp_path,
            times,
            lambda _: None,
            tmp_path / "spool",
            tmp_path,
            lambda **_: None,
        ):
            if failure == "body":
                raise ValueError("body failed")
    assert (
        tracking.iter_frames is old_tracking
        and court_detection.iter_frames is old_court
    )
    assert (tmp_path / "spool/pixels.bin").is_file()
    assert calls == ([0] if failure in ("decode", "clock") else [0, 1, 2])


def test_exact_decoded_coverage_and_cleanup_without_source_replay(
    tmp_path, monkeypatch
):
    from badminton import court_detection, tracking, video

    video_doc, times = {"id": "generated", "frame_count": 3}, [0.0, 0.04, 0.11]
    visits, progress, checks = [], [], []

    def decoded(*_):
        for index in range(3):
            visits.append(index)
            yield index, times[index], generated_frame()

    monkeypatch.setattr(video, "iter_frames", decoded)
    monkeypatch.setattr(video, "resolve_source", lambda *_: checks.append("source"))
    with continuation.decode_spool(
        video_doc,
        tmp_path,
        times,
        progress.append,
        tmp_path / "spool",
        tmp_path,
        lambda **_: None,
    ) as count:
        assert count == 3
        assert [
            r[:2] for r in tracking.iter_frames(video_doc, tmp_path, times, 0, 3)
        ] == list(enumerate(times))
        assert (
            next(iter(court_detection.iter_frames(video_doc, tmp_path, times, 2, 3)))[0]
            == 2
        )
        with pytest.raises(ValueError):
            list(tracking.iter_frames(video_doc, tmp_path, times, True, 3))
    assert visits == [0, 1, 2] and progress == [1, 2, 3] and checks == ["source"]
    assert not (tmp_path / "spool").exists()


def test_memory_and_disk_guards_refuse_before_packing(tmp_path, monkeypatch):
    import psutil

    spool = continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)
    monkeypatch.setattr(
        scaling,
        "pack_frame",
        lambda _: pytest.fail("Packing before resource admission"),
    )
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=0))
    with pytest.raises(ValueError, match="RAM"):
        spool.append(0, 0.0, generated_frame())
    monkeypatch.setattr(
        psutil, "virtual_memory", lambda: SimpleNamespace(available=8 * 1024**3)
    )
    monkeypatch.setattr(psutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="disk reserve"):
        spool.append(0, 0.0, generated_frame())
    spool.close()


def test_cleanup_preserves_unexpected_files_and_changed_records(tmp_path):
    spool = continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)
    spool.append(0, 0.0, generated_frame())
    spool.seal()
    spool.close()
    extra = spool.directory / "foreign.txt"
    extra.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected spool"):
        spool.cleanup()
    assert extra.read_text() == "preserve" and spool.path.exists()


def test_public_fixed_protocol_matches_module():
    root = Path(continuation.__file__).resolve().parents[2]
    assert (
        json.loads(
            (
                root / "data/manifests/aicup_pose_continuation_protocol_v1.json"
            ).read_bytes()
        )
        == continuation.PROTOCOL
    )


def test_spool_cannot_escape_its_run_or_reuse_old_directory(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        continuation.FrameSpool(tmp_path.parent / "escape", tmp_path, lambda **_: None)
    spool = continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)
    spool.close()
    with pytest.raises(FileExistsError):
        continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)


def test_metadata_size_is_validated_before_any_decompress(monkeypatch):
    record = scaling.pack_frame(generated_frame())
    record = copy.deepcopy(record)
    record["shape"] = [2**63, 2**63]
    monkeypatch.setattr(
        zlib, "decompressobj", lambda: pytest.fail("Allocation before size validation")
    )
    with pytest.raises(ValueError):
        continuation.bounded_record(record)


def test_manifest_bytes_are_included_in_scratch_reservation(tmp_path, monkeypatch):
    spool = continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)
    spool.append(0, 0.0, generated_frame())
    monkeypatch.setitem(continuation.PROTOCOL["limits"], "scratch_bytes", spool.size)
    with pytest.raises(ValueError, match="scratch cap"):
        spool.seal()
    spool.close()
    assert spool.path.exists() and not (spool.directory / "manifest.json").exists()


def test_record_scratch_denial_precedes_packing(tmp_path, monkeypatch):
    spool = continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)
    monkeypatch.setitem(continuation.PROTOCOL["limits"], "scratch_bytes", 0)
    monkeypatch.setattr(
        scaling, "pack_frame", lambda _: pytest.fail("Packing before scratch admission")
    )
    with pytest.raises(ValueError, match="scratch cap"):
        spool.append(0, 0.0, generated_frame())
    spool.close()


def test_cleanup_checks_payload_changes_after_readers_close(tmp_path):
    spool = continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)
    spool.append(0, 0.0, generated_frame())
    spool.seal()
    spool.close()
    with spool.path.open("r+b") as stream:
        stream.seek(-1, 2)
        old = stream.read(1)
        stream.seek(-1, 2)
        stream.write(bytes([old[0] ^ 1]))
    with pytest.raises(ValueError, match="record before cleanup"):
        spool.cleanup()
    assert spool.path.exists()


def test_failure_to_write_manifest_preserves_records(tmp_path, monkeypatch):
    spool = continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)
    spool.append(0, 0.0, generated_frame())
    original = Path.open

    def denied(path, *args, **kwargs):
        if path.name == "manifest.json":
            raise OSError("generated full disk")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(OSError, match="full disk"):
        spool.seal()
    spool.close()
    assert spool.path.exists() and not spool.sealed
