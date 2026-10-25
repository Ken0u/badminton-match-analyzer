"""Validate prospective native review structure, without accepting source truth.

Only supplied immutable JSON bytes are consumed. No image, file, Store, model,
network or assessor is accessed. Raw provenance bindings still require the
historical planner's independently granted input audit.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter

from . import rally_review_plan as planner
from . import rally_temporal_context as temporal

SCENES = ("live", "replay", "non_play", "unknown")
CONTACTS = ("observed", "possible", "not_observed", "unknown")
KINDS = ("serve", "shot", "rally_end", "unresolved_contact")
FAMILIES = ("clear", "lift", "net", "drop", "smash", "drive", "unknown")
SIDES = ("forehand", "backhand", "unknown")
TERMINAL_BASES = (
    "observed_terminal",
    "stopped_play",
    "last_stroke",
    "shuttle_absence",
    "unknown",
)
DOCUMENT_KEYS = (
    "schema_version",
    "kind",
    "contract_sha256",
    "plan_sha256",
    "source",
    "lane",
    "batch_index",
    "previous_document_sha256",
    "observations",
    "actors",
    "events",
    "boundaries",
    "event_correspondence",
    "actor_correspondence",
    "notes",
)
OBSERVATION_KEYS = (
    "frame",
    "native",
    "camera",
    "camera_view",
    "scene",
    "contact",
    "actor_ids",
    "notes",
)
ACTOR_KEYS = ("actor_id", "visibility", "evidence_frames", "notes")
EVENT_KEYS = (
    "event_id",
    "kind",
    "start_frame",
    "end_frame",
    "evidence_frames",
    "support",
    "actor_id",
    "family",
    "side",
    "terminal_basis",
    "notes",
)
EVENT_LINK_KEYS = (
    "current_event_id",
    "previous_event_id",
    "relation",
    "evidence_frames",
    "notes",
)
ACTOR_LINK_KEYS = (
    "current_actor_id",
    "previous_actor_id",
    "relation",
    "evidence_frames",
    "notes",
)
CONTRACT = {
    "schema_version": 1,
    "kind": "native_rally_review_contract",
    "document_kind": "native_rally_review",
    "fields": {
        "document": list(DOCUMENT_KEYS),
        "source": list(planner.join.SOURCE_KEYS),
        "observation": list(OBSERVATION_KEYS),
        "native": [*planner.FRAME_KEYS, "image", "available"],
        "native_image": ["path", "sha256", "bytes"],
        "actor": list(ACTOR_KEYS),
        "event": list(EVENT_KEYS),
        "boundaries": ["opening", "ending", "notes"],
        "event_correspondence": list(EVENT_LINK_KEYS),
        "actor_correspondence": list(ACTOR_LINK_KEYS),
    },
    "enums": {
        "lane": list(planner.LANES),
        "camera": ["unchanged", "change", "unknown"],
        "scene": list(SCENES),
        "contact": list(CONTACTS),
        "visibility": ["visible", "hidden", "unknown"],
        "event_kind": list(KINDS),
        "support": ["supported", "uncertain", "unknown"],
        "family": list(FAMILIES),
        "side": list(SIDES),
        "terminal_basis": list(TERMINAL_BASES),
        "boundary": ["observed", "censored", "unknown"],
        "event_relation": ["same", "distinct", "unresolved"],
        "actor_relation": ["supported", "distinct", "unresolved"],
    },
    "rules": {
        "json": "Original immutable UTF8 bytes; duplicate keys, nonfinite numbers, unknown fields and boolean ordinals rejected.",
        "plan": "Reconstruct every structural field with the unchanged original planner. Canonical packet/gallery SHA256 values are bindings only, not proof of original input provenance.",
        "bundle": "A source-plan bundle requires explicit source_id selection. Documents bind SHA256 of the entire original supplied plan bytes.",
        "identity": "Exact contract hash, raw plan hash, source and clock, lane and zero-based batch index. Previous hash is null only for batch zero; otherwise SHA256 of immediately preceding own-stream original bytes.",
        "observations": "One ordered observation for each scheduled native frame including overlap. Native is the exact full plan frame object. Camera_view is a document-local nonempty view ID, or null only with unknown camera evidence. Equal view strings across documents never establish view correspondence. Gallery context supplies no observations or truth.",
        "local_ids": "Nonempty bounded document-local IDs, unique within their own actor/event namespace. Equal strings across documents never imply correspondence.",
        "evidence": "Evidence frame arrays are strictly increasing unique integers in the document batch. Visible actors need evidence; every actor evidence frame must cite that actor in its observation. Hidden/unknown actors may have empty evidence.",
        "intervals": "Inclusive native intervals lie within the document batch. Evidence lies within interval. Both endpoints may be null only with no evidence and uncertain/unknown support; supported events need evidence. No exact physical timing is inferred.",
        "contacts": "Every observed/possible contact observation has a serve/shot/unresolved_contact event citing that evidence frame. Unknown/not_observed never proves physical absence. Repeated mentions remain separate variants.",
        "terminal": "Only rally_end may have a nonunknown terminal_basis; rally_end family/side remain unknown. Stopped play, last stroke and shuttle absence remain limitations and never prove exact ending. Observed opening/ending needs a supported serve/rally_end respectively, with observed_terminal for ending. Censoring and unknown boundaries remain explicit.",
        "links": "Only immediate-predecessor local IDs may be cited. Supplied evidence is shared overlap present in both definitions. Same-event/supported-actor requires nonempty shared evidence and one-to-one noncontradictory mapping; supported actors must both be visible. Distinct/unresolved may be unsupported claims with empty evidence and explicit uncertainty notes. Missing, unresolved or conflicting evidence is retained as unresolved diagnostics. Links never merge events or actors.",
        "prefix": "Only chronological prefixes accepted. Full expected native denominator and all unchanged parsed document variants and raw hashes retained. Private coverage records selected source/lane/raw plan hash, expected/observed/missing native ordinals and per-frame observation counts including zero counts. Unavailable plan accepts zero documents and retains reason and denominator.",
        "notes": "Every notes field is explicit text of at most 8192 characters; empty string is permitted.",
        "acceptance": "Structural coverage only. Scientific complete_references=0; all four eligibility flags false; scientific_acceptance_changed=false; execution_authorized=false. No classifier scores or scientific acceptance.",
    },
}
fingerprint = planner.fingerprint
CONTRACT_SHA256 = fingerprint(CONTRACT)
require = planner.require


def encode_json(value):
    """Deterministic UTF8/LF JSON encoding; this is never a raw-input identity."""
    planner.join._json(value)
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def strict_json(raw):
    """Parse the supplied bytes once, enforcing UTF8 and the strict JSON codec."""
    require(type(raw) is bytes, "Original immutable UTF8 bytes required")
    try:
        return planner.strict_json(raw.decode("utf-8"))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid UTF8 JSON") from exc


def _object(value, keys, name):
    require(
        type(value) is dict and set(value) == set(keys), f"Exact {name} fields required"
    )
    return value


def _list(value, name):
    require(type(value) is list, f"Explicit {name} array required")
    return value


def _enum(value, choices, name):
    require(type(value) is str and value in choices, f"Unknown {name}")


def _notes(value):
    require(
        type(value) is str and len(value) <= 8192, "Explicit bounded notes required"
    )


def _id(value):
    require(
        type(value) is str and bool(value.strip()) and len(value) <= 256,
        "Bounded local ID required",
    )
    return value


def _same(left, right):
    return fingerprint(left) == fingerprint(right)


def _frames(value, allowed):
    rows = _list(value, "evidence frames")
    for number in rows:
        temporal.integer(number)
        require(number in allowed, "Evidence frame outside native batch")
    require(rows == sorted(set(rows)), "Ordered unique evidence frames required")
    return set(rows)


def _plan(value):
    """Recreate every reconstructable field; retain raw-input hashes as bindings."""
    _object(
        value,
        (
            "schema_version",
            "kind",
            "source",
            "bindings",
            "canonical_packet_sha256",
            "canonical_gallery_sha256",
            "limits",
            "summary",
            "blocked_native_frame",
            "frames",
            "gallery_sheets",
            "navigation_context",
            "batches",
            "output_contract",
            "lane_manifests",
        ),
        "source plan",
    )
    source = _object(value["source"], planner.join.SOURCE_KEYS, "plan source")
    frames = _list(value["frames"], "native frames")
    require(bool(frames), "Full native denominator required")
    raw_frames = []
    for row in frames:
        _object(row, (*planner.FRAME_KEYS, "image", "available"), "native frame")
        raw_frames.append(
            {key: copy.deepcopy(row[key]) for key in (*planner.FRAME_KEYS, "image")}
        )
    packet = {
        **copy.deepcopy(source),
        "frames": raw_frames,
        "eligibility": dict(temporal.ELIGIBILITY),
    }
    # Original source packets can contain historical fields deliberately stripped
    # by the planner. Their canonical hashes cannot be reconstructed from a plan.
    # Recreate the gallery memberships from source metadata, not a fabricated raw
    # original packet hash, and compare only structurally reconstructable outputs.
    sheets = []
    for sheet in _list(value["gallery_sheets"], "gallery sheets"):
        _object(
            sheet,
            ("index", "path", "sha256", "bytes", "size", "frames"),
            "gallery sheet",
        )
        sheets.append(
            {key: copy.deepcopy(item) for key, item in sheet.items() if key != "index"}
        )
    gallery = {
        "schema_version": 1,
        "plan": temporal.sample_plan(packet),
        "sheets": sheets,
    }
    limits = _object(
        value["limits"], ("max_image_bytes", "max_distinct_images"), "plan limits"
    )
    expected_source = {
        **source,
        "packet_sha256": value["bindings"]["packet_sha256"],
        "native_frame_count": len(frames),
    }
    _, rebuilt = planner.plan_source(
        packet,
        gallery,
        expected_source=expected_source,
        bindings=value["bindings"],
        max_bytes=limits["max_image_bytes"],
        max_images=limits["max_distinct_images"],
    )
    for key in ("canonical_packet_sha256", "canonical_gallery_sha256"):
        temporal.sha(value[key])
        rebuilt[key] = value[key]
    require(_same(value, rebuilt), "Plan structural schedule or identity changed")
    return value


def _select_plan(parsed, source_id):
    require(type(parsed) is dict, "Source plan object required")
    if "kind" in parsed:
        plan = _plan(parsed)
        require(
            source_id is None or source_id == plan["source"]["source_id"],
            "Selected source mismatch",
        )
        return plan, {
            "plan_container": "single_source",
            "selected_source_count": 1,
            "supplied_source_count": 1,
        }
    require(
        bool(parsed) and type(source_id) is str and source_id in parsed,
        "Plan bundle requires explicit source_id selection",
    )
    # Validate every supplied structural plan, so selection never silently hides
    # another source's malformed or unavailable denominator.
    for key, value in parsed.items():
        plan = _plan(value)
        require(key == plan["source"]["source_id"], "Bundle source key mismatch")
    return parsed[source_id], {
        "plan_container": "bundle",
        "selected_source_count": 1,
        "supplied_source_count": len(parsed),
    }


def _definitions(doc, numbers, observations):
    actors, events = {}, {}
    for actor in _list(doc["actors"], "actors"):
        _object(actor, ACTOR_KEYS, "actor")
        identity = _id(actor["actor_id"])
        require(identity not in actors, "Duplicate local actor ID")
        _enum(actor["visibility"], ("visible", "hidden", "unknown"), "actor visibility")
        evidence = _frames(actor["evidence_frames"], numbers)
        require(
            actor["visibility"] != "visible" or bool(evidence),
            "Visible actor needs source evidence",
        )
        for frame in evidence:
            require(
                identity in observations[frame]["actor_ids"],
                "Actor source evidence missing observation reference",
            )
        _notes(actor["notes"])
        actors[identity] = actor
    for row in observations.values():
        ids = _list(row["actor_ids"], "observation actor IDs")
        require(
            len(ids) == len({_id(identity) for identity in ids}),
            "Duplicate observed actor ID",
        )
        require(
            all(identity in actors for identity in ids), "Unknown local actor reference"
        )
    for event in _list(doc["events"], "events"):
        _object(event, EVENT_KEYS, "event")
        identity = _id(event["event_id"])
        require(identity not in events, "Duplicate local event ID")
        _enum(event["kind"], KINDS, "event kind")
        _enum(event["support"], ("supported", "uncertain", "unknown"), "source support")
        _enum(event["family"], FAMILIES, "stroke family")
        _enum(event["side"], SIDES, "stroke side")
        _enum(event["terminal_basis"], TERMINAL_BASES, "terminal basis")
        evidence = _frames(event["evidence_frames"], numbers)
        start, end = event["start_frame"], event["end_frame"]
        if start is None or end is None:
            require(
                start is end is None
                and not evidence
                and event["support"] != "supported",
                "Unknown interval cannot claim supported timing",
            )
        else:
            temporal.integer(start)
            temporal.integer(end)
            require(
                start in numbers and end in numbers and start <= end,
                "Inclusive event interval outside native batch",
            )
            require(
                all(start <= frame <= end for frame in evidence),
                "Event evidence outside inclusive interval",
            )
        require(
            event["support"] != "supported" or bool(evidence),
            "Supported event needs source evidence",
        )
        require(
            event["actor_id"] is None or _id(event["actor_id"]) in actors,
            "Unknown event actor reference",
        )
        if event["kind"] == "rally_end":
            require(
                event["family"] == event["side"] == "unknown",
                "Terminal event cannot supply stroke labels",
            )
        else:
            require(
                event["terminal_basis"] == "unknown",
                "Nonterminal event cannot supply ending basis",
            )
        _notes(event["notes"])
        events[identity] = event
    for number, row in observations.items():
        if row["contact"] in ("observed", "possible"):
            require(
                any(
                    event["kind"] != "rally_end" and number in event["evidence_frames"]
                    for event in events.values()
                ),
                "Contact observation needs local contact event mention",
            )
    return actors, events


def _boundaries(doc, events):
    boundary = _object(doc["boundaries"], ("opening", "ending", "notes"), "boundary")
    for key in ("opening", "ending"):
        _enum(boundary[key], ("observed", "censored", "unknown"), "boundary evidence")
    _notes(boundary["notes"])
    for key, kind in (("opening", "serve"), ("ending", "rally_end")):
        if boundary[key] == "observed":
            require(
                any(
                    event["kind"] == kind
                    and event["support"] == "supported"
                    and (
                        key != "ending"
                        or event["terminal_basis"] == "observed_terminal"
                    )
                    for event in events.values()
                ),
                "Observed boundary needs supported source event",
            )


def _links(doc, prior, current_defs, prior_defs, overlap, kind):
    actor = kind == "actor"
    field = f"{kind}_correspondence"
    current_key, previous_key = f"current_{kind}_id", f"previous_{kind}_id"
    relation = "supported" if actor else "same"
    keys = ACTOR_LINK_KEYS if actor else EVENT_LINK_KEYS
    diagnostics, seen, supported_current, supported_previous = [], set(), {}, {}
    claims = _list(doc[field], field)
    require(prior is not None or not claims, "First document cannot cite a predecessor")
    for claim in claims:
        _object(claim, keys, field)
        current, previous = _id(claim[current_key]), _id(claim[previous_key])
        require(
            current in current_defs and previous in prior_defs,
            "Correspondence needs immediate predecessor local references",
        )
        pair = (current, previous)
        require(pair not in seen, "Duplicate or contradictory correspondence pair")
        seen.add(pair)
        _enum(
            claim["relation"],
            (relation, "distinct", "unresolved"),
            "correspondence relation",
        )
        evidence = _frames(
            claim["evidence_frames"], {overlap} if overlap is not None else set()
        )
        require(
            evidence
            <= set(current_defs[current]["evidence_frames"])
            & set(prior_defs[previous]["evidence_frames"]),
            "Correspondence needs shared native overlap evidence",
        )
        if claim["relation"] == relation:
            require(
                bool(evidence), "Supported correspondence needs shared overlap evidence"
            )
            if actor:
                require(
                    current_defs[current]["visibility"]
                    == prior_defs[previous]["visibility"]
                    == "visible",
                    "Hidden or unknown actors cannot support positive identity correspondence",
                )
            require(
                current not in supported_current and previous not in supported_previous,
                "Conflicting one-to-one supported correspondence",
            )
            supported_current[current] = previous
            supported_previous[previous] = current
        elif claim["relation"] == "unresolved":
            diagnostics.append(
                {
                    "code": f"unresolved_{kind}_correspondence",
                    current_key: current,
                    previous_key: previous,
                }
            )
        _notes(claim["notes"])
        require(
            bool(evidence) or bool(claim["notes"].strip()),
            "Unsupported correspondence needs explicit uncertainty notes",
        )
    # Each overlap occurrence needs explicit supported correspondence to be
    # structurally linked. A distinct claim does not invent its actual match.
    if prior is not None:
        for side, definitions, linked in (
            ("current", current_defs, supported_current),
            ("previous", prior_defs, supported_previous),
        ):
            for identity, value in definitions.items():
                if overlap in value["evidence_frames"] and identity not in linked:
                    diagnostics.append(
                        {
                            "code": f"unresolved_{kind}_overlap_occurrence",
                            f"{side}_{kind}_id": identity,
                        }
                    )
    return diagnostics


def _document(doc, plan, plan_sha256, lane, index, previous_hash, prior):
    _object(doc, DOCUMENT_KEYS, "document")
    require(
        type(doc["schema_version"]) is int
        and doc["schema_version"] == 1
        and doc["kind"] == "native_rally_review",
        "Wrong review document identity",
    )
    require(
        doc["contract_sha256"] == CONTRACT_SHA256 and doc["plan_sha256"] == plan_sha256,
        "Wrong contract or original plan SHA256",
    )
    require(
        _same(doc["source"], plan["source"]) and doc["lane"] == lane,
        "Wrong source, clock or lane",
    )
    require(
        type(doc["batch_index"]) is int and doc["batch_index"] == index,
        "Chronological prefix batch index required",
    )
    require(
        doc["previous_document_sha256"] == previous_hash,
        "Immediate own-stream raw predecessor SHA256 required",
    )
    batch = plan["batches"][index]
    native = {row["frame"]: row for row in plan["frames"]}
    rows = _list(doc["observations"], "native observations")
    require(
        len(rows) == len(batch["frames"]),
        "Exactly every scheduled native observation required",
    )
    observations = {}
    for row, number in zip(rows, batch["frames"]):
        _object(row, OBSERVATION_KEYS, "observation")
        require(
            type(row["frame"]) is int
            and row["frame"] == number
            and _same(row["native"], native[number]),
            "Native observation order or exact image/clock identity changed",
        )
        _enum(row["camera"], ("unchanged", "change", "unknown"), "camera evidence")
        require(
            (row["camera_view"] is None and row["camera"] == "unknown")
            or (type(row["camera_view"]) is str and bool(_id(row["camera_view"]))),
            "Camera view evidence required unless unknown",
        )
        _enum(row["scene"], SCENES, "scene evidence")
        _enum(row["contact"], CONTACTS, "contact evidence")
        _notes(row["notes"])
        observations[number] = row
    actors, events = _definitions(doc, set(batch["frames"]), observations)
    _boundaries(doc, events)
    _notes(doc["notes"])
    prior_actors = {row["actor_id"]: row for row in prior["actors"]} if prior else {}
    prior_events = {row["event_id"]: row for row in prior["events"]} if prior else {}
    overlap = batch["overlap_frame"]
    diagnostics = _links(doc, prior, events, prior_events, overlap, "event")
    diagnostics += _links(doc, prior, actors, prior_actors, overlap, "actor")
    for event in events.values():
        if event["kind"] == "rally_end" and event["terminal_basis"] in (
            "stopped_play",
            "last_stroke",
            "shuttle_absence",
        ):
            diagnostics.append(
                {
                    "code": "unsupported_terminal_basis",
                    "event_id": event["event_id"],
                    "basis": event["terminal_basis"],
                }
            )
    if prior is not None:
        prior_observation = prior["observations"][-1]
        current_observation = observations[overlap]
        # Actor strings are intentionally excluded: they are document-local.
        changed = [
            key
            for key in ("camera", "scene", "contact")
            if prior_observation[key] != current_observation[key]
        ]
        if changed:
            diagnostics.append(
                {
                    "code": "overlap_observation_variants",
                    "frame": overlap,
                    "fields": changed,
                }
            )
    return diagnostics


def validate_stream(
    plan_raw: bytes, documents: list[bytes], lane: str, *, source_id=None
):
    """Return public aggregate structure and unchanged private document variants.

    Malformed inputs raise ValueError; a valid chronological prefix is retained
    as incomplete, including a zero-document prefix. Structural completion never
    asserts scientific truth, execution authority or source eligibility.
    """
    try:
        return _validate_stream(plan_raw, documents, lane, source_id=source_id)
    except (
        KeyError,
        TypeError,
        IndexError,
        OverflowError,
        RecursionError,
        ZeroDivisionError,
    ) as exc:
        raise ValueError("Malformed review contract input") from exc


def _validate_stream(plan_raw, documents, lane, *, source_id):
    _enum(lane, planner.LANES, "planned lane")
    _list(documents, "original document bytes")
    plan, scope = _select_plan(strict_json(plan_raw), source_id)
    plan_sha256 = hashlib.sha256(plan_raw).hexdigest()
    expected = len(plan["batches"])
    require(len(documents) <= expected, "Too many documents or unavailable plan")
    private, previous_hash, prior = [], None, None
    observed, occurrences, event_variants, actor_variants = set(), 0, 0, 0
    observation_counts = Counter()
    for index, raw in enumerate(documents):
        doc = strict_json(raw)
        raw_hash = hashlib.sha256(raw).hexdigest()
        diagnostics = _document(
            doc, plan, plan_sha256, lane, index, previous_hash, prior
        )
        private.append(
            {"sha256": raw_hash, "document": doc, "diagnostics": diagnostics}
        )
        observed.update(row["frame"] for row in doc["observations"])
        observation_counts.update(row["frame"] for row in doc["observations"])
        occurrences += len(doc["observations"])
        event_variants += len(doc["events"])
        actor_variants += len(doc["actors"])
        previous_hash, prior = raw_hash, doc
    unavailable = plan["summary"]["status"] == "unavailable"
    summary = {
        "schema_version": 1,
        "contract_sha256": CONTRACT_SHA256,
        "selection_scope": scope,
        "status": "unavailable"
        if unavailable
        else "structurally_complete"
        if len(documents) == expected
        else "incomplete",
        "reason": plan["summary"]["reason"] if unavailable else None,
        "expected_documents": expected,
        "received_documents": len(documents),
        "expected_native_frames": len(plan["frames"]),
        "observed_native_frames": len(observed),
        "missing_native_frames": len(plan["frames"]) - len(observed),
        "observation_occurrences": occurrences,
        "repeated_overlap_observations": occurrences - len(observed),
        "event_variants": event_variants,
        "actor_variants": actor_variants,
        "unresolved_correspondences": sum(
            row["code"].startswith("unresolved_")
            for item in private
            for row in item["diagnostics"]
        ),
        "complete_references": 0,
        "eligibility": dict(temporal.ELIGIBILITY),
        "scientific_acceptance_changed": False,
        "execution_authorized": False,
    }
    expected_frames = [row["frame"] for row in plan["frames"]]
    coverage = {
        "source": copy.deepcopy(plan["source"]),
        "lane": lane,
        "plan_sha256": plan_sha256,
        "expected_frames": expected_frames,
        "observed_frames": sorted(observed),
        "missing_frames": [frame for frame in expected_frames if frame not in observed],
        "observation_counts": [
            {"frame": frame, "count": observation_counts[frame]}
            for frame in expected_frames
        ],
    }
    return {"summary": summary, "coverage": coverage, "documents": private}
