"""Read-only census of sealed scene evidence; no media, models or label writes."""

from __future__ import annotations

import stat
from collections import Counter, defaultdict
from pathlib import Path

from . import shuttle_scene_preparation as preparation
from . import shuttle_scene_review as review

require = preparation.require
encode = preparation.encode
decode = preparation.decode
digest = preparation.digest
ELIGIBILITY = preparation.ELIGIBILITY
MAX_INPUT_BYTES = 128 * 1024**2
CONSUMERS = (
    "backend/badminton/shuttle_context_audit.py",
    "backend/badminton/shuttle_scene_preparation.py",
    "backend/badminton/shuttle_scene_review.py",
    "backend/badminton/shuttle_scene_support.py",
    "scripts/audit_shuttle_scene_support.py",
    "tests/test_shuttle_scene_support.py",
    "tests/test_shuttle_scene_review.py",
)
BUCKETS = (
    "live_same_camera",
    "live_edit",
    "replay",
    "non_play",
    "unknown",
    "conflict",
    "unavailable",
)


def counts(values, keys):
    found = Counter(values)
    require(not set(found) - set(keys), "Unaccounted census category")
    return {key: found[key] for key in keys}


def category(row, start):
    if row["status"] != "independent_agreement":
        return row["status"]
    if row["scene"] in ("replay", "non_play"):
        return row["scene"]
    require(row["scene"] == "live", "Unknown scene cannot supply support")
    expected = "view_start" if row["frame"] == start else "same"
    return "live_same_camera" if row["transition"] == expected else "live_edit"


