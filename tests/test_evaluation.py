import json

import pytest
from badminton.cli import load_evaluation_run
from badminton.evaluation import evaluate_contacts, evaluate_shuttle
from badminton.storage import Store


def video():
    return {
        "id": "sample",
        "sha256": "a" * 64,
        "frame_count": 100,
        "width": 100,
        "height": 100,
        "mode": "singles",
    }


def window(start=0, end=20, **kwargs):
    return {
        "id": f"review-{start}",
        "start_frame": start,
        "end_frame": end,
        "contacts_complete": True,
        "scene": "live",
    } | kwargs


def event(name, frame, time, **kwargs):
    return {
        "id": name,
        "frame": frame,
        "time_s": time,
        "status": "reviewed",
        "kind": "shot",
    } | kwargs


def contact_run(candidates, start=0, end=100):
    return {
        "video_id": "sample",
        "stage": "contacts",
        "start_frame": start,
        "end_frame": end,
        "candidates": [
            {"id": name, "frame": frame, "time_s": time}
            for name, frame, time in candidates
        ],
        "run_id": "contact-job",
    }


def annotations(events=None, windows=None, points=None):
    return {
        "revision": 7,
        "events": events or [],
        "review_windows": windows or [],
        "shuttle_points": points or [],
    }


def test_contact_matching_maximizes_count_before_timing_error():
    # Matching nearest-first would give the second candidate to event a, losing b.
    labels = annotations([event("a", 2, 0.10), event("b", 4, 0.20)], [window()])
    run = contact_run([("first", 0, 0), ("second", 3, 0.12)])
    result = evaluate_contacts(video(), labels, run, tolerance_s=0.11)
    assert result["metrics"] == {
        "tp": 2,
        "fp": 0,
        "fn": 0,
        "precision": 1,
        "recall": 1,
        "f1": 1,
    }
    assert [(m["event_id"], m["candidate_id"]) for m in result["matches"]] == [
        ("a", "first"),
        ("b", "second"),
    ]
    assert result["mean_absolute_error_s"] == pytest.approx(0.09)
    assert result["tighter_tolerance"]["metrics"]["tp"] == 1
    assert result["annotation_revision"] == 7
    assert result["video_sha256"] == "a" * 64
    assert result["run_id"] == "contact-job"


def test_contact_matching_minimizes_error_and_uses_source_times():
    labels = annotations([event("a", 1, 1.0), event("b", 5, 2.0)], [window()])
    run = contact_run([("a", 2, 0.99), ("extra", 4, 1.9), ("b", 6, 2.01)])
    result = evaluate_contacts(video(), labels, run)
    assert [m["candidate_id"] for m in result["matches"]] == ["a", "b"]
    assert result["metrics"]["fp"] == 1
    assert result["mean_absolute_error_s"] == pytest.approx(0.01)
    assert result["unmatched_candidate_ids"] == ["extra"]
    # Frame difference is deliberately unrelated to time at an assumed FPS.
    result = evaluate_contacts(
        video(),
        annotations([event("vfr", 1, 0.8)], [window()]),
        contact_run([("vfr", 15, 0.84)]),
        tolerance_s=0.04,
    )
    assert result["metrics"]["tp"] == 1


def test_contact_scores_require_exhaustive_live_coverage_and_half_open_bounds():
    windows = [
        window(0, 10, contacts_complete=False),
        window(10, 20, scene="replay"),
        window(20, 40),  # Partly outside the run; never truncate its ground truth.
        window(40, 50),
    ]
    labels = annotations([event("a", 22, 1)], windows)
    run = contact_run([("a", 22, 1)], start=0, end=30)
    result = evaluate_contacts(video(), labels, run)
    assert result["status"] == "needs_complete_live_review"
    assert result["metrics"] is None
    assert len(result["coverage"]["skipped_windows"]) == 4
    result = evaluate_contacts(
        video(),
        annotations(
            [
                event("serve", 10, 0.4, kind="serve"),
                event("predicted", 11, 0.44, status="predicted"),
                event("end", 12, 0.48, kind="rally_end"),
                event("outside", 20, 0.8),
            ],
            [window(10, 20)],
        ),
        contact_run([("inside", 10, 0.4), ("end-exclusive", 20, 0.8)]),
    )
    assert result["metrics"]["tp"] == 1
    assert result["metrics"]["fp"] == result["metrics"]["fn"] == 0
    assert result["coverage"]["excluded_candidates"] == 1
    assert result["coverage"]["reviewed_contacts"] == 1


def test_empty_exhaustive_window_can_measure_false_positives():
    result = evaluate_contacts(
        video(), annotations(windows=[window()]), contact_run([("false", 5, 0.2)])
    )
    assert result["status"] == "scored"
    assert result["metrics"]["fp"] == 1
    assert result["metrics"]["precision"] == 0
    assert result["metrics"]["recall"] is None
    assert result["metrics"]["f1"] == 0


