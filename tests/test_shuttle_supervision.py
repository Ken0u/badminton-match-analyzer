"""Published labels remain separate from complete native source evidence."""

import io
import itertools
import json
import os
import stat
import zipfile
from unittest.mock import patch

import pytest
from badminton import shuttle_supervision as supervision


def spec():
    return supervision.load_manifest()


def clock(count=3, **changes):
    return {
        "frames": [
            {
                "frame": i,
                "pts": 100 + i * 3,
                "time_base": "1/90",
                "time_s": (100 + i * 3) / 90,
            }
            for i in range(count)
        ],
        "frame_count": count,
        "source_size": [1280, 720],
        "display_size": [1280, 720],
        "rotation": 0,
        "issues": [],
        **changes,
    }


def archive_bytes(entries):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        for name, value in entries:
            z.writestr(name, value)
    return data.getvalue()


def test_manifest_pins_separate_supplier_and_no_usage_approval():
    source = spec()
    assert source["archive"]["sha256"] == supervision.ARCHIVE_SHA
    assert source["archive"]["creator_authenticity"].startswith("unverified")
    assert all(
        source["eligibility"][k] is False
        for k in (
            "training_allowed",
            "model_deployment_allowed",
            "dataset_redistribution_allowed",
            "independent_test_allowed",
        )
    )


def test_changed_source_or_usage_policy_is_rejected(tmp_path):
    source = spec()
    source["eligibility"]["training_allowed"] = True
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="Changed frozen"):
        supervision.load_manifest(path)


@pytest.mark.parametrize(
    "name",
    [
        "../hidden.csv",
        "/absolute.csv",
        "C:/a.csv",
        "a\\b.csv",
        "a/../b.csv",
        "a/./b.csv",
        "a//b.csv",
        "a/x:ads.csv",
        "a/CON.txt",
        "a/b. /x.csv",
        "a/b./x.csv",
    ],
)
def test_all_member_paths_are_validated_even_if_not_selected(name):
    # Windows ZipInfo construction normalizes backslashes even while reading.
    # Preserve a real raw central/local name rather than testing a writer rewrite.
    raw = archive_bytes([(name.replace("\\", "/"), b"ignored")])
    if "\\" in name:
        raw = raw.replace(name.replace("\\", "/").encode(), name.encode())
    with (
        zipfile.ZipFile(io.BytesIO(raw)) as archive,
        pytest.raises(ValueError, match="Unsafe"),
    ):
        supervision.census_archive(archive, spec()["limits"])


def test_case_collisions_symlinks_and_parent_files_are_rejected():
    for entries in (
        [("A/x.csv", b""), ("a/X.csv", b"")],
        [("A", b""), ("A/x.csv", b"")],
    ):
        with (
            zipfile.ZipFile(io.BytesIO(archive_bytes(entries))) as archive,
            pytest.raises(ValueError),
        ):
            supervision.census_archive(archive, spec()["limits"])
    member = zipfile.ZipInfo("link")
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with (
        zipfile.ZipFile(io.BytesIO(archive_bytes([(member, b"outside")]))) as archive,
        pytest.raises(ValueError, match="special"),
    ):
        supervision.census_archive(archive, spec()["limits"])


