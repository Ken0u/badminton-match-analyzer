"""Pinned public stroke labels, kept separate from source-aligned app annotations."""

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

SOURCE_MANIFEST = Path(__file__).with_name("shuttleset_manifest.json")
FAMILIES = ("clear", "lift", "net", "drop", "smash", "drive", "other")
SOURCE_TYPES = {
    "放小球": ("net shot", "net"),
    "擋小球": ("return net", "other"),
    "殺球": ("smash", "smash"),
    "點扣": ("wrist smash", "other"),
    "挑球": ("lob", "lift"),
    "防守回挑": ("defensive return lob", "lift"),
    "長球": ("clear", "clear"),
    "平球": ("drive", "drive"),
    "小平球": ("driven flight", "drive"),
    "後場抽平球": ("back-court drive", "drive"),
    "切球": ("drop", "drop"),
    "過渡切球": ("passive drop", "drop"),
    "推球": ("push", "other"),
    "撲球": ("rush", "other"),
    "防守回抽": ("defensive return drive", "drive"),
    "勾球": ("cross-court net shot", "net"),
    "發短球": ("short service", None),
    "發長球": ("long service", None),
}


def pinned_source():
    return json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def source_path(root, relative):
    path = (Path(root).resolve() / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("Dataset source path must stay inside its source directory")
    return path


def verified_bytes(root, relative, expected):
    path = source_path(root, relative)
    if not path.is_file():
        raise ValueError(f"Missing dataset source file: {relative}; fetch it first")
    data = path.read_bytes()
    if blob_sha(data) != expected:
        raise ValueError(f"Dataset source hash mismatch: {relative}")
    return data


def read_rows(data):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("Dataset CSV requires unique named columns")
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("Dataset CSV row width does not match its header")
    return rows


def integer(value, minimum=0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not number.is_integer() or number < minimum:
        return None
    return int(number)


def source_seconds(value):
    try:
        hour, minute, second = value.split(":")
        h, m, s = float(hour), float(minute), float(second)
        if not all(math.isfinite(v) for v in (h, m, s)):
            return None
        if (
            h < 0
            or not h.is_integer()
            or not 0 <= m < 60
            or not m.is_integer()
            or not 0 <= s < 60
        ):
            return None
        return h * 3600 + m * 60 + s
    except (ValueError, AttributeError):
        return None


def source_flag(value):
    # The pinned original cleaner explicitly fills blank backhand with zero.
    if value == "":
        return False
    number = integer(value)
    return bool(number) if number in (0, 1) else None


def frame_rate_evidence(records):
    """Diagnose agreement with coarse time labels; never certify media alignment."""
    rows = [
        r
        for r in records
        if r["source_frame"] is not None and r["source_time_s"] is not None
    ]
    candidates = []
    for fps in (23.976, 24, 25, 29.97, 30, 50, 59.94, 60):
        count = sum(
            0 <= r["source_frame"] / fps - r["source_time_s"] < 1.001 for r in rows
        )
        candidates.append({"fps": fps, "consistent_rows": count})
    best = max((c["consistent_rows"] for c in candidates), default=0)
    winners = [c["fps"] for c in candidates if c["consistent_rows"] == best]
    return {
        "meaning": "Frame/FPS agrees with the recorded second; this does not verify video origin, frame numbering, or alignment",
        "timed_rows": len(rows),
        "candidate_fps": winners[0]
        if len(winners) == 1 and rows and best / len(rows) >= 0.98
        else None,
        "candidates": candidates,
    }


def normalize_set(rows, match, set_id, split, known_issues=()):
    """Retain every raw row, quarantining flawed rallies and ambiguous records."""
    required = {
        "rally",
        "ball_round",
        "frame_num",
        "time",
        "player",
        "type",
        "backhand",
        "aroundhead",
        "server",
        "flaw",
    }
    if not rows or not required.issubset(rows[0]):
        raise ValueError("Stroke CSV is empty or missing required source columns")
    match_id = integer(match["id"], 1)
    if match_id is None:
        raise ValueError("Match ID must be a positive integer")
    bad_rallies = defaultdict(set)
    for issue in known_issues:
        if integer(issue["match"]) != match_id:
            continue
        issue_set, rally = integer(issue["set"]), integer(issue["rally"])
        if issue_set in (0, set_id):
            bad_rallies[rally].add("published_issue: " + issue["reason"])
    records = []
    for number, raw in enumerate(rows, 2):
        rally, order = integer(raw["rally"], 1), integer(raw["ball_round"], 1)
        frame, time = integer(raw["frame_num"]), source_seconds(raw["time"])
        backhand, around = (
            source_flag(raw["backhand"].strip()),
            source_flag(raw["aroundhead"].strip()),
        )
        translated, family = SOURCE_TYPES.get(raw["type"], ("unknown", "unknown"))
        kind = "serve" if translated in ("short service", "long service") else "shot"
        issues = []
        if rally is None or order is None:
            issues.append("invalid_rally_or_stroke_order")
        if frame is None or time is None:
            issues.append("invalid_source_frame_or_time")
        if raw["player"] not in ("A", "B"):
            issues.append("unknown_source_player")
        if family == "unknown":
            issues.append("unresolved_source_type")
        if backhand is None or around is None or (backhand and around):
            side = "unknown"
            issues.append("invalid_or_conflicting_side_flags")
        else:
            side = "backhand" if backhand else "forehand"
        if raw["server"] not in ("1", "2", "3") or (raw["server"] == "1") != (
            kind == "serve"
        ):
            issues.append("serve_marker_disagrees_with_type")
        if raw["flaw"].strip() and rally is not None:
            bad_rallies[rally].add("source_flaw_flag")
        records.append(
            {
                "id": f"shuttleset:{match_id}:{set_id}:{rally}:{order}:{number}",
                "match_id": match_id,
                "set_id": set_id,
                "rally_id": rally,
                "stroke_order": order,
                "source_row": number,
                "split": split,
                "source_frame": frame,
                "source_time_s": time,
                "source_player": raw["player"],
                "kind": kind,
                "family": family,
                "side": side,
                "source_type": translated,
                "around_head": around,
                "terminal_stroke_marker": raw["server"] == "3",
                "media_alignment": "unverified",
                "issues": issues,
                "raw": dict(raw),
            }
        )
    frames = defaultdict(list)
    rallies = defaultdict(list)
    previous = None
    for record in records:
        rallies[record["rally_id"]].append(record)
        if record["source_frame"] is not None:
            frames[record["source_frame"]].append(record)
            if previous and record["source_frame"] < previous["source_frame"]:
                bad_rallies[record["rally_id"]].add("nonmonotonic_source_frames")
                bad_rallies[previous["rally_id"]].add("nonmonotonic_source_frames")
            previous = record
    for repeated in frames.values():
        if len(repeated) > 1:
            for record in repeated:
                bad_rallies[record["rally_id"]].add("duplicate_source_frame")
    for rally, group in rallies.items():
        if [r["stroke_order"] for r in group] != list(range(1, len(group) + 1)):
            bad_rallies[rally].add("incomplete_or_duplicate_stroke_order")
    for record in records:
        issues = record["issues"] + sorted(
            bad_rallies[0] | bad_rallies[record["rally_id"]]
        )
        if split == "quarantine":
            issues.append("match_quarantined_by_published_split")
        record["issues"] = sorted(set(issues))
        record["family_eligible"] = not issues and (
            record["kind"] == "serve" or record["family"] in FAMILIES
        )
        record["side_eligible"] = not issues and record["side"] in (
            "forehand",
            "backhand",
        )
    return records


def import_shuttleset(source, output, *, manifest=None):
    """Build a deterministic, source-verified label index, not app annotations."""
    spec = manifest or pinned_source()
    files = spec["files"]
    snapshots = {}

    def read(relative):
        data = verified_bytes(source, relative, files[relative])
        snapshots[relative] = {
            "git_blob_sha1": files[relative],
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        return read_rows(data)

    matches = read("ShuttleSet/set/match.csv")
    identities = [integer(m["id"], 1) for m in matches]
    if None in identities or len(set(identities)) != len(identities):
        raise ValueError("Dataset match IDs must be unique positive integers")
    urls = [m["url"] for m in matches if m["url"]]
    if len(set(urls)) != len(urls) or any(
        not re.fullmatch(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}", u)
        for u in urls
    ):
        raise ValueError(
            "Dataset source videos must have unique canonical YouTube URLs"
        )
    splits = {}
    for split, ids in spec["splits"].items():
        if split not in ("train", "validation", "test", "quarantine"):
            raise ValueError("Unknown dataset split")
        for match_id in ids:
            if match_id in splits:
                raise ValueError("One original match cannot appear in multiple splits")
            splits[match_id] = split
    if set(splits) != set(identities):
        raise ValueError("Frozen splits must cover exactly the original match catalog")
    if any(
        not match["url"] and splits[integer(match["id"])] != "quarantine"
        for match in matches
    ):
        raise ValueError("A usable match needs a source video URL")
    references = []
    known_issues = []
    for entry in spec["references"]:
        data = verified_bytes(source, entry["path"], entry["git_blob_sha1"])
        references.append(entry | {"sha256": hashlib.sha256(data).hexdigest()})
        if entry["path"].endswith("bst_flaw_shot_records.csv"):
            known_issues = read_rows(data)
    records, summaries = [], []
    for match in sorted(matches, key=lambda item: integer(item["id"], 1)):
        match_id, sets = integer(match["id"], 1), integer(match["set"], 1)
        if sets not in (2, 3):
            raise ValueError("A source match must contain two or three sets")
        own = []
        for set_id in range(1, sets + 1):
            relative = f"ShuttleSet/set/{match['video']}/set{set_id}.csv"
            if relative not in files:
                raise ValueError("Match catalog references an unpinned set file")
            group = normalize_set(
                read(relative), match, set_id, splits[match_id], known_issues
            )
            for record in group:
                record["source_file"] = relative
            own.extend(group)
        summaries.append(
            {
                "metadata": match,
                "split": splits[match_id],
                "record_count": len(own),
                "frame_rate_evidence": frame_rate_evidence(own),
            }
        )
        records.extend(own)
    destination = Path(output).resolve()
    source_root = Path(source).resolve()
    if destination == source_root or destination.is_relative_to(source_root):
        raise ValueError(
            "Write the normalized dataset outside the immutable source directory"
        )
    destination.mkdir(parents=True, exist_ok=True)
    data = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in records
    ).encode("utf-8")
    index = destination / "strokes.jsonl"
    temp = index.with_suffix("." + uuid4().hex + ".tmp")
    try:
        temp.write_bytes(data)
        temp.replace(index)
    finally:
        temp.unlink(missing_ok=True)
    report = {
        "schema_version": 1,
        "dataset": "ShuttleSet",
        "mapping_version": spec["mapping_version"],
        "source_repository": spec["repository"],
        "source_commit": spec["commit"],
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(spec, sort_keys=True).encode()
        ).hexdigest(),
        "source_files": snapshots,
        "references": references,
        "splits": spec["splits"],
        "split_source": spec["split_source"],
        "side_policy": spec["side_policy"],
        "matches": summaries,
        "record_count": len(records),
        "rally_count": len(
            {(r["match_id"], r["set_id"], r["rally_id"]) for r in records}
        ),
        "index_sha256": hashlib.sha256(data).hexdigest(),
        "family_eligible_records": sum(r["family_eligible"] for r in records),
        "side_eligible_records": sum(r["side_eligible"] for r in records),
        "eligible_family_counts": dict(
            Counter(
                "serve" if r["kind"] == "serve" else r["family"]
                for r in records
                if r["family_eligible"]
            )
        ),
        "eligible_side_counts": dict(
            Counter(r["side"] for r in records if r["side_eligible"])
        ),
        "exclusion_counts": dict(
            Counter(issue for r in records for issue in r["issues"])
        ),
        "training_ready_records": 0,
        "media_alignment": "All video alignments remain unverified. Label eligibility alone does not make frames ready for training or app evaluation.",
        "rally_end_policy": "Terminal stroke markers are not exported as rally-end times.",
    }
    from .video import write_json

    write_json(destination / "manifest.json", report)
    return report
