"""Source contracts protect new supervision from labels, clocks and split errors."""

import copy
import hashlib
import json
import struct
import zipfile

import pytest
from badminton.aicup_data import import_aicup2023, normalize_clip
from badminton.datasets import read_rows


def stroke(order="1", frame="17", family="1", **changes):
    return {
        "ShotSeq": order,
        "HitFrame": frame,
        "Hitter": "A",
        "Backhand": "2",
        "BallType": family,
        "Winner": "X",
        "RoundHead": "1",
    } | changes


def clip(*rows):
    return normalize_clip(list(rows) or [stroke()], "00001", "train")


def csv_bytes(rows):
    return (
        ",".join(rows[0])
        + "\r\r\n"
        + "\r\r\n".join(",".join(r.values()) for r in rows)
        + "\r\r\n"
    ).encode()


def archive_fixture(tmp_path, *, files=None):
    path = tmp_path / "part1.zip"
    readme = b"Generated software fixture, not public data"
    files = {"part1/README.txt": readme} | (
        files
        if files is not None
        else {
            "part1/train/00001/00001.mp4": b"fake training media; no decoding requested",
            "part1/train/00001/00001_S2.csv": csv_bytes([stroke()]),
            "part1/val/00001/00001.mp4": b"fake unlabelled validation media",
        }
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    spec = {
        "dataset": "generated AI CUP source-contract fixture",
        "normalization_version": 1,
        "archive": {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
            "clip_counts": {"train": 1, "val": 1},
            "label_counts": {"train": 1, "val": 0},
            "readme_sha256": hashlib.sha256(readme).hexdigest(),
        },
    }
    return path, spec


def test_original_nine_codes_and_side_flag_convention():
    rows = [stroke(str(i), str(10 * i), str(i)) for i in range(1, 10)]
    # Two serves in this mapping-only diagnostic correctly quarantine sequence.
    mapped = clip(*rows)
    assert [r["family"] for r in mapped] == [
        None,
        None,
        "clear",
        "drive",
        "smash",
        "net",
        "drop",
        "lift",
        "other",
    ]
    assert [r["kind"] for r in mapped[:3]] == ["serve", "serve", "shot"]
    assert clip(stroke(Backhand="1"))[0]["side"] == "backhand"
    assert clip(stroke(Backhand="2"))[0]["side"] == "forehand"
    assert clip(stroke(Backhand="0"))[0]["side"] == "unknown"


def test_raw_ordinals_court_ends_and_published_partition_do_not_manufacture_truth():
    raw = stroke(frame="0", Backhand="", Winner="B")
    before = copy.deepcopy(raw)
    row = clip(raw)[0]
    assert row["source_contact_frame"] == 0
    assert row["source_court_end"] == "far" and row["player_id"] is None
    assert row["side"] == "unknown" and row["source_partition"] == "train"
    assert row["split"] == "unassigned" and row["source_match_id"] is None
    assert not row["training_ready"] and row["media_alignment"] == "unverified"
    assert "frame" not in row and "time_s" not in row
    assert "terminal_frame" not in row and row["kind"] == "serve"
    assert row["raw"] == raw == before


@pytest.mark.parametrize("frame", ["", "-1", "1.5", "nan", "inf"])
def test_invalid_contact_is_retained_and_cannot_become_supervision(frame):
    row = clip(stroke(frame=frame))[0]
    assert row["source_contact_frame"] is None and row["raw"]["HitFrame"] == frame
    assert not row["contact_label_eligible"]
    assert not row["family_eligible"] and not row["side_eligible"]


@pytest.mark.parametrize(
    "mutation,issue",
    [
        ({"ShotSeq": "3"}, "incomplete_or_duplicate_stroke_order"),
        ({"HitFrame": "17"}, "duplicate_or_reversed_contact_frames"),
        ({"BallType": "2"}, "serve_sequence_disagrees_with_type"),
    ],
)
def test_inconsistent_sequences_are_preserved_and_entire_clip_is_quarantined(
    mutation, issue
):
    rows = clip(stroke(), stroke("2", "23", "8", **mutation))
    assert len(rows) == 2
    assert all(issue in r["issues"] and not r["contact_label_eligible"] for r in rows)


def test_winner_marker_is_not_rally_end_or_another_contact():
    rows = clip(stroke(Winner="A"), stroke("2", "23", "8", Winner="B"))
    assert all("winner_before_terminal_stroke" in r["issues"] for r in rows)
    assert len(rows) == 2 and all(r["kind"] != "rally_end" for r in rows)


def test_a_missing_frame_cannot_hide_reversed_known_contacts():
    rows = clip(stroke(), stroke("2", "", "8"), stroke("3", "16", "6"))
    assert [r["source_contact_frame"] for r in rows] == [17, None, 16]
    assert all("duplicate_or_reversed_contact_frames" in r["issues"] for r in rows)
    assert all(not r["contact_label_eligible"] for r in rows)


def test_unknown_family_side_and_hitter_remain_independently_unknown():
    row = clip(stroke(), stroke("2", "25", "99", Backhand="3", Hitter="C"))[1]
    assert row["contact_label_eligible"]
    assert not row["family_eligible"] and not row["side_eligible"]
    assert row["family"] == row["side"] == "unknown"
    assert row["source_court_end"] is None


def test_import_indexes_all_media_without_decoding_or_assuming_independent_matches(
    tmp_path,
):
    archive, spec = archive_fixture(tmp_path)
    output = tmp_path / "index"
    before = archive.read_bytes()
    report = import_aicup2023(archive, output, spec=spec)
    records = json.loads((output / "records.json").read_text())
    clips = json.loads((output / "clips.json").read_text())
    assert report["record_count"] == 1 and report["labelled_clip_count"] == 1
    assert report["clip_counts"] == {"train": 1, "val": 1}
    assert len(clips) == 2 and "label_path" not in clips[1]
    assert records[0]["media_sha256"] == clips[0]["media_sha256"]
    assert (
        clips[0]["media_sha256"]
        == hashlib.sha256(b"fake training media; no decoding requested").hexdigest()
    )
    assert not records[0]["training_ready"] and report["training_ready_records"] == 0
    assert import_aicup2023(archive, output, spec=spec) == report
    assert archive.read_bytes() == before


@pytest.mark.parametrize("problem", ["size", "hash", "counts"])
def test_bad_pins_fail_before_writing_any_outputs(tmp_path, problem):
    archive, spec = archive_fixture(tmp_path)
    if problem == "size":
        spec["archive"]["bytes"] += 1
    elif problem == "hash":
        spec["archive"]["sha256"] = "0" * 64
    else:
        spec["archive"]["clip_counts"]["train"] = 2
    with pytest.raises(ValueError, match=r"mismatch|disagree"):
        import_aicup2023(archive, tmp_path / "output", spec=spec)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "name",
    [
        "../escape.csv",
        "part1/train/00001/00002_S2.csv",
        "part1/train/00001/sub/00001_S2.csv",
        "predictions.csv",
    ],
)
def test_unexpected_or_mismatched_members_are_never_extracted(tmp_path, name):
    archive, spec = archive_fixture(tmp_path, files={name: csv_bytes([stroke()])})
    with pytest.raises(ValueError, match="Unexpected"):
        import_aicup2023(archive, tmp_path / "output", spec=spec)
    assert not (tmp_path / "output").exists() and not (tmp_path / "escape.csv").exists()


