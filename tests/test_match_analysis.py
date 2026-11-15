"""MatchAnalysis builder on a small synthetic two-window, two-view singles match."""

import json

import pytest
from badminton.match_analysis import (
    COURT_LENGTH_M,
    COURT_WIDTH_M,
    MatchAnalysis,
    MatchInputs,
    build_match_analysis,
    court_homography,
    match_analysis_path,
    project,
    read_match_analysis,
    write_match_analysis,
)

W, H, FPS, FRAMES = 1000, 500, 25.0, 300
CUT = 200
CORNERS = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
FAR, NEAR = (3.0, 2.0), (3.0, 11.0)


def pixel(metres):
    x, y = metres
    return (0.2 + x / COURT_WIDTH_M * 0.6) * W, (0.2 + y / COURT_LENGTH_M * 0.6) * H


def person(track, metres):
    px, py = pixel(metres)
    return {"track_id": track, "box": [px - 20, py - 80, px + 20, py]}


def signature(start, end):
    return [start, end, [list(c) for c in CORNERS]]


def calibration(start, end):
    return {
        "start_frame": start,
        "end_frame": end,
        "corners": [{"x": x, "y": y} for x, y in CORNERS],
    }


def players_run(run_id, start, end, tracks, signatures, automatic):
    """tracks(frame) -> [(track_id, metres), ...] observed at that frame."""
    return {
        "stage": "players",
        "video_id": "v",
        "run_id": run_id,
        "start_frame": start,
        "end_frame": end,
        "model": "pose-model",
        "checkpoint_sha256": "a" * 64,
        "calibration_signature": signatures,
        "automatic_calibrations": automatic,
        "frames": [
            {
                "frame": f,
                "time_s": f / FPS,
                "players": [person(t, m) for t, m in tracks(f)],
                "camera_segment_start_frame": CUT if f >= CUT else 0,
                "calibration_valid": not 100 <= f < 110,
            }
            for f in range(start, end)
        ],
    }


def shuttle_run(start, end):
    def point(f):
        if f % 2 or 60 <= f <= 70:
            return {"visible": False, "x": None, "y": None}
        return {"visible": True, "x": 500.0, "y": 250.0}

    return {
        "stage": "shuttle",
        "video_id": "v",
        "start_frame": start,
        "end_frame": end,
        "model": "shuttle-model",
        "checkpoint_sha256": "b" * 64,
        "frames": [{"frame": f, "shuttle": point(f)} for f in range(start, end)],
    }


def contact(frame, track, learned=None):
    result = {"id": f"contact-{frame}", "frame": frame, "score": 0.9, "track_id": track}
    if learned:
        result["learned"] = learned
    return result


