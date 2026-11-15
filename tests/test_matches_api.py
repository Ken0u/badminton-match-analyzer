"""The matches flow: upload plus names, one job, name confirmation, swaps."""

import json
import threading
import time

import av
import numpy as np
import pytest
from badminton import matches, pipeline
from badminton.api import create_app
from badminton.match_analysis import build_match_analysis, write_match_analysis
from badminton.storage import Store
from badminton.video import timestamps_for, write_json
from fastapi.testclient import TestClient
from test_match_analysis import persons_inputs
from test_pipeline import stub_person_looks

# Real processing ---------------------------------------------------------------


def tiny_video(path, frames=40):
    """A real 4 s, 10 fps clip: enough for ingest and one processing window."""
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=10)
        stream.width, stream.height = 64, 32
        stream.pix_fmt = "yuv420p"
        for index in range(frames):
            frame = av.VideoFrame.from_ndarray(
                np.full((32, 64, 3), index * 5, np.uint8), format="rgb24"
            )
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path.read_bytes()


@pytest.fixture
def flow(tmp_path, monkeypatch):
    """A real upload with stand-ins for the inference stages."""
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    content = tiny_video(tmp_path / "clip.mp4")
    (tmp_path / "clip.mp4").unlink()
    data = tmp_path / "processed"
    calls = []

    def scan(v, root, data, callback, output):
        calls.append("segments")
        times = timestamps_for(data, v["id"])
        write_json(
            output,
            {
                "stage": "segments",
                "video_id": v["id"],
                "video_sha256": v["sha256"],
                "start_frame": 0,
                "end_frame": len(times),
                "cut_frames": [],
                "boundaries": [],
                "method": "synthetic",
                "decoded_frames": len(times),
            },
        )
        callback(1)

    def rows(v, data, first, last, **extra):
        times = timestamps_for(data, v["id"])
        return [{"frame": i, "time_s": times[i], **extra} for i in range(first, last)]

    def players(v, root, data, doc, first, last, stride, callback, output, **kw):
        calls.append("players")
        callback(0.5)
        write_json(
            output,
            {
                "stage": "players",
                "video_id": v["id"],
                "video_sha256": v["sha256"],
                "start_frame": first,
                "end_frame": last,
                "stride": stride,
                "calibration_signature": [],
                "frames": rows(
                    v, data, first, last, players=[], calibration_valid=False
                ),
            },
        )

    def shuttle(v, root, data, first, last, callback, output, doc, **kw):
        calls.append("shuttle")
        hidden = {"visible": False, "x": None, "y": None, "repaired": False}
        write_json(
            output,
            {
                "stage": "shuttle",
                "video_id": v["id"],
                "video_sha256": v["sha256"],
                "start_frame": first,
                "end_frame": last,
                "stride": 1,
                "frames": rows(v, data, first, last, shuttle=hidden),
            },
        )
        callback(1)

    monkeypatch.setattr(pipeline, "scan_video", scan)
    monkeypatch.setattr(pipeline, "track_players", players)
    monkeypatch.setattr(pipeline, "track_shuttle", shuttle)
    stub_person_looks(monkeypatch, {"width": 64, "height": 32})
    return tmp_path, data, content, calls


def wait(client, match_id, states=("needs_names", "ready", "failed", "paused")):
    deadline = time.monotonic() + 30
    seen = []
    while time.monotonic() < deadline:
        status = client.get(f"/api/matches/{match_id}").json()
        seen.append(status)
        if status["state"] in states:
            return status, seen
        time.sleep(0.02)
    pytest.fail(f"Match did not finish: {seen[-1]}")


def create(client, content, mode="singles", team1=("Ann",), team2=("Bo",)):
    return client.post(
        "/api/matches",
        files={"file": ("Final.mp4", content, "video/mp4")},
        data={"mode": mode, "team1": list(team1), "team2": list(team2)},
    )


