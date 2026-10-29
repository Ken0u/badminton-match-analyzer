"""Generated source-clock integrity checks; no model or scientific labels."""

import json
from copy import deepcopy

import pytest
from badminton.api import create_app
from badminton.rallies import generate_rallies, propose_rallies
from fastapi.testclient import TestClient
from rally_fixture import catalog, scene


def invalid_clock(name, times):
    result = list(times)
    values = {
        "nan": float("nan"),
        "infinity": float("inf"),
        "negative_infinity": -float("inf"),
        "negative": -0.01,
        "boolean": True,
        "string": "1.0",
        "null": None,
        "complex": 1 + 0j,
        "overflow": 10**1000,
        "duplicate": times[24],
        "decreasing": times[24] - 0.01,
    }
    if name in values:
        result[25] = values[name]
        return result
    if name == "short":
        return result[:-1]
    if name == "long":
        return [*result, result[-1] + 0.04]
    if name == "mapping":
        return dict(enumerate(result))
    if name == "text":
        return "0" * len(result)
    if name == "iterator":
        return iter(result)
    raise AssertionError(name)


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize(
    "failure",
    [
        "nan",
        "infinity",
        "negative_infinity",
        "negative",
        "boolean",
        "string",
        "null",
        "complex",
        "overflow",
        "duplicate",
        "decreasing",
        "short",
        "long",
        "mapping",
        "text",
        "iterator",
    ],
)
def test_invalid_full_clock_is_refused(mode, failure):
    args = scene(mode)
    times = [r["time_s"] for r in args[1]["frames"]]
    with pytest.raises(ValueError, match=r"[Ss]ource|[Tt]imestamp|[Cc]lock"):
        propose_rallies(*args, source_times=invalid_clock(failure, times))


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("outside", [0, 99])
def test_unobserved_clock_entries_are_still_validated(mode, outside):
    args = scene(mode)
    times = [r["time_s"] for r in args[1]["frames"]]
    for run in args[1:3]:
        run.update(start_frame=10, end_frame=90)
        run["frames"] = [r for r in run["frames"] if 10 <= r["frame"] < 90]
    assert propose_rallies(*args, source_times=times)["candidate_count"] == 2
    times[outside] = float("nan")
    with pytest.raises(ValueError, match=r"[Ss]ource|[Tt]imestamp|[Cc]lock"):
        propose_rallies(*args, source_times=times)


@pytest.mark.parametrize("stage", [1, 2])
@pytest.mark.parametrize(
    "value",
    [True, float("nan"), float("inf"), 10**1000],
    ids=["boolean", "nan", "infinity", "overflow"],
)
def test_perception_time_must_be_numeric_finite_and_not_boolean(stage, value):
    args = scene()
    args[stage]["frames"][25]["time_s"] = value
    with pytest.raises(ValueError, match=r"[Tt]ime|[Tt]imestamp"):
        propose_rallies(*args)


@pytest.mark.parametrize("mode", ["singles", "doubles"])
@pytest.mark.parametrize("kind", ["constant", "variable", "nonzero", "gap"])
def test_valid_native_clocks_preserve_candidate_values_and_inputs(mode, kind):
    times, timestamp = [], 7.0 if kind == "nonzero" else 0.0
    for index in range(100):
        times.append(timestamp)
        timestamp += 0.02 if kind == "variable" and index % 2 else 0.04
        if kind == "gap" and index == 75:
            timestamp += 0.7
    args = scene(mode, times)
    original = deepcopy(args)
    legacy = propose_rallies(*args)
    assert propose_rallies(*args, source_times=times) == legacy
    assert propose_rallies(*args, source_times=tuple(times)) == legacy
    assert args == original


def test_sparse_runs_keep_their_existing_values_with_a_valid_full_clock():
    args = scene()
    times = [r["time_s"] for r in args[1]["frames"]]
    for run in args[1:3]:
        run["frames"] = [r for r in run["frames"] if r["frame"] % 7]
    assert propose_rallies(*args, source_times=times) == propose_rallies(*args)


def test_source_frame_count_must_be_an_integer():
    args = scene()
    times = [r["time_s"] for r in args[1]["frames"]]
    args[0]["frame_count"] = float(len(times))
    with pytest.raises(ValueError, match=r"[Ss]ource|[Tt]imestamp|[Cc]lock"):
        propose_rallies(*args, source_times=times)


def test_finite_ordered_clock_still_must_correspond_to_native_observations():
    args = scene()
    times = [r["time_s"] + 0.01 for r in args[1]["frames"]]
    with pytest.raises(ValueError, match="timestamps do not match"):
        propose_rallies(*args, source_times=times)


def test_generator_refuses_nan_clock_before_writing_an_artifact(tmp_path):
    args = scene()
    times = [r["time_s"] for r in args[1]["frames"]]
    times[25] = float("nan")
    output = tmp_path / "invalid.json"
    with pytest.raises(ValueError, match=r"[Ss]ource|[Tt]imestamp|[Cc]lock"):
        generate_rallies(*args, "players", "shuttle", output, source_times=times)
    assert not output.exists()


def test_legacy_generation_explicitly_records_no_native_clock_validation(tmp_path):
    args = scene()
    output = tmp_path / "legacy.json"
    generate_rallies(*args, "players", "shuttle", output)
    result = json.loads(output.read_bytes())
    assert result["source_timestamps_validated"] is False
    assert result["candidates"] == propose_rallies(*args)["candidates"]


@pytest.mark.parametrize("failure", ["nan", "boolean", "string", "duplicate"])
def test_api_rejects_invalid_clock_before_job_admission(tmp_path, failure):
    root, data = tmp_path, tmp_path / "processed"
    store, video = catalog(root, data)
    clock_path = data / video["id"] / "timestamps.json"
    times = json.loads(clock_path.read_bytes())
    clock_path.write_text(json.dumps(invalid_clock(failure, times)), encoding="utf-8")
    before_clock = clock_path.read_bytes()
    jobs = store.jobs()
    annotations = store.annotations(video["id"]).model_dump()
    run_dir = data / video["id"] / "runs"
    runs = {p.name: p.read_bytes() for p in run_dir.iterdir()}
    with TestClient(create_app(root, data)) as client:
        response = client.post(
            f"/api/videos/{video['id']}/rallies",
            json={"player_run_id": "qa-players", "shuttle_run_id": "qa-shuttle"},
        )
        assert response.status_code == 422, response.text
        assert any(
            word in response.text.lower() for word in ("source", "timestamp", "clock")
        )
    assert store.jobs() == jobs
    assert store.annotations(video["id"]).model_dump() == annotations
    assert {p.name: p.read_bytes() for p in run_dir.iterdir()} == runs
    assert clock_path.read_bytes() == before_clock
