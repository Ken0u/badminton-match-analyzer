"""Read-only weak image-foot/pose correspondence, never actor or scene truth.

No media is decoded and no model runtime is invoked. The original producer's
immutable seals are checked individually: this new consumer is not part of its
historical all-module inventory. Every original weak reference stays explicit.
"""

import argparse
import json
import math
import platform
import sqlite3
import time
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from . import aicup_pose_pilot as producer

PROTOCOL = {
    "schema_version": 1,
    "name": "aicup-actor-correspondence-v1",
    "preparation_sha256": "24110a19919ba0307fbeff375d64ea973ab535ac6bf8b63f2b78cf7ff8563dea",
    "completion_sha256": "fe0021fca0236d2701f86d2274b3799ffae7ca5a77fffaca419e296c13deb523",
    "expected": {"clips": 45, "native_frames": 24273, "references": 784},
    "source_schema": "https://sites.google.com/view/coachai-challenge-2023/tasks/track1",
    "coordinates": "Image-pixel dominant foot/toe; jumping uses court-plane projection",
    "landing": "Trajectory-end projection; not contact or automatically rally end",
    "interval": "Both inclusive [H-1,H] frames; H0 censored and unavailable",
    "representations": ["ankle", "box_bottom"],
    "ankle_indices": [15, 16],
    "minimum_ankle_confidence": 0.25,
    "minimum_candidates": 2,
    "maximum_normalized_distance": 0.5,
    "minimum_normalized_margin": 0.25,
    "normalization": "Each candidate's own observed positive box height",
    "pair": "Same distinct hitter/defender tracks at both endpoints and representations; one camera and valid calibration",
    "forbidden_matching_inputs": ["family", "side", "landing", "A/B", "winner"],
    "limits": {"runtime_seconds": 14400, "output_bytes": 1073741824, "audits": 1},
    "image_bytes": 0,
    "native_passes": 0,
    "real_fits": 0,
    "training_ready": False,
    "accuracy_established": False,
    "complete_rally_references": {"accepted": 0, "required": 2},
}

read_json = producer.read_json
digest = producer.digest
publish = producer.publish
inside = producer.inside


def finite(values):
    return all(type(v) in (int, float) and math.isfinite(v) for v in values)


def coordinate(raw, prefix, width, height):
    """Return availability reasons, rather than inventing a location."""
    try:
        values = [raw[prefix + axis] for axis in ("X", "Y")]
        if any(type(v) not in (str, int, float) for v in values):
            return None, "missing_or_invalid_coordinate"
        x, y = map(float, values)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, "missing_or_invalid_coordinate"
    if not finite([x, y]):
        return None, "nonfinite_coordinate"
    if not (0 <= x < width and 0 <= y < height):
        return None, "coordinate_outside_display"
    return [x, y], None


def candidate_geometry(person, width, height):
    """A track and two observation representations; no inferred floor point."""
    identity, box, points = (
        person.get("track_id"),
        person.get("box", []),
        person.get("keypoints", []),
    )
    if type(identity) is not int or identity < 1:
        return None, "missing_track"
    if (
        not isinstance(box, list)
        or len(box) != 4
        or not finite(box)
        or not 0 <= box[0] < box[2] <= width
        or not 0 <= box[1] < box[3] <= height
    ):
        return None, "invalid_box"
    ankles = []
    if not isinstance(points, list) or len(points) not in (0, 17):
        return None, "invalid_keypoints"
    for point in points:
        if (
            not isinstance(point, list)
            or len(point) != 3
            or not finite(point)
            or not 0 <= point[2] <= 1
        ):
            return None, "invalid_keypoints"
    if points:
        for index in PROTOCOL["ankle_indices"]:
            x, y, confidence = points[index]
            if confidence >= PROTOCOL["minimum_ankle_confidence"]:
                if not (0 <= x < width and 0 <= y < height):
                    return None, "ankle_outside_display"
                ankles.append([x, y])
    return {
        "track_id": identity,
        "height": box[3] - box[1],
        "ankle": ankles,
        "box_bottom": [[(box[0] + box[2]) / 2, box[3]]],
    }, None


