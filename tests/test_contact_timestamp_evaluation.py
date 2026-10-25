"""Generated source-clock cases; no video, model or scientific labels are used."""

from copy import deepcopy

import pytest
from badminton.contacts import MAX_FRAME_STEP_S
from badminton.evaluation import evaluate_contacts
from badminton.recognition_evaluation import evaluate_recognition


def clock(*, step=0.11, origin=12.5, gaps=None):
    steps = {20: step} if gaps is None else gaps
    times = [origin]
    for frame in range(1, 40):
        times.append(times[-1] + steps.get(frame, 0.04))
    return times


def event(name, frame, times, **changes):
    return {
        "id": name,
        "frame": frame,
        "time_s": times[frame],
        "kind": "shot",
        "status": "reviewed",
        "family": "drive",
        "side": "forehand",
        "player_id": "A",
    } | changes


def candidate(name, frame, times, **changes):
    return (
        event(name, frame, times)
        | {
            "status": "predicted",
            "hitter_hint": {"player_id": "A"},
        }
        | changes
    )


def window(start, end):
    return {
        "id": f"w-{start}-{end}",
        "start_frame": start,
        "end_frame": end,
        "scene": "live",
        "contacts_complete": True,
    }


def inputs(times, stage, *, events=None, candidates=None, windows=None):
    return (
        {"id": "generated", "sha256": "a" * 64, "frame_count": len(times)},
        {
            "revision": 3,
            "events": [event("before", 19, times)] if events is None else events,
            "review_windows": [window(0, 40)] if windows is None else windows,
        },
        {
            "video_id": "generated",
            "video_sha256": "a" * 64,
            "stage": stage,
            "run_id": "generated-run",
            "start_frame": 0,
            "end_frame": 40,
            "candidates": [candidate("after", 20, times)]
            if candidates is None
            else candidates,
        },
    )


@pytest.fixture(params=["contacts", "recognition"])
def evaluator(request):
    return request.param, (
        evaluate_contacts if request.param == "contacts" else evaluate_recognition
    )


def counts(result, stage):
    metrics = result["metrics" if stage == "contacts" else "complete_event"]
    return metrics["tp"], metrics["fp"], metrics["fn"]


@pytest.mark.parametrize(
    "step,separated",
    [
        (0.04, False),
        (MAX_FRAME_STEP_S - 1e-7, False),
        (MAX_FRAME_STEP_S, False),
        (MAX_FRAME_STEP_S + 0.5e-9, False),
        (MAX_FRAME_STEP_S + 2e-9, True),
        (0.11, True),
    ],
)
def test_source_step_threshold_preserves_point_miss_and_false_denominators(
    evaluator, step, separated
):
    stage, evaluate = evaluator
    times = clock(step=step)
    args = inputs(times, stage)
    original = deepcopy((args, times))
    result = evaluate(*args, native_timestamps=times)
    assert result["prediction_clock_status"] == "validated"
    assert counts(result, stage) == ((0, 1, 1) if separated else (1, 0, 0))
    coverage = result["coverage"]
    assert coverage["frame_ranges"] == ([[0, 20], [20, 40]] if separated else [[0, 40]])
    assert coverage["source_timestamp_gap_frames"] == ([20] if separated else [])
    assert coverage["camera_cut_frames"] == []
    assert coverage["camera_context_metadata"] == "unavailable"
    assert coverage["reviewed_frames"] == 40
    assert coverage["reviewed_event_ids"] == ["before"]
    assert coverage["evaluated_candidate_ids"] == ["after"]
    assert coverage["excluded_candidate_ids"] == []
    if stage == "contacts":
        assert result["tighter_tolerance"]["metrics"]["tp"] == int(step == 0.04)
        assert result["interval_coverage"]["matched_count"] == 0
        assert result["unmatched_event_ids"] == (["before"] if separated else [])
    else:
        assert result["family"]["per_class"]["drive"]["f1"] == (0 if separated else 1)
        assert result["hitter"]["correct_count"] == (0 if separated else 1)
        assert result["side"]["per_class"]["forehand"]["recall"] == (
            0 if separated else 1
        )
    assert (args, times) == original


