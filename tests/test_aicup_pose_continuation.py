"""Generated native storage controls; never open private media or fit a model."""

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import zlib
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import psutil
import pytest
from badminton import aicup_pose_continuation as continuation
from badminton import aicup_pose_scaling as scaling
from test_aicup_pose_scaling import (  # noqa: F401
    cohort_case,
    combined_case,
    generated_frame,
    metadata_operation,
    run_case,
)

NATIVE_DISK_USAGE = psutil.disk_usage


@pytest.mark.parametrize("target", ["spool", "retained", "scratch"])
def test_disk_guards_use_real_native_api_with_filesystem_text(
    tmp_path, monkeypatch, target
):
    """Permissive resource doubles must not conceal the Windows API boundary."""
    calls = []

    def disk_usage(path):
        calls.append(path)
        result = NATIVE_DISK_USAGE(path)
        # Enforce Windows' boundary even on hosts whose psutil accepts PathLike.
        assert type(path) is str
        return result

    monkeypatch.setattr(psutil, "disk_usage", disk_usage)
    monkeypatch.setitem(continuation.PROTOCOL["limits"], "minimum_disk_free_bytes", 0)
    output = tmp_path / "run"
    output.mkdir()
    if target == "spool":
        spool = continuation.FrameSpool(output / "spool", output, lambda **_: None)
        try:
            spool.guard()
        finally:
            spool.close()
    elif target == "retained":
        original = {
            name: str(tmp_path / "original" / name)
            for name in (
                "prepared",
                "native",
                "audit",
                "control",
                "output",
                "prospective_directory",
                "actor_prospective",
                "control_prospective",
            )
        }
        continuation.disk_budget(
            {
                "workspace": str(tmp_path),
                "original": original,
                "prospective_directory": str(tmp_path / "freeze"),
                "output": str(output),
            }
        )
    else:
        # Exercise the scratch boundary independently of retained-disk admission.
        budget = continuation.OutputBudget.__new__(continuation.OutputBudget)
        budget.output, budget.retained, budget.journal_reserve = output, 0, 0
        budget.scratch()
    assert calls


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


@pytest.mark.parametrize("format", continuation.PROTOCOL["frame_storage"]["formats"])
def test_rotated_720p_display_keeps_exact_pixels_without_larger_byte_budget(
    tmp_path, format
):
    import av

    # A native 1280x720 source displayed after a quarter turn is 720x1280.
    pixels = np.zeros((1280, 720, 3), np.uint8)
    pixels[::3, ::5] = (29, 97, 173)
    frame = av.VideoFrame.from_ndarray(pixels, "rgb24").reformat(format=format)
    frame.pts, frame.time_base = 9009, Fraction(1, 30000)
    spool = continuation.FrameSpool(tmp_path / "spool", tmp_path, lambda **_: None)
    try:
        spool.append(0, 0.0, frame)
        spool.seal()
        restored = spool.frame(0)[2]
        assert (restored.width, restored.height) == (720, 1280)
        assert restored.pts == frame.pts and restored.time_base == frame.time_base
        for layout in ("rgb24", "bgr24"):
            np.testing.assert_array_equal(
                restored.to_ndarray(format=layout), frame.to_ndarray(format=layout)
            )
    finally:
        spool.close()
    spool.cleanup()


@pytest.fixture
def science_observation(monkeypatch):
    spec = {
        "resources": ["gpu:windows-primary", "cpu:windows-training"],
        "paths": ["docs/AICUP_POSE_SCALING_REPORT.md"],
        "dependencies": ["391", "393", str(continuation.PROTOCOL["code_task"])],
    }
    spec_hash = hashlib.sha256(continuation.encoded(spec)).hexdigest()
    monkeypatch.setitem(continuation.PROTOCOL, "spec_hash", spec_hash)
    claim = {
        "actor": "Ken0u",
        "host_id": "MSI",
        "session_id": "generated",
        "epoch": 1,
        "spec_hash": spec_hash,
        "branch": f"codex/issue-{continuation.PROTOCOL['task']}-generated",
        "baseline_sha": "a" * 40,
        "granted_at": 1000,
        "expires_at": 11800,
    }
    return {
        "at": 1100,
        "task": {
            "status": "running",
            "epoch": 1,
            "spec_hash": spec_hash,
            "claim": claim,
            "spec": spec,
        },
        "grant_receipt": {
            "status": "granted",
            "verb": "next",
            "task_id": str(continuation.PROTOCOL["task"]),
            "epoch": 1,
            "actor": "Ken0u",
            "at": 1000,
            "claim": copy.deepcopy(claim),
        },
        "code_task": {
            "status": "done",
            "delivery_pending": False,
            "merge_sha": "a" * 40,
            "candidate_run": "https://github.com/Ken0u/badminton-match-analyzer/actions/runs/123",
        },
    }


def test_science_grant_binds_exact_source_and_preserves_clock_on_renewal(
    science_observation,
):
    binding = continuation.live_grant(science_observation, "a" * 40, now=1200)
    science_observation["task"]["claim"]["expires_at"] += 1000
    assert continuation.live_grant(science_observation, "a" * 40, now=1200) == binding
    assert binding["granted_at"] == 1000 and "expires_at" not in binding