def rank(point, candidates, representation):
    distances = sorted(
        (
            {
                "track_id": c["track_id"],
                "normalized_distance": min(
                    math.dist(point, p) for p in c[representation]
                )
                / c["height"],
            }
            for c in candidates
            if c[representation]
        ),
        key=lambda row: (row["normalized_distance"], row["track_id"]),
    )
    reasons = []
    if len(distances) < PROTOCOL["minimum_candidates"]:
        reasons.append("insufficient_candidates")
    if distances:
        if (
            distances[0]["normalized_distance"]
            > PROTOCOL["maximum_normalized_distance"]
        ):
            reasons.append("remote")
        if len(distances) > 1:
            gap = (
                distances[1]["normalized_distance"]
                - distances[0]["normalized_distance"]
            )
            if gap == 0:
                reasons.append("tie")
            if gap < PROTOCOL["minimum_normalized_margin"]:
                reasons.append("small_margin")
    return {
        "distances": distances,
        "candidate_track": distances[0]["track_id"] if not reasons else None,
        "reasons": reasons,
    }


def endpoint(frame, points, width, height):
    candidates, rejected = [], []
    identities = [p.get("track_id") for p in frame["players"]]
    duplicates = {
        identity
        for identity in identities
        if type(identity) is int and identities.count(identity) > 1
    }
    for person in frame["players"]:
        geometry, reason = candidate_geometry(person, width, height)
        if geometry is not None and geometry["track_id"] in duplicates:
            geometry, reason = None, "duplicate_track"
        if geometry is not None:
            candidates.append(geometry)
        else:
            rejected.append({"track_id": person.get("track_id"), "reason": reason})
    matching = {}
    for role, point in points.items():
        matching[role] = {
            representation: rank(point, candidates, representation)
            if point is not None
            else {
                "distances": [],
                "candidate_track": None,
                "reasons": ["unavailable_coordinate"],
            }
            for representation in PROTOCOL["representations"]
        }
    return {
        "frame": frame["frame"],
        "camera_segment_start_frame": frame["camera_segment_start_frame"],
        "calibration_valid": frame["calibration_valid"],
        "matching": matching,
        "rejected_observations": rejected,
    }


def diagnose(reference, result, video):
    """Labels annotate aggregate groups only; they never select an observation."""
    points, reasons = {}, []
    for role, prefix in (
        ("hitter", "HitterLocation"),
        ("defender", "DefenderLocation"),
    ):
        point, reason = coordinate(
            reference["raw"], prefix, video["width"], video["height"]
        )
        points[role] = point
        if reason:
            reasons.append(role + ":" + reason)
    h = reference["source_contact_frame"]
    interval = [h - 1, h] if type(h) is int and h > 0 else None
    available = interval is not None and h < len(result["frames"])
    if not available:
        reasons.append("censored_H0" if h == 0 else "unavailable_interval")
    endpoints = (
        [
            endpoint(result["frames"][frame], points, video["width"], video["height"])
            for frame in interval
            if available
        ]
        if available
        else []
    )
    choices = defaultdict(list)
    for item in endpoints:
        if item["calibration_valid"] is not True:
            reasons.append("unavailable_calibration")
        for role, representations in item["matching"].items():
            for name, ranked in representations.items():
                choices[role].append(ranked["candidate_track"])
                reasons.extend(role + ":" + name + ":" + r for r in ranked["reasons"])
    if len({e["camera_segment_start_frame"] for e in endpoints}) > 1:
        reasons.append("camera_boundary")
    selected = {}
    for role in ("hitter", "defender"):
        values = choices[role]
        selected[role] = (
            values[0]
            if len(values) == 4 and None not in values and len(set(values)) == 1
            else None
        )
        if len({v for v in values if v is not None}) > 1:
            reasons.append(role + ":representation_or_endpoint_disagreement")
        if selected[role] is None:
            reasons.append(role + ":unresolved")
    if selected["hitter"] is not None and selected["hitter"] == selected["defender"]:
        reasons.append("same_hitter_defender")
    return {
        "reference_id": reference["id"],
        "clip_key": reference["clip_key"],
        "published_interval": interval,
        "interval_available": available,
        "coordinates": points,
        "endpoints": endpoints,
        "weak_pair": selected if not reasons else None,
        "reasons": sorted(set(reasons)),
        "correct_hitter": None,
        "source_scene_truth": "unknown",
        "training_ready": False,
    }


