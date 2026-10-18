"""Pinned author labels for recognition research, separate from app truth.

Action intervals are not contact instants. The smaller bilingual publication
adds contact-frame references for 40 rallies; these still need media alignment.
"""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from .datasets import source_path, verify_output_version
from .video import write_json

MANIFEST = Path(__file__).with_name("finebadminton_manifest.json")
FAMILIES = {
    "serve": None,
    "clear": "clear",
    "net lift": "lift",
    "net shot": "net",
    "cross-court net shot": "net",
    "drop shot": "drop",
    # The paired Chinese publication calls this 杀球, distinct from 扑球.
    "kill": "smash",
    "drive": "drive",
    "push shot": "other",
    "block": "other",
    "net kill": "other",
}
PARALLEL_TYPES = {
    "发球": "serve",
    "高远球": "clear",
    "挑球": "net lift",
    "放网前球": "net shot",
    "勾球": "cross-court net shot",
    "吊球": "drop shot",
    "杀球": "kill",
    "抽球": "drive",
    "推球": "push shot",
    "挡网": "block",
    "扑球": "net kill",
    "": "",
}
PARALLEL_SIDES = {"正手击球": "forehand", "反手击球": "backhand"}


def pinned_source():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def integer(value):
    return type(value) is int and value >= 0


def interval(row):
    start, end = row.get("start_frame"), row.get("end_frame")
    return (start, end) if integer(start) and integer(end) and start <= end else None


def parallel_references(chinese, english):
    """Require one-to-one bilingual records; never join by approximate time."""
    if len(chinese) != len(english):
        raise ValueError("Parallel publications have different rally counts")
    references = {}
    for original, translated in zip(chinese, english):
        match = re.fullmatch(r"(\d{4})_\d+\.mp4", original.get("video", ""))
        bounds = interval(original)
        if (
            match is None
            or bounds is None
            or original.get("video") != translated.get("video")
            or bounds != interval(translated)
            or original.get("fps") != translated.get("fps")
            or len(original["hitting"]) != len(translated["hitting"])
        ):
            raise ValueError("Parallel publications disagree on rally identity")
        for index, (left, right) in enumerate(
            zip(original["hitting"], translated["hitting"])
        ):
            key = (match[1], *bounds, index)
            if (
                key in references
                or interval(left) != interval(right)
                or left.get("hit_frame") != right.get("hit_frame")
                or left.get("player") != right.get("player")
                or left.get("hit_type") not in PARALLEL_TYPES
                or PARALLEL_TYPES.get(left.get("hit_type")) != right.get("hit_type")
            ):
                raise ValueError("Parallel publications disagree on stroke identity")
            original_sides = {
                PARALLEL_SIDES[action]
                for action in left.get("player_actions", [])
                if action in PARALLEL_SIDES
            }
            translated_sides = set(right.get("player_actions", [])).intersection(
                ("forehand", "backhand")
            )
            if original_sides != translated_sides:
                raise ValueError("Parallel publications disagree on stroke side")
            references[key] = {"original": left, "translated": right}
    return references