def fixture():
    """Window A: frames 0..170 (core 0..150). Window B: 130..300 (core 150..300).

    A camera cut at frame 200 resets the tracker; after it the players have
    changed ends: the near track 6 is the person who was far before.
    """

    def tracks_a(f):
        return [(1, FAR), (2, NEAR)]

    def tracks_b(f):
        return [(1, FAR), (2, NEAR)] if f < CUT else [(5, FAR), (6, NEAR)]

    runs = {
        "pA": players_run(
            "pA",
            0,
            170,
            tracks_a,
            [signature(0, 100), signature(110, 170)],
            [calibration(0, 100), calibration(110, 170)],
        ),
        "pB": players_run(
            "pB",
            130,
            300,
            tracks_b,
            [signature(110, 200), signature(200, 300)],
            [calibration(110, 200)],  # the second view was reviewed
        ),
        "sA": shuttle_run(0, 170),
        "sB": shuttle_run(130, 300),
        "cA": {
            "stage": "contacts",
            "video_id": "v",
            "method": "event model",
            "recipe": {"event_model_sha256": "c" * 64},
            "player_run_id": "pA",
            "candidates": [
                contact(20, 2),
                contact(40, 1),
                contact(65, 2),
                contact(160, 1),  # halo: owned by window B
            ],
        },
        "rA": {
            "stage": "recognition",
            "video_id": "v",
            "model": "event model",
            "checkpoint_sha256": "c" * 64,
            "candidates": [
                {
                    "frame": 20,
                    "contact_candidate_id": "contact-20",
                    "kind": "serve",
                    "family": None,
                    "family_score": 0.99,
                    "side": "backhand",
                    "side_score": 0.8,
                    "serve_type": "short",
                    "hitter_hint": {"track_id": 2},
                },
                {
                    "frame": 40,
                    "contact_candidate_id": "contact-40",
                    "kind": "shot",
                    "family": "net kill",
                    "family_score": 0.7,
                    "side": "forehand",
                    "side_score": 0.6,
                    "hitter_hint": {"track_id": 1},
                },
                {
                    "frame": 65,
                    "contact_candidate_id": "contact-65",
                    "kind": "shot",
                    "family": "mystery",
                    "family_score": 0.5,
                    "side": "unknown",
                    "side_score": 0.55,
                    "hitter_hint": {"track_id": 2},
                },
            ],
        },
        "cB": {
            "stage": "contacts",
            "video_id": "v",
            "method": "event model",
            "player_run_id": "pB",
            "candidates": [
                contact(145, 1),  # halo: owned by window A, which has none there
                contact(
                    170, 1, {"kind": "shot", "family": "smash", "side": "forehand"}
                ),
                contact(185, 2),
                contact(210, 6, {"kind": "serve", "serve_type": "long"}),
                contact(230, 5, {"kind": "shot", "family": "clear"}),
                contact(250, None, {"kind": "shot", "family": "drive"}),
            ],
        },
    }
    plan = {
        "analysis_key": "k" * 64,
        "video_id": "v",
        "processing_complete": True,
        "parts": [
            {
                "window": {"index": 0, "core_start_frame": 0, "core_end_frame": 150},
                "stages": {
                    "players": {"run_id": "pA"},
                    "shuttle": {"run_id": "sA"},
                    "contacts": {"run_id": "cA"},
                    "recognition": {"run_id": "rA"},
                },
            },
            {
                "window": {"index": 1, "core_start_frame": 150, "core_end_frame": 300},
                "stages": {
                    "players": {"run_id": "pB"},
                    "shuttle": {"run_id": "sB"},
                    "contacts": {"run_id": "cB"},
                },
            },
        ],
    }
    video = {
        "id": "v",
        "name": "synthetic.mp4",
        "mode": "singles",
        "fps": FPS,
        "frame_count": FRAMES,
        "duration_s": FRAMES / FPS,
        "width": W,
        "height": H,
    }
    return MatchInputs(video, [f / FPS for f in range(FRAMES)], plan, runs)


IDENTITY = {
    "persons": [
        {"id": "P1", "team": "T1", "name": "Ann"},
        {"id": "P2", "team": "T2", "name": "Bo", "unused_extra": 1},
    ],
    "assignments": [
        {
            "run_id": "pA",
            "track_id": 1,
            "start_frame": 0,
            "end_frame": 170,
            "player_id": "P1",
        },
        {
            "run_id": "pA",
            "track_id": 2,
            "start_frame": 0,
            "end_frame": 170,
            "player_id": "P2",
        },
        {
            "run_id": "pB",
            "track_id": 1,
            "start_frame": 130,
            "end_frame": 200,
            "player_id": "P1",
        },
        {
            "run_id": "pB",
            "track_id": 2,
            "start_frame": 130,
            "end_frame": 200,
            "player_id": "P2",
        },
        {
            "run_id": "pB",
            "track_id": 6,
            "start_frame": 200,
            "end_frame": 300,
            "player_id": "P1",
        },
        {
            "run_id": "pB",
            "track_id": 5,
            "start_frame": 200,
            "end_frame": 300,
            "player_id": "P2",
        },
    ],
    "method": "test identity",
}


def shots(document):
    return {s.frame: s for r in document.rallies for s in r.shots}


