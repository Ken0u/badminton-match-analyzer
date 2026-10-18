import copy
import hashlib
import json

import pytest
from badminton.finebadminton_data import (
    import_finebadminton,
    normalize_match,
    parallel_references,
    pinned_source,
)


def hit(family="kill", side=None, **changes):
    return {
        "start_frame": 100,
        "end_frame": 120,
        "player": "Player A",
        "Foundational Actions Level": {"hit type": family, "hitter": "top"},
        "Tactical Semantics Level": {"player actions": side or ["forehand"]},
    } | changes


def rally(*hits, **changes):
    return {
        "video": "0011.mp4",
        "start_frame": 100,
        "end_frame": 150,
        "duration_frames": 51,
        "fps": 25.0,
        "hitting": list(hits) or [hit()],
    } | changes


def publication(**changes):
    stroke = {
        "start_frame": 100,
        "end_frame": 120,
        "hit_frame": 107,
        "player": "Player A",
        "hit_type": "kill",
        "player_actions": ["forehand"],
    } | changes
    english = [rally(stroke, video="0011_001.mp4")]
    chinese = copy.deepcopy(english)
    chinese[0]["hitting"][0]["hit_type"] = "杀球"
    chinese[0]["hitting"][0]["player_actions"] = ["正手击球"]
    return chinese, english


def test_paired_translation_distinguishes_smash_net_kill_and_non_target_strokes():
    raw = rally(*(hit(family) for family in ("kill", "net kill", "push shot", "block")))
    before = copy.deepcopy(raw)
    records = normalize_match([raw], "0011")
    assert [r["family"] for r in records] == ["smash", "other", "other", "other"]
    assert all(r["side"] == "forehand" for r in records)
    assert raw == before
    assert all(r["raw"] == h for r, h in zip(records, raw["hitting"]))


def test_action_intervals_do_not_manufacture_contacts_or_rally_end_events():
    records = normalize_match([rally(hit("serve"), hit("net lift"))], "0011")
    assert [r["kind"] for r in records] == ["serve", "shot"]
    assert records[0]["family"] is None and records[1]["family"] == "lift"
    for row in records:
        assert row["source_action_interval"] == (100, 120)
        assert row["source_contact_frame"] is None
        assert row["media_alignment"] == "unverified"
        assert row["contact_adjudication"] == "unverified"
        assert row["training_ready"] is False and row["split"] == "unassigned"
        assert "frame" not in row and "time_s" not in row


def test_court_end_and_around_head_do_not_imply_stroke_side():
    row = normalize_match([rally(hit("clear", ["over head", "cross-court"]))], "0011")[
        0
    ]
    assert row["source_court_end"] == "top" and row["side"] == "unknown"
    assert row["family_eligible"] and not row["side_eligible"]
    conflict = normalize_match([rally(hit(side=["backhand", "forehand"]))], "0011")[0]
    assert conflict["side"] == "unknown" and not conflict["side_eligible"]


def test_exact_join_retains_published_contact_and_both_raw_publications():
    chinese, english = publication()
    references = parallel_references(chinese, english)
    row = normalize_match([rally()], "0011", references)[0]
    assert row["source_contact_frame"] == 107
    assert row["raw_contact_reference"]["original"] == chinese[0]["hitting"][0]
    assert row["raw_contact_reference"]["translated"] == english[0]["hitting"][0]
    assert row["training_ready"] is False


@pytest.mark.parametrize(
    "field,value", [("hit_frame", 108), ("player", "Other"), ("hit_type", "drive")]
)
def test_parallel_disagreement_cannot_silently_join(field, value):
    chinese, english = publication()
    english[0]["hitting"][0][field] = value
    with pytest.raises(ValueError, match="stroke identity"):
        parallel_references(chinese, english)


