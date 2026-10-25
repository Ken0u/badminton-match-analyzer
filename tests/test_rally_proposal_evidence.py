"""Generated observation provenance, never independently verified rally truth."""

import json
from bisect import bisect_right
from copy import deepcopy

import pytest
from badminton import rallies
from badminton.rally_evaluation import evaluate_rallies
from rally_fixture import scene


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("clock", ["constant", "variable", "high_rate", "offset"])
def test_emitted_context_contains_observed_windows_and_motion_dependencies(
    mode, clock, monkeypatch
):
    times = None
    if clock == "variable":
        times, now = [], 0.0
        for i in range(110):
            times.append(now)
            now += 0.02 if i % 2 else 0.06
    elif clock == "high_rate":
        times = [i / 100 for i in range(400)]
    args = scene(mode, times)
    if clock == "offset":
        args[0]["frame_count"] += 37
        args[-1]["calibrations"][0].update(start_frame=37, end_frame=137)
        for run in args[1:3]:
            run.update(start_frame=37, end_frame=137)
            for row in run["frames"]:
                row["frame"] += 37
                row["time_s"] += 20
    original = deepcopy(args)
    read_rows = []
    window = rallies._window

    def observe_window(*values):
        result = window(*values)
        read_rows.extend(result)
        return result

    monkeypatch.setattr(rallies, "_window", observe_window)
    verified = []
    for name in ("_serve", "_ending"):
        original_function = getattr(rallies, name)

        def observed_call(rows, source_times, *values, function=original_function):
            read_rows.clear()
            candidate = function(rows, source_times, *values)
            if candidate is not None:
                left, right = (
                    candidate["context_start_frame"],
                    candidate["context_end_frame"],
                )
                assert read_rows
                assert rows[0]["frame"] <= left <= candidate["start_frame"]
                assert candidate["end_frame"] < right <= rows[-1]["frame"] + 1
                for row in read_rows:
                    index = row["frame"] - rows[0]["frame"]
                    assert left <= row["frame"] < right
                    if index:
                        assert left <= rows[index - 1]["frame"] < right
                    lag = bisect_right(source_times, row["time_s"] - 0.16 + 1e-8) - 1
                    if (
                        0 <= lag < index
                        and 0.112 <= row["time_s"] - source_times[lag] <= 0.24
                    ):
                        assert left <= rows[lag]["frame"] < right
                verified.append(candidate["kind"])
            return candidate

        monkeypatch.setattr(rallies, name, observed_call)
    run = rallies.propose_rallies(*args)
    assert {c["kind"] for c in run["candidates"]} == {"serve", "rally_end"}
    assert set(verified) == {"serve", "rally_end"}
    assert args == original


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("kind", ["serve", "rally_end"])
def test_new_saved_evidence_excludes_boundary_only_review_but_full_context_matches(
    tmp_path, mode, kind
):
    args = scene(mode)
    video, players, _shuttle, annotations = args
    times = [row["time_s"] for row in players["frames"]]
    before = deepcopy(args)
    path = tmp_path / "proposals.json"
    summary = rallies.generate_rallies(
        *args, "players", "shuttle", path, source_times=times
    )
    run = json.loads(path.read_bytes())
    assert summary["candidate_count"] == 2
    candidate = next(c for c in run["candidates"] if c["kind"] == kind)
    left, right = candidate["start_frame"], candidate["end_frame"] + 1
    evidence_left = candidate["context_start_frame"]
    evidence_right = candidate["context_end_frame"]
    assert evidence_left < left
    assert right < evidence_right
    prefix = "contact_" if kind == "serve" else "terminal_"
    doc = deepcopy(annotations)
    doc.update(
        events=[
            {
                "id": "reference",
                "kind": kind,
                "frame": candidate["frame"],
                "status": "reviewed",
                prefix + "start_frame": left,
                prefix + "end_frame": right - 1,
            }
        ],
        review_windows=[
            {
                "id": "review",
                "start_frame": left,
                "end_frame": right,
                "scene": "live",
                "serves_complete": True,
                "rally_ends_complete": True,
            }
        ],
    )
    original_doc, original_run = deepcopy(doc), deepcopy(run)
    report = evaluate_rallies(video, doc, run, times)["kinds"][kind]
    assert report["coverage"]["reviewed_events"] == 1
    assert report["coverage"]["reviewed_frames"] == right - left
    assert report["interval_compatibility"]["matched_count"] == 0
    assert report["interval_compatibility"]["unmatched_event_ids"] == ["reference"]
    assert candidate["id"] in {
        c["id"]
        for c in report["coverage"]["candidate_evidence_context"]["excluded_candidates"]
        if c["reason"] == "evidence_context_outside_reviewed_coverage"
    }
    assert (doc, run) == (original_doc, original_run)
    doc["review_windows"][0].update(start_frame=evidence_left, end_frame=evidence_right)
    full = evaluate_rallies(video, doc, run, times)["kinds"][kind]
    assert full["coverage"]["reviewed_events"] == 1
    assert full["interval_compatibility"]["matched_count"] == 1
    assert (
        candidate["id"]
        in full["coverage"]["candidate_evidence_context"]["declared_candidate_ids"]
    )
    assert not full["coverage"]["candidate_evidence_context"][
        "unavailable_candidate_ids"
    ]
    assert args == before


@pytest.mark.parametrize("failure", ["cut", "gap", "missing", "nonlive"])
def test_emitted_context_never_reaches_across_source_barriers(failure):
    args = scene()
    barriers = [5, 85]
    for run in args[1:3]:
        if failure == "cut":
            run["cut_frames"] = barriers
        elif failure == "gap":
            for row in run["frames"]:
                row["time_s"] += sum(0.2 for cut in barriers if row["frame"] >= cut)
        elif failure == "missing":
            run["frames"] = [r for r in run["frames"] if r["frame"] not in barriers]
    if failure == "nonlive":
        args[-1]["scene_ranges"] = [
            {"id": str(c), "start_frame": c, "end_frame": c + 1, "scene": "non_play"}
            for c in barriers
        ]
    result = rallies.propose_rallies(*args)
    assert {c["kind"] for c in result["candidates"]} == {"serve", "rally_end"}
    for candidate in result["candidates"]:
        left, right = candidate["context_start_frame"], candidate["context_end_frame"]
        assert not any(left < cut < right for cut in barriers)
        if failure in ("missing", "nonlive"):
            assert not any(left <= cut < right for cut in barriers)
