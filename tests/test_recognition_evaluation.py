import copy

import pytest
from badminton.recognition_evaluation import evaluate_recognition


def fixture():
    video = {"id": "v", "sha256": "a" * 64, "frame_count": 100}
    events = [
        {
            "id": "one",
            "frame": 10,
            "time_s": 0.4,
            "kind": "shot",
            "family": "drive",
            "side": "forehand",
            "player_id": "A",
            "status": "reviewed",
        },
        {
            "id": "two",
            "frame": 40,
            "time_s": 1.6,
            "kind": "shot",
            "family": "smash",
            "side": "backhand",
            "player_id": "B",
            "status": "reviewed",
        },
    ]
    doc = {
        "revision": 3,
        "events": events,
        "review_windows": [
            {
                "id": "w",
                "start_frame": 0,
                "end_frame": 100,
                "scene": "live",
                "contacts_complete": True,
            }
        ],
    }
    run = {
        "stage": "recognition",
        "video_id": "v",
        "video_sha256": "a" * 64,
        "run_id": "r",
        "start_frame": 0,
        "end_frame": 100,
        "candidates": [
            {
                "id": "p1",
                "frame": 10,
                "time_s": 0.4,
                "kind": "shot",
                "family": "drive",
                "side": "unknown",
                "status": "predicted",
                "event_id": "one",
                "hitter_hint": {"player_id": "A"},
            },
            {
                "id": "p2",
                "frame": 40,
                "time_s": 1.6,
                "status": "abstained",
                "event_id": "two",
            },
            {
                "id": "p3",
                "frame": 80,
                "time_s": 3.2,
                "kind": "shot",
                "family": "drive",
                "side": "unknown",
                "status": "predicted",
                "hitter_hint": {"player_id": "B"},
            },
        ],
    }
    return video, doc, run


def test_family_scoring_penalizes_abstentions_and_spurious_contacts_without_claiming_six_classes():
    result = evaluate_recognition(*fixture())
    assert result["family"]["coverage"] == 0.5
    drive = result["family"]["per_class"]["drive"]
    assert (drive["tp"], drive["fp"], drive["fn"]) == (1, 1, 0)
    assert drive["precision"] == 0.5 and drive["f1"] == pytest.approx(2 / 3)
    assert result["family"]["macro_f1_supported"] == pytest.approx(1 / 3)
    assert result["family"]["macro_f1_all_six"] is None
    assert result["family"]["confusion"]["smash"]["unanswered"] == 1
    assert result["side"]["balanced_accuracy"] == 0
    assert result["hitter"]["accuracy_including_unanswered"] == 0.5
    assert result["complete_event"] == {
        "tp": 0,
        "fp": 0,
        "fn": 2,
        "precision": None,
        "recall": 0,
        "f1": 0,
    }
    assert result["contact_inputs"] == {
        "reviewed_event_targets": 2,
        "proposal_targets": 1,
    }


def test_model_assisted_labels_and_unknown_truth_do_not_become_self_accuracy_or_false_positives():
    video, doc, run = fixture()
    doc["events"][0]["classification_run_id"] = "a-previous-model"
    doc["events"][1]["family"] = "unknown"
    run["candidates"] = run["candidates"][:2]
    result = evaluate_recognition(video, doc, run)
    assert result["status"] == "needs_independent_family_labels"
    assert result["labels"]["excluded_model_assisted_event_ids"] == ["one"]
    assert result["labels"]["unknown_family_event_ids"] == ["two"]
    assert result["family"]["macro_f1_supported"] is None
    assert result["family"]["coverage"] is None
    assert result["complete_event"] is None
    assert all(v["fp"] == 0 for v in result["family"]["per_class"].values())


