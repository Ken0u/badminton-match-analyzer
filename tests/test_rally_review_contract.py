"""Generated metadata only; no scientific packets, labels, images or models."""

import copy
import hashlib
from fractions import Fraction

import pytest
from badminton import rally_review_contract as contract
from badminton import rally_review_plan as planner
from badminton import rally_temporal_context as temporal


def generated_plan(
    *, count=9, times=None, rotation=0, first=0, unavailable=False, max_images=4
):
    times = (
        times if times is not None else [Fraction(number, 2) for number in range(count)]
    )
    packet = {
        "source_id": "generated",
        "source_sha256": "a" * 64,
        "clock_sha256": "b" * 64,
        "eligibility": dict(temporal.ELIGIBILITY),
        "frames": [
            {
                "frame": first + number,
                "pts": time.numerator,
                "time_base": str(Fraction(1, time.denominator)),
                "time_s": float(time),
                "rotation": rotation,
                "source_size": [32, 24],
                "display_size": [24, 32] if rotation in (90, 270) else [32, 24],
                "orientation_error": None,
                "corrupt": False,
                "image": {
                    "path": f"generated/{number}.png",
                    "sha256": hashlib.sha256(str(number).encode()).hexdigest(),
                    "bytes": 100,
                },
            }
            for number, time in enumerate(times)
        ],
    }
    if unavailable:
        packet["frames"][0]["image"] = None
    samples = temporal.sample_plan(packet)
    selected = [row["frame"] for row in samples["samples"]]
    gallery = {
        "schema_version": 1,
        "plan": samples,
        "sheets": [
            {
                "path": f"sheet-{index:03d}.png",
                "sha256": hashlib.sha256(f"sheet-{index}".encode()).hexdigest(),
                "bytes": 100,
                "size": list(temporal.SHEET),
                "frames": selected[start : start + 16],
            }
            for index, start in enumerate(range(0, len(selected), 16))
        ],
    }
    bindings = dict.fromkeys(planner.BINDING_KEYS, "c" * 64)
    return planner.plan_source(
        packet,
        gallery,
        expected_source={
            "source_id": packet["source_id"],
            "source_sha256": packet["source_sha256"],
            "clock_sha256": packet["clock_sha256"],
            "packet_sha256": bindings["packet_sha256"],
            "native_frame_count": len(times),
        },
        bindings=bindings,
        max_images=max_images,
    )[1]


def generated_documents(plan, plan_raw=None, *, lane="independent_a"):
    plan_raw = contract.encode_json(plan) if plan_raw is None else plan_raw
    frames = {row["frame"]: row for row in plan["frames"]}
    documents, previous = [], None
    for batch in plan["batches"]:
        document = {
            "schema_version": 1,
            "kind": "native_rally_review",
            "contract_sha256": contract.CONTRACT_SHA256,
            "plan_sha256": hashlib.sha256(plan_raw).hexdigest(),
            "source": copy.deepcopy(plan["source"]),
            "lane": lane,
            "batch_index": batch["index"],
            "previous_document_sha256": previous,
            "observations": [
                {
                    "frame": frame,
                    "native": copy.deepcopy(frames[frame]),
                    "camera": "unknown",
                    "camera_view": None,
                    "scene": "unknown",
                    "contact": "unknown",
                    "actor_ids": [],
                    "notes": "Generated unknown source evidence",
                }
                for frame in batch["frames"]
            ],
            "actors": [],
            "events": [],
            "boundaries": {
                "opening": "censored",
                "ending": "unknown",
                "notes": "Unknown boundaries",
            },
            "event_correspondence": [],
            "actor_correspondence": [],
            "notes": "Generated only",
        }
        raw = contract.encode_json(document)
        documents.append(raw)
        previous = hashlib.sha256(raw).hexdigest()
    return documents


def rebuild_chain(documents):
    previous, result = None, []
    for raw in documents:
        document = (
            contract.strict_json(raw) if type(raw) is bytes else copy.deepcopy(raw)
        )
        document["previous_document_sha256"] = previous
        raw = contract.encode_json(document)
        result.append(raw)
        previous = hashlib.sha256(raw).hexdigest()
    return result


