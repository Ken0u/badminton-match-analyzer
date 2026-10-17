import csv
import io
import json

import pytest
from badminton.datasets import (
    blob_sha,
    frame_rate_evidence,
    import_shuttleset,
    normalize_set,
    pinned_source,
    source_path,
)


def stroke(order=1, frame=100, **changes):
    return {
        "rally": "1",
        "ball_round": str(order),
        "frame_num": str(frame),
        "time": "00:00:04",
        "player": "A",
        "type": "發短球" if order == 1 else "挑球",
        "server": "1" if order == 1 else "3",
        "backhand": "",
        "aroundhead": "",
        "flaw": "",
    } | changes


def normalize(rows, **kwargs):
    return normalize_set(rows, {"id": "1"}, 1, "train", **kwargs)


def test_source_side_convention_and_terminal_stroke_are_preserved_without_inventing_end():
    source = [stroke(), stroke(2, 125, backhand="1.0")]
    result = normalize(source)
    assert result[0]["kind"] == "serve" and result[0]["family"] is None
    assert result[0]["side"] == "forehand" and result[1]["side"] == "backhand"
    assert result[1]["kind"] == "shot" and result[1]["terminal_stroke_marker"]
    assert all(row["family_eligible"] and row["side_eligible"] for row in result)
    assert all(row["media_alignment"] == "unverified" for row in result)
    assert [r["raw"] for r in result] == source
    assert not any("frame" in row or "time_s" in row for row in result)
    around = normalize([stroke(aroundhead="1")])[0]
    assert around["around_head"] and around["side"] == "forehand"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"backhand": "nan"}, "invalid_or_conflicting_side_flags"),
        ({"backhand": "1", "aroundhead": "1"}, "invalid_or_conflicting_side_flags"),
        ({"frame_num": "100.2"}, "invalid_source_frame_or_time"),
        ({"time": "00:60:04"}, "invalid_source_frame_or_time"),
        ({"type": "mystery"}, "unresolved_source_type"),
        ({"player": "C"}, "unknown_source_player"),
    ],
)
def test_ambiguous_or_malformed_labels_remain_visible_and_ineligible(changes, reason):
    source = stroke(**changes)
    record = normalize([source])[0]
    assert reason in record["issues"]
    assert not record["family_eligible"] and not record["side_eligible"]
    assert record["raw"] == source


def test_flaw_and_published_correction_exclude_entire_rally_without_changing_labels():
    rows = [stroke(), stroke(2, 125, flaw="1"), stroke(1, 160, rally="2")]
    result = normalize(rows)
    assert not result[0]["family_eligible"] and not result[1]["family_eligible"]
    assert result[2]["family_eligible"]
    issue = {
        "match": "1",
        "set": "1",
        "rally": "2",
        "reason": "time gap",
        "measure": "modified",
    }
    result = normalize(rows, known_issues=[issue])
    assert "published_issue: time gap" in result[2]["issues"]
    assert result[2]["source_frame"] == 160


def test_duplicate_and_reversed_contacts_quarantine_both_affected_rallies():
    records = normalize([stroke(), stroke(2, 100), stroke(1, 90, rally="2")])
    assert all(not row["family_eligible"] for row in records)
    assert "duplicate_source_frame" in records[0]["issues"]
    assert "nonmonotonic_source_frames" in records[-1]["issues"]


def test_frame_rate_diagnostic_detects_25_fps_instead_of_assuming_paper_rate():
    records = [
        {"source_frame": f, "source_time_s": t}
        for f, t in [(11496, 459), (11900, 476), (44700, 1788)]
    ]
    report = frame_rate_evidence(records)
    assert report["candidate_fps"] == 25
    assert "does not verify" in report["meaning"]
    assert (
        next(c for c in report["candidates"] if c["fps"] == 30)["consistent_rows"] == 0
    )
    assert frame_rate_evidence([])["candidate_fps"] is None


@pytest.fixture
def snapshot(tmp_path):
    root = tmp_path / "source"
    files = {}

    def write(relative, rows):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        data = text.getvalue().encode()
        path.write_bytes(data)
        files[relative] = blob_sha(data)

    write(
        "ShuttleSet/set/match.csv",
        [
            {
                "id": "1",
                "video": "one",
                "set": "2",
                "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
            }
        ],
    )
    for index in (1, 2):
        write(f"ShuttleSet/set/one/set{index}.csv", [stroke(), stroke(2, 125)])
    spec = {
        "files": files,
        "splits": {"train": [1], "test": [], "validation": [], "quarantine": []},
        "references": [],
        "mapping_version": 1,
        "repository": "fixture",
        "commit": "a" * 40,
        "split_source": {"meaning": "test fixture"},
        "side_policy": "source convention",
    }
    return root, tmp_path / "normalized", spec


def test_import_is_deterministic_verifies_inputs_and_keeps_media_unverified(snapshot):
    source, target, spec = snapshot
    first = import_shuttleset(source, target, manifest=spec)
    data = (target / "strokes.jsonl").read_bytes()
    second = import_shuttleset(source, target, manifest=spec)
    assert first == second and data == (target / "strokes.jsonl").read_bytes()
    assert first["record_count"] == 4 and first["rally_count"] == 2
    assert (
        first["family_eligible_records"] == 4 and first["training_ready_records"] == 0
    )
    assert len({json.loads(line)["id"] for line in data.splitlines()}) == 4
    (source / "ShuttleSet/set/one/set2.csv").write_bytes(b"modified source")
    with pytest.raises(ValueError, match="hash mismatch"):
        import_shuttleset(source, target, manifest=spec)
    assert (target / "strokes.jsonl").read_bytes() == data


def test_original_match_cannot_cross_splits_or_write_into_immutable_source(snapshot):
    source, target, spec = snapshot
    spec["splits"]["test"] = [1]
    with pytest.raises(ValueError, match="multiple splits"):
        import_shuttleset(source, target, manifest=spec)
    spec["splits"]["test"] = []
    with pytest.raises(ValueError, match="immutable source"):
        import_shuttleset(source, source / "normalized", manifest=spec)
    with pytest.raises(ValueError, match="inside"):
        source_path(source, "../escape.csv")


def test_pinned_splits_and_label_contract_cover_original_matches_without_overlap():
    spec = pinned_source()
    ids = [i for group in spec["splits"].values() for i in group]
    assert sorted(ids) == list(range(1, 45)) and len(set(ids)) == 44
    assert spec["splits"]["quarantine"] == [9, 10, 12, 27]
    assert len(spec["files"]) == 107
    assert spec["commit"] == "45517f7d4cb936b03f3eabf939cc7959d39226fe"