def test_one_job_runs_to_needs_names_then_confirmation_makes_it_ready(flow):
    root, data, content, calls = flow
    with TestClient(create_app(root, data)) as client:
        response = create(client, content)
        assert response.status_code == 202, response.text
        created = response.json()
        match_id = created["match_id"]
        assert created["video_id"] == match_id and not created["reused_video"]
        status, seen = wait(client, match_id)
        assert status["state"] == "needs_names", status
        assert status["progress"] == 1 and status["error"] is None
        assert status["name"] == "Final.mp4" and status["mode"] == "singles"
        progress = [s["progress"] for s in seen]
        assert progress == sorted(progress)
        assert calls == ["segments", "players", "shuttle"]
        store = Store(data)
        job = store.job(created["job_id"])
        assert job["kind"] == "analysis" and job["status"] == "completed"
        assert job["details"]["match"] and job["details"]["analysis_key"]
        assert job["summary"]["identity"] == "persons_stage"

        document = client.get(f"/api/matches/{match_id}/analysis").json()
        assert document["identity"]["source"] == "persons_stage"
        assert not document["names_confirmed"]
        assert [p["name"] for p in document["players"]] == ["", ""]
        assert client.get(f"/api/videos/{match_id}/match-analysis").json() == document

        players = client.get(f"/api/matches/{match_id}/players").json()
        assert players["teams"] == {"T1": ["Ann"], "T2": ["Bo"]}
        assert [
            (p["id"], p["team"], p["name"], p["name_source"])
            for p in players["players"]
        ] == [
            ("P1", "T1", "Ann", "guessed"),
            ("P2", "T2", "Bo", "guessed"),
        ]
        # Swapping the two names is the one correction a person makes.
        confirmed = client.put(
            f"/api/matches/{match_id}/players",
            json={"names": {"P1": "Bo", "P2": "Ann"}},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert [p["name"] for p in confirmed.json()["players"]] == ["Bo", "Ann"]
        assert confirmed.json()["state"] == "ready"
        assert client.get(f"/api/matches/{match_id}").json()["state"] == "ready"
        document = client.get(f"/api/matches/{match_id}/analysis").json()
        assert document["names_confirmed"]
        assert [p["name"] for p in document["players"]] == ["Bo", "Ann"]
        # The persons artifact is never edited; names live in the match record.
        record = json.loads((data / match_id / "match.json").read_text())
        assert record["confirmed"] == {"P1": "Bo", "P2": "Ann"}
        persons = list((data / match_id / "persons").rglob("persons.json"))
        assert persons and "Bo" not in persons[0].read_text()

        bad = client.put(
            f"/api/matches/{match_id}/players",
            json={"names": {"P1": "Bo", "P2": "Cy"}},
        )
        assert bad.status_code == 422
        assert [m["match_id"] for m in client.get("/api/matches").json()] == [match_id]


def test_same_video_again_reuses_its_stages_and_starts_over_on_names(flow):
    root, data, content, calls = flow
    with TestClient(create_app(root, data)) as client:
        first = create(client, content).json()
        wait(client, first["match_id"])
        client.put(
            f"/api/matches/{first['match_id']}/players",
            json={"names": {"P1": "Ann", "P2": "Bo"}},
        )
        calls.clear()
        again = create(client, content, team1=["Cy"], team2=["Di"])
        assert again.status_code == 202
        second = again.json()
        assert second["match_id"] == first["match_id"] and second["reused_video"]
        status, _ = wait(client, second["match_id"])
        assert status["state"] == "needs_names" and calls == []
        job = Store(data).job(second["job_id"])
        assert job["summary"]["reused_stages"] == job["summary"]["completed_stages"]
        names = client.get(f"/api/matches/{second['match_id']}/players").json()
        assert [p["name"] for p in names["players"]] == ["Cy", "Di"]
        # The duplicate upload left no second copy of the video.
        assert len(list((root / ".media").iterdir())) == 1
        wrong = create(
            client, content, mode="doubles", team1=["A", "B"], team2=["C", "D"]
        )
        assert wrong.status_code == 409


def test_missing_identity_weights_still_finish_with_a_warning(flow, monkeypatch):
    root, data, content, _ = flow
    reason = "Player re-identification weights are not installed (reid/x.pth)"
    monkeypatch.setattr(pipeline, "persons_unavailable", lambda: reason)
    with TestClient(create_app(root, data)) as client:
        match_id = create(client, content).json()["match_id"]
        status, _ = wait(client, match_id)
        assert status["state"] == "needs_names"
        identity_warnings = [w for w in status["warnings"] if "re-identification" in w]
        assert len(identity_warnings) == 1 and "not installed" in identity_warnings[0]
        document = client.get(f"/api/matches/{match_id}/analysis").json()
        assert document["identity"]["source"] == "per_view_fallback"
        assert document["identity"]["persistent"] is False
        assert document["warnings"] == status["warnings"]
        # With the weights back, resuming runs only the persons stage.
        monkeypatch.setattr(pipeline, "persons_unavailable", lambda: None)
        resumed = client.post(f"/api/matches/{match_id}/resume")
        assert resumed.status_code == 202
        status, _ = wait(client, match_id)
        assert status["warnings"] == []
        job = Store(data).job(resumed.json()["job_id"])
        summary = job["summary"]
        assert summary["reused_stages"] == summary["completed_stages"] - 1


def test_pause_and_resume_through_the_match(flow, monkeypatch):
    root, data, content, calls = flow
    entered, release = threading.Event(), threading.Event()
    original = pipeline.track_shuttle

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "track_shuttle", blocked)
    with TestClient(create_app(root, data)) as client:
        match_id = create(client, content).json()["match_id"]
        assert entered.wait(10)
        try:
            running = client.get(f"/api/matches/{match_id}").json()
            assert running["state"] == "running"
            assert running["stage"] == "Tracking the shuttle"
            assert 0 < running["progress"] < 1
            assert client.get(f"/api/matches/{match_id}/players").status_code == 409
            assert client.post(f"/api/matches/{match_id}/resume").status_code == 409
            paused = client.post(f"/api/matches/{match_id}/pause")
            assert paused.status_code == 202 and paused.json()["stage"] == "Pausing"
            assert create(client, content).status_code == 409  # one job at a time
        finally:
            release.set()
        status, _ = wait(client, match_id)
        assert status["state"] == "paused" and status["error"]
        assert client.post(f"/api/matches/{match_id}/pause").status_code == 409
        monkeypatch.setattr(pipeline, "track_shuttle", original)
        calls.clear()
        assert client.post(f"/api/matches/{match_id}/resume").status_code == 202
        status, _ = wait(client, match_id)
        assert status["state"] == "needs_names"
        assert calls == ["shuttle"]  # finished segments and players were reused


