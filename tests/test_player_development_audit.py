"""Generated-only contracts for the sparse, prediction-blind development audit."""

from copy import deepcopy

import pytest
from badminton.player_audit import (
    box_iou,
    maximum_iou_matching,
    score_audit,
    validate_assessment,
    validate_manifest,
    validate_packet,
)

MANIFEST_HASH = "a" * 64
PACKET_HASH = "b" * 64


def person(actor="near", box=None):
    return {
        "actor": actor,
        "box": [10, 10, 30, 60] if box is None else box,
        "localization_eligible": True,
        "identity_eligible": actor is not None,
        "note": "Generated source-only evidence",
    }


def predicted(track=1, box=None):
    return {
        "track_id": track,
        "box": [10, 10, 30, 60] if box is None else box,
        "confidence": 0.8,
        "keypoints": [],
    }


@pytest.fixture
def documents():
    manifest = {
        "schema_version": 1,
        "source_sha256": "c" * 64,
        "clock_sha256": "d" * 64,
        "annotation_sha256": "e" * 64,
        "run_sha256": "f" * 64,
        "video_id": "generated-video",
        "annotation_revision": 1,
        "start_frame": 10,
        "end_frame": 15,
        "sample_frames": [10, 12, 14],
        "iou_threshold": 0.5,
    }
    packet = {
        "schema_version": 1,
        "manifest_sha256": MANIFEST_HASH,
        "source_sha256": manifest["source_sha256"],
        "clock_sha256": manifest["clock_sha256"],
        "video_id": manifest["video_id"],
        "width": 100,
        "height": 100,
        "samples": [
            {
                "frame": frame,
                "time_s": frame * 0.04,
                "image": f"source/frame-{frame}.png",
                "image_sha256": str(frame % 10) * 64,
            }
            for frame in manifest["sample_frames"]
        ],
    }
    assessment = {
        "schema_version": 1,
        "packet_sha256": PACKET_HASH,
        "session_id": "fresh-generated-session",
        "prediction_blind": True,
        "frames": [
            {
                "frame": frame,
                "scene": "court_view",
                "view_id": "view-a",
                "complete": True,
                "persons": [person()],
                "note": "Generated scene",
            }
            for frame in manifest["sample_frames"]
        ],
    }
    run = {
        "schema_version": 1,
        "video_id": manifest["video_id"],
        "video_sha256": manifest["source_sha256"],
        "stage": "players",
        "start_frame": 10,
        "end_frame": 15,
        "stride": 1,
        "processed_frames": 5,
        "annotation_revision": 1,
        "checkpoint_sha256": "1" * 64,
        "cut_frames": [],
        "camera_ranges": [{"start_frame": 10, "end_frame": 15, "scene": "unknown"}],
        "frames": [
            {
                "frame": frame,
                "time_s": frame * 0.04,
                "camera_segment_start_frame": 10,
                "scene": None,
                "players": [predicted()],
            }
            for frame in range(10, 15)
        ],
    }
    return manifest, packet, assessment, run


def score(documents):
    return score_audit(
        *documents, manifest_sha256=MANIFEST_HASH, packet_sha256=PACKET_HASH
    )