def test_contacts_never_match_across_unreviewed_gaps():
    result = evaluate_contacts(
        video(),
        annotations([event("a", 9, 0.36)], [window(0, 10), window(11, 20)]),
        contact_run([("b", 11, 0.44)]),
    )
    assert result["metrics"]["tp"] == 0
    assert result["metrics"]["fp"] == result["metrics"]["fn"] == 1


def point(frame, visible=True, x=0.5, y=0.5):
    return {
        "frame": frame,
        "visible": visible,
        "x": x if visible else None,
        "y": y if visible else None,
    }


def shuttle_run(predictions, start=0, end=100):
    return {
        "video_id": "sample",
        "stage": "shuttle",
        "start_frame": start,
        "end_frame": end,
        "frames": [
            {"frame": frame, "shuttle": {"visible": visible, "x": x, "y": y}}
            for frame, visible, x, y in predictions
        ],
    }


def test_shuttle_visibility_localization_and_missing_output_are_distinct():
    labels = annotations(
        points=[
            point(0),
            point(1),
            point(2),
            point(3, False),
            point(4, False),
            point(5),
            point(6, False),
            point(7, x=0, y=0),
        ]
    )
    run = shuttle_run(
        [
            (0, True, 50, 50),  # Exact localization.
            (1, True, 80, 80),  # Wrong localization is both FP and FN.
            (2, False, None, None),
            (3, True, 50, 50),  # Visible prediction against an invisible label.
            (4, False, None, None),
            (7, True, 0, 0),  # Zero coordinates are real positions.
        ]
    )
    result = evaluate_shuttle(video(), labels, run)
    assert result["metrics"] == {
        "tp": 2,
        "fp": 2,
        "fn": 3,
        "precision": 0.5,
        "recall": 0.4,
        "f1": pytest.approx(4 / 9),
        "true_negatives": 1,
        "wrong_localizations": 1,
        "correct_frame_fraction": 3 / 8,
    }
    assert result["visibility_metrics"]["tp"] == 3
    assert result["visibility_metrics"]["fn"] == 2
    assert result["coverage"]["missing_output_frames"] == 2
    assert result["coverage"]["missing_invisible_output_frames"] == 1
    assert result["tolerance_px"] == pytest.approx(0.005 * 100 * 2**0.5)


def test_shuttle_only_scores_labeled_frames_in_run():
    run = shuttle_run([(1, True, 50, 50), (2, True, 50, 50)], start=1, end=3)
    result = evaluate_shuttle(video(), annotations(points=[point(0), point(3)]), run)
    assert result["metrics"] is None
    assert result["status"] == "needs_shuttle_labels"
    assert result["coverage"]["excluded_labeled_frames"] == 2
    result = evaluate_shuttle(video(), annotations(points=[point(1)]), run)
    assert result["metrics"]["tp"] == 1
    assert result["metrics"]["fp"] == 0  # Unlabeled frame 2 is not a false positive.


def test_evaluation_rejects_wrong_source_stage_and_nonfinite_tolerance():
    with pytest.raises(ValueError, match="contacts run"):
        evaluate_contacts(video() | {"id": "other"}, annotations(), contact_run([]))
    with pytest.raises(ValueError, match="tolerance"):
        evaluate_contacts(video(), annotations(), contact_run([]), float("nan"))
    with pytest.raises(ValueError, match="tolerance"):
        evaluate_shuttle(video(), annotations(), shuttle_run([]), float("inf"))
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_shuttle(
            video(), annotations(), shuttle_run([(1, False, None, None)] * 2)
        )


def test_cli_loader_requires_completed_same_video_and_correct_artifact(tmp_path):
    store = Store(tmp_path)
    store.register(video())
    job = {"id": "job", "video_id": "sample", "kind": "contacts", "status": "running"}
    store.put_job(job)
    with pytest.raises(ValueError, match="Completed"):
        load_evaluation_run(store, "sample", "job", "contacts")
    job["status"] = "completed"
    store.put_job(job)
    with pytest.raises(ValueError, match="unavailable"):
        load_evaluation_run(store, "sample", "job", "contacts")
    path = tmp_path / "sample" / "runs" / "job.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(contact_run([])), encoding="utf-8")
    loaded = load_evaluation_run(store, "sample", "job", "contacts")
    assert loaded["run_id"] == "job"
    with pytest.raises(ValueError, match="Completed"):
        load_evaluation_run(store, "sample", "job", "shuttle")
    path.write_text(
        json.dumps(contact_run([]) | {"video_id": "other"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="does not match"):
        load_evaluation_run(store, "sample", "job", "contacts")
