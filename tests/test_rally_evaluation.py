"""Generated source-clock boundary evaluation, without scientific reference data."""

from copy import deepcopy
from random import Random

import pytest
from badminton.calibration_context import effective_annotations
from badminton.rallies import context_signature
from badminton.rally_evaluation import evaluate_rallies


def window(start=0, end=40, **changes):
    return {
        "id": f"window-{start}",
        "start_frame": start,
        "end_frame": end,
        "scene": "live",
        "serves_complete": True,
        "rally_ends_complete": True,
    } | changes


def event(name, frame, kind="serve", **changes):
    return {"id": name, "frame": frame, "kind": kind, "status": "reviewed"} | changes


def candidate(name, frame, kind="serve", times=None, **changes):
    times = times or [i * 0.04 for i in range(40)]
    return {"id": name, "frame": frame, "kind": kind, "time_s": times[frame]} | changes


def bind(run, annotations):
    run["context_signature"] = context_signature(
        effective_annotations(annotations, run["court_context"]),
        run["context_start_frame"],
        run["context_end_frame"],
    )


def inputs(events=None, candidates=None, windows=None, mode="singles"):
    video = {"id": "source", "sha256": "a" * 64, "frame_count": 40, "mode": mode}
    annotations = {
        "revision": 9,
        "events": events or [],
        "review_windows": windows or [],
        "scene_ranges": [],
        "camera_corrections": [],
        "calibrations": [],
    }
    run = {
        "video_id": "source",
        "video_sha256": video["sha256"],
        "run_id": "saved-rallies",
        "stage": "rallies",
        "start_frame": 0,
        "end_frame": 40,
        "context_start_frame": 0,
        "context_end_frame": 40,
        "source_timestamps_validated": True,
        "cut_frames": [],
        "court_context": {"start_frame": 0, "end_frame": 40, "cut_frames": []},
        "candidates": candidates or [],
    }
    bind(run, annotations)
    return video, annotations, run, [i * 0.04 for i in range(40)]


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("kind", ["serve", "rally_end"])
def test_exact_positive_negative_coverage_and_input_immutability(mode, kind):
    args = inputs(
        [event("hit", 5, kind), event("miss", 15, kind, status="corrected")],
        [candidate("match", 6, kind), candidate("false", 30, kind)],
        [window()],
        mode,
    )
    original = deepcopy(args)
    result = evaluate_rallies(*args, tolerance_s=0.05)
    assert args == original
    assert result["stage"] == "rallies"
    assert result["video_id"] == "source"
    assert result["video_sha256"] == "a" * 64
    assert result["annotation_revision"] == 9
    assert result["run_id"] == "saved-rallies"
    report = result["kinds"][kind]
    assert report["status"] == "scored"
    assert report["coverage"]["reviewed_events"] == 2
    assert report["coverage"]["evaluated_candidates"] == 2
    score = report["representative_timing"]
    assert score["metrics"] == {
        "tp": 1,
        "fp": 1,
        "fn": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
    }
    assert score["matches"][0]["absolute_error_s"] == pytest.approx(0.04)
    assert score["unmatched_event_ids"] == ["miss"]
    assert score["unmatched_candidate_ids"] == ["false"]
    # Exact interval support needs identical frames even when point tolerance matches.
    assert report["interval_compatibility"]["matched_count"] == 0


@pytest.mark.parametrize("kind", ["serve", "rally_end"])
@pytest.mark.parametrize(
    "reference,prediction,counts",
    [(True, False, (0, 0, 1)), (False, True, (0, 1, 0)), (False, False, (0, 0, 0))],
)
def test_empty_sets_preserve_false_positives_misses_and_undefined_ratios(
    kind, reference, prediction, counts
):
    report = evaluate_rallies(
        *inputs(
            [event("reference", 5, kind)] if reference else [],
            [candidate("prediction", 5, kind)] if prediction else [],
            [window()],
        )
    )["kinds"][kind]
    assert report["status"] == "scored"
    metrics = report["representative_timing"]["metrics"]
    assert tuple(metrics[key] for key in ("tp", "fp", "fn")) == counts
    assert metrics["precision"] == (0 if prediction else None)
    assert metrics["recall"] == (0 if reference else None)
    assert metrics["f1"] == (0 if reference or prediction else None)