def event(identity, frame, **changes):
    return {
        "event_id": identity,
        "kind": "unresolved_contact",
        "start_frame": frame,
        "end_frame": frame,
        "evidence_frames": [frame],
        "support": "uncertain",
        "actor_id": None,
        "family": "unknown",
        "side": "unknown",
        "terminal_basis": "unknown",
        "notes": "Generated uncertain event",
        **changes,
    }


def with_overlap_entities(plan, documents):
    docs = [contract.strict_json(raw) for raw in documents[:2]]
    frame = plan["batches"][1]["overlap_frame"]
    for doc in docs:
        observation = next(row for row in doc["observations"] if row["frame"] == frame)
        observation.update(contact="possible", actor_ids=["local-person"])
        doc["actors"] = [
            {
                "actor_id": "local-person",
                "visibility": "visible",
                "evidence_frames": [frame],
                "notes": "Generated visible source",
            }
        ]
        doc["events"] = [event("local-contact", frame, actor_id="local-person")]
    return docs, frame


def validate(plan, documents=None, **kwargs):
    raw = contract.encode_json(plan)
    return contract.validate_stream(
        raw,
        generated_documents(plan, raw) if documents is None else documents,
        "independent_a",
        **kwargs,
    )


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"rotation": 90},
        {"rotation": 180},
        {"rotation": 270},
        {"first": 43},
        {"times": [Fraction(80) + Fraction(n * n, 10) for n in range(9)]},
        {"count": 1},
        {"count": 38, "max_images": 20},
    ],
)
def test_generated_complete_structure_preserves_clock_orientation_and_full_denominator(
    options,
):
    plan = generated_plan(**options)
    before = copy.deepcopy(plan)
    raw = contract.encode_json(plan)
    docs = generated_documents(plan, raw)
    result = contract.validate_stream(raw, docs, "independent_a")
    summary = result["summary"]
    assert summary["status"] == "structurally_complete"
    assert (
        summary["expected_native_frames"]
        == summary["observed_native_frames"]
        == len(plan["frames"])
    )
    assert summary["missing_native_frames"] == 0
    assert summary["repeated_overlap_observations"] == len(docs) - 1
    assert summary["observation_occurrences"] == len(plan["frames"]) + len(docs) - 1
    assert summary["complete_references"] == 0
    assert summary["eligibility"] == temporal.ELIGIBILITY
    assert (
        summary["scientific_acceptance_changed"]
        is summary["execution_authorized"]
        is False
    )
    for original, row in zip(docs, result["documents"]):
        assert row["sha256"] == hashlib.sha256(original).hexdigest()
        assert row["document"] == contract.strict_json(original)
    assert plan == before


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_valid_prefix_keeps_all_missing_native_frames(count):
    plan = generated_plan()
    documents = generated_documents(plan)[:count]
    summary = validate(plan, documents)["summary"]
    expected_observed = {
        frame for batch in plan["batches"][:count] for frame in batch["frames"]
    }
    assert summary["status"] == "incomplete"
    assert summary["expected_documents"] == 4
    assert summary["expected_native_frames"] == 9
    assert summary["observed_native_frames"] == len(expected_observed)
    assert summary["missing_native_frames"] == 9 - len(expected_observed)