def test_vfr_nonzero_origin_multiple_gaps_and_touching_windows(evaluator):
    stage, evaluate = evaluator
    times = clock(
        origin=100.25,
        gaps={
            frame: (0.11 if frame in (10, 20, 30) else 0.02 + frame % 3 * 0.01)
            for frame in range(1, 40)
        },
    )
    args = inputs(
        times,
        stage,
        events=[event(f"e-{f}", f, times) for f in (9, 10, 19, 20, 29, 30)],
        candidates=[candidate(f"p-{f}", f, times) for f in (9, 10, 19, 20, 29, 30)],
        windows=[window(0, 10), window(10, 20), window(18, 30), window(30, 40)],
    )
    result = evaluate(*args, native_timestamps=times)
    assert counts(result, stage) == (6, 0, 0)
    assert result["coverage"]["frame_ranges"] == [[0, 10], [10, 20], [20, 30], [30, 40]]
    assert result["coverage"]["source_timestamp_gap_frames"] == [10, 20, 30]
    frames = [f for a, b in result["coverage"]["frame_ranges"] for f in range(a, b)]
    assert frames == list(range(40))
    if stage == "contacts":
        assert result["interval_coverage"]["matched_count"] == 6
        assert result["tighter_tolerance"]["metrics"]["tp"] == 6


@pytest.mark.parametrize("evidence", [False, True])
@pytest.mark.parametrize("frame", [19, 20])
def test_cross_gap_interval_and_evidence_are_excluded_on_either_navigation_side(
    evaluator, evidence, frame
):
    stage, evaluate = evaluator
    times = clock()
    prefix = "contact_" if stage == "recognition" else ""
    changes = (
        {"context_start_frame": 18, "context_end_frame": 22}
        if evidence
        else {f"{prefix}start_frame": 19, f"{prefix}end_frame": 20}
    )
    args = inputs(
        times, stage, candidates=[candidate("crossing", frame, times, **changes)]
    )
    original = deepcopy(args)
    result = evaluate(*args, native_timestamps=times)
    assert counts(result, stage) == (0, 0, 1)
    assert result["coverage"]["reviewed_frames"] == 40
    assert result["coverage"]["evaluated_candidate_ids"] == []
    assert result["coverage"]["excluded_candidate_ids"] == ["crossing"]
    assert result["coverage"]["candidate_exclusions"] == [
        {
            "id": "crossing",
            "reason": ("evidence_context" if evidence else "contact_interval")
            + "_crosses_source_timestamp_gap",
        }
    ]
    if stage == "contacts":
        assert result["interval_coverage"]["candidate_count"] == 0
        assert result["interval_coverage"]["matched_count"] == 0
        assert result["tighter_tolerance"]["metrics"]["fn"] == 1
    else:
        assert result["family"]["confusion"]["no_contact"]["drive"] == 0
        assert result["unmatched_candidate_ids"] == []
        assert result["contact_inputs"] == {
            "reviewed_event_targets": 0,
            "proposal_targets": 0,
        }
    assert args == original


@pytest.mark.parametrize("frame,start,end", [(19, 18, 19), (20, 20, 21)])
def test_inclusive_interval_and_half_open_evidence_endpoints_stay_eligible(
    evaluator, frame, start, end
):
    stage, evaluate = evaluator
    times = clock()
    prefix = "contact_" if stage == "recognition" else ""
    proposal = candidate(
        "same-side",
        frame,
        times,
        **{
            f"{prefix}start_frame": start,
            f"{prefix}end_frame": end,
            "context_start_frame": start,
            "context_end_frame": end + 1,
        },
    )
    result = evaluate(
        *inputs(
            times,
            stage,
            candidates=[proposal],
            events=[event("same-side", frame, times)],
        ),
        native_timestamps=times,
    )
    assert result["coverage"]["evaluated_candidate_ids"] == ["same-side"]
    assert result["coverage"]["uncertain_candidate_count"] == 1
    if stage == "contacts":
        assert counts(result, stage) == (1, 0, 0)
        assert result["interval_coverage"]["matched_count"] == 1
    else:
        assert result["family"]["per_class"]["drive"]["tp"] == 1
        assert counts(result, stage) == (0, 1, 1)


@pytest.mark.parametrize("evidence", [False, True])
def test_camera_precedence_and_native_gap_metadata_are_distinct(evaluator, evidence):
    stage, evaluate = evaluator
    times = clock(gaps={20: 0.11, 30: 0.14})
    prefix = "contact_" if stage == "recognition" else ""
    changes = (
        {"context_start_frame": 18, "context_end_frame": 22}
        if evidence
        else {
            f"{prefix}start_frame": 19,
            f"{prefix}end_frame": 20,
        }
    )
    args = inputs(
        times, stage, candidates=[candidate("crossing", 19, times, **changes)]
    )
    args[2]["cut_frames"] = [10, 20]
    args[1]["camera_corrections"] = [{"frame": 30, "is_cut": False}]
    result = evaluate(*args, native_timestamps=times)
    assert result["coverage"]["frame_ranges"] == [[0, 10], [10, 20], [20, 30], [30, 40]]
    assert result["coverage"]["reviewed_frames"] == 40
    assert result["coverage"]["camera_cut_frames"] == [10, 20]
    assert result["coverage"]["source_timestamp_gap_frames"] == [20, 30]
    assert (
        result["coverage"]["candidate_exclusions"][0]["reason"]
        == ("evidence_context" if evidence else "contact_interval")
        + "_crosses_camera_cut"
    )