def test_unknown_csv_and_unpaired_video_do_not_disappear():
    raw = archive_bytes(
        [
            ("unrecognized/new.csv", b"Frame,Visibility,X,Y\n0,1,5,8\n"),
            ("unrecognized/movie.mp4", b"not media"),
            ("other.bin", b"x"),
        ]
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        result = supervision.census_archive(archive, spec()["limits"])
    assert [r["kind"] for r in result] == ["labels", "video", "unrecognized"]
    assert result[0]["clip"] != result[1]["clip"]


def test_uncompressed_and_selected_bounds_precede_extraction():
    source = spec()["limits"]
    source["csv_bytes"] = 3
    raw = archive_bytes([("Professional/match1/csv/1_00_01_ball.csv", b"four")])
    with (
        zipfile.ZipFile(io.BytesIO(raw)) as archive,
        pytest.raises(ValueError, match="bound"),
    ):
        supervision.census_archive(archive, source)


def test_interrupted_stream_never_publishes_partial_final(tmp_path):
    class Interrupted:
        calls = 0

        def read(self, _size):
            self.calls += 1
            if self.calls == 1:
                return b"partial"
            raise OSError("interrupted")

    target = tmp_path / "result"
    with pytest.raises(OSError):
        supervision.publish_stream(target, Interrupted(), limit=100)
    assert not target.exists()
    pending = list(tmp_path.glob("result.pending-*"))
    assert len(pending) == 1 and pending[0].read_bytes() == b"partial"
    supervision.publish_stream(target, io.BytesIO(b"complete"), limit=100)
    with pytest.raises(FileExistsError):
        supervision.publish_stream(target, io.BytesIO(b"changed"), limit=100)
    assert target.read_bytes() == b"complete" and pending[0].is_file()


def test_wrong_stream_hash_preserves_pending_but_not_final(tmp_path):
    target = tmp_path / "archive"
    with pytest.raises(ValueError, match="SHA256"):
        supervision.publish_stream(
            target, io.BytesIO(b"changed"), limit=20, expected_sha="a" * 64
        )
    assert not target.exists() and list(tmp_path.glob("archive.pending-*"))


def test_all_visibility_rows_and_native_pts_remain_distinct():
    raw = b"Frame,Visibility,X,Y\n0,1,10,20\n1,0,0,0\n2,unknown,3,4\n"
    result = supervision.normalize_csv(raw, spec(), clock())
    assert result["record_count"] == 3 and result["ordinal_coverage_complete"]
    rows = result["records"]
    assert [r["published_state"] for r in rows] == [
        "published_visible",
        "published_not_visible",
        "unknown",
    ]
    assert rows[0]["native_frame"]["pts"] == 100
    assert rows[0]["coordinate_reference_eligible"]
    assert not any(r["training_eligible"] for r in rows)
    assert not rows[2]["coordinate_reference_eligible"]


@pytest.mark.parametrize(
    "raw",
    [
        b"Frame,Visibility,X,Y\n1,1,10,20\n2,1,30,40\n3,1,40,50\n",
        b"Frame,Visibility,X,Y\n0,1,10,20\n0,1,30,40\n2,1,40,50\n",
    ],
)
def test_shifted_or_duplicate_ordinals_are_not_silently_rebased(raw):
    result = supervision.normalize_csv(raw, spec(), clock())
    assert result["record_count"] == 3 and not result["ordinal_coverage_complete"]
    assert not any(r["coordinate_reference_eligible"] for r in result["records"])
    assert all(r["native_frame"] is None for r in result["records"])


def test_unavailable_clock_rotation_and_malformed_points_retain_denominators():
    raw = b"Frame,Visibility,X,Y\n0,1,nan,20\n1,1,1400,30\n2,0,1,1\n"
    for source in (None, clock(rotation=90), clock(issues=["missing_pts"])):
        result = supervision.normalize_csv(raw, spec(), source)
        assert result["record_count"] == 3
        assert not any(r["coordinate_reference_eligible"] for r in result["records"])
        assert result["records"][2]["published_state"] == "published_not_visible"
        assert "invisible_with_nonzero_coordinate" in result["records"][2]["issues"]


def test_unsupported_and_unparsed_csv_are_explicitly_retained():
    result = supervision.normalize_csv(b"Frame,X,Y\n0,4,6\n", spec(), clock(1))
    assert result["record_count"] == 1 and result["records"][0]["raw_fields"] == [
        "0",
        "4",
        "6",
    ]
    assert not result["records"][0]["coordinate_reference_eligible"]
    result = supervision.normalize_csv(b"Frame,Visibility,X,Y\n\xff", spec(), None)
    assert (
        result["record_count"] is None and result["parse_error"] == "UnicodeDecodeError"
    )


def test_existing_extracted_source_must_match_pinned_archive(tmp_path):
    raw = archive_bytes([("Professional/match1/csv/1_00_01_ball.csv", b"original")])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        item = supervision.census_archive(archive, spec()["limits"])[0]
        path = supervision._extract(archive, item, tmp_path, spec())
        path.write_bytes(b"changed!")
        with pytest.raises(ValueError, match="differs"):
            supervision._extract(archive, item, tmp_path, spec())


def test_resume_binds_recorded_terminal_hash_and_each_clock_row(tmp_path):
    clip = {
        "clip": "professional/match1/1_00_01",
        "context_sha256": "c" * 64,
        "clock": clock(),
        "inputs": {},
    }
    path = tmp_path / "attempts/first/clips/a.json"
    supervision.publish_json(path, clip)
    terminal = tmp_path / "attempts/first/terminal.json"
    supervision.publish_json(
        terminal,
        {
            "context_sha256": "c" * 64,
            "completed_clips": [supervision._seal(tmp_path, path)],
        },
    )
    expected = supervision.file_hash(terminal)
    assert clip["clip"] in supervision._resume(tmp_path, terminal, expected, "c" * 64)
    clip["clock"]["frames"][0]["pts"] += 1
    path.write_text(json.dumps(clip))
    with pytest.raises(ValueError, match="Completed output changed"):
        supervision._resume(tmp_path, terminal, expected, "c" * 64)
    with pytest.raises(ValueError, match="receipt hash"):
        supervision._resume(tmp_path, terminal, "a" * 64, "c" * 64)


def test_real_shared_admission_blocks_before_fetch_or_import(tmp_path, monkeypatch):
    from badminton import config
    from badminton.storage import ConflictError, Store

    shared = tmp_path / "data/processed"
    store = Store(shared)
    store.claim_job(
        {
            "id": "existing",
            "kind": "research",
            "video_id": None,
            "status": "running",
            "progress": 0,
        }
    )
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", shared)
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    monkeypatch.setattr(supervision, "_context", lambda *_a: ({}, "c" * 64))
    monkeypatch.setattr(supervision, "_prior_proofs", lambda *_a: [])
    with patch.object(supervision.urllib.request, "urlopen") as fetch:
        with pytest.raises(ConflictError):
            supervision.run_preparation(
                tmp_path,
                tmp_path / ".cache/output",
                tmp_path / "declaration",
                mode="fetch",
            )
        fetch.assert_not_called()
    assert store.jobs()[0]["id"] == "existing"


def test_isolated_data_root_is_rejected_before_context_or_job(tmp_path, monkeypatch):
    from badminton import config

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path / "isolated")
    with (
        patch.object(supervision, "_context") as context,
        pytest.raises(ValueError, match="real shared"),
    ):
        supervision.run_preparation(
            tmp_path, tmp_path / ".cache/output", tmp_path / "none", mode="fetch"
        )
    context.assert_not_called()


