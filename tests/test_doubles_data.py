import csv
import io
import json
from copy import deepcopy

import pytest
from badminton.datasets import blob_sha
from badminton.doubles_data import import_doubles, normalize_set, pinned_source


def stroke(order=1, **changes):
    return {
        "rally": "1",
        "ball_round": str(order),
        "time": "00:00:00",
        "start_frame": str(order * 10),
        "end_frame": str((order + 1) * 10),
        "player": "C" if order == 1 else "B",
        "server": "1" if order == 1 else "3",
        "ball_type": "發短球" if order == 1 else "殺球",
        "backhand": "1" if order == 1 else "0",
        "roundscore_AB": "1",
        "roundscore_CD": "0",
        "flaw": "0",
        "db": "0",
    } | changes


def normalize(rows, **segment_changes):
    segment = {
        "Score": "1_01_00",
        "Start": "5",
        "End": "50",
        "Comment": "0",
    } | segment_changes
    return normalize_set(rows, 1, 1, "train", {segment["Score"]: segment})


def test_serve_terminal_fault_and_final_shot_remain_events_not_rally_ends():
    rows = [stroke(), stroke(2)]
    records, rallies = normalize(rows)
    assert [r["kind"] for r in records] == ["serve", "shot"]
    assert records[1]["family"] == "smash" and records[1]["terminal_stroke_marker"]
    assert all(r["label_eligible"] and not r["training_ready"] for r in records)
    assert all(
        r["contact_frame"] is None and r["media_alignment"] == "unverified"
        for r in records
    )
    assert [r["raw"] for r in records] == rows
    assert (
        rallies[0]["exact_serve_frame"] is None
        and rallies[0]["exact_terminal_frame"] is None
    )
    records, rallies = normalize([stroke(server="3")])
    assert records[0]["kind"] == "serve" and records[0]["label_eligible"]
    assert rallies[0]["terminal_serve"] is True


@pytest.mark.parametrize(
    "changes,issue",
    [
        ({"backhand": ""}, "missing_or_invalid_side_flag"),
        ({"backhand": "2"}, "missing_or_invalid_side_flag"),
        ({"start_frame": "20"}, "invalid_shot_interval"),
        ({"ball_type": "new stroke"}, "unresolved_source_type"),
        ({"player": "E"}, "unknown_source_player"),
        ({"flaw": "1"}, "source_flaw_or_unknown_flag"),
        ({"time": "00:70:01"}, "invalid_coarse_source_time"),
    ],
)
def test_uncertain_source_fields_stay_raw_and_ineligible(changes, issue):
    raw = stroke(**changes)
    records, _ = normalize([raw, stroke(2)])
    assert issue in records[0]["issues"] and not records[0]["label_eligible"]
    assert records[0]["raw"] == raw


def test_combined_push_kill_is_other_and_blank_side_is_not_default_forehand():
    records, _ = normalize([stroke(), stroke(2, ball_type="推撲球", backhand="")])
    assert records[1]["family"] == "other" and records[1]["side"] == "unknown"
    assert not records[1]["label_eligible"]


def test_nonmonotonic_frames_invalidate_both_affected_rallies():
    rows = [
        stroke(server="3"),
        stroke(
            server="3", rally="2", start_frame="9", end_frame="15", roundscore_AB="2"
        ),
    ]
    records, _ = normalize(rows)
    assert all(
        "duplicate_or_reversed_source_frames" in r["rally_issues"] for r in records
    )
    assert all(not r["label_eligible"] for r in records)


