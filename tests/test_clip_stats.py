"""Clip statistics on small synthetic MatchAnalysis documents."""

import pytest
from badminton.clip_stats import (
    ClipStats,
    _Context,
    clip_stats,
    distance_of,
    label,
    turned,
)
from badminton.match_analysis import (
    COURT_LENGTH_M,
    COURT_WIDTH_M,
    Court,
    CourtView,
    IdentityInfo,
    ImagePoint,
    Landing,
    MatchAnalysis,
    Person,
    PersonTrack,
    PlayerPosition,
    Provenance,
    Rally,
    RallyOutcome,
    Shot,
    ShotFlight,
    ShuttleTrack,
    Tracks,
    VideoInfo,
    build_match_analysis,
    court_homography,
)

FPS, FRAMES = 10.0, 300
CORNERS = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
# Doubles: T1 (P1, P2) at the far end, T2 (P3, P4) at the near end.
HOME = {"P1": (3.0, 4.5), "P2": (3.0, 1.5), "P3": (1.5, 10.0), "P4": (4.5, 10.0)}


def flight(speed, quality="good", settled=None):
    return ShotFlight(
        initial_speed_kmh=speed,
        speed_settled_kmh=settled if settled is not None else min(speed, 120) / 2,
        apex_m=3.0,
        quality=quality,
        rms=0.004,
        points=12,
        inliers=12,
    )


def shot(frame, hitter, kind="shot", family=None, side=None, serve_type=None, **kw):
    position = HOME.get(hitter)
    return Shot(
        id=f"shot-{frame}",
        frame=frame,
        time_s=frame / FPS,
        kind=kind,
        hitter_id=hitter,
        family=family,
        side=side,
        serve_type=serve_type,
        hitter_position=None if position is None else dict(zip("xy", position)),
        players=[
            PlayerPosition(person_id=p, position=dict(zip("xy", xy)))
            for p, xy in HOME.items()
        ],
        **kw,
    )


def landing(frame, x, y, kind="rest", in_court=True):
    return Landing(
        frame=frame,
        time_s=frame / FPS,
        image=ImagePoint(x=0.5, y=0.5),
        position=None if x is None else {"x": x, "y": y},
        in_court=in_court,
        kind=kind,
        source="test",
    )


def rallies():
    """Rally 1 (T1 wins with P2's smash), rally 2 (P4's net error: T1 wins),
    rally 3 (a lone serve, outcome unknown)."""
    one = Rally(
        id="rally-1",
        start_frame=10,
        end_frame=60,
        start_s=1.0,
        end_s=6.0,
        start_source="proposed_serve",
        end_source="landing",
        server_id="P3",
        shots=[
            shot(10, "P3", "serve", serve_type="short", flight=flight(30)),
            shot(20, "P1", family="push", side="forehand", flight=flight(80)),
            shot(30, "P4", family="lift", side="backhand", flight=flight(100)),
            shot(40, "P2", family="smash", side="forehand", flight=flight(300)),
            shot(50, "P3", family="block", side="backhand", flight=flight(50)),
            shot(
                55,
                "P2",
                family="smash",
                side="forehand",
                flight=flight(449, "speed_bound", 110),
                landing=landing(60, 3.0, 11.0),
            ),
        ],
        outcome=RallyOutcome(
            winner_team="T1",
            winner_end="far",
            last_hitter_end="far",
            reason="winner",
            detail="in",
            source="rule",
        ),
    )
    two = Rally(
        id="rally-2",
        start_frame=100,
        end_frame=140,
        start_s=10.0,
        end_s=14.0,
        start_source="predicted_serve",
        end_source="proposed_rally_end",
        server_id="P1",
        shots=[
            shot(100, "P1", "serve", serve_type="long", flight=flight(90)),
            shot(110, "P3", family="clear", side="forehand", flight=flight(150)),
            shot(120, "P2", family="smash", side="forehand", flight=flight(260)),
            shot(125, "P4", family="lift", flight=flight(120, "poor_fit")),
            shot(130, None, family="drive"),  # hitter unknown
            shot(135, "P4", family="net", landing=landing(140, 3.0, 7.0)),
        ],
        outcome=RallyOutcome(
            winner_team="T1",
            winner_end="far",
            last_hitter_end="near",
            reason="error",
            detail="net",
            source="rule",
        ),
    )
    three = Rally(
        id="rally-3",
        start_frame=200,
        end_frame=200,
        start_s=20.0,
        end_s=20.0,
        start_source="proposed_serve",
        end_source="last_contact",
        server_id="P3",
        shots=[shot(200, "P3", "serve", serve_type=None)],
    )
    return [one, two, three]


