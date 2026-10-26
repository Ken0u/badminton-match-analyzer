import copy
import hashlib
import json
import time
from fractions import Fraction
from types import SimpleNamespace

import av
import numpy as np
import pytest
from badminton.api import create_app
from badminton.storage import Store
from badminton.video import write_json
from fastapi.testclient import TestClient


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    source = tmp_path / "fixture.mp4"
    source.write_bytes(b"fixture; decoder is isolated in audio tests")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    video = {
        "id": checksum[:16],
        "sha256": checksum,
        "path": source.name,
        "name": "fixture",
        "mode": "singles",
        "width": 640,
        "height": 360,
        "frame_count": 25,
        "duration_s": 1,
        "source_start_s": 0,
    }
    data = tmp_path / "data"
    store = Store(data)
    store.register(video)
    write_json(data / video["id"] / "timestamps.json", [i * 0.04 for i in range(25)])
    for stage in ("shuttle", "players"):
        write_json(
            data / video["id"] / "runs" / f"{stage}.json",
            {
                "stage": stage,
                "video_id": video["id"],
                "frames": [],
                "start_frame": 0,
                "end_frame": 25,
            },
        )
        store.put_job(
            {"id": stage, "kind": stage, "video_id": video["id"], "status": "completed"}
        )
    return tmp_path, data, store, video


def wait(store, identifier):
    for _ in range(200):
        job = next(job for job in store.jobs() if job["id"] == identifier)
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.01)
    pytest.fail("Contact job did not finish")


@pytest.mark.parametrize(
    "enabled,status", [(False, "available"), (True, "missing"), (True, "available")]
)
def test_audio_is_opt_in_and_never_changes_annotations(
    catalog, monkeypatch, enabled, status
):
    import badminton.audio as audio
    import badminton.contacts as contacts

    root, data, store, video = catalog
    visual = [
        {
            "id": "contact-10",
            "frame": 10,
            "time_s": 0.4,
            "track_id": None,
            "player_id": None,
        }
    ]
    monkeypatch.setattr(contacts, "propose_contacts", lambda *_: visual)
    calls = []

    def decode(v, r, start, end):
        calls.append((v["sha256"], r, start, end))
        return {"status": status, "peaks": []}

    monkeypatch.setattr(audio, "extract_audio_cues", decode)
    base = f"/api/videos/{video['id']}"
    with TestClient(create_app(root, data)) as client:
        request = {"shuttle_run_id": "shuttle", "player_run_id": "players"}
        if enabled:
            request["include_audio"] = True
        response = client.post(base + "/contacts", json=request)
        assert response.status_code == 202
        job = wait(store, response.json()["id"])
        assert job["status"] == "completed", job
        result = client.get(base + "/runs/" + job["id"]).json()
        assert result["candidates"] == [
            c | {"scene_excluded": False, "scene_exclusion_reason": None}
            for c in visual
        ]
        import json

        raw = json.loads(
            (data / video["id"] / "runs" / f"{job['id']}.json").read_text()
        )
        assert raw["candidates"] == visual
        assert "audio" not in job["summary"]
        if enabled:
            assert calls == [(video["sha256"], root, 0, 1)]
            assert result["audio"]["status"] == status
            assert job["summary"]["audio_status"] == status
        else:
            assert not calls and "audio" not in result
    assert store.annotations(video["id"]).revision == 0


def test_audio_request_requires_pose_and_rejects_unknown_flags(catalog):
    root, data, store, video = catalog
    with TestClient(create_app(root, data)) as client:
        base = f"/api/videos/{video['id']}/contacts"
        assert (
            client.post(
                base, json={"shuttle_run_id": "shuttle", "include_audio": True}
            ).status_code
            == 422
        )
        assert (
            client.post(
                base, json={"shuttle_run_id": "shuttle", "audio": True}
            ).status_code
            == 422
        )
    assert len(store.jobs()) == 2