def test_perfect_sparse_sample_retains_provenance_and_arguments(documents):
    frozen = deepcopy(documents)
    result = score(documents)
    assert documents == frozen
    assert result["sample_frames"] == [10, 12, 14]
    totals = result["totals"]
    assert totals["sample_frames"] == totals["scored_frames"] == 3
    assert totals["source_person_observations"] == totals["matched_persons"] == 3
    assert totals["raw_predictions"] == totals["scored_predictions"] == 3
    assert totals["eligible_transitions"] == totals["same_id_transitions"] == 2
    assert result["iou_summary"] == {"count": 3, "minimum": 1, "maximum": 1, "mean": 1}
    assert result["source_actor_fragments"][0]["track_ids"] == [1]
    assert result["track_id_reuse"] == []
    # These are sparse transitions, not interpolated five-frame identity truth.
    assert len(result["frames"]) == 3
    assert len(result["transitions"]) == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.update(schema_version=True),
        lambda m: m.update(source_sha256="C" * 64),
        lambda m: m.update(clock_sha256="missing"),
        lambda m: m.update(run_sha256=None),
        lambda m: m.update(annotation_revision=True),
        lambda m: m.update(start_frame=-1),
        lambda m: m.update(end_frame=262),
        lambda m: m.update(sample_frames=[]),
        lambda m: m.update(sample_frames=[10, 10]),
        lambda m: m.update(sample_frames=[12, 10]),
        lambda m: m.update(sample_frames=[10, 15]),
        lambda m: m.update(sample_frames=[10, True]),
        lambda m: m.update(iou_threshold=0.6),
        lambda m: m.update(iou_threshold=float("nan")),
    ],
)
def test_manifest_rejects_unfrozen_or_unbounded_protocol(documents, mutate):
    mutate(documents[0])
    with pytest.raises(ValueError):
        validate_manifest(documents[0])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(manifest_sha256="0" * 64),
        lambda p: p.update(source_sha256="0" * 64),
        lambda p: p.update(clock_sha256="0" * 64),
        lambda p: p.update(video_id="other"),
        lambda p: p.update(width=False),
        lambda p: p["samples"].pop(),
        lambda p: p["samples"].reverse(),
        lambda p: p["samples"][1].update(frame=10),
        lambda p: p["samples"][1].update(time_s=0.4),
        lambda p: p["samples"][1].update(time_s=float("nan")),
        lambda p: p["samples"][0].update(image="../outside.png"),
        lambda p: p["samples"][0].update(image="C:\\source\\frame.png"),
        lambda p: p["samples"][0].update(image="/outside.png"),
        lambda p: p["samples"][1].update(image="source/frame-10.png"),
        lambda p: p["samples"][0].update(image_sha256="invalid"),
    ],
)
def test_packet_rejects_source_clock_receipt_and_sample_mismatches(documents, mutate):
    mutate(documents[1])
    with pytest.raises(ValueError):
        validate_packet(documents[0], documents[1], manifest_sha256=MANIFEST_HASH)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.update(packet_sha256="0" * 64),
        lambda a: a.update(prediction_blind=False),
        lambda a: a.update(session_id=""),
        lambda a: a["frames"].pop(),
        lambda a: a["frames"].reverse(),
        lambda a: a["frames"][0].update(scene="live"),
        lambda a: a["frames"][0].update(complete=None),
        lambda a: a["frames"][0]["persons"].append(person()),
        lambda a: a["frames"][0]["persons"][0].update(box=None),
        lambda a: a["frames"][0]["persons"][0].update(box=[10, 10, 10, 60]),
        lambda a: a["frames"][0]["persons"][0].update(box=[10, 10, 30, 101]),
        lambda a: a["frames"][0]["persons"][0].update(box=[10, 10, float("inf"), 60]),
        lambda a: a["frames"][0]["persons"][0].update(box=[True, 10, 30, 60]),
        lambda a: a["frames"][0]["persons"][0].update(actor=None),
        lambda a: a["frames"][0].update(view_id=None),
        lambda a: a["frames"][0]["persons"][0].update(localization_eligible=False),
        lambda a: a["frames"][0]["persons"][0].update(note=None),
    ],
)
def test_assessment_rejects_missing_malformed_or_conflicting_source_labels(
    documents, mutate
):
    mutate(documents[2])
    with pytest.raises(ValueError):
        validate_assessment(documents[1], documents[2], packet_sha256=PACKET_HASH)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(video_sha256="0" * 64),
        lambda r: r.update(video_id="wrong"),
        lambda r: r.update(annotation_revision=0),
        lambda r: r.update(processed_frames=4),
        lambda r: r.update(stride=2),
        lambda r: r.update(stage="shuttle"),
        lambda r: r.update(checkpoint_sha256="unrecorded"),
        lambda r: r.update(requires_tracking_rerun=True),
        lambda r: r["frames"].pop(),
        lambda r: r["frames"].reverse(),
        lambda r: r["frames"][1].update(frame=10),
        lambda r: r["frames"][2].update(time_s=0.49),
        lambda r: r["frames"][1].update(time_s=0.4),
        lambda r: r["frames"][1].update(time_s=float("nan")),
        lambda r: r["frames"][1].update(camera_segment_start_frame=11),
        lambda r: r["frames"][1]["players"].append(predicted()),
        lambda r: r["frames"][1]["players"][0].update(track_id=True),
        lambda r: r["frames"][1]["players"][0].update(track_id=-1),
        lambda r: r["frames"][1]["players"][0].update(track_id="1"),
        lambda r: r["frames"][1]["players"][0].pop("track_id"),
        lambda r: r["frames"][1]["players"][0].update(box=[30, 10, 10, 60]),
        lambda r: r["frames"][1]["players"][0].update(confidence=float("nan")),
        lambda r: r["frames"][1]["players"][0].update(confidence=1.1),
        lambda r: r.update(cut_frames=[11, 11]),
        lambda r: r.update(camera_ranges=[]),
        lambda r: r.update(known_preceding_timestamp_gaps=["11"]),
    ],
)
def test_run_rejects_incomplete_native_coverage_or_invalid_predictions(
    documents, mutate
):
    mutate(documents[3])
    with pytest.raises(ValueError):
        score(documents)