@pytest.mark.parametrize(
    "change,reason",
    [
        ("replay", "scene_is_not_live"),
        ("incomplete", "contacts_not_exhaustively_reviewed"),
        ("interval", "contact_timing_needs_adjudication"),
        ("partial", "run_does_not_cover_entire_window"),
    ],
)
def test_recognition_uses_exhaustive_live_timing_coverage_gates(change, reason):
    video, doc, run = fixture()
    if change == "replay":
        doc["review_windows"][0]["scene"] = "replay"
    if change == "incomplete":
        doc["review_windows"][0]["contacts_complete"] = False
    if change == "interval":
        doc["events"][0].update(contact_start_frame=9, contact_end_frame=11)
    if change == "partial":
        run["end_frame"] = 90
    result = evaluate_recognition(video, doc, run)
    assert result["status"] == "needs_complete_live_review"
    assert result["coverage"]["skipped_windows"][0]["reason"] == reason
    assert result["family"]["macro_f1_supported"] is None


def test_complete_event_requires_correct_hitter_side_family_and_resolved_timing():
    video, doc, run = fixture()
    run["candidates"] = run["candidates"][:1]
    run["candidates"][0]["side"] = "forehand"
    result = evaluate_recognition(video, doc, run)
    assert result["complete_event"]["tp"] == 1 and result["complete_event"]["fn"] == 1
    run["candidates"][0].update(contact_start_frame=9, contact_end_frame=11)
    result = evaluate_recognition(video, doc, run)
    assert result["complete_event"]["tp"] == 0
    assert result["coverage"]["uncertain_candidate_count"] == 1


