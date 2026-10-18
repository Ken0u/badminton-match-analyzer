import copy
import json

import numpy as np
import pytest
from badminton.calibration_context import (
    court_context_changed,
    court_run_context,
    court_signature,
    effective_annotations,
)
from badminton.rallies import generate_rallies, propose_rallies, reviewed_rallies
from badminton.scene_review import reviewed_run
from badminton.stroke_context import StrokeContext
from rally_fixture import scene
from test_stroke_context import inputs


def derived(doc, end=100, cuts=None):
    return {
        "stage": "players",
        "start_frame": 0,
        "end_frame": end,
        "cut_frames": cuts or [],
        "court_context_version": 1,
        "automatic_calibrations": copy.deepcopy(doc["calibrations"]),
    }


def test_manual_geometry_has_priority_and_does_not_mutate_saved_or_derived_inputs():
    _, _, _, doc = scene()
    run = derived(doc)
    doc["calibrations"][0].update(start_frame=25, end_frame=75)
    doc["calibrations"][0]["corners"][0]["x"] = 0.1
    before = copy.deepcopy((doc, run))
    effective = effective_annotations(doc, run)["calibrations"]
    assert [(c["start_frame"], c["end_frame"]) for c in effective] == [
        (0, 25),
        (25, 75),
        (75, 100),
    ]
    assert effective[1]["corners"][0]["x"] == 0.1
    assert effective[0]["corners"][0]["x"] == 0
    assert (doc, run) == before


def test_old_manual_geometry_expires_at_cut_and_new_auto_geometry_can_cover_next_view():
    _, _, _, doc = scene()
    run = derived(doc, cuts=[40])
    run["automatic_calibrations"][0]["start_frame"] = 40
    effective = effective_annotations(doc, run)["calibrations"]
    assert [(c["start_frame"], c["end_frame"]) for c in effective] == [
        (0, 40),
        (40, 100),
    ]
    # Legacy records keep their original signature contract.
    run.pop("court_context_version")
    run["automatic_calibrations"] = []
    assert effective_annotations(doc, run)["calibrations"] == doc["calibrations"]


@pytest.mark.parametrize("failure", ["outside", "overlap", "cut", "nonfinite"])
def test_invalid_persisted_automatic_context_is_rejected(failure):
    _, _, _, doc = scene()
    run = derived(doc)
    if failure == "outside":
        run["automatic_calibrations"][0]["end_frame"] = 101
    elif failure == "overlap":
        run["automatic_calibrations"] *= 2
    elif failure == "cut":
        run["cut_frames"] = [50]
    else:
        run["automatic_calibrations"][0]["corners"][0]["x"] = float("nan")
    with pytest.raises(ValueError):
        effective_annotations({"calibrations": []}, run)


def test_manual_edits_invalidate_auto_filtered_player_inputs_but_labels_do_not():
    _, _, _, doc = scene()
    run = derived(doc)
    doc["calibrations"] = []
    run["calibration_signature"] = court_signature(
        effective_annotations(doc, run), 0, 100
    )
    assert not reviewed_run(run, doc)["requires_tracking_rerun"]
    doc["events"] = [{"frame": 40, "family": "smash"}]
    assert not reviewed_run(run, doc)["requires_tracking_rerun"]
    doc["calibrations"] = copy.deepcopy(run["automatic_calibrations"])
    # Adopting precisely the same geometry and scope preserves numerical inputs.
    assert not reviewed_run(run, doc)["requires_tracking_rerun"]
    doc["calibrations"][0]["corners"][0]["x"] += 0.02
    result = reviewed_run(run, doc)
    assert result["requires_tracking_rerun"] and result["requires_court_tracking_rerun"]


def test_rallies_use_auto_context_and_review_detects_current_edits(tmp_path):
    video, players, shuttle, doc = scene()
    expected = propose_rallies(video, players, shuttle, doc)
    players.update(derived(doc))
    players["calibration_signature"] = court_signature(doc, 0, 100)
    doc["calibrations"] = []
    before = copy.deepcopy((players, shuttle, doc))
    assert propose_rallies(video, players, shuttle, doc) == expected
    output = tmp_path / "rallies.json"
    generate_rallies(video, players, shuttle, doc, "players", "shuttle", output)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert not reviewed_rallies(result, doc)["requires_proposal_rerun"]
    doc["calibrations"] = copy.deepcopy(players["automatic_calibrations"])
    doc["calibrations"][0]["corners"][0]["x"] += 0.02
    assert reviewed_rallies(result, doc)["requires_proposal_rerun"]
    doc["calibrations"] = []
    assert (players, shuttle, doc) == before


def test_observed_stroke_features_use_derived_court_with_exact_manual_parity():
    video, players, shuttle, doc = inputs()
    expected = StrokeContext(video, players, shuttle, doc).pack(40, 1)["features"]
    players.update(derived(doc, video["frame_count"]))
    doc["calibrations"] = []
    actual = StrokeContext(video, players, shuttle, doc).pack(40, 1)["features"]
    np.testing.assert_array_equal(actual, expected)


def test_saved_contact_and_recognition_context_stales_after_geometry_edit():
    _, _, _, doc = scene()
    players = derived(doc)
    artifact = {
        "court_context": court_run_context(players),
        "calibration_signature": court_signature(doc, 0, 100),
    }
    doc["calibrations"] = []
    assert not court_context_changed(doc, artifact)
    doc["calibrations"] = copy.deepcopy(players["automatic_calibrations"])
    doc["calibrations"][0]["corners"][0]["x"] += 0.02
    assert court_context_changed(doc, artifact)
