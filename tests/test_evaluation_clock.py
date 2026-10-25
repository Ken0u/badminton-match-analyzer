"""Generated native clocks exercise evaluation without media or scientific labels."""

from copy import deepcopy

import pytest
from badminton.evaluation import evaluate_contacts
from badminton.recognition_evaluation import evaluate_recognition


def generated(stage="contacts"):
    # Deliberately irregular PTS with a nonzero source origin; FPS cannot map it.
    times = [0.11, 0.13, 0.18, 0.21, 0.29, 0.31, 0.36, 0.42]
    video = {"id": "generated", "sha256": "a" * 64, "frame_count": len(times)}
    event = {
        "id": "truth",
        "frame": 3,
        "time_s": times[3],
        "kind": "shot",
        "status": "reviewed",
        "family": "drive",
        "side": "forehand",
        "player_id": "A",
    }
    annotations = {
        "revision": 1,
        "events": [event],
        "review_windows": [
            {
                "id": "complete",
                "start_frame": 0,
                "end_frame": len(times),
                "contacts_complete": True,
                "scene": "live",
            }
        ],
    }
    candidate = {
        "id": "proposal",
        "frame": 3,
        "time_s": times[3],
        "kind": "shot",
        "status": "predicted",
        "family": "drive",
        "side": "forehand",
        "hitter_hint": {"player_id": "A"},
    }
    run = {
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "stage": stage,
        "run_id": "generated-run",
        "start_frame": 0,
        "end_frame": len(times),
        "candidates": [candidate],
    }
    evaluator = evaluate_contacts if stage == "contacts" else evaluate_recognition
    return evaluator, video, annotations, run, times


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
def test_vfr_clock_validates_without_mutation_and_keeps_legacy_metrics(stage):
    evaluator, video, annotations, run, times = generated(stage)
    before = deepcopy((video, annotations, run, times))
    legacy = evaluator(video, annotations, run, 0.001)
    checked = evaluator(video, annotations, run, 0.001, native_timestamps=tuple(times))
    assert legacy.pop("prediction_clock_status") == "unavailable"
    assert checked.pop("prediction_clock_status") == "validated"
    assert checked == legacy
    assert checked["coverage"]["reviewed_contacts"] == 1
    if stage == "contacts":
        assert checked["metrics"]["f1"] == 1
    else:
        assert checked["complete_event"]["f1"] == 1
    assert (video, annotations, run, times) == before
    assert "start_time_s" not in run["candidates"][0]


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize(
    "bad",
    [[], [0.0] * 8, list(range(7)), list(range(9)), "01234567", {}, 0, iter(range(8))],
)
def test_clock_requires_complete_ordered_sequence_even_without_labels(stage, bad):
    evaluator, video, annotations, run, _ = generated(stage)
    annotations["events"] = []
    annotations["review_windows"] = []
    run["candidates"] = []
    with pytest.raises(ValueError, match="Native source timestamps"):
        evaluator(video, annotations, run, native_timestamps=bad)


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize(
    "bad", [True, False, None, "0.18", float("nan"), float("inf"), -1, 1j]
)
def test_clock_rejects_invalid_time_values(stage, bad):
    evaluator, video, annotations, run, times = generated(stage)
    times[2] = bad
    with pytest.raises(ValueError, match="Native source timestamp"):
        evaluator(video, annotations, run, native_timestamps=times)


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("replacement", [0.13, 0.12])
def test_clock_rejects_duplicates_and_reversed_pts(stage, replacement):
    evaluator, video, annotations, run, times = generated(stage)
    times[2] = replacement
    with pytest.raises(ValueError, match="strictly increasing"):
        evaluator(video, annotations, run, native_timestamps=times)


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("target", ["reference", "candidate"])
@pytest.mark.parametrize(
    "bad", [True, None, "0.21", float("nan"), float("inf"), -1, 0.36]
)
def test_representative_times_must_match_native_ordinal(stage, target, bad):
    evaluator, video, annotations, run, times = generated(stage)
    item = annotations["events"][0] if target == "reference" else run["candidates"][0]
    item["time_s"] = bad
    with pytest.raises(ValueError, match="time_s"):
        evaluator(video, annotations, run, native_timestamps=times)


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("target", ["reference", "candidate"])
@pytest.mark.parametrize("field", ["frame", "time_s"])
def test_missing_representative_fields_raise_value_error(stage, target, field):
    evaluator, video, annotations, run, times = generated(stage)
    item = annotations["events"][0] if target == "reference" else run["candidates"][0]
    del item[field]
    with pytest.raises(ValueError, match=r"native source frame|time_s"):
        evaluator(video, annotations, run, native_timestamps=times)


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("target", ["reference", "candidate"])
@pytest.mark.parametrize("bad", [True, None, 3.0, "3", -1, 8])
def test_representative_ordinals_are_native_integers(stage, target, bad):
    evaluator, video, annotations, run, times = generated(stage)
    item = annotations["events"][0] if target == "reference" else run["candidates"][0]
    item["frame"] = bad
    with pytest.raises(ValueError, match="native source frame"):
        evaluator(video, annotations, run, native_timestamps=times)


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("target", ["reference", "candidate"])
@pytest.mark.parametrize("bounds", [(True, 4), (2, 8), (4, 2), (2, None), (2.0, 4)])
def test_interval_bounds_require_paired_inclusive_native_ordinals(
    stage, target, bounds
):
    evaluator, video, annotations, run, times = generated(stage)
    item = annotations["events"][0] if target == "reference" else run["candidates"][0]
    prefix = "contact_" if target == "reference" or stage == "recognition" else ""
    item.update({prefix + "start_frame": bounds[0], prefix + "end_frame": bounds[1]})
    with pytest.raises(ValueError, match="native source frame"):
        evaluator(video, annotations, run, native_timestamps=times)


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("target", ["reference", "candidate"])
def test_valid_inclusive_interval_times_keep_uncertainty_and_original_metadata(
    stage, target
):
    evaluator, video, annotations, run, times = generated(stage)
    item = annotations["events"][0] if target == "reference" else run["candidates"][0]
    prefix = "contact_" if target == "reference" or stage == "recognition" else ""
    item.update({prefix + "start_frame": 2, prefix + "end_frame": 4})
    time_prefix = "contact_" if target == "reference" else ""
    item[time_prefix + "start_time_s"] = times[2]
    item[time_prefix + "end_time_s"] = times[4]
    before = deepcopy((annotations, run, times))
    result = evaluator(video, annotations, run, native_timestamps=times)
    assert result["prediction_clock_status"] == "validated"
    if target == "reference":
        assert result["status"] == "needs_complete_live_review"
        assert (
            result["coverage"]["skipped_windows"][0]["reason"]
            == "contact_timing_needs_adjudication"
        )
    else:
        assert result["coverage"]["uncertain_candidate_count"] == 1
        if stage == "recognition":
            assert result["complete_event"]["tp"] == 0
        else:
            assert result["interval_coverage"]["matched_count"] == 1
    assert (annotations, run, times) == before


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("target", ["reference", "candidate"])
@pytest.mark.parametrize("endpoint", ["start", "end"])
@pytest.mark.parametrize("bad", [True, "0.18", float("nan"), -1, 0.19])
def test_optional_interval_times_bind_to_inclusive_source_bounds(
    stage, target, endpoint, bad
):
    evaluator, video, annotations, run, times = generated(stage)
    reference = target == "reference"
    item = annotations["events"][0] if reference else run["candidates"][0]
    prefix = "contact_" if reference or stage == "recognition" else ""
    item.update({prefix + "start_frame": 2, prefix + "end_frame": 4})
    time_prefix = "contact_" if reference else ""
    item[time_prefix + "start_time_s"] = times[2]
    item[time_prefix + "end_time_s"] = times[4]
    item[time_prefix + endpoint + "_time_s"] = bad
    with pytest.raises(ValueError, match=endpoint + "_time_s"):
        evaluator(video, annotations, run, native_timestamps=times)


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("error,accepted", [(0.00001, True), (0.00003, False)])
def test_serialization_tolerance_is_fixed_and_inputs_are_not_rewritten(
    stage, error, accepted
):
    evaluator, video, annotations, run, times = generated(stage)
    candidate = run["candidates"][0]
    candidate.update(
        time_s=times[3] + error,
        start_time_s=times[3] + error,
        end_time_s=times[3] + error,
    )
    before = deepcopy((annotations, run, times))
    if accepted:
        result = evaluator(video, annotations, run, 0, native_timestamps=times)
        assert result["prediction_clock_status"] == "validated"
        if stage == "contacts":
            assert result["metrics"]["tp"] == 0  # Validation never normalizes times.
        else:
            assert result["family"]["answered_contact_count"] == 0
    else:
        with pytest.raises(ValueError, match="does not match native source frame"):
            evaluator(video, annotations, run, 10, native_timestamps=times)
    assert (annotations, run, times) == before


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("exclusion", ["no_labels", "scene", "camera", "review_gap"])
def test_all_proposals_are_validated_before_domain_exclusion(stage, exclusion):
    evaluator, video, annotations, run, times = generated(stage)
    candidate = run["candidates"][0]
    if exclusion == "no_labels":
        annotations["events"] = []
        annotations["review_windows"] = []
    elif exclusion == "scene":
        annotations["scene_ranges"] = [
            {"id": "replay", "start_frame": 2, "end_frame": 5, "scene": "replay"}
        ]
    elif exclusion == "camera":
        run["cut_frames"] = [4]
        prefix = "contact_" if stage == "recognition" else ""
        candidate.update({prefix + "start_frame": 3, prefix + "end_frame": 4})
    else:
        annotations["review_windows"][0]["end_frame"] = 3
    candidate["time_s"] = times[6]
    with pytest.raises(ValueError, match="does not match native source frame 3"):
        evaluator(video, annotations, run, native_timestamps=times)


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("status", ["reviewed", "corrected"])
def test_references_outside_scoring_coverage_are_checked(stage, status):
    evaluator, video, annotations, run, times = generated(stage)
    annotations["events"][0].update(status=status, time_s=times[6])
    annotations["review_windows"] = []
    with pytest.raises(ValueError, match="Reviewed contact time_s"):
        evaluator(video, annotations, run, native_timestamps=times)


