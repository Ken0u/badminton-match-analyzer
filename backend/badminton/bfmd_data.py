"""Pinned broadcast timelines, separate from app truth and aligned training data.

No video, model, source script or inferred player/shuttle track is opened. Raw
result provenance and source ranges survive normalization, including conflicts.
"""

import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

import psutil

from .datasets import read_rows

MANIFEST = Path(__file__).with_name("bfmd_manifest.json")
MAX_FILE_BYTES = 16 * 1024 * 1024
TYPES = {
    "serve": ("serve", None),
    "flick_serve": ("serve", None),
    "clear": ("shot", "clear"),
    "lift": ("shot", "lift"),
    "net_shot": ("shot", "net"),
    "drop": ("shot", "drop"),
    "smash": ("shot", "smash"),
    "drive": ("shot", "drive"),
    **dict.fromkeys(("net_kill", "push", "press", "block", "other"), ("shot", "other")),
}
SCENES = {
    "Rally",
    "replay",
    "hawk_eye_challenge",
    "11-point interval",
    "21-point interval",
    "court_cleaning",
}
LABELS = set(TYPES) | SCENES | {"hit", "bounce", "net_hit"}


def pinned_source():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _json(data):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON source key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Nonfinite JSON source number")

    return json.loads(
        data.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant
    )


def _interval(value):
    if not isinstance(value, dict):
        return None
    a, b = value.get("start"), value.get("end")
    return [a, b] if type(a) is int and type(b) is int and 0 <= a <= b else None