def tracks(positions=None):
    """10 Hz tracks: every player at home unless ``positions`` gives
    person -> {sample: (x, y) or None}."""
    positions = positions or {}
    persons = []
    for person, (x, y) in HOME.items():
        own = positions.get(person, {})
        xs, ys = [], []
        for k in range(FRAMES):
            point = own.get(k, (x, y))
            xs.append(None if point is None else point[0])
            ys.append(None if point is None else point[1])
        persons.append(PersonTrack(person_id=person, x=xs, y=ys))
    return Tracks(
        rate_hz=10,
        sample_frames=list(range(FRAMES)),
        persons=persons,
        shuttle=ShuttleTrack(x=[None] * FRAMES, y=[None] * FRAMES),
    )


def document(mode="doubles", rally_list=None, track=None, views=True, flights=True):
    players = (
        [Person(id=p, team="T1" if p in ("P1", "P2") else "T2") for p in HOME]
        if mode == "doubles"
        else [Person(id="P1", team="T1"), Person(id="P2", team="T2")]
    )
    return MatchAnalysis(
        video=VideoInfo(
            id="v",
            mode=mode,
            fps=FPS,
            frame_count=FRAMES,
            duration_s=FRAMES / FPS,
            width=1000,
            height=500,
        ),
        players=players,
        identity=IdentityInfo(
            source="supplied",
            method="test",
            persistent=True,
            note="test",
            assignment_count=4,
        ),
        court=Court(
            views=[
                CourtView(
                    start_frame=0,
                    end_frame=FRAMES,
                    corners=[ImagePoint(x=x, y=y) for x, y in CORNERS],
                    homography=court_homography(CORNERS),
                    source="automatic",
                )
            ]
            if views
            else []
        ),
        rallies=rally_list if rally_list is not None else rallies(),
        tracks=track or tracks(),
        provenance=Provenance(
            created_at="2026-11-17T00:00:00+00:00",
            analysis_key="k" * 64,
            shot_flights=flights,
            parts=[],
            models=[],
        ),
    )


def player(stats, person):
    return next(p for p in stats.players if p.person_id == person)


def team(stats, name):
    return next(t for t in stats.teams if t.team == name)


def test_round_trip_version_and_sample_sizes():
    stats = clip_stats(document())
    assert ClipStats.model_validate_json(stats.model_dump_json()) == stats
    schema = ClipStats.model_json_schema()
    assert schema["properties"]["stats_version"]["const"] == 1
    assert stats.analysis_schema_version == 4 and stats.mode == "doubles"
    assert stats.identity_persistent and stats.shot_flights and stats.warnings == []
    assert [p.person_id for p in stats.players] == ["P1", "P2", "P3", "P4"]
    assert [t.person_ids for t in stats.teams] == [["P1", "P2"], ["P3", "P4"]]


def test_labels_and_turning():
    serve = shot(1, "P1", "serve", serve_type="long")
    assert label(serve) == "serve_long"
    assert label(shot(1, "P1", "serve")) == "serve"
    assert label(shot(1, "P1", family="net_kill")) == "net_kill"
    assert label(shot(1, "P1", None)) == "unknown"
    assert label(shot(1, "P1")) == "unknown"
    assert turned(1.0, 2.0, "far") == pytest.approx((5.1, 11.4))
    assert turned(1.0, 12.0, "near") == (1.0, 12.0)