def test_prior_pid_reuse_requires_original_store_lifetime_and_terminal_state(tmp_path):
    import psutil
    from badminton.storage import Store

    shared = tmp_path / "data/processed"
    store = Store(shared)
    owner = psutil.Process()
    store.claim_job(
        {"id": "old", "kind": "research", "video_id": None, "status": "running"}
    )
    output = tmp_path / ".cache/output"
    admission = output / "attempts/old/admission.json"
    supervision.publish_json(
        admission,
        {
            "job_id": "old",
            "process": {"pid": os.getpid(), "creation_time": owner.create_time()},
        },
    )
    with pytest.raises(ValueError, match="still alive"):
        supervision._prior_proofs(tmp_path, output)

    class Reused:
        def create_time(self):
            return owner.create_time() + 10

    with patch.object(supervision.psutil, "Process", return_value=Reused()):
        with pytest.raises(ValueError, match="not terminal"):
            supervision._prior_proofs(tmp_path, output)
        job = store.jobs()[0]
        job["status"] = "completed"
        store.put_job(job)
        assert supervision._prior_proofs(tmp_path, output)[0][
            "original_lifetime_exited"
        ]


def test_native_vfr_clock_matches_existing_source_identity_without_fps_invention(
    tmp_path, monkeypatch
):
    from badminton.video import timestamps_for
    from test_segments import make_source

    monkeypatch.setattr(supervision.importlib.util, "find_spec", lambda _name: None)
    video, data, _store = make_source(tmp_path)
    actual = supervision.decode_clock(tmp_path / video["path"], 100)
    expected = timestamps_for(data, video["id"])
    assert actual["frame_count"] == video["frame_count"] == 65
    assert [r["frame"] for r in actual["frames"]] == list(range(65))
    assert [
        r["time_s"] - video["source_start_s"] for r in actual["frames"]
    ] == pytest.approx(expected, abs=0.00002)
    assert (
        len({b - a for a, b in itertools.pairwise(r["pts"] for r in actual["frames"])})
        == 2
    )
    assert actual["source_size"] == [96, 64] and actual["rotation"] == 0
    assert actual["issues"] == []