def test_create_rejects_bad_names_before_queuing(flow):
    root, data, content, _ = flow
    with TestClient(create_app(root, data)) as client:
        for mode, team1, team2 in (
            ("singles", ["Ann", "Al"], ["Bo"]),
            ("doubles", ["Ann", "Al"], ["Bo"]),
            ("singles", ["Ann"], ["ann"]),
            ("singles", [" "], ["Bo"]),
            ("singles", ["A" * 101], ["Bo"]),
        ):
            assert create(client, content, mode, team1, team2).status_code == 422
        bad_video = client.post(
            "/api/matches",
            files={"file": ("x.mp4", b"not a video", "video/mp4")},
            data={"mode": "singles", "team1": ["Ann"], "team2": ["Bo"]},
        )
        assert bad_video.status_code == 422
        assert Store(data).jobs() == []
        assert not (root / ".media").exists() or not any((root / ".media").iterdir())
        assert client.get("/api/matches/unknown").status_code == 404


# Names, swaps and thumbnails on a built document ----------------------------


@pytest.fixture
def built(tmp_path, monkeypatch):
    """A finished singles match built from the synthetic builder fixture."""
    data = tmp_path / "data"
    store = Store(data)
    store.register({"id": "v", "mode": "singles", "name": "synthetic.mp4"})
    store.put_job(
        {"id": "j", "kind": "analysis", "video_id": "v", "status": "completed"}
    )
    record = matches.new_record(
        "v", "singles", {"T1": ["Ann"], "T2": ["Bo"]}, "synthetic.mp4"
    )
    record.update(job_id="j", jobs=["j"])
    matches.write_record(data, record)
    monkeypatch.setattr(
        matches, "load_match_inputs", lambda store, video_id, key=None: persons_inputs()
    )
    picture = data / "v" / "persons" / "persons-run" / "P1.jpg"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"\xff\xd8 not really a jpeg")
    write_match_analysis(data, build_match_analysis(persons_inputs()))
    return tmp_path, data


def rally_hitters(document, index=0):
    return [s["hitter_id"] for s in document["rallies"][index]["shots"]]