@pytest.mark.parametrize("native_unavailable", [True, False])
def test_unavailable_plan_keeps_full_denominator_and_reason(native_unavailable):
    plan = generated_plan(
        unavailable=native_unavailable, max_images=4 if native_unavailable else 1
    )
    summary = validate(plan, [])["summary"]
    assert summary["status"] == "unavailable"
    assert summary["expected_native_frames"] == summary["missing_native_frames"] == 9
    assert summary["reason"] == (
        "unavailable_native_input" if native_unavailable else "oversized_minimum_batch"
    )
    with pytest.raises(ValueError):
        validate(plan, [b"{}"])


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), True),
        (("kind",), "different"),
        (("source", "source_sha256"), "bad"),
        (("source", "extra"), 1),
        (("canonical_packet_sha256",), "bad"),
        (("canonical_gallery_sha256",), False),
        (("bindings", "extra"), "c" * 64),
        (("limits", "max_image_bytes"), 0),
        (("limits", "max_distinct_images"), True),
        (("summary", "native_frames"), 8),
        (("summary", "complete_references"), 1),
        (("summary", "available_native_frames"), False),
        (("summary", "proposed_image_bytes"), 1),
        (("summary", "reason"), "invented"),
        (("frames", 0, "pts"), True),
        (("frames", 0, "time_base"), "1/0"),
        (("frames", 0, "time_s"), 7),
        (("frames", 0, "rotation"), False),
        (("frames", 0, "display_size"), [24, 32]),
        (("frames", 0, "available"), 1),
        (("frames", 0, "image", "bytes"), False),
        (("frames", 0, "image", "extra"), 1),
        (("frames", 0, "extra"), 1),
        (("gallery_sheets", 0, "index"), True),
        (("gallery_sheets", 0, "frames"), [999]),
        (("gallery_sheets", 0, "size"), [1, 1]),
        (("navigation_context", 0, "sheet"), 1),
        (("navigation_context", 0, "nearest_sample"), 999),
        (("batches", 1, "overlap_frame"), 1),
        (("batches", 0, "total_image_bytes"), 0),
        (("batches", 0, "frames"), [0, 2, 1]),
        (("lane_manifests", 0, "execution_authorized"), True),
        (("output_contract", "acceptance"), "truth promoted"),
        (("extra",), 1),
    ],
)
def test_mutated_plan_structural_fields_rejected(path, value):
    plan = generated_plan()
    target = plan
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate(plan, [])


def test_canonical_hashes_are_bindings_not_fabricated_proof_of_original_packets():
    plan = generated_plan()
    plan["canonical_packet_sha256"] = "d" * 64
    plan["canonical_gallery_sha256"] = "e" * 64
    assert validate(plan)["summary"]["status"] == "structurally_complete"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":{"y":1,"y":2}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e999}',
        b'{"x":[1e999]}',
        b"\xff",
        '{"x":1}'.encode("utf-16"),
    ],
)
def test_strict_original_utf8_json_rejects_invalid_values(raw):
    with pytest.raises(ValueError):
        contract.strict_json(raw)


@pytest.mark.parametrize("value", ["{}", bytearray(b"{}"), {}, None])
def test_codec_requires_immutable_bytes(value):
    with pytest.raises(ValueError):
        contract.strict_json(value)


def test_plan_raw_whitespace_identity_and_document_raw_predecessor_identity():
    plan = generated_plan()
    raw = contract.encode_json(plan)
    docs = generated_documents(plan, raw)
    with pytest.raises(ValueError, match="original plan SHA256"):
        contract.validate_stream(raw + b"\n", docs, "independent_a")
    changed = [docs[0] + b" \n", *docs[1:]]
    with pytest.raises(ValueError, match="raw predecessor"):
        contract.validate_stream(raw, changed, "independent_a")
    first = contract.strict_json(docs[0])
    assert contract.fingerprint(first) != hashlib.sha256(docs[0] + b"\n").hexdigest()


@pytest.mark.parametrize(
    "change",
    [
        "skip",
        "reorder",
        "duplicate",
        "wrong_lane",
        "wrong_source",
        "wrong_clock",
        "wrong_contract",
        "wrong_index_bool",
        "first_predecessor",
        "late_null",
        "unknown",
        "classifier",
    ],
)
def test_document_identity_chain_source_lane_and_unknown_fields_rejected(change):
    plan = generated_plan()
    docs = generated_documents(plan)
    if change in ("skip", "reorder", "duplicate"):
        indices = {"skip": [0, 2], "reorder": [1, 0], "duplicate": [0, 0]}[change]
        docs = [docs[index] for index in indices]
    else:
        document = contract.strict_json(docs[1] if change == "late_null" else docs[0])
        if change == "wrong_lane":
            document["lane"] = "independent_b"
        elif change == "wrong_source":
            document["source"]["source_id"] = "another"
        elif change == "wrong_clock":
            document["source"]["clock_sha256"] = "e" * 64
        elif change == "wrong_contract":
            document["contract_sha256"] = "e" * 64
        elif change == "wrong_index_bool":
            document["batch_index"] = False
        elif change == "first_predecessor":
            document["previous_document_sha256"] = "e" * 64
        elif change == "late_null":
            document["previous_document_sha256"] = None
        else:
            document["score" if change == "classifier" else "extra"] = 0.9
        docs[1 if change == "late_null" else 0] = contract.encode_json(document)
    with pytest.raises(ValueError):
        validate(plan, docs)