def check_deadline(granted_at, deadline):
    if (
        not finite([granted_at, deadline])
        or not granted_at <= time.time() < deadline
        or not 0 < deadline - granted_at <= PROTOCOL["limits"]["runtime_seconds"]
    ):
        raise ValueError("Expired or unbounded original correspondence deadline")


def code_seals():
    folder = Path(__file__).parent
    paths = [
        *sorted(folder.glob("*.py")),
        folder.parents[1] / "scripts/audit_aicup_actor_correspondence.py",
        folder.parents[1]
        / "data/manifests/aicup_actor_correspondence_protocol_v1.json",
    ]
    return {p.relative_to(folder.parents[1]).as_posix(): digest(p) for p in paths}


def verify_inventory(folder, expected):
    if producer.inventory(folder) != expected:
        raise ValueError("Changed or incomplete immutable artifact inventory")


def verify_producer_code(seals):
    folder = Path(producer.__file__).parent
    # Preserve the original inventory; do not compare it to a later glob result.
    for name, expected in seals.items():
        path = inside(folder.parents[1], name) if "/" in name else inside(folder, name)
        if digest(path) != expected:
            raise ValueError("Changed original producer dependency: " + name)


def canonical_cohort(freeze, cohort):
    sources = {k: Path(v["path"]) for k, v in freeze["sources"].items()}
    producer.verify_sources(sources)
    clips, groups = read_json(sources["clips"]), read_json(sources["groups"])
    folds, contexts = producer.capture_folds(clips, groups)
    rows = producer.canonical_rows(sources["archive"], clips, folds)
    # The complete cohort, not merely normalized family targets, is authoritative.
    if producer.select_cohort(rows) != cohort:
        raise ValueError("Prepared rows/coordinates contradict canonical original CSV")
    for clip in freeze["clips"]:
        if (
            clip["fold"] != folds[clip["key"]]
            or clip["context"] != contexts[clip["key"]]
        ):
            raise ValueError("Conflicting development capture fold/context")


def validate_clocks(video, ledger, times):
    rows = ledger["rows"]
    if (
        len(rows) != video["frame_count"]
        or len(times) != len(rows)
        or ledger["source_sha256"] != video["sha256"]
        or ledger["rotation"] != video["rotation"]
        or ledger["display_dimensions"] != [video["width"], video["height"]]
    ):
        raise ValueError("Conflicting native source clock/display")
    previous = None
    for index, row in enumerate(rows):
        if type(row["pts"]) is not int or row["frame"] != index:
            raise ValueError("Invalid integer native frame/PTS")
        if any(type(v) is not int or v <= 0 for v in row["time_base"]):
            raise ValueError("Invalid rational native time base")
        relative = row["pts"] * Fraction(*row["time_base"]) - ledger[
            "origin_pts"
        ] * Fraction(*ledger["stream_time_base"])
        if (
            Fraction(*row["relative_time"]) != relative
            or times[index] != round(float(relative), 8)
            or (previous is not None and relative <= previous)
        ):
            raise ValueError("Invalid or nonmonotonic native clock")
        previous = relative