@pytest.mark.parametrize("stage", ["contacts", "recognition"])
@pytest.mark.parametrize("context", ["camera", "gap", "uncertainty", "absent_hash"])
def test_clock_validation_preserves_existing_comparison_domain(stage, context):
    evaluator, video, annotations, run, times = generated(stage)
    candidate = run["candidates"][0]
    if context == "camera":
        run["cut_frames"] = [4]
        candidate.update(frame=4, time_s=times[4])
    elif context == "gap":
        annotations["review_windows"][0]["end_frame"] = 3
    elif context == "uncertainty":
        prefix = "contact_" if stage == "recognition" else ""
        candidate.update({prefix + "start_frame": 2, prefix + "end_frame": 4})
    elif stage == "contacts":
        del run["video_sha256"]
    else:
        # Recognition has always required its explicit source hash.
        run["candidates"] = []
    legacy = evaluator(video, annotations, run)
    checked = evaluator(video, annotations, run, native_timestamps=times)
    legacy.pop("prediction_clock_status")
    checked.pop("prediction_clock_status")
    assert checked == legacy
    if context == "camera":
        assert checked["coverage"]["reviewed_frames"] == len(times)
        if stage == "contacts":
            assert checked["metrics"]["fp"] == checked["metrics"]["fn"] == 1


@pytest.mark.parametrize("label_kind", ["unknown", "assisted", "abstained", "missing"])
def test_recognition_keeps_unknown_assisted_abstention_and_missing_denominators(
    label_kind,
):
    evaluator, video, annotations, run, times = generated("recognition")
    if label_kind == "unknown":
        annotations["events"][0]["family"] = "unknown"
    elif label_kind == "assisted":
        annotations["events"][0]["classification_run_id"] = "previous-model"
    elif label_kind == "abstained":
        run["candidates"][0]["status"] = "abstained"
    else:
        run["candidates"] = []
    legacy = evaluator(video, annotations, run)
    checked = evaluator(video, annotations, run, native_timestamps=times)
    legacy.pop("prediction_clock_status")
    checked.pop("prediction_clock_status")
    assert checked == legacy
    assert checked["coverage"]["reviewed_contacts"] == 1
    if label_kind in ("abstained", "missing"):
        assert checked["family"]["per_class"]["drive"]["fn"] == 1
        assert checked["complete_event"]["fn"] == 1