def test_shot_breakdown_and_rally_lengths():
    stats = clip_stats(document())
    clip = stats.clip
    assert (clip.rallies, clip.contacts, clip.unattributed_contacts) == (3, 13, 1)
    assert clip.rally_shots.n == 3 and clip.rally_shots.median == 6
    assert clip.rally_shots.counts[0] == 1 and clip.rally_shots.counts[5] == 2
    assert clip.rally_seconds.median == 4.0 and clip.rally_seconds.max == 5.0
    assert clip.rally_seconds.counts[0] == 1  # the lone serve: 0 s
    assert clip.rallies_ended_at_landing.model_dump() == {
        "count": 1,
        "n": 3,
        "share": 0.3333,
    }
    assert clip.outcomes_known.count == 2
    shots = clip.shots
    assert (shots.contacts, shots.serves, shots.shots, shots.unknown_kind) == (
        13,
        3,
        10,
        0,
    )
    assert shots.families["smash"].model_dump() == {"count": 3, "n": 10, "share": 0.3}
    assert shots.serve_types["unknown"].count == 1
    assert shots.sides["unknown"].count == 3
    assert shots.forehand_by_family["lift"].model_dump() == {
        "count": 0,
        "n": 1,
        "share": 0.0,
    }
    p2 = player(stats, "P2").shots
    assert (p2.contacts, p2.shots) == (3, 3)
    assert p2.families["smash"].share == 1.0
    t2 = team(stats, "T2").shots
    assert t2.contacts == 7 and t2.serves == 2


def test_winners_errors_consistency_and_rallies_won():
    stats = clip_stats(document())
    t1, t2 = team(stats, "T1"), team(stats, "T2")
    assert t1.rallies_won.model_dump() == {"count": 2, "n": 2, "share": 1.0}
    assert t2.rallies_won.model_dump() == {"count": 0, "n": 2, "share": 0.0}
    assert (t1.won_by_winner, t1.won_by_opponent_error) == (1, 1)
    p2, p4 = player(stats, "P2"), player(stats, "P4")
    assert p2.finish.ended == 1 and p2.finish.winners.count == 1
    smash = p2.finish.by_label["smash"]
    assert (smash.played, smash.winners, smash.errors) == (3, 1, 0)
    assert smash.consistency.share == 1.0 and smash.winner_rate.count == 1
    net = p4.finish.by_label["net"]
    assert (net.played, net.errors, net.errors_net, net.errors_out) == (1, 1, 1, 0)
    assert net.consistency.model_dump() == {"count": 0, "n": 1, "share": 0.0}
    assert p4.finish.by_label["lift"].played == 2
    # The lone serve of rally 3 has no known outcome: not played.
    p3 = player(stats, "P3").finish.by_label
    assert p3["serve_short"].played == 1 and "serve" not in p3
    assert stats.clip.outcome_conflicts == 0


def test_outcome_conflicting_with_the_hitter_is_left_out():
    rally_list = rallies()
    # The last hitter (P2, T1) "won", but the outcome gives the rally to T2.
    rally_list[0] = rally_list[0].model_copy(
        update={
            "outcome": rally_list[0].outcome.model_copy(update={"winner_team": "T2"})
        }
    )
    stats = clip_stats(document(rally_list=rally_list))
    assert stats.clip.outcome_conflicts == 1
    assert player(stats, "P2").finish.ended == 0
    assert player(stats, "P2").finish.by_label["smash"].played == 2
    # Rallies won still count the team the outcome names.
    assert team(stats, "T2").rallies_won.count == 1


def test_serve_and_receive():
    stats = clip_stats(document())
    p3 = player(stats, "P3")
    assert p3.serve.serves == 2
    assert p3.serve.serve_types["short"].count == 1
    assert p3.serve.serve_types["unknown"].count == 1
    # Rally 1 lost; rally 3 has no outcome.
    assert p3.serve.won.model_dump() == {"count": 0, "n": 1, "share": 0.0}
    assert p3.serve.faults.n == 1 and p3.serve.unreturned.count == 0
    assert len(p3.serve.positions) == 2
    p1 = player(stats, "P1")
    assert p1.receive.returns == 1 and p1.receive.families["push"].count == 1
    assert p1.receive.won.model_dump() == {"count": 1, "n": 1, "share": 1.0}
    assert team(stats, "T2").receive.returns == 1  # P3 returned P1's serve
    assert team(stats, "T1").serve.won.share == 1.0