@pytest.mark.parametrize(
    "path,value",
    [
        (("observations",), []),
        (("observations", 0, "frame"), False),
        (("observations", 0, "native", "pts"), 3),
        (("observations", 0, "native", "image", "sha256"), "f" * 64),
        (("observations", 0, "scene"), "live_play"),
        (("observations", 0, "contact"), "absent"),
        (("observations", 0, "camera"), "same_view"),
        (("observations", 0, "camera"), "change"),
        (("observations", 0, "camera_view"), False),
        (("observations", 0, "actor_ids"), ["nonexistent"]),
        (("observations", 0, "notes"), None),
        (("observations", 0, "extra"), 1),
        (("boundaries", "extra"), 1),
        (("boundaries", "opening"), "observed"),
    ],
)
def test_observation_and_boundary_fields_are_exact(path, value):
    plan = generated_plan()
    doc = contract.strict_json(generated_documents(plan)[0])
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate(plan, [contract.encode_json(doc)])


def test_gallery_context_never_substitutes_for_missing_native_or_contact_mentions():
    plan = generated_plan()
    doc = contract.strict_json(generated_documents(plan)[0])
    doc["observations"][1]["contact"] = "possible"
    with pytest.raises(ValueError, match="event mention"):
        validate(plan, [contract.encode_json(doc)])
    doc["events"] = [event("one", 1)]
    assert validate(plan, [contract.encode_json(doc)])["summary"]["event_variants"] == 1
    doc["events"][0]["evidence_frames"] = [0]
    with pytest.raises(ValueError):
        validate(plan, [contract.encode_json(doc)])


def test_equal_local_ids_do_not_establish_correspondence_and_all_variants_remain():
    plan = generated_plan()
    docs, frame = with_overlap_entities(plan, generated_documents(plan))
    docs[1]["events"][0].update(
        family="smash", side="backhand", start_frame=frame, end_frame=frame + 1
    )
    result = validate(plan, rebuild_chain(docs))
    assert (
        result["summary"]["event_variants"] == result["summary"]["actor_variants"] == 2
    )
    assert result["summary"]["unresolved_correspondences"] == 4
    assert result["documents"][0]["document"]["events"][0]["family"] == "unknown"
    assert result["documents"][1]["document"]["events"][0]["family"] == "smash"
    assert "global_actor_map" not in result


def test_explicit_supported_links_preserve_variants_without_merging():
    plan = generated_plan()
    docs, frame = with_overlap_entities(plan, generated_documents(plan))
    docs[1]["event_correspondence"] = [
        {
            "current_event_id": "local-contact",
            "previous_event_id": "local-contact",
            "relation": "same",
            "evidence_frames": [frame],
            "notes": "Generated shared overlap",
        }
    ]
    docs[1]["actor_correspondence"] = [
        {
            "current_actor_id": "local-person",
            "previous_actor_id": "local-person",
            "relation": "supported",
            "evidence_frames": [frame],
            "notes": "Generated shared overlap",
        }
    ]
    result = validate(plan, rebuild_chain(docs))
    assert result["summary"]["unresolved_correspondences"] == 0
    assert result["summary"]["event_variants"] == 2
    assert result["summary"]["actor_variants"] == 2