def test_complete_import_retains_orphans_unknown_layout_and_all_rows(
    tmp_path, monkeypatch
):
    entries = [
        (
            "Professional/match1/csv/1_01_00_ball.csv",
            b"Frame,Visibility,X,Y\n0,1,10,20\n1,0,0,0\n2,unknown,3,4\n",
        ),
        ("Professional/match1/video/1_01_00.mp4", b"video one"),
        (
            "Professional/match2/csv/1_02_00_ball.csv",
            b"Frame,Visibility,X,Y\n0,1,5,6\n",
        ),
        ("Test/match1/video/1_01_00.mp4", b"video two"),
        ("other/unknown.csv", b"Frame,Visibility,X,Y\n0,1,7,8\n"),
    ]
    raw = archive_bytes(entries)
    archive = tmp_path / "source.zip"
    archive.write_bytes(raw)
    source = spec()
    source["archive"].update(bytes=len(raw), sha256=supervision.digest(raw))
    monkeypatch.setattr(supervision, "decode_clock", lambda *_a: clock())
    output = tmp_path / "output"
    completed, progress = [], []
    result = supervision.import_archive(
        archive,
        output,
        output / "attempts/a",
        source,
        "c" * 64,
        progress.append,
        completed,
    )
    report = supervision.read_json(output / result["report"]["path"])
    assert report["clip_count"] == 4 and report["published_rows_parsed"] == 5
    assert report["native_clock_clips"] == 2 and report["native_frames"] == 6
    assert report["coordinate_reference_eligible"] == 1
    assert report["training_ready_rows"] == 0
    assert report["published_states"]["unknown"] == 1
    assert report["clip_issues"]["missing_or_ambiguous_video"] == 2
    assert report["clip_issues"]["missing_or_ambiguous_label_file"] == 1
    assert len(completed) == 4 and progress == sorted(progress)


def test_entire_archive_census_precedes_any_extraction(tmp_path):
    raw = archive_bytes(
        [("Professional/match1/csv/1_01_00_ball.csv", b"valid"), ("../bad", b"bad")]
    )
    archive = tmp_path / "source.zip"
    archive.write_bytes(raw)
    source = spec()
    source["archive"].update(bytes=len(raw), sha256=supervision.digest(raw))
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Unsafe"):
        supervision.import_archive(
            archive,
            output,
            output / "attempts/a",
            source,
            "c" * 64,
            lambda _v: None,
            [],
        )
    assert not output.exists()


def test_source_snapshot_tampering_is_not_accepted(tmp_path):
    source = tmp_path / "source.md"
    source.write_bytes(b"creator")
    declaration = {
        "sources": {"source.md": {"sha256": supervision.file_hash(source), "bytes": 7}}
    }
    path = tmp_path / "declaration.json"
    path.write_text(json.dumps(declaration))
    expected = {
        "sources": declaration["sources"],
        "source_declaration_sha256": supervision.file_hash(path),
    }
    supervision.verify_declaration(path, expected)
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="snapshot changed"):
        supervision.verify_declaration(path, expected)