def load_inputs(prepared, native):
    """Integrity-only read; does not compute coordinate/pose correspondence."""
    prepared, native = Path(prepared).resolve(), Path(native).resolve()
    if digest(prepared / "freeze.json") != PROTOCOL["preparation_sha256"]:
        raise ValueError("Changed original preparation freeze")
    if digest(native / "completion.json") != PROTOCOL["completion_sha256"]:
        raise ValueError("Changed original native completion")
    freeze, completion = (
        read_json(prepared / "freeze.json"),
        read_json(native / "completion.json"),
    )
    if (
        completion["freeze_sha256"] != PROTOCOL["preparation_sha256"]
        or freeze["protocol"] != producer.PROTOCOL
    ):
        raise ValueError("Conflicting original protocol/completion")
    verify_producer_code(freeze["code"])
    verify_inventory(
        prepared, freeze["artifacts"] | {"freeze.json": PROTOCOL["preparation_sha256"]}
    )
    verify_inventory(
        native,
        completion["artifacts"] | {"completion.json": PROTOCOL["completion_sha256"]},
    )
    claim = prepared.with_name(prepared.name + "-native-start.json")
    if Path(completion["execution_claim"]) != claim or read_json(claim) != {
        "freeze_sha256": PROTOCOL["preparation_sha256"],
        "output": str(native),
    }:
        raise ValueError("Changed original native execution claim")
    cohort = read_json(prepared / "cohort.json")
    canonical_cohort(freeze, cohort)
    references = cohort["reference_rows"]
    clips = freeze["clips"]
    if any(c["fold"] not in producer.FOLDS for c in clips):
        raise ValueError("Held-out source in original development cohort")
    if (len(clips), sum(c["frames"] for c in clips), len(references)) != tuple(
        PROTOCOL["expected"][k] for k in ("clips", "native_frames", "references")
    ):
        raise ValueError("Incomplete original denominator")
    if len(completion["receipts"]) != len(clips):
        raise ValueError("Incomplete original receipts")
    observations = []
    for index, clip in enumerate(clips):
        folder, directory = (
            inside(prepared, clip["folder"]),
            native / f"clip-{index:02d}",
        )
        video, ledger = (
            read_json(folder / "video.json"),
            read_json(folder / "native-clock.json"),
        )
        times = read_json(folder / "data" / video["id"] / "timestamps.json")
        scan, result = (
            read_json(folder / "camera.json"),
            read_json(directory / "players.json"),
        )
        validate_clocks(video, ledger, times)
        if (
            video["sha256"] != digest(folder / "source.mp4")
            or clip["frames"] != video["frame_count"]
        ):
            raise ValueError("Changed clip source/frame identity")
        coverage = producer.validate_pose(result, video, times, scan, ledger)
        refs = [r for r in references if r["clip_key"] == clip["key"]]
        support = producer.reference_support(refs, result)
        receipt = producer.clip_receipt(clip, coverage, support, directory)
        if (
            support != read_json(directory / "support.json")
            or receipt != read_json(directory / "receipt.json")
            or receipt != completion["receipts"][index]
        ):
            raise ValueError("Changed original native support/receipt")
        observations.append((clip, video, result, refs))
    expected_summary = {
        "clips": len(clips),
        "native_frames": sum(c["frames"] for c in clips),
        "freeze_sha256": PROTOCOL["preparation_sha256"],
    }
    if completion["summary"] != expected_summary:
        raise ValueError("Changed native completion denominator")
    data = Path(completion["shared_data"])
    if producer.annotation_snapshot(data) != completion["original_annotations_sha256"]:
        raise ValueError("Original annotation history changed")
    with sqlite3.connect(
        (data / "catalog.sqlite3").as_uri() + "?mode=ro", uri=True
    ) as db:
        row = db.execute(
            "SELECT document FROM jobs WHERE id=?", (completion["job_id"],)
        ).fetchone()
    job = json.loads(row[0]) if row else {}
    if job.get("status") != "completed" or job.get("summary") != expected_summary:
        raise ValueError("Original shared Store completion is absent or changed")
    return observations


