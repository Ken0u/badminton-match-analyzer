"""Generated revision cases test accounting, ambiguity and preservation."""

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from badminton import shuttle_label_comparison as comparison

HEADER = "Frame,Visibility,X,Y\n"
ROWS = "0,1,5,8\n1,0,0,0\n2,1,7,9\n"
CSV = (HEADER + ROWS).encode()
ROOT = Path(__file__).resolve().parents[1]


def basis(**changes):
    return {
        "source_sha256": hashlib.sha256(b"generated source identity only").hexdigest(),
        "evidence_sha256": hashlib.sha256(b"generated basis declaration").hexdigest(),
        "frame_count": 3,
        "width": 1280,
        "height": 720,
        "rotation": 0,
        "ordinal_origin": 0,
        "coordinate_space": "source_pixels",
        **changes,
    }


def descriptor(root, path, raw=CSV, native_basis=True):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(raw)
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "basis": basis() if native_basis is True else native_basis,
    }


def case(root, key="sample", original=CSV, revised=CSV):
    return {
        "case_id": key,
        "original": descriptor(root, key + "/a.csv", original)
        if original is not None
        else None,
        "revised": descriptor(root, key + "/b.csv", revised)
        if revised is not None
        else None,
        "quarantine_reasons": [],
    }


def run(root, cases):
    inventory = root / "inventory.json"
    inventory.write_bytes(comparison.encoded({"schema_version": 1, "cases": cases}))
    return comparison.compare_inventory(inventory, root)


def test_nine_frozen_baseline_cases_retain_denominators(tmp_path):
    cases = [
        case(tmp_path, "unchanged"),
        case(
            tmp_path,
            "changed",
            revised=(HEADER + "0,0,0,0\n1,1,5,6\n2,1,9,9\n").encode(),
        ),
        case(
            tmp_path, "unknown_visibility", original=CSV.replace(b"0,1,5,8", b"0,2,5,8")
        ),
        case(
            tmp_path, "missing_tail", original=(HEADER + "0,1,5,8\n1,0,0,0\n").encode()
        ),
        case(
            tmp_path,
            "duplicate",
            original=(HEADER + "0,1,5,8\n0,0,0,0\n1,1,7,9\n").encode(),
        ),
        case(
            tmp_path,
            "reversed",
            original=(HEADER + "0,1,5,8\n2,1,7,9\n1,0,0,0\n").encode(),
        ),
        case(tmp_path, "basis_conflict"),
        case(tmp_path, "unavailable_original", original=None),
        case(
            tmp_path, "invalid_ordinal", original=CSV.replace(b"0,1,5,8", b"True,1,5,8")
        ),
    ]
    cases[6]["revised"]["basis"]["source_sha256"] = "a" * 64
    report = run(tmp_path, cases)
    assert report["summary"]["cases"] == 9
    assert report["summary"]["compared_cases"] == 3
    assert report["summary"]["unscored_cases"] == 6
    assert report["summary"]["original"] == {
        "known_records": 23,
        "known_record_count_cases": 8,
        "unknown_record_count_cases": 1,
    }
    assert report["summary"]["revised"]["known_records"] == 27
    results = {r["case_id"]: r for r in report["cases"]}
    unchanged = results["unchanged"]
    assert unchanged["byte_equal"] is True
    assert unchanged["comparison"] == {
        "declared_native_frame_pairs": 3,
        "visibility_pairs": 3,
        "unscored_pairs": 0,
        "visibility_transitions": {"0_to_0": 1, "1_to_1": 2},
        "visible_coordinate_pairs": 2,
        "coordinate_changes": 0,
    }
    changed = results["changed"]["comparison"]
    assert changed["visibility_transitions"] == {"1_to_0": 1, "0_to_1": 1, "1_to_1": 1}
    assert changed["visible_coordinate_pairs"] == changed["coordinate_changes"] == 1
    unknown = results["unknown_visibility"]
    assert unknown["original"]["issues"]["unknown_visibility"] == 1
    assert unknown["comparison"]["visibility_pairs"] == 2
    assert unknown["comparison"]["unscored_pairs"] == 1
    assert results["missing_tail"]["ordinal_inventory"]["only_revised"] == 1
    assert results["missing_tail"]["original"]["unlabelled_tail_frames"] == 1
    assert results["duplicate"]["original"]["duplicate_records"] == 2
    assert results["reversed"]["original"]["reversals"] == 1
    assert results["basis_conflict"]["unscored_reasons"] == [
        "conflicting_declared_native_basis"
    ]
    for key in (
        "missing_tail",
        "duplicate",
        "reversed",
        "basis_conflict",
        "unavailable_original",
        "invalid_ordinal",
    ):
        assert results[key]["comparison"] is None
    assert set(report["eligibility"].values()) == {False}
    assert report["protocol_sha256"] == comparison.digest(
        comparison.encoded(comparison.PROTOCOL)
    )