def census(gallery, plan, protocol, lane_a, lane_b, original, cases, cameras):
    """Reproduce original comparison, then count full views without inferring labels."""
    schedule = review.prepare_schedule(gallery, plan, protocol)
    reproduced = review.compare_lanes(schedule, lane_a, lane_b)
    require(reproduced == original, "Original comparison does not reproduce exactly")
    views = [g["view"] for g in gallery["galleries"]]
    require(len(cameras) == len(views), "Missing original camera metadata")
    grouped, unique, sheet_members = defaultdict(list), defaultdict(list), {}
    batch_members = defaultdict(set)
    attempts = {
        lane["lane"]: {r["batch_index"]: r for r in lane["results"]}
        for lane in (lane_a, lane_b)
    }
    for batch in schedule:
        for sheet in batch["images"]:
            for member in sheet["members"]:
                key = (batch["view_index"], member["frame"])
                identity = (sheet["path"], sheet["sha256"])
                require(
                    key not in sheet_members or sheet_members[key] == identity,
                    "Original sheet membership changed",
                )
                sheet_members[key] = identity
                batch_members[key].add(batch["index"])
    ledger = []
    for row in original["records"]:
        view = views[row["view_index"]]
        require(row["source_id"] == view["video_id"], "Occurrence source mismatch")
        clock = gallery["source_clocks"][row["source_id"]][row["frame"]]
        require(
            row["pts"] == clock["pts"] and row["time_base"] == clock["time_base"],
            "Occurrence native clock mismatch",
        )
        bucket = category(row, view["start_frame"])
        item = {
            "view_index": view["index"],
            "source_id": row["source_id"],
            "frame": row["frame"],
            "pts": row["pts"],
            "time_base": row["time_base"],
            "status": row["status"],
            "scene": row["scene"],
            "transition": row["transition"],
            "category": bucket,
            "sheet_path": sheet_members[(view["index"], row["frame"])][0],
            "original_batch_indices": sorted(
                batch_members[(view["index"], row["frame"])]
            ),
            "original_attempts": {
                lane: [
                    {
                        "batch_index": index,
                        "status": results[index]["status"]
                        if index in results
                        else "unattempted",
                        "session_id": results[index]["session_id"]
                        if index in results
                        else None,
                    }
                    for index in sorted(batch_members[(view["index"], row["frame"])])
                ]
                for lane, results in attempts.items()
            },
            "partition": max(
                i
                for i, start in enumerate(view["partition_starts"])
                if start <= row["frame"]
            ),
            "original_lanes": {
                name: {
                    "status": row[key]["status"],
                    "cross_view_conflict": row[key]["cross_view_conflict"],
                    "session_ids": sorted(
                        {r["session_id"] for r in row[key]["readings"]}
                    ),
                }
                for name, key in zip(review.LANES, ("original_a", "original_b"))
            },
        }
        ledger.append(item)
        grouped[view["index"]].append(item)
        unique[(item["source_id"], item["frame"])].append(item)
    view_ledger = []
    for view, camera_ranges in zip(views, cameras):
        rows = grouped[view["index"]]
        require(
            [r["frame"] for r in rows]
            == list(range(view["start_frame"], view["end_frame"])),
            "Missing, duplicate or unordered original occurrence",
        )
        require(type(camera_ranges) is list and camera_ranges, "Missing camera ranges")
        for camera in camera_ranges:
            preparation.integer(camera["start_frame"])
            preparation.integer(camera["end_frame"], camera["start_frame"] + 1)
        boundaries = sorted(
            {
                camera[key]
                for camera in camera_ranges
                for key in ("start_frame", "end_frame")
                if view["start_frame"] < camera[key] < view["end_frame"]
            }
        )
        unambiguous_camera = all(
            sum(
                c["start_frame"] <= row["frame"] < c["end_frame"] for c in camera_ranges
            )
            == 1
            for row in rows
        )
        known = all(r["status"] == "independent_agreement" for r in rows)
        live = all(r["category"] == "live_same_camera" for r in rows)
        stable = live and not boundaries and unambiguous_camera
        view_ledger.append(
            {
                **view,
                "categories": counts((r["category"] for r in rows), BUCKETS),
                "known_scene_complete": known,
                "live_stable_camera_complete": stable,
                "known_mixed_or_excluded_complete": known and not stable,
                "declared_camera_boundaries": boundaries,
                "camera_membership_unambiguous": unambiguous_camera,
                "supported_edit_occurrences": sum(
                    r["transition"] == "changed"
                    and r["status"] == "independent_agreement"
                    for r in rows
                ),
            }
        )
    case_ids, case_ledger = set(), []
    for case in cases:
        require(set(case) == {"id", "video_id", "frame"}, "Unexpected case fields")
        require(case["id"] not in case_ids, "Duplicate case identity")
        case_ids.add(case["id"])
        members = [v for v in view_ledger if case["id"] in v["case_ids"]]
        require(len(members) == 1, "Missing or ambiguous case membership")
        view = members[0]
        require(
            case["video_id"] == view["video_id"]
            and type(case["frame"]) is int
            and view["start_frame"] <= case["frame"] < view["end_frame"],
            "Case source/frame outside original half-open view",
        )
        center = next(r for r in grouped[view["index"]] if r["frame"] == case["frame"])
        case_ledger.append(
            {
                **case,
                "view_index": view["index"],
                "center_category": center["category"],
                "center_known_agreement": center["status"] == "independent_agreement",
                "whole_view_known_scene_complete": view["known_scene_complete"],
                "whole_view_live_stable_camera_complete": view[
                    "live_stable_camera_complete"
                ],
            }
        )
    require(
        case_ids == {c for v in views for c in v["case_ids"]}
        and len(cases) == protocol["denominators"]["cases"],
        "Original case denominator changed",
    )
    gaps = [r for r in ledger if r["status"] != "independent_agreement"]
    gap_keys = {(r["view_index"], r["frame"]) for r in gaps}
    batches = [
        b
        for b in schedule
        if any(
            (b["view_index"], m["frame"]) in gap_keys
            for s in b["images"]
            for m in s["members"]
        )
    ]
    gap_sheets = {r["sheet_path"] for r in gaps}
    selected_images = {s["path"]: s for b in batches for s in b["images"]}
    unique_status = Counter()
    for rows in unique.values():
        supported = [r for r in rows if r["status"] == "independent_agreement"]
        if len(supported) == len(rows):
            scenes = {r["scene"] for r in rows}
            transitions = {
                r["transition"] for r in rows if r["transition"] != "view_start"
            }
            require(
                len(scenes) == 1 and len(transitions) <= 1,
                "Cross-view disagreement escaped original comparison",
            )
            unique_status["all_occurrences_known_agreement"] += 1
        elif supported:
            unique_status["mixed_supported_and_unresolved"] += 1
        else:
            unique_status["no_supported_occurrence"] += 1
    partition_count = sum(len(v["partition_starts"]) for v in views)
    stable_partitions = 0
    for view in views:
        starts = view["partition_starts"]
        for start, end in zip(starts, [*starts[1:], view["end_frame"]]):
            rows = [r for r in grouped[view["index"]] if start <= r["frame"] < end]
            # A declared partition start is not a reviewed edit or a new view start.
            stable_partitions += bool(rows) and all(
                r["category"] == "live_same_camera" for r in rows
            )
    public = {
        "schema_version": 1,
        "original_comparison": original["aggregate"],
        "denominators": {
            **protocol["denominators"],
            "unique_source_frames": len(unique),
            "declared_partitions": partition_count,
        },
        "occurrence_categories": counts((r["category"] for r in ledger), BUCKETS),
        "unique_frame_support": {
            k: unique_status[k]
            for k in (
                "all_occurrences_known_agreement",
                "mixed_supported_and_unresolved",
                "no_supported_occurrence",
            )
        },
        "views": {
            "known_scene_complete": sum(v["known_scene_complete"] for v in view_ledger),
            "live_stable_camera_complete": sum(
                v["live_stable_camera_complete"] for v in view_ledger
            ),
            "known_mixed_or_excluded_complete": sum(
                v["known_mixed_or_excluded_complete"] for v in view_ledger
            ),
            "incomplete_scene_evidence": sum(
                not v["known_scene_complete"] for v in view_ledger
            ),
        },
        "cases": {
            "center_known_agreement": sum(
                c["center_known_agreement"] for c in case_ledger
            ),
            "whole_view_known_scene_complete": sum(
                c["whole_view_known_scene_complete"] for c in case_ledger
            ),
            "whole_view_live_stable_camera_complete": sum(
                c["whole_view_live_stable_camera_complete"] for c in case_ledger
            ),
            "center_categories": counts(
                (c["center_category"] for c in case_ledger), BUCKETS
            ),
        },
        "partitions": {
            "declared": partition_count,
            "all_cells_live_same_camera_agreement": stable_partitions,
        },
        "review_gaps": {
            "frame_occurrences": len(gaps),
            "unique_source_frames": len({(r["source_id"], r["frame"]) for r in gaps}),
            "sheets": len(gap_sheets),
            "original_batches_touching_gaps": len(batches),
        },
        "hypothetical_original_batch_cost": {
            "one_pass_sessions": len(batches),
            "one_pass_image_bytes": sum(
                s["bytes"] for b in batches for s in b["images"]
            ),
            "two_fresh_passes_sessions": 2 * len(batches),
            "two_fresh_passes_image_bytes": 2
            * sum(s["bytes"] for b in batches for s in b["images"]),
            "unique_sheets_with_original_batch_context": len(selected_images),
            "unique_sheet_bytes_with_original_batch_context": sum(
                s["bytes"] for s in selected_images.values()
            ),
            "authorized_schedule": False,
        },
        "historical_original_sessions": {
            lane["lane"]: {
                k: lane["aggregate"][k]
                for k in (
                    "expected_sessions",
                    "completed_sessions",
                    "failed_sessions",
                    "missing_sessions",
                )
            }
            for lane in (lane_a, lane_b)
        },
        "overlapping_evidence_flags": {
            "either_lane_missing": sum(
                any(
                    row[k]["status"] == "unavailable"
                    for k in ("original_a", "original_b")
                )
                for row in original["records"]
            ),
            "either_lane_overlap_conflict": sum(
                any(
                    row[k]["status"] == "overlap_conflict"
                    for k in ("original_a", "original_b")
                )
                for row in original["records"]
            ),
            "either_lane_cross_view_conflict": sum(
                any(row[k]["cross_view_conflict"] for k in ("original_a", "original_b"))
                for row in original["records"]
            ),
            "either_lane_unknown_scene": sum(
                any(row[k]["scene"] == "unknown" for k in ("original_a", "original_b"))
                for row in original["records"]
            ),
            "either_lane_unknown_transition": sum(
                any(
                    row[k]["transition"] == "unknown"
                    for k in ("original_a", "original_b")
                )
                for row in original["records"]
            ),
            "both_lanes_same_known_scene_but_unknown_transition": sum(
                row["original_a"]["scene"] == row["original_b"]["scene"] != "unknown"
                and any(
                    row[k]["transition"] == "unknown"
                    for k in ("original_a", "original_b")
                )
                for row in original["records"]
            ),
        },
        "source_groups": [
            {
                "source_group": digest(source.encode())[:16],
                "frame_occurrences": sum(r["source_id"] == source for r in ledger),
                "unique_source_frames": len(
                    {r["frame"] for r in ledger if r["source_id"] == source}
                ),
                "views": sum(v["video_id"] == source for v in view_ledger),
                "cases": sum(c["video_id"] == source for c in case_ledger),
                "known_scene_complete_views": sum(
                    v["video_id"] == source and v["known_scene_complete"]
                    for v in view_ledger
                ),
                "live_stable_camera_complete_views": sum(
                    v["video_id"] == source and v["live_stable_camera_complete"]
                    for v in view_ledger
                ),
                "occurrence_categories": counts(
                    (r["category"] for r in ledger if r["source_id"] == source), BUCKETS
                ),
            }
            for source in sorted({r["source_id"] for r in ledger})
        ],
        "eligibility": dict(ELIGIBILITY),
        "complete_independent_rally_references": "0/2",
        "full_match_accuracy_established": False,
        "source_judgments_created": 0,
        "image_bytes_read": 0,
    }
    require(
        sum(public["occurrence_categories"].values()) == len(ledger),
        "Occurrence census lost rows",
    )
    require(
        sum(public["unique_frame_support"].values()) == len(unique),
        "Unique census lost rows",
    )
    private = {
        "occurrences": ledger,
        "views": view_ledger,
        "cases": case_ledger,
        "gap_batch_indices": [b["index"] for b in batches],
    }
    return public, private


