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
