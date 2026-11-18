"""Persistent person ids from looks, on small synthetic views (no video)."""

import hashlib
import json
import random

import numpy as np
import pytest
from badminton import person_identity as pid
from badminton import pipeline
from badminton.identity import validate_assignments

WIDTH, HEIGHT = 640, 480
# Each person's whole-body colour (BGR) and build; partners differ in both.
LOOKS = {
    "a": ((200, 40, 40), 1.00),
    "b": ((40, 200, 40), 1.12),
    "c": ((40, 40, 200), 0.95),
    "d": ((200, 200, 40), 1.08),
}


def body(x, feet, scale):
    """A standing player: box and a full 17-point pose inside it."""
    height = 120 * scale
    top = feet - height

    def at(dx, share):
        return [x + dx * scale, top + share * height, 1.0]

    points = [at(0, 0.08)] * 5  # face
    points += [at(-8, 0.2), at(8, 0.2)]  # shoulders
    points += [at(-12, 0.35), at(12, 0.35), at(-12, 0.45), at(12, 0.45)]  # arms
    points += [at(-6, 0.5), at(6, 0.5)]  # hips
    points += [at(-6, 0.7), at(6, 0.7)]  # knees
    points += [at(-6, 0.88), at(6, 0.88)]  # ankles
    box = [x - 20 * scale, top, x + 20 * scale, feet]
    return box, points


def synthetic_video(mode, views, frames=24, seed=1):
    """Views with players at both ends; sides change ends every other view
    and partners stand left or right at random. Returns the video, the
    identities run, one player run, and the true person of every chain."""
    rng = random.Random(seed)
    sides = (("a", "b"), ("c", "d")) if mode == "doubles" else (("a",), ("c",))
    tracks, rows, truth = [], [], {}
    for view in range(views):
        start = view * frames
        far, near = sides if view % 2 == 0 else sides[::-1]
        placed = []
        for end, people, feet in (("far", far, 170), ("near", near, 420)):
            people = list(people)
            rng.shuffle(people)
            for place, person in enumerate(people):
                track_id = view * 10 + len(placed)
                continuity = f"view{view}-{person}"
                x = 200 + 240 * place if len(people) == 2 else 320
                placed.append((track_id, person, x, feet))
                truth[(start, continuity)] = person
                tracks.append(
                    {
                        "run_id": "run1",
                        "track_id": track_id,
                        "actor_id": continuity,
                        "continuity_id": continuity,
                        "camera_segment_start_frame": start,
                        "court_end": end,
                        "start_frame": start,
                        "end_frame": start + frames,
                    }
                )
        for frame in range(start, start + frames):
            people = []
            for track_id, person, x, feet in placed:
                box, points = body(x + rng.uniform(-3, 3), feet, LOOKS[person][1])
                people.append(
                    {
                        "track_id": track_id,
                        "box": box,
                        "keypoints": points,
                        "confidence": 0.9,
                        "person": person,
                    }
                )
            rows.append(
                {
                    "frame": frame,
                    "players": people,
                    "calibration_valid": True,
                    "camera_segment_start_frame": start,
                }
            )
    count = views * frames
    video = {"id": "v", "mode": mode, "frame_count": count, "sha256": "0" * 64}
    identity_run = {"tracks": tracks, "start_frame": 0, "end_frame": count}
    player_run = {"start_frame": 0, "end_frame": count, "frames": rows}
    return video, identity_run, player_run, truth


def painter(player_run):
    """Decoded frames: each player's box filled with their colour."""
    rows = {row["frame"]: row for row in player_run["frames"]}

    def decode(frames):
        for frame in frames:
            image = np.full((HEIGHT, WIDTH, 3), 128, np.uint8)
            for person in rows[frame]["players"]:
                x1, y1, x2, y2 = (int(v) for v in person["box"])
                image[max(0, y1) : y2 + 30, x1:x2] = LOOKS[person["person"]][0]
            yield frame, image

    return decode


def describe(crops):
    """A stand-in description: the crop's mean colour, made unit length."""
    vectors = np.array([c.reshape(-1, 3).mean(0) for c in crops], float)
    vectors = np.concatenate([vectors, np.ones((len(crops), 1)) * 50], axis=1)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def run(mode, views=6, tmp_path=None, **kwargs):
    video, identity_run, player_run, truth = synthetic_video(mode, views, **kwargs)
    document = pid.identify_persons(
        video,
        identity_run,
        [("run1", player_run)],
        painter(player_run),
        describe,
        thumbnails_dir=tmp_path,
        thumbnail_prefix="persons/x/",
    )
    return document, identity_run, truth


def chain_labels(document, identity_run):
    chains = pid.chains_of(identity_run)
    found = {}
    for item in document["assignments"]:
        chain, _ = chains[(item["run_id"], item["track_id"])]
        assert found.setdefault(chain, item["player_id"]) == item["player_id"]
    return found