@pytest.mark.parametrize("number", ["-1", "1.0", "true", "", "1e0", "0" * 19])
def test_bad_ordinal_is_retained_and_not_reindexed(tmp_path, number):
    item = case(
        tmp_path, original=CSV.replace(b"0,1,5,8", (number + ",1,5,8").encode())
    )
    result = run(tmp_path, [item])["cases"][0]
    assert result["original"]["record_count"] == 3
    assert result["original"]["invalid_ordinal_records"] == 1
    assert result["comparison"] is None


def test_reversal_is_detected_across_an_invalid_ordinal(tmp_path):
    raw = (HEADER + "2,1,5,8\n?,1,5,8\n0,1,7,9\n").encode()
    result = run(tmp_path, [case(tmp_path, original=raw)])["cases"][0]
    assert result["original"]["reversals"] == 1
    assert result["original"]["record_count"] == 3


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"frame,Visibility,X,Y\n0,1,5,8\n",
        b"Frame,Visibility,X,Y\n\n",
        b"Frame,Visibility,X,Y\n0,1,5\n",
        b"Frame,Visibility,X,Y,extra\n0,1,5,8,x\n",
    ],
)
def test_empty_or_malformed_records_do_not_disappear(tmp_path, raw):
    result = run(tmp_path, [case(tmp_path, original=raw)])["cases"][0]
    assert result["original"]["record_count"] == (0 if raw == b"" else 1)
    assert result["comparison"] is None


@pytest.mark.parametrize("raw", [b"\xff", b'Frame,Visibility,X,Y\n"unterminated'])
def test_unparsed_records_are_unknown_not_zero(tmp_path, raw):
    report = run(tmp_path, [case(tmp_path, original=raw, revised=raw)])
    item = report["cases"][0]
    assert item["byte_equal"] is True
    assert item["original"]["record_count"] is None
    assert report["summary"]["original"]["known_records"] == 0
    assert report["summary"]["original"]["unknown_record_count_cases"] == 1
    assert item["comparison"] is None


@pytest.mark.parametrize(
    "coordinate", ["NaN", "Infinity", "-Infinity", "", "nope", "1280", "-1"]
)
def test_invalid_visible_coordinate_stays_in_pair_denominator(tmp_path, coordinate):
    result = run(
        tmp_path,
        [
            case(
                tmp_path,
                original=CSV.replace(b"0,1,5,8", f"0,1,{coordinate},8".encode()),
            )
        ],
    )["cases"][0]
    assert result["original"]["record_count"] == 3
    assert result["comparison"]["declared_native_frame_pairs"] == 3
    assert result["comparison"]["unscored_pairs"] == 1
    assert result["comparison"]["visibility_pairs"] == 2


def test_decimal_changes_below_float_resolution_are_not_hidden(tmp_path):
    a = CSV.replace(b"0,1,5,8", b"0,1,1.0000000000000001,8")
    b = CSV.replace(b"0,1,5,8", b"0,1,1.0,8")
    result = run(tmp_path, [case(tmp_path, original=a, revised=b)])["cases"][0]
    assert result["comparison"]["coordinate_changes"] == 1
    item = case(
        tmp_path,
        "equivalent",
        original=a,
        revised=a.replace(b"1.0000000000000001", b"1.00000000000000010"),
    )
    assert run(tmp_path, [item])["cases"][0]["comparison"]["coordinate_changes"] == 0


def test_invalid_invisible_coordinates_and_unknown_flags_are_not_negatives(tmp_path):
    raw = (HEADER + "0,0,3,4\n1,2,0,0\n2,1,7,9\n").encode()
    result = run(tmp_path, [case(tmp_path, original=raw)])["cases"][0]
    assert result["original"]["issues"]["invisible_nonzero_coordinate"] == 1
    assert result["original"]["issues"]["unknown_visibility"] == 1
    assert result["comparison"]["visibility_pairs"] == 1
    assert result["comparison"]["unscored_pairs"] == 2


def test_missing_gap_and_extra_ordinal_have_separate_raw_inventory_counts(tmp_path):
    raw = (HEADER + "0,1,5,8\n2,1,7,9\n3,1,2,3\n").encode()
    result = run(tmp_path, [case(tmp_path, original=raw)])["cases"][0]
    assert result["ordinal_inventory"] == {
        "union": 4,
        "shared": 2,
        "only_original": 1,
        "only_revised": 1,
    }
    assert result["original"]["native_missing_ordinals"] == 1
    assert result["original"]["unlabelled_tail_frames"] == 0
    assert result["comparison"] is None