@pytest.mark.parametrize(
    "mutation",
    [
        "code_only",
        "pending",
        "expired",
        "stale",
        "future",
        "changed_spec",
        "missing_receipt",
        "source",
        "actor",
        "session",
        "epoch",
        "history",
        "incomplete_delivery",
        "failed_delivery",
        "unverified_main",
        "old_window",
        "changed_original_grant",
        "future_grant",
        "missing_field",
        "code_scope",
    ],
)
def test_science_admission_refuses_wrong_or_stale_controller_evidence(
    science_observation,
    mutation,
    monkeypatch,
):
    case = science_observation
    now, source = 1200, "a" * 40
    if mutation == "code_only":
        case["grant_receipt"]["task_id"] = str(continuation.PROTOCOL["code_task"])
    elif mutation == "pending":
        case["task"]["status"] = "ready"
    elif mutation == "expired":
        case["task"]["claim"]["expires_at"] = now
    elif mutation == "stale":
        case["at"] = now - 301
    elif mutation == "future":
        case["at"] = now + 1
    elif mutation == "changed_spec":
        case["task"]["spec"]["extra"] = "different"
    elif mutation == "missing_receipt":
        case["grant_receipt"] = {"status": "pending"}
    elif mutation == "source":
        source = "b" * 40
    elif mutation in ("actor", "session", "epoch"):
        key = {"actor": "actor", "session": "session_id", "epoch": "epoch"}[mutation]
        case["task"]["claim"][key] = 2 if key == "epoch" else "different"
    elif mutation == "history":
        case["task"]["history"] = [{"claim": {"granted_at": 0}}]
    elif mutation == "incomplete_delivery":
        case["code_task"]["delivery_pending"] = True
    elif mutation == "failed_delivery":
        case["code_task"]["delivery_error"] = "failed"
    elif mutation == "unverified_main":
        case["code_task"]["status"] = "verifying_main"
    elif mutation == "old_window":
        now = 1000 + continuation.PROTOCOL["limits"]["task_seconds"]
        case["at"] = now
        case["task"]["claim"]["expires_at"] = now + 1000
    elif mutation == "changed_original_grant":
        case["grant_receipt"]["claim"]["granted_at"] -= 1
    elif mutation == "future_grant":
        case["task"]["claim"]["granted_at"] = now + 1
    elif mutation == "missing_field":
        del case["task"]["claim"]["baseline_sha"]
    elif mutation == "code_scope":
        case["task"]["spec"]["resources"] = []
        changed = hashlib.sha256(continuation.encoded(case["task"]["spec"])).hexdigest()
        monkeypatch.setitem(continuation.PROTOCOL, "spec_hash", changed)
        case["task"]["spec_hash"] = changed
        case["task"]["claim"]["spec_hash"] = changed
        case["grant_receipt"]["claim"]["spec_hash"] = changed
    with pytest.raises(ValueError):
        continuation.live_grant(case, source, now=now)


def test_operation_windows_do_not_reset_with_later_outputs_or_lease_updates():
    assert continuation.operation_deadline(1000, 2000, now=2000) == 45200
    assert continuation.operation_deadline(1000, 30000, now=30000) == 58600
    with pytest.raises(ValueError, match="Expired"):
        continuation.operation_deadline(1000, 2000, now=45200)
    with pytest.raises(ValueError, match="headroom"):
        continuation.operation_deadline(1000, 2000, now=2000, forecast=40000)
    for invalid in (True, float("nan"), float("inf"), "1000"):
        with pytest.raises(ValueError):
            continuation.operation_deadline(invalid, 2000, now=2000)


def test_stage_journal_retains_uncertainty_and_original_attempt_counts(tmp_path):
    path = tmp_path / "stages.jsonl"
    ledger = continuation.StageLedger(path)
    ledger.begin("decoded", "generated:1", 7)
    ledger.advance(7)
    ledger.finish()
    ledger.begin("observed", "generated:1", 7)
    ledger.advance(3)
    summary = ledger.summary()
    ledger.close()
    assert summary["exact"] == {"decoded": 7, "observed": None, "real_fits": 0}
    assert summary["lower"]["observed"] == 3
    assert summary["upper"]["observed"] == 7
    assert summary["cumulative"] == {
        "decoded_lower": 6509,
        "decoded_upper": 6509,
        "observed_lower": 2203,
        "observed_upper": 3258,
        "observed_exact": None,
        "real_fits_consumed": 0,
    }
    previous = "0" * 64
    for index, raw in enumerate(path.read_bytes().splitlines()):
        event = json.loads(raw)
        assert event["previous"] == previous and event["sequence"] == index
        previous = hashlib.sha256(raw).hexdigest()
    with pytest.raises(FileExistsError):
        continuation.StageLedger(path)


def test_started_fit_is_consumed_even_if_no_checkpoint_returns(tmp_path):
    ledger = continuation.StageLedger(tmp_path / "stages.jsonl")
    try:
        ledger.begin("real_fits", "candidate", 1)
        assert ledger.summary()["exact"]["real_fits"] == 1
        assert ledger.summary()["cumulative"]["real_fits_consumed"] == 1
        with pytest.raises(ValueError, match="incomplete"):
            ledger.begin("real_fits", "retry", 1)
        ledger.advance(1)
        ledger.finish()
        with pytest.raises(ValueError, match="cap"):
            ledger.begin("real_fits", "retry", 1)
    finally:
        ledger.close()