def test_swap_is_stored_applied_survives_rebuild_and_undoes(built):
    root, data = built
    with TestClient(create_app(root, data)) as client:
        before = client.get("/api/matches/v/analysis").json()
        assert rally_hitters(before) == ["P2", "P1", "P2"]
        assert rally_hitters(before, 1) == ["P1", "P2"]
        swapped = client.post(
            "/api/matches/v/rallies/rally-1/swap", json={"persons": ["P1", "P2"]}
        )
        assert swapped.status_code == 200, swapped.text
        body = swapped.json()
        assert body["applied"] and rally_hitters({"rallies": [body["rally"]]}) == [
            "P1",
            "P2",
            "P1",
        ]
        assert body["overrides"] == [
            {
                "kind": "swap",
                "persons": ["P1", "P2"],
                "start_frame": 20,
                "end_frame": 65,
                "rally_id": "rally-1",
            }
        ]
        after = client.get("/api/matches/v/analysis").json()
        assert rally_hitters(after) == ["P1", "P2", "P1"]
        assert rally_hitters(after, 1) == ["P1", "P2"]  # other rallies untouched
        stored = json.loads((data / "v" / "match_overrides.json").read_text())
        assert len(stored["overrides"]) == 1

        # A rebuild (e.g. after new code) keeps the override.
        matches.rebuild(Store(data), "v")
        assert rally_hitters(client.get("/api/matches/v/analysis").json()) == [
            "P1",
            "P2",
            "P1",
        ]
        # The same swap again undoes it.
        again = client.post(
            "/api/matches/v/rallies/rally-1/swap", json={"persons": ["P2", "P1"]}
        ).json()
        assert not again["applied"] and again["overrides"] == []
        assert rally_hitters(client.get("/api/matches/v/analysis").json()) == [
            "P2",
            "P1",
            "P2",
        ]
        # DELETE removes every swap of the rally.
        client.post(
            "/api/matches/v/rallies/rally-1/swap", json={"persons": ["P1", "P2"]}
        )
        undone = client.delete("/api/matches/v/rallies/rally-1/swap")
        assert undone.status_code == 200 and undone.json()["overrides"] == []
        assert rally_hitters(client.get("/api/matches/v/analysis").json()) == [
            "P2",
            "P1",
            "P2",
        ]
        assert (
            client.post(
                "/api/matches/v/rallies/rally-9/swap", json={"persons": ["P1", "P2"]}
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/matches/v/rallies/rally-1/swap", json={"persons": ["P1", "P1"]}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/matches/v/rallies/rally-1/swap", json={"persons": ["P1", "P3"]}
            ).status_code
            == 422
        )


def test_confirmed_names_and_swaps_survive_each_other(built):
    root, data = built
    with TestClient(create_app(root, data)) as client:
        client.post(
            "/api/matches/v/rallies/rally-1/swap", json={"persons": ["P1", "P2"]}
        )
        client.put("/api/matches/v/players", json={"names": {"P1": "Ann", "P2": "Bo"}})
        document = client.get("/api/matches/v/analysis").json()
        assert document["names_confirmed"] and len(document["overrides"]) == 1
        assert [p["name"] for p in document["players"]] == ["Ann", "Bo"]


def test_thumbnails_are_served_only_from_inside_the_video_folder(built):
    root, data = built
    with TestClient(create_app(root, data)) as client:
        players = client.get("/api/matches/v/players").json()["players"]
        assert players[0]["thumbnail_url"] == "/api/matches/v/players/P1/thumbnail"
        assert players[1]["thumbnail_url"] is None
        picture = client.get(players[0]["thumbnail_url"])
        assert picture.status_code == 200
        assert picture.headers["content-type"] == "image/jpeg"
        assert client.get("/api/matches/v/players/P2/thumbnail").status_code == 404
        assert client.get("/api/matches/v/players/P9/thumbnail").status_code == 404
    outside = data / "secret.jpg"
    outside.write_bytes(b"x")
    (data / "v" / "notes.txt").write_text("x")
    for relative in (
        "../secret.jpg",
        "persons/../../secret.jpg",
        str(outside),
        "/etc/passwd",
        "C:/Windows/win.ini",
        "notes.txt",
        "persons/persons-run/missing.jpg",
        "",
        None,
    ):
        assert matches.thumbnail_file(data, "v", relative) is None, relative
    assert matches.thumbnail_file(data, "v", "persons/persons-run/P1.jpg")