def test_maps_turn_the_player_to_the_near_end():
    stats = clip_stats(document())
    p2 = player(stats, "P2")
    # P2 stands at (3.0, 1.5) at the far end: turned to the near end.
    assert {(c.x, c.y) for c in p2.contacts} == {(3.1, 11.9)}
    (spot,) = p2.landings
    # The far hitter's smash landed near (3.0, 11.0): it shows at the far end.
    assert (spot.x, spot.y, spot.label, spot.result) == (3.1, 2.4, "smash", "winner")
    assert spot.in_court and spot.kind == "rest"
    # P4's net error lands on its own (near) side.
    (net,) = player(stats, "P4").landings
    assert (net.x, net.y, net.result) == (3.0, 7.0, "error")
    assert len(stats.clip.landings) == 2
    # Where the other side played P2's smashes: P3 (block) at the near end,
    # seen with P2 at the near end.
    returned = player(stats, "P2").returned_at
    assert [(r.label, r.x, r.y) for r in returned] == [
        ("smash", 4.6, 3.4),
        ("smash", 1.6, 3.4),
    ]
    grid = p2.positions
    assert grid.n == 51 + 41 + 1 and grid.outside == 0
    assert len(grid.counts) == len(grid.y_edges) - 1 == 30
    assert len(grid.counts[0]) == len(grid.x_edges) - 1 == 16
    assert grid.x_edges[2] == 0 and grid.y_edges[-3] == COURT_LENGTH_M
    assert sum(map(sum, grid.counts)) == grid.n
    row = next(i for i, r in enumerate(grid.counts) if any(r))
    assert grid.y_edges[row] <= COURT_LENGTH_M - 1.5 < grid.y_edges[row + 1]


def test_track_end_landings_and_unknown_hitter_ends_are_left_off_the_map():
    rally_list = rallies()
    last = rally_list[0].shots[-1]
    rally_list[0].shots[-1] = last.model_copy(
        update={"landing": landing(60, 3.0, 11.0, "track_end")}
    )
    stats = clip_stats(document(rally_list=rally_list))
    assert player(stats, "P2").landings == []
    assert len(stats.clip.landings) == 1


def test_distance_handles_glitches_gaps_and_jitter():
    # P1 runs along x at 1 m/s through rally 1 (samples 10..60), with one
    # glitch sample, a 0.3 s gap that is bridged and nothing after 50.
    run = {k: (1.0 + 0.1 * (k - 10), 4.5) for k in range(10, 61)}
    run[30] = (5.5, 1.0)  # a jump of several metres and back
    for k in (40, 41):
        run[k] = None
    for k in range(51, 61):
        run[k] = None
    # P2 stands still with 3 cm of jitter.
    jitter = {k: (3.0 + (0.03 if k % 2 else -0.03), 1.5) for k in range(0, FRAMES)}
    doc = document(track=tracks({"P1": run, "P2": jitter}))
    context = _Context(doc)
    rally = doc.rallies[0]
    metres, tracked, rally_s = distance_of(context, "P1", rally)
    assert rally_s == pytest.approx(5.1)
    assert tracked == pytest.approx(4.1)  # samples 10..50
    # 4.0 m run, less 0.05 m smoothed off each end.
    assert metres == pytest.approx(3.9, abs=0.01)
    still, _, _ = distance_of(context, "P2", rally)
    raw = 0.06 * 50
    assert still < raw / 2
    stats = clip_stats(doc)
    distance = player(stats, "P1").distance
    first = distance.per_rally[0]
    assert first.coverage == pytest.approx(0.804, abs=0.001) and first.covered
    # Rally 3 is one sample long: nothing to measure.
    assert distance.rally_m.n == 2 and not distance.per_rally[2].covered
    assert distance.total_m == pytest.approx(3.9, abs=0.1)
    assert distance.per_minute_m is not None
    # A 1 s gap splits the span: its time does not count as tracked.
    gap = dict(run)
    for k in range(20, 31):
        gap[k] = None
    doc = document(track=tracks({"P1": gap}))
    _, tracked, _ = distance_of(_Context(doc), "P1", doc.rallies[0])
    assert tracked == pytest.approx(1.0 + 2.0)