def test_missing_media_and_missing_training_labels_fail(tmp_path):
    archive, spec = archive_fixture(
        tmp_path, files={"part1/train/00001/00001_S2.csv": csv_bytes([stroke()])}
    )
    with pytest.raises(ValueError, match="paired media"):
        import_aicup2023(archive, tmp_path / "output", spec=spec)
    archive, spec = archive_fixture(
        tmp_path, files={"part1/train/00001/00001.mp4": b"fake"}
    )
    with pytest.raises(ValueError, match="no labels"):
        import_aicup2023(archive, tmp_path / "output", spec=spec)


def test_csv_source_shape_errors_and_different_output_version_are_rejected(tmp_path):
    for data in [b"HitFrame,HitFrame\n1,2", b"ShotSeq,HitFrame\n1,2,3"]:
        with pytest.raises(ValueError):
            read_rows(data)
    with pytest.raises(ValueError, match="required"):
        clip({"HitFrame": "2"})
    archive, spec = archive_fixture(tmp_path)
    output = tmp_path / "output"
    import_aicup2023(archive, output, spec=spec)
    before = (output / "records.json").read_bytes()
    spec["normalization_version"] += 1
    with pytest.raises(ValueError, match="different source/mapping"):
        import_aicup2023(archive, output, spec=spec)
    assert (output / "records.json").read_bytes() == before