def test_ledger_rejects_unfinished_or_excess_progress(tmp_path):
    ledger = continuation.StageLedger(tmp_path / "stages.jsonl")
    try:
        ledger.begin("decoded", "generated:1", 3)
        with pytest.raises(ValueError, match="Incomplete"):
            ledger.finish()
        for invalid in (0, -1, 4, True):
            with pytest.raises(ValueError):
                ledger.advance(invalid)
        ledger.advance(2)
        with pytest.raises(ValueError):
            ledger.advance(1)
    finally:
        ledger.close()


def test_metadata_cost_covers_all_remaining_frames_without_certifying_formats():
    # This is a generated structural ledger, not a reading of private sources.
    counts = [1051, 1416] + [344] * 394 + [518, 476]
    assert len(counts) == 398 and sum(counts) == 138997
    clocks = {
        str(i): {"shape": [1280, 720], "decoded_frames": value}
        for i, value in enumerate(counts)
    }
    assert continuation.metadata_cost(clocks, "0") == {
        "clips": 398,
        "frames": 138997,
        "decode_visits": 276943,
        "maximum_scratch_bytes": 7424966656,
        "native_format_or_compression_certified": False,
    }
    del clocks["397"]
    with pytest.raises(ValueError, match="denominator"):
        continuation.metadata_cost(clocks, "0")


@pytest.mark.parametrize("change", ["partial", "hash", "truncated", "order"])
def test_read_only_stage_verification_preserves_partial_or_rejects_corruption(
    tmp_path, change
):
    path = tmp_path / "stages.jsonl"
    ledger = continuation.StageLedger(path)
    ledger.begin("observed", "generated:1", 9)
    ledger.advance(4)
    ledger.close()
    original = path.read_bytes()
    if change == "partial":
        verified = continuation.StageLedger.verify(path)
        assert verified["summary"]["exact"]["observed"] is None
        assert verified["summary"]["lower"]["observed"] == 4
        assert verified["summary"]["upper"]["observed"] == 9
        assert path.read_bytes() == original
        return
    if change == "hash":
        path.write_bytes(original.replace(b'"completed":4', b'"completed":5', 1))
        # A changed terminal event needs an external inventory seal; the reader
        # reports the changed final hash even without another linked event.
        assert (
            continuation.StageLedger.verify(path)["sha256"]
            != hashlib.sha256(original.splitlines()[-1]).hexdigest()
        )
        return
    if change == "truncated":
        path.write_bytes(original[:-1])
    elif change == "order":
        lines = original.splitlines(keepends=True)
        path.write_bytes(lines[0] + lines[2] + lines[1])
    with pytest.raises(ValueError):
        continuation.StageLedger.verify(path)