def test_homography_maps_corners_to_court_metres():
    matrix = court_homography(CORNERS)
    targets = [(0, 0), (COURT_WIDTH_M, 0), (COURT_WIDTH_M, COURT_LENGTH_M), (0, 13.4)]
    for (x, y), (u, v) in zip(CORNERS, targets, strict=True):
        assert project(matrix, x, y) == pytest.approx((u, v), abs=1e-9)
    assert project(matrix, 0.5, 0.5) == pytest.approx((3.05, 6.7))
    # A perspective view like the broadcast fits (far baseline narrower).
    trapezoid = [(0.346, 0.361), (0.655, 0.361), (0.774, 0.908), (0.224, 0.908)]
    matrix = court_homography(trapezoid)
    for (x, y), (u, v) in zip(trapezoid, targets, strict=True):
        assert project(matrix, x, y) == pytest.approx((u, v), abs=1e-6)
    net = project(matrix, 0.5, 0.55)
    assert 0 < net[1] < COURT_LENGTH_M
    assert court_homography([(0.1, 0.1), (0.2, 0.2), (0.3, 0.3), (0.4, 0.4)]) is None


def test_schema_round_trip_and_unknowns_stay_null(tmp_path):
    document = build_match_analysis(
        fixture(), IDENTITY, created_at="2026-11-15T00:00:00+00:00"
    )
    text = document.model_dump_json()
    assert MatchAnalysis.model_validate_json(text) == document
    assert (
        MatchAnalysis.model_json_schema()["properties"]["schema_version"]["const"] == 2
    )
    assert document.video.duration_s == 12.0
    assert [p.name for p in document.players] == ["Ann", "Bo"]
    assert all(p.handedness is None and p.thumbnail is None for p in document.players)

    views = [(v.start_frame, v.end_frame, v.source) for v in document.court.views]
    assert views == [
        (0, 100, "automatic"),
        (110, 200, "automatic"),
        (200, 300, "reviewed"),
    ]

    by_frame = shots(document)
    assert sorted(by_frame) == [
        20,
        40,
        65,
        170,
        185,
        210,
        230,
        250,
    ]  # halo copies dropped
    serve = by_frame[20]
    assert (serve.kind, serve.family, serve.serve_type, serve.side) == (
        "serve",
        None,
        "short",
        "backhand",
    )
    assert serve.hitter_position.model_dump() == pytest.approx({"x": 3.0, "y": 11.0})
    assert serve.shuttle.model_dump() == {"x": 0.5, "y": 0.5}
    assert {p.person_id: (p.position.x, p.position.y) for p in serve.players} == {
        "P1": (3.0, 2.0),
        "P2": (3.0, 11.0),
    }
    assert by_frame[40].family == "net_kill"
    unknown = by_frame[65]
    assert (unknown.family, unknown.side, unknown.side_score, unknown.shuttle) == (
        None,
        None,
        None,
        None,
    )
    assert by_frame[185].kind is None and by_frame[185].family is None
    no_track = by_frame[250]
    assert (no_track.hitter_id, no_track.hitter_position) == (None, None)
    assert len(no_track.players) == 2
    assert all(s.landing is None for s in by_frame.values())
    assert all(r.outcome is None for r in document.rallies)

    # The 10 Hz tracks have no position in the frames without a court fit.
    tracks = document.tracks
    assert tracks.rate_hz == 10 and len(tracks.sample_frames) == 120
    assert tracks.sample_frames[0] == 0 and tracks.sample_frames[2] == 5
    p1 = next(t for t in tracks.persons if t.person_id == "P1")
    blind = [i for i, f in enumerate(tracks.sample_frames) if 100 <= f < 110]
    assert blind and all(p1.x[i] is None for i in blind)
    assert p1.y[0] == 2.0 and p1.y[-1] == 11.0  # P1 changed ends after the cut
    assert len(tracks.shuttle.x) == FRAMES
    assert tracks.shuttle.x[0] == 0.5 and tracks.shuttle.x[1] is None

    provenance = document.provenance
    assert provenance.analysis_key == "k" * 64
    assert [p.recognition_run_id for p in provenance.parts] == ["rA", None]
    assert {m.stage for m in provenance.models} == {
        "players",
        "shuttle",
        "contacts",
        "recognition",
    }

    # The stored file reads back identically.
    path = write_match_analysis(tmp_path, document)
    assert (
        path
        == match_analysis_path(tmp_path, "v")
        == tmp_path / "v" / "match_analysis.json"
    )
    assert read_match_analysis(tmp_path, "v") == document
    assert read_match_analysis(tmp_path, "other") is None
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2