class EvidenceReader:
    """Frozen metadata/opaque evidence only; image and model bytes are forbidden."""

    def __init__(self, root, bindings, inventory_sha256):
        require(
            type(bindings) is dict and set(bindings) == {"inputs", "absent", "roots"},
            "Invalid input bindings",
        )
        self.root = Path(root).absolute()
        self.inputs, self.absent = bindings["inputs"], bindings["absent"]
        self.roots = bindings["roots"]
        require(
            set(self.roots) == {"original", "preparation", "historical"},
            "Missing historical namespaces",
        )
        for name in self.roots.values():
            path = preparation.safe_path(self.root, name, must_exist=False)
            require(
                path.is_dir() and path != self.root,
                "Ordinary historical namespace required",
            )
        commitment = {
            "inputs": {
                k: {f: v[f] for f in ("sha256", "mode")} for k, v in self.inputs.items()
            },
            "absent": self.absent,
            "roots": self.roots,
        }
        require(
            digest(encode(commitment)) == inventory_sha256,
            "Frozen evidence inventory changed",
        )
        self.paths = {}
        for key, value in self.inputs.items():
            require(
                set(value) == {"path", "sha256", "mode"}, "Unexpected input descriptor"
            )
            path = preparation.safe_path(self.root, value["path"])
            require(
                path.suffix in (".json", ".jsonl", ".txt", ".py", ".log"),
                "Only declared metadata/text evidence may be read",
            )
            require(
                value["mode"] in ("json", "events", "opaque"), "Invalid evidence mode"
            )
            require(path not in self.paths.values(), "Duplicate input file identity")
            self.paths[key] = path
        require(
            type(self.absent) is list and len(set(self.absent)) == len(self.absent),
            "Invalid absence inventory",
        )
        self.verify_unchanged()

    def verify_unchanged(self):
        for key, path in self.paths.items():
            preparation.safe_path(self.root, self.inputs[key]["path"])
            require(
                path.stat().st_size <= MAX_INPUT_BYTES
                and preparation.file_hash(path) == self.inputs[key]["sha256"],
                "Frozen evidence bytes changed",
            )
        for name in self.absent:
            path = preparation.safe_path(self.root, name, must_exist=False)
            require(not path.exists(), "Historically absent evidence appeared")
        original = self.root / self.roots["original"]
        expected = {
            p.relative_to(original).as_posix()
            for p in self.paths.values()
            if p.is_relative_to(original)
        }
        require(
            tree_files(original) == expected,
            "Historical original evidence tree changed",
        )

    def key_at(self, namespace, relative):
        path = preparation.safe_path(self.root, self.roots[namespace] + "/" + relative)
        keys = [key for key, candidate in self.paths.items() if candidate == path]
        require(len(keys) == 1, "Historical evidence missing from frozen inventory")
        return keys[0]

    def read_at(self, namespace, relative):
        return self.read(self.key_at(namespace, relative))

    def read(self, key):
        descriptor = self.inputs[key]
        require(
            descriptor["mode"] == "json",
            "Only declared scene/metadata JSON may be decoded",
        )
        path = preparation.safe_path(self.root, descriptor["path"])
        raw = path.read_bytes()
        require(
            len(raw) <= MAX_INPUT_BYTES and digest(raw) == descriptor["sha256"],
            "Bound metadata changed",
        )
        return decode(raw)

    def events(self, key):
        descriptor = self.inputs[key]
        require(
            descriptor["mode"] == "events",
            "Only declared execution metadata may be projected",
        )
        raw = self.paths[key].read_bytes()
        require(
            len(raw) <= MAX_INPUT_BYTES and digest(raw) == descriptor["sha256"],
            "Execution metadata changed",
        )
        threads, completed, tools, unexpected = [], 0, [], set()
        for line in raw.splitlines():
            event = decode(line)
            require(type(event) is dict, "Invalid execution event")
            if event.get("type") not in (
                "thread.started",
                "turn.started",
                "item.started",
                "item.updated",
                "item.completed",
                "turn.completed",
            ):
                unexpected.add(str(event.get("type")))
            if event.get("type") == "thread.started":
                review.text(event["thread_id"], 300)
                threads.append(event["thread_id"])
            completed += event.get("type") == "turn.completed"
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") not in (
                "reasoning",
                "agent_message",
            ):
                tools.append(item.get("type"))
        return {
            "threads": threads,
            "completed_turns": completed,
            "tools": tools,
            "unexpected_types": sorted(unexpected),
        }