def _strings(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def normalize_timeline(task, match_name, mode):
    """Preserve source records; only unambiguous manual HITs can carry targets."""
    if not isinstance(task, dict) or mode not in ("singles", "doubles"):
        raise ValueError("BFMD requires a task object and singles/doubles mode")
    records, headers, result_count = [], {}, 0
    for container in ("annotations", "predictions"):
        annotations = task.get(container, [])
        if not isinstance(annotations, list):
            raise ValueError("BFMD annotation containers must be lists")
        headers[container] = []
        for ai, annotation in enumerate(annotations):
            if not isinstance(annotation, dict) or not isinstance(
                annotation.get("result"), list
            ):
                raise ValueError("BFMD annotation needs a result list")
            headers[container].append(
                {k: v for k, v in annotation.items() if k != "result"}
            )
            for ri, item in enumerate(annotation["result"]):
                if not isinstance(item, dict) or not isinstance(
                    item.get("value"), dict
                ):
                    raise ValueError("BFMD result needs an object value")
                result_count += 1
                value = item["value"]
                labels, choices = (
                    value.get("timelinelabels", []),
                    value.get("choices", []),
                )
                if not _strings(labels) or not _strings(choices):
                    raise ValueError("BFMD labels and choices must be string lists")
                ranges = value.get("ranges", [])
                if not isinstance(ranges, list):
                    raise ValueError("BFMD ranges must be a list")
                for index, raw_range in enumerate(ranges or [None]):
                    interval = _interval(raw_range)
                    issues = []
                    manual = (
                        container == "annotations"
                        and item.get("origin") == "manual"
                        and not annotation.get("was_cancelled", False)
                    )
                    if not manual:
                        issues.append("not_active_manual_annotation")
                    if interval is None:
                        issues.append("invalid_source_frame_interval")
                    if not labels and not choices:
                        issues.append("missing_source_label")
                    if set(labels) - LABELS:
                        issues.append("unknown_timeline_label")
                    if choices:
                        issues.append("choice_layer_contact_alignment_unverified")
                    timeline = (
                        item.get("type") == "timelinelabels"
                        and "timelinelabels" in value
                        and "choices" not in value
                    )
                    choice = (
                        item.get("type") == "choices"
                        and "choices" in value
                        and "timelinelabels" not in value
                    )
                    if not (timeline or choice):
                        issues.append("source_result_type_disagrees_with_value")
                    point = interval is not None and interval[0] == interval[1]
                    records.append(
                        {
                            "id": f"bfmd:{match_name}:{container}:{ai}:{ri}:{index}",
                            "source_match_name": match_name,
                            "mode": mode,
                            "source_container": container,
                            "source_annotation_index": ai,
                            "source_result_index": ri,
                            "source_range_index": index,
                            "source_result_id": item.get("id"),
                            "source_origin": item.get("origin"),
                            "active_manual": manual,
                            "source_labels": list(labels),
                            "source_choices": list(choices),
                            "source_interval": interval,
                            "source_contact_frame": interval[0]
                            if point and "hit" in labels
                            else None,
                            "source_interval_bounds": "publisher ranges; inclusivity undocumented",
                            "source_frame_base": "undocumented; preserve published ordinal",
                            "source_declared_fps": 30,
                            "split": "unassigned",
                            "media_alignment": "unverified",
                            "contact_adjudication": "unverified",
                            "training_ready": False,
                            "side": "unknown",
                            "side_eligible": False,
                            "player_id": None,
                            "raw": item,
                            "issues": issues,
                        }
                    )
    typed, hit_counts, unknown_points = defaultdict(set), Counter(), set()
    rallies, replays = [], []
    for r in records:
        interval = r["source_interval"]
        if (
            not r["active_manual"]
            or interval is None
            or "source_result_type_disagrees_with_value" in r["issues"]
        ):
            continue
        if "Rally" in r["source_labels"]:
            rallies.append(interval)
        if "replay" in r["source_labels"]:
            replays.append(interval)
        if interval[0] == interval[1]:
            typed[interval[0]].update(set(r["source_labels"]) & set(TYPES))
            if "unknown_timeline_label" in r["issues"]:
                unknown_points.add(interval[0])
            if "hit" in r["source_labels"]:
                hit_counts[interval[0]] += 1
    overlaps = [
        (max(a, c), min(b, d))
        for a, b in rallies
        for c, d in replays
        if max(a, c) < min(b, d)
    ]
    for r in records:
        interval, labels = r["source_interval"], r["source_labels"]
        point = interval is not None and interval[0] == interval[1]
        candidates = (
            sorted(typed.get(interval[0], set()))
            if point and r["active_manual"]
            else []
        )
        r["source_types_at_point"] = candidates
        r["kind"], r["family"] = (
            TYPES[candidates[0]] if len(candidates) == 1 else ("unknown", "unknown")
        )
        if len(candidates) > 1:
            r["issues"].append("conflicting_source_types_at_frame")
        if point and interval[0] in unknown_points:
            r["issues"].append("unresolved_source_labels_at_frame")
            r["kind"], r["family"] = "unknown", "unknown"
        is_hit = "hit" in labels
        if interval is not None and any(
            a <= interval[0] <= b or interval[0] <= a <= interval[1]
            for a, b in overlaps
        ):
            if set(labels) & {"Rally", "replay", "hit"}:
                r["issues"].append("conflicting_source_live_replay_context")
        if is_hit and not point:
            r["issues"].append("nonpoint_contact_marker")
        if is_hit and point and hit_counts[interval[0]] > 1:
            r["issues"].append("duplicate_source_hit_frame")
        contained = interval is not None and any(
            a <= interval[0] <= interval[1] <= b for a, b in rallies
        )
        r["inside_source_rally"] = (
            contained if rallies and interval is not None else None
        )
        if is_hit and not contained:
            r["issues"].append("contact_outside_source_rally")
        contact_blockers = {
            "not_active_manual_annotation",
            "invalid_source_frame_interval",
            "nonpoint_contact_marker",
            "duplicate_source_hit_frame",
            "contact_outside_source_rally",
            "source_result_type_disagrees_with_value",
            "conflicting_source_live_replay_context",
        }
        r["contact_label_eligible"] = (
            is_hit and point and not contact_blockers.intersection(r["issues"])
        )
        r["family_eligible"] = (
            r["contact_label_eligible"]
            and len(candidates) == 1
            and interval[0] not in unknown_points
        )
        r["source_label_eligible"] = not r["issues"]
    return records, {
        "task": {
            k: v for k, v in task.items() if k not in ("annotations", "predictions")
        },
        "annotation_headers": headers,
        "source_result_count": result_count,
    }


def _safe_path(root, relative):
    path = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or path.is_absolute()
        or ".." in path.parts
        or ":" in relative
    ):
        raise ValueError(
            "BFMD source paths must be relative and stay inside the source directory"
        )
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("BFMD source paths must stay inside the source directory")
    return target


