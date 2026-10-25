"""Generated selector provenance is software evidence, never badminton truth."""

from copy import deepcopy

import pytest
from badminton import rallies
from badminton.rally_evaluation import evaluate_rallies
from badminton.shuttle import _ComponentSelector
from rally_fixture import scene


def selected_scene(mode="singles", times=None):
    args = scene(mode, times)
    video, _players, flight, _doc = args
    selector = _ComponentSelector(video["width"], video["height"])
    for row in flight["frames"]:
        original = row["shuttle"]
        good = {"id": 1, "x": original["x"], "y": original["y"], "confidence": 0.9}
        raw = original | {"component_candidates": [good], "confidence": 0.9}
        if row["frame"] >= 3:
            raw.update(x=-100000, y=-100000)
        row["shuttle"] = selector.select(raw, row["frame"], row["time_s"])
        assert (row["shuttle"]["x"], row["shuttle"]["y"]) == (
            original["x"],
            original["y"],
        )
        if row["frame"] >= 3:
            # The producer's immediate three observations recursively depend
            # on the first observation; the declared bound retains that chain.
            assert row["shuttle"]["selection_context_start_frame"] == 0
    return args


def without_evidence(run):
    result = deepcopy(run)
    for candidate in result["candidates"]:
        candidate.pop("context_start_frame")
        candidate.pop("context_end_frame")
    return result


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("clock", ["constant", "variable", "high_rate", "offset"])
def test_transitive_component_history_preserves_all_other_proposal_fields(mode, clock):
    times = None
    if clock == "variable":
        times, now = [], 0.0
        for i in range(110):
            times.append(now)
            now += 0.02 if i % 2 else 0.06
    elif clock == "high_rate":
        times = [i / 100 for i in range(400)]
    args, control = selected_scene(mode, times), scene(mode, times)
    offset = 37 if clock == "offset" else 0
    if offset:
        for values in (args, control):
            values[0]["frame_count"] += offset
            values[-1]["calibrations"][0].update(start_frame=37, end_frame=137)
            for run in values[1:3]:
                run.update(start_frame=37, end_frame=137)
                for row in run["frames"]:
                    row["frame"] += offset
                    row["time_s"] += 20
                    for key in (
                        "selection_context_start_frame",
                        "selection_context_end_frame",
                    ):
                        if key in row.get("shuttle", {}):
                            row["shuttle"][key] += offset
    original = deepcopy(args)
    actual, legacy = rallies.propose_rallies(*args), rallies.propose_rallies(*control)
    assert without_evidence(actual) == without_evidence(legacy)
    assert {c["kind"] for c in actual["candidates"]} == {"serve", "rally_end"}
    assert all(c["context_start_frame"] == offset for c in actual["candidates"])
    assert [c["context_end_frame"] for c in actual["candidates"]] == [
        c["context_end_frame"] for c in legacy["candidates"]
    ]
    assert args == original


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("kind", ["serve", "rally_end"])
def test_short_review_cannot_credit_a_proposal_with_unreviewed_selection_history(
    tmp_path, mode, kind
):
    import json

    args = selected_scene(mode)
    video, players, _flight, doc = args
    before = deepcopy(args)
    times = [r["time_s"] for r in players["frames"]]
    path = tmp_path / "rallies.json"
    rallies.generate_rallies(*args, "players", "shuttle", path, source_times=times)
    saved = json.loads(path.read_bytes())
    candidate = next(c for c in saved["candidates"] if c["kind"] == kind)
    prefix = "contact_" if kind == "serve" else "terminal_"
    doc = deepcopy(doc)
    doc.update(
        events=[
            dict(
                id="reference",
                frame=candidate["frame"],
                kind=kind,
                status="reviewed",
                **{
                    prefix + "start_frame": candidate["start_frame"],
                    prefix + "end_frame": candidate["end_frame"],
                },
            )
        ],
        review_windows=[
            {
                "id": "review",
                "start_frame": 4 if kind == "serve" else 6,
                "end_frame": candidate["context_end_frame"],
                "scene": "live",
                "serves_complete": True,
                "rally_ends_complete": True,
            }
        ],
    )
    frozen = deepcopy((doc, saved))
    report = evaluate_rallies(video, doc, saved, times)["kinds"][kind]
    assert report["coverage"]["reviewed_events"] == 1
    assert report["coverage"]["reviewed_frames"] == (28 if kind == "serve" else 65)
    assert report["interval_compatibility"]["matched_count"] == 0
    assert report["interval_compatibility"]["unmatched_event_ids"] == ["reference"]
    assert any(
        c["id"] == candidate["id"]
        and c["reason"] == "evidence_context_outside_reviewed_coverage"
        for c in report["coverage"]["candidate_evidence_context"]["excluded_candidates"]
    )
    assert (doc, saved) == frozen
    doc["review_windows"][0]["start_frame"] = 0
    full = evaluate_rallies(video, doc, saved, times)["kinds"][kind]
    assert full["interval_compatibility"]["matched_count"] == 1
    assert full["coverage"]["reviewed_events"] == 1
    assert args == before


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize(
    "failure",
    [
        "negative",
        "bool",
        "float",
        "null",
        "missing_start",
        "missing_end",
        "future",
        "reversed",
    ],
)
def test_invalid_declared_selection_history_cannot_supply_evidence(mode, failure):
    args = selected_scene(mode)
    for row in args[2]["frames"]:
        point = row["shuttle"]
        if failure == "missing_start":
            del point["selection_context_start_frame"]
        elif failure == "missing_end":
            del point["selection_context_end_frame"]
        elif failure == "future":
            point["selection_context_end_frame"] = row["frame"] + 2
        else:
            point["selection_context_start_frame"] = {
                "negative": -1,
                "bool": False,
                "float": 0.0,
                "null": None,
                "reversed": row["frame"] + 1,
            }[failure]
    before = deepcopy(args)
    result = rallies.propose_rallies(*args)
    assert result["candidate_count"] == 0
    assert result["diagnostics"]["eligible_frames"] == 100
    assert args == before


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize(
    "failure", ["cut", "row_cut", "gap", "missing", "scene", "overlap"]
)
def test_declared_history_cannot_cross_an_input_context_barrier(mode, failure):
    args = selected_scene(mode)
    for run in args[1:3]:
        if failure == "cut":
            run["cut_frames"] = [5]
        elif failure == "row_cut":
            run["frames"][5]["scene_cut"] = True
        elif failure == "gap":
            for row in run["frames"][5:]:
                row["time_s"] += 0.2
        elif failure == "missing":
            run["frames"] = [r for r in run["frames"] if r["frame"] != 5]
        elif failure == "overlap":
            run["start_frame"] = 5
            run["frames"] = run["frames"][5:]
        elif failure == "scene":
            run["frames"][5]["scene"] = "unknown"
    before = deepcopy(args)
    assert rallies.propose_rallies(*args)["candidate_count"] == 0
    assert args == before


@pytest.mark.parametrize("kind", ["serve", "rally_end"])
def test_preceding_speed_observations_keep_their_own_selection_history(
    kind, monkeypatch
):
    args = scene()
    consumed = {}
    original = rallies._with_context

    def observe(candidate, rows):
        consumed.setdefault(candidate["kind"], min(row["frame"] for row in rows))
        return original(candidate, rows)

    monkeypatch.setattr(rallies, "_with_context", observe)
    baseline = rallies.propose_rallies(*args)
    first = consumed[kind]
    point = args[2]["frames"][first - 1]["shuttle"]
    point.update(selection_context_start_frame=0, selection_context_end_frame=first)
    current = rallies.propose_rallies(*args)
    assert without_evidence(current) == without_evidence(baseline)
    assert (
        next(c for c in current["candidates"] if c["kind"] == kind)[
            "context_start_frame"
        ]
        == 0
    )