def tree_files(root):
    """Enumerate ordinary metadata paths without following linked directories."""
    root = Path(root)
    pending, result = [root], set()
    while pending:
        path = pending.pop()
        info = path.lstat()
        require(
            not stat.S_ISLNK(info.st_mode)
            and not getattr(info, "st_file_attributes", 0) & 1024,
            "Linked evidence tree is unsupported",
        )
        if stat.S_ISDIR(info.st_mode):
            pending.extend(path.iterdir())
        else:
            require(stat.S_ISREG(info.st_mode), "Ordinary evidence file required")
            result.add(path.relative_to(root).as_posix())
    return result


def verify_consumers(source, protocol):
    require(
        set(protocol["consumer_sha256"]) == set(CONSUMERS),
        "Consumer membership changed",
    )
    for name, expected in protocol["consumer_sha256"].items():
        require(
            preparation.file_hash(preparation.safe_path(source, name)) == expected,
            "Tested consumer changed",
        )


def verify_public_inventory(protocol, bindings):
    require(
        protocol["evidence_sha256"]
        == {
            k: {f: v[f] for f in ("sha256", "mode")}
            for k, v in bindings["inputs"].items()
        }
        and protocol["absence_commitment_sha256"] == digest(encode(bindings["absent"]))
        and protocol["namespace_commitment_sha256"]
        == digest(encode(bindings["roots"])),
        "Public prospective evidence commitment changed",
    )