def test_mutations_wait_for_results(built):
    root, data = built
    store = Store(data)
    with TestClient(create_app(root, data)) as client:
        # After start-up recovery, which marks owner-less jobs interrupted.
        store.put_job(
            {"id": "j", "kind": "analysis", "video_id": "v", "status": "running"}
        )
        assert client.get("/api/matches/v").json()["state"] == "running"
        assert (
            client.put(
                "/api/matches/v/players", json={"names": {"P1": "Ann", "P2": "Bo"}}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/matches/v/rallies/rally-1/swap", json={"persons": ["P1", "P2"]}
            ).status_code
            == 409
        )
        store.put_job(
            {
                "id": "j",
                "kind": "analysis",
                "video_id": "v",
                "status": "failed",
                "message": "Out of memory",
            }
        )
        failed = client.get("/api/matches/v").json()
        assert (failed["state"], failed["error"]) == ("failed", "Out of memory")


# Name rules ---------------------------------------------------------------------


def test_names_guess_and_confirmation_rules():
    from badminton.match_analysis import default_persons

    doubles = default_persons("doubles")
    entered = matches.entered_names("doubles", ["Ann", "Al"], ["Bo", "Bea"])
    assert entered == {"T1": ["Ann", "Al"], "T2": ["Bo", "Bea"]}
    assert matches.guessed_names(entered, doubles) == {
        "P1": "Ann",
        "P2": "Al",
        "P3": "Bo",
        "P4": "Bea",
    }
    # Swapping partners, or whole teams, is allowed.
    for names in (
        {"P1": "Al", "P2": "Ann", "P3": "Bo", "P4": "Bea"},
        {"P1": "Bo", "P2": "Bea", "P3": "Ann", "P4": "Al"},
    ):
        assert matches.check_confirmation("doubles", entered, doubles, names) == names
    for names, message in (
        ({"P1": "Ann", "P2": "Bo", "P3": "Al", "P4": "Bea"}, "Partners"),
        ({"P1": "Ann", "P2": "Al", "P3": "Bo"}, "every player"),
        ({"P1": "Ann", "P2": "Ann", "P3": "Bo", "P4": "Bea"}, "exactly once"),
        ({"P1": "Ann", "P2": "Al", "P3": "Bo", "P4": "Cy"}, "exactly once"),
    ):
        with pytest.raises(ValueError, match=message):
            matches.check_confirmation("doubles", entered, doubles, names)
    singles = default_persons("singles")
    entered = matches.entered_names("singles", [" Ann "], ["Bo"])
    assert matches.guessed_names(entered, singles) == {"P1": "Ann", "P2": "Bo"}
    assert matches.check_confirmation(
        "singles", entered, singles, {"P1": "Bo ", "P2": "Ann"}
    ) == {"P1": "Bo", "P2": "Ann"}
    with pytest.raises(ValueError, match="different name"):
        matches.entered_names("doubles", ["Ann", "ANN"], ["Bo", "Bea"])


def test_progress_is_time_weighted_monotonic_and_labelled():
    weights = matches.ProcessingProgress(2)
    assert len(weights.sequence) == 4 + 2 * len(pipeline.STAGES)
    values = [i / 1000 for i in range(1001)]
    mapped = [weights(v) for v in values]
    fractions = [f for f, _ in mapped]
    assert fractions == sorted(fractions)
    assert fractions[0] == 0 and fractions[-1] == pytest.approx(1)
    assert mapped[0][1] == "Scanning the video"
    assert weights(1.5 / 14)[1] == "Finding players"
    assert weights(2.5 / 14)[1] == "Tracking the shuttle"
    assert weights(3.5 / 14)[1] == "Reading strokes"
    assert weights(12.5 / 14)[1] == "Recognising players"
    assert weights(13.5 / 14)[1] == "Reading rally outcomes"
    # Players tracking moves the bar more than a cheap stage of the same count.
    assert (
        weights(2 / 13)[0] - weights(1 / 13)[0]
        > weights(4 / 13)[0] - weights(3 / 13)[0]
    )


def test_match_endpoints_are_in_the_contract(built):
    root, data = built
    paths = create_app(root, data).openapi()["paths"]
    for path in (
        "/api/matches",
        "/api/matches/{match_id}",
        "/api/matches/{match_id}/players",
        "/api/matches/{match_id}/players/{person_id}/thumbnail",
        "/api/matches/{match_id}/rallies/{rally_id}/swap",
        "/api/matches/{match_id}/analysis",
        "/api/matches/{match_id}/pause",
        "/api/matches/{match_id}/resume",
        "/api/videos/{video_id}/match-analysis",
    ):
        assert path in paths, path