def test_rallies_split_at_serves_gaps_and_cuts():
    document = build_match_analysis(fixture(), IDENTITY)
    rallies = [
        (r.start_frame, r.end_frame, r.server_id, len(r.shots))
        for r in document.rallies
    ]
    # 65 -> 170 is 4.2 s without a contact; 210 is a serve after a cut.
    assert rallies == [(20, 65, "P2", 3), (170, 185, None, 2), (210, 250, "P1", 3)]
    first = document.rallies[0]
    assert (first.start_s, first.end_s) == (0.8, 2.6)


def test_supplied_identity_holds_across_windows_and_views():
    document = build_match_analysis(fixture(), IDENTITY)
    by_frame = shots(document)
    assert document.identity.source == "supplied" and document.identity.persistent
    assert document.identity.assigned_observation_share == 1.0
    # Track 1 of window A, track 1 of window B and track 6 after the cut.
    assert [by_frame[f].hitter_id for f in (40, 170, 210, 230)] == [
        "P1",
        "P1",
        "P1",
        "P2",
    ]
    assert by_frame[210].hitter_position.y == 11.0  # P1 now at the near end


def test_fallback_is_per_view_and_says_so():
    document = build_match_analysis(fixture())
    identity = document.identity
    assert identity.source == "per_view_fallback" and not identity.persistent
    assert "Not persistent" in identity.note
    assert [(p.id, p.name, p.team) for p in document.players] == [
        ("P1", "", "T1"),
        ("P2", "", "T2"),
    ]
    by_frame = shots(document)
    # Far player is P1 in every view: after the end change the near hitter
    # (the same human as before) is labelled P2.
    assert [by_frame[f].hitter_id for f in (20, 40, 170, 210, 230)] == [
        "P2",
        "P1",
        "P1",
        "P2",
        "P1",
    ]
    assert identity.assignment_count == 6


def test_fallback_groups_tracks_by_continuity():
    inputs = fixture()
    inputs.plan["identities"] = {"run_id": "ids"}
    inputs.runs["ids"] = {
        "stage": "identities",
        "tracks": [
            {"run_id": "pA", "track_id": 1, "continuity_id": "far-a"},
            {"run_id": "pB", "track_id": 1, "continuity_id": "far-a"},
        ],
    }
    document = build_match_analysis(inputs)
    assert document.provenance.identities_run_id == "ids"
    assert shots(document)[170].hitter_id == "P1"


def test_identity_input_is_validated():
    bad = json.loads(json.dumps(IDENTITY))
    bad["assignments"][0]["player_id"] = "P3"
    with pytest.raises(ValueError, match="Unknown player"):
        build_match_analysis(fixture(), bad)
    overlap = json.loads(json.dumps(IDENTITY))
    overlap["assignments"][1]["player_id"] = "P1"
    with pytest.raises(ValueError, match="overlapping"):
        build_match_analysis(fixture(), overlap)
    with pytest.raises(ValueError):
        build_match_analysis(
            fixture(), {"persons": IDENTITY["persons"][:1], "assignments": []}
        )