@pytest.mark.parametrize(
    "failure,issue",
    [
        ("comment", "source_segment_problem_flag"),
        ("terminal", "missing_or_misplaced_terminal_marker"),
        ("discontinuous", "discontinuous_shot_intervals"),
        ("outside", "shot_outside_rally_window"),
        ("score", "inconsistent_rally_score"),
        ("order", "incomplete_or_duplicate_stroke_order"),
    ],
)
def test_rally_quality_propagates_to_all_strokes(failure, issue):
    rows = [stroke(), stroke(2)]
    changes = {}
    if failure == "comment":
        changes["Comment"] = "1"
    elif failure == "terminal":
        rows[-1]["server"] = "2"
    elif failure == "discontinuous":
        rows[0]["end_frame"] = "19"
    elif failure == "outside":
        changes["End"] = "25"
    elif failure == "score":
        rows[1]["roundscore_AB"] = "2"
    elif failure == "order":
        rows[1]["ball_round"] = "1"
    records, rallies = normalize(rows, **changes)
    assert issue in rallies[0]["issues"]
    assert all(issue in r["rally_issues"] and not r["label_eligible"] for r in records)


def csv_bytes(rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


def catalog(tmp_path):
    source = tmp_path / "source"
    blobs = {
        "README.md": b"Source fixture, not actual match labels",
        "Match.csv": csv_bytes([{"id": "1", "name": "fixture", "set": "2"}]),
        "Match 001/label/set1.csv": csv_bytes([stroke(), stroke(2)]),
        "Match 001/label/set2.csv": csv_bytes(
            [stroke(start_frame="60", end_frame="70", server="3")]
        ),
        "Match 001/RallySeg.csv": csv_bytes(
            [
                {"Score": "1_01_00", "Start": "5", "End": "50", "Comment": "0"},
                {"Score": "2_01_00", "Start": "55", "End": "80", "Comment": "0"},
                {"Score": "2_02_00", "Start": "90", "End": "100", "Comment": "0"},
            ]
        ),
    }
    for name, body in blobs.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    spec = pinned_source() | {
        "files": {name: blob_sha(body) for name, body in blobs.items()},
        "splits": {"train": [1], "validation": [], "test": []},
    }
    return source, spec


def test_verified_import_is_deterministic_keeps_orphans_and_preserves_sources(tmp_path):
    source, spec = catalog(tmp_path)
    before = {
        p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
    }
    destination = tmp_path / "normalized"
    first = import_doubles(source, destination, manifest=spec)
    after = {p.name: p.read_bytes() for p in destination.iterdir()}
    assert import_doubles(source, destination, manifest=spec) == first
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == after
    assert {
        p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
    } == before
    assert first["record_count"] == 3 and first["rally_count"] == 3
    assert first["single_stroke_terminal_serves"] == 1
    assert first["training_ready_records"] == 0
    assert first["rally_issue_counts"]["missing_stroke_labels"] == 1
    records = [
        json.loads(line)
        for line in (destination / "strokes.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert all("frame" not in r and "time_s" not in r for r in records)
    with pytest.raises(ValueError, match="outside"):
        import_doubles(source, source / "overwritten", manifest=spec)


def test_tampering_duplicate_splits_and_unpinned_files_fail(tmp_path):
    source, spec = catalog(tmp_path)
    bad = deepcopy(spec)
    bad["splits"]["test"] = [1]
    with pytest.raises(ValueError, match="multiple splits"):
        import_doubles(source, tmp_path / "out", manifest=bad)
    bad = deepcopy(spec)
    bad["files"].pop("Match 001/label/set2.csv")
    with pytest.raises(ValueError, match="unpinned"):
        import_doubles(source, tmp_path / "out", manifest=bad)
    (source / "Match.csv").write_bytes(b"tampered source")
    with pytest.raises(ValueError, match="hash mismatch"):
        import_doubles(source, tmp_path / "out", manifest=spec)


def test_changed_dataset_version_requires_a_new_output_directory(tmp_path):
    source, spec = catalog(tmp_path)
    target = tmp_path / "out"
    import_doubles(source, target, manifest=spec)
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    with pytest.raises(ValueError, match="new directory"):
        import_doubles(source, target, manifest=spec | {"mapping_version": 2})
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before