def session_history(reader, schedule, lanes, *, attempts=None):
    """Audit every attempted identity, including failed and unsealed adjudication."""
    original_root = reader.root / reader.roots["original"]
    by_batch = {b["index"]: b for b in schedule}
    accepted = {
        (lane["lane"], r["batch_index"]): r for lane in lanes for r in lane["results"]
    }
    sessions, threads, memberships, adjudication = set(), set(), set(), []
    totals = {lane: Counter() for lane in (*review.LANES, review.ADJUDICATION)}
    for key, path in sorted(reader.paths.items()):
        if (
            not path.is_relative_to(original_root / "sessions")
            or path.name != "reservation.json"
        ):
            continue
        relative = path.relative_to(original_root).as_posix()
        parts = relative.split("/")
        require(
            len(parts) == 4 and parts[0] == "sessions", "Invalid original session path"
        )
        reservation = reader.read(key)
        lane, index = reservation["lane"], reservation["batch_index"]
        require(
            lane in totals and type(index) is int and index in by_batch,
            "Unexpected historical session membership",
        )
        require(
            parts[1] == lane and parts[2] == f"{index:03d}",
            "Historical session path mismatch",
        )
        member = (lane, index)
        require(
            member not in memberships and reservation["session_id"] not in sessions,
            "Duplicate global assessor identity",
        )
        memberships.add(member)
        sessions.add(reservation["session_id"])
        batch = by_batch[index]
        images = [
            {k: s[k] for k in ("path", "sha256", "bytes")} for s in batch["images"]
        ]
        require(
            reservation["images"] == images
            and reservation["image_bytes"] == sum(s["bytes"] for s in images)
            and reservation["replacement_allowed"] is False,
            "Historical payload reservation changed",
        )
        folder = "/".join(parts[:-1])
        result = reader.read_at("original", folder + "/result.json")
        require(
            result["session_id"] == reservation["session_id"]
            and result["batch_index"] == index,
            "Historical result identity changed",
        )
        require(
            result["status"] in ("completed", "failed"), "Nonterminal historical result"
        )
        events = reader.events(reader.key_at("original", folder + "/events.jsonl"))
        require(
            len(events["threads"]) <= 1 and not threads.intersection(events["threads"]),
            "Duplicate global assessor thread",
        )
        threads.update(events["threads"])
        finish = reader.read_at("original", folder + "/finish.json")
        if result["status"] == "completed":
            require(
                events["threads"] == [result["thread_id"]]
                and events["completed_turns"] == 1
                and not events["tools"]
                and not events["unexpected_types"]
                and finish["exit_code"] == 0
                and finish["all_observed_processes_absent"]
                and finish["stdin_error"] is None
                and not finish["bounded_stop"]
                and finish["pipes_reached_eof"]
                and not finish["collection_errors"]
                and not finish["stdout"]["truncated"]
                and not finish["stderr"]["truncated"],
                "Accepted source session lacks clean independent terminal evidence",
            )
            require(
                reader.read_at("original", folder + "/original-final.json")
                == result["document"],
                "Accepted source response differs from sealed reading",
            )
        else:
            require(
                result["document"] is None, "Failed session supplied scientific labels"
            )
        if lane in review.LANES:
            require(
                member in accepted and result == accepted[member],
                "Sealed session result differs from original lane",
            )
        else:
            require(
                result["status"] == "failed",
                "Unexpected successful unsealed adjudication",
            )
            adjudication.append(result)
        totals[lane][result["status"]] += 1
        totals[lane]["reserved_image_bytes"] += reservation["image_bytes"]
        totals[lane]["unresolved_terminal_metadata"] += not (
            finish["all_observed_processes_absent"] and finish["pipes_reached_eof"]
        )
        if attempts is not None:
            attempts[member] = {
                "batch_index": index,
                "status": result["status"],
                "session_id": reservation["session_id"],
                "thread_ids": events["threads"],
                "terminal_metadata_resolved": bool(
                    finish["all_observed_processes_absent"]
                    and finish["pipes_reached_eof"]
                ),
            }
    require(set(accepted) <= memberships, "Missing sealed original session evidence")
    partial = review.assemble_lane(
        schedule,
        sorted(adjudication, key=lambda r: r["batch_index"]),
        review.ADJUDICATION,
    )
    return {
        "lanes": {
            lane: {
                "successful": c["completed"],
                "failed": c["failed"],
                "unattempted_schedule_slots": len(schedule)
                - c["completed"]
                - c["failed"],
                "reserved_image_bytes": c["reserved_image_bytes"],
                "unresolved_terminal_metadata": c["unresolved_terminal_metadata"],
            }
            for lane, c in totals.items()
        },
        "global_sessions": len(sessions),
        "global_threads": len(threads),
        "adjudication_terminal_seal_available": False,
        "partial_adjudication_successful_sessions": partial["aggregate"][
            "completed_sessions"
        ],
    }