@pytest.mark.parametrize("mode", ["singles", "doubles"])
def test_every_chain_gets_its_true_person_across_end_changes(mode):
    document, identity_run, truth = run(mode)
    found = chain_labels(document, identity_run)
    assert set(found) == set(truth)
    # One label per true person and one person per label: right up to names.
    pairs = {(truth[c], found[c]) for c in truth}
    assert len(pairs) == len({p for p, _ in pairs}) == len({q for _, q in pairs})


def test_doubles_partners_share_a_team_and_teams_follow_the_layout():
    document, identity_run, truth = run("doubles")
    found = chain_labels(document, identity_run)
    team = {p["id"]: p["team"] for p in document["persons"]}
    assert team == {"P1": "T1", "P2": "T1", "P3": "T2", "P4": "T2"}
    side = {c: team[label] for c, label in found.items()}
    for partners in (("a", "b"), ("c", "d")):
        teams = {side[c] for c in truth if truth[c] in partners}
        assert len(teams) == 1
    # T1 is the side at the far end of the first view, P1 its far-left player.
    first = min(c[0] for c in truth)
    far = [t for t in identity_run["tracks"] if t["court_end"] == "far"]
    far = [t for t in far if t["camera_segment_start_frame"] == first]
    assert {found[(first, t["continuity_id"])] for t in far} == {"P1", "P2"}


def test_singles_has_two_people_on_two_teams_and_no_partner_certainty():
    document, identity_run, _ = run("singles")
    assert document["persons"] == [
        {"id": "P1", "team": "T1", "thumbnail": None},
        {"id": "P2", "team": "T2", "thumbnail": None},
    ]
    assert {a["certainty"] for a in document["assignments"]} == {None}
    # P1 is the player at the far end of the first view.
    found = chain_labels(document, identity_run)
    far = next(t for t in identity_run["tracks"] if t["court_end"] == "far")
    assert found[(far["camera_segment_start_frame"], far["continuity_id"])] == "P1"


def test_document_has_the_agreed_shape_and_valid_track_assignments(tmp_path):
    document, identity_run, _ = run("doubles", tmp_path=tmp_path)
    assert set(document) == {
        "schema_version",
        "mode",
        "persons",
        "assignments",
        "provenance",
    }
    assert document["schema_version"] == 1 and document["mode"] == "doubles"
    for person in document["persons"]:
        assert set(person) == {"id", "team", "thumbnail"}
        assert person["thumbnail"] == f"persons/x/{person['id']}.jpg"
        assert (tmp_path / f"{person['id']}.jpg").stat().st_size > 0
    for item in document["assignments"]:
        assert set(item) == {
            "run_id",
            "track_id",
            "start_frame",
            "end_frame",
            "player_id",
            "certainty",
        }
        assert 0 <= item["certainty"] <= 1
    plain = [
        {k: v for k, v in a.items() if k != "certainty"}
        for a in document["assignments"]
    ]
    assert validate_assignments(plain, frame_count=identity_run["end_frame"])
    summary = document["provenance"]["summary"]
    assert summary["views"] == summary["views_all_named"] == 6
    assert summary["player_track_frames"] == summary["player_track_frames_named"]
    assert json.loads(json.dumps(document)) == document


def test_short_lived_extra_tracks_and_one_ended_views_get_no_person():
    video, identity_run, player_run, _ = synthetic_video("singles", 4)
    # An official tracked briefly at the far end of the first view.
    player_run["frames"][0]["players"].append(
        {
            "track_id": 99,
            "box": [10, 50, 40, 170],
            "keypoints": [],
            "confidence": 0.9,
            "person": "a",
        }
    )
    identity_run["tracks"].append(
        {
            "run_id": "run1",
            "track_id": 99,
            "actor_id": "official",
            "continuity_id": "official",
            "camera_segment_start_frame": 0,
            "court_end": "far",
            "start_frame": 0,
            "end_frame": 1,
        }
    )
    # A view where only the near player was tracked.
    lone = player_run["frames"][-24:]
    for row in lone:
        row["players"] = [p for p in row["players"] if p["box"][3] > 300]
    document = pid.identify_persons(
        video, identity_run, [("run1", player_run)], painter(player_run), describe
    )
    found = chain_labels(document, identity_run)
    assert (0, "official") not in found
    assert not any(chain[0] == 72 for chain in found)
    assert document["provenance"]["summary"]["views"] == 3


def test_rows_outside_core_range_or_live_play_are_not_used():
    _, identity_run, player_run, _ = synthetic_video("singles", 2)
    player_run["analysis_core_start_frame"] = 4
    player_run["analysis_core_end_frame"] = 40
    player_run["frames"][10]["scene"] = "replay"
    player_run["frames"][11]["calibration_valid"] = False
    rows = pid.player_rows(identity_run, [("run1", player_run)])
    assert min(rows) == 4 and max(rows) == 39
    assert 10 not in rows and 11 not in rows and len(rows) == 34


