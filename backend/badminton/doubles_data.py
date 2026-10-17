"""Source-verified doubles labels, separate from app annotations and predictions."""

import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

from .datasets import (
    SOURCE_TYPES,
    integer,
    read_rows,
    source_seconds,
    verified_bytes,
    verify_output_version,
)
from .video import write_json

SOURCE_MANIFEST = Path(__file__).with_name("s2doubles_manifest.json")
TYPES = SOURCE_TYPES | {
    "網前小球": ("net shot", "net"),
    "推撲球": ("combined push/kill category", "other"),
}


def pinned_source():
    return json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))


def normalize_set(rows, match_id, set_id, split, segments):
    required = {
        "rally",
        "ball_round",
        "time",
        "start_frame",
        "end_frame",
        "player",
        "server",
        "ball_type",
        "backhand",
        "flaw",
        "roundscore_AB",
        "roundscore_CD",
    }
    if not rows or not required.issubset(rows[0]):
        raise ValueError("Doubles CSV missing required source columns")
    records, groups = [], defaultdict(list)
    for number, raw in enumerate(rows, 2):
        start, end = integer(raw["start_frame"]), integer(raw["end_frame"])
        rally, order = integer(raw["rally"], 1), integer(raw["ball_round"], 1)
        translated, family = TYPES.get(raw["ball_type"], ("unknown", "unknown"))
        kind = "serve" if translated in ("short service", "long service") else "shot"
        flag = integer(raw["backhand"])
        issues = []
        if start is None or end is None or start >= end:
            issues.append("invalid_shot_interval")
        if source_seconds(raw["time"]) is None:
            issues.append("invalid_coarse_source_time")
        if rally is None or order is None:
            issues.append("invalid_rally_or_stroke_order")
        if raw["player"] not in ("A", "B", "C", "D"):
            issues.append("unknown_source_player")
        if flag not in (0, 1):
            issues.append("missing_or_invalid_side_flag")
        if family == "unknown":
            issues.append("unresolved_source_type")
        if raw["server"] not in ("1", "2", "3"):
            issues.append("invalid_phase_marker")
        if integer(raw["flaw"]) != 0:
            issues.append("source_flaw_or_unknown_flag")
        record = {
            "id": f"s2doubles:{match_id}:{set_id}:{rally}:{order}:{number}",
            "match_id": match_id,
            "set_id": set_id,
            "rally_id": rally,
            "stroke_order": order,
            "source_row": number,
            "split": split,
            "source_start_frame": start,
            "source_end_frame": end,
            "source_time_s_coarse": source_seconds(raw["time"]),
            "source_interval_bounds": "undocumented",
            "contact_frame": None,
            "source_player": raw["player"],
            "kind": kind,
            "family": family,
            "side": "backhand" if flag == 1 else "forehand" if flag == 0 else "unknown",
            "source_type": translated,
            "terminal_stroke_marker": raw["server"] == "3",
            "media_alignment": "unverified",
            "training_ready": False,
            "issues": issues,
            "raw": dict(raw),
        }
        records.append(record)
        groups[rally].append(record)
    timeline_issues = defaultdict(set)
    for a, b in itertools.pairwise(records):
        if (
            a["source_start_frame"] is not None
            and b["source_start_frame"] is not None
            and a["source_start_frame"] >= b["source_start_frame"]
        ):
            for record in (a, b):
                timeline_issues[record["rally_id"]].add(
                    "duplicate_or_reversed_source_frames"
                )
    rallies, used_segments = [], set()
    for rally, group in groups.items():
        issues = set(timeline_issues[rally])
        first = group[0]["raw"]
        scores = (integer(first["roundscore_AB"]), integer(first["roundscore_CD"]))
        score_key = (
            f"{set_id}_{scores[0]:02}_{scores[1]:02}" if None not in scores else None
        )
        segment = segments.get(score_key)
        if not segment:
            issues.add("missing_rally_segment")
        else:
            used_segments.add(score_key)
            if integer(segment["Comment"]) != 0:
                issues.add("source_segment_problem_flag")
            a, b = integer(segment["Start"]), integer(segment["End"])
            if a is None or b is None or a >= b:
                issues.add("invalid_rally_window")
            elif any(
                r["source_start_frame"] is not None
                and r["source_end_frame"] is not None
                and not a <= r["source_start_frame"] < r["source_end_frame"] <= b
                for r in group
            ):
                issues.add("shot_outside_rally_window")
        if [r["stroke_order"] for r in group] != list(range(1, len(group) + 1)):
            issues.add("incomplete_or_duplicate_stroke_order")
        if group[0]["kind"] != "serve" or any(r["kind"] == "serve" for r in group[1:]):
            issues.add("serve_sequence_disagrees_with_type")
        # A single serve fault is both a serve and the terminal stroke. The
        # source's mutually exclusive phase code is 3 in these legitimate rows.
        terminal_serve = (
            len(group) == 1 and group[0]["kind"] == "serve" and first["server"] == "3"
        )
        if not terminal_serve and (
            first["server"] != "1" or any(r["raw"]["server"] == "1" for r in group[1:])
        ):
            issues.add("serve_marker_disagrees_with_sequence")
        if group[-1]["raw"]["server"] != "3" or any(
            r["raw"]["server"] == "3" for r in group[:-1]
        ):
            issues.add("missing_or_misplaced_terminal_marker")
        for record in group:
            raw = record["raw"]
            if (integer(raw["roundscore_AB"]), integer(raw["roundscore_CD"])) != scores:
                issues.add("inconsistent_rally_score")
        for a, b in itertools.pairwise(group):
            if a["source_end_frame"] != b["source_start_frame"]:
                issues.add("discontinuous_shot_intervals")
        summary = {
            "match_id": match_id,
            "set_id": set_id,
            "rally_id": rally,
            "score_key": score_key,
            "split": split,
            "source_window": dict(segment) if segment else None,
            "stroke_count": len(group),
            "terminal_serve": terminal_serve,
            "issues": sorted(issues),
            "media_alignment": "unverified",
            "exact_serve_frame": None,
            "exact_terminal_frame": None,
        }
        rallies.append(summary)
        for record in group:
            record["rally_issues"] = sorted(issues)
            record["label_eligible"] = not record["issues"] and not issues
    for key, segment in segments.items():
        if key.startswith(f"{set_id}_") and key not in used_segments:
            rallies.append(
                {
                    "match_id": match_id,
                    "set_id": set_id,
                    "rally_id": None,
                    "score_key": key,
                    "split": split,
                    "source_window": dict(segment),
                    "stroke_count": 0,
                    "terminal_serve": False,
                    "issues": ["missing_stroke_labels"],
                    "media_alignment": "unverified",
                    "exact_serve_frame": None,
                    "exact_terminal_frame": None,
                }
            )
    return records, rallies