@pytest.mark.parametrize("kind", ["pcm", "missing", "corrupt"])
@pytest.mark.parametrize(
    "mutation", ["stable", "decode", "close", "removed", "visual_only"]
)
def test_actual_audio_job_rejects_source_changes_without_publishing_or_editing_truth(
    catalog, monkeypatch, kind, mutation
):
    from badminton.audio import RATE
    from badminton.contacts import propose_contacts
    from badminton.schemas import Event

    root, data, store, video = catalog
    original_documents = {}
    runs = {}
    for stage in ("shuttle", "players"):
        path = data / video["id"] / "runs" / f"{stage}.json"
        run = json.loads(path.read_bytes())
        run["frames"] = []
        for index in range(25):
            row = {"frame": index, "time_s": index * 0.04}
            if stage == "shuttle":
                row["shuttle"] = {
                    "visible": True,
                    "x": 300 + 200 * abs(index * 0.04 - 0.48),
                    "y": 200,
                    "repaired": False,
                }
            else:
                row["players"] = [
                    {"track_id": 7, "box": [280, 180, 380, 320], "keypoints": []}
                ]
            run["frames"].append(row)
        write_json(path, run)
        runs[stage] = run
        original_documents[path] = path.read_bytes()
    visual = propose_contacts(runs["shuttle"], runs["players"], video)
    assert len(visual) == 1
    old_prediction = data / video["id"] / "runs" / "original-contacts.json"
    write_json(
        old_prediction,
        {"stage": "contacts", "video_id": video["id"], "candidates": visual},
    )
    original_documents[old_prediction] = old_prediction.read_bytes()
    reviewed = store.annotations(video["id"])
    reviewed.events.append(
        Event(
            id="preserved",
            rally_id="R1",
            kind="shot",
            frame=12,
            family="drop",
            side="backhand",
            status="corrected",
        )
    )
    assert store.save_annotations(video["id"], reviewed).revision == 1

    def revisions():
        with store.connect() as db:
            return db.execute(
                "SELECT revision,document,saved_at FROM annotations ORDER BY revision"
            ).fetchall()

    original_revisions = revisions()
    source = root / video["path"]
    source_bytes = source.read_bytes()
    opens = []
    pcm = av.AudioFrame.from_ndarray(np.zeros((1, RATE), np.float32), "fltp", "mono")
    pcm.sample_rate, pcm.time_base, pcm.pts = RATE, Fraction(1, RATE), 0

    def change():
        if mutation == "removed":
            source.unlink()
        else:
            source.write_bytes(b"X" * len(source_bytes))

    class Container:
        streams = SimpleNamespace(
            audio=[]
            if kind == "missing"
            else [SimpleNamespace(index=0, time_base=Fraction(1, RATE))]
        )

        def __enter__(self):
            return self

        def __exit__(self, *_):
            if mutation in ("close", "removed") or (
                kind == "missing" and mutation == "decode"
            ):
                change()

        def seek(self, *_args, **_kwargs):
            pass

        def decode(self, _stream):
            if mutation == "decode":
                change()
            if kind == "corrupt":
                raise av.error.InvalidDataError(1, "generated corrupt audio")
            yield pcm

    def open_generated(path):
        assert path == str(source)
        opens.append(path)
        return Container()

    # Keep the real extractor, source validator, media wrapper and proposal code.
    monkeypatch.setattr(av, "open", open_generated)
    with TestClient(create_app(root, data)) as client:
        response = client.post(
            f"/api/videos/{video['id']}/contacts",
            json={
                "shuttle_run_id": "shuttle",
                "player_run_id": "players",
                "include_audio": mutation != "visual_only",
            },
        )
        assert response.status_code == 202, response.text
        job = wait(store, response.json()["id"])
        artifact = data / video["id"] / "runs" / f"{job['id']}.json"
        if mutation in ("stable", "visual_only"):
            assert job["status"] == "completed", job
            result = json.loads(artifact.read_bytes())
            assert result["candidates"] == visual
            assert source.read_bytes() == source_bytes
            if mutation == "visual_only":
                assert not opens and "audio" not in result
            else:
                assert len(opens) == 1
                assert (
                    result["audio"]["status"]
                    == {
                        "pcm": "available",
                        "missing": "missing",
                        "corrupt": "unavailable",
                    }[kind]
                )
        else:
            assert job["status"] == "failed", job
            assert not artifact.exists()
            assert (
                "source is unavailable" in job["message"]
                if mutation == "removed"
                else "source changed" in job["message"]
            )
    assert all(
        path.read_bytes() == before for path, before in original_documents.items()
    )
    assert revisions() == original_revisions