def test_old_contact_coverage_does_not_imply_either_boundary_completeness():
    old_window = window(contacts_complete=True)
    del old_window["serves_complete"]
    del old_window["rally_ends_complete"]
    args = inputs(
        [event("serve", 5), event("ending", 20, "rally_end")],
        [candidate("serve-p", 5), candidate("ending-p", 20, "rally_end")],
        [old_window],
    )
    for report in evaluate_rallies(*args)["kinds"].values():
        assert report["status"] == "needs_complete_live_review"
        assert report["representative_timing"] is None
        assert report["interval_compatibility"] is None
        assert len(report["coverage"]["excluded_event_ids"]) == 1
        assert len(report["coverage"]["excluded_candidate_ids"]) == 1


def test_boundary_completeness_is_independent_and_predicted_events_are_excluded():
    args = inputs(
        [event("predicted", 5, status="predicted"), event("shot", 8, "shot")],
        [candidate("false", 5)],
        [window(rally_ends_complete=False)],
    )
    result = evaluate_rallies(*args)
    serve = result["kinds"]["serve"]
    assert serve["representative_timing"]["metrics"]["fp"] == 1
    assert serve["coverage"]["excluded_event_ids"] == ["predicted"]
    assert result["kinds"]["rally_end"]["status"] == "needs_complete_live_review"


@pytest.mark.parametrize("scene", ["unknown", "replay"])
def test_non_live_windows_are_skipped_without_scoring_negatives(scene):
    report = evaluate_rallies(
        *inputs([event("a", 5)], [candidate("b", 5)], [window(scene=scene)])
    )["kinds"]["serve"]
    assert report["representative_timing"] is None
    assert report["coverage"]["skipped_windows"] == [
        {"id": "window-0", "reason": "scene_is_not_live"}
    ]


@pytest.mark.parametrize("scene", ["unknown", "replay", "non_play"])
def test_conflicting_reviewed_scene_blocks_entire_window(scene):
    args = inputs([event("a", 5)], [candidate("b", 5)], [window()])
    args[1]["scene_ranges"] = [
        {"id": "scene", "start_frame": 30, "end_frame": 35, "scene": scene}
    ]
    bind(args[2], args[1])
    report = evaluate_rallies(*args)["kinds"]["serve"]
    assert report["representative_timing"] is None
    assert (
        report["coverage"]["skipped_windows"][0]["reason"]
        == "reviewed_scene_excludes_window"
    )


def test_partial_run_cannot_truncate_reviewed_window():
    args = inputs([event("a", 5)], [candidate("b", 5)], [window()])
    args[2]["end_frame"] = 20
    report = evaluate_rallies(*args)["kinds"]["serve"]
    assert report["representative_timing"] is None
    assert report["coverage"]["reviewed_frames"] == 0
    assert (
        report["coverage"]["skipped_windows"][0]["reason"]
        == "run_does_not_cover_entire_window"
    )


@pytest.mark.parametrize(
    "kind,prefix", [("serve", "contact_"), ("rally_end", "terminal_")]
)
def test_uncertain_reference_keeps_inclusive_support_and_blocks_whole_window_timing(
    kind, prefix
):
    uncertain = event(
        "uncertain", 5, kind, **{prefix + "start_frame": 4, prefix + "end_frame": 8}
    )
    proposal = candidate(
        "interval", 10, kind, start_frame=8, end_frame=12, timing="uncertain_interval"
    )
    args = inputs([uncertain, event("other", 15, kind)], [proposal], [window()])
    report = evaluate_rallies(*args)["kinds"][kind]
    assert report["status"] == "needs_exact_boundary_timing"
    assert report["representative_timing"] is None
    assert report["coverage"]["reviewed_events"] == 2
    assert report["coverage"]["point_timing_event_count"] == 0
    assert report["coverage"]["uncertain_reference_event_ids"] == ["uncertain"]
    assert report["coverage"]["point_timing_skipped_windows"] == [
        {"id": "window-0", "reason": "boundary_timing_needs_adjudication"}
    ]
    support = report["interval_compatibility"]
    assert support["matched_count"] == 1
    match = support["matches"][0]
    assert match["event_interval_frames"] == match["candidate_interval_frames"] == 5
    assert match["overlap_start_frame"] == match["overlap_end_frame"] == 8
    assert support["unmatched_event_ids"] == ["other"]
    assert "f1" not in support and "accuracy" not in support


