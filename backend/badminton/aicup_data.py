"""Published AI CUP contact labels, separate from predictions and app truth.

Source HitFrame values are retained without assuming their ordinal convention.
Rally clips are not independent matches; published partitions are not promoted
to match-disjoint training/evaluation splits without a source-match audit.
"""

import hashlib
import itertools
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from .datasets import integer, read_rows, verify_output_version
from .video import write_json

MANIFEST = Path(__file__).with_name("aicup2023_manifest.json")
TYPES = {
    1: ("short serve", None),
    2: ("long serve", None),
    3: ("clear", "clear"),
    4: ("drive", "drive"),
    5: ("smash", "smash"),
    6: ("net shot", "net"),
    7: ("drop shot", "drop"),
    8: ("lift", "lift"),
    # The original competition combines push/net-kill; neither is a target.
    9: ("combined push/kill", "other"),
}
REQUIRED = {"ShotSeq", "HitFrame", "Hitter", "Backhand", "BallType", "Winner"}
CLIP_PATH = re.compile(r"part1/(train|val)/(\d{5})/(\d{5})(\.mp4|_S2\.csv)")
DIRECTORY_PATH = re.compile(r"part1/(?:(?:train|val)/(?:\d{5}/)?)?")


def pinned_source():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def normalize_clip(rows, clip_id, partition):
    if not re.fullmatch(r"\d{5}", clip_id) or partition not in ("train", "val"):
        raise ValueError("Invalid published clip identity or partition")
    if not rows or not REQUIRED.issubset(rows[0]):
        raise ValueError("AI CUP CSV missing required source columns")
    records = []
    for number, raw in enumerate(rows, 2):
        contact = integer(raw["HitFrame"])
        order = integer(raw["ShotSeq"], 1)
        code = integer(raw["BallType"], 1)
        source_type, family = TYPES.get(code, ("unknown", "unknown"))
        side = {1: "backhand", 2: "forehand"}.get(integer(raw["Backhand"]), "unknown")
        court_end = {"A": "far", "B": "near"}.get(raw["Hitter"])
        issues = []
        if contact is None:
            issues.append("invalid_published_contact_frame")
        if order is None:
            issues.append("invalid_stroke_order")
        if source_type == "unknown":
            issues.append("unresolved_source_family")
        if side == "unknown":
            issues.append("missing_or_invalid_side_flag")
        if court_end is None:
            issues.append("unknown_source_court_end")
        if raw["Winner"] not in ("A", "B", "X"):
            issues.append("unknown_source_winner_flag")
        records.append(
            {
                "id": f"aicup2023:{partition}:{clip_id}:{number}",
                "dataset": "AI CUP 2023 part1",
                "source_clip_id": clip_id,
                "source_partition": partition,
                "source_row": number,
                "stroke_order": order,
                "source_contact_frame": contact,
                "source_frame_base": "undocumented; preserve published ordinal",
                "source_declared_fps": 30,
                "source_court_end": court_end,
                "source_player": raw["Hitter"],
                "source_type": source_type,
                "kind": "serve" if code in (1, 2) else "shot",
                "family": family,
                "side": side,
                "raw": dict(raw),
                "issues": issues,
                "split": "unassigned",
                "source_match_id": None,
                "mode": "unverified",
                "player_id": None,
                "media_alignment": "unverified",
                "contact_adjudication": "unverified",
                "training_ready": False,
            }
        )
    sequence_issues = []
    if [r["stroke_order"] for r in records] != list(range(1, len(records) + 1)):
        sequence_issues.append("incomplete_or_duplicate_stroke_order")
    frames = [
        r["source_contact_frame"]
        for r in records
        if r["source_contact_frame"] is not None
    ]
    if any(a >= b for a, b in itertools.pairwise(frames)):
        sequence_issues.append("duplicate_or_reversed_contact_frames")
    if records[0]["kind"] != "serve" or any(r["kind"] == "serve" for r in records[1:]):
        sequence_issues.append("serve_sequence_disagrees_with_type")
    if any(r["raw"]["Winner"] != "X" for r in records[:-1]):
        sequence_issues.append("winner_before_terminal_stroke")
    for row in records:
        row["issues"].extend(sequence_issues)
        row["contact_label_eligible"] = (
            row["source_contact_frame"] is not None and not sequence_issues
        )
        row["family_eligible"] = (
            row["contact_label_eligible"] and row["family"] != "unknown"
        )
        row["side_eligible"] = (
            row["contact_label_eligible"] and row["side"] != "unknown"
        )
    return records