def import_doubles(source, output, *, manifest=None):
    spec = manifest or pinned_source()
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("Write normalized data outside the immutable source directory")
    verify_output_version(output, spec)
    files = {}

    def read(relative, csv=True):
        if relative not in spec["files"]:
            raise ValueError("Catalog references an unpinned source file")
        data = verified_bytes(source, relative, spec["files"][relative])
        files[relative] = {
            "git_blob_sha1": spec["files"][relative],
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        return read_rows(data) if csv else data

    read("README.md", csv=False)
    matches = read("Match.csv")
    ids = [integer(m["id"], 1) for m in matches]
    if None in ids or len(set(ids)) != len(ids):
        raise ValueError("Source match IDs must be unique positive integers")
    splits = {}
    for split, members in spec["splits"].items():
        if split not in ("train", "validation", "test"):
            raise ValueError("Unknown source split")
        for match_id in members:
            if match_id in splits:
                raise ValueError("An original match cannot appear in multiple splits")
            splits[match_id] = split
    if set(splits) != set(ids):
        raise ValueError("Splits must cover exactly the original matches")
    records, rallies = [], []
    for match in sorted(matches, key=lambda m: integer(m["id"])):
        mid, sets = integer(match["id"]), integer(match["set"])
        if sets not in (2, 3):
            raise ValueError("A source match must contain two or three sets")
        segments = read(f"Match {mid:03}/RallySeg.csv")
        if (
            not segments
            or not {"Score", "Start", "End", "Comment"}.issubset(segments[0])
            or len({r["Score"] for r in segments}) != len(segments)
        ):
            raise ValueError(
                "Rally windows require unique score keys and source fields"
            )
        lookup = {s["Score"]: s for s in segments}
        for sid in range(1, sets + 1):
            path = f"Match {mid:03}/label/set{sid}.csv"
            strokes, windows = normalize_set(read(path), mid, sid, splits[mid], lookup)
            for row in strokes:
                row["source_file"] = path
            records.extend(strokes)
            rallies.extend(windows)
    output.mkdir(parents=True, exist_ok=True)
    digests = {}
    for filename, rows in (("strokes.jsonl", records), ("rallies.jsonl", rallies)):
        # A content digest makes repeated imports comparable without changing IDs.
        body = "".join(
            json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
            for r in rows
        )
        temp = output / f".{uuid4().hex}.tmp"
        try:
            temp.write_text(body, encoding="utf-8", newline="\n")
            temp.replace(output / filename)
        finally:
            temp.unlink(missing_ok=True)
        digests[filename] = hashlib.sha256(body.encode()).hexdigest()
    report = {
        "schema_version": 1,
        "dataset": "S2Doubles",
        "mapping_version": spec["mapping_version"],
        "repository": spec["repository"],
        "commit": spec["commit"],
        "source_files": files,
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(spec, sort_keys=True).encode()
        ).hexdigest(),
        "matches": [
            {"metadata": m, "split": splits[integer(m["id"])]} for m in matches
        ],
        "splits": spec["splits"],
        "split_policy": spec["split_policy"],
        "record_count": len(records),
        "rally_count": len(rallies),
        "coarse_time_consistent_at_documented_fps": sum(
            r["source_start_frame"] is not None
            and r["source_time_s_coarse"] is not None
            and 0
            <= r["source_start_frame"] / spec["source_fps_requirement"]
            - r["source_time_s_coarse"]
            < 1.001
            for r in records
        ),
        "label_eligible_records": sum(r["label_eligible"] for r in records),
        "single_stroke_terminal_serves": sum(r["terminal_serve"] for r in rallies),
        "eligible_family_counts": dict(
            Counter(
                "serve" if r["kind"] == "serve" else r["family"]
                for r in records
                if r["label_eligible"]
            )
        ),
        "eligible_family_side_counts": dict(
            Counter(
                f"{r['family']}:{r['side']}"
                for r in records
                if r["label_eligible"] and r["kind"] == "shot"
            )
        ),
        "row_issue_counts": dict(Counter(x for r in records for x in r["issues"])),
        "rally_issue_counts": dict(Counter(x for r in rallies for x in r["issues"])),
        "index_sha256": digests,
        "source_fps_requirement": spec["source_fps_requirement"],
        "interval_bounds": spec["interval_bounds"],
        "frame_origin": spec["frame_origin"],
        "rally_end_policy": spec["rally_end_policy"],
        "terms_status": spec["terms_status"],
        "media_alignment": "unverified",
        "training_ready_records": 0,
        "coordinate_policy": "Projected hitting/landing points are not observed shuttle-localization truth; TrackNet files not imported.",
    }
    write_json(output / "manifest.json", report)
    return report