def test_only_uncertain_windows_are_removed_from_point_score():
    args = inputs(
        [
            event("unknown", 5, contact_start_frame=4, contact_end_frame=6),
            event("exact", 25),
        ],
        [candidate("unknown-p", 5), candidate("exact-p", 25)],
        [window(0, 20), window(20, 40)],
    )
    report = evaluate_rallies(*args)["kinds"]["serve"]
    assert report["status"] == "scored"
    assert report["coverage"]["reviewed_events"] == 2
    assert report["coverage"]["point_timing_event_count"] == 1
    assert report["representative_timing"]["metrics"]["tp"] == 1
    assert report["interval_compatibility"]["matched_count"] == 2


def test_uncertain_proposal_representative_is_navigation_not_physical_truth():
    args = inputs(
        [event("exact", 5)],
        [
            candidate(
                "interval", 5, start_frame=4, end_frame=8, timing="uncertain_interval"
            )
        ],
        [window()],
    )
    report = evaluate_rallies(*args)["kinds"]["serve"]
    assert report["representative_timing"]["metrics"]["tp"] == 1
    assert "navigation" in report["representative_timing"]["meaning"]
    assert report["coverage"]["uncertain_candidate_ids"] == ["interval"]


def test_general_interval_matching_uses_augmenting_paths_instead_of_greedy_steal():
    args = inputs(
        [
            event("flexible", 1, contact_start_frame=1, contact_end_frame=5),
            event("restricted", 2),
        ],
        [candidate("early", 2), candidate("late", 4)],
        [window()],
    )
    support = evaluate_rallies(*args)["kinds"]["serve"]["interval_compatibility"]
    assert support["matched_count"] == 2
    assert {(m["event_id"], m["candidate_id"]) for m in support["matches"]} == {
        ("flexible", "late"),
        ("restricted", "early"),
    }


def test_generated_interval_matching_agrees_with_exhaustive_assignment_oracle():
    def maximum(events, candidates):
        if not events:
            return 0
        first, *rest = events
        choices = [maximum(rest, candidates)]
        for index, other in enumerate(candidates):
            if max(first[0], other[0]) <= min(first[1], other[1]):
                choices.append(
                    1 + maximum(rest, candidates[:index] + candidates[index + 1 :])
                )
        return max(choices)

    rng = Random(256)
    for _ in range(80):
        event_ranges = [sorted(rng.sample(range(1, 15), 2)) for _ in range(4)]
        candidate_ranges = [sorted(rng.sample(range(1, 15), 2)) for _ in range(4)]
        args = inputs(
            [
                event(f"e-{i}", a, contact_start_frame=a, contact_end_frame=b)
                for i, (a, b) in enumerate(event_ranges)
            ],
            [
                candidate(f"c-{i}", a, start_frame=a, end_frame=b)
                for i, (a, b) in enumerate(candidate_ranges)
            ],
            [window()],
        )
        support = evaluate_rallies(*args)["kinds"]["serve"]["interval_compatibility"]
        assert support["matched_count"] == maximum(event_ranges, candidate_ranges)
        assert (
            len({m["event_id"] for m in support["matches"]}) == support["matched_count"]
        )
        assert (
            len({m["candidate_id"] for m in support["matches"]})
            == support["matched_count"]
        )


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"start_frame": "0", "end_frame": 40},
        {"start_frame": 1, "end_frame": 40},
        {"start_frame": 0, "end_frame": 41},
        {"start_frame": 0, "end_frame": 40, "automatic_calibrations": [None]},
        {"start_frame": 0, "end_frame": 40, "cut_frames": [None]},
    ],
)
def test_malformed_nested_court_context_is_rejected(context):
    args = inputs(windows=[window()])
    args[2]["court_context"] = context
    with pytest.raises(ValueError):
        evaluate_rallies(*args)


def test_point_matching_maximizes_cardinality_before_error():
    args = inputs(
        [event("a", 2), event("b", 4)],
        [candidate("early", 0), candidate("late", 3)],
        [window()],
    )
    score = evaluate_rallies(*args, tolerance_s=0.09)["kinds"]["serve"][
        "representative_timing"
    ]
    assert score["metrics"]["tp"] == 2
    assert [(m["event_id"], m["candidate_id"]) for m in score["matches"]] == [
        ("a", "early"),
        ("b", "late"),
    ]