def test_negative_camera_review_cannot_remove_a_source_gap(evaluator):
    stage, evaluate = evaluator
    times = clock()
    args = inputs(times, stage)
    args[1]["camera_corrections"] = [{"frame": 20, "is_cut": False}]
    result = evaluate(*args, native_timestamps=times)
    assert counts(result, stage) == (0, 1, 1)
    assert result["coverage"]["source_timestamp_gap_frames"] == [20]
    assert result["coverage"]["camera_cut_frames"] == []
    assert result["coverage"]["camera_context_metadata"] == "unavailable"


@pytest.mark.parametrize(
    "events,candidates", [(False, False), (True, False), (False, True)]
)
def test_empty_negative_missing_and_false_cases_keep_coverage(
    evaluator, events, candidates
):
    stage, evaluate = evaluator
    times = clock()
    result = evaluate(
        *inputs(
            times,
            stage,
            events=[event("before", 19, times)] if events else [],
            candidates=[candidate("after", 20, times)] if candidates else [],
        ),
        native_timestamps=times,
    )
    assert result["coverage"]["reviewed_frames"] == 40
    assert result["coverage"]["reviewed_contacts"] == int(events)
    assert result["coverage"]["evaluated_candidates"] == int(candidates)
    if stage == "contacts":
        assert counts(result, stage) == (0, int(candidates), int(events))
    else:
        assert result["family"]["known_contact_count"] == int(events)
        assert result["family"]["confusion"]["no_contact"]["drive"] == int(candidates)


def test_one_to_one_same_side_matching_does_not_recover_cross_gap_credit(evaluator):
    stage, evaluate = evaluator
    times = clock()
    result = evaluate(
        *inputs(
            times,
            stage,
            events=[event("before", 19, times), event("after", 20, times)],
            candidates=[candidate("one", 20, times), candidate("two", 21, times)],
        ),
        native_timestamps=times,
    )
    assert counts(result, stage) == (1, 1, 1)
    if stage == "contacts":
        assert result["unmatched_event_ids"] == ["before"]
        assert len(result["unmatched_candidate_ids"]) == 1
    else:
        assert result["matches"][0]["candidate_id"] is None
        assert result["matches"][1]["candidate_id"] == "one"


def test_uncertain_reference_still_invalidates_complete_review(evaluator):
    stage, evaluate = evaluator
    times = clock()
    result = evaluate(
        *inputs(
            times,
            stage,
            events=[
                event(
                    "uncertain",
                    19,
                    times,
                    contact_start_frame=19,
                    contact_end_frame=20,
                )
            ],
        ),
        native_timestamps=times,
    )
    assert result["coverage"]["source_timestamp_gap_frames"] == [20]
    assert result["coverage"]["reviewed_frames"] == 0
    assert result["coverage"]["skipped_windows"] == [
        {
            "id": "w-0-40",
            "reason": "contact_timing_needs_adjudication",
        }
    ]


def test_unknown_assisted_abstained_and_missing_recognition_targets_remain_explicit():
    times = clock()
    events = [
        event("unknown", 4, times, family="unknown", side="unknown", player_id=None),
        event("assisted", 9, times, classification_run_id="old-model"),
        event("abstained", 19, times),
        event("missing", 30, times),
    ]
    proposals = [
        candidate("p-unknown", 4, times),
        candidate("p-assisted", 9, times),
        candidate("p-abstained", 19, times, status="abstained"),
    ]
    result = evaluate_recognition(
        *inputs(times, "recognition", events=events, candidates=proposals),
        native_timestamps=times,
    )
    assert result["coverage"]["reviewed_contacts"] == 4
    assert result["coverage"]["evaluated_candidates"] == 3
    assert result["labels"] == {
        "known_family_event_ids": ["abstained", "missing"],
        "unknown_family_event_ids": ["unknown"],
        "excluded_model_assisted_event_ids": ["assisted"],
    }
    assert result["family"]["confusion"]["drive"]["unanswered"] == 2
    assert result["family"]["confusion"]["no_contact"]["drive"] == 0
    assert result["family"]["coverage"] == 0
    assert counts(result, "recognition") == (0, 0, 2)