def test_doubles_formation_by_phase():
    stats = clip_stats(document())
    t1, t2 = team(stats, "T1"), team(stats, "T2")
    # T1 stands one behind the other, T2 side by side, throughout.
    assert t1.formation.all.front_back.share == 1.0
    assert t2.formation.all.side_by_side.share == 1.0
    assert t1.formation.attacking.front_back.n > 0
    assert t2.formation.defending.side_by_side.n == t1.formation.attacking.front_back.n
    # Attacking after P4's lift (rally 1, 30..39), P2's smashes (40..49 and
    # 55..60), P3's clear (rally 2, 110..119), P2's smash (120..124) and P4's
    # lift (125..129); defending after P1's long serve (100..109).
    assert t1.formation.attacking.front_back.n == 10 + 10 + 6 + 10 + 5 + 5
    assert t1.formation.defending.front_back.n == 10
    assert t1.formation.seconds == pytest.approx((51 + 41 + 1) / 10)
    singles = clip_stats(two_player_document())
    assert all(t.formation is None for t in singles.teams)


def two_player_document():
    one = Rally(
        id="rally-1",
        start_frame=10,
        end_frame=30,
        start_s=1.0,
        end_s=3.0,
        start_source="first_contact",
        end_source="last_contact",
        shots=[
            Shot(id="shot-10", frame=10, time_s=1.0, kind="shot", hitter_id="P1"),
            Shot(id="shot-30", frame=30, time_s=3.0, kind="shot", hitter_id="P2"),
        ],
    )
    track = Tracks(
        rate_hz=10,
        sample_frames=list(range(FRAMES)),
        persons=[
            PersonTrack(person_id=p, x=[None] * FRAMES, y=[None] * FRAMES)
            for p in ("P1", "P2")
        ],
        shuttle=ShuttleTrack(x=[None] * FRAMES, y=[None] * FRAMES),
    )
    return document("singles", [one], track, views=False, flights=False)


def test_unknowns_stay_null_without_court_flights_or_outcomes():
    stats = clip_stats(two_player_document())
    assert any("No camera view" in w for w in stats.warnings)
    assert any("no speeds" in w for w in stats.warnings)
    p1 = player(stats, "P1")
    assert p1.positions.n == 0 and p1.contacts == [] and p1.landings == []
    assert p1.distance.total_m == 0 and p1.distance.coverage == 0
    assert p1.distance.per_minute_m is None and p1.distance.rally_m.median is None
    assert p1.speeds is None and stats.clip.speeds is None
    assert p1.finish.ended == 0 and p1.finish.winners.share is None
    assert p1.serve.won.share is None and p1.receive.returns == 0
    assert p1.shots.families["unknown"].count == 1
    assert stats.clip.pairs == []  # every label unknown
    assert team(stats, "T1").rallies_won.model_dump() == {
        "count": 0,
        "n": 0,
        "share": None,
    }


def test_speeds_leave_out_bound_and_poor_fits():
    stats = clip_stats(document())
    smash = stats.clip.speeds["smash"]
    assert (smash.shots, smash.fitted, smash.good, smash.speed_bound) == (3, 3, 2, 1)
    assert smash.initial_kmh.n == 2 and smash.initial_kmh.median == 280
    assert smash.initial_kmh.max is None and smash.initial_kmh.p90 is not None
    # The bound fit's speed 0.1 s after contact is still a measurement.
    assert smash.settled_kmh.n == 3
    lift = player(stats, "P4").speeds["lift"]
    assert (lift.shots, lift.good, lift.poor_fit) == (2, 1, 1)
    assert lift.initial_kmh.median == 100
    drive = stats.clip.speeds["drive"]
    assert (drive.shots, drive.fitted) == (1, 0) and drive.initial_kmh.n == 0
    assert sum(drive.initial_kmh.counts) == 0
    hist = smash.initial_kmh
    assert sum(hist.counts) + hist.above + hist.below == hist.n