def test_match_analysis_endpoint(tmp_path):
    from badminton.api import create_app
    from badminton.storage import Store
    from fastapi.testclient import TestClient

    data = tmp_path / "data"
    app = create_app(root=tmp_path, data=data)
    Store(data).register({"id": "v", "mode": "singles"})
    with TestClient(app) as client:
        assert client.get("/api/videos/v/match-analysis").status_code == 404
        assert client.get("/api/videos/unknown/match-analysis").status_code == 404
        document = build_match_analysis(fixture(), IDENTITY)
        write_match_analysis(data, document)
        response = client.get("/api/videos/v/match-analysis")
        assert response.status_code == 200
        assert MatchAnalysis.model_validate(response.json()) == document
        schema = client.get("/openapi.json").json()["components"]["schemas"]
        assert "MatchAnalysis" in schema and "Shot" in schema


def test_identity_artifact_extra_keys_are_ignored():
    artifact = json.loads(json.dumps(IDENTITY))
    del artifact["method"]
    artifact["schema_version"] = 1
    artifact["provenance"] = {"method": "looks v1", "recipe": {}}
    for item in artifact["assignments"]:
        item["certainty"] = 0.9
    document = build_match_analysis(fixture(), artifact)
    assert document.identity.method == "looks v1"
    assert shots(document)[210].hitter_id == "P1"


def with_proposals(inputs, a, b):
    """Add rallies-stage runs: window A proposes `a`, window B `b`."""
    for index, (run_id, candidates) in enumerate((("yA", a), ("yB", b))):
        inputs.plan["parts"][index]["stages"]["rallies"] = {"run_id": run_id}
        inputs.runs[run_id] = {
            "stage": "rallies",
            "video_id": "v",
            "candidates": [
                {"kind": kind, "frame": frame} for kind, frame in candidates
            ],
        }
    return inputs


def test_rally_boundaries_come_from_proposals_first():
    inputs = with_proposals(
        fixture(),
        # A serve just before contact 20, a rally end after contact 65, a
        # serve at 100 without a contact, and a halo copy that B owns.
        [("serve", 18), ("rally_end", 75), ("serve", 100), ("serve", 160)],
        # A serve next to contact 185 splits a quick exchange.
        [("serve", 195)],
    )
    document = build_match_analysis(inputs, IDENTITY)
    rallies = [
        (
            r.start_frame,
            r.end_frame,
            r.start_source,
            r.end_source,
            r.server_id,
            [s.frame for s in r.shots],
        )
        for r in document.rallies
    ]
    assert rallies == [
        (20, 75, "proposed_serve", "proposed_rally_end", "P2", [20, 40, 65]),
        # Contact 170 follows the unmatched serve proposal within 4 s; its
        # serve contact was not detected, so the server is unknown.
        (100, 170, "proposed_serve", "last_contact", None, [170]),
        (185, 185, "proposed_serve", "last_contact", "P2", [185]),
        # No proposal between 185 and 210: the fallback's predicted serve.
        (210, 250, "predicted_serve", "last_contact", "P1", [210, 230, 250]),
    ]
    assert document.rallies[0].end_s == 3.0
    assert [p.rallies_run_id for p in document.provenance.parts] == ["yA", "yB"]


def test_rally_end_proposal_opens_the_next_rally_and_far_proposals_are_ignored():
    inputs = with_proposals(
        fixture(),
        # 75: after 65 (ends rally 1); 140: 3 s after 65, but rally 1 already
        # has its end.
        [("rally_end", 75), ("rally_end", 140)],
        # 290: 1.6 s after the last contact ends the last rally; no contact
        # follows the serve at 270, so it opens nothing.
        [("rally_end", 290), ("serve", 270)],
    )
    document = build_match_analysis(inputs, IDENTITY)
    rallies = [
        (r.start_frame, r.end_frame, r.start_source, r.end_source)
        for r in document.rallies
    ]
    assert rallies == [
        (20, 75, "first_contact", "proposed_rally_end"),
        (170, 185, "after_proposed_end", "last_contact"),
        (210, 290, "predicted_serve", "proposed_rally_end"),
    ]


def test_rallies_without_proposals_record_the_fallback_sources():
    document = build_match_analysis(fixture(), IDENTITY)
    assert [(r.start_source, r.end_source) for r in document.rallies] == [
        ("first_contact", "last_contact"),
        ("contact_gap", "last_contact"),
        ("predicted_serve", "last_contact"),
    ]