@pytest.mark.parametrize(
    "kind,relation",
    [
        ("event", "unresolved"),
        ("event", "distinct"),
        ("actor", "unresolved"),
        ("actor", "distinct"),
    ],
)
def test_unresolved_and_distinct_links_allow_disjoint_evidence_and_preserve_uncertainty(
    kind, relation
):
    plan = generated_plan()
    docs, _frame = with_overlap_entities(plan, generated_documents(plan))
    docs[1][f"{kind}_correspondence"] = [
        {
            f"current_{kind}_id": "local-contact"
            if kind == "event"
            else "local-person",
            f"previous_{kind}_id": "local-contact"
            if kind == "event"
            else "local-person",
            "relation": relation,
            "evidence_frames": [],
            "notes": "Correspondence remains unknown",
        }
    ]
    result = validate(plan, rebuild_chain(docs))
    assert result["summary"]["unresolved_correspondences"] >= 4
    assert (
        result["documents"][1]["document"][f"{kind}_correspondence"][0]["relation"]
        == relation
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing_shared",
        "outside_overlap",
        "unknown_local",
        "non_immediate",
        "duplicate",
        "one_to_many",
        "many_to_one",
        "hidden",
        "unknown_actor",
    ],
)
def test_supported_link_requires_shared_visible_evidence_and_nonconflicting_one_to_one_claims(
    change,
):
    plan = generated_plan()
    docs, frame = with_overlap_entities(plan, generated_documents(plan))
    link = {
        "current_actor_id": "local-person",
        "previous_actor_id": "local-person",
        "relation": "supported",
        "evidence_frames": [frame],
        "notes": "Generated link",
    }
    docs[1]["actor_correspondence"] = [link]
    if change == "missing_shared":
        link["evidence_frames"] = []
    elif change == "outside_overlap":
        link["evidence_frames"] = [frame + 1]
    elif change in ("unknown_local", "non_immediate"):
        link["previous_actor_id"] = "unknown-or-older-document-actor"
    elif change == "duplicate":
        docs[1]["actor_correspondence"].append(copy.deepcopy(link))
    elif change in ("one_to_many", "many_to_one"):
        side = 0 if change == "one_to_many" else 1
        second = copy.deepcopy(docs[side]["actors"][0])
        second["actor_id"] = "second"
        docs[side]["actors"].append(second)
        next(row for row in docs[side]["observations"] if row["frame"] == frame)[
            "actor_ids"
        ].append("second")
        other = copy.deepcopy(link)
        other["previous_actor_id" if side == 0 else "current_actor_id"] = "second"
        docs[1]["actor_correspondence"].append(other)
    else:
        docs[0]["actors"][0]["visibility"] = (
            "hidden" if change == "hidden" else "unknown"
        )
    with pytest.raises(ValueError):
        validate(plan, rebuild_chain(docs))


def test_event_same_link_requires_shared_event_evidence_not_just_interval_overlap():
    plan = generated_plan()
    docs, frame = with_overlap_entities(plan, generated_documents(plan))
    docs[1]["event_correspondence"] = [
        {
            "current_event_id": "local-contact",
            "previous_event_id": "local-contact",
            "relation": "same",
            "evidence_frames": [frame],
            "notes": "Generated",
        }
    ]
    docs[0]["events"][0]["evidence_frames"] = []
    docs[0]["observations"][-1]["contact"] = "unknown"
    with pytest.raises(ValueError, match="shared native overlap"):
        validate(plan, rebuild_chain(docs))