def test_duplicate_member_names_cannot_silently_choose_a_label_version(tmp_path):
    archive, spec = archive_fixture(tmp_path)
    with (
        zipfile.ZipFile(archive, "a") as target,
        pytest.warns(UserWarning, match="Duplicate"),
    ):
        target.writestr(
            "part1/train/00001/00001_S2.csv", csv_bytes([stroke(Backhand="1")])
        )
    spec["archive"].update(
        bytes=archive.stat().st_size,
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    with pytest.raises(ValueError, match="Duplicate archive"):
        import_aicup2023(archive, tmp_path / "output", spec=spec)
    assert not (tmp_path / "output").exists()


def test_crc_is_checked_for_media_in_addition_to_the_archive_pin(tmp_path):
    archive, spec = archive_fixture(tmp_path)
    with zipfile.ZipFile(archive) as target:
        info = target.getinfo("part1/train/00001/00001.mp4")
    data = bytearray(archive.read_bytes())
    name, extra = struct.unpack_from("<HH", data, info.header_offset + 26)
    offset = info.header_offset + 30 + name + extra
    # Flip a deflate literal while retaining valid structure and wrong CRC.
    data[offset + info.compress_size - 3] ^= 1
    archive.write_bytes(data)
    spec["archive"]["sha256"] = hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError, match="corrupt AI CUP archive"):
        import_aicup2023(archive, tmp_path / "output", spec=spec)
    assert not (tmp_path / "output").exists()


def test_source_mutation_after_hashing_cannot_be_published_as_verified(
    tmp_path, monkeypatch
):
    from badminton import aicup_data

    archive, spec = archive_fixture(tmp_path)
    original = aicup_data._hash
    changed = False

    def mutating_hash(source):
        nonlocal changed
        result = original(source)
        if not changed:
            with archive.open("ab") as writable:
                writable.write(b"source changed")
            changed = True
        return result

    monkeypatch.setattr(aicup_data, "_hash", mutating_hash)
    with pytest.raises(ValueError, match="changed during import"):
        import_aicup2023(archive, tmp_path / "output", spec=spec)
    assert not (tmp_path / "output").exists()


def test_cli_imports_generated_archive_without_opening_app_store(
    tmp_path, monkeypatch, capsys
):
    from badminton import aicup_data, cli

    archive, spec = archive_fixture(tmp_path)
    monkeypatch.setattr(aicup_data, "pinned_source", lambda: spec)
    monkeypatch.setattr(
        cli, "Store", lambda *args: pytest.fail("Dataset import opened app store")
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "badminton",
            "import-aicup2023",
            str(archive),
            "--output",
            str(tmp_path / "output"),
        ],
    )
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["record_count"] == 1 and result["training_ready_records"] == 0
    assert result["media_alignment"] == "unverified"


def test_cli_bad_source_is_actionable_without_partial_output(
    tmp_path, monkeypatch, capsys
):
    from badminton import aicup_data, cli

    archive, spec = archive_fixture(tmp_path)
    spec["archive"]["sha256"] = "0" * 64
    monkeypatch.setattr(aicup_data, "pinned_source", lambda: spec)
    monkeypatch.setattr(
        "sys.argv",
        [
            "badminton",
            "import-aicup2023",
            str(archive),
            "--output",
            str(tmp_path / "output"),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert "archive source hash mismatch" in capsys.readouterr().err
    assert not (tmp_path / "output").exists()


def test_exact_duplicate_media_across_partitions_is_reported_without_dropping_clips(
    tmp_path,
):
    archive, spec = archive_fixture(
        tmp_path,
        files={
            "part1/train/00001/00001.mp4": b"same media",
            "part1/train/00001/00001_S2.csv": csv_bytes([stroke()]),
            "part1/val/00001/00001.mp4": b"same media",
        },
    )
    report = import_aicup2023(archive, tmp_path / "output", spec=spec)
    assert report["clip_counts"] == {"train": 1, "val": 1}
    assert len(report["duplicate_media_groups"]) == 1
    assert report["duplicate_media_groups"][0]["paths"] == [
        "part1/train/00001/00001.mp4",
        "part1/val/00001/00001.mp4",
    ]
    assert report["training_ready_records"] == 0