def test_matching_uses_global_optimum_instead_of_greedy_largest_overlap():
    source = [[0, 0, 10, 10], [3, 0, 13, 10]]
    predictions = [[1, 0, 11, 10], [0, 0, 8, 10]]
    result = maximum_iou_matching(source, predictions)
    assert [(m["person_index"], m["prediction_index"]) for m in result] == [
        (0, 1),
        (1, 0),
    ]
    assert sum(m["iou"] for m in result) == pytest.approx(0.8 + 2 / 3)


def test_matching_threshold_edges_and_deterministic_ties():
    source = [[0, 0, 10, 10]]
    assert box_iou(source[0], [0, 0, 5, 10]) == 0.5
    assert len(maximum_iou_matching(source, [[0, 0, 5, 10]])) == 1
    assert maximum_iou_matching(source, [[0, 0, 4.999, 10]]) == []
    tied = maximum_iou_matching(source * 2, source * 2)
    assert [(m["person_index"], m["prediction_index"]) for m in tied] == [
        (0, 0),
        (1, 1),
    ]
    assert maximum_iou_matching([], source) == []
    assert maximum_iou_matching(source, []) == []


def test_matching_capacity_is_explicit_not_silent_truncation(documents):
    with pytest.raises(ValueError, match="capacity"):
        maximum_iou_matching([[0, 0, 1, 1]] * 9, [])
    with pytest.raises(ValueError, match="capacity"):
        maximum_iou_matching([], [[0, 0, 1, 1]] * 129)
    documents[2]["frames"][0]["persons"] = [person(str(i)) for i in range(9)]
    with pytest.raises(ValueError, match="eight"):
        score(documents)


def test_unknown_people_and_unmatched_observations_keep_denominators(documents):
    source = documents[2]["frames"][0]
    source["persons"].extend(
        [
            {
                "actor": None,
                "box": None,
                "localization_eligible": False,
                "identity_eligible": False,
                "note": "Occluded unknown person",
            },
            person(None, [60, 10, 80, 60]),
        ]
    )
    documents[3]["frames"][0]["players"].append(predicted(None, [40, 10, 50, 60]))
    result = score(documents)
    totals = result["totals"]
    assert totals["source_person_observations"] == 5
    assert totals["unknown_actor_persons"] == 2
    assert totals["unlocalizable_persons"] == 1
    assert totals["source_localization_eligible_persons"] == 4
    assert totals["localization_eligible_persons"] == 4
    assert totals["matched_persons"] == 3
    assert totals["unmatched_eligible_persons"] == 1
    assert totals["unmatched_predictions"] == 1
    assert totals["predictions_without_track_id"] == 1
    assert len(result["frames"][0]["persons"]) == 3
    assert result["frames"][0]["unmatched_prediction_indices"] == [1]
    assert "false_positives" not in totals


@pytest.mark.parametrize(
    "scene,complete",
    [("court_view", False), ("unknown", True), ("replay", True), ("non_play", True)],
)
def test_incomplete_or_excluded_frames_preserve_raw_denominators(
    documents, scene, complete
):
    documents[2]["frames"][1].update(scene=scene, complete=complete)
    result = score(documents)
    totals = result["totals"]
    assert totals["sample_frames"] == totals["source_person_observations"] == 3
    assert totals["scored_frames"] == 2
    assert totals["unscored_predictions"] == 1
    assert totals["matched_persons"] == 2
    assert totals["unmatched_predictions"] == 0
    assert totals["eligible_transitions"] == 0
    assert totals["ineligible_transitions"] == 2
    assert result["frames"][1]["unscored_prediction_indices"] == [0]