@pytest.mark.parametrize(
    "change",
    [
        None,
        {"rotation": 90},
        {"ordinal_origin": 1},
        {"coordinate_space": "display_pixels"},
    ],
)
def test_basis_is_never_inferred_from_equal_names_or_bytes(tmp_path, change):
    item = case(tmp_path)
    item["original"]["basis"] = basis(**change) if change is not None else None
    result = run(tmp_path, [item])["cases"][0]
    assert result["byte_equal"] is True
    assert result["ordinal_inventory"]["shared"] == 3
    assert result["comparison"] is None


def test_explicit_pairing_does_not_guess_filename_aliases_or_remove_quarantine(
    tmp_path,
):
    a = descriptor(tmp_path, "1_02_07_ball.csv")
    b = descriptor(tmp_path, "2_02_07_ball.csv")
    item = {
        "case_id": "unresolved_alias",
        "original": a,
        "revised": b,
        "quarantine_reasons": ["unresolved_filename_mapping"],
    }
    result = run(tmp_path, [item])["cases"][0]
    assert result["byte_equal"] is True
    assert result["comparison"] is None
    assert "unresolved_filename_mapping" in result["unscored_reasons"]


def test_absent_and_hash_mismatched_inputs_preserve_case_and_known_rows(tmp_path):
    missing, changed = case(tmp_path, "missing"), case(tmp_path, "changed")
    (tmp_path / missing["original"]["path"]).unlink()
    (tmp_path / changed["original"]["path"]).write_bytes(
        b"unexpected labels not parsed"
    )
    report = run(
        tmp_path,
        [missing, changed, case(tmp_path, "none", original=None, revised=None)],
    )
    assert report["summary"]["cases"] == 3
    assert report["summary"]["unscored_cases"] == 3
    assert report["summary"]["original"]["unknown_record_count_cases"] == 3
    assert report["summary"]["revised"]["known_records"] == 6
    assert report["cases"][1]["original"]["status"] == "hash_mismatch"
    assert report["cases"][1]["original"]["record_count"] is None


@pytest.mark.parametrize(
    "path",
    [
        "../escape.csv",
        "/abs.csv",
        "C:/file.csv",
        "a\\b.csv",
        "a//b.csv",
        "a/./b.csv",
        "CON.csv",
        "a./b.csv",
        "a/x:ads.csv",
        "a.pt",
    ],
)
def test_path_errors_fail_inventory_before_any_label_read(tmp_path, path):
    item = case(tmp_path)
    item["original"]["path"] = path
    with patch.object(
        comparison, "_load_side", side_effect=AssertionError("must not read")
    ):
        with pytest.raises(ValueError, match="path"):
            run(tmp_path, [item])


def test_json_duplicates_nonfinite_and_typed_fields_are_rejected(tmp_path):
    inventory = tmp_path / "bad.json"
    for raw in (
        b'{"schema_version":1,"schema_version":1,"cases":[]}',
        b'{"schema_version":NaN,"cases":[]}',
    ):
        inventory.write_bytes(raw)
        with pytest.raises(ValueError):
            comparison.compare_inventory(inventory, tmp_path)
    item = case(tmp_path)
    for field, bad in (
        ("frame_count", True),
        ("width", 1280.0),
        ("rotation", False),
        ("source_sha256", None),
    ):
        changed = copy.deepcopy(item)
        changed["original"]["basis"][field] = bad
        with pytest.raises(ValueError):
            run(tmp_path, [changed])
    for invalid in (
        {"schema_version": True, "cases": [item]},
        {"schema_version": 1, "cases": [item, item]},
    ):
        with pytest.raises(ValueError):
            comparison.validate_inventory(invalid)


def test_symlink_input_is_unavailable_without_reading_target(tmp_path):
    item = case(tmp_path)
    target = tmp_path / item["original"]["path"]
    target.unlink()
    try:
        target.symlink_to(tmp_path / item["revised"]["path"])
    except OSError:
        pytest.skip("Creating symlinks requires OS permission")
    result = run(tmp_path, [item])["cases"][0]
    assert result["original"]["status"] == "unavailable"
    assert result["original"]["observed_sha256"] is None
    assert result["comparison"] is None


def test_inventory_or_root_symlink_is_rejected_before_csv_reads(tmp_path):
    item = case(tmp_path)
    run(tmp_path, [item])
    for name, target in (
        ("alias.json", tmp_path / "inventory.json"),
        ("alias-root", tmp_path),
    ):
        link = tmp_path / name
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except OSError:
            pytest.skip("Creating symlinks requires OS permission")
        inventory = link if name == "alias.json" else tmp_path / "inventory.json"
        root = link if name == "alias-root" else tmp_path
        with pytest.raises(ValueError, match="Symlink"):
            comparison.compare_inventory(inventory, root)