def test_shifted_or_orphaned_published_references_are_rejected():
    references = parallel_references(*publication())
    with pytest.raises(ValueError, match="no released stroke"):
        normalize_match([rally(start_frame=99)], "0011", references)
    with pytest.raises(ValueError, match="disagrees"):
        normalize_match([rally(hit("drive"))], "0011", references)
    with pytest.raises(ValueError, match="multiple"):
        normalize_match([rally(), rally()], "0011", references)


def test_malformed_and_outside_intervals_are_retained_and_ineligible():
    missing = hit()
    del missing["start_frame"]
    rows = normalize_match(
        [rally(missing, hit(start_frame=90), hit(start_frame=True))], "0011"
    )
    assert len(rows) == 3
    assert all(not r["family_eligible"] and not r["side_eligible"] for r in rows)
    assert rows[0]["raw"] == missing
    assert rows[1]["source_action_interval"] == (90, 120)
    assert "action_outside_rally" in rows[1]["issues"]


def test_bilingual_side_conflicts_fail_and_release_omissions_are_not_filled():
    chinese, english = publication()
    english[0]["hitting"][0]["player_actions"] = ["backhand"]
    with pytest.raises(ValueError, match="stroke side"):
        parallel_references(chinese, english)
    references = parallel_references(*publication())
    row = normalize_match([rally(hit(side=["over head"]))], "0011", references)[0]
    assert row["side"] == "unknown" and row["published_contact_side"] == "forehand"
    assert "published_side_disagrees_with_release" in row["issues"]
    assert row["family_eligible"] and not row["side_eligible"]


def test_unknown_bilingual_family_is_rejected_instead_of_joining_nulls():
    chinese, english = publication()
    del chinese[0]["hitting"][0]["hit_type"]
    del english[0]["hitting"][0]["hit_type"]
    with pytest.raises(ValueError, match="stroke identity"):
        parallel_references(chinese, english)


def test_duration_conventions_and_nonstandard_fps_are_preserved_without_retiming():
    rows = normalize_match(
        [rally(duration_frames=n, fps=24.635218809072505) for n in (51, 50, 77)],
        "0011",
    )
    assert [r["rally_duration_convention"] for r in rows] == [
        "inclusive",
        "exclusive",
        "inconsistent",
    ]
    assert all(r["source_declared_fps"] == 24.635218809072505 for r in rows)
    assert all(r["source_action_interval"] == (100, 120) for r in rows)


def spec_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    chinese, english = publication()
    entries = []
    for name, rows in (
        ("zh.json", chinese),
        ("en.json", english),
        ("0011.json", [rally()]),
    ):
        data = json.dumps(rows).encode()
        (source / name).write_bytes(data)
        entries.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    spec = {
        "dataset": "Finebadminton-20K",
        "normalization_version": 1,
        "parallel_files": entries[:2],
        "files": [entries[2] | {"match_id": "0011"}],
    }
    return source, spec


def test_import_checks_source_bytes_and_refuses_changed_mapping_output(tmp_path):
    source, spec = spec_files(tmp_path)
    output = tmp_path / "normalized"
    result = import_finebadminton(source, output, spec=spec)
    assert result["record_count"] == result["published_contact_records"] == 1
    assert result["training_ready_records"] == 0
    records = (output / "records.json").read_bytes()
    assert import_finebadminton(source, output, spec=spec) == result
    assert (output / "records.json").read_bytes() == records
    with pytest.raises(ValueError, match="different source/mapping"):
        import_finebadminton(source, output, spec=spec | {"normalization_version": 2})
    (source / "0011.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="source hash mismatch"):
        import_finebadminton(source, tmp_path / "new", spec=spec)


def test_pinned_manifest_has_unique_paths_and_all_author_media_hashes():
    spec = pinned_source()
    assert len(spec["files"]) == 70 and len(spec["parallel_files"]) == 2
    assert len({r["match_id"] for r in spec["files"]}) == 70
    assert len({r["path"] for r in spec["files"]}) == 70
    assert all(len(r["sha256"]) == len(r["media_sha256"]) == 64 for r in spec["files"])
    assert all(0 < r["media_bytes"] < 2 * 1024**3 for r in spec["files"])