@pytest.mark.parametrize(
    "case,expected",
    [
        ("aligned", 1),
        ("shifted_frames", 0),
        ("shifted_times", 0),
        ("duplicate", 0),
        ("conflicting_duplicate", 0),
        ("time_collision", 0),
        ("missing_frame", 0),
        ("sparse", 1),
        ("partial", 1),
        ("too_sparse", 0),
        ("player_replay", 0),
        ("shuttle_gap", 0),
    ],
)
def test_generated_audio_job_uses_corresponding_source_rows(
    catalog, monkeypatch, case, expected
):
    import badminton.audio as audio
    from badminton.contacts import propose_contacts
    from badminton.schemas import Event

    root, data, store, video = catalog
    shuttle, players = [], []
    for frame in range(25):
        visible = frame != 12
        shuttle.append(
            {
                "frame": frame,
                "time_s": frame * 0.04,
                "shuttle": {
                    "visible": visible,
                    "x": 300 if visible else None,
                    "y": 200 if visible else None,
                },
            }
        )
        keypoints = [[0, 0, 0] for _ in range(17)]
        keypoints[9] = [300 + (frame - 12) * 4, 200, 0.9]
        players.append(
            {
                "frame": frame,
                "time_s": frame * 0.04,
                "players": [
                    {"track_id": 7, "box": [270, 190, 350, 350], "keypoints": keypoints}
                ],
            }
        )
    if case == "shifted_frames":
        for row in players:
            row["frame"] += 100
    elif case == "shifted_times":
        for row in players:
            row["time_s"] += 0.005
    elif case in ("duplicate", "conflicting_duplicate"):
        duplicate = copy.deepcopy(players[12])
        if case == "conflicting_duplicate":
            duplicate["time_s"] += 0.001
        players.append(duplicate)
    elif case == "time_collision":
        players[12]["time_s"] = players[11]["time_s"]
    elif case == "missing_frame":
        players[12].pop("frame")
    elif case == "sparse":
        players = players[::2]
    elif case == "partial":
        players.pop(12)
    elif case == "too_sparse":
        players = players[::4]
    elif case == "player_replay":
        players[12]["scene"] = "replay"
    elif case == "shuttle_gap":
        shuttle.pop(11)
    documents = {}
    for stage, frames in (("shuttle", shuttle), ("players", players)):
        document = {
            "stage": stage,
            "video_id": video["id"],
            "frames": frames,
            "start_frame": 0,
            "end_frame": 25,
        }
        path = data / video["id"] / "runs" / f"{stage}.json"
        write_json(path, document)
        documents[path] = path.read_bytes()
    # Exercise real visual proposals and the actual background Store/API job.
    # Only the acoustic decoder is stubbed; this is not acoustic validation.
    assert (
        propose_contacts(
            json.loads(documents[data / video["id"] / "runs" / "shuttle.json"]),
            json.loads(documents[data / video["id"] / "runs" / "players.json"]),
            video,
        )
        == []
    )
    source = root / video["path"]
    source_bytes = source.read_bytes()
    reviewed = store.annotations(video["id"])
    reviewed.events.append(
        Event(
            id="kept-reviewed-event",
            rally_id="R1",
            kind="shot",
            frame=12,
            family="drop",
            side="backhand",
            status="corrected",
            notes="Generated preservation fixture, not source truth",
        )
    )
    assert store.save_annotations(video["id"], reviewed).revision == 1

    def saved_revisions():
        with store.connect() as db:
            return db.execute(
                "SELECT revision,document,saved_at FROM annotations WHERE video_id=? ORDER BY revision",
                (video["id"],),
            ).fetchall()

    revision_rows = saved_revisions()
    annotation_bytes = store.annotations(video["id"]).model_dump_json()
    calls = []

    def decode(*args):
        calls.append(args)
        return {
            "status": "available",
            "peaks": [
                {"time_s": 0.49, "strength_ratio": 4, "flux": 12, "threshold": 3}
            ],
        }

    monkeypatch.setattr(audio, "extract_audio_cues", decode)
    with TestClient(create_app(root, data)) as client:
        base = f"/api/videos/{video['id']}"
        response = client.post(
            base + "/contacts",
            json={
                "shuttle_run_id": "shuttle",
                "player_run_id": "players",
                "include_audio": True,
            },
        )
        if case in {
            "shifted_frames",
            "shifted_times",
            "duplicate",
            "conflicting_duplicate",
            "time_collision",
            "missing_frame",
        }:
            assert response.status_code == 422, response.text
            assert len(store.jobs()) == 2 and calls == []
            assert set((data / video["id"] / "runs").glob("*.json")) == set(documents)
            assert all(
                path.read_bytes() == before for path, before in documents.items()
            )
            assert source.read_bytes() == source_bytes
            assert store.annotations(video["id"]).model_dump_json() == annotation_bytes
            assert saved_revisions() == revision_rows
            return
        assert response.status_code == 202, response.text
        job = wait(store, response.json()["id"])
        assert job["status"] == "completed", job
        result = json.loads(
            (data / video["id"] / "runs" / f"{job['id']}.json").read_bytes()
        )
        assert len(result["candidates"]) == expected
        assert calls == [(video, root, 0, 1)]
        assert job["summary"]["candidate_count"] == expected
        if expected:
            candidate = result["candidates"][0]
            assert candidate["frame"] == 12 and candidate["track_id"] == 7
            assert candidate["reviewed"] is False
            assert candidate["timing"] == "uncertain_interval"
            assert candidate["evidence"]["av_offset_calibrated"] is False
    assert all(path.read_bytes() == before for path, before in documents.items())
    assert source.read_bytes() == source_bytes
    assert store.annotations(video["id"]).model_dump_json() == annotation_bytes
    assert saved_revisions() == revision_rows