@pytest.mark.parametrize("reuse_preparation", [False, True])
@pytest.mark.parametrize("interrupt", [False, True])
def test_generated_clip_decodes_once_after_preparation_and_counts_real_model_boundary(
    tmp_path,
    monkeypatch,
    reuse_preparation,
    interrupt,
):
    import zipfile

    import av

    pytest.importorskip("torchvision")
    from badminton import av_runtime, court_detection, tracking
    from badminton import video as video_tools

    YOLO = pytest.importorskip("ultralytics").YOLO

    media = tmp_path / "generated.mkv"
    with av.open(str(media), "w") as container:
        stream = container.add_stream("ffv1", rate=25)
        stream.width, stream.height, stream.pix_fmt = 96, 64, "bgr0"
        stream.time_base = stream.codec_context.time_base = Fraction(1, 1000)
        for pts in (100, 140, 200):
            frame = generated_frame("bgr0")
            frame.pts, frame.time_base = pts, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    raw = media.read_bytes()
    archive = tmp_path / "generated.zip"
    member = "part1/train/00001/00001.mp4"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr(member, raw)
    clip = {
        "key": "train:00001",
        "fold": "train",
        "context": "generated-source",
        "media_path": member,
        "media_sha256": hashlib.sha256(raw).hexdigest(),
        "media_bytes": len(raw),
    }
    clock = {
        "decoded_frames": 3,
        "media_sha256": clip["media_sha256"],
        "shape": [96, 64],
        "first_pts": 0,
        "last_pts": 0.1,
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
    reuse = None
    if reuse_preparation:
        reuse = tmp_path / "predecessor"
        reuse.mkdir()
        (reuse / "source.mp4").write_bytes(raw)
        source_clock, times, video, scan = scaling.clock_and_scan(
            reuse / "source.mp4", lambda _: None
        )
        video["path"] = "source.mp4"
        for name, value in (
            ("native-clock.json", source_clock),
            ("video.json", video),
            ("camera.json", scan),
        ):
            continuation.publish(reuse / name, value)
        (reuse / "data" / video["id"]).mkdir(parents=True)
        continuation.publish(reuse / "data" / video["id"] / "timestamps.json", times)
    before = continuation.producer.inventory(reuse) if reuse is not None else {}
    original_open, visits, predictions = av_runtime.open_media, [], []

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

    def model(_model, pixels, *args, **kwargs):
        predictions.append(hashlib.sha256(pixels.tobytes()).hexdigest())
        if interrupt and len(predictions) == 2:
            raise RuntimeError("Generated model interruption")
        return []

    def observe(
        video, root, data, annotations, start, end, stride, progress, output, **kwargs
    ):
        assert (start, end, stride) == (0, 3, 1)
        assert kwargs["player_model"] == "small" and kwargs["auto_calibrate"] is True
        times = continuation.read(data / video["id"] / "timestamps.json")
        rows = list(tracking.iter_frames(video, root, times, 0, 3))
        sample = list(court_detection.iter_frames(video, root, times, 1, 2))
        np.testing.assert_array_equal(
            sample[0][2].to_ndarray(format="bgr24"),
            rows[1][2].to_ndarray(format="bgr24"),
        )
        for _, _, frame in rows:
            YOLO.predict(None, frame.to_ndarray(format="bgr24"))
        scan = kwargs["camera_scan"]
        continuation.publish(
            output,
            {
                "stage": "players",
                "video_id": video["id"],
                "video_sha256": video["sha256"],
                "checkpoint_sha256": continuation.producer.PROTOCOL["sources"]["model"],
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
                "device": "cuda:0",
                "frames": [
                    {
                        "frame": i,
                        "time_s": timestamp,
                        "players": [],
                        "motion_players": [],
                        "camera_segment_start_frame": 0,
                        "calibration_valid": False,
                    }
                    for i, timestamp, _ in rows
                ],
            },
        )

    monkeypatch.setattr(av_runtime, "open_media", counted)
    monkeypatch.setattr(video_tools, "open_media", counted)
    monkeypatch.setattr(YOLO, "predict", model)
    monkeypatch.setattr(tracking, "track_players", observe)
    run = tmp_path / "successor"
    run.mkdir()
    journal = continuation.StageLedger(run / "stages.jsonl")
    plan = {
        "output": str(run),
        "original": {"sources": {"archive": {"path": str(archive)}}},
    }
    aliases = tracking.iter_frames, court_detection.iter_frames
    try:
        if interrupt:
            with pytest.raises(RuntimeError, match="interruption"):
                continuation.continue_clip(
                    plan,
                    clip,
                    [reference],
                    clock,
                    run / "clip-004",
                    journal,
                    lambda **_: None,
                    lambda _: None,
                    reuse,
                )
            assert not (run / "clip-004/receipt.json").exists()
            assert (run / "scratch/clip-004/pixels.bin").exists()
            assert journal.summary()["lower"]["observed"] == 1
            assert journal.summary()["upper"]["observed"] == 3
        else:
            features, receipt = continuation.continue_clip(
                plan,
                clip,
                [reference],
                clock,
                run / "clip-004",
                journal,
                lambda **_: None,
                lambda _: None,
                reuse,
            )
            assert receipt["decoded_frame_visits"] == (3 if reuse_preparation else 6)
            assert receipt["model_frame_observations"] == 3
            assert features[0]["family"] == features[0]["side"] == -1
            assert not features[0]["available"] and features[0]["static"] == [0.0] * 108
            assert (run / "clip-004/pixel-spool.json").exists()
            assert not (run / "scratch/clip-004").exists()
            rebuilt, _ = continuation.verified_clip(
                run / "clip-004", clip, [reference], clock
            )
            assert rebuilt == features
    finally:
        journal.close()
    assert visits == [[100, 140, 200]] * (1 if reuse_preparation else 2)
    assert (tracking.iter_frames, court_detection.iter_frames) == aliases
    assert YOLO.predict is model
    assert (
        continuation.StageLedger.verify(run / "stages.jsonl")["summary"]
        == journal.summary()
    )
    if reuse_preparation:
        assert continuation.producer.inventory(reuse) == before


@pytest.fixture
def continuation_operation(metadata_operation, science_observation, monkeypatch):  # noqa: F811
    original, store, result, predictions = metadata_operation
    root = Path(original["workspace"])
    old_rows = scaling.original_inputs(original)[2]
    cohort = copy.deepcopy(original["cohort"])
    cohort["reference_rows"] = scaling.canonical_reference_rows(None)
    cohort["new_keys"] = [f"completed:{i}" for i in range(4)]
    original["runtime"] = {"generated": True}
    old_receipts = [{"key": key, "frames": 0} for key in cohort["new_keys"]]
    cost = {"maximum_scratch_bytes": 1024, "clips": 0, "frames": 0, "decode_visits": 0}
    monkeypatch.setattr(
        continuation,
        "continuation_inputs",
        lambda _: (original, cohort, {}, old_rows, [], old_receipts, cost),
    )
    monkeypatch.setattr(
        continuation, "source_seals", lambda: {"generated.py": "b" * 64}
    )
    monkeypatch.setattr(scaling, "tested_commit", lambda: "a" * 40)
    monkeypatch.setattr(scaling, "git_seals", lambda *_: None)
    monkeypatch.setattr(continuation.producer, "runtime", lambda: {"generated": True})
    monkeypatch.setattr(continuation.time, "time", lambda: 1200)
    for key in ("decoded_frame_visits", "model_observations"):
        monkeypatch.setitem(continuation.PROTOCOL["limits"], key, 0)
    monkeypatch.setitem(
        continuation.PROTOCOL["expected"], "all_reference_rows", len(old_rows)
    )
    monkeypatch.setitem(continuation.PROTOCOL["expected"], "validation_rows", 1)
    monkeypatch.setattr(
        continuation, "continue_clip", lambda *_: pytest.fail("Completed clip replayed")
    )
    grant = root / ".cache/grant.json"
    continuation.publish(grant, science_observation)
    protocol = root / ".cache/protocol.json"
    continuation.publish(protocol, continuation.PROTOCOL)
    return original, store, result, predictions, grant, protocol


def freeze_generated(case, capsys):
    original, _, _, _, grant, protocol = case
    root = Path(original["workspace"])
    directory, output = root / ".cache/continuation-freeze", root / ".cache/successor"
    continuation.main(
        [
            "freeze",
            "--workspace",
            str(root),
            "--grant-state",
            str(grant),
            "--protocol",
            str(protocol),
            "--output",
            str(directory),
            "--run-output",
            str(output),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    prospective = directory / "prospective.json"
    plan = continuation.read(prospective)
    publication = root / ".cache/publication.json"
    continuation.publish(
        publication,
        {
            "author": "Ken0u",
            "url": "https://github.com/Ken0u/badminton-match-analyzer/issues/405#issuecomment-123",
            "published_at": 1200,
            "intent": {
                "task": continuation.PROTOCOL["task"],
                "spec_hash": continuation.PROTOCOL["spec_hash"],
                "prospective_sha256": result["prospective_sha256"],
                "source_commit": plan["tested_commit"],
            },
        },
    )
    return prospective, result["prospective_sha256"], output, grant, publication


def test_public_main_freeze_run_verify_uses_real_store_and_one_fake_fit(
    continuation_operation,
    monkeypatch,
    capsys,
):
    original, store, result, predictions, _, _ = continuation_operation
    fits, verifications = [], []

    def fit(_data, output, _progress):
        fits.append(output)
        output.mkdir()
        continuation.publish(
            output / "predictions.json", [p.tolist() for p in predictions]
        )
        return result

    def verify_arm(_data, output):
        verifications.append(output)
        return result, [p.tolist() for p in predictions]

    monkeypatch.setattr(continuation.learning, "fit", fit)
    prospective, expected, output, grant, publication = freeze_generated(
        continuation_operation, capsys
    )
    assert not output.exists() and not fits
    immutable = continuation.producer.inventory(Path(original["control"]))
    continuation.main(
        [
            "run",
            "--prospective",
            str(prospective),
            "--prospective-sha256",
            expected,
            "--output",
            str(output),
            "--grant-state",
            str(grant),
            "--publication",
            str(publication),
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    assert len(fits) == 1 and summary["remaining_clips"] == 0
    process = continuation.read(output / "process.json")
    assert store.job(process["job_id"])["status"] == "completed"
    monkeypatch.setattr(continuation.learning, "verify_arm", verify_arm)
    monkeypatch.setattr(
        continuation.learning, "fit", lambda *_: pytest.fail("Refit in verification")
    )
    before = continuation.producer.inventory(output)
    continuation.main(
        [
            "verify",
            "--prospective",
            str(prospective),
            "--prospective-sha256",
            expected,
            "--output",
            str(output),
        ]
    )
    verified = json.loads(capsys.readouterr().out)
    assert verified["verified_references"] == 2
    assert (
        verified["verification_new_decodes"] == verified["verification_real_fits"] == 0
    )
    assert len(verifications) == 2 and continuation.producer.inventory(output) == before
    assert continuation.producer.inventory(Path(original["control"])) == immutable


def test_occupied_shared_store_refuses_before_creating_successor_output(
    continuation_operation,
    monkeypatch,
    capsys,
):
    from badminton.storage import ConflictError

    _, store, _, _, _, _ = continuation_operation
    args = freeze_generated(continuation_operation, capsys)
    store.claim_job({"id": "existing", "kind": "players", "status": "running"})
    monkeypatch.setattr(
        continuation.learning, "fit", lambda *_: pytest.fail("Fit before admission")
    )
    with pytest.raises(ConflictError):
        continuation.run(*args)
    assert not args[2].exists() and store.job("existing")["status"] == "running"


def test_failed_fit_consumes_once_and_preserves_real_store_and_partial_output(
    continuation_operation,
    monkeypatch,
    capsys,
):
    _, store, _, _, _, _ = continuation_operation
    args = freeze_generated(continuation_operation, capsys)
    calls = []

    def failed_fit(_data, output, _progress):
        calls.append(output)
        output.mkdir()
        (output / "partial.bin").write_bytes(b"generated")
        raise RuntimeError("Generated interrupted fit")

    monkeypatch.setattr(continuation.learning, "fit", failed_fit)
    with pytest.raises(RuntimeError, match="interrupted fit"):
        continuation.run(*args)
    failure = continuation.read(args[2] / "failure.json")
    assert failure["accounting"]["exact"]["real_fits"] == 1
    process = continuation.read(args[2] / "process.json")
    assert store.job(process["job_id"])["status"] == "failed"
    before = continuation.producer.inventory(args[2])
    with pytest.raises(ValueError, match="previously used"):
        continuation.run(*args)
    assert len(calls) == 1 and continuation.producer.inventory(args[2]) == before


@pytest.mark.parametrize(
    "change", ["source", "runtime", "claim", "grant", "publication"]
)
def test_frozen_tampering_is_refused_before_any_scientific_fit(
    continuation_operation,
    monkeypatch,
    capsys,
    change,
):
    args = freeze_generated(continuation_operation, capsys)
    if change == "source":
        monkeypatch.setattr(
            continuation, "source_seals", lambda: {"different": "c" * 64}
        )
    elif change == "runtime":
        monkeypatch.setattr(continuation.producer, "runtime", lambda: {"changed": True})
    elif change == "claim":
        claim = continuation.claim_path(continuation_operation[0]["workspace"])
        value = continuation.read(claim)
        value["deadline"] += 1
        claim.write_bytes(continuation.encoded(value))
    elif change == "grant":
        value = continuation.read(args[3])
        value["task"]["claim"]["session_id"] = "different"
        args[3].write_bytes(continuation.encoded(value))
    elif change == "publication":
        value = continuation.read(args[4])
        value["intent"]["source_commit"] = "c" * 40
        args[4].write_bytes(continuation.encoded(value))
    monkeypatch.setattr(
        continuation.learning, "fit", lambda *_: pytest.fail("Fit after tampering")
    )
    with pytest.raises(ValueError):
        continuation.run(*args)
    assert not args[2].exists()


def launcher_module():
    path = (
        Path(continuation.__file__).resolve().parents[2]
        / "scripts/continue_aicup_pose_scaling.py"
    )
    spec = importlib.util.spec_from_file_location(
        "generated_continuation_launcher", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_pins_root_before_import_and_excludes_credentials_from_child(
    tmp_path, monkeypatch
):
    launcher = launcher_module()
    observed = []
    refreshed = []
    monkeypatch.setenv("GENERATED_API_KEY", "generated-secret")
    monkeypatch.setenv("GENERATED_ACCESS_KEY_ID", "generated-identifier")
    monkeypatch.setenv("GENERATED_AUTH", "generated-auth")
    monkeypatch.setenv("PYTHONPATH", "generated-untrusted-path")

    def child(command, *, env, check):
        assert refreshed == [True]
        observed.append((command, env))
        assert command[:3] == [sys.executable, "-I", "-B"]
        assert "--worker" in command and check is False
        assert env["BADMINTON_ROOT"] == str(tmp_path)
        assert env["BADMINTON_DATA_DIR"] == str(tmp_path / "data/processed")
        assert env["BADMINTON_WEIGHTS_DIR"] == str(tmp_path / "models/weights")
        assert not any(
            word in key.upper()
            for key in env
            for word in ("TOKEN", "SECRET", "AUTH", "KEY")
        )
        assert "PYTHONPATH" not in env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher.subprocess, "run", child)
    monkeypatch.setattr(
        launcher, "refresh_before_worker", lambda *_: refreshed.append(True)
    )
    launcher.launch(["freeze", "--workspace", str(tmp_path)])
    assert len(observed) == 1 and os.environ["GENERATED_API_KEY"] == "generated-secret"


@pytest.mark.parametrize("command", ["freeze", "run"])
def test_parent_refreshes_authenticated_grant_and_run_publication_before_child(
    tmp_path, monkeypatch, command
):
    launcher = launcher_module()
    grant = tmp_path / ".cache/pose405-observations/grant.json"
    publication = tmp_path / ".cache/pose405-observations/publication.json"
    publication.parent.mkdir(parents=True)
    publication.write_text(json.dumps({"url": "generated-publication-url"}))
    calls = []

    def observe(argv, quiet=False):
        assert quiet is True
        assert argv[argv.index("--workspace") + 1] == str(tmp_path)
        calls.append(argv)

    def child(*_args, **_kwargs):
        assert [call[0] for call in calls] == (
            ["observe-grant", "observe-publication"]
            if command == "run"
            else ["observe-grant"]
        )
        assert calls[0][calls[0].index("--output") + 1] == str(grant)
        if command == "run":
            assert calls[1][calls[1].index("--output") + 1] == str(publication)
            assert calls[1][-1] == "generated-publication-url"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher, "observe", observe)
    monkeypatch.setattr(launcher.subprocess, "run", child)
    launcher.launch(
        [command, "--workspace", str(tmp_path), "--grant-state", str(grant)]
        + (["--publication", str(publication)] if command == "run" else [])
    )


@pytest.mark.parametrize("failed_observation", ["observe-grant", "observe-publication"])
def test_parent_authentication_failure_prevents_numerical_child(
    tmp_path, monkeypatch, failed_observation
):
    launcher = launcher_module()
    publication = tmp_path / "publication.json"
    publication.write_text(json.dumps({"url": "generated-publication-url"}))

    def observe(argv, quiet=False):
        if argv[0] == failed_observation:
            raise RuntimeError("Generated authentication refusal")

    monkeypatch.setattr(launcher, "observe", observe)
    monkeypatch.setattr(
        launcher.subprocess, "run", lambda *_a, **_k: pytest.fail("Child after refusal")
    )
    with pytest.raises(RuntimeError, match="authentication refusal"):
        launcher.launch(
            [
                "run",
                "--workspace",
                str(tmp_path),
                "--grant-state",
                "generated.json",
                "--publication",
                str(publication),
            ]
        )


def test_observation_writer_cannot_replace_old_runs_or_escape_private_area(tmp_path):
    launcher = launcher_module()
    old = tmp_path / ".cache/pose397-run-v1/process.json"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"preserved")
    with pytest.raises(ValueError):
        launcher.private_write(tmp_path, old, {"new": True})
    assert old.read_bytes() == b"preserved"
    output = tmp_path / ".cache/pose405-observations/grant.json"
    launcher.private_write(tmp_path, output, {"at": 1})
    launcher.private_write(tmp_path, output, {"at": 2})
    assert json.loads(output.read_bytes()) == {"at": 2}
    assert not output.with_name(output.name + ".pending").exists()


def test_public_subprocess_help_and_bad_freeze_never_open_scientific_sources(tmp_path):
    launcher = launcher_module()
    command = [sys.executable, "-B", launcher.__file__]
    result = subprocess.run([*command, "--help"], capture_output=True, text=True)
    assert result.returncode == 0 and "{freeze,run,verify}" in result.stdout
    protocol = tmp_path / "protocol.json"
    protocol.write_text("{}")
    failure = subprocess.run(
        [
            *command,
            "freeze",
            "--workspace",
            str(tmp_path),
            "--protocol",
            str(protocol),
            "--output",
            str(tmp_path / ".cache/freeze"),
            "--run-output",
            str(tmp_path / ".cache/run"),
        ],
        capture_output=True,
        text=True,
    )
    assert (
        failure.returncode != 0
        and "Exactly one --grant-state is required" in failure.stderr
    )
    assert not (tmp_path / ".cache").exists()


def test_output_budget_denies_artifact_before_write_and_restores_scoped_writers(
    continuation_operation,
    monkeypatch,
):
    original = continuation_operation[0]
    root = Path(original["workspace"])
    output = root / ".cache/budget-case"
    output.mkdir()
    plan = {
        "original": original,
        "workspace": str(root),
        "output": str(output),
        "prospective_directory": str(root / ".cache/freeze-budget"),
    }
    budget = continuation.OutputBudget(plan)
    from badminton import tracking

    before = (
        continuation.publish,
        continuation.producer.publish,
        continuation.learning.publish,
        tracking.write_json,
        continuation.learning.save_state,
    )
    monkeypatch.setitem(continuation.PROTOCOL["limits"], "retained_bytes", 0)
    with continuation.bounded_outputs(plan, budget):
        with pytest.raises(ValueError, match="disk budget"):
            continuation.publish(output / "too-big.json", {"value": 1})
        with pytest.raises(ValueError, match="disk budget"):
            tracking.write_json(output / "players.json", {"frames": []})
    assert not list(output.iterdir())
    assert before == (
        continuation.publish,
        continuation.producer.publish,
        continuation.learning.publish,
        tracking.write_json,
        continuation.learning.save_state,
    )


def test_terminal_slot_records_failure_without_allocating_more_disk(tmp_path):
    path = tmp_path / "terminal.json"
    continuation.terminal_record(path, {"terminal": False}, create=True)
    size = path.stat().st_size
    continuation.terminal_record(
        path,
        {
            "terminal": True,
            "scientific_success": False,
            "accounting": {"observed_exact": None},
        },
    )
    assert (
        path.stat().st_size == size == continuation.PROTOCOL["limits"]["terminal_bytes"]
    )
    assert continuation.read(path)["accounting"]["observed_exact"] is None
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="reservation"):
        continuation.terminal_record(path, {"terminal": True})


def generated_admission(root, monkeypatch):
    failure, integrity = continuation.admission_receipts(root)
    failure.parent.mkdir(parents=True, exist_ok=True)
    expected = copy.deepcopy(continuation.PROTOCOL["prior_admission"])
    value = {
        "task": expected["task"],
        "source": expected["source"],
        "grant_at": expected["granted_at"],
        "original_task_deadline": expected["deadline"],
        "managed_exec_terminal": True,
        "managed_exec_exit_code": 1,
        "prospective_created": False,
        "successor_claim_created": False,
        "run_output_created": False,
        "active_shared_store_jobs": 0,
        "scientific_operations_started": 0,
        "source_decode_visits": 0,
        "model_observations": 0,
        "real_fits": 0,
    }
    continuation.publish(failure, value)
    continuation.publish(integrity, {"generated": True})
    expected.update(
        failure_sha256=continuation.digest(failure),
        integrity_sha256=continuation.digest(integrity),
    )
    monkeypatch.setitem(continuation.PROTOCOL, "prior_admission", expected)
    return failure, integrity


@pytest.mark.parametrize(
    "change",
    [None, "missing_failure", "missing_integrity", "bytes", "clock", "fits", "claim"],
)
def test_prior_admission_preserves_zero_counts_and_original_clock(
    tmp_path, monkeypatch, change
):
    failure, integrity = generated_admission(tmp_path, monkeypatch)
    if change == "missing_failure":
        failure.unlink()
    elif change == "missing_integrity":
        integrity.unlink()
    elif change == "bytes":
        failure.write_bytes(b"changed")
    elif change:
        value = continuation.read(failure)
        value[
            {
                "clock": "original_task_deadline",
                "fits": "real_fits",
                "claim": "successor_claim_created",
            }[change]
        ] += 1
        failure.write_bytes(continuation.encoded(value))
        # Even matching seals cannot reinterpret a nonzero operation or old clock.
        monkeypatch.setitem(
            continuation.PROTOCOL["prior_admission"],
            "failure_sha256",
            continuation.digest(failure),
        )
    if change:
        with pytest.raises((ValueError, FileNotFoundError)):
            continuation.prior_admission(tmp_path)
    else:
        before = continuation.producer.inventory(tmp_path)
        continuation.prior_admission(tmp_path)
        assert continuation.producer.inventory(tmp_path) == before


def test_retained_budget_counts_admission_files_and_both_observation_directories(
    tmp_path, monkeypatch
):
    generated_admission(tmp_path, monkeypatch)
    for task in (402, 405):
        observation = tmp_path / f".cache/pose{task}-observations/grant.json"
        observation.parent.mkdir()
        continuation.publish(observation, {"generated": task})
    original = {
        name: str(tmp_path / "original" / name)
        for name in (
            "prepared",
            "native",
            "audit",
            "control",
            "output",
            "prospective_directory",
            "actor_prospective",
            "control_prospective",
        )
    }
    plan = {
        "workspace": str(tmp_path),
        "original": original,
        "prospective_directory": str(tmp_path / "freeze"),
        "output": str(tmp_path / "run"),
    }
    expected = sum(
        p.stat().st_size for p in (tmp_path / ".cache").rglob("*") if p.is_file()
    )
    assert continuation.disk_budget(plan)["retained_bytes"] == expected
    monkeypatch.setitem(continuation.PROTOCOL["limits"], "retained_bytes", expected - 1)
    with pytest.raises(ValueError, match="disk budget"):
        continuation.disk_budget(plan)


@pytest.fixture
def generated_predecessor(tmp_path, monkeypatch):
    import psutil
    from badminton.storage import Store

    root = tmp_path / "original"
    generated_admission(root, monkeypatch)
    output = root / ".cache/pose397-run-v1"
    output.mkdir(parents=True)
    continuation.publish(output / "failure.json", {"real_fits": 0})
    (output / "preserved.bin").write_bytes(b"generated-original-evidence")
    store = Store(root / "data/processed")
    process = psutil.Process()
    # An explicitly different lifetime for this reused PID is terminal evidence.
    identity = {"pid": process.pid, "created_at": process.create_time() - 100}
    store.put_job(
        {
            "id": "failed-original",
            "kind": "feature-preparation",
            "status": "failed",
            "owner_pid": identity["pid"],
            "owner_started": identity["created_at"],
        }
    )
    original = root / ".cache/pose397-freeze-v1/prospective.json"
    original.parent.mkdir()
    plan = {
        "workspace": str(root),
        "output": str(output),
        "protocol": scaling.PROTOCOL,
        "tested_commit": continuation.PROTOCOL["predecessor"]["scientific_commit"],
        "deadline": continuation.PROTOCOL["predecessor"]["original_deadline"],
        "code": {},
    }
    continuation.publish(original, plan)
    claim = scaling.execution_claim(plan)
    continuation.publish(claim, {"consumed": True})
    companion = original.parent / "dispatch-recovery-v1"
    companion.mkdir()
    terminal = {
        "terminal": True,
        "process_state": "exited",
        "scientific_success": False,
        "exit_code": 1,
        "process": identity,
    }
    continuation.publish(companion / "terminal.json", terminal)
    proof = {
        "terminal_sha256": continuation.digest(companion / "terminal.json"),
        "scientific_success": False,
        "real_fits": 0,
        "decoded_frame_visits": 6502,
        "model_observations_exact": None,
        "model_observations_completed": 2200,
        "model_observations_upper_bound": 3251,
        "store_job": store.job("failed-original"),
        "inventory": {
            name: {"sha256": sha, "bytes": (output / name).stat().st_size}
            for name, sha in continuation.producer.inventory(output).items()
        },
    }
    continuation.publish(companion / "failure-preservation.json", proof)
    predecessor = copy.deepcopy(continuation.PROTOCOL["predecessor"])
    predecessor.update(
        prospective_sha256=continuation.digest(original),
        claim_sha256=continuation.digest(claim),
        failure_sha256=continuation.digest(output / "failure.json"),
        preservation_sha256=continuation.digest(
            companion / "failure-preservation.json"
        ),
    )
    monkeypatch.setitem(continuation.PROTOCOL, "predecessor", predecessor)
    monkeypatch.setattr(scaling, "git_seals", lambda *_: None)
    return root, output, store, companion


@pytest.mark.parametrize(
    "change", [None, "artifact", "claim", "store", "live", "unknown"]
)
def test_predecessor_integrity_refuses_changed_live_or_unobservable_originals(
    generated_predecessor,
    monkeypatch,
    change,
):
    import psutil

    root, output, store, companion = generated_predecessor
    before = continuation.producer.inventory(output)
    if change == "artifact":
        (output / "preserved.bin").write_bytes(b"changed")
    elif change == "claim":
        original = continuation.read(root / ".cache/pose397-freeze-v1/prospective.json")
        scaling.execution_claim(original).write_bytes(b"changed")
    elif change == "store":
        job = store.job("failed-original")
        job["status"] = "completed"
        store.put_job(job)
    elif change == "live":
        terminal = continuation.read(companion / "terminal.json")
        terminal["process"]["created_at"] = psutil.Process().create_time()
        (companion / "terminal.json").write_bytes(continuation.encoded(terminal))
        proof = continuation.read(companion / "failure-preservation.json")
        proof["terminal_sha256"] = continuation.digest(companion / "terminal.json")
        (companion / "failure-preservation.json").write_bytes(
            continuation.encoded(proof)
        )
        monkeypatch.setitem(
            continuation.PROTOCOL["predecessor"],
            "preservation_sha256",
            continuation.digest(companion / "failure-preservation.json"),
        )
    elif change == "unknown":

        def denied(_pid):
            raise psutil.AccessDenied(_pid)

        monkeypatch.setattr(psutil, "Process", denied)
    if change:
        with pytest.raises((ValueError, psutil.AccessDenied)):
            continuation.predecessor(root)
    else:
        plan, preserved, proof = continuation.predecessor(root)
        assert preserved == output and proof["model_observations_exact"] is None
        assert (
            plan["deadline"]
            == continuation.PROTOCOL["predecessor"]["original_deadline"]
        )
    if change != "artifact":
        assert continuation.producer.inventory(output) == before
