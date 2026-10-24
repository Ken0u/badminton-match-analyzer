"""Metadata census of validated source labels; never a scientific adjudicator.

Every observation remains in the private ledger. Aggregate groups describe
repetition and contradiction, not distinct physical contacts or player truth.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
from collections import Counter, defaultdict

LANES = ("independent_a", "independent_b", "adjudication")
SCENES = ("live", "replay", "non_play", "unknown")
CONTACTS = ("none_observed", "observed", "possible", "unknown")
KINDS = ("serve", "shot", "rally_end", "unresolved_contact")
FAMILIES = ("clear", "lift", "net", "drop", "smash", "drive", "other", "unknown")
SIDES = ("forehand", "backhand", "unknown")
EVIDENCE = ("ground_contact", "net_fault", "fault", "stopped_play", "unknown")
SIGNATURE = ("kind", "interval", "actor_id", "family", "side", "evidence")


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def seal(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def native_set(frames):
    frames = list(frames)
    if (
        not frames
        or any(type(n) is not int or n < 0 for n in frames)
        or frames != sorted(set(frames))
    ):
        raise ValueError("Ordered unique exact native frame integers required")
    return set(frames)


def interval_frames(interval, allowed):
    if (
        not isinstance(interval, list)
        or len(interval) != 2
        or any(type(n) is not int for n in interval)
        or interval[0] > interval[1]
        or interval[0] not in allowed
        or interval[1] not in allowed
        or interval[1] - interval[0] + 1 > len(allowed)
    ):
        raise ValueError("Inclusive interval escapes native membership")
    selected = set(range(interval[0], interval[1] + 1))
    if not selected <= allowed:
        raise ValueError("Inclusive interval escapes native membership")
    return selected


def _counts(values, categories):
    counts = Counter(values)
    if set(counts) - set(categories):
        raise ValueError("Unexpected scientific category")
    return {category: counts[category] for category in categories}


def census_lane(documents, *, native_frames):
    """Retain all variants; unique-frame category counts may overlap."""
    allowed = native_set(native_frames)
    states, actors, groups, keys = (defaultdict(list) for _ in range(4))
    gaps, censored, context, unsupported = (set() for _ in range(4))
    ledger = {"documents": [], "frames": [], "events": [], "actors": []}
    memberships = 0
    for index, (doc, _receipt) in enumerate(documents):
        inspected = [r["frame"] for r in doc["inspected_frames"]]
        selected = native_set(inspected)
        if (
            not selected <= allowed
            or [r["frame"] for r in doc["frame_states"]] != inspected
        ):
            raise ValueError(
                "Explicit native frame review required for every membership"
            )
        if (
            doc["scene"] not in SCENES
            or type(doc["coverage_complete"]) is not bool
            or any(type(doc[k]) is not bool for k in ("start_censored", "end_censored"))
        ):
            raise ValueError("Explicit context and censoring required")
        ledger["documents"].append(
            {
                "index": index,
                "document_sha256": seal(doc),
                **{
                    k: copy.deepcopy(doc[k])
                    for k in (
                        "scene",
                        "coverage_complete",
                        "start_censored",
                        "end_censored",
                        "unresolved_gaps",
                    )
                },
            }
        )
        memberships += len(selected)
        if doc["start_censored"] or doc["end_censored"]:
            censored.update(selected)
        if doc["scene"] != "live" or not doc["coverage_complete"]:
            context.update(selected)
        for gap in doc["unresolved_gaps"]:
            gaps.update(interval_frames(gap["interval"], selected))
        for ordinal, row in enumerate(doc["frame_states"]):
            if row["scene"] not in SCENES or row["contact_state"] not in CONTACTS:
                raise ValueError("Unexpected scientific category")
            if not isinstance(row["camera_view"], str) or not row["camera_view"]:
                raise ValueError("Explicit camera view required")
            states[row["frame"]].append(row)
            ledger["frames"].append(
                {"document": index, "row": ordinal, "state": copy.deepcopy(row)}
            )
        local_actors = {}
        for ordinal, actor in enumerate(doc["actors"]):
            if (
                not isinstance(actor["actor_id"], str)
                or not actor["actor_id"]
                or actor["actor_id"] in local_actors
                or type(actor["identity_supported"]) is not bool
            ):
                raise ValueError("Distinct local actor definitions required")
            local_actors[actor["actor_id"]] = actor
            actors[actor["actor_id"]].append(actor)
            ledger["actors"].append(
                {"document": index, "row": ordinal, "definition": copy.deepcopy(actor)}
            )
        for ordinal, event in enumerate(doc["events"]):
            region = interval_frames(event["interval"], selected)
            if event["kind"] not in KINDS:
                raise ValueError("Unexpected event kind")
            if event["kind"] in {"serve", "shot"}:
                if (
                    event.get("side") not in SIDES
                    or (event["kind"] == "shot" and event.get("family") not in FAMILIES)
                    or (event["kind"] == "serve" and event.get("family") is not None)
                ):
                    raise ValueError("Requested labels must retain explicit unknowns")
                if not local_actors.get(event.get("actor_id"), {}).get(
                    "identity_supported"
                ):
                    unsupported.update(region)
            if event["kind"] == "rally_end" and event.get("evidence") not in EVIDENCE:
                raise ValueError("Explicit terminal evidence required")
            signature = {k: event.get(k) for k in SIGNATURE}
            group = encoded(signature)
            key = event["kind"], tuple(event["interval"])
            groups[group].append((index, ordinal))
            keys[key].append(group)
            ledger["events"].append(
                {"document": index, "row": ordinal, "event": copy.deepcopy(event)}
            )

    def count_frames(predicate):
        return sum(
            any(predicate(row) for row in variants) for variants in states.values()
        )

    contact_keys = [k for k in keys if k[0] in {"serve", "shot"}]
    pairs = [
        (left, right)
        for left, right in itertools.combinations(sorted(contact_keys), 2)
        if max(left[1][0], right[1][0]) <= min(left[1][1], right[1][1])
    ]
    ledger["distinct_key_overlapping_contact_pairs"] = pairs
    ledger["signature_occurrences"] = [
        {"signature": json.loads(key), "occurrences": rows}
        for key, rows in sorted(groups.items())
    ]
    events = [row["event"] for row in ledger["events"]]
    contact_events = [e for e in events if e["kind"] in {"serve", "shot"}]
    summary = {
        "native_frame_denominator": len(allowed),
        "documents": len(documents),
        "inspected_memberships": memberships,
        "unique_inspected_frames": len(states),
        "uninspected_native_frames": len(allowed - set(states)),
        "repeated_frame_observation_excess": memberships - len(states),
        "conflicting_frame_variants": sum(
            len({encoded(r) for r in rows}) > 1 for rows in states.values()
        ),
        "contact_state_unique_frame_counts": {
            c: count_frames(lambda r: r["contact_state"] == c) for c in CONTACTS
        },
        "scene_unique_frame_counts": {
            c: count_frames(lambda r: r["scene"] == c) for c in SCENES
        },
        "unknown_camera_frames": count_frames(
            lambda r: r["camera_view"] in {"unknown", "unreviewed"}
        ),
        "unresolved_gap_frames": len(gaps),
        "censored_document_frames": len(censored),
        "nonlive_or_incomplete_document_frames": len(context),
        "event_occurrences": len(events),
        "event_kind_occurrences": _counts((e["kind"] for e in events), KINDS),
        "distinct_acceptance_signatures": len(groups),
        "signature_repeat_excess": sum(len(rows) - 1 for rows in groups.values()),
        "within_document_signature_repeat_excess": sum(
            len(rows) - len({i for i, _ in rows}) for rows in groups.values()
        ),
        "cross_document_signature_repeat_excess": sum(
            len({i for i, _ in rows}) - 1 for rows in groups.values()
        ),
        "conflicting_event_keys": sum(len(set(rows)) > 1 for rows in keys.values()),
        "distinct_contact_keys": len(contact_keys),
        "distinct_key_overlapping_contact_pairs": len(pairs),
        "actor_definition_occurrences": sum(len(rows) for rows in actors.values()),
        "actor_id_groups": len(actors),
        "conflicting_actor_definition_groups": sum(
            len({encoded(r) for r in rows}) > 1 for rows in actors.values()
        ),
        "unsupported_identity_contact_frames": len(unsupported),
        "unknown_contact_side_occurrences": sum(
            e["side"] == "unknown" for e in contact_events
        ),
        "shot_family_occurrences": _counts(
            (e["family"] for e in events if e["kind"] == "shot"), FAMILIES
        ),
        "contact_side_occurrences": _counts((e["side"] for e in contact_events), SIDES),
        "terminal_evidence_occurrences": _counts(
            (e["evidence"] for e in events if e["kind"] == "rally_end"), EVIDENCE
        ),
    }
    # Count support per original document, without a later actor definition
    # overwriting the one that accompanied a contact.
    summary["unsupported_identity_contact_occurrences"] = sum(
        row["event"]["kind"] in {"serve", "shot"}
        and not any(
            a["actor_id"] == row["event"].get("actor_id") and a["identity_supported"]
            for a in documents[row["document"]][0]["actors"]
        )
        for row in ledger["events"]
    )
    return summary, ledger


def diagnose_source(streams, *, native_frames, bounds, acceptance):
    """Call unchanged scientific acceptance independently of the census."""
    allowed = native_set(native_frames)
    if set(streams) != set(LANES):
        raise ValueError("Retain all three explicit stream slots")
    source_ids, images = set(), {}
    for lane, documents in streams.items():
        for doc, _ in documents:
            if doc["stage"] != "dense" or doc["stream"] != lane:
                raise ValueError("Source stream identity mismatch")
            source_ids.add(doc["source_id"])
            for row in doc["inspected_frames"]:
                n, sha = row["frame"], row["sha256"]
                if n not in allowed or (n in images and images[n] != sha):
                    raise ValueError("Original native image identity mismatch")
                images[n] = sha
    if len(source_ids) != 1:
        raise ValueError("Exactly one original source per census required")
    before = seal(streams)
    summaries, ledgers = {}, {}
    for lane in LANES:
        summaries[lane], ledgers[lane] = census_lane(
            streams[lane], native_frames=sorted(allowed)
        )
    status = acceptance(streams, native_frames=sorted(allowed), bounds=bounds)
    if seal(streams) != before:
        raise ValueError("Scientific inputs mutated")
    return {
        "source_id": next(iter(source_ids)),
        "native_frames": len(allowed),
        "scientific_status": status,
        "streams": summaries,
    }, ledgers


def require_unchanged(results, original):
    """A diagnostic never supplies a replacement acceptance criterion."""
    expected = {row["source_id"]: row for row in original["results"]}
    if len(results) != len(expected) or {r["source_id"] for r in results} != set(
        expected
    ):
        raise ValueError("Both original source slots required")
    for row in results:
        old = expected[row["source_id"]]
        if {
            "source_id": row["source_id"],
            "native_frames": row["native_frames"],
            **row["scientific_status"],
        } != old:
            raise ValueError("Unchanged frozen scientific verdict differs")
    if original["complete_references"] != sum(
        r["scientific_status"]["complete_reference"] for r in results
    ):
        raise ValueError("Unchanged complete-reference denominator differs")
    if original["all_requested_labels_supported_slots"] != sum(
        r["scientific_status"]["all_requested_labels_supported"] for r in results
    ):
        raise ValueError("Unchanged supported-label denominator differs")
    return True