def test_creator_match_tables_preserve_separate_namespaces_without_identity_certification():
    text = """### Descriptions of each video (train professional matches)
| Seq | Players | Match | Color | Frames |
| 1 | A Vs B | Tournament2020 | Green | 10 |
### Rally of each match
| 2 | 8 | Scores | Not identities | 8 |
### Descriptions of each video (test professional matches)
| 1 | C Vs D | Tournament2021 | Red | 12 |
"""
    catalog = supervision.creator_catalog(text)
    assert set(catalog) == {"professional/match1", "test/match1"}
    assert catalog["professional/match1"]["published_frame_claim"] == "10"
    assert not catalog["test/match1"]["source_identity_reviewed"]


def test_changed_consumers_fail_real_store_job_before_completion(tmp_path, monkeypatch):
    from badminton import config
    from badminton.storage import Store

    shared = tmp_path / "data/processed"
    store = Store(shared)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", shared)
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    source = spec()
    source["archive"].update(bytes=3, sha256=supervision.digest(b"zip"))
    monkeypatch.setattr(supervision, "load_manifest", lambda _p: source)
    monkeypatch.setattr(supervision, "_prior_proofs", lambda *_a: [])
    output = tmp_path / ".cache/output"
    with patch.object(
        supervision,
        "_context",
        side_effect=[({}, "c" * 64), ValueError("Consumer changed")],
    ):
        with patch.object(
            supervision.urllib.request, "urlopen", return_value=io.BytesIO(b"zip")
        ):
            with pytest.raises(ValueError, match="Consumer changed"):
                supervision.run_preparation(
                    tmp_path, output, tmp_path / "declaration", mode="fetch"
                )
    assert store.jobs()[0]["status"] == "failed"
    assert (
        supervision.read_json(next(output.glob("attempts/*/terminal.json")))["status"]
        == "failed"
    )
    assert (output / "archive.zip").read_bytes() == b"zip"


def test_consumer_change_between_hash_and_snapshot_blocks_before_admission(
    tmp_path, monkeypatch
):
    source = tmp_path / "candidate.py"
    source.write_bytes(b"original")
    declaration = tmp_path / "declaration.json"
    declaration.write_text("{}")
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"archive": {}}')
    output = tmp_path / ".cache/output"
    monkeypatch.setattr(supervision, "verify_declaration", lambda *_a: {})
    monkeypatch.setattr(
        supervision, "_consumers", lambda: {"badminton/candidate.py": source}
    )
    original_read = type(source).read_bytes

    def changed_read(path):
        return b"changed" if path == source else original_read(path)

    with patch.object(type(source), "read_bytes", changed_read):
        with pytest.raises(ValueError, match="changed during snapshot"):
            supervision._context(
                tmp_path, output, declaration, manifest, {"archive": {}}
            )
    assert not (output / "consumer/badminton/candidate.py").exists()


def test_foreign_nonempty_output_is_preserved_without_new_context(
    tmp_path, monkeypatch
):
    declaration, manifest = tmp_path / "declaration.json", tmp_path / "manifest.json"
    declaration.write_text("{}")
    manifest.write_text('{"archive": {}}')
    output = tmp_path / ".cache/other-research"
    output.mkdir(parents=True)
    sentinel = output / "existing-results.txt"
    sentinel.write_bytes(b"other research")
    monkeypatch.setattr(supervision, "verify_declaration", lambda *_a: {})
    monkeypatch.setattr(supervision, "_consumers", dict)
    with pytest.raises(ValueError, match="owned output lineage"):
        supervision._context(tmp_path, output, declaration, manifest, {"archive": {}})
    assert sentinel.read_bytes() == b"other research"
    assert not (output / "context.json").exists()


def test_shared_cache_itself_is_not_an_output_lineage(tmp_path, monkeypatch):
    from badminton import config
    from badminton.storage import Store

    shared = tmp_path / "data/processed"
    Store(shared)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", shared)
    monkeypatch.setattr(config, "WEIGHTS", tmp_path / "models/weights")
    with patch.object(
        supervision, "_context", side_effect=AssertionError("must not reach context")
    ):
        with pytest.raises(ValueError, match="dedicated output"):
            supervision.run_preparation(
                tmp_path, tmp_path / ".cache", tmp_path / "none", mode="fetch"
            )