def aggregate(observations, diagnostics):
    groups = defaultdict(Counter)
    distances = defaultdict(list)
    references = {r["id"]: (clip, r) for clip, _, _, refs in observations for r in refs}
    if len(diagnostics) != len(references) or [
        d["reference_id"] for d in diagnostics
    ] != list(references):
        raise ValueError("Incomplete/duplicate diagnostic denominator")
    for diagnostic in diagnostics:
        clip, ref = references[diagnostic["reference_id"]]
        dimensions = (
            "all",
            "fold:" + clip["fold"],
            "context:" + clip["context"],
            "family:" + str(ref["family"]),
            "side:" + ref["side"],
            "family-side:" + str(ref["family"]) + ":" + ref["side"],
        )
        for dimension in dimensions:
            c = groups[dimension]
            c["references"] += 1
            c["available_intervals"] += diagnostic["interval_available"]
            c["weak_pairs"] += diagnostic["weak_pair"] is not None
            c["unresolved_pairs"] += diagnostic["weak_pair"] is None
            c["training_ready"] += diagnostic["training_ready"]
            for reason in diagnostic["reasons"]:
                c["reason:" + reason] += 1
            for frame in diagnostic["endpoints"]:
                for role, reps in frame["matching"].items():
                    for name, ranked in reps.items():
                        for entry in ranked["distances"]:
                            distances[dimension + ":" + role + ":" + name].append(
                                entry["normalized_distance"]
                            )
    return {
        "groups": {key: dict(value) for key, value in sorted(groups.items())},
        "distances": {
            key: {
                "observations": len(values),
                "minimum": min(values),
                "mean": math.fsum(values) / len(values),
                "maximum": max(values),
            }
            for key, values in sorted(distances.items())
        },
        "training_ready": False,
        "accuracy_established": False,
        "complete_rally_references": {"accepted": 0, "required": 2},
    }


def private_output(workspace, output):
    cache, output = Path(workspace).resolve() / ".cache", Path(output).resolve()
    if output == cache or not output.is_relative_to(cache):
        raise ValueError("New outputs must remain in the real workspace private cache")
    return output


def budget(folder, extra=0):
    if (
        sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) + extra
        > PROTOCOL["limits"]["output_bytes"]
    ):
        raise ValueError("Correspondence output budget exceeded")


def audit_claim(plan):
    # A second prospective directory cannot silently repeat this original audit.
    return (
        Path(plan["workspace"])
        / ".cache"
        / (PROTOCOL["name"] + "-" + PROTOCOL["completion_sha256"] + "-start.json")
    )


def total_budget(plan, prospective_path, output, extra=0):
    files = {Path(prospective_path).resolve(), audit_claim(plan).resolve()}
    files.update(p.resolve() for p in output.rglob("*") if p.is_file())
    if (
        sum(p.stat().st_size for p in files if p.is_file()) + extra
        > PROTOCOL["limits"]["output_bytes"]
    ):
        raise ValueError("Cumulative correspondence output budget exceeded")


def freeze(workspace, prepared, native, protocol, granted_at, deadline, output):
    check_deadline(granted_at, deadline)
    if read_json(protocol) != PROTOCOL:
        raise ValueError("Changed fixed correspondence protocol")
    output = private_output(workspace, output)
    if any(output.is_relative_to(Path(p).resolve()) for p in (prepared, native)):
        raise ValueError("Cannot write prospective files inside original inputs")
    output.mkdir(exist_ok=False)
    code = code_seals()
    observations = load_inputs(prepared, native)
    record = {
        "protocol": PROTOCOL,
        "code": code,
        "python": platform.python_version(),
        "workspace": str(Path(workspace).resolve()),
        "prepared": str(Path(prepared).resolve()),
        "native": str(Path(native).resolve()),
        "granted_at": granted_at,
        "deadline": deadline,
        "denominator": {
            "clips": len(observations),
            "references": sum(len(o[3]) for o in observations),
        },
        "audit_executed": False,
    }
    if code_seals() != code:
        raise ValueError("Consumer changed during freeze")
    check_deadline(granted_at, deadline)
    publish(output / "prospective.json", record)
    budget(output)
    return {
        "prospective_sha256": digest(output / "prospective.json"),
        "denominator": record["denominator"],
        "audit_executed": False,
    }


def prospective(path, expected_hash, *, clock):
    path = Path(path).resolve()
    if digest(path) != expected_hash:
        raise ValueError("Changed prospective consumer freeze")
    value = read_json(path)
    if (
        value["code"] != code_seals()
        or value["protocol"] != PROTOCOL
        or value["python"] != platform.python_version()
    ):
        raise ValueError("Changed correspondence consumer/protocol/runtime")
    if clock:
        check_deadline(value["granted_at"], value["deadline"])
    return value