@pytest.mark.parametrize("mode", ["singles", "doubles"])
def test_a_brief_new_tracker_id_inside_a_players_track_gets_the_same_person(mode):
    # The tracker gives one player a new ID for a few frames, then the old ID
    # again; actor linking joins both into one chain (DShuttleNet match 52).
    video, identity_run, player_run, _ = synthetic_video(mode, 4)
    long = identity_run["tracks"][0]
    for row in player_run["frames"][8:12]:
        for person in row["players"]:
            if person["track_id"] == long["track_id"]:
                person["track_id"] = 77
    identity_run["tracks"].append(
        long | {"track_id": 77, "start_frame": 8, "end_frame": 12}
    )
    document = pid.identify_persons(
        video, identity_run, [("run1", player_run)], painter(player_run), describe
    )
    mine = [
        a for a in document["assignments"] if a["track_id"] in (long["track_id"], 77)
    ]
    assert {a["player_id"] for a in mine} == {mine[0]["player_id"]}
    assert sorted((a["track_id"], a["start_frame"], a["end_frame"]) for a in mine) == [
        (long["track_id"], 0, 8),
        (long["track_id"], 12, 24),
        (77, 8, 12),
    ]
    plain = [
        {k: v for k, v in a.items() if k != "certainty"}
        for a in document["assignments"]
    ]
    assert validate_assignments(plain, frame_count=identity_run["end_frame"])


def test_without_overlaps_cuts_only_the_same_persons_tracks_of_one_run():
    def item(run, track, start, end, person):
        return {
            "run_id": run,
            "track_id": track,
            "start_frame": start,
            "end_frame": end,
            "player_id": person,
        }

    kept = [item("r1", 1, 0, 50, "P1"), item("r1", 2, 0, 50, "P2")]
    kept.append(item("r2", 3, 20, 30, "P1"))
    assert sorted(map(str, pid.without_overlaps(kept))) == sorted(map(str, kept))
    cut = pid.without_overlaps(
        [item("r1", 1, 0, 50, "P1"), item("r1", 2, 40, 60, "P1")]
    )
    assert sorted((a["track_id"], a["start_frame"], a["end_frame"]) for a in cut) == [
        (1, 0, 40),
        (2, 40, 60),
    ]


def test_grouping_needs_no_video_when_no_view_has_both_ends():
    video, identity_run, player_run, _ = synthetic_video("doubles", 2)
    for row in player_run["frames"]:
        row["players"] = [p for p in row["players"] if p["box"][3] > 300]

    def nothing(frames):
        assert frames == []
        return iter(())

    prepared = []
    document = pid.identify_persons(
        video,
        identity_run,
        [("run1", player_run)],
        nothing,
        describe,
        prepare=lambda: prepared.append(True),
    )
    assert document["assignments"] == [] and prepared == []
    assert [p["id"] for p in document["persons"]] == ["P1", "P2", "P3", "P4"]


def test_split_two_and_agree_order_noisy_pairs_consistently():
    rng = np.random.default_rng(0)
    flips = rng.random(30) < 0.5
    pairs = []
    for flip in flips:
        one = np.array([1.0, 0, 0]) + rng.normal(0, 0.1, 3)
        two = np.array([0, 1.0, 0]) + rng.normal(0, 0.1, 3)
        pairs.append((two, one) if flip else (one, two))
    signs, _ = pid.split_two(pairs)
    assert len({s * (-1 if f else 1) for s, f in zip(signs, flips)}) == 1
    signs, support = pid.agree(pairs, pairs)
    assert len({s * (-1 if f else 1) for s, f in zip(signs, flips)}) == 1
    assert ((support > 0) & (support <= 1 + 1e-9)).all()