def _hash(source):
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _read_clips(source, readme_sha256):
    clips, records = {}, []
    has_readme = False
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len({i.filename for i in entries}) != len(entries):
                raise ValueError("Duplicate archive member names")
            for info in entries:
                if info.is_dir():
                    if DIRECTORY_PATH.fullmatch(info.filename) is None:
                        raise ValueError("Unexpected AI CUP archive directory")
                    continue
                if info.filename == "part1/README.txt":
                    if info.file_size > 1024 * 1024:
                        raise ValueError("Source README exceeds size bound")
                    if hashlib.sha256(archive.read(info)).hexdigest() != readme_sha256:
                        raise ValueError("Published README source hash mismatch")
                    has_readme = True
                    continue
                match = CLIP_PATH.fullmatch(info.filename)
                if match is None or match[2] != match[3]:
                    raise ValueError(
                        "Unexpected AI CUP archive member or clip identity"
                    )
                partition, clip_id, extension = match[1], match[2], match[4]
                key = (partition, clip_id)
                clip = clips.setdefault(
                    key, {"source_clip_id": clip_id, "source_partition": partition}
                )
                if extension == ".mp4":
                    with archive.open(info) as media:
                        media_hash = _hash(media)
                    clip.update(
                        media_path=info.filename,
                        media_sha256=media_hash,
                        media_bytes=info.file_size,
                    )
                else:
                    if info.file_size > 1024 * 1024:
                        raise ValueError("Source CSV exceeds size bound")
                    data = archive.read(info)
                    clip.update(
                        label_path=info.filename,
                        label_sha256=hashlib.sha256(data).hexdigest(),
                    )
                    records.extend(normalize_clip(read_rows(data), clip_id, partition))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid or corrupt AI CUP archive: {exc}") from exc
    if not has_readme:
        raise ValueError("Published source README is missing")
    return clips, records


def import_aicup2023(archive_path, destination, *, spec=None):
    """Verify one pinned archive; index all labelled and unlabelled clips.

    No archive paths are extracted or executed. Every media member is streamed
    through CRC verification and SHA-256, ready for later source-clock checks.
    """
    spec = spec or pinned_source()
    verify_output_version(destination, spec)
    expected = spec["archive"]
    with Path(archive_path).open("rb") as source:
        before = os.fstat(source.fileno())
        if before.st_size != expected["bytes"]:
            raise ValueError("AI CUP archive size mismatch")
        if _hash(source) != expected["sha256"]:
            raise ValueError("AI CUP archive source hash mismatch")
        source.seek(0)
        clips, records = _read_clips(source, expected["readme_sha256"])
        after = os.fstat(source.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(
                "AI CUP archive changed during import; retry unchanged source"
            )
    if any("media_path" not in c for c in clips.values()):
        raise ValueError("Published labels have no paired media")
    if any("label_path" not in c for (p, _), c in clips.items() if p == "train"):
        raise ValueError("Published training clip has no labels")
    counts = Counter(p for p, _ in clips)
    if dict(counts) != expected["clip_counts"]:
        raise ValueError("AI CUP archive clip counts disagree with pinned source")
    label_counts = {
        partition: sum(
            "label_path" in c for (p, _), c in clips.items() if p == partition
        )
        for partition in counts
    }
    if label_counts != expected["label_counts"]:
        raise ValueError("AI CUP archive label counts disagree with pinned source")
    for row in records:
        row.update(
            {
                k: v
                for k, v in clips[
                    (row["source_partition"], row["source_clip_id"])
                ].items()
                if k not in ("source_partition", "source_clip_id")
            }
        )
    media_groups = defaultdict(list)
    for clip in clips.values():
        media_groups[clip["media_sha256"]].append(clip["media_path"])
    report = {
        "dataset": spec["dataset"],
        "normalization_version": spec["normalization_version"],
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(spec, sort_keys=True).encode()
        ).hexdigest(),
        "source": spec,
        "record_count": len(records),
        "clip_counts": dict(counts),
        "label_counts": label_counts,
        "labelled_clip_count": sum("label_path" in c for c in clips.values()),
        "duplicate_media_groups": [
            {"sha256": key, "paths": sorted(paths)}
            for key, paths in sorted(media_groups.items())
            if len(paths) > 1
        ],
        "family_counts": dict(
            Counter("serve" if r["kind"] == "serve" else r["family"] for r in records)
        ),
        "side_counts": dict(Counter(r["side"] for r in records)),
        "issues": dict(Counter(i for r in records for i in r["issues"])),
        "contact_label_eligible_records": sum(
            r["contact_label_eligible"] for r in records
        ),
        "family_eligible_records": sum(r["family_eligible"] for r in records),
        "side_eligible_records": sum(r["side_eligible"] for r in records),
        "training_ready_records": 0,
        "media_alignment": "unverified",
        "split": "unassigned; published clip partitions do not prove match disjointness",
    }
    destination = Path(destination)
    write_json(destination / "records.json", records)
    write_json(destination / "clips.json", [clips[key] for key in sorted(clips)])
    write_json(destination / "manifest.json", report)
    return report