def test_sequences_skip_unknowns_and_same_team_pairs():
    stats = clip_stats(document())
    pairs = {tuple(p.labels): p.count for p in stats.clip.pairs}
    assert pairs[("lift", "smash")] == 1 and pairs[("clear", "smash")] == 1
    assert pairs[("serve_short", "push")] == 1
    # 125 (P4, lift) -> 130 (unknown hitter, drive) -> 135 (P4, net) count;
    # P4's lift after P2's smash too. No same-team pair occurs here.
    assert pairs[("lift", "drive")] == 1 and pairs[("drive", "net")] == 1
    n = stats.clip.pairs[0].n
    assert n == 5 + 5 == sum(pairs.values())
    triples = {tuple(p.labels): p.count for p in stats.clip.triples}
    assert triples[("lift", "smash", "block")] == 1
    replies = {tuple(r.labels): r.count for r in player(stats, "P2").replies}
    # P2's smashes answered P4's lift, P3's block and P3's clear.
    assert replies == {
        ("lift", "smash"): 1,
        ("block", "smash"): 1,
        ("clear", "smash"): 1,
    }
    # Two consecutive shots by one team are a mistake: left out.
    rally_list = rallies()
    shots = list(rally_list[0].shots)
    shots[2] = shots[2].model_copy(update={"hitter_id": "P2"})
    rally_list[0] = rally_list[0].model_copy(update={"shots": shots})
    pairs = {
        tuple(p.labels) for p in clip_stats(document(rally_list=rally_list)).clip.pairs
    }
    assert ("push", "lift") not in pairs


def test_stats_follow_swap_overrides_in_the_document():
    from test_match_analysis import IDENTITY, fixture

    plain = build_match_analysis(fixture(), IDENTITY)
    swap = {"persons": ["P1", "P2"], "start_frame": 20, "end_frame": 65}
    swapped = build_match_analysis(fixture(), IDENTITY, overrides=[swap])
    before, after = clip_stats(plain), clip_stats(swapped)
    # Contacts 20 (P2 -> P1), 40 (P1 -> P2) and 65 (P2 -> P1) change persons.
    assert player(before, "P1").shots.contacts == 3  # 40, 170, 210
    assert player(after, "P1").shots.contacts == 4  # 20, 65, 170, 210
    assert player(before, "P2").serve.serves == 1  # 20
    assert player(after, "P1").serve.serves == 2  # 20 and 210
    assert player(after, "P2").serve.serves == 0
    assert player(before, "P1").shots.families["net_kill"].count == 1
    assert "net_kill" not in player(after, "P1").shots.families
    assert player(after, "P2").shots.families["net_kill"].count == 1
    # Track samples follow too: the totals stay, the split moves.
    total = sum(player(before, p).positions.n for p in ("P1", "P2"))
    assert total == sum(player(after, p).positions.n for p in ("P1", "P2"))


def test_real_builder_output_without_outcomes():
    from test_match_analysis import IDENTITY, fixture

    stats = clip_stats(build_match_analysis(fixture(), IDENTITY))
    assert stats.mode == "singles" and not stats.shot_flights
    assert stats.clip.outcomes_known.count == 0
    assert all(t.rallies_won.n == 0 for t in stats.teams)
    assert stats.clip.rallies == 3
    p1 = player(stats, "P1")
    # P1 is at the far end before the cut and the near end after it: both
    # turned to the near end.
    assert {round(c.y, 1) for c in p1.contacts} == {11.4, 11.0}
    assert all(0 <= c.x <= COURT_WIDTH_M for c in p1.contacts)


def test_endpoints(tmp_path):
    from badminton import matches as match_flow
    from badminton.api import create_app
    from badminton.match_analysis import write_match_analysis
    from badminton.storage import Store
    from fastapi.testclient import TestClient

    data = tmp_path / "data"
    app = create_app(root=tmp_path, data=data)
    Store(data).register({"id": "v", "mode": "doubles"})
    match_flow.write_record(
        data,
        match_flow.new_record(
            "v", "doubles", {"T1": ["A", "B"], "T2": ["C", "D"]}, "x"
        ),
    )
    with TestClient(app) as client:
        assert client.get("/api/videos/v/match-stats").status_code == 404
        assert client.get("/api/matches/v/stats").status_code == 404
        assert client.get("/api/matches/unknown/stats").status_code == 404
        write_match_analysis(data, document())
        response = client.get("/api/videos/v/match-stats")
        assert response.status_code == 200
        assert ClipStats.model_validate(response.json()) == clip_stats(document())
        assert client.get("/api/matches/v/stats").json() == response.json()
        schema = client.get("/openapi.json").json()["components"]["schemas"]
        assert "ClipStats" in schema and "ShotFlight" in schema
