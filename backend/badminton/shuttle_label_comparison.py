"""Compare pinned local label revisions without inferring source alignment.

This module performs no acquisition, media decoding, learning or label repair.
Reports contain aggregate counts, never per-frame labels or coordinates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import stat
import tempfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

LIMITS = {
    "cases": 512,
    "inventory_bytes": 1024**2,
    "csv_bytes": 16 * 1024**2,
    "total_csv_bytes": 64 * 1024**2,
    "records_per_csv": 200000,
    "report_bytes": 2 * 1024**2,
}
ELIGIBILITY = dict.fromkeys(
    (
        "training_allowed",
        "independent_test_allowed",
        "model_deployment_allowed",
        "dataset_redistribution_allowed",
    ),
    False,
)
PROTOCOL = {
    "schema_version": 1,
    "name": "shuttle_label_comparison_v1",
    "columns": ["Frame", "Visibility", "X", "Y"],
    "ordinal": "nonnegative decimal integer, at most 18 digits; no reindexing",
    "visibility": {"0": "published_not_visible", "1": "published_visible"},
    "coordinates": "finite source pixels; exact numeric equality; no tolerance",
    "correspondence": "matching declared basis only; not independent verification",
    "quarantine": "incomplete, duplicate, reversed or malformed ordinal coverage",
    "output": "aggregate counts only; unknowns remain unscored",
    "limits": LIMITS,
    "eligibility": ELIGIBILITY,
}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
ORDINAL = re.compile(r"[0-9]{1,18}\Z")


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate inventory key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Nonfinite inventory number")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid inventory JSON") from exc


def _fields(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"Invalid {name} fields")


def _positive(value, name, maximum):
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError(f"Invalid {name}")


def _relative_path(value):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("Invalid input path")
    parts = value.split("/")
    if any(
        part in {"", ".", ".."}
        or part.endswith((" ", "."))
        or re.fullmatch(r"[A-Za-z0-9_. -]+", part) is None
        or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", part)
        for part in parts
    ) or not value.endswith(".csv"):
        raise ValueError("Unsafe portable CSV path")
    return parts


def _validate_basis(basis):
    if basis is None:
        return
    _fields(
        basis,
        (
            "source_sha256",
            "evidence_sha256",
            "frame_count",
            "width",
            "height",
            "ordinal_origin",
            "rotation",
            "coordinate_space",
        ),
        "native basis",
    )
    for key in ("source_sha256", "evidence_sha256"):
        if not isinstance(basis[key], str) or not SHA256.fullmatch(basis[key]):
            raise ValueError("Invalid basis SHA256")
    _positive(basis["frame_count"], "native frame count", 10**9)
    for key in ("width", "height"):
        _positive(basis[key], "source dimension", 10**6)
    for key in ("ordinal_origin", "rotation"):
        if type(basis[key]) is not int:
            raise ValueError("Invalid native basis integer")
    if not isinstance(basis["coordinate_space"], str):
        raise ValueError("Invalid coordinate space")


def validate_inventory(value):
    """Validate the entire inventory before opening any declared label file."""
    _fields(value, ("schema_version", "cases"), "inventory")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported inventory schema")
    cases = value["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= LIMITS["cases"]:
        raise ValueError("Invalid inventory case count")
    seen = set()
    for case in cases:
        _fields(case, ("case_id", "original", "revised", "quarantine_reasons"), "case")
        key = case["case_id"]
        if not isinstance(key, str) or not CASE_ID.fullmatch(key) or key in seen:
            raise ValueError("Invalid or duplicate case ID")
        seen.add(key)
        reasons = case["quarantine_reasons"]
        if (
            not isinstance(reasons, list)
            or any(not isinstance(r, str) or not CASE_ID.fullmatch(r) for r in reasons)
            or len(reasons) != len(set(reasons))
        ):
            raise ValueError("Invalid quarantine reasons")
        for name in ("original", "revised"):
            descriptor = case[name]
            if descriptor is None:
                continue
            _fields(descriptor, ("path", "sha256", "basis"), "file descriptor")
            _relative_path(descriptor["path"])
            checksum = descriptor["sha256"]
            if not isinstance(checksum, str) or not SHA256.fullmatch(checksum):
                raise ValueError("Invalid input SHA256")
            _validate_basis(descriptor["basis"])
    return value


def _safe_input(root, relative):
    path = root
    for part in _relative_path(relative):
        path = path / part
        info = path.lstat()
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise ValueError("Symlink or reparse input")
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError("Input is not a contained regular file")
    return path


def _reject_links(path):
    """Reject explicit inventory/root aliases before resolving their paths."""
    for component in (path, *path.parents):
        info = component.lstat()
        if component.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise ValueError("Symlink or reparse input location")


class _ChangedInput(ValueError):
    def __init__(self, read_bytes):
        super().__init__("input_changed_during_read")
        self.read_bytes = read_bytes


def _read_bounded(path, limit):
    """Read at most limit bytes and reject observed changes to this file lifetime."""
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("not_regular_file")
        if before.st_size > limit:
            raise ValueError("byte_limit")
        raw = stream.read(limit)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (
        after.st_size,
        after.st_mtime_ns,
    ) or len(raw) != before.st_size:
        raise _ChangedInput(len(raw))
    return raw


def _supported_basis(basis):
    return (
        basis is not None
        and basis["ordinal_origin"] == 0
        and basis["rotation"] == 0
        and basis["coordinate_space"] == "source_pixels"
    )


def _parse_csv(raw, basis):
    """Keep all parsed records, including blank records; no raw values escape."""
    result = {"record_count": None, "issues": {}, "structural_issues": []}
    try:
        reader = csv.reader(
            io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True
        )
        header = next(reader, [])
        rows = []
        for row in reader:
            if len(rows) >= LIMITS["records_per_csv"]:
                result["structural_issues"] = ["record_limit"]
                return result, None
            rows.append(row)
    except (UnicodeError, csv.Error):
        result["structural_issues"] = ["unparsed_csv"]
        return result, None
    result["record_count"] = len(rows)
    structural, issues = set(), Counter()
    if header != PROTOCOL["columns"]:
        structural.add("unsupported_csv_schema")
    numbers = [int(r[0]) if r and ORDINAL.fullmatch(r[0]) else None for r in rows]
    counts = Counter(n for n in numbers if n is not None)
    previous = None
    reversals = 0
    for number in numbers:
        if number is not None:
            reversals += previous is not None and number < previous
            previous = number
    if reversals:
        structural.add("reversed_ordinals")
    if any(count > 1 for count in counts.values()):
        structural.add("duplicate_ordinals")
    supported = _supported_basis(basis)
    native_count = basis["frame_count"] if supported else None
    in_range = {n for n in counts if native_count is not None and n < native_count}
    complete = (
        (
            len(in_range) == native_count
            and len(rows) == native_count
            and all(count == 1 for count in counts.values())
        )
        if native_count is not None
        else None
    )
    if complete is False:
        structural.add("incomplete_native_coverage")
    parsed = {}
    for row, number in zip(rows, numbers):
        row_issues = []
        if header != PROTOCOL["columns"] or len(row) != 4:
            row_issues.append("unsupported_record_schema")
            structural.add("unsupported_record_schema")
        if number is None:
            row_issues.append("invalid_ordinal")
            structural.add("invalid_ordinal")
        elif counts[number] > 1:
            row_issues.append("duplicate_ordinal")
        if number is not None and native_count is not None and number >= native_count:
            row_issues.append("out_of_range_ordinal")
            structural.add("out_of_range_ordinal")
        flag = row[1] if header == PROTOCOL["columns"] and len(row) == 4 else None
        if flag not in {"0", "1"}:
            row_issues.append("unknown_visibility")
        point = None
        if header == PROTOCOL["columns"] and len(row) == 4:
            try:
                x, y = Decimal(row[2]), Decimal(row[3])
                if not x.is_finite() or not y.is_finite():
                    raise ValueError
                if flag == "0" and (x != 0 or y != 0):
                    row_issues.append("invisible_nonzero_coordinate")
                if flag == "1":
                    if not supported:
                        row_issues.append("unknown_coordinate_basis")
                    elif not (0 <= x < basis["width"] and 0 <= y < basis["height"]):
                        row_issues.append("coordinate_outside_source")
                    else:
                        point = (x, y)
            except (ValueError, InvalidOperation):
                row_issues.append("invalid_coordinate")
        issues.update(set(row_issues))
        if number is not None and counts[number] == 1:
            parsed[number] = (flag, point, not row_issues)
    result.update(
        issues=dict(sorted(issues.items())),
        structural_issues=sorted(structural),
        unique_ordinals=len(counts),
        valid_unique_records=sum(valid for _flag, _point, valid in parsed.values()),
        duplicate_ordinals=sum(n > 1 for n in counts.values()),
        duplicate_records=sum(n for n in counts.values() if n > 1),
        duplicate_excess_records=sum(n - 1 for n in counts.values()),
        invalid_ordinal_records=sum(n is None for n in numbers),
        reversals=reversals,
        native_coverage_complete=complete,
        native_missing_ordinals=native_count - len(in_range) if supported else None,
        unlabelled_tail_frames=native_count - 1 - max(in_range, default=-1)
        if supported
        else None,
    )
    return result, (set(counts), parsed)


def _load_side(root, descriptor, budget):
    result = {"status": "not_supplied", "record_count": None, "observed_sha256": None}
    if descriptor is None:
        return result, None, 0
    result.update(expected_sha256=descriptor["sha256"], status="unavailable")
    try:
        path = _safe_input(root, descriptor["path"])
        raw = _read_bounded(path, min(LIMITS["csv_bytes"], budget))
    except (OSError, ValueError) as exc:
        result["reason"] = (
            str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        )
        return result, None, getattr(exc, "read_bytes", 0)
    result.update(observed_sha256=digest(raw), observed_bytes=len(raw))
    if result["observed_sha256"] != descriptor["sha256"]:
        result.update(status="hash_mismatch", reason="input_sha256_mismatch")
        return result, None, len(raw)
    parsed, rows = _parse_csv(raw, descriptor["basis"])
    result.update(parsed)
    result["status"] = "parsed" if rows is not None else "unparsed"
    return result, rows, len(raw)


def _compare_case(root, case, budget):
    originals, left, used = _load_side(root, case["original"], budget)
    revisions, right, more = _load_side(root, case["revised"], budget - used)
    result = {
        "case_id": case["case_id"],
        "original": originals,
        "revised": revisions,
        "byte_equal": None,
        "ordinal_inventory": None,
        "comparison": None,
        "unscored_reasons": [],
    }
    verified = {"parsed", "unparsed"}
    if originals["status"] in verified and revisions["status"] in verified:
        result["byte_equal"] = (
            originals["observed_sha256"] == revisions["observed_sha256"]
        )
    if left is not None and right is not None:
        a, b = left[0], right[0]
        result["ordinal_inventory"] = {
            "union": len(a | b),
            "shared": len(a & b),
            "only_original": len(a - b),
            "only_revised": len(b - a),
        }
    reasons = set(case["quarantine_reasons"])
    for name, item in (("original", originals), ("revised", revisions)):
        if item["status"] != "parsed":
            reasons.add(name + "_" + item["status"])
        reasons.update(name + "_" + r for r in item.get("structural_issues", []))
    a_basis = case["original"]["basis"] if case["original"] else None
    b_basis = case["revised"]["basis"] if case["revised"] else None
    if not _supported_basis(a_basis) or not _supported_basis(b_basis):
        reasons.add("unavailable_supported_native_basis")
    elif any(a_basis[k] != b_basis[k] for k in a_basis if k != "evidence_sha256"):
        reasons.add("conflicting_declared_native_basis")
    if not reasons:
        transitions, coordinate_pairs, coordinate_changes, unscored = Counter(), 0, 0, 0
        for number in left[0] & right[0]:
            a, b = left[1][number], right[1][number]
            if not a[2] or not b[2]:
                unscored += 1
                continue
            transitions[a[0] + "_to_" + b[0]] += 1
            if a[0] == b[0] == "1":
                coordinate_pairs += 1
                coordinate_changes += a[1] != b[1]
        result["comparison"] = {
            "declared_native_frame_pairs": len(left[0] & right[0]),
            "visibility_pairs": sum(transitions.values()),
            "unscored_pairs": unscored,
            "visibility_transitions": dict(sorted(transitions.items())),
            "visible_coordinate_pairs": coordinate_pairs,
            "coordinate_changes": coordinate_changes,
        }
    result["unscored_reasons"] = sorted(reasons)
    return result, used + more


def compare_inventory(inventory_path, inputs_root):
    """Read only explicit local pins; reports assert no independent source truth."""
    inventory_path, root = Path(inventory_path).absolute(), Path(inputs_root).absolute()
    _reject_links(inventory_path)
    _reject_links(root)
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("Input root must be a directory")
    raw = _read_bounded(inventory_path, LIMITS["inventory_bytes"])
    inventory = validate_inventory(_strict_json(raw))
    cases, read_bytes = [], 0
    for case in inventory["cases"]:
        item, used = _compare_case(root, case, LIMITS["total_csv_bytes"] - read_bytes)
        cases.append(item)
        read_bytes += used
    counts = Counter(r for c in cases for r in c["unscored_reasons"])
    summary = {
        "cases": len(cases),
        "compared_cases": sum(c["comparison"] is not None for c in cases),
        "unscored_cases": sum(c["comparison"] is None for c in cases),
        "csv_bytes_read": read_bytes,
        "unscored_reason_cases": dict(sorted(counts.items())),
    }
    for name in ("original", "revised"):
        known = [
            c[name]["record_count"]
            for c in cases
            if c[name]["record_count"] is not None
        ]
        summary[name] = {
            "known_records": sum(known),
            "known_record_count_cases": len(known),
            "unknown_record_count_cases": len(cases) - len(known),
        }
    return {
        "schema_version": 1,
        "protocol": PROTOCOL["name"],
        "protocol_sha256": digest(encoded(PROTOCOL)),
        "inventory_sha256": digest(raw),
        "eligibility": dict(ELIGIBILITY),
        "limitations": [
            "Native correspondence is declared by the caller, not independently verified.",
            "Label revision differences are not model errors or expert accuracy measurements.",
            "Unknown record counts are not zero; unscored cases remain in the case denominator.",
        ],
        "summary": summary,
        "cases": cases,
    }


def publish_report(path, report):
    """Publish a complete fresh aggregate file atomically without replacement."""
    path, raw = Path(path), encoded(report)
    if len(raw) > LIMITS["report_bytes"]:
        raise ValueError("Report exceeds byte limit")
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".comparison-", delete=False
    ) as f:
        pending = Path(f.name)
        try:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            pending.unlink()
            raise
    try:
        os.link(pending, path)
    finally:
        pending.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--inputs-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(args.output)
        report = compare_inventory(args.inventory, args.inputs_root)
        publish_report(args.output, report)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Comparison not published: {exc}\n")
    print(json.dumps(report["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