def _read_source(root, entries):
    contents, source_files = {}, []
    for entry in entries:
        name = entry["path"]
        if name in contents:
            raise ValueError("Duplicate BFMD source path")
        paths = {_safe_path(root, n) for n in (name, entry["download_name"])}
        found = [p for p in sorted(paths) if p.is_file()]
        if not found:
            raise ValueError(f"Missing BFMD source file: {name}")
        for path in found:
            if (
                path.stat().st_size != entry["bytes"]
                or not 0 < entry["bytes"] <= MAX_FILE_BYTES
            ):
                raise ValueError(f"BFMD source size mismatch: {name}")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError(f"BFMD source hash mismatch: {name}")
            contents[name] = data
        source_files.append({k: entry[k] for k in ("path", "bytes", "sha256")})
    return contents, source_files


def _serialize(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def import_bfmd(source, output, *, spec=None):
    """Import a pinned local reference snapshot; never open the application Store."""
    spec = pinned_source() if spec is None else spec
    root, destination = Path(source).resolve(), Path(output).resolve()
    if destination == root or destination.is_relative_to(root):
        raise ValueError("Write BFMD output outside the immutable source directory")
    raw, source_files = _read_source(root, spec["files"])
    if len(raw) != spec["expected"]["files"]:
        raise ValueError("BFMD source file count differs from the pinned snapshot")
    videos = read_rows(raw["Badminton_video_list.csv"])
    matches = {v["match_name"]: v for v in videos}
    if len(matches) != len(videos) or len(matches) != spec["expected"]["matches"]:
        raise ValueError("BFMD match catalog is repeated or incomplete")
    metadata, metadata_wrappers, ignored_backups = {}, [], []
    for name, data in raw.items():
        if not name.startswith("annotations/metadata/"):
            continue
        if not name.endswith(".json"):
            ignored_backups.append(name)
            continue
        value = _json(data)
        if isinstance(value, list):
            if len(value) != 1 or not isinstance(value[0], dict):
                raise ValueError("BFMD metadata list must wrap exactly one object")
            value = value[0]
            metadata_wrappers.append(name)
        match = PurePosixPath(name).stem
        if (
            not isinstance(value, dict)
            or value.get("match_name") != match
            or match not in matches
        ):
            raise ValueError("BFMD metadata identity disagrees with the match catalog")
        metadata[match] = value
    if len(metadata) != spec["expected"]["metadata_matches"]:
        raise ValueError("BFMD metadata count differs from the pinned snapshot")
    events, summaries, sources, metadata_rallies = [], [], {}, []
    total_results = 0
    for match, video in matches.items():
        mode = video["type"]
        if mode not in ("singles", "doubles"):
            raise ValueError("Unknown BFMD match mode")
        category = "shot_type" if mode == "singles" else "hits_doubles"
        filename = f"annotations/{category}/{match}.json"
        records, header = normalize_timeline(_json(raw[filename]), match, mode)
        total_results += header["source_result_count"]
        timeline = {
            tuple(r["source_interval"])
            for r in records
            if r["active_manual"]
            and "Rally" in r["source_labels"]
            and r["source_interval"] is not None
        }
        meta_intervals = set()
        for game, group in metadata.get(match, {}).get("games", {}).items():
            for index, rally in enumerate(group.get("rallies", [])):
                interval = _interval(rally)
                if interval is not None:
                    meta_intervals.add(tuple(interval))
                metadata_rallies.append(
                    {
                        "source_match_name": match,
                        "game": game,
                        "source_index": index,
                        "source_interval": interval,
                        "raw": rally,
                        "origin": "metadata; not assumed manual",
                        "matches_manual_timeline": interval is not None
                        and tuple(interval) in timeline,
                        "training_ready": False,
                    }
                )
        for record in records:
            record.update(
                source_file=filename,
                source_sha256=hashlib.sha256(raw[filename]).hexdigest(),
            )
        summary = {
            "match_name": match,
            "mode": mode,
            "source_video": video,
            "record_count": len(records),
            "metadata_only_intervals": len(meta_intervals - timeline),
            "timeline_only_intervals": len(timeline - meta_intervals)
            if match in metadata
            else None,
            "metadata_available": match in metadata,
            "split": "unassigned",
            "original_source_overlap_reviewed": False,
            "media_alignment": "unverified",
        }
        summaries.append(summary)
        sources[match] = header
        events.extend(records)
    if total_results != spec["expected"]["annotation_results"]:
        raise ValueError("BFMD result count differs from the pinned snapshot")
    payloads = {
        "events.jsonl": b"".join(_serialize(r) for r in events),
        "matches.json": _serialize(summaries),
        "source_tasks.json": _serialize(sources),
        "metadata.json": _serialize(metadata),
        "metadata_rallies.json": _serialize(metadata_rallies),
        "source_indexes.json": _serialize(
            {"video_list": videos, "match_index": read_rows(raw["match_index.csv"])}
        ),
    }
    report = {
        "dataset": spec["dataset"],
        "normalization_version": spec["normalization_version"],
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(spec, sort_keys=True).encode()
        ).hexdigest(),
        "source_files": source_files,
        "source": spec,
        "match_count": len(matches),
        "record_count": len(events),
        "source_result_count": total_results,
        "mode_counts": dict(Counter(v["type"] for v in videos)),
        "source_label_counts": dict(
            Counter(label for r in events for label in r["source_labels"])
        ),
        "source_origin_counts": dict(Counter(str(r["source_origin"]) for r in events)),
        "issues": dict(Counter(issue for r in events for issue in r["issues"])),
        "conflicting_point_type_frames": len(
            {
                (r["source_match_name"], r["source_interval"][0])
                for r in events
                if "conflicting_source_types_at_frame" in r["issues"]
            }
        ),
        "contact_label_eligible_records": sum(
            r["contact_label_eligible"] for r in events
        ),
        "family_eligible_records": sum(r["family_eligible"] for r in events),
        "metadata_rally_count": len(metadata_rallies),
        "metadata_only_intervals": sum(s["metadata_only_intervals"] for s in summaries),
        "metadata_singleton_wrappers": metadata_wrappers,
        "ignored_backup_files": ignored_backups,
        "side_eligible_records": 0,
        "training_ready_records": 0,
        "media_alignment": "unverified",
        "split": "unassigned; original-broadcast and cross-corpus overlap audit required",
        "rights": spec["rights"],
        "boundary_policy": "Preserve source ranges; no invented exact serve/contact/rally-end or negative live/replay labels",
        "output_sha256": {
            n: hashlib.sha256(b).hexdigest() for n, b in payloads.items()
        },
    }
    payloads["manifest.json"] = _serialize(report)
    # Recheck every source before any writes, including alternate local copies.
    _read_source(root, spec["files"])
    destination.mkdir(parents=True, exist_ok=True)
    lock = destination / ".bfmd-import.lock"
    try:
        owner = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError(
            "BFMD output has an import lock; inspect its owner before retrying"
        ) from exc
    try:
        with owner:
            owner.write(
                json.dumps(
                    {"pid": os.getpid(), "created": psutil.Process().create_time()}
                )
            )
            owner.flush()
            existing = {p.name for p in destination.iterdir() if p != lock}
            if existing:
                if existing == set(payloads) and all(
                    (destination / n).is_file() and (destination / n).read_bytes() == b
                    for n, b in payloads.items()
                ):
                    return report
                raise ValueError(
                    "BFMD output is incomplete, changed or another version; preserve it and choose a new directory"
                )
            for name, data in payloads.items():
                path = destination / name
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(data)
                temporary.replace(path)
    finally:
        lock.unlink()
    return report