def audit(prospective_path, prospective_sha256, output):
    plan = prospective(prospective_path, prospective_sha256, clock=True)
    output = private_output(plan["workspace"], output)
    if output.is_relative_to(Path(plan["prepared"])) or output.is_relative_to(
        Path(plan["native"])
    ):
        raise ValueError("Cannot write inside original inputs")
    claim = audit_claim(plan)
    publish(claim, {"prospective_sha256": prospective_sha256, "output": str(output)})
    output.mkdir(exist_ok=False)
    try:
        observations = load_inputs(plan["prepared"], plan["native"])
        diagnostics = []
        for _, video, result, references in observations:
            check_deadline(plan["granted_at"], plan["deadline"])
            diagnostics.extend(diagnose(r, result, video) for r in references)
        summary = aggregate(observations, diagnostics)
        raw = producer.encoded(diagnostics)
        total_budget(plan, prospective_path, output, len(raw))
        with (output / "diagnostics.json").open("xb") as stream:
            stream.write(raw)
        publish(output / "aggregate.json", summary)
        # Repeat integrity reads only; never a second geometry selection rule.
        load_inputs(plan["prepared"], plan["native"])
        prospective(prospective_path, prospective_sha256, clock=True)
        completion = {
            "prospective_sha256": prospective_sha256,
            "artifacts": producer.inventory(output),
            "summary": summary,
            "finished_at": time.time(),
            "claim": str(claim),
        }
        total_budget(plan, prospective_path, output, len(producer.encoded(completion)))
        publish(output / "completion.json", completion)
        return {
            "references": len(diagnostics),
            "weak_pairs": summary["groups"]["all"]["weak_pairs"],
            "accuracy_established": False,
        }
    except BaseException as error:
        publish(
            output / "failure.json",
            {
                "error_type": type(error).__name__,
                "time": time.time(),
                "original_audit_consumed": True,
            },
        )
        raise


def verify(prospective_path, prospective_sha256, output):
    plan = prospective(prospective_path, prospective_sha256, clock=False)
    output = private_output(plan["workspace"], output)
    completion = read_json(output / "completion.json")
    if completion["prospective_sha256"] != prospective_sha256:
        raise ValueError("Changed completed audit binding")
    claim = audit_claim(plan)
    if completion["claim"] != str(claim) or read_json(claim) != {
        "prospective_sha256": prospective_sha256,
        "output": str(output),
    }:
        raise ValueError("Changed original audit execution claim")
    if not plan["granted_at"] <= completion["finished_at"] < plan["deadline"]:
        raise ValueError("Audit did not finish within original scientific window")
    verify_inventory(
        output,
        completion["artifacts"]
        | {"completion.json": digest(output / "completion.json")},
    )
    observations = load_inputs(plan["prepared"], plan["native"])
    diagnostics = [
        diagnose(r, result, video)
        for _, video, result, refs in observations
        for r in refs
    ]
    if read_json(output / "diagnostics.json") != diagnostics:
        raise ValueError("Diagnostic does not reproduce from original observations")
    summary = aggregate(observations, diagnostics)
    if (
        read_json(output / "aggregate.json") != summary
        or completion["summary"] != summary
    ):
        raise ValueError("Aggregate does not preserve the original denominator")
    total_budget(plan, prospective_path, output)
    return {
        "verified_references": len(diagnostics),
        "weak_pairs": summary["groups"]["all"]["weak_pairs"],
        "accuracy_established": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("freeze")
    for name in ("workspace", "prepared", "native", "protocol", "output"):
        command.add_argument("--" + name, type=Path, required=True)
    command.add_argument("--granted-at", type=float, required=True)
    command.add_argument("--deadline", type=float, required=True)
    for name in ("audit", "verify"):
        command = sub.add_parser(name)
        command.add_argument(
            "--prospective", dest="prospective_path", type=Path, required=True
        )
        command.add_argument("--prospective-sha256", required=True)
        command.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args(argv))
    name = args.pop("command")
    print(
        producer.encoded(
            {"freeze": freeze, "audit": audit, "verify": verify}[name](**args)
        ).decode(),
        end="",
    )