@pytest.mark.parametrize("boundary", ["camera", "source_gap", "unreviewed_gap"])
def test_point_matching_never_crosses_context_or_coverage_gap(boundary):
    args = inputs([event("before", 19)], [candidate("after", 20)], [window()])
    if boundary == "camera":
        args[2]["cut_frames"] = [20]
        args[2]["court_context"]["cut_frames"] = [20]
    elif boundary == "source_gap":
        args[3][20:] = [t + 0.2 for t in args[3][20:]]
        args[2]["candidates"][0]["time_s"] = args[3][20]
    else:
        args[1]["review_windows"] = [window(0, 20), window(21, 40)]
        args[2]["candidates"][0] = candidate("after", 21)
    report = evaluate_rallies(*args, tolerance_s=0.5)
    assert report["kinds"]["serve"]["representative_timing"]["metrics"] == {
        "tp": 0,
        "fp": 1,
        "fn": 1,
        "precision": 0,
        "recall": 0,
        "f1": 0,
    }
    if boundary == "source_gap":
        assert report["source_timestamp_gap_frames"] == [20]


@pytest.mark.parametrize("crossing", ["reference", "candidate"])
def test_intervals_crossing_camera_boundary_are_explicitly_excluded(crossing):
    args = inputs([event("a", 19)], [candidate("b", 19)], [window()])
    args[2]["cut_frames"] = [20]
    args[2]["court_context"]["cut_frames"] = [20]
    if crossing == "reference":
        args[1]["events"][0].update(contact_start_frame=18, contact_end_frame=20)
    else:
        args[2]["candidates"][0].update(start_frame=18, end_frame=20)
    report = evaluate_rallies(*args)["kinds"]["serve"]
    if crossing == "reference":
        assert report["representative_timing"] is None
        assert (
            report["coverage"]["skipped_windows"][0]["reason"]
            == "reference_interval_crosses_coverage_or_context"
        )
    else:
        assert report["coverage"]["excluded_candidate_ids"] == ["b"]
        assert report["representative_timing"]["metrics"]["fn"] == 1


def test_half_open_coverage_and_crossing_reference_never_hide_unknowns():
    args = inputs(
        [event("left", 10, contact_start_frame=9, contact_end_frame=11)],
        [],
        [window(10, 20)],
    )
    report = evaluate_rallies(*args)["kinds"]["serve"]
    assert report["status"] == "needs_complete_live_review"
    assert report["coverage"]["excluded_event_ids"] == ["left"]
    args = inputs(
        [event("outside", 20)], [candidate("outside-p", 20)], [window(10, 20)]
    )
    report = evaluate_rallies(*args)["kinds"]["serve"]
    assert report["coverage"]["reviewed_events"] == 0
    assert report["coverage"]["evaluated_candidates"] == 0


def test_vfr_source_timestamps_determine_error_without_fps_conversion():
    args = inputs([event("a", 1)], [], [window()])
    args[0]["fps"] = 1000  # Deliberately unrelated to the native clock.
    args[3][:] = [sum(0.01 if j % 2 else 0.06 for j in range(i)) for i in range(40)]
    args[2]["candidates"] = [candidate("b", 3, times=args[3])]
    score = evaluate_rallies(*args, tolerance_s=0.07)["kinds"]["serve"][
        "representative_timing"
    ]
    assert score["metrics"]["tp"] == 1
    assert score["mean_absolute_error_s"] == pytest.approx(0.07)


@pytest.mark.parametrize(
    "field,value",
    [
        ("video_id", "other"),
        ("stage", "contacts"),
        ("video_sha256", "b" * 64),
        ("source_timestamps_validated", False),
        ("source_timestamps_validated", 1),
        ("requires_proposal_rerun", True),
        ("requires_tracking_rerun", True),
        ("start_frame", -1),
        ("end_frame", 41),
        ("end_frame", True),
        ("context_start_frame", 1),
        ("context_end_frame", 39),
        ("context_signature", {}),
        ("court_context", None),
        ("court_context", []),
        ("candidates", None),
        ("cut_frames", [40]),
        ("cut_frames", [True]),
    ],
)
def test_mismatched_or_malformed_run_is_rejected(field, value):
    args = inputs(windows=[window()])
    args[2][field] = value
    with pytest.raises(ValueError):
        evaluate_rallies(*args)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", ""),
        ("kind", "shot"),
        ("kind", []),
        ("frame", True),
        ("frame", 40),
        ("time_s", float("nan")),
        ("time_s", float("inf")),
        ("time_s", -1),
        ("time_s", True),
        ("time_s", 0.3),
        ("start_frame", 6),
        ("end_frame", 4),
        ("start_frame", 3),
        ("start_time_s", 0.1),
        ("context_start_frame", 8),
    ],
)
def test_invalid_candidate_identity_bounds_or_time_are_rejected(field, value):
    args = inputs(candidates=[candidate("b", 5)], windows=[window()])
    args[2]["candidates"][0][field] = value
    with pytest.raises(ValueError):
        evaluate_rallies(*args)