@pytest.mark.parametrize("family", contract.FAMILIES)
@pytest.mark.parametrize("side", contract.SIDES)
def test_every_family_and_side_and_hidden_actor_remain_permitted_unknowns(family, side):
    plan = generated_plan()
    doc = contract.strict_json(generated_documents(plan)[0])
    doc["actors"] = [
        {
            "actor_id": "hidden",
            "visibility": "hidden",
            "evidence_frames": [],
            "notes": "Occluded",
        }
    ]
    doc["events"] = [
        event("contact", 1, kind="shot", actor_id="hidden", family=family, side=side)
    ]
    result = validate(plan, [contract.encode_json(doc)])
    assert result["documents"][0]["document"]["events"][0]["family"] == family
    assert result["summary"]["complete_references"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "half_smash",
        "side",
        "actor",
        "bool_start",
        "inverted",
        "outside",
        "evidence_outside",
        "duplicate_evidence",
        "unknown_field",
        "partial_null",
        "supported_null",
        "unsupported_empty",
        "nonterminal_basis",
    ],
)
def test_local_event_interval_label_reference_and_source_support_rejections(change):
    plan = generated_plan()
    doc = contract.strict_json(generated_documents(plan)[0])
    item = event("contact", 1)
    doc["events"] = [item]
    if change == "half_smash":
        item["family"] = "half_smash"
    elif change == "side":
        item["side"] = "both"
    elif change == "actor":
        item["actor_id"] = "missing"
    elif change == "bool_start":
        item["start_frame"] = False
    elif change == "inverted":
        item.update(start_frame=2, end_frame=1)
    elif change == "outside":
        item["end_frame"] = 3
    elif change == "evidence_outside":
        item["evidence_frames"] = [0]
    elif change == "duplicate_evidence":
        item["evidence_frames"] = [1, 1]
    elif change == "unknown_field":
        item["score"] = 0.8
    elif change == "partial_null":
        item["start_frame"] = None
    elif change == "supported_null":
        item.update(
            start_frame=None, end_frame=None, evidence_frames=[], support="supported"
        )
    elif change == "unsupported_empty":
        item.update(evidence_frames=[], support="supported")
    else:
        item["terminal_basis"] = "last_stroke"
    with pytest.raises(ValueError):
        validate(plan, [contract.encode_json(doc)])


def test_inclusive_boundary_support_unknown_timing_and_unsupported_terminal_basis_retained():
    plan = generated_plan()
    doc = contract.strict_json(generated_documents(plan)[0])
    doc["events"] = [
        event(
            "serve",
            0,
            kind="serve",
            start_frame=0,
            end_frame=1,
            evidence_frames=[0, 1],
            support="supported",
        ),
        event(
            "hidden",
            1,
            start_frame=None,
            end_frame=None,
            evidence_frames=[],
            support="unknown",
        ),
        event("ending", 2, kind="rally_end", terminal_basis="stopped_play"),
    ]
    doc["boundaries"]["opening"] = "observed"
    result = validate(plan, [contract.encode_json(doc)])
    assert result["documents"][0]["document"] == doc
    assert {row["code"] for row in result["documents"][0]["diagnostics"]} == {
        "unsupported_terminal_basis"
    }
    doc["boundaries"]["ending"] = "observed"
    with pytest.raises(ValueError, match="Observed boundary"):
        validate(plan, [contract.encode_json(doc)])
    doc["events"][-1].update(terminal_basis="observed_terminal", support="supported")
    assert (
        validate(plan, [contract.encode_json(doc)])["summary"]["complete_references"]
        == 0
    )


def test_bundle_requires_explicit_source_and_binds_entire_original_bundle_bytes():
    first, second = generated_plan(), generated_plan(count=1)
    second["source"]["source_id"] = "other"
    second["summary"]["source_id"] = "other"
    for lane in second["lane_manifests"]:
        lane["source"]["source_id"] = "other"
    bundle = {"generated": first, "other": second}
    raw = contract.encode_json(bundle)
    docs = generated_documents(first, raw)
    with pytest.raises(ValueError, match="explicit source_id"):
        contract.validate_stream(raw, docs, "independent_a")
    result = contract.validate_stream(raw, docs, "independent_a", source_id="generated")
    assert result["summary"]["selection_scope"] == {
        "plan_container": "bundle",
        "selected_source_count": 1,
        "supplied_source_count": 2,
    }
    with pytest.raises(ValueError, match="original plan SHA256"):
        contract.validate_stream(contract.encode_json(first), docs, "independent_a")
    bundle["other"]["summary"]["native_frames"] = 99
    with pytest.raises(ValueError):
        contract.validate_stream(
            contract.encode_json(bundle), [], "independent_a", source_id="generated"
        )


def test_contract_fingerprint_and_encoding_are_frozen_deterministic_and_lf():
    assert contract.CONTRACT_SHA256 == contract.fingerprint(contract.CONTRACT)
    raw = contract.encode_json(contract.CONTRACT)
    assert b"\r" not in raw and raw.endswith(b"\n")
    assert contract.strict_json(raw) == contract.CONTRACT
    with pytest.raises(ValueError):
        contract.encode_json({"score": float("nan")})