def test_load_document_rejects_a_changed_document(tmp_path):
    folder = tmp_path / "v" / "persons" / "r1"
    folder.mkdir(parents=True)
    (folder / "persons.json").write_text('{"schema_version": 1}', encoding="utf-8")
    record = {
        "document": "persons/r1/persons.json",
        "document_sha256": hashlib.sha256(b'{"schema_version": 1}').hexdigest(),
    }
    runs = tmp_path / "v" / "runs"
    runs.mkdir()
    (runs / "r1.json").write_text(json.dumps(record), encoding="utf-8")
    checkpoint = {
        "run_id": "r1",
        "sha256": hashlib.sha256((runs / "r1.json").read_bytes()).hexdigest(),
    }
    assert pid.load_document(tmp_path, "v", checkpoint) == {"schema_version": 1}
    (folder / "persons.json").write_text('{"schema_version": 2}', encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        pid.load_document(tmp_path, "v", checkpoint)


# Cache keys --------------------------------------------------------------------


def recipe(**changes):
    files = {
        "person_identity.py": "p",
        "identity.py": "i",
        "config.py": "c",
        "osnet.py": "o",
        "video.py": "v",
        "av_runtime.py": "a",
        "file_cache.py": "f",
        "orientation.py": "r",
        "tracking.py": "t",
        "api.py": "x",
        "model_manifest.json": "m",
        "static/build-manifest.json": "s",
    }
    files.update(changes)
    return {
        "method": pipeline.METHOD,
        "video": {"id": "v"},
        "settings": {"player_model": "small", "auto_calibrate": True},
        "context_signature": {"court": []},
        "local_side_files": {},
        "event_model_sha256": "e",
        "source_files": files,
    }


def persons_key(base, manifest=None, monkeypatch=None):
    if manifest is not None:
        monkeypatch.setattr(pipeline, "MODEL_MANIFEST", manifest)
    return pipeline.digest(pipeline.stage_recipe(base, "persons", None, {"x": 1}))


def test_persons_key_follows_only_its_own_code_and_weights(tmp_path, monkeypatch):
    manifest = tmp_path / "model_manifest.json"
    entry = {"name": "reid/w.pth", "sha256": "1" * 64}
    manifest.write_text(json.dumps({pid.MANIFEST_KEY: entry}), encoding="utf-8")
    key = persons_key(recipe(), manifest, monkeypatch)
    # Unrelated code, the event model, recognition settings, a frontend build.
    for unrelated in (
        recipe(**{"api.py": "changed"}),
        recipe(**{"static/build-manifest.json": "changed"}),
        recipe() | {"event_model_sha256": "other"},
        recipe() | {"settings": {"recognize": False}},
    ):
        assert persons_key(unrelated) == key
    # Its own code, the code it imports, and the camera/scene/court context.
    for related in (
        recipe(**{"person_identity.py": "changed"}),
        recipe(**{"osnet.py": "changed"}),
        recipe(**{"video.py": "changed"}),
        recipe() | {"context_signature": {"court": [1]}},
    ):
        assert persons_key(related) != key
    assert (
        pipeline.digest(pipeline.stage_recipe(recipe(), "persons", None, {"x": 2}))
        != key
    )
    # New weights in the manifest.
    manifest.write_text(
        json.dumps({pid.MANIFEST_KEY: entry | {"sha256": "2" * 64}}), encoding="utf-8"
    )
    assert persons_key(recipe()) != key


def test_registering_later_weights_keeps_perception_keys(tmp_path, monkeypatch):
    manifest = tmp_path / "model_manifest.json"
    models = {"player_pose": {"name": "p.pt", "sha256": "3" * 64}}
    manifest.write_bytes((json.dumps(models, indent=2) + "\n").encode())
    monkeypatch.setattr(pipeline, "MODEL_MANIFEST", manifest)
    base = recipe(**{"model_manifest.json": pipeline.file_sha(manifest)})
    before = {
        name: pipeline.digest(pipeline.stage_recipe(base, name, {"index": 0}, {}))
        for name in ("players", "shuttle", "segments")
    }
    models[pid.MANIFEST_KEY] = {"name": "reid/w.pth", "sha256": "1" * 64}
    manifest.write_bytes((json.dumps(models, indent=2) + "\n").encode())
    after_base = recipe(**{"model_manifest.json": pipeline.file_sha(manifest)})
    assert (
        pipeline.perception_manifest_sha()
        == base["source_files"]["model_manifest.json"]
    )
    for name, key in before.items():
        assert (
            pipeline.digest(pipeline.stage_recipe(after_base, name, {"index": 0}, {}))
            == key
        )
    # A change to a perception model's entry still reaches perception.
    models["player_pose"]["sha256"] = "4" * 64
    manifest.write_bytes((json.dumps(models, indent=2) + "\n").encode())
    changed = recipe(**{"model_manifest.json": pipeline.file_sha(manifest)})
    assert (
        pipeline.digest(pipeline.stage_recipe(changed, "players", {"index": 0}, {}))
        != before["players"]
    )


def test_manifest_registers_the_installed_identity_weights():
    entry = pid.manifest_entry()
    assert entry["name"] == "reid/osnet_doubles_ft1.pth"
    assert len(entry["sha256"]) == 64 and "non-commercial" in entry["terms"]
    path = pid.WEIGHTS / entry["name"]
    if path.is_file():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]


def test_identical_inputs_give_identical_documents():
    first, _, _ = run("doubles", seed=3)
    second, _, _ = run("doubles", seed=3)
    for document in (first, second):
        document["provenance"]["summary"].pop("elapsed_s")
    assert first == second
    labels = {a["player_id"] for a in first["assignments"]}
    assert labels == {"P1", "P2", "P3", "P4"}