def test_interval_times_and_optional_evidence_context_must_bind_to_source():
    args = inputs(
        candidates=[
            candidate(
                "b",
                5,
                start_frame=4,
                end_frame=6,
                start_time_s=0.16,
                end_time_s=0.24,
                context_start_frame=3,
                context_end_frame=8,
            )
        ],
        windows=[window()],
    )
    evaluate_rallies(*args)
    args[2]["candidates"][0]["end_time_s"] = 0.25
    with pytest.raises(ValueError, match="native source frame"):
        evaluate_rallies(*args)
    args[2]["candidates"][0]["end_time_s"] = 0.24
    args[2]["start_frame"] = 5
    with pytest.raises(ValueError, match="inside its run"):
        evaluate_rallies(*args)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "rejected"),
        ("frame", -1),
        ("time_s", 0.3),
        ("contact_start_frame", 4),
        ("terminal_start_frame", 5),
        ("contact_end_frame", 6),
        ("kind", []),
    ],
)
def test_malformed_reference_rejected(field, value):
    args = inputs([event("a", 5)], windows=[window()])
    args[1]["events"][0][field] = value
    with pytest.raises(ValueError):
        evaluate_rallies(*args)


@pytest.mark.parametrize("collection", ["events", "candidates", "review_windows"])
def test_duplicate_ids_are_rejected(collection):
    args = inputs([event("a", 5)], [candidate("b", 5)], [window()])
    owner = args[2] if collection == "candidates" else args[1]
    owner[collection].append(deepcopy(owner[collection][0]))
    with pytest.raises(ValueError, match="unique"):
        evaluate_rallies(*args)


@pytest.mark.parametrize(
    "invalid",
    [
        [0.0] * 40,
        [0.0],
        [i * 0.04 for i in range(39)] + [float("nan")],
        [True] + [i * 0.04 for i in range(1, 40)],
    ],
)
def test_invalid_or_incomplete_native_clock_is_rejected(invalid):
    args = inputs(windows=[window()])
    with pytest.raises(ValueError):
        evaluate_rallies(*args[:3], invalid)


@pytest.mark.parametrize("tolerance", [float("nan"), float("inf"), -0.1, True, "0.12"])
def test_invalid_tolerance_is_rejected(tolerance):
    with pytest.raises(ValueError):
        evaluate_rallies(*inputs(windows=[window()]), tolerance_s=tolerance)


@pytest.mark.parametrize(
    "windows",
    [
        [window(0, 20), window(19, 40)],
        [window(start_frame="0")],
        [window(), window(20, 30, start_frame=None)],
        [window(serves_complete=1)],
        [window(rally_ends_complete="true")],
        [window(scene="non_play")],
    ],
)
def test_malformed_review_coverage_is_rejected(windows):
    with pytest.raises(ValueError):
        evaluate_rallies(*inputs(windows=windows))


@pytest.mark.parametrize("changed", ["camera", "scene", "court"])
def test_changed_annotation_context_requires_new_proposals(changed):
    args = inputs(windows=[window()])
    if changed == "camera":
        args[1]["camera_corrections"] = [{"frame": 20, "is_cut": True}]
    elif changed == "scene":
        args[1]["scene_ranges"] = [
            {"start_frame": 20, "end_frame": 30, "scene": "live"}
        ]
    else:
        args[1]["calibrations"] = [
            {
                "start_frame": 0,
                "end_frame": 40,
                "corners": [
                    {"x": x, "y": y} for x, y in [(0, 0), (1, 0), (1, 1), (0, 1)]
                ],
            }
        ]
    with pytest.raises(ValueError, match="context changed"):
        evaluate_rallies(*args)