def test_private_native_coverage_retains_missing_ordinals_and_overlap_occurrences():
    plan = generated_plan(first=40)
    result = validate(plan, generated_documents(plan)[:2])
    coverage = result["coverage"]
    assert coverage["source"] == plan["source"]
    assert coverage["lane"] == "independent_a"
    assert (
        coverage["plan_sha256"]
        == hashlib.sha256(contract.encode_json(plan)).hexdigest()
    )
    assert coverage["expected_frames"] == list(range(40, 49))
    assert coverage["observed_frames"] == list(range(40, 45))
    assert coverage["missing_frames"] == list(range(45, 49))
    assert coverage["observation_counts"] == [
        {"frame": number, "count": 2 if number == 42 else 1 if number < 45 else 0}
        for number in range(40, 49)
    ]


def test_each_original_byte_object_is_parsed_once_and_inputs_are_not_mutated(
    monkeypatch,
):
    plan = generated_plan()
    raw = contract.encode_json(plan)
    documents = generated_documents(plan)
    originals = documents[:]
    actual_parse, calls = contract.planner.strict_json, []

    def parse_once(value):
        calls.append(value)
        return actual_parse(value)

    monkeypatch.setattr(contract.planner, "strict_json", parse_once)
    result = contract.validate_stream(raw, documents, "independent_a")
    assert calls == [value.decode("utf-8") for value in [raw, *documents]]
    assert documents == originals
    assert all(
        row["sha256"] == hashlib.sha256(original).hexdigest()
        for row, original in zip(result["documents"], originals)
    )


@pytest.mark.parametrize(
    "change",
    [
        "actor_bool",
        "actor_unknown",
        "visible_no_evidence",
        "actor_duplicate",
        "event_duplicate",
        "first_links",
    ],
)
def test_document_local_definitions_reject_missing_evidence_unknown_fields_and_collisions(
    change,
):
    plan = generated_plan()
    docs, _ = with_overlap_entities(plan, generated_documents(plan))
    doc = docs[0]
    if change == "actor_bool":
        doc["actors"][0]["evidence_frames"] = [True]
    elif change == "actor_unknown":
        doc["actors"][0]["global_id"] = "invented"
    elif change == "visible_no_evidence":
        doc["actors"][0]["evidence_frames"] = []
    elif change == "actor_duplicate":
        doc["actors"].append(copy.deepcopy(doc["actors"][0]))
    elif change == "event_duplicate":
        doc["events"].append(copy.deepcopy(doc["events"][0]))
    else:
        doc["event_correspondence"] = [
            {
                "current_event_id": "local-contact",
                "previous_event_id": "local-contact",
                "relation": "unresolved",
                "evidence_frames": [],
                "notes": "No predecessor exists",
            }
        ]
    with pytest.raises(ValueError):
        validate(plan, [contract.encode_json(doc)])


def test_multiple_event_mentions_of_one_interval_remain_separate_local_variants():
    plan = generated_plan()
    doc = contract.strict_json(generated_documents(plan)[0])
    doc["events"] = [
        event("variant-a", 1),
        event("variant-b", 1, family="drive", side="forehand"),
    ]
    doc["observations"][1]["contact"] = "observed"
    result = validate(plan, [contract.encode_json(doc)])
    assert result["summary"]["event_variants"] == 2
    assert result["documents"][0]["document"]["events"] == doc["events"]


def test_camera_view_strings_stay_document_local_and_no_global_view_is_inferred():
    plan = generated_plan()
    docs = [contract.strict_json(raw) for raw in generated_documents(plan)[:2]]
    for doc in docs:
        for row in doc["observations"]:
            row.update(camera="unchanged", camera_view="view-1")
    result = validate(plan, rebuild_chain(docs))
    assert result["summary"]["status"] == "incomplete"
    assert all(
        row["document"]["observations"][0]["camera_view"] == "view-1"
        for row in result["documents"]
    )
    assert "global_camera_map" not in result