@pytest.mark.parametrize(
    "rate,case,expected",
    [(rate, "aligned", 1) for rate in (24, 25, 30, 50, 60, 120)]
    + [
        (60, case, 1)
        for case in (
            "sparse",
            "vfr_origin",
            "duplicate_sound",
            "history_valid",
            "recursive_history",
        )
    ]
    + [
        (60, case, 0)
        for case in (
            "edge",
            "tail",
            "cut",
            "player_cut",
            "replay_bound",
            "player_replay_bound",
            "unknown_bound",
            "excluded_bound",
            "frame_gap",
            "timestamp_gap",
            "missing_audio",
            "no_gap",
            "static_wrist",
            "history_replay",
            "missing_history",
            "bound_pose_mismatch",
            "bound_pose_duplicate",
            "history_cut",
            "history_player_replay",
        )
    ],
)
def test_generated_audio_interval_api_preserves_source_bounds_and_review_context(
    catalog, monkeypatch, rate, case, expected
):
    import badminton.audio as audio
    from badminton.schemas import Event, SceneRange
    from test_audio_contacts import interval_scenario

    root, data, store, video = catalog
    shuttle, players, metadata, cues, times = interval_scenario(rate, case)
    video.update(metadata)
    store.register(video)
    write_json(data / video["id"] / "timestamps.json", times)
    original_bytes = {}
    for stage, document in (("shuttle", shuttle), ("players", players)):
        document.update(stage=stage, video_id=video["id"], start_frame=0, end_frame=80)
        path = data / video["id"] / "runs" / f"{stage}.json"
        write_json(path, document)
        original_bytes[path] = path.read_bytes()
    reviewed = store.annotations(video["id"])
    reviewed.events.append(
        Event(
            id="keep",
            rally_id="R1",
            kind="shot",
            frame=24,
            family="drop",
            side="backhand",
            status="corrected",
        )
    )
    store.save_annotations(video["id"], reviewed)

    def revisions():
        with store.connect() as db:
            return db.execute(
                "SELECT revision,document,saved_at FROM annotations ORDER BY revision"
            ).fetchall()

    original_revisions = revisions()
    source = root / video["path"]
    source_bytes = source.read_bytes()
    monkeypatch.setattr(audio, "extract_audio_cues", lambda *_: copy.deepcopy(cues))
    with TestClient(create_app(root, data)) as client:
        base = f"/api/videos/{video['id']}"
        response = client.post(
            base + "/contacts",
            json={
                "shuttle_run_id": "shuttle",
                "player_run_id": "players",
                "include_audio": True,
            },
        )
        if case in {"bound_pose_mismatch", "bound_pose_duplicate"}:
            assert response.status_code == 422, response.text
            assert len(store.jobs()) == 2
            assert set((data / video["id"] / "runs").glob("*.json")) == set(
                original_bytes
            )
            assert revisions() == original_revisions
            assert source.read_bytes() == source_bytes
            assert all(path.read_bytes() == raw for path, raw in original_bytes.items())
            return
        assert response.status_code == 202, response.text
        job = wait(store, response.json()["id"])
        assert job["status"] == "completed", job
        path = data / video["id"] / "runs" / f"{job['id']}.json"
        raw_bytes = path.read_bytes()
        result = json.loads(raw_bytes)
        assert len(result["candidates"]) == expected
        assert revisions() == original_revisions
        assert source.read_bytes() == source_bytes
        assert all(
            path.read_bytes() == original for path, original in original_bytes.items()
        )
        if expected:
            candidate = result["candidates"][0]
            onset = cues["peaks"][0]["time_s"]
            assert candidate["start_time_s"] <= onset - 0.12
            assert candidate["end_time_s"] >= onset + 0.12
            assert candidate["context_start_frame"] <= candidate["start_frame"]
            assert candidate["context_end_frame"] > candidate["end_frame"]
            assert candidate["interval_bounds"] == "inclusive"
            assert not client.get(base + "/runs/" + job["id"]).json()["candidates"][0][
                "scene_excluded"
            ]
            # A later explicit unknown at the inclusive endpoint must exclude
            # the proposal through the unchanged existing review endpoint.
            current = store.annotations(video["id"])
            current.scene_ranges.append(
                SceneRange(
                    id="later-unknown",
                    start_frame=candidate["end_frame"],
                    end_frame=candidate["end_frame"] + 1,
                    scene="unknown",
                )
            )
            store.save_annotations(video["id"], current)
            refreshed = client.get(base + "/runs/" + job["id"]).json()
            assert refreshed["candidates"][0]["scene_excluded"] is True
            assert path.read_bytes() == raw_bytes
            assert revisions()[:2] == original_revisions