def persons_inputs():
    inputs = fixture()
    inputs.plan["persons"] = {"run_id": "persons-run", "sha256": "f" * 64}
    identity = json.loads(json.dumps(IDENTITY))
    del identity["method"]
    identity["provenance"] = {"method": "looks-only person grouping v1"}
    identity["persons"][0]["thumbnail"] = "persons/persons-run/P1.jpg"
    for person in identity["persons"]:
        person.pop("name")
    inputs.identity = identity
    return inputs


def test_persons_stage_document_is_the_identity_by_default():
    document = build_match_analysis(persons_inputs())
    identity = document.identity
    assert (identity.source, identity.persistent) == ("persons_stage", True)
    assert identity.method == "looks-only person grouping v1"
    assert "persons stage" in identity.note
    assert document.provenance.persons_run_id == "persons-run"
    assert document.players[0].thumbnail == "persons/persons-run/P1.jpg"
    assert not document.names_confirmed and document.warnings == []
    assert shots(document)[210].hitter_id == "P1"
    # A supplied identity still wins.
    supplied = build_match_analysis(persons_inputs(), IDENTITY)
    assert supplied.identity.source == "supplied"


def test_missing_identity_weights_fall_back_with_a_warning():
    inputs = fixture()
    inputs.plan["persons"] = None
    inputs.plan["persons_unavailable"] = (
        "Player re-identification weights are not installed (reid/x.pth)"
    )
    document = build_match_analysis(inputs)
    identity = document.identity
    assert identity.source == "per_view_fallback" and not identity.persistent
    assert identity.note.startswith("Player re-identification weights are not")
    assert len(document.warnings) == 1
    assert "not installed" in document.warnings[0]
    assert "per camera view" in document.warnings[0]
    # Without a reason the fallback still warns.
    assert "per camera view" in build_match_analysis(fixture()).warnings[0]


def test_confirmed_names_fill_players():
    document = build_match_analysis(persons_inputs(), names={"P1": " Ann ", "P2": "Bo"})
    assert [p.name for p in document.players] == ["Ann", "Bo"]
    assert document.names_confirmed
    with pytest.raises(ValueError, match="name every person"):
        build_match_analysis(persons_inputs(), names={"P1": "Ann"})
    with pytest.raises(ValueError, match="name every person"):
        build_match_analysis(persons_inputs(), names={"P1": "Ann", "P2": " "})


def test_swap_overrides_apply_to_one_range_in_order():
    inputs = persons_inputs()
    plain = build_match_analysis(inputs)
    swap = {"persons": ["P1", "P2"], "start_frame": 20, "end_frame": 65}
    document = build_match_analysis(inputs, overrides=[swap])
    before, after = shots(plain), shots(document)
    for frame in (20, 40, 65):
        assert {before[frame].hitter_id, after[frame].hitter_id} == {"P1", "P2"}
        assert before[frame].hitter_id != after[frame].hitter_id
        assert {p.person_id for p in after[frame].players} == {"P1", "P2"}
    assert all(after[f].hitter_id == before[f].hitter_id for f in (170, 210, 230))
    assert document.rallies[0].server_id == "P1"  # was P2
    assert document.overrides[0].persons == ("P1", "P2")
    p1 = {t.person_id: t for t in document.tracks.persons}["P1"]
    old = {t.person_id: t for t in plain.tracks.persons}["P2"]
    inside = [i for i, f in enumerate(document.tracks.sample_frames) if 20 <= f <= 65]
    assert inside and all(p1.y[i] == old.y[i] for i in inside)
    # The same swap twice is no swap at all.
    twice = build_match_analysis(inputs, overrides=[swap, swap])
    assert [s.hitter_id for s in shots(twice).values()] == [
        s.hitter_id for s in before.values()
    ]
    with pytest.raises(ValueError):
        build_match_analysis(inputs, overrides=[swap | {"persons": ["P1", "P3"]}])
