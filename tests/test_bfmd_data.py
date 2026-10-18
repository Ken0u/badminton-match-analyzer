import copy
import hashlib
import json

import pytest
from badminton import bfmd_data
from badminton.bfmd_data import import_bfmd, normalize_timeline


def marker(label, start=30, end=None, origin="manual", **extra):
    return {
        "id": "source-id",
        "type": "timelinelabels",
        "origin": origin,
        "value": {
            "timelinelabels": [label],
            "ranges": [{"start": start, "end": start if end is None else end}],
        },
        **extra,
    }


def task(*results, predictions=None, **annotation):
    return {
        "id": 17,
        "data": {"video": "/untrusted/source/video.mp4"},
        "annotations": [{"result": list(results), **annotation}],
        "predictions": predictions or [],
    }


def normalized(*results, **kwargs):
    return normalize_timeline(
        task(marker("Rally", 0, 100), *results, **kwargs), "match", "singles"
    )[0]


def fixture(tmp_path, *, mode="singles", results=None, metadata=None, flat=False):
    source = tmp_path / "source"
    source.mkdir()
    category = "shot_type" if mode == "singles" else "hits_doubles"
    data = {
        "Badminton_video_list.csv": f"match_name,type,youtube_url,status\nmatch,{mode},https://www.youtube.com/watch?v=abcdefghijk,VERIFIED\n".encode(),
        "match_index.csv": b"match_name,num_rallies\nmatch,1\nTOTAL,1\n",
        f"annotations/{category}/match.json": json.dumps(
            task(
                *(results or [marker("Rally", 0, 100), marker("hit"), marker("clear")])
            )
        ).encode(),
    }
    if metadata is not None:
        data["annotations/metadata/match.json"] = json.dumps(metadata).encode()
    files = []
    for i, (name, raw) in enumerate(data.items()):
        download = f"download-{i}.dat"
        path = source / (download if flat else name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        files.append(
            {
                "path": name,
                "download_name": download,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    spec = {
        "dataset": "generated BFMD fixture",
        "normalization_version": 1,
        "rights": "fixture, not source data",
        "expected": {
            "files": len(files),
            "matches": 1,
            "annotation_results": len((results or [0, 1, 2])),
            "metadata_matches": int(metadata is not None),
        },
        "files": files,
    }
    return source, spec


def test_manual_contact_family_join_keeps_source_frame_without_claiming_exact_clock():
    raw = task(marker("Rally", 0, 100), marker("hit"), marker("clear"))
    before = copy.deepcopy(raw)
    records, header = normalize_timeline(raw, "match", "singles")
    hit = records[1]
    assert hit["source_contact_frame"] == 30 and hit["family"] == "clear"
    assert hit["contact_label_eligible"] and hit["family_eligible"]
    assert not records[2]["family_eligible"]  # One target, not two duplicate contacts.
    assert hit["source_frame_base"].startswith("undocumented")
    assert hit["media_alignment"] == hit["contact_adjudication"] == "unverified"
    assert hit["side"] == "unknown" and hit["player_id"] is None
    assert not hit["training_ready"] and not hit["side_eligible"]
    assert "time_s" not in hit and "frame" not in hit and "rally_end_frame" not in hit
    assert raw == before and header["task"] == {"id": 17, "data": raw["data"]}


def test_conflicting_family_markers_do_not_erase_independent_contact_support():
    records = normalized(marker("hit"), marker("clear"), marker("lift"))
    hit = records[1]
    assert hit["contact_label_eligible"] and not hit["family_eligible"]
    assert hit["family"] == "unknown" and hit["source_types_at_point"] == [
        "clear",
        "lift",
    ]
    assert "conflicting_source_types_at_frame" in hit["issues"]
    assert len(records) == 4


def test_unknown_source_type_cannot_be_hidden_by_a_known_family_at_the_same_frame():
    hit = normalized(marker("hit"), marker("clear"), marker("new_unmapped_type"))[1]
    assert hit["contact_label_eligible"] and not hit["family_eligible"]
    assert (
        hit["family"] == "unknown"
        and "unresolved_source_labels_at_frame" in hit["issues"]
    )


@pytest.mark.parametrize(
    "label,family,kind",
    [
        ("net_shot", "net", "shot"),
        ("net_kill", "other", "shot"),
        ("block", "other", "shot"),
        ("serve", None, "serve"),
        ("flick_serve", None, "serve"),
    ],
)
def test_taxonomy_preserves_serves_and_other_actions_without_inventing_target_classes(
    label, family, kind
):
    hit = normalized(marker("hit"), marker(label))[1]
    assert hit["family_eligible"] and hit["family"] == family and hit["kind"] == kind


def test_prediction_origin_inside_annotations_never_becomes_manual_truth():
    rows = normalized(marker("hit", origin="prediction"), marker("clear"))
    assert (
        rows[1]["source_container"] == "annotations"
        and not rows[1]["contact_label_eligible"]
    )
    assert not rows[1]["family_eligible"] and rows[1]["raw"]["origin"] == "prediction"


def test_inferred_rally_cannot_certify_live_context_for_a_manual_contact():
    rows = normalized(
        marker("Rally", 150, 300, origin="prediction"),
        marker("hit", 200),
        marker("clear", 200),
    )
    hit = rows[2]
    assert hit["active_manual"] and not hit["contact_label_eligible"]
    assert "contact_outside_source_rally" in hit["issues"]
    assert (
        rows[1]["source_interval"] == [150, 300]
        and not rows[1]["source_label_eligible"]
    )


def test_prediction_container_and_cancelled_annotation_are_preserved_but_not_supervision():
    rows = normalized(
        marker("hit"),
        marker("clear"),
        was_cancelled=True,
        predictions=[{"result": [marker("hit"), marker("smash")]}],
    )
    assert len(rows) == 5 and all(not r["contact_label_eligible"] for r in rows)
    assert (
        rows[-1]["source_container"] == "predictions"
        and rows[-1]["raw"]["origin"] == "manual"
    )


@pytest.mark.parametrize(
    "start,end", [(None, None), (-1, 2), (1.5, 2), (True, 2), ("1", 2), (40, 30)]
)
def test_invalid_ranges_remain_visible_and_cannot_supply_contacts(start, end):
    item = marker("hit")
    item["value"]["ranges"] = [{"start": start, "end": end}]
    row = normalized(item)[1]
    assert row["raw"] == item and row["source_interval"] is None
    assert not row["contact_label_eligible"]


def test_nonpoint_duplicate_and_outside_rally_contacts_are_not_silently_repaired():
    rows = normalized(
        marker("hit", 20, 21), marker("hit", 30), marker("hit", 30), marker("hit", 101)
    )
    assert len(rows) == 5 and all(not r["contact_label_eligible"] for r in rows)
    assert "nonpoint_contact_marker" in rows[1]["issues"]
    assert "duplicate_source_hit_frame" in rows[2]["issues"]
    assert "contact_outside_source_rally" in rows[4]["issues"]
    assert rows[1]["source_contact_frame"] is None and rows[4]["source_interval"] == [
        101,
        101,
    ]


def test_choice_intervals_empty_ranges_and_multiple_ranges_survive_without_fake_contacts():
    choice = {
        "type": "choices",
        "origin": "manual",
        "value": {"choices": ["smash"], "ranges": [{"start": 20, "end": 40}]},
    }
    empty = marker("hit")
    empty["value"]["ranges"] = []
    multi = marker("replay")
    multi["value"]["ranges"] = [{"start": 50, "end": 60}, {"start": 70, "end": 80}]
    rows = normalized(choice, empty, multi)
    assert len(rows) == 5 and len({r["id"] for r in rows}) == 5
    assert rows[1]["source_choices"] == ["smash"] and rows[1]["source_interval"] == [
        20,
        40,
    ]
    assert all(not r["family_eligible"] for r in rows)
    assert "invalid_source_frame_interval" in rows[2]["issues"]


def test_model_family_marker_does_not_poison_a_manual_family_or_fill_missing_manual_types():
    rows = normalized(
        marker("hit"), marker("clear"), marker("smash", origin="prediction")
    )
    assert rows[1]["family"] == "clear" and rows[1]["family_eligible"]
    hit = normalized(marker("hit"), marker("clear", origin="prediction"))[1]
    assert hit["contact_label_eligible"] and not hit["family_eligible"]


@pytest.mark.parametrize("label", ["hit", "clear", "Rally"])
def test_result_type_mismatch_cannot_supply_contact_family_or_rally_support(label):
    bad = marker(label, 0 if label == "Rally" else 30, 100 if label == "Rally" else 30)
    bad["type"] = "choices"
    if label == "Rally":
        records, _ = normalize_timeline(
            task(bad, marker("hit"), marker("clear")), "match", "singles"
        )
        assert not records[1]["contact_label_eligible"]
    elif label == "hit":
        assert not normalized(bad, marker("clear"))[1]["contact_label_eligible"]
    else:
        assert not normalized(marker("hit"), bad)[1]["family_eligible"]


def test_source_live_replay_overlap_is_retained_but_cannot_be_used_as_live_contact_truth():
    records = normalized(marker("replay", 20, 40), marker("hit"), marker("clear"))
    assert not records[2]["contact_label_eligible"]
    assert "conflicting_source_live_replay_context" in records[0]["issues"]
    assert (
        records[1]["source_interval"] == [20, 40]
        and not records[1]["source_label_eligible"]
    )


def test_cli_bad_hash_fails_without_creating_partial_outputs(
    tmp_path, monkeypatch, capsys
):
    from badminton import cli

    source, spec = fixture(tmp_path)
    spec["files"][0]["sha256"] = "0" * 64
    monkeypatch.setattr(bfmd_data, "pinned_source", lambda: spec)
    monkeypatch.setattr(
        "sys.argv",
        ["badminton", "import-bfmd", str(source), "--output", str(tmp_path / "index")],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2 and "source hash mismatch" in capsys.readouterr().err
    assert not (tmp_path / "index").exists()


@pytest.mark.parametrize("flat", [False, True])
def test_pinned_import_preserves_metadata_disagreement_and_is_byte_identical_on_repeat(
    tmp_path, flat
):
    metadata = [
        {
            "match_name": "match",
            "auto_extracted": {"num_rallies": 2},
            "games": {
                "game1": {
                    "rallies": [{"start": 0, "end": 100}, {"start": 200, "end": 300}]
                }
            },
        }
    ]
    source, spec = fixture(tmp_path, metadata=metadata, flat=flat)
    output = tmp_path / "index"
    report = import_bfmd(source, output, spec=spec)
    assert report["record_count"] == 3 and report["source_result_count"] == 3
    assert (
        report["metadata_only_intervals"] == 1 and report["metadata_rally_count"] == 2
    )
    assert report["metadata_singleton_wrappers"] == ["annotations/metadata/match.json"]
    assert (
        report["contact_label_eligible_records"]
        == report["family_eligible_records"]
        == 1
    )
    assert report["training_ready_records"] == report["side_eligible_records"] == 0
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert import_bfmd(source, output, spec=spec) == report
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}
    rallies = json.loads((output / "metadata_rallies.json").read_text())
    assert (
        rallies[1]["source_interval"] == [200, 300] and not rallies[1]["training_ready"]
    )


@pytest.mark.parametrize("problem", ["bytes", "hash", "counts", "traversal"])
def test_bad_source_fails_before_any_output(tmp_path, problem):
    source, spec = fixture(tmp_path)
    if problem == "bytes":
        spec["files"][0]["bytes"] += 1
    elif problem == "hash":
        spec["files"][0]["sha256"] = "0" * 64
    elif problem == "counts":
        spec["expected"]["annotation_results"] += 1
    else:
        spec["files"][0]["download_name"] = "../elsewhere"
    with pytest.raises(ValueError):
        import_bfmd(source, tmp_path / "index", spec=spec)
    assert not (tmp_path / "index").exists()


def test_conflicting_duplicate_local_source_copy_is_not_hidden_by_canonical_path(
    tmp_path,
):
    source, spec = fixture(tmp_path)
    (source / spec["files"][0]["download_name"]).write_bytes(b"different")
    with pytest.raises(ValueError, match="source size mismatch"):
        import_bfmd(source, tmp_path / "index", spec=spec)


def test_changed_partial_and_locked_outputs_are_preserved(tmp_path):
    source, spec = fixture(tmp_path)
    output = tmp_path / "index"
    import_bfmd(source, output, spec=spec)
    (output / "events.jsonl").write_bytes(b"do not overwrite reviewed edits")
    with pytest.raises(ValueError, match="changed or another version"):
        import_bfmd(source, output, spec=spec)
    assert (output / "events.jsonl").read_bytes() == b"do not overwrite reviewed edits"
    lock = output / ".bfmd-import.lock"
    lock.write_text("existing-owner")
    with pytest.raises(ValueError, match="import lock"):
        import_bfmd(source, output, spec=spec)
    assert lock.read_text() == "existing-owner"


def test_source_output_overlap_and_mutation_during_import_are_rejected(
    tmp_path, monkeypatch
):
    source, spec = fixture(tmp_path)
    with pytest.raises(ValueError, match="outside the immutable"):
        import_bfmd(source, source / "output", spec=spec)
    original = bfmd_data._read_source

    def mutate(root, entries):
        result = original(root, entries)
        (source / entries[0]["path"]).write_bytes(b"changed during import")
        return result

    monkeypatch.setattr(bfmd_data, "_read_source", mutate)
    with pytest.raises(ValueError, match="source size mismatch"):
        import_bfmd(source, tmp_path / "index", spec=spec)
    assert not (tmp_path / "index").exists()


def test_cli_import_never_opens_app_store_or_perception(tmp_path, monkeypatch, capsys):
    from badminton import cli

    source, spec = fixture(tmp_path, mode="doubles")
    monkeypatch.setattr(bfmd_data, "pinned_source", lambda: spec)
    monkeypatch.setattr(
        cli, "Store", lambda *_: pytest.fail("Offline import opened app Store")
    )
    monkeypatch.setattr(
        "sys.argv",
        ["badminton", "import-bfmd", str(source), "--output", str(tmp_path / "index")],
    )
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["match_count"] == 1 and result["training_ready_records"] == 0


@pytest.mark.parametrize(
    "raw", [b'{"id":1,"id":2}', b'{"frame":NaN}', b'{"frame":Infinity}']
)
def test_ambiguous_or_nonfinite_json_is_not_silently_normalized(raw):
    with pytest.raises(ValueError):
        bfmd_data._json(raw)