def audit_bound(reader, protocol):
    """Verify the frozen historical chain before consuming sealed scene JSON."""
    require(
        {
            reader.roots["original"] + "/" + name
            for name in (
                "adjudication/terminal.json",
                "audit/terminal.json",
                "comparison-final.json",
                "adjudication.json",
            )
        }
        <= set(reader.absent),
        "Incomplete adjudication must remain explicitly absent",
    )
    old = reader.read("review_protocol")
    prep = reader.read("preparation_protocol")
    for name, role in (
        ("familiar-scene-inventory", "inventory"),
        ("context-audit-diagnostics", "diagnostics"),
    ):
        require(
            prep["artifacts"][name] == reader.inputs[role]["sha256"],
            "Historical source metadata binding changed",
        )
    gallery, plan = reader.read("gallery"), reader.read("plan")
    context, prep_context = (
        reader.read("review_context"),
        reader.read("preparation_context"),
    )
    require(
        old["eligibility"] == prep["eligibility"] == ELIGIBILITY,
        "Historical eligibility changed",
    )
    require(
        old["denominators"] == protocol["denominators"], "Frozen denominator changed"
    )
    require(
        [
            {
                k: s[k]
                for k in ("id", "sha256", "frame_count", "rotation", "display_size")
            }
            for s in old["sources"]
        ]
        == [
            {
                k: s[k]
                for k in ("id", "sha256", "frame_count", "rotation", "display_size")
            }
            for s in prep["sources"]
        ],
        "Historical source identity/clock conventions changed",
    )
    require(
        context["protocol_sha256"] == reader.inputs["review_protocol"]["sha256"],
        "Historical review protocol changed",
    )
    require(
        prep_context["protocol_sha256"]
        == reader.inputs["preparation_protocol"]["sha256"],
        "Historical preparation protocol changed",
    )
    require(
        context["source_commit"] == protocol["historical_source_commit"],
        "Historical consumer revision changed",
    )
    for name, expected in context["consumers"]["files"].items():
        key = reader.key_at("historical", name)
        require(
            reader.inputs[key]["sha256"] == expected,
            "Historical consumer bytes changed",
        )
    for name in (
        "backend/badminton/shuttle_scene_review.py",
        "backend/badminton/shuttle_scene_preparation.py",
        "backend/badminton/shuttle_context_audit.py",
    ):
        require(
            context["consumers"]["files"][name] == protocol["consumer_sha256"][name],
            "Original comparison engine changed",
        )
    artifact_roles = {
        "scene-gallery": "gallery",
        "scene-plan": "plan",
        "scene-aggregate": "preparation_aggregate",
        "scene-context": "preparation_context",
        "scene-audit": "preparation_audit",
    }
    for name, role in artifact_roles.items():
        require(
            old["artifacts"][name] == reader.inputs[role]["sha256"],
            "Historical prepared input changed",
        )
    inventory, diagnostics = reader.read("inventory"), reader.read("diagnostics")
    views, cases = preparation.inventory(inventory, diagnostics, prep)
    require(
        [g["view"] for g in gallery["galleries"]] == views,
        "Historical source/view partitions changed",
    )
    schedule = review.prepare_schedule(gallery, plan, old)
    require(
        digest(encode(schedule)) == context["schedule_sha256"],
        "Historical schedule changed",
    )
    prep_audit = reader.read("preparation_audit")
    prep_terminal = reader.read("preparation_terminal")
    require(
        prep_audit["status"] == prep_terminal["summary"]["status"] == "audited"
        and prep_audit == prep_terminal["summary"]
        and prep_audit["gallery_sha256"]
        == prep_terminal["summary"]["gallery_sha256"]
        == reader.inputs["gallery"]["sha256"],
        "Historical preparation terminal evidence changed",
    )
    for key, role in (
        ("plan_sha256", "plan"),
        ("aggregate_sha256", "preparation_aggregate"),
    ):
        require(
            prep_audit[key] == reader.inputs[role]["sha256"],
            "Historical audited output changed",
        )
    terminal, seal = reader.read("original_terminal"), reader.read("original_seal")
    require(
        terminal["summary"]["status"] == "originals_sealed"
        and terminal["summary"]["seal_sha256"]
        == reader.inputs["original_seal"]["sha256"],
        "Historical original terminal seal changed",
    )
    original_root = reader.root / reader.roots["original"]
    sealed_files = {}
    for path in reader.paths.values():
        if path.is_relative_to(original_root / "sessions"):
            relative = path.relative_to(original_root).as_posix()
            if relative.split("/")[1] in review.LANES:
                key = reader.key_at("original", relative)
                sealed_files[relative] = reader.inputs[key]["sha256"]
    require(
        sealed_files == seal["sessions"], "Original session seal membership changed"
    )
    lanes = [reader.read(role) for role in ("lane_a", "lane_b")]
    for lane, role in zip(lanes, ("lane_a", "lane_b")):
        require(
            seal["lanes"][lane["lane"]] == reader.inputs[role]["sha256"],
            "Original lane seal changed",
        )
    require(
        seal["comparison_sha256"] == reader.inputs["comparison"]["sha256"],
        "Original comparison seal changed",
    )
    original = reader.read("comparison")
    require(
        terminal["summary"]["aggregate"] == original["aggregate"],
        "Original terminal comparison differs",
    )
    attempts = {}
    history = session_history(reader, schedule, lanes, attempts=attempts)
    public, private = census(
        gallery,
        plan,
        old,
        *lanes,
        original,
        cases,
        [v["camera_metadata"] for v in diagnostics["methods"]["control"]["views"]],
    )
    public["historical_execution"] = history
    for occurrence in private["occurrences"]:
        occurrence["adjudication_attempts"] = [
            attempts.get(
                (review.ADJUDICATION, index),
                {
                    "batch_index": index,
                    "status": "unattempted",
                    "session_id": None,
                    "thread_ids": [],
                    "terminal_metadata_resolved": None,
                },
            )
            for index in occurrence["original_batch_indices"]
        ]
    require(
        original["aggregate"]["status_counts"]
        == protocol["expected_original_status_counts"],
        "Preserved original result changed",
    )
    require(
        history["lanes"] == protocol["expected_historical_lanes"],
        "Preserved historical execution changed",
    )
    reader.verify_unchanged()
    return public, private