def test_wrong_source_hash_and_duplicate_prediction_ids_are_rejected_and_inputs_remain_unchanged():
    video, doc, run = fixture()
    before = copy.deepcopy((video, doc, run))
    evaluate_recognition(video, doc, run)
    assert (video, doc, run) == before
    run["video_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="source video and hash"):
        evaluate_recognition(video, doc, run)
    run["video_sha256"] = video["sha256"]
    run["candidates"][1]["id"] = "p1"
    with pytest.raises(ValueError, match="unique"):
        evaluate_recognition(video, doc, run)


def one_contact(mode="singles"):
    video, doc, run = fixture()
    video["mode"] = mode
    doc["events"] = doc["events"][:1]
    doc["events"][0].update(frame=20, time_s=0.8)
    run["candidates"] = run["candidates"][:1]
    run["candidates"][0].update(frame=20, time_s=0.8, side="forehand")
    return video, doc, run


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("status", ["reviewed", "corrected"])
@pytest.mark.parametrize("cut_source", ["run", "court", "review"])
def test_cross_camera_matches_cannot_credit_family_side_hitter_or_complete_event(
    mode, status, cut_source
):
    video, doc, run = one_contact(mode)
    doc["events"][0].update(frame=19, time_s=0.76, status=status)
    if cut_source == "run":
        run["cut_frames"] = [20]
    elif cut_source == "court":
        run["calibration_signature"] = []
        run["court_context"] = {
            "start_frame": 0,
            "end_frame": 100,
            "cut_frames": [20],
        }
    else:
        doc["camera_corrections"] = [{"frame": 20, "is_cut": True}]
    before = copy.deepcopy((video, doc, run))
    result = evaluate_recognition(video, doc, run)
    assert (video, doc, run) == before
    assert result["coverage"]["frame_ranges"] == [[0, 20], [20, 100]]
    assert result["coverage"]["reviewed_frames"] == 100
    assert result["coverage"]["reviewed_event_ids"] == ["one"]
    assert result["coverage"]["evaluated_candidate_ids"] == ["p1"]
    drive = result["family"]["per_class"]["drive"]
    assert (drive["tp"], drive["fp"], drive["fn"]) == (0, 1, 1)
    assert result["family"]["confusion"]["drive"]["unanswered"] == 1
    assert result["family"]["confusion"]["no_contact"]["drive"] == 1
    assert result["side"]["confusion"]["forehand"]["unanswered"] == 1
    assert result["hitter"]["correct_count"] == 0
    assert result["hitter"]["known_contact_count"] == 1
    assert result["hitter"]["accuracy_including_unanswered"] == 0
    complete = result["complete_event"]
    assert (complete["tp"], complete["fp"], complete["fn"]) == (0, 1, 1)
    assert result["unmatched_candidate_ids"] == ["p1"]
    assert result["matches"][0]["candidate_id"] is None


@pytest.mark.parametrize("mode", ["singles", "doubles"])
def test_same_camera_matching_keeps_family_side_hitter_and_complete_event(mode):
    video, doc, run = one_contact(mode)
    doc["events"][0].update(frame=21, time_s=0.84)
    run["candidates"][0].update(frame=22, time_s=0.88)
    run["cut_frames"] = [20]
    result = evaluate_recognition(video, doc, run)
    assert result["family"]["per_class"]["drive"]["f1"] == 1
    assert result["side"]["confusion"]["forehand"]["forehand"] == 1
    assert result["hitter"]["accuracy_including_unanswered"] == 1
    assert result["complete_event"]["f1"] == 1
    assert result["unmatched_candidate_ids"] == []


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize(
    "excluded_context",
    ["cut_interval", "cut_evidence", "gap_interval", "gap_evidence", "scene"],
)
def test_recognition_uses_exact_contact_domain_without_reintroducing_excluded_proposals(
    mode, excluded_context
):
    video, doc, run = one_contact(mode)
    candidate = run["candidates"][0]
    if excluded_context.startswith("cut"):
        run["cut_frames"] = [20]
        if excluded_context == "cut_interval":
            candidate.update(contact_start_frame=19, contact_end_frame=21)
        else:
            candidate.update(context_start_frame=19, context_end_frame=22)
    elif excluded_context.startswith("gap"):
        doc["review_windows"] = [
            {**doc["review_windows"][0], "end_frame": 19},
            {**doc["review_windows"][0], "id": "w2", "start_frame": 20},
        ]
        if excluded_context == "gap_interval":
            candidate.update(contact_start_frame=18, contact_end_frame=21)
        else:
            candidate.update(context_start_frame=18, context_end_frame=22)
    else:
        doc["review_windows"][0].update(start_frame=20, end_frame=40)
        doc["scene_ranges"] = [
            {"id": "non-play", "start_frame": 18, "end_frame": 19, "scene": "non_play"}
        ]
        candidate.update(context_start_frame=18, context_end_frame=22)
    before = copy.deepcopy((video, doc, run))
    result = evaluate_recognition(video, doc, run)
    assert (video, doc, run) == before
    assert result["coverage"]["reviewed_event_ids"] == ["one"]
    assert result["coverage"]["evaluated_candidate_ids"] == []
    assert result["coverage"]["excluded_candidate_ids"] == ["p1"]
    assert result["contact_inputs"] == {
        "reviewed_event_targets": 0,
        "proposal_targets": 0,
    }
    drive = result["family"]["per_class"]["drive"]
    assert (drive["tp"], drive["fp"], drive["fn"]) == (0, 0, 1)
    assert result["family"]["confusion"]["drive"]["unanswered"] == 1
    assert result["family"]["confusion"]["no_contact"]["drive"] == 0
    assert result["hitter"]["accuracy_including_unanswered"] == 0
    complete = result["complete_event"]
    assert (complete["tp"], complete["fp"], complete["fn"]) == (0, 0, 1)
    assert result["unmatched_candidate_ids"] == []
    assert result["unmatched_prediction_class_counts"] == {}


@pytest.mark.parametrize("reference", ["unknown", "assisted"])
def test_unknown_or_assisted_truth_stays_separate_from_excluded_prediction(reference):
    video, doc, run = one_contact()
    if reference == "unknown":
        doc["events"][0]["family"] = "unknown"
    else:
        doc["events"][0]["classification_run_id"] = "prior-model"
    run["cut_frames"] = [20]
    run["candidates"].append(
        {
            **run["candidates"][0],
            "id": "excluded",
            "contact_start_frame": 19,
            "contact_end_frame": 21,
        }
    )
    result = evaluate_recognition(video, doc, run)
    assert result["coverage"]["evaluated_candidate_ids"] == ["p1"]
    assert result["coverage"]["excluded_candidate_ids"] == ["excluded"]
    assert result["family"]["known_contact_count"] == 0
    assert result["family"]["confusion"]["no_contact"]["drive"] == 0
    assert result["complete_event"] is None
    assert result["unmatched_candidate_ids"] == []
    assert result["labels"][
        "unknown_family_event_ids"
        if reference == "unknown"
        else "excluded_model_assisted_event_ids"
    ] == ["one"]