@pytest.mark.parametrize(
    "field,value", [("width", 1920), ("height", 1080), ("frame_count", 4)]
)
def test_different_native_basis_is_not_normalized(tmp_path, field, value):
    item = case(tmp_path)
    item["revised"]["basis"][field] = value
    result = run(tmp_path, [item])["cases"][0]
    assert result["comparison"] is None
    assert "conflicting_declared_native_basis" in result["unscored_reasons"]


def test_distinct_evidence_declarations_can_describe_same_native_basis(tmp_path):
    item = case(tmp_path)
    item["revised"]["basis"]["evidence_sha256"] = "e" * 64
    result = run(tmp_path, [item])["cases"][0]
    assert result["comparison"]["declared_native_frame_pairs"] == 3


def test_all_fixed_read_record_and_report_bounds(tmp_path, monkeypatch):
    item = case(tmp_path)
    monkeypatch.setitem(comparison.LIMITS, "csv_bytes", 2)
    assert run(tmp_path, [item])["summary"]["csv_bytes_read"] == 0
    monkeypatch.setitem(comparison.LIMITS, "csv_bytes", len(CSV))
    monkeypatch.setitem(comparison.LIMITS, "total_csv_bytes", len(CSV))
    report = run(tmp_path, [item])
    assert report["summary"]["csv_bytes_read"] == len(CSV)
    assert report["cases"][0]["original"]["status"] == "parsed"
    assert report["cases"][0]["revised"]["status"] == "unavailable"
    monkeypatch.setitem(comparison.LIMITS, "total_csv_bytes", 2 * len(CSV))
    monkeypatch.setitem(comparison.LIMITS, "records_per_csv", 2)
    assert run(tmp_path, [item])["cases"][0]["original"]["record_count"] is None
    monkeypatch.setitem(comparison.LIMITS, "cases", 1)
    with pytest.raises(ValueError, match="case count"):
        run(tmp_path, [item, item])
    monkeypatch.setitem(comparison.LIMITS, "inventory_bytes", 1)
    with pytest.raises(ValueError, match="byte_limit"):
        run(tmp_path, [item])
    monkeypatch.setitem(comparison.LIMITS, "report_bytes", 1)
    with pytest.raises(ValueError, match="Report exceeds"):
        comparison.publish_report(tmp_path / "out.json", report)
    assert not (tmp_path / "out.json").exists()


def test_changed_read_bytes_still_consume_total_budget(tmp_path):
    item = case(tmp_path)
    actual = comparison._read_bounded

    def changed(path, limit):
        if path.suffix == ".csv":
            raise comparison._ChangedInput(len(CSV))
        return actual(path, limit)

    with patch.object(comparison, "_read_bounded", side_effect=changed):
        report = run(tmp_path, [item])
    assert report["summary"]["csv_bytes_read"] == 2 * len(CSV)
    assert report["summary"]["original"]["unknown_record_count_cases"] == 1


def test_deterministic_report_and_cli_preserve_input_and_existing_output(tmp_path):
    item = case(tmp_path)
    expected = run(tmp_path, [item])
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert run(tmp_path, [item]) == expected
    output = tmp_path / "report.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/compare_shuttle_labels.py"),
        "--inventory",
        str(tmp_path / "inventory.json"),
        "--inputs-root",
        str(tmp_path),
        "--output",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text()) == expected
    saved = output.read_bytes()
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and output.read_bytes() == saved
    for path, raw in before.items():
        assert path.read_bytes() == raw
    serialized = saved.decode()
    assert "raw_fields" not in serialized and "published_point" not in serialized
    assert "5,8" not in serialized and "source_sha256" not in serialized


def test_interrupted_publication_and_racing_destination_leave_no_partial_final(
    tmp_path,
):
    target = tmp_path / "report.json"
    with patch.object(comparison.os, "fsync", side_effect=OSError("interrupted")):
        with pytest.raises(OSError, match="interrupted"):
            comparison.publish_report(target, {"aggregate": 3})
    assert not target.exists()

    def race(_source, destination):
        Path(destination).write_bytes(b"other writer")
        raise FileExistsError(destination)

    with patch.object(comparison.os, "link", side_effect=race):
        with pytest.raises(FileExistsError):
            comparison.publish_report(target, {"aggregate": 3})
    assert target.read_bytes() == b"other writer"
    assert not list(tmp_path.glob(".comparison-*"))


def test_frozen_protocol_is_packaged_without_runtime_manifest_dependency():
    document = json.loads(
        (ROOT / "data/manifests/shuttle_label_comparison_protocol_v1.json").read_text()
    )
    assert document == comparison.PROTOCOL
    assert set(document["eligibility"].values()) == {False}


def test_no_model_or_media_imports_in_fresh_process():
    code = "import sys; from badminton import shuttle_label_comparison; assert not {'torch','torchvision','av','cv2'} & set(sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": str(ROOT / "backend")},
    )
    assert result.returncode == 0, result.stderr