def test_no_clock_preserves_legacy_matching_without_inventing_source_barriers(
    evaluator,
):
    stage, evaluate = evaluator
    args = inputs(clock(), stage)
    before = deepcopy(args)
    result = evaluate(*args)
    assert counts(result, stage) == (1, 0, 0)
    assert result["prediction_clock_status"] == "unavailable"
    assert result["coverage"]["source_timestamp_gap_frames"] == []
    assert result["coverage"]["frame_ranges"] == [[0, 40]]
    assert args == before


@pytest.mark.parametrize("bad", [[], [0.0] * 40, [float("nan")] * 40, [True] * 40])
def test_invalid_native_clocks_are_rejected_without_mutation(evaluator, bad):
    stage, evaluate = evaluator
    args = inputs(clock(), stage)
    before = deepcopy(args)
    with pytest.raises(ValueError, match="source timestamp"):
        evaluate(*args, native_timestamps=bad)
    assert args == before


def test_source_hash_rejection_precedes_clock_or_candidate_parsing(evaluator):
    stage, evaluate = evaluator
    args = inputs(clock(), stage)
    args[2]["video_sha256"] = "b" * 64
    args[2]["candidates"] = None
    with pytest.raises(ValueError, match=r"[Ss]ource.*hash"):
        evaluate(*args, native_timestamps=[])


def test_bad_declared_time_cannot_be_hidden_by_gap_exclusion(evaluator):
    stage, evaluate = evaluator
    times = clock()
    args = inputs(times, stage)
    args[2]["candidates"][0].update(
        time_s=times[20] + 0.02, context_start_frame=18, context_end_frame=22
    )
    with pytest.raises(ValueError, match="does not match native source frame"):
        evaluate(*args, native_timestamps=times)


@pytest.mark.parametrize("evidence", [False, True])
def test_native_gap_reason_precedes_outside_reviewed_coverage(evaluator, evidence):
    stage, evaluate = evaluator
    times = clock()
    prefix = "contact_" if stage == "recognition" else ""
    changes = (
        {"context_start_frame": 18, "context_end_frame": 22}
        if evidence
        else {f"{prefix}start_frame": 19, f"{prefix}end_frame": 20}
    )
    result = evaluate(
        *inputs(
            times,
            stage,
            candidates=[candidate("crossing", 19, times, **changes)],
            windows=[window(0, 20), window(21, 40)],
        ),
        native_timestamps=times,
    )
    assert result["coverage"]["reviewed_frames"] == 39
    assert result["coverage"]["candidate_exclusions"] == [
        {
            "id": "crossing",
            "reason": ("evidence_context" if evidence else "contact_interval")
            + "_crosses_source_timestamp_gap",
        }
    ]


def test_scene_exclusion_keeps_precedence_over_native_gap(evaluator):
    stage, evaluate = evaluator
    times = clock()
    args = inputs(
        times,
        stage,
        candidates=[
            candidate(
                "crossing", 19, times, context_start_frame=18, context_end_frame=22
            )
        ],
    )
    args[1]["scene_ranges"] = [
        {
            "id": "replay",
            "start_frame": 20,
            "end_frame": 22,
            "scene": "replay",
        }
    ]
    result = evaluate(*args, native_timestamps=times)
    assert result["coverage"]["candidate_exclusions"] == [
        {
            "id": "crossing",
            "reason": "reviewed_scene_excludes_evidence",
        }
    ]
    assert result["coverage"]["scene_context_excluded_candidate_ids"] == ["crossing"]
    assert result["coverage"]["source_timestamp_gap_frames"] == [20]


def test_legacy_inferred_evidence_cannot_be_shortened_to_navigation_frame(evaluator):
    stage, evaluate = evaluator
    times = clock()
    args = inputs(
        times,
        stage,
        candidates=[
            candidate("legacy", 19, times, evidence_source="observed_trajectory")
        ],
    )
    before = deepcopy(args)
    result = evaluate(*args, native_timestamps=times)
    assert result["coverage"]["candidate_exclusions"] == [
        {
            "id": "legacy",
            "reason": "evidence_context_crosses_source_timestamp_gap",
        }
    ]
    assert counts(result, stage) == (0, 0, 1)
    assert args == before