def test_id_changes_fragmentation_and_reuse_are_distinct(documents):
    # Actor near uses 1, then 2, then 2; actor far uses 2, then 1, then 1.
    for index, source in enumerate(documents[2]["frames"]):
        source["persons"].append(person("far", [60, 10, 80, 60]))
        row = documents[3]["frames"][source["frame"] - 10]
        row["players"] = [
            predicted(1 if index == 0 else 2),
            predicted(2 if index == 0 else 1, [60, 10, 80, 60]),
        ]
    result = score(documents)
    assert result["totals"]["eligible_transitions"] == 4
    assert result["totals"]["changed_id_transitions"] == 2
    assert result["totals"]["same_id_transitions"] == 2
    assert len(result["track_id_reuse"]) == 2
    assert all(r["actors"] == ["far", "near"] for r in result["track_id_reuse"])
    assert all(a["distinct_track_ids"] == 2 for a in result["source_actor_fragments"])


@pytest.mark.parametrize("scene", ["replay", "unknown", "non_play"])
def test_intervening_reviewed_exclusion_breaks_only_affected_transition(
    documents, scene
):
    documents[3]["frames"][1]["scene"] = scene
    result = score(documents)
    assert result["totals"]["scored_frames"] == 3  # Exclusion is between samples.
    assert result["totals"]["eligible_transitions"] == 1
    assert result["transitions"][0]["ineligible_reasons"] == [
        "reviewed_scene_exclusion"
    ]
    assert result["transitions"][1]["status"] == "same_id"


def test_camera_cut_between_samples_breaks_transition_and_keeps_id_reuse_separate(
    documents,
):
    run = documents[3]
    run["cut_frames"] = [11]
    run["camera_ranges"] = [
        {"start_frame": 10, "end_frame": 11, "scene": "unknown"},
        {"start_frame": 11, "end_frame": 15, "scene": "unknown"},
    ]
    for row in run["frames"][1:]:
        row["camera_segment_start_frame"] = 11
    result = score(documents)
    assert result["totals"]["eligible_transitions"] == 1
    assert "camera_cut" in result["transitions"][0]["ineligible_reasons"]
    assert len(result["source_actor_fragments"]) == 2
    assert result["track_id_reuse"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_segment",
        "changed_view",
        "missing_actor",
        "unknown_track",
        "physical_gap",
    ],
)
def test_missing_or_unknown_context_never_bridges_adjacent_samples(documents, mutation):
    if mutation == "unknown_segment":
        documents[3]["frames"][1]["camera_segment_start_frame"] = None
    elif mutation == "changed_view":
        documents[2]["frames"][0]["view_id"] = "view-other"
    elif mutation == "missing_actor":
        documents[2]["frames"][0]["persons"] = []
    elif mutation == "unknown_track":
        documents[3]["frames"][0]["players"][0]["track_id"] = None
    elif mutation == "physical_gap":
        documents[3]["boundaries"] = [
            {"frame": 11, "reason": "timestamp_discontinuity"}
        ]
    result = score(documents)
    assert not result["transitions"][0]["eligible"]
    assert result["transitions"][1]["eligible"]
    assert result["totals"]["transition_candidates"] == 2


def test_missing_middle_sample_match_does_not_bridge_outer_samples(documents):
    documents[3]["frames"][2]["players"] = []
    result = score(documents)
    assert result["totals"]["unmatched_eligible_persons"] == 1
    assert result["totals"]["eligible_transitions"] == 0
    assert [(t["from_frame"], t["to_frame"]) for t in result["transitions"]] == [
        (10, 12),
        (12, 14),
    ]


def test_native_global_camera_segment_may_precede_window_start(documents):
    for row in documents[3]["frames"]:
        row["camera_segment_start_frame"] = 0
    assert score(documents)["totals"]["same_id_transitions"] == 2


def test_single_sample_and_empty_source_scene_remain_reportable(documents):
    manifest, packet, assessment, _run = documents
    manifest["sample_frames"] = [10]
    packet["samples"] = packet["samples"][:1]
    assessment["frames"] = assessment["frames"][:1]
    assessment["frames"][0]["persons"] = []
    result = score(documents)
    assert result["totals"]["source_person_observations"] == 0
    assert result["totals"]["unmatched_predictions"] == 1
    assert result["transitions"] == []
    assert result["iou_summary"]["mean"] is None