def normalize_match(rallies, match_id, references=None):
    if not re.fullmatch(r"\d{4}", match_id):
        raise ValueError("Source match IDs must contain four digits")
    references = references or {}
    records, used = [], set()
    for rally_index, rally in enumerate(rallies):
        bounds = interval(rally)
        fps = rally.get("fps")
        rally_issues = []
        if bounds is None:
            rally_issues.append("invalid_rally_interval")
        if rally.get("video") != f"{match_id}.mp4":
            raise ValueError("Annotation video does not match its source file")
        if type(fps) not in (int, float) or not math.isfinite(fps) or fps <= 0:
            rally_issues.append("invalid_declared_fps")
        duration = rally.get("duration_frames")
        convention = (
            "inclusive"
            if bounds and duration == bounds[1] - bounds[0] + 1
            else "exclusive"
            if bounds and duration == bounds[1] - bounds[0]
            else "inconsistent"
        )
        for index, hit in enumerate(rally["hitting"]):
            issues = list(rally_issues)
            action = interval(hit)
            family_name = hit.get("Foundational Actions Level", {}).get("hit type")
            family = FAMILIES.get(family_name, "unknown")
            if family == "unknown":
                issues.append("unresolved_source_family")
            if action is None:
                issues.append("missing_or_invalid_action_interval")
            elif bounds and not bounds[0] <= action[0] <= action[1] <= bounds[1]:
                issues.append("action_outside_rally")
            actions = hit.get("Tactical Semantics Level", {}).get("player actions", [])
            tokens = (
                {str(a).strip().lower() for a in actions}
                if isinstance(actions, list)
                else set()
            )
            sides = tokens.intersection(("forehand", "backhand"))
            side = next(iter(sides)) if len(sides) == 1 else "unknown"
            if side == "unknown":
                issues.append("missing_or_conflicting_stroke_side")
            reference = references.get((match_id, *bounds, index)) if bounds else None
            contact = None
            reference_side = "unknown"
            if reference:
                translated = reference["translated"]
                if (
                    interval(translated) != action
                    or translated.get("hit_type") != family_name
                    or translated.get("player") != hit.get("player")
                ):
                    raise ValueError(
                        "Contact publication disagrees with released stroke"
                    )
                key = (match_id, *bounds, index)
                if key in used:
                    raise ValueError(
                        "A contact reference matched multiple released rallies"
                    )
                used.add(key)
                reference_sides = set(
                    translated.get("player_actions", [])
                ).intersection(("forehand", "backhand"))
                if len(reference_sides) == 1:
                    reference_side = next(iter(reference_sides))
                if reference_side != side:
                    issues.append("published_side_disagrees_with_release")
                contact = translated.get("hit_frame")
                if not integer(contact) or not bounds[0] <= contact <= bounds[1]:
                    issues.append("invalid_published_contact_frame")
                    contact = None
                elif action and not action[0] <= contact <= action[1]:
                    issues.append("published_contact_outside_action")
            source_end = hit.get("Foundational Actions Level", {}).get("hitter")
            kind = "serve" if family_name == "serve" else "shot"
            unusable = set(issues).difference(
                {
                    "unresolved_source_family",
                    "missing_or_conflicting_stroke_side",
                    "published_side_disagrees_with_release",
                }
            )
            records.append(
                {
                    "id": f"finebadminton:{match_id}:{rally_index}:{index}",
                    "dataset": "Finebadminton-20K",
                    "mode": "singles",
                    "source_match_id": match_id,
                    "source_rally_index": rally_index,
                    "source_stroke_index": index,
                    "source_video": rally["video"],
                    "source_declared_fps": fps,
                    "source_rally_interval": bounds,
                    "source_rally_duration_frames": duration,
                    "rally_duration_convention": convention,
                    "source_action_interval": action,
                    "source_contact_frame": contact,
                    "published_contact_side": reference_side,
                    "contact_provenance": "bilingual publication"
                    if reference
                    else "not published in the full release",
                    "source_player_name": hit.get("player"),
                    "source_court_end": source_end
                    if source_end in ("top", "bottom")
                    else None,
                    "kind": kind,
                    "family": family,
                    "side": side,
                    "family_eligible": family != "unknown" and not unusable,
                    "side_eligible": side != "unknown"
                    and not unusable
                    and "published_side_disagrees_with_release" not in issues,
                    "issues": issues,
                    "split": "unassigned",
                    "media_alignment": "unverified",
                    "contact_adjudication": "unverified",
                    "training_ready": False,
                    "raw": hit,
                    "raw_contact_reference": reference,
                }
            )
    expected = {key for key in references if key[0] == match_id}
    if used != expected:
        raise ValueError("Some published contact references have no released stroke")
    return records


def verified_json(root, entry):
    data = source_path(root, entry["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError(f"Dataset source hash mismatch: {entry['path']}")
    return json.loads(data)


def import_finebadminton(source, destination, *, spec=None):
    spec = spec or pinned_source()
    verify_output_version(destination, spec)
    if len(spec["parallel_files"]) != 2:
        raise ValueError(
            "Both original and translated contact publications are required"
        )
    references = parallel_references(
        *(verified_json(source, entry) for entry in spec["parallel_files"])
    )
    ids = [entry["match_id"] for entry in spec["files"]]
    if len(ids) != len(set(ids)) or {key[0] for key in references}.difference(ids):
        raise ValueError("Source manifest has duplicate or missing match IDs")
    records = [
        record
        for entry in spec["files"]
        for record in normalize_match(
            verified_json(source, entry), entry["match_id"], references
        )
    ]
    report = {
        "dataset": spec["dataset"],
        "normalization_version": spec["normalization_version"],
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(spec, sort_keys=True).encode()
        ).hexdigest(),
        "source": spec,
        "record_count": len(records),
        "match_count": len(ids),
        "rally_count": len(
            {(r["source_match_id"], r["source_rally_index"]) for r in records}
        ),
        "family_counts": dict(
            Counter("serve" if r["kind"] == "serve" else r["family"] for r in records)
        ),
        "side_counts": dict(Counter(r["side"] for r in records)),
        "issues": dict(Counter(i for r in records for i in r["issues"])),
        "family_eligible_records": sum(r["family_eligible"] for r in records),
        "side_eligible_records": sum(r["side_eligible"] for r in records),
        "published_contact_records": sum(
            r["source_contact_frame"] is not None for r in records
        ),
        "training_ready_records": 0,
        "media_alignment": "unverified",
        "contact_adjudication": "unverified",
        "split": "unassigned; deduplicate source matches before splitting",
    }
    destination = Path(destination)
    write_json(destination / "records.json", records)
    write_json(destination / "manifest.json", report)
    return report
